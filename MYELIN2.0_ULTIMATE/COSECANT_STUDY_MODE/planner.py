"""The single Study Planner authority for MYELIN.

The planner owns future Study blocks.  It validates local civil time,
recurrence, DST fold selection, conflicts and one-use timer preparation.

It deliberately does not start Study Mode, begin a break, draw planner widgets,
or write persistence rows.  A coordinator may consume a preparation and call
``StudyRuntime.prepare``; the user must still press Start separately.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PLANNER_SCHEMA_VERSION: Final = "myelin-study-planner-v1"

#: The one Planner collection this version of MYELIN keeps.
#:
#: Durable planner rows are keyed ``(plan_id, block_id)``.  A plan_id that was
#: minted freshly on every launch would key yesterday's rows under an identity
#: no later run could name, so the user's plans would persist but never
#: reopen.  A stable named constant makes the collection findable across
#: restarts without inventing a schema or a second Planner runtime.
#:
#: It is deliberately a fixed name and not derived from subject text, task
#: text, note content, browser facts or a per-launch timestamp: an identity
#: computed from content would change whenever the content changed.
DEFAULT_PLAN_ID: Final = "MYELIN-STUDY-PLANNER-V1"
MAX_PROJECTION_DAYS: Final = 366
MAX_OCCURRENCES: Final = 366
MAX_PENDING_PREPARATIONS: Final = 32
MINIMUM_STUDY_MINUTES: Final = 1
MAXIMUM_STUDY_MINUTES: Final = 24 * 60
MINIMUM_BREAK_MINUTES: Final = 1
MAXIMUM_BREAK_MINUTES: Final = 24 * 60


class PlanStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    INTERRUPTED = "INTERRUPTED"


class PlanPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class RecurrenceKind(str, Enum):
    NONE = "NONE"
    DAILY = "DAILY"
    WEEKDAYS = "WEEKDAYS"
    WEEKLY = "WEEKLY"
    CUSTOM_WEEKDAYS = "CUSTOM_WEEKDAYS"


class DstStatus(str, Enum):
    NORMAL = "NORMAL"
    AMBIGUOUS = "AMBIGUOUS"
    NONEXISTENT = "NONEXISTENT"


class PlannerWarningKind(str, Enum):
    CONFLICT = "CONFLICT"
    DST_AMBIGUOUS = "DST_AMBIGUOUS"
    DST_NONEXISTENT = "DST_NONEXISTENT"


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """A bounded recurrence expressed in the block's local timezone."""

    kind: RecurrenceKind = RecurrenceKind.NONE
    weekdays: tuple[int, ...] = ()
    end_date: str = ""
    occurrence_count: int | None = None
    exception_dates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RecurrenceKind):
            raise TypeError("kind must be a RecurrenceKind")
        weekdays = tuple(sorted(set(self.weekdays)))
        if any(type(day) is not int or not 0 <= day <= 6 for day in weekdays):
            raise ValueError("weekdays must contain unique values from 0 to 6")
        if self.kind is RecurrenceKind.WEEKDAYS:
            weekdays = (0, 1, 2, 3, 4)
        elif self.kind is RecurrenceKind.CUSTOM_WEEKDAYS and not weekdays:
            raise ValueError("CUSTOM_WEEKDAYS requires at least one weekday")
        elif self.kind not in {
            RecurrenceKind.WEEKDAYS,
            RecurrenceKind.CUSTOM_WEEKDAYS,
        } and weekdays:
            raise ValueError("weekdays are valid only for weekday recurrence")
        if self.end_date:
            _parse_date(self.end_date, "end_date")
        if self.occurrence_count is not None:
            if type(self.occurrence_count) is not int or self.occurrence_count <= 0:
                raise ValueError("occurrence_count must be a positive integer")
            if self.occurrence_count > MAX_OCCURRENCES:
                raise ValueError("occurrence_count exceeds the planner limit")
        exceptions = tuple(sorted(set(self.exception_dates)))
        for value in exceptions:
            _parse_date(value, "exception date")
        object.__setattr__(self, "weekdays", weekdays)
        object.__setattr__(self, "exception_dates", exceptions)


@dataclass(frozen=True, slots=True)
class PlanBlock:
    """One validated local-time Study plan block."""

    block_id: str
    subject: str
    task: str
    local_date: str
    local_hour: int
    local_minute: int
    timezone_id: str
    dst_fold: int
    study_minutes: int
    break_minutes: int
    recurrence: RecurrenceRule
    priority: PlanPriority
    status: PlanStatus
    version: int
    notes: str = ""
    schema_version: str = PLANNER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not str(self.block_id).strip():
            raise ValueError("block_id cannot be empty")
        subject = " ".join(str(self.subject).split())
        task = " ".join(str(self.task).split())
        if not subject or not task:
            raise ValueError("subject and task are required")
        _parse_date(self.local_date, "local_date")
        _validate_clock(self.local_hour, self.local_minute, self.dst_fold)
        _zone(self.timezone_id)
        _validate_minutes(
            self.study_minutes,
            "study_minutes",
            MINIMUM_STUDY_MINUTES,
            MAXIMUM_STUDY_MINUTES,
        )
        _validate_minutes(
            self.break_minutes,
            "break_minutes",
            MINIMUM_BREAK_MINUTES,
            MAXIMUM_BREAK_MINUTES,
        )
        if not isinstance(self.recurrence, RecurrenceRule):
            raise TypeError("recurrence must be a RecurrenceRule")
        if not isinstance(self.priority, PlanPriority):
            raise TypeError("priority must be a PlanPriority")
        if not isinstance(self.status, PlanStatus):
            raise TypeError("status must be a PlanStatus")
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("version must be a positive integer")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "timezone_id", str(self.timezone_id).strip())
        object.__setattr__(self, "notes", str(self.notes).strip())


@dataclass(frozen=True, slots=True)
class PlanOccurrence:
    """One virtual occurrence; projection never starts a timer."""

    occurrence_key: str
    block_id: str
    block_version: int
    subject: str
    task: str
    local_date: str
    local_hour: int
    local_minute: int
    timezone_id: str
    dst_fold: int
    dst_status: DstStatus
    scheduled_start_utc: str
    study_minutes: int
    break_minutes: int
    priority: PlanPriority
    status: PlanStatus

    @property
    def total_reserved_minutes(self) -> int:
        return self.study_minutes + self.break_minutes


@dataclass(frozen=True, slots=True)
class PlannerWarning:
    kind: PlannerWarningKind
    message: str
    first_occurrence_key: str
    second_occurrence_key: str = ""
    overlap_minutes: int = 0


@dataclass(frozen=True, slots=True)
class PlannerProjection:
    occurrences: tuple[PlanOccurrence, ...]
    warnings: tuple[PlannerWarning, ...]


@dataclass(frozen=True, slots=True)
class CosecantTimerPreparation:
    """One-use facts for timer configuration; this is not a Start command."""

    token: str
    block_id: str
    block_version: int
    occurrence_key: str
    subject: str
    task: str
    study_seconds: int
    selected_break_seconds: int
    scheduled_start_utc: str
    timezone_id: str
    dst_fold: int
    schema_version: str = PLANNER_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class PreparationResult:
    accepted: bool
    reason: str
    preparation: CosecantTimerPreparation | None


class StudyPlanner:
    """Thread-safe in-memory authority for current planner truth.

    Persistence may save and restore ``PlanBlock`` values, but it must not
    reinterpret recurrence or timer preparation.
    """

    def __init__(self, *, plan_id: str = "", repository: object | None = None) -> None:
        self._lock = threading.RLock()
        self._blocks: dict[str, PlanBlock] = {}
        self._pending: dict[str, CosecantTimerPreparation] = {}
        # Optional durable backing.  When present, every mutation commits
        # BEFORE it becomes planner truth (see ``_commit``).  When absent the
        # planner is a pure in-memory authority, exactly as before.
        self._repository = repository
        # One stable collection identity for this planner.  Durable rows are
        # keyed (plan_id, block_id), which is exactly what planner_blocks
        # already uses, and it is what a Note's linked_plan_id refers to.  It
        # is deliberately NOT a second Study runtime: a plan_id names a
        # collection of future intentions and nothing that is running.
        #
        # The default is a fixed name, not a fresh random token: a planner
        # rebuilt on the next launch must be able to reopen the rows the last
        # one stored.  An explicit plan_id still overrides it.
        self._plan_id = str(plan_id).strip() or DEFAULT_PLAN_ID

    @property
    def plan_id(self) -> str:
        """This planner collection's stable durable identity."""

        return self._plan_id

    def add_block(
        self,
        *,
        subject: str,
        task: str,
        local_date: str,
        local_hour: int,
        local_minute: int,
        timezone_id: str,
        dst_fold: int,
        study_minutes: int,
        break_minutes: int,
        recurrence: RecurrenceRule = RecurrenceRule(),
        priority: PlanPriority = PlanPriority.NORMAL,
        notes: str = "",
        block_id: str = "",
    ) -> PlanBlock:
        """Validate and store one new block without scheduling side effects."""

        candidate = PlanBlock(
            block_id=str(block_id).strip() or secrets.token_hex(12),
            subject=subject,
            task=task,
            local_date=local_date,
            local_hour=local_hour,
            local_minute=local_minute,
            timezone_id=timezone_id,
            dst_fold=dst_fold,
            study_minutes=study_minutes,
            break_minutes=break_minutes,
            recurrence=recurrence,
            priority=priority,
            status=PlanStatus.PLANNED,
            version=1,
            notes=notes,
        )
        # Base blocks cannot be saved at a wall time that never occurs.
        status, _ = resolve_local_start(candidate)
        if status is DstStatus.NONEXISTENT:
            raise ValueError("The selected local time does not exist because of DST")
        with self._lock:
            if candidate.block_id in self._blocks:
                raise ValueError("block_id is already in use")
            self._commit(candidate, expected_version=0)
            self._blocks[candidate.block_id] = candidate
            return candidate

    def replace_block(self, block: PlanBlock) -> PlanBlock:
        """Replace one block with optimistic version checking."""

        if not isinstance(block, PlanBlock):
            raise TypeError("block must be a PlanBlock")
        status, _ = resolve_local_start(block)
        if status is DstStatus.NONEXISTENT:
            raise ValueError("The selected local time does not exist because of DST")
        with self._lock:
            current = self._blocks.get(block.block_id)
            if current is None:
                raise ValueError("planner block was not found")
            if block.version != current.version:
                raise ValueError("planner block changed; reload before editing")
            updated = replace(block, version=block.version + 1)
            self._commit(updated, expected_version=current.version)
            self._blocks[block.block_id] = updated
            self._drop_pending_for(block.block_id)
            return updated

    def set_status(
        self,
        block_id: str,
        status: PlanStatus,
        *,
        expected_version: int,
    ) -> PlanBlock:
        """Change one block's status, refusing a stale caller's intent.

        ``replace_block`` has always compared versions; these two destructive
        operations did not, so a planner row the user was looking at minutes
        ago could restatus or delete whatever now holds that block_id.  The
        block ID alone is not identity -- identity is (block_id, version).
        """

        if not isinstance(status, PlanStatus):
            raise TypeError("status must be a PlanStatus")
        with self._lock:
            current = self._require_block(block_id)
            self._require_version(current, expected_version)
            updated = replace(current, status=status, version=current.version + 1)
            self._commit(updated, expected_version=current.version)
            self._blocks[current.block_id] = updated
            self._drop_pending_for(current.block_id)
            return updated

    def remove_block(self, block_id: str, *, expected_version: int) -> bool:
        """Delete one block, refusing a stale caller's intent."""

        with self._lock:
            current = self._require_block(block_id)
            self._require_version(current, expected_version)
            if current.status is PlanStatus.ACTIVE:
                raise ValueError("an active planner block cannot be removed")
            self._commit_removal(current)
            del self._blocks[current.block_id]
            self._drop_pending_for(current.block_id)
            return True

    # -- durability before publication ------------------------------------
    #
    # Required ordering for every mutation:
    #
    #     validate candidate -> expected-version check -> DURABLE COMMIT
    #     -> recheck -> publish to planner truth
    #
    # The commit happens while the planner lock is held and BEFORE
    # ``self._blocks`` is touched, so a persistence failure raises and the
    # in-memory authority never advances past durable truth.  The old order --
    # mutate memory, then try to save -- could leave the visible plan claiming
    # something the database never accepted.

    def _commit(self, block: PlanBlock, *, expected_version: int) -> None:
        """Durably store one block before it becomes planner truth.

        Raises whatever the repository raises.  Callers must not catch it: the
        exception IS the refusal, and letting it propagate is what keeps the
        in-memory state behind rather than ahead of the database.
        """

        if self._repository is None:
            return
        self._repository.save_planner_block(
            plan_id=self._plan_id,
            block=block,
            expected_version=expected_version,
        )
        # Recheck: the durable write is the authority on what happened, so
        # confirm the row we just committed is the one now stored before this
        # planner publishes it.
        stored = self._durable_block(block.block_id)
        if stored is None or stored.version != block.version:
            raise RuntimeError(
                "planner commit did not produce the expected durable version; "
                "refusing to publish planner state ahead of durable truth"
            )

    def _commit_removal(self, block: PlanBlock) -> None:
        """Durably archive one block before it leaves planner truth."""

        if self._repository is None:
            return
        self._repository.archive_planner_block(
            plan_id=self._plan_id,
            block_id=block.block_id,
            expected_version=block.version,
        )

    def _durable_block(self, block_id: str) -> PlanBlock | None:
        if self._repository is None:
            return None
        for stored in self._repository.list_planner_blocks(plan_id=self._plan_id):
            if stored.block_id == block_id:
                return stored
        return None

    def load_persisted(self) -> tuple[PlanBlock, ...]:
        """Rehydrate this collection from durable truth.

        The restart path: a planner rebuilt on the next launch names the same
        collection (see ``DEFAULT_PLAN_ID``) and reloads the rows the previous
        run stored.  Loading replaces in-memory state wholesale -- durable
        truth wins -- and drops any pending preparation, which belonged to the
        superseded state.
        """

        if self._repository is None:
            return ()
        stored = tuple(self._repository.list_planner_blocks(plan_id=self._plan_id))
        with self._lock:
            self._blocks = {block.block_id: block for block in stored}
            self._pending.clear()
            return self.blocks()

    @staticmethod
    def _require_version(current: PlanBlock, expected_version: int) -> None:
        """Refuse a mutation aimed at a version that is no longer current."""

        if type(expected_version) is not int:
            raise TypeError("expected_version must be an integer")
        if expected_version != current.version:
            raise ValueError("planner block changed; reload before editing")

    def block(self, block_id: str) -> PlanBlock:
        with self._lock:
            return self._require_block(block_id)

    def blocks(self) -> tuple[PlanBlock, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._blocks.values(),
                    key=lambda item: (
                        item.local_date,
                        item.local_hour,
                        item.local_minute,
                        item.block_id,
                    ),
                )
            )

    def project(self, *, date_from: str, date_to: str) -> PlannerProjection:
        """Expand every block and return DST plus overlap warnings."""

        start = _parse_date(date_from, "date_from")
        end = _parse_date(date_to, "date_to")
        if end < start or (end - start).days >= MAX_PROJECTION_DAYS:
            raise ValueError("planner projection must cover 1 to 366 days")
        with self._lock:
            blocks = tuple(self._blocks.values())

        occurrences: list[PlanOccurrence] = []
        warnings: list[PlannerWarning] = []
        for block in blocks:
            block_occurrences, block_warnings = _expand_block(block, start, end)
            occurrences.extend(block_occurrences)
            warnings.extend(block_warnings)
            if len(occurrences) > MAX_OCCURRENCES:
                raise ValueError("planner projection exceeds 366 occurrences")

        ordered = tuple(
            sorted(
                occurrences,
                key=lambda item: (item.scheduled_start_utc, item.occurrence_key),
            )
        )
        warnings.extend(_conflict_warnings(ordered))
        return PlannerProjection(ordered, tuple(warnings))

    def prepare_cosecant_timer(
        self,
        occurrence: PlanOccurrence,
    ) -> PreparationResult:
        """Create a one-use configuration token without starting anything."""

        if not isinstance(occurrence, PlanOccurrence):
            raise TypeError("occurrence must be a PlanOccurrence")
        with self._lock:
            current = self._blocks.get(occurrence.block_id)
            if current is None:
                return PreparationResult(False, "planner_block_missing", None)
            if current.version != occurrence.block_version:
                return PreparationResult(False, "planner_block_changed", None)
            if current.status not in {PlanStatus.PLANNED, PlanStatus.READY}:
                return PreparationResult(False, "planner_block_not_ready", None)
            if len(self._pending) >= MAX_PENDING_PREPARATIONS:
                return PreparationResult(False, "too_many_pending_preparations", None)

            # A valid block identity is NOT a valid occurrence identity.  The
            # caller's projection is a copy that may have been edited, so it is
            # treated as a REQUEST naming an occurrence, never as a source of
            # scheduling fact.  Planner re-derives the occurrence from its own
            # current block and recurrence rule and requires an exact match.
            canonical = self._canonical_occurrence(current, occurrence.occurrence_key)
            if canonical is None:
                return PreparationResult(False, "planner_occurrence_unknown", None)
            if canonical != occurrence:
                return PreparationResult(False, "planner_occurrence_changed", None)

            token = secrets.token_urlsafe(24)
            # Every field below comes from the block or the re-derived
            # occurrence.  Nothing is copied from the caller's object.
            preparation = CosecantTimerPreparation(
                token=token,
                block_id=current.block_id,
                block_version=current.version,
                occurrence_key=canonical.occurrence_key,
                subject=current.subject,
                task=current.task,
                study_seconds=current.study_minutes * 60,
                selected_break_seconds=current.break_minutes * 60,
                scheduled_start_utc=canonical.scheduled_start_utc,
                timezone_id=current.timezone_id,
                dst_fold=canonical.dst_fold,
            )
            self._pending[token] = preparation
            return PreparationResult(True, "timer_ready_not_started", preparation)

    def _canonical_occurrence(
        self,
        block: PlanBlock,
        occurrence_key: str,
    ) -> PlanOccurrence | None:
        """Re-project one occurrence from current Planner authority.

        The key carries the day, so the projection window is that single day.
        Expanding through ``_expand_block`` rather than calling ``_occurrence``
        directly is deliberate: it reuses the real recurrence rule, the end
        date, the occurrence count and the exception dates, so a day the rule
        never produces yields nothing here instead of being manufactured.
        """

        key = str(occurrence_key)
        if not key:
            return None
        if block.recurrence.kind is RecurrenceKind.NONE:
            if key != block.block_id:
                return None
            day_text = block.local_date
        else:
            prefix = f"{block.block_id}@"
            if not key.startswith(prefix):
                return None
            day_text = key[len(prefix):]
        try:
            day = _parse_date(day_text, "occurrence_key")
        except ValueError:
            return None
        occurrences, _warnings = _expand_block(block, day, day)
        for candidate in occurrences:
            if candidate.occurrence_key == key:
                return candidate
        return None

    def consume_preparation(
        self,
        preparation: CosecantTimerPreparation,
    ) -> PreparationResult:
        """Consume once and recheck the source block immediately before use."""

        if not isinstance(preparation, CosecantTimerPreparation):
            raise TypeError("preparation must be a CosecantTimerPreparation")
        with self._lock:
            pending = self._pending.pop(preparation.token, None)
            if pending != preparation:
                return PreparationResult(False, "preparation_expired", None)
            current = self._blocks.get(preparation.block_id)
            if current is None or current.version != preparation.block_version:
                return PreparationResult(False, "planner_block_changed", None)
            if current.status not in {PlanStatus.PLANNED, PlanStatus.READY}:
                return PreparationResult(False, "planner_block_not_ready", None)
            return PreparationResult(True, "timer_ready_not_started", preparation)

    def cancel_preparation(self, token: str) -> bool:
        with self._lock:
            return self._pending.pop(str(token), None) is not None

    def _require_block(self, block_id: str) -> PlanBlock:
        block = self._blocks.get(str(block_id))
        if block is None:
            raise ValueError("planner block was not found")
        return block

    def _drop_pending_for(self, block_id: str) -> None:
        stale = [
            token
            for token, preparation in self._pending.items()
            if preparation.block_id == block_id
        ]
        for token in stale:
            self._pending.pop(token, None)


def plan_block_payload(block: PlanBlock) -> str:
    """Serialise one block for durable storage.

    Planner owns its own shape.  Storage keeps the row and the key; it never
    interprets recurrence, DST fold or civil time, so the payload round-trips
    through this pair rather than through columns storage would have to reason
    about.
    """

    if not isinstance(block, PlanBlock):
        raise TypeError("block must be a PlanBlock")
    rule = block.recurrence
    return json.dumps(
        {
            "schema_version": block.schema_version,
            "block_id": block.block_id,
            "subject": block.subject,
            "task": block.task,
            "local_date": block.local_date,
            "local_hour": block.local_hour,
            "local_minute": block.local_minute,
            "timezone_id": block.timezone_id,
            "dst_fold": block.dst_fold,
            "study_minutes": block.study_minutes,
            "break_minutes": block.break_minutes,
            "priority": block.priority.value,
            "status": block.status.value,
            "version": block.version,
            "notes": block.notes,
            "recurrence": {
                "kind": rule.kind.value,
                "weekdays": list(rule.weekdays),
                "end_date": rule.end_date,
                "occurrence_count": rule.occurrence_count,
                "exception_dates": list(rule.exception_dates),
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def plan_block_from_payload(source: str) -> PlanBlock:
    """Rebuild one block from storage, revalidating every field.

    The stored row is re-validated by ``PlanBlock.__post_init__`` exactly like
    a freshly entered block, so a corrupted or hand-edited row fails loudly
    instead of becoming planner truth.
    """

    data = json.loads(source)
    if not isinstance(data, dict):
        raise ValueError("planner payload must be a JSON object")
    if str(data.get("schema_version")) != PLANNER_SCHEMA_VERSION:
        raise ValueError("planner payload schema version is unsupported")
    rule_data = data.get("recurrence") or {}
    rule = RecurrenceRule(
        kind=RecurrenceKind(str(rule_data.get("kind", RecurrenceKind.NONE.value))),
        weekdays=tuple(int(day) for day in rule_data.get("weekdays", ())),
        end_date=str(rule_data.get("end_date") or ""),
        occurrence_count=rule_data.get("occurrence_count"),
        exception_dates=tuple(
            str(item) for item in rule_data.get("exception_dates", ())
        ),
    )
    return PlanBlock(
        block_id=str(data["block_id"]),
        subject=str(data["subject"]),
        task=str(data["task"]),
        local_date=str(data["local_date"]),
        local_hour=int(data["local_hour"]),
        local_minute=int(data["local_minute"]),
        timezone_id=str(data["timezone_id"]),
        dst_fold=int(data["dst_fold"]),
        study_minutes=int(data["study_minutes"]),
        break_minutes=int(data["break_minutes"]),
        recurrence=rule,
        priority=PlanPriority(str(data["priority"])),
        status=PlanStatus(str(data["status"])),
        version=int(data["version"]),
        notes=str(data.get("notes", "")),
    )


def timezone_available(timezone_id: str) -> bool:
    try:
        _zone(timezone_id)
    except ValueError:
        return False
    return True


def inspect_local_time(
    *,
    local_date: str,
    local_hour: int,
    local_minute: int,
    timezone_id: str,
) -> DstStatus:
    """Report whether a local wall time is normal, repeated or nonexistent."""

    day = _parse_date(local_date, "local_date")
    _validate_clock(local_hour, local_minute, 0)
    zone = _zone(timezone_id)
    naive = datetime.combine(day, time(local_hour, local_minute))
    valid0 = _round_trip_matches(naive, zone, 0)
    valid1 = _round_trip_matches(naive, zone, 1)
    if not valid0 and not valid1:
        return DstStatus.NONEXISTENT
    offset0 = naive.replace(tzinfo=zone, fold=0).utcoffset()
    offset1 = naive.replace(tzinfo=zone, fold=1).utcoffset()
    if valid0 and valid1 and offset0 != offset1:
        return DstStatus.AMBIGUOUS
    return DstStatus.NORMAL


def resolve_local_start(block: PlanBlock) -> tuple[DstStatus, str]:
    """Resolve one block start to canonical UTC without silent DST shifting."""

    status = inspect_local_time(
        local_date=block.local_date,
        local_hour=block.local_hour,
        local_minute=block.local_minute,
        timezone_id=block.timezone_id,
    )
    if status is DstStatus.NONEXISTENT:
        return status, ""
    if status is DstStatus.NORMAL and block.dst_fold != 0:
        raise ValueError("dst_fold must be 0 when the local time is not repeated")
    zone = _zone(block.timezone_id)
    day = _parse_date(block.local_date, "local_date")
    local = datetime(
        day.year,
        day.month,
        day.day,
        block.local_hour,
        block.local_minute,
        tzinfo=zone,
        fold=block.dst_fold,
    )
    return status, _utc_text(local.astimezone(timezone.utc))


def _expand_block(
    block: PlanBlock,
    start: date,
    end: date,
) -> tuple[list[PlanOccurrence], list[PlannerWarning]]:
    base = _parse_date(block.local_date, "local_date")
    rule = block.recurrence
    effective_start = max(start, base)
    effective_end = end
    if rule.end_date:
        effective_end = min(effective_end, _parse_date(rule.end_date, "end_date"))
    if effective_end < effective_start:
        return [], []

    occurrences: list[PlanOccurrence] = []
    warnings: list[PlannerWarning] = []
    matched = (
        0
        if effective_start <= base
        else _matched_through(rule, base, effective_start - timedelta(days=1))
    )
    cursor = effective_start
    exceptions = frozenset(rule.exception_dates)
    while cursor <= effective_end:
        if _date_matches(rule, cursor, base):
            matched += 1
            if rule.occurrence_count is not None and matched > rule.occurrence_count:
                break
            if cursor >= effective_start and cursor.isoformat() not in exceptions:
                occurrence, warning = _occurrence(block, cursor)
                if occurrence is not None:
                    occurrences.append(occurrence)
                if warning is not None:
                    warnings.append(warning)
        cursor += timedelta(days=1)
    return occurrences, warnings


def _occurrence(
    block: PlanBlock,
    day: date,
) -> tuple[PlanOccurrence | None, PlannerWarning | None]:
    status = inspect_local_time(
        local_date=day.isoformat(),
        local_hour=block.local_hour,
        local_minute=block.local_minute,
        timezone_id=block.timezone_id,
    )
    key = (
        block.block_id
        if block.recurrence.kind is RecurrenceKind.NONE
        else f"{block.block_id}@{day.isoformat()}"
    )
    if status is DstStatus.NONEXISTENT:
        return None, PlannerWarning(
            kind=PlannerWarningKind.DST_NONEXISTENT,
            message="Recurring local time does not exist on this DST date",
            first_occurrence_key=key,
        )
    selected_fold = block.dst_fold if status is DstStatus.AMBIGUOUS else 0
    local_block = replace(
        block,
        local_date=day.isoformat(),
        dst_fold=selected_fold,
    )
    _, scheduled = resolve_local_start(local_block)
    warning = None
    if status is DstStatus.AMBIGUOUS:
        warning = PlannerWarning(
            kind=PlannerWarningKind.DST_AMBIGUOUS,
            message=f"Repeated DST hour uses fold {block.dst_fold}",
            first_occurrence_key=key,
        )
    return (
        PlanOccurrence(
            occurrence_key=key,
            block_id=block.block_id,
            block_version=block.version,
            subject=block.subject,
            task=block.task,
            local_date=day.isoformat(),
            local_hour=block.local_hour,
            local_minute=block.local_minute,
            timezone_id=block.timezone_id,
            dst_fold=selected_fold,
            dst_status=status,
            scheduled_start_utc=scheduled,
            study_minutes=block.study_minutes,
            break_minutes=block.break_minutes,
            priority=block.priority,
            status=block.status,
        ),
        warning,
    )


def _conflict_warnings(
    occurrences: tuple[PlanOccurrence, ...],
) -> tuple[PlannerWarning, ...]:
    visible = {
        PlanStatus.PLANNED,
        PlanStatus.READY,
        PlanStatus.ACTIVE,
        PlanStatus.INTERRUPTED,
    }
    ordered = tuple(item for item in occurrences if item.status in visible)
    warnings: list[PlannerWarning] = []
    for index, first in enumerate(ordered):
        first_start = _parse_utc(first.scheduled_start_utc)
        first_end = first_start + timedelta(minutes=first.total_reserved_minutes)
        for second in ordered[index + 1 :]:
            second_start = _parse_utc(second.scheduled_start_utc)
            if second_start >= first_end:
                break
            second_end = second_start + timedelta(
                minutes=second.total_reserved_minutes
            )
            overlap_end = min(first_end, second_end)
            if overlap_end <= second_start:
                continue
            overlap = max(1, math_ceil_minutes(overlap_end - second_start))
            warnings.append(
                PlannerWarning(
                    kind=PlannerWarningKind.CONFLICT,
                    message=(
                        "Study blocks overlap when their planned COSECANT "
                        "break time is included"
                    ),
                    first_occurrence_key=first.occurrence_key,
                    second_occurrence_key=second.occurrence_key,
                    overlap_minutes=overlap,
                )
            )
    return tuple(warnings)


def _date_matches(rule: RecurrenceRule, candidate: date, base: date) -> bool:
    if rule.kind is RecurrenceKind.NONE:
        return candidate == base
    if rule.kind is RecurrenceKind.DAILY:
        return True
    if rule.kind is RecurrenceKind.WEEKDAYS:
        return candidate.weekday() < 5
    if rule.kind is RecurrenceKind.WEEKLY:
        return candidate.weekday() == base.weekday()
    return candidate.weekday() in rule.weekdays


def _matched_through(rule: RecurrenceRule, base: date, through: date) -> int:
    """Count earlier matches arithmetically instead of scanning old years."""

    if through < base:
        return 0
    days = (through - base).days
    if rule.kind is RecurrenceKind.NONE:
        return 1
    if rule.kind is RecurrenceKind.DAILY:
        return days + 1
    if rule.kind is RecurrenceKind.WEEKLY:
        return days // 7 + 1
    selected = (
        frozenset(range(5))
        if rule.kind is RecurrenceKind.WEEKDAYS
        else frozenset(rule.weekdays)
    )
    whole_weeks, tail = divmod(days + 1, 7)
    count = whole_weeks * len(selected)
    cursor = base + timedelta(days=whole_weeks * 7)
    for offset in range(tail):
        if (cursor + timedelta(days=offset)).weekday() in selected:
            count += 1
    return count


def _round_trip_matches(naive: datetime, zone: ZoneInfo, fold: int) -> bool:
    aware = naive.replace(tzinfo=zone, fold=fold)
    returned = aware.astimezone(timezone.utc).astimezone(zone)
    return returned.replace(tzinfo=None) == naive and returned.fold == fold


def _zone(timezone_id: str) -> ZoneInfo:
    name = str(timezone_id).strip()
    if not name:
        raise ValueError("timezone_id cannot be empty")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"timezone is unavailable: {name}") from exc


def _parse_date(value: str, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a canonical ISO date") from exc
    if value != parsed.isoformat():
        raise ValueError(f"{field_name} must be a canonical ISO date")
    return parsed


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("scheduled start must be canonical UTC") from exc
    if parsed.tzinfo is None:
        raise ValueError("scheduled start must include UTC")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _validate_clock(hour: int, minute: int, fold: int) -> None:
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("local_hour must be from 0 to 23")
    if type(minute) is not int or not 0 <= minute <= 59:
        raise ValueError("local_minute must be from 0 to 59")
    if type(fold) is not int or fold not in {0, 1}:
        raise ValueError("dst_fold must be 0 or 1")


def _validate_minutes(value: int, name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def math_ceil_minutes(value: timedelta) -> int:
    seconds = value.total_seconds()
    return int((seconds + 59) // 60)


__all__ = [
    "CosecantTimerPreparation",
    "DEFAULT_PLAN_ID",
    "DstStatus",
    "PLANNER_SCHEMA_VERSION",
    "PlanBlock",
    "PlanOccurrence",
    "PlanPriority",
    "PlanStatus",
    "PlannerProjection",
    "PlannerWarning",
    "PlannerWarningKind",
    "PreparationResult",
    "RecurrenceKind",
    "RecurrenceRule",
    "StudyPlanner",
    "inspect_local_time",
    "plan_block_from_payload",
    "plan_block_payload",
    "resolve_local_start",
    "timezone_available",
]
