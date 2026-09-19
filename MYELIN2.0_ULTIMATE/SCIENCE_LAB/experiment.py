"""Durable, non-Qt Science Lab experiment lifecycle authority.

An experiment is an explicitly started observation window attached to one
real MYELIN session.  This module owns no monitoring, organ evidence,
analysis, UI, STOP signal, or report behavior.  Durable state remains the
authority throughout the lifecycle.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Final

from PERSISTENCE.storage import (
    EngineStorage,
    ScienceLabExperimentRecord,
    read_running_science_lab_experiment,
    read_science_lab_experiment,
    read_science_lab_experiments_for_session,
)


STATUS_RUNNING: Final = "RUNNING"
STATUS_COMPLETED: Final = "COMPLETED"
STATUS_INTERRUPTED: Final = "INTERRUPTED"

END_REASON_USER: Final = "USER_END"
END_REASON_PARENT_SESSION: Final = "PARENT_SESSION_ENDED"
END_REASON_CRASH: Final = "CRASH_RECOVERY"

_PROCESS_INSTANCE_ID = uuid.uuid4().hex


def _parent_session_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("parent_session_id must be a positive integer")
    return value


def _local_date_key() -> str:
    return datetime.now().astimezone().strftime("%d%m%Y")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _experiment_id(date_key: str, daily_sequence: int) -> str:
    return f"MYL-{date_key}-SCI{daily_sequence:02d}"


def _require_current_process(record: ScienceLabExperimentRecord) -> None:
    if record.runtime_instance_id != _PROCESS_INSTANCE_ID:
        raise RuntimeError(
            "running Science Lab experiment belongs to another process lifetime"
        )


def contains_completed_window(
    record: ScienceLabExperimentRecord,
    occurred_monotonic_ns: int,
) -> bool:
    """Return whether one exact instant lies in a completed [start, end) window."""

    if record.status != STATUS_COMPLETED:
        raise ValueError("completed experiment required")
    if record.ended_monotonic_ns is None:
        raise RuntimeError("completed experiment has no end boundary")
    if type(occurred_monotonic_ns) is not int:
        raise ValueError("occurred_monotonic_ns must be an exact integer")
    return (
        record.started_monotonic_ns
        <= occurred_monotonic_ns
        < record.ended_monotonic_ns
    )


class ScienceLabExperimentLifecycle:
    """Coordinate explicit experiment transitions through durable storage."""

    def __init__(self, *, storage: EngineStorage) -> None:
        if not isinstance(storage, EngineStorage):
            raise TypeError("storage must be an EngineStorage facade")
        self._storage = storage

    def current(self) -> ScienceLabExperimentRecord | None:
        return read_running_science_lab_experiment()

    def history(
        self,
        parent_session_id: int,
    ) -> tuple[ScienceLabExperimentRecord, ...]:
        return read_science_lab_experiments_for_session(
            _parent_session_id(parent_session_id)
        )

    def start(self, parent_session_id: int) -> ScienceLabExperimentRecord:
        sid = _parent_session_id(parent_session_id)
        if self.current() is not None:
            raise RuntimeError("a Science Lab experiment is already running")

        date_key = _local_date_key()
        started_at_utc = _utc_now()
        started_monotonic_ns = time.monotonic_ns()
        sequence = self._storage.start_science_lab_experiment(
            parent_session_id=sid,
            date_key=date_key,
            started_at_utc=started_at_utc,
            started_monotonic_ns=started_monotonic_ns,
            runtime_instance_id=_PROCESS_INSTANCE_ID,
        )

        experiment_id = _experiment_id(date_key, sequence)
        record = read_science_lab_experiment(experiment_id)
        if record is None:
            raise RuntimeError(
                "Science Lab experiment committed but could not be read back"
            )
        if (
            record.experiment_id != experiment_id
            or record.parent_session_id != sid
            or record.daily_sequence != sequence
            or record.status != STATUS_RUNNING
            or record.runtime_instance_id != _PROCESS_INSTANCE_ID
        ):
            raise RuntimeError(
                "Science Lab experiment read-back identity is inconsistent"
            )
        return record

    def end_user(self) -> ScienceLabExperimentRecord:
        record = self.current()
        if record is None:
            raise RuntimeError("no Science Lab experiment is running")
        _require_current_process(record)

        ended_at_utc = _utc_now()
        ended_monotonic_ns = time.monotonic_ns()
        self._storage.complete_science_lab_experiment(
            experiment_id=record.experiment_id,
            parent_session_id=record.parent_session_id,
            ended_at_utc=ended_at_utc,
            ended_monotonic_ns=ended_monotonic_ns,
            end_reason=END_REASON_USER,
        )

        completed = read_science_lab_experiment(record.experiment_id)
        if (
            completed is None
            or completed.status != STATUS_COMPLETED
            or completed.end_reason != END_REASON_USER
            or completed.ended_monotonic_ns != ended_monotonic_ns
        ):
            raise RuntimeError(
                "Science Lab experiment completion was not durably readable"
            )
        return completed

    def end_for_parent_session(
        self,
        parent_session_id: int,
    ) -> ScienceLabExperimentRecord | None:
        sid = _parent_session_id(parent_session_id)
        record = self.current()
        if record is None:
            return None
        if record.parent_session_id != sid:
            raise RuntimeError(
                "running Science Lab experiment belongs to another parent session"
            )
        _require_current_process(record)

        ended_at_utc = _utc_now()
        ended_monotonic_ns = time.monotonic_ns()
        self._storage.complete_science_lab_experiment(
            experiment_id=record.experiment_id,
            parent_session_id=sid,
            ended_at_utc=ended_at_utc,
            ended_monotonic_ns=ended_monotonic_ns,
            end_reason=END_REASON_PARENT_SESSION,
        )

        completed = read_science_lab_experiment(record.experiment_id)
        if (
            completed is None
            or completed.status != STATUS_COMPLETED
            or completed.end_reason != END_REASON_PARENT_SESSION
            or completed.ended_monotonic_ns != ended_monotonic_ns
        ):
            raise RuntimeError(
                "parent-session experiment completion was not durably readable"
            )
        return completed

    def recover_stale_from_previous_process(
        self,
    ) -> ScienceLabExperimentRecord | None:
        record = self.current()
        if record is None:
            return None
        if record.runtime_instance_id == _PROCESS_INSTANCE_ID:
            return record

        interrupted_at_utc = _utc_now()
        changed = self._storage.interrupt_stale_science_lab_experiment(
            experiment_id=record.experiment_id,
            current_runtime_instance_id=_PROCESS_INSTANCE_ID,
            interrupted_at_utc=interrupted_at_utc,
        )
        if not changed:
            raise RuntimeError(
                "stale Science Lab experiment was not durably interrupted"
            )

        interrupted = read_science_lab_experiment(record.experiment_id)
        if (
            interrupted is None
            or interrupted.experiment_id != record.experiment_id
            or interrupted.status != STATUS_INTERRUPTED
            or interrupted.end_reason != END_REASON_CRASH
            or interrupted.ended_at_utc != interrupted_at_utc
            or interrupted.ended_monotonic_ns is not None
        ):
            raise RuntimeError(
                "Science Lab interruption was not durably readable"
            )
        return interrupted


__all__ = [
    "END_REASON_CRASH",
    "END_REASON_PARENT_SESSION",
    "END_REASON_USER",
    "STATUS_COMPLETED",
    "STATUS_INTERRUPTED",
    "STATUS_RUNNING",
    "ScienceLabExperimentLifecycle",
    "contains_completed_window",
]
