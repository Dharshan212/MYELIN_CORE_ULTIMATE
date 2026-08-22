"""MYELIN Study Mode runtime authority.

PHASE A — STUDY SESSION CONFIGURATION
-------------------------------------
This phase owns the validated Study plan entered by the user.

It stores:
- subject;
- task;
- planned Study duration;
- normal keywords; and
- important keywords.

Later phases add:
- Study state;
- Study timer;
- ACTIVE-epoch protection; and
- read-only Study outputs.

This file does not control SINE, Blacklist, Idle, MIRL, browser monitoring,
or Study-alignment confidence.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Final


# ============================================================
# PHASE A — CONSTANTS
# ============================================================

STUDY_SCHEMA_VERSION: Final = "myelin-study-v4"

NANOSECONDS_PER_SECOND: Final = 1_000_000_000

MINIMUM_STUDY_SECONDS: Final = 60
MAXIMUM_STUDY_SECONDS: Final = 24 * 60 * 60

MAX_KEYWORDS: Final = 64
MAX_KEYWORD_LENGTH: Final = 120


# ============================================================
# PHASE A — STUDY PLAN
# ============================================================

@dataclass(frozen=True, slots=True)
class StudyPlan:
    """Validated instructions for one Study block."""

    subject: str
    task: str
    planned_seconds: int

    keywords: tuple[str, ...] = ()
    important_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        subject = _clean_text(self.subject)
        task = _clean_text(self.task)

        if not subject:
            raise ValueError("Study subject cannot be empty")

        if not task:
            raise ValueError("Study task cannot be empty")

        # bool is a subclass of int in Python.
        # type(...) is used deliberately so True/False cannot become
        # accidental Study durations.
        if type(self.planned_seconds) is not int:
            raise TypeError("planned_seconds must be an integer")

        if not (
            MINIMUM_STUDY_SECONDS
            <= self.planned_seconds
            <= MAXIMUM_STUDY_SECONDS
        ):
            raise ValueError(
                "planned_seconds must be between 60 seconds and 24 hours"
            )

        keywords = _clean_keywords(
            self.keywords,
            field_name="keywords",
        )

        important_keywords = _clean_keywords(
            self.important_keywords,
            field_name="important_keywords",
        )

        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "keywords", keywords)
        object.__setattr__(
            self,
            "important_keywords",
            important_keywords,
        )


# ============================================================
# PHASE A — INPUT VALIDATION HELPERS
# ============================================================

def _clean_text(value: object) -> str:
    """Accept only real strings and normalize repeated whitespace.

    Study truth must fail closed.

    Values such as None, integers, booleans, or arbitrary objects must not
    silently become strings because that could create false Study data.
    """

    if not isinstance(value, str):
        raise TypeError("text contract values must be strings")

    return " ".join(value.split())


def _keyword_input_tuple(
    values: Iterable[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    """Safely convert one keyword collection into a tuple.

    A plain string is rejected because otherwise:

        "brain"

    could accidentally become:

        ("b", "r", "a", "i", "n")
    """

    if isinstance(values, (str, bytes)):
        raise TypeError(
            f"{field_name} must be an iterable of strings, not one string"
        )

    try:
        return tuple(values)

    except TypeError as exc:
        raise TypeError(
            f"{field_name} must be an iterable of strings"
        ) from exc


def _clean_keywords(
    values: Iterable[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    """Normalize, deduplicate, and validate one keyword collection."""

    raw_values = _keyword_input_tuple(
        values,
        field_name=field_name,
    )

    cleaned: list[str] = []
    seen: set[str] = set()

    for raw in raw_values:
        value = _clean_text(raw)

        # Empty keyword entries are harmless and can be discarded.
        if not value:
            continue

        if len(value) > MAX_KEYWORD_LENGTH:
            raise ValueError(
                f"{field_name} entries must be at most "
                f"{MAX_KEYWORD_LENGTH} characters"
            )

        # Duplicate detection is case-insensitive.
        #
        # brain
        # Brain
        # BRAIN
        #
        # become one keyword.
        key = value.casefold()

        if key in seen:
            continue

        seen.add(key)
        cleaned.append(value)

        if len(cleaned) > MAX_KEYWORDS:
            raise ValueError(
                f"{field_name} cannot contain more than "
                f"{MAX_KEYWORDS} entries"
            )

    return tuple(cleaned)

# ============================================================
# PHASE B — STUDY STATE MACHINE
# ============================================================

class StudyState(str, Enum):
    """The only legal states of one Study runtime."""

    EMPTY = "EMPTY"
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    SHUTDOWN = "SHUTDOWN"


class StudyCompletionReason(str, Enum):
    """Why the current Study block stopped permanently."""

    NONE = "NONE"
    USER_COMPLETED = "USER_COMPLETED"
    TARGET_REACHED = "TARGET_REACHED"
    SAFE_SHUTDOWN = "SAFE_SHUTDOWN"


class ContextDelivery(str, Enum):
    """Delivery status of one caller-published ``StudyContext``.

    Local presentation/audit status only.  It records whether a caller's own
    attempt to publish or retire a ``StudyContext`` with the Resource Intent
    authority was accepted; it never decides Study or Resource Intent state
    itself.
    """

    NOT_PUBLISHED = "NOT_PUBLISHED"
    CONFIRMED = "CONFIRMED"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"


class _StudyCommand(str, Enum):
    """Internal commands allowed to move Study state."""

    PREPARE = "PREPARE"
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    COMPLETE = "COMPLETE"
    SHUTDOWN = "SHUTDOWN"


_STUDY_STATE_TRANSITIONS: Final[
    dict[tuple[StudyState, _StudyCommand], StudyState]
] = {
    # A new Study block can be prepared from EMPTY.
    (StudyState.EMPTY, _StudyCommand.PREPARE): StudyState.READY,

    # READY may be replaced by another prepared block, or started.
    (StudyState.READY, _StudyCommand.PREPARE): StudyState.READY,
    (StudyState.READY, _StudyCommand.START): StudyState.ACTIVE,

    # ACTIVE may pause or complete.
    (StudyState.ACTIVE, _StudyCommand.PAUSE): StudyState.PAUSED,
    (StudyState.ACTIVE, _StudyCommand.COMPLETE): StudyState.COMPLETED,

    # PAUSED may resume or complete.
    (StudyState.PAUSED, _StudyCommand.RESUME): StudyState.ACTIVE,
    (StudyState.PAUSED, _StudyCommand.COMPLETE): StudyState.COMPLETED,

    # A completed block may be replaced by a fresh prepared block.
    (StudyState.COMPLETED, _StudyCommand.PREPARE): StudyState.READY,

    # Safe shutdown is available from every non-terminal runtime state.
    (StudyState.EMPTY, _StudyCommand.SHUTDOWN): StudyState.SHUTDOWN,
    (StudyState.READY, _StudyCommand.SHUTDOWN): StudyState.SHUTDOWN,
    (StudyState.ACTIVE, _StudyCommand.SHUTDOWN): StudyState.SHUTDOWN,
    (StudyState.PAUSED, _StudyCommand.SHUTDOWN): StudyState.SHUTDOWN,
    (StudyState.COMPLETED, _StudyCommand.SHUTDOWN): StudyState.SHUTDOWN,

    # Shutdown is deliberately idempotent.
    (StudyState.SHUTDOWN, _StudyCommand.SHUTDOWN): StudyState.SHUTDOWN,
}


def _next_study_state(
    current_state: StudyState,
    command: _StudyCommand,
) -> StudyState:
    """Return the legal next state for one Study command.

    Illegal transitions fail closed. This function changes no runtime state;
    it only validates the state-machine contract.
    """

    if not isinstance(current_state, StudyState):
        raise TypeError("current_state must be StudyState")

    if not isinstance(command, _StudyCommand):
        raise TypeError("command must be _StudyCommand")

    next_state = _STUDY_STATE_TRANSITIONS.get(
        (current_state, command)
    )

    if next_state is None:
        raise ValueError(
            f"{command.value} is not allowed while Study Mode is "
            f"{current_state.value}"
        )

    return next_state

# ============================================================
# PHASE C — STUDY TIMER
# ============================================================

@dataclass(frozen=True, slots=True)
class _StudyTimerSample:
    """Internal factual view of the Study timer."""

    planned_seconds: int
    elapsed_seconds: float
    remaining_seconds: int
    progress_percent: float
    running: bool
    target_reached: bool


class _StudyTimer:
    """Monotonic-clock Study timer.

    This timer knows only factual Study time.

    It does not know:
    - Study alignment;
    - browser/resource identity;
    - SINE;
    - Blacklist;
    - Idle;
    - MIRL;

    Paused time does not count toward elapsed Study time.
    """

    def __init__(
        self,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")

        self._monotonic_ns = monotonic_ns

        self._planned_ns = 0
        self._accumulated_ns = 0
        self._running_since_ns: int | None = None

        # Protect against a broken/injected monotonic clock moving backwards.
        self._last_monotonic_ns = -1


    # --------------------------------------------------------
    # TIMER STATE
    # --------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Return True when a Study duration has been configured."""

        return self._planned_ns > 0


    @property
    def running(self) -> bool:
        """Return True only while Study time is actively accumulating."""

        return self._running_since_ns is not None


    # --------------------------------------------------------
    # CONFIGURATION
    # --------------------------------------------------------

    def configure(
        self,
        planned_seconds: int,
    ) -> None:
        """Configure a fresh Study timer.

        Reconfiguration resets elapsed Study time to zero.

        A running timer cannot be reconfigured.
        """

        if type(planned_seconds) is not int:
            raise TypeError(
                "planned_seconds must be an integer"
            )

        if not (
            MINIMUM_STUDY_SECONDS
            <= planned_seconds
            <= MAXIMUM_STUDY_SECONDS
        ):
            raise ValueError(
                "planned_seconds must be between 60 seconds and 24 hours"
            )

        if self.running:
            raise RuntimeError(
                "Cannot reconfigure a running Study timer"
            )

        self._planned_ns = (
            planned_seconds * NANOSECONDS_PER_SECOND
        )

        self._accumulated_ns = 0
        self._running_since_ns = None


    # --------------------------------------------------------
    # START / RESUME
    # --------------------------------------------------------

    def start(self) -> None:
        """Begin accumulating Study time."""

        self._begin_running(
            operation="start",
        )


    def resume(self) -> None:
        """Resume accumulating Study time after a pause."""

        self._begin_running(
            operation="resume",
        )


    # --------------------------------------------------------
    # PAUSE / STOP
    # --------------------------------------------------------

    def pause(self) -> bool:
        """Pause Study timing.

        Returns True if the Study target was reached at the exact moment
        of the pause.

        The caller can then complete the Study state instead of entering
        PAUSED.
        """

        if not self.configured:
            raise RuntimeError(
                "Study timer is not configured"
            )

        if not self.running:
            raise RuntimeError(
                "Cannot pause a Study timer that is not running"
            )

        now_ns = self._read_monotonic()

        return self._capture_at(now_ns)


    def stop(self) -> bool:
        """Stop factual Study timing.

        Returns True if the planned Study duration has been reached.

        This method does not decide WHY Study Mode stopped. The final
        StudyRuntime will decide whether the reason is USER_COMPLETED,
        TARGET_REACHED, or SAFE_SHUTDOWN.
        """

        if not self.configured:
            raise RuntimeError(
                "Study timer is not configured"
            )

        if not self.running:
            return (
                self._accumulated_ns
                >= self._planned_ns
            )

        now_ns = self._read_monotonic()

        return self._capture_at(now_ns)


    # --------------------------------------------------------
    # TIMER ADVANCE
    # --------------------------------------------------------

    def advance(self) -> bool:
        """Advance factual timer truth.

        Returns True once the planned Study duration has been reached.

        When the target is reached, elapsed time is fixed exactly at the
        planned duration and the timer stops accumulating.
        """

        if not self.configured:
            raise RuntimeError(
                "Study timer is not configured"
            )

        if not self.running:
            return (
                self._accumulated_ns
                >= self._planned_ns
            )

        now_ns = self._read_monotonic()

        elapsed_ns = self._elapsed_ns_at(now_ns)

        if elapsed_ns < self._planned_ns:
            return False

        self._accumulated_ns = self._planned_ns
        self._running_since_ns = None

        return True


    # --------------------------------------------------------
    # INTERNAL TIMER SAMPLE
    # --------------------------------------------------------

    def sample(self) -> _StudyTimerSample:
        """Return a factual internal timer sample.

        Sampling never changes timer state.

        The public StudySnapshot will be created later in Phase G.
        """

        if not self.configured:
            return _StudyTimerSample(
                planned_seconds=0,
                elapsed_seconds=0.0,
                remaining_seconds=0,
                progress_percent=0.0,
                running=False,
                target_reached=False,
            )

        elapsed_ns = self._accumulated_ns

        if self.running:
            now_ns = self._read_monotonic()
            elapsed_ns = self._elapsed_ns_at(now_ns)

        target_reached = (
            elapsed_ns >= self._planned_ns
        )

        remaining_ns = max(
            0,
            self._planned_ns - elapsed_ns,
        )

        planned_seconds = (
            self._planned_ns
            // NANOSECONDS_PER_SECOND
        )

        elapsed_seconds = (
            elapsed_ns
            / NANOSECONDS_PER_SECOND
        )

        progress_percent = min(
            100.0,
            (
                elapsed_ns
                / self._planned_ns
            )
            * 100.0,
        )

        return _StudyTimerSample(
            planned_seconds=planned_seconds,
            elapsed_seconds=round(
                elapsed_seconds,
                3,
            ),
            remaining_seconds=math.ceil(
                remaining_ns
                / NANOSECONDS_PER_SECOND
            ),
            progress_percent=round(
                progress_percent,
                3,
            ),
            running=self.running,
            target_reached=target_reached,
            )

    # --------------------------------------------------------
    # INTERNAL HELPERS
    # --------------------------------------------------------

    def _begin_running(
        self,
        *,
        operation: str,
    ) -> None:
        """Start or resume the monotonic timer safely."""

        if not self.configured:
            raise RuntimeError(
                f"Cannot {operation} an unconfigured Study timer"
            )

        if self.running:
            raise RuntimeError(
                "Study timer is already running"
            )

        if (
            self._accumulated_ns
            >= self._planned_ns
        ):
            raise RuntimeError(
                "Completed Study timer cannot run again"
            )

        now_ns = self._read_monotonic()

        self._running_since_ns = now_ns


    def _capture_at(
        self,
        now_ns: int,
    ) -> bool:
        """Capture elapsed Study time and stop accumulation."""

        elapsed_ns = self._elapsed_ns_at(
            now_ns
        )

        self._accumulated_ns = elapsed_ns
        self._running_since_ns = None

        return (
            elapsed_ns
            >= self._planned_ns
        )


    def _elapsed_ns_at(
        self,
        now_ns: int,
    ) -> int:
        """Calculate factual elapsed Study time at one monotonic instant."""

        elapsed_ns = self._accumulated_ns

        if self._running_since_ns is not None:
            if now_ns < self._running_since_ns:
                raise RuntimeError(
                    "The monotonic clock moved backwards"
                )

            elapsed_ns += (
                now_ns
                - self._running_since_ns
            )

        return max(
            0,
            min(
                elapsed_ns,
                self._planned_ns,
            ),
        )


    def _read_monotonic(self) -> int:
        """Read and validate the monotonic clock."""

        value = self._monotonic_ns()

        if (
            type(value) is not int
            or value < 0
        ):
            raise RuntimeError(
                "The monotonic clock returned an invalid value"
            )

        if value < self._last_monotonic_ns:
            raise RuntimeError(
                "The monotonic clock moved backwards"
            )

        self._last_monotonic_ns = value

        return value
    
# ============================================================
# PHASE D — ACTIVE-EPOCH PROTECTION
# ============================================================

@dataclass(frozen=True, slots=True)
class _StudyActiveEpochSample:
    """Internal read-only view of the current Study ACTIVE epoch."""

    active: bool
    started_monotonic_ns: int


class _StudyActiveEpoch:
    """Own the freshness boundary for one ACTIVE Study period.

    A new epoch begins every time Study Mode enters ACTIVE through Start
    or Resume. Resource evidence observed before that boundary must not
    authorize Study protection.

    This component owns only freshness truth. It does not know browser
    identity, Study alignment, SINE, Blacklist, Idle, MIRL, or popup policy.

    The final StudyRuntime will call this component while holding the
    runtime's lock.
    """

    def __init__(
        self,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")

        self._monotonic_ns = monotonic_ns

        # Keep activity separate from the timestamp. A monotonic clock may
        # validly return 0, especially in deterministic tests, so timestamp 0
        # must not itself mean "inactive".
        self._active = False
        self._started_monotonic_ns = 0
        self._last_monotonic_ns = -1

    @property
    def active(self) -> bool:
        """Return True only while an ACTIVE Study epoch is open."""

        return self._active

    @property
    def started_monotonic_ns(self) -> int:
        """Return the most recent ACTIVE-epoch boundary."""

        return self._started_monotonic_ns

    def reset(self) -> None:
        """Reset epoch truth for a newly prepared Study block.

        Reset is forbidden while an ACTIVE epoch is open. The final
        StudyRuntime must close the epoch before preparing a new block.

        The monotonic rollback guard is deliberately preserved across blocks.
        """

        if self._active:
            raise RuntimeError(
                "Cannot reset Study ACTIVE epoch while it is open"
            )

        self._active = False
        self._started_monotonic_ns = 0

    def begin(self) -> int:
        """Open a fresh ACTIVE epoch and return its monotonic boundary.

        The final StudyRuntime will call this after a legal Start or Resume.
        Opening another epoch while one is already active fails closed rather
        than silently replacing the existing freshness boundary.
        """

        if self._active:
            raise RuntimeError(
                "Study ACTIVE epoch is already open"
            )

        now_ns = self._read_monotonic()

        self._started_monotonic_ns = now_ns
        self._active = True

        return now_ns

    def end(self) -> None:
        """Close the current ACTIVE epoch without erasing its last boundary.

        Closing is deliberately idempotent so Pause, completion, or safe
        shutdown cleanup cannot fail merely because the epoch is already
        inactive. A later Resume opens a new epoch with a new boundary.
        """

        self._active = False

    def accepts_observation(
        self,
        observed_monotonic_ns: int,
    ) -> bool:
        """Return True only for evidence valid in the current ACTIVE epoch.

        Evidence fails closed when:
        - no ACTIVE epoch is open;
        - it was observed before the current Start/Resume boundary; or
        - its timestamp claims to be in the future.

        Equality with the epoch boundary is accepted. This matches the Study
        alignment contract: only evidence strictly older than the current
        ACTIVE epoch is stale.
        """

        if type(observed_monotonic_ns) is not int:
            raise TypeError(
                "observed_monotonic_ns must be an integer"
            )

        if observed_monotonic_ns < 0:
            raise ValueError(
                "observed_monotonic_ns must be non-negative"
            )

        if not self._active:
            return False

        if observed_monotonic_ns < self._started_monotonic_ns:
            return False

        now_ns = self._read_monotonic()

        if observed_monotonic_ns > now_ns:
            return False

        return True

    def sample(self) -> _StudyActiveEpochSample:
        """Return a read-only epoch sample without changing epoch state."""

        return _StudyActiveEpochSample(
            active=self._active,
            started_monotonic_ns=self._started_monotonic_ns,
        )

    def _read_monotonic(self) -> int:
        """Read and validate this component's monotonic clock."""

        value = self._monotonic_ns()

        if type(value) is not int or value < 0:
            raise RuntimeError(
                "The monotonic clock returned an invalid value"
            )

        if value < self._last_monotonic_ns:
            raise RuntimeError(
                "The monotonic clock moved backwards"
            )

        self._last_monotonic_ns = value

        return value
    
# ============================================================
# PHASE G — FINAL STUDY RUNTIME + PUBLIC OUTPUT VALVES
# ============================================================

@dataclass(frozen=True, slots=True)
class StudyTargetSnapshot:
    """Small read-only Study target consumed by Study alignment."""

    block_id: str
    generation: int
    state: StudyState
    study_active: bool

    subject: str
    task: str
    keywords: tuple[str, ...]
    important_keywords: tuple[str, ...]

    active_epoch_monotonic_ns: int
    published_monotonic_ns: int

    schema_version: str = STUDY_SCHEMA_VERSION

    @property
    def configured(self) -> bool:
        """Return True when a Study block has been prepared."""

        return bool(self.block_id)


@dataclass(frozen=True, slots=True)
class StudySnapshot:
    """Immutable public view of the authoritative Study runtime."""

    block_id: str
    generation: int
    state: StudyState

    subject: str
    task: str
    keywords: tuple[str, ...]
    important_keywords: tuple[str, ...]

    active_epoch_monotonic_ns: int

    planned_seconds: int
    elapsed_seconds: float
    remaining_seconds: int
    progress_percent: float

    started_wall_time_utc: str
    paused_wall_time_utc: str
    completed_wall_time_utc: str
    ends_at_wall_time_utc: str

    completion_reason: StudyCompletionReason
    last_action: str

    published_monotonic_ns: int

    schema_version: str = STUDY_SCHEMA_VERSION

    @property
    def configured(self) -> bool:
        """Return True when a Study block has been prepared."""

        return bool(self.block_id)

    @property
    def study_active(self) -> bool:
        """Return True only while Study Mode is semantically ACTIVE."""

        return self.state is StudyState.ACTIVE

    @property
    def context_token(self) -> str:
        """Same identity concept as CORE_ENGINE.resource_intent.StudyContext.context_token.

        Derived, not stored: COSECANT (``start_break``) and Resource Intent
        both need to agree on one exact-block/generation identity, and
        ``CORE_ENGINE.resource_intent.study_context_token`` is the single
        canonical function that computes it. Reusing it here (instead of
        duplicating the hash) keeps the two sides from ever silently
        drifting into disagreeing token values for the same block/generation.
        """

        from CORE_ENGINE.resource_intent import study_context_token

        return study_context_token(self.block_id, self.generation)


@dataclass(frozen=True, slots=True)
class StudyActionResult:
    """Result returned by a Study runtime command."""

    accepted: bool
    message: str
    snapshot: StudySnapshot


class StudyRuntime:
    """Thread-safe authority for the Study Mode lifecycle.

    This runtime owns:
    - Study session truth;
    - Study semantic state;
    - factual Study timing;
    - ACTIVE-epoch freshness;
    - immutable Study outputs.

    It does not:
    - inspect Windows;
    - inspect browsers;
    - calculate Study alignment;
    - control Idle;
    - run Blacklist dwell;
    - schedule SINE;
    - show popups;
    - create MIRL episodes;
    - own COSECANT break state; or
    - persist data.

    All mutating commands are serialized through one re-entrant lock.

    """

    def __init__(
        self,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock_utc: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(monotonic_ns):
            raise TypeError(
                "monotonic_ns must be callable"
            )

        if (
            wall_clock_utc is not None
            and not callable(wall_clock_utc)
        ):
            raise TypeError(
                "wall_clock_utc must be callable"
            )

        self._monotonic_ns = monotonic_ns

        self._wall_clock_utc = (
            wall_clock_utc
            or (
                lambda: datetime.now(
                    timezone.utc
                )
            )
        )

        self._lock = threading.RLock()

        self._state = StudyState.EMPTY

        self._plan: StudyPlan | None = None

        self._block_id = ""
        self._generation = 0

        # Both organs deliberately use the same monotonic source.
        self._timer = _StudyTimer(
            monotonic_ns=monotonic_ns,
        )

        self._active_epoch = _StudyActiveEpoch(
            monotonic_ns=monotonic_ns,
        )

        self._started_wall_time_utc = ""
        self._paused_wall_time_utc = ""
        self._completed_wall_time_utc = ""

        self._completion_reason = (
            StudyCompletionReason.NONE
        )

        self._last_action = (
            "Study Mode is empty"
        )

        self._last_runtime_monotonic_ns = -1
        self._published_monotonic_ns = 0

        self._snapshot = self._make_snapshot(
            now_wall=self._read_wall_clock(),
            published_monotonic_ns=0,
        )

        self._assert_runtime_invariants()


    # --------------------------------------------------------
    # PREPARE
    # --------------------------------------------------------

    def prepare(
        self,
        *,
        subject: str,
        task: str,
        planned_seconds: int,
        keywords: Iterable[str] = (),
        important_keywords: Iterable[str] = (),
        block_id: str = "",
    ) -> StudyActionResult:
        """Prepare a fresh Study block without starting Study time."""

        plan = StudyPlan(
            subject=subject,
            task=task,
            planned_seconds=planned_seconds,
            keywords=_keyword_input_tuple(
                keywords,
                field_name="keywords",
            ),
            important_keywords=_keyword_input_tuple(
                important_keywords,
                field_name="important_keywords",
            ),
        )

        clean_block_id = _clean_text(
            block_id
        )

        with self._lock:
            self._assert_runtime_invariants()

            try:
                next_state = _next_study_state(
                    self._state,
                    _StudyCommand.PREPARE,
                )

            except ValueError:
                if self._state is StudyState.SHUTDOWN:
                    return self._reject(
                        "Study Mode has already shut down"
                    )

                return self._reject(
                    "Complete the current Study block "
                    "before preparing another"
                )

            next_generation = (
                self._generation + 1
            )

            next_block_id = (
                clean_block_id
                or secrets.token_hex(12)
            )

            now_wall = self._read_wall_clock()

            # PREPARE is legal only from EMPTY, READY, or COMPLETED.
            # Therefore none of these organs may currently be ACTIVE.
            self._active_epoch.reset()

            self._timer.configure(
                plan.planned_seconds
            )

            self._plan = plan

            self._block_id = next_block_id
            self._generation = next_generation

            self._state = next_state

            self._started_wall_time_utc = ""
            self._paused_wall_time_utc = ""
            self._completed_wall_time_utc = ""

            self._completion_reason = (
                StudyCompletionReason.NONE
            )

            self._last_action = (
                "Study block prepared"
            )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._accept(
                "Study block is ready"
            )


    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    def start(
        self,
    ) -> StudyActionResult:
        """Start the prepared Study block."""

        with self._lock:
            self._assert_runtime_invariants()

            try:
                next_state = _next_study_state(
                    self._state,
                    _StudyCommand.START,
                )

            except ValueError:
                return self._reject(
                    "Start is allowed only from READY"
                )

            now_wall = self._read_wall_clock()


            # Open the freshness boundary first.
            #
            # If timer start unexpectedly fails, the epoch is immediately
            # closed again before the exception escapes.
            self._active_epoch.begin()

            try:
                self._timer.start()

            except Exception:
                self._active_epoch.end()
                raise

            self._state = next_state

            self._started_wall_time_utc = (
                _wall_text(
                    now_wall
                )
            )

            self._paused_wall_time_utc = ""
            self._completed_wall_time_utc = ""

            self._completion_reason = (
                StudyCompletionReason.NONE
            )

            self._last_action = (
                "Study timer started"
            )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._accept(
                "Study Mode started"
            )


    # --------------------------------------------------------
    # PAUSE
    # --------------------------------------------------------

    def pause(
        self,
    ) -> StudyActionResult:
        """Pause Study time.

        If factual Study time already reached the target, the Study block
        completes instead of entering PAUSED.
        """

        with self._lock:
            self._assert_runtime_invariants()

            try:
                paused_state = _next_study_state(
                    self._state,
                    _StudyCommand.PAUSE,
                )

            except ValueError:
                return self._reject(
                    "Pause is allowed only from ACTIVE"
                )

            now_wall = self._read_wall_clock()


            target_reached = (
                self._timer.pause()
            )

            self._active_epoch.end()

            if target_reached:
                self._state = _next_study_state(
                    self._state,
                    _StudyCommand.COMPLETE,
                )

                self._completion_reason = (
                    StudyCompletionReason.TARGET_REACHED
                )

                self._completed_wall_time_utc = (
                    _wall_text(
                        now_wall
                    )
                )

                self._last_action = (
                    "Planned Study time reached"
                )

                message = (
                    "Study block completed: "
                    "planned time reached"
                )

            else:
                self._state = paused_state

                self._paused_wall_time_utc = (
                    _wall_text(
                        now_wall
                    )
                )

                self._last_action = (
                    "Study timer paused"
                )

                message = (
                    "Study Mode paused"
                )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._accept(
                message
            )


    # --------------------------------------------------------
    # RESUME
    # --------------------------------------------------------

    def resume(
        self,
    ) -> StudyActionResult:
        """Resume a paused Study block.

        Resume opens a fresh ACTIVE epoch so evidence from before Resume
        cannot silently inherit Study protection.
        """

        with self._lock:
            self._assert_runtime_invariants()

            try:
                next_state = _next_study_state(
                    self._state,
                    _StudyCommand.RESUME,
                )

            except ValueError:
                return self._reject(
                    "Resume is allowed only from PAUSED"
                )

            now_wall = self._read_wall_clock()

            self._active_epoch.begin()

            try:
                self._timer.resume()

            except Exception:
                self._active_epoch.end()
                raise

            self._state = next_state

            self._paused_wall_time_utc = ""

            self._last_action = (
                "Study timer resumed"
            )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._accept(
                "Study Mode resumed"
            )


    # --------------------------------------------------------
    # COMPLETE
    # --------------------------------------------------------

    def complete(
        self,
    ) -> StudyActionResult:
        """Complete an ACTIVE or PAUSED Study block."""

        with self._lock:
            self._assert_runtime_invariants()

            try:
                next_state = _next_study_state(
                    self._state,
                    _StudyCommand.COMPLETE,
                )

            except ValueError:
                return self._reject(
                    "Complete requires an ACTIVE "
                    "or PAUSED Study block"
                )

            now_wall = self._read_wall_clock()

            target_reached = (
                self._timer.stop()
            )

            if self._state is StudyState.ACTIVE:
                self._active_epoch.end()

            self._state = next_state

            if target_reached:
                self._completion_reason = (
                    StudyCompletionReason.TARGET_REACHED
                )

                self._last_action = (
                    "Planned Study time reached"
                )

                message = (
                    "Study block completed: "
                    "planned time reached"
                )

            else:
                self._completion_reason = (
                    StudyCompletionReason.USER_COMPLETED
                )

                self._last_action = (
                    "Study block completed by user"
                )

                message = (
                    "Study block completed"
                )

            self._completed_wall_time_utc = (
                _wall_text(
                    now_wall
                )
            )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._accept(
                message
            )


    # --------------------------------------------------------
    # ADVANCE
    # --------------------------------------------------------

    def advance(
        self,
    ) -> StudySnapshot:
        """Advance timer truth once.

        A monitor/controller may call this periodically.
        """

        with self._lock:
            self._assert_runtime_invariants()

            if self._state is StudyState.SHUTDOWN:
                return self._snapshot

            now_wall = self._read_wall_clock()


            self._complete_if_target_reached(
                now_wall=now_wall
            )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._snapshot


    # --------------------------------------------------------
    # SHUTDOWN
    # --------------------------------------------------------

    def shutdown(
        self,
    ) -> StudyActionResult:
        """Safely stop Study Mode and make the runtime permanently inert."""

        with self._lock:
            self._assert_runtime_invariants()

            if self._state is StudyState.SHUTDOWN:
                return StudyActionResult(
                    accepted=True,
                    message=(
                        "Study Mode is already shut down"
                    ),
                    snapshot=self._snapshot,
                )

            now_wall = self._read_wall_clock()

            target_reached = False

            if self._state is StudyState.ACTIVE:
                target_reached = (
                    self._timer.stop()
                )

                self._active_epoch.end()

            elif self._state is StudyState.PAUSED:
                target_reached = (
                    self._timer.stop()
                )

            # Preserve factual target completion if shutdown happened
            # immediately after the Study target was reached.
            if target_reached:
                self._state = _next_study_state(
                    self._state,
                    _StudyCommand.COMPLETE,
                )

                self._completion_reason = (
                    StudyCompletionReason.TARGET_REACHED
                )

                self._completed_wall_time_utc = (
                    _wall_text(
                        now_wall
                    )
                )

            was_completed = (
                self._state is StudyState.COMPLETED
            )

            self._state = _next_study_state(
                self._state,
                _StudyCommand.SHUTDOWN,
            )

            if not was_completed:
                self._completion_reason = (
                    StudyCompletionReason.SAFE_SHUTDOWN
                )

                self._completed_wall_time_utc = (
                    _wall_text(
                        now_wall
                    )
                )

            self._last_action = (
                "Study Mode shut down safely"
            )

            self._publish(
                now_wall=now_wall,
            )

            self._assert_runtime_invariants()

            return self._accept(
                "Study Mode shut down safely"
            )


    # --------------------------------------------------------
    # READ-ONLY OUTPUT VALVES
    # --------------------------------------------------------

    def snapshot(
        self,
    ) -> StudySnapshot:
        """Return the last immutable full Study snapshot.

        This call never advances the Study timer.

        A monitor/controller should call advance() when it wants factual
        timer truth refreshed.
        """

        with self._lock:
            return self._snapshot


    def study_target(
        self,
    ) -> StudyTargetSnapshot:
        """Return the immutable Study target consumed by Study alignment."""

        with self._lock:
            plan = self._plan

            return StudyTargetSnapshot(
                block_id=self._block_id,
                generation=self._generation,
                state=self._state,
                study_active=(
                    self._state
                    is StudyState.ACTIVE
                ),
                subject=(
                    plan.subject
                    if plan is not None
                    else ""
                ),
                task=(
                    plan.task
                    if plan is not None
                    else ""
                ),
                keywords=(
                    plan.keywords
                    if plan is not None
                    else ()
                ),
                important_keywords=(
                    plan.important_keywords
                    if plan is not None
                    else ()
                ),
                active_epoch_monotonic_ns=(
                    self._active_epoch.started_monotonic_ns
                ),
                published_monotonic_ns=(
                    self._published_monotonic_ns
                ),
            )


    # --------------------------------------------------------
    # INTERNAL TARGET SETTLEMENT
    # --------------------------------------------------------

    def _complete_if_target_reached(
        self,
        *,
        now_wall: datetime,
    ) -> bool:
        """Complete ACTIVE Study Mode if factual time reached the target."""

        if self._state is not StudyState.ACTIVE:
            return False

        if not self._timer.advance():
            return False

        self._active_epoch.end()

        self._state = _next_study_state(
            self._state,
            _StudyCommand.COMPLETE,
        )

        self._completion_reason = (
            StudyCompletionReason.TARGET_REACHED
        )

        self._completed_wall_time_utc = (
            _wall_text(
                now_wall
            )
        )

        self._last_action = (
            "Planned Study time reached"
        )

        return True


    # --------------------------------------------------------
    # SNAPSHOT PUBLICATION
    # --------------------------------------------------------

    def _publish(
        self,
        *,
        now_wall: datetime,
    ) -> None:
        """Publish one causally ordered immutable Study snapshot."""

        timer_sample = self._timer.sample()

        # A timer sample can reach the target between a Start/Resume mutation
        # and publication. Never publish ACTIVE Study state once the sampled
        # timer itself says the planned target has been reached.

        published_monotonic_ns = (
            self._read_runtime_monotonic()
        )

        self._published_monotonic_ns = (
            published_monotonic_ns
        )

        self._snapshot = self._make_snapshot(
            now_wall=now_wall,
            published_monotonic_ns=(
                published_monotonic_ns
            ),
            timer_sample=timer_sample,
        )


    def _make_snapshot(
        self,
        *,
        now_wall: datetime,
        published_monotonic_ns: int,
        timer_sample: _StudyTimerSample | None = None,
    ) -> StudySnapshot:
        """Build one immutable Study runtime snapshot."""

        plan = self._plan

        timer = (
            timer_sample
            if timer_sample is not None
            else self._timer.sample()
        )

        ends_at = ""

        if (
            self._state is StudyState.ACTIVE
            and timer.remaining_seconds > 0
        ):
            ends_at = _wall_text(
                now_wall
                + timedelta(
                    seconds=(
                        timer.remaining_seconds
                    )
                )
            )

        return StudySnapshot(
            block_id=self._block_id,
            generation=self._generation,
            state=self._state,

            subject=(
                plan.subject
                if plan is not None
                else ""
            ),

            task=(
                plan.task
                if plan is not None
                else ""
            ),

            keywords=(
                plan.keywords
                if plan is not None
                else ()
            ),

            important_keywords=(
                plan.important_keywords
                if plan is not None
                else ()
            ),


            active_epoch_monotonic_ns=(
                self._active_epoch.started_monotonic_ns
            ),

            planned_seconds=(
                timer.planned_seconds
            ),

            elapsed_seconds=(
                timer.elapsed_seconds
            ),

            remaining_seconds=(
                timer.remaining_seconds
            ),

            progress_percent=(
                timer.progress_percent
            ),

            started_wall_time_utc=(
                self._started_wall_time_utc
            ),

            paused_wall_time_utc=(
                self._paused_wall_time_utc
            ),

            completed_wall_time_utc=(
                self._completed_wall_time_utc
            ),

            ends_at_wall_time_utc=(
                ends_at
            ),

            completion_reason=(
                self._completion_reason
            ),

            last_action=(
                self._last_action
            ),

            published_monotonic_ns=(
                published_monotonic_ns
            ),
        )


    # --------------------------------------------------------
    # COMMAND RESULTS
    # --------------------------------------------------------

    def _accept(
        self,
        message: str,
    ) -> StudyActionResult:
        """Return an accepted command result."""

        return StudyActionResult(
            accepted=True,
            message=message,
            snapshot=self._snapshot,
        )


    def _reject(
        self,
        message: str,
    ) -> StudyActionResult:
        """Return a rejected command result without mutating Study state."""

        return StudyActionResult(
            accepted=False,
            message=message,
            snapshot=self._snapshot,
        )


    # --------------------------------------------------------
    # CLOCKS
    # --------------------------------------------------------

    def _read_runtime_monotonic(
        self,
    ) -> int:
        """Read and validate the runtime publication clock."""

        value = self._monotonic_ns()

        if (
            type(value) is not int
            or value < 0
        ):
            raise RuntimeError(
                "The monotonic clock returned "
                "an invalid value"
            )

        if (
            value
            < self._last_runtime_monotonic_ns
        ):
            raise RuntimeError(
                "The monotonic clock moved backwards"
            )

        self._last_runtime_monotonic_ns = value

        return value


    def _read_wall_clock(
        self,
    ) -> datetime:
        """Read one timezone-aware UTC wall-clock value."""

        value = self._wall_clock_utc()

        if not isinstance(
            value,
            datetime,
        ):
            raise RuntimeError(
                "The wall clock must return a datetime"
            )

        if value.tzinfo is None:
            raise RuntimeError(
                "The wall clock datetime "
                "must include a timezone"
            )

        return value.astimezone(
            timezone.utc
        )


    # --------------------------------------------------------
    # RUNTIME INVARIANTS
    # --------------------------------------------------------

    def _assert_runtime_invariants(
        self,
    ) -> None:
        """Fail loudly if Study state and its internal organs disagree."""

        state = self._state

        # ----------------------------------------------------
        # EMPTY
        # ----------------------------------------------------

        if state is StudyState.EMPTY:
            if self._plan is not None:
                raise RuntimeError(
                    "EMPTY Study state cannot "
                    "have a Study plan"
                )

            if (
                self._block_id
                or self._generation != 0
            ):
                raise RuntimeError(
                    "EMPTY Study state cannot "
                    "have block identity"
                )

            if self._timer.configured:
                raise RuntimeError(
                    "EMPTY Study state cannot "
                    "have a configured timer"
                )

            if self._active_epoch.active:
                raise RuntimeError(
                    "EMPTY Study state cannot "
                    "have an ACTIVE epoch"
                )


        # ----------------------------------------------------
        # READY
        # ----------------------------------------------------

        elif state is StudyState.READY:
            self._assert_configured_identity()

            if not self._timer.configured:
                raise RuntimeError(
                    "READY Study state requires "
                    "a configured timer"
                )

            if self._timer.running:
                raise RuntimeError(
                    "READY Study state cannot "
                    "have a running timer"
                )

            if self._active_epoch.active:
                raise RuntimeError(
                    "READY Study state cannot "
                    "have an ACTIVE epoch"
                )

            if (
                self._completion_reason
                is not StudyCompletionReason.NONE
            ):
                raise RuntimeError(
                    "READY Study state cannot "
                    "have a completion reason"
                )


        # ----------------------------------------------------
        # ACTIVE
        # ----------------------------------------------------

        elif state is StudyState.ACTIVE:
            self._assert_configured_identity()

            if not self._timer.configured:
                raise RuntimeError(
                    "ACTIVE Study state requires "
                    "a configured timer"
                )

            if not self._timer.running:
                raise RuntimeError(
                    "ACTIVE Study state requires "
                    "a running timer"
                )

            if not self._active_epoch.active:
                raise RuntimeError(
                    "ACTIVE Study state requires "
                    "an ACTIVE epoch"
                )

            if (
                self._completion_reason
                is not StudyCompletionReason.NONE
            ):
                raise RuntimeError(
                    "ACTIVE Study state cannot "
                    "have a completion reason"
                )


        # ----------------------------------------------------
        # PAUSED
        # ----------------------------------------------------

        elif state is StudyState.PAUSED:
            self._assert_configured_identity()

            if not self._timer.configured:
                raise RuntimeError(
                    "PAUSED Study state requires "
                    "a configured timer"
                )

            if self._timer.running:
                raise RuntimeError(
                    "PAUSED Study state cannot "
                    "have a running timer"
                )

            if self._active_epoch.active:
                raise RuntimeError(
                    "PAUSED Study state cannot "
                    "have an ACTIVE epoch"
                )

            if (
                self._completion_reason
                is not StudyCompletionReason.NONE
            ):
                raise RuntimeError(
                    "PAUSED Study state cannot "
                    "have a completion reason"
                )


        # ----------------------------------------------------
        # COMPLETED
        # ----------------------------------------------------

        elif state is StudyState.COMPLETED:
            self._assert_configured_identity()

            if not self._timer.configured:
                raise RuntimeError(
                    "COMPLETED Study state requires "
                    "a configured timer"
                )

            if self._timer.running:
                raise RuntimeError(
                    "COMPLETED Study state cannot "
                    "have a running timer"
                )

            if self._active_epoch.active:
                raise RuntimeError(
                    "COMPLETED Study state cannot "
                    "have an ACTIVE epoch"
                )

            if (
                self._completion_reason
                is StudyCompletionReason.NONE
            ):
                raise RuntimeError(
                    "COMPLETED Study state requires "
                    "a completion reason"
                )


        # ----------------------------------------------------
        # SHUTDOWN
        # ----------------------------------------------------

        elif state is StudyState.SHUTDOWN:
            if self._timer.running:
                raise RuntimeError(
                    "SHUTDOWN Study state cannot "
                    "have a running timer"
                )

            if self._active_epoch.active:
                raise RuntimeError(
                    "SHUTDOWN Study state cannot "
                    "have an ACTIVE epoch"
                )

            if (
                self._completion_reason
                is StudyCompletionReason.NONE
            ):
                raise RuntimeError(
                    "SHUTDOWN Study state requires "
                    "a completion reason"
                )

            if self._plan is not None:
                self._assert_configured_identity()

            else:
                if (
                    self._block_id
                    or self._generation != 0
                ):
                    raise RuntimeError(
                        "Unconfigured SHUTDOWN state "
                        "cannot have block identity"
                    )

                if self._timer.configured:
                    raise RuntimeError(
                        "Unconfigured SHUTDOWN state "
                        "cannot have a configured timer"
                    )

        else:
            raise RuntimeError(
                "Unknown Study runtime state"
            )


    def _assert_configured_identity(
        self,
    ) -> None:
        """Verify one configured Study block and its internal bindings."""

        if self._plan is None:
            raise RuntimeError(
                "Configured Study state requires "
                "a Study plan"
            )

        if not self._block_id:
            raise RuntimeError(
                "Configured Study state requires "
                "a block_id"
            )

        if self._generation < 1:
            raise RuntimeError(
                "Configured Study state requires "
                "a positive generation"
            )

        expected_planned_ns = (
            self._plan.planned_seconds
            * NANOSECONDS_PER_SECOND
        )

        if (
            self._timer._planned_ns
            != expected_planned_ns
        ):
            raise RuntimeError(
                "Study timer duration does not "
                "match the Study plan"
            )



# ============================================================
# PHASE G — WALL-CLOCK OUTPUT HELPER
# ============================================================

def _wall_text(
    value: datetime,
) -> str:
    """Return one stable UTC wall-clock string."""

    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(
            "value must be datetime"
        )

    if value.tzinfo is None:
        raise ValueError(
            "value must include "
            "timezone information"
        )

    return value.astimezone(
        timezone.utc
    ).isoformat()


# ============================================================
# PHASE G — PUBLIC EXPORT SURFACE
# ============================================================

__all__ = [
    "STUDY_SCHEMA_VERSION",
    "ContextDelivery",
    "StudyActionResult",
    "StudyCompletionReason",
    "StudyPlan",
    "StudyRuntime",
    "StudySnapshot",
    "StudyState",
    "StudyTargetSnapshot",
]
