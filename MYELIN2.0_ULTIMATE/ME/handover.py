"""Thin 120-second sibling-continuity layer for MYELIN.

Phase 2A: isolated only. This module knows no organ physiology and calls nobody.
Only Monitor (Mom) may connect to it later.
"""

from dataclasses import dataclass
from typing import Any, Optional


HANDOVER_SECONDS = 120
HANDOVER_NS = HANDOVER_SECONDS * 1_000_000_000
VALID_SONS = frozenset({"SINE", "COSINE", "MINE"})


@dataclass(frozen=True)
class HandoverSnapshot:
    active: bool
    paused: bool
    state: str
    source: Optional[str]
    target: Optional[str]
    source_episode_key: Optional[Any]
    elapsed_seconds: float
    remaining_seconds: float
    total_seconds: int
    progress_fraction: float
    last_action: str
    last_reason: Optional[str]
    handover_count: int
    source_return_count: int
    target_switch_count: int
    expiry_count: int
    finish_count: int


@dataclass(frozen=True)
class HandoverResult:
    action: str
    reason: Optional[str]
    source: Optional[str]
    target: Optional[str]
    source_episode_key: Optional[Any]
    snapshot: HandoverSnapshot


class HandoverLayer:
    """Protect one source episode while one sibling is the current target."""

    def __init__(self) -> None:
        self._active = False
        self._paused = False
        self._source: Optional[str] = None
        self._target: Optional[str] = None
        self._source_episode_key: Optional[Any] = None
        self._started_ns: Optional[int] = None
        self._pause_started_ns: Optional[int] = None
        self._paused_total_ns = 0
        self._last_seen_ns: Optional[int] = None
        self._last_action = "NOOP"
        self._last_reason: Optional[str] = None

        # Runtime-only metrics. No database/persistence in Phase 2A.
        self._handover_count = 0
        self._source_return_count = 0
        self._target_switch_count = 0
        self._expiry_count = 0
        self._finish_count = 0

    def _check_now(self, now_ns: int) -> None:
        if isinstance(now_ns, bool) or not isinstance(now_ns, int):
            raise TypeError("now_ns must be an integer monotonic timestamp")
        if now_ns < 0:
            raise ValueError("now_ns must be >= 0")
        if self._last_seen_ns is not None and now_ns < self._last_seen_ns:
            raise ValueError("now_ns must not move backwards")
        self._last_seen_ns = now_ns

    @staticmethod
    def _check_son(son: str, name: str) -> None:
        if son not in VALID_SONS:
            raise ValueError(f"{name} must be SINE, COSINE, or MINE")

    def _elapsed_ns(self, now_ns: int) -> int:
        if not self._active or self._started_ns is None:
            return 0
        paused_now = 0
        if self._paused:
            if self._pause_started_ns is None:
                raise RuntimeError("frozen handover has no pause start")
            paused_now = now_ns - self._pause_started_ns
        return max(
            0,
            now_ns - self._started_ns - self._paused_total_ns - paused_now,
        )

    def _snapshot(self, now_ns: int) -> HandoverSnapshot:
        if self._active:
            elapsed_ns = min(self._elapsed_ns(now_ns), HANDOVER_NS)
            remaining_ns = max(0, HANDOVER_NS - elapsed_ns)
            progress = elapsed_ns / HANDOVER_NS
        else:
            elapsed_ns = 0
            remaining_ns = 0
            progress = 0.0

        state = "IDLE"
        if self._active:
            state = "FROZEN" if self._paused else "ACTIVE"

        return HandoverSnapshot(
            active=self._active,
            paused=self._paused,
            state=state,
            source=self._source,
            target=self._target,
            source_episode_key=self._source_episode_key,
            elapsed_seconds=elapsed_ns / 1_000_000_000,
            remaining_seconds=remaining_ns / 1_000_000_000,
            total_seconds=HANDOVER_SECONDS,
            progress_fraction=progress,
            last_action=self._last_action,
            last_reason=self._last_reason,
            handover_count=self._handover_count,
            source_return_count=self._source_return_count,
            target_switch_count=self._target_switch_count,
            expiry_count=self._expiry_count,
            finish_count=self._finish_count,
        )

    def _result(
        self,
        action: str,
        reason: Optional[str],
        source: Optional[str],
        target: Optional[str],
        source_episode_key: Optional[Any],
        now_ns: int,
    ) -> HandoverResult:
        return HandoverResult(
            action=action,
            reason=reason,
            source=source,
            target=target,
            source_episode_key=source_episode_key,
            snapshot=self._snapshot(now_ns),
        )

    def _clear(self) -> None:
        self._active = False
        self._paused = False
        self._source = None
        self._target = None
        self._source_episode_key = None
        self._started_ns = None
        self._pause_started_ns = None
        self._paused_total_ns = 0

    def _expire_if_due(self, now_ns: int) -> Optional[HandoverResult]:
        if not self._active or self._paused:
            return None
        if self._elapsed_ns(now_ns) < HANDOVER_NS:
            return None

        source, target, key = self._source, self._target, self._source_episode_key
        self._expiry_count += 1
        self._last_action = "EXPIRED"
        self._last_reason = "HANDOVER_EXPIRED"
        self._clear()
        return self._result(
            "EXPIRED", "HANDOVER_EXPIRED", source, target, key, now_ns
        )

    def start(
        self,
        source: str,
        target: str,
        source_episode_key: Any,
        now_ns: int,
    ) -> HandoverResult:
        self._check_now(now_ns)
        self._check_son(source, "source")
        self._check_son(target, "target")
        if source == target:
            raise ValueError("source and target must be different sons")
        if source_episode_key is None:
            raise ValueError("source_episode_key must not be None")
        if isinstance(source_episode_key, str) and not source_episode_key.strip():
            raise ValueError("source_episode_key must not be blank")
        if self._active:
            raise RuntimeError("a handover relationship is already active")

        self._active = True
        self._source = source
        self._target = target
        self._source_episode_key = source_episode_key
        self._started_ns = now_ns
        self._paused = False
        self._pause_started_ns = None
        self._paused_total_ns = 0
        self._handover_count += 1
        self._last_action = "STARTED"
        self._last_reason = None
        return self._result("STARTED", None, source, target, source_episode_key, now_ns)

    def switch_target(self, target: str, now_ns: int) -> HandoverResult:
        self._check_now(now_ns)
        self._check_son(target, "target")
        if not self._active:
            raise RuntimeError("no active handover relationship")
        if self._paused:
            raise RuntimeError("cannot switch target while handover is frozen")

        expired = self._expire_if_due(now_ns)
        if expired is not None:
            return expired

        if target == self._source:
            raise ValueError("target cannot be the protected source")
        if target == self._target:
            return self._result(
                "NOOP", None, self._source, self._target,
                self._source_episode_key, now_ns
            )

        self._target = target
        self._started_ns = now_ns
        self._paused_total_ns = 0
        self._target_switch_count += 1
        self._last_action = "TARGET_SWITCHED"
        self._last_reason = None
        return self._result(
            "TARGET_SWITCHED", None, self._source, self._target,
            self._source_episode_key, now_ns
        )

    def source_returned(self, now_ns: int) -> HandoverResult:
        self._check_now(now_ns)
        if not self._active:
            raise RuntimeError("no active handover relationship")
        if self._paused:
            raise RuntimeError("cannot process source return while handover is frozen")

        expired = self._expire_if_due(now_ns)
        if expired is not None:
            return expired

        source, target, key = self._source, self._target, self._source_episode_key
        self._source_return_count += 1
        self._last_action = "SOURCE_RETURNED"
        self._last_reason = "SOURCE_RETURNED"
        self._clear()
        return self._result(
            "SOURCE_RETURNED", "SOURCE_RETURNED", source, target, key, now_ns
        )

    def set_paused(self, paused: bool, now_ns: int) -> HandoverResult:
        self._check_now(now_ns)
        if not isinstance(paused, bool):
            raise TypeError("paused must be bool")
        if not self._active:
            return self._result("NOOP", None, None, None, None, now_ns)

        if paused and not self._paused:
            expired = self._expire_if_due(now_ns)
            if expired is not None:
                return expired
            self._paused = True
            self._pause_started_ns = now_ns
            self._last_action = "FROZEN"
            self._last_reason = "GLOBAL_PAUSE"
            return self._result(
                "FROZEN", "GLOBAL_PAUSE", self._source, self._target,
                self._source_episode_key, now_ns
            )

        if not paused and self._paused:
            if self._pause_started_ns is None:
                raise RuntimeError("frozen handover has no pause start")
            self._paused_total_ns += now_ns - self._pause_started_ns
            self._pause_started_ns = None
            self._paused = False
            self._last_action = "RESUMED"
            self._last_reason = "GLOBAL_PAUSE_RELEASED"
            return self._result(
                "RESUMED", "GLOBAL_PAUSE_RELEASED", self._source, self._target,
                self._source_episode_key, now_ns
            )

        return self._result(
            "NOOP", None, self._source, self._target,
            self._source_episode_key, now_ns
        )

    def finish(self, reason: str, now_ns: int) -> HandoverResult:
        self._check_now(now_ns)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("finish reason must be a non-blank string")
        if not self._active:
            return self._result("NOOP", reason, None, None, None, now_ns)

        source, target, key = self._source, self._target, self._source_episode_key
        self._finish_count += 1
        self._last_action = "FINISHED"
        self._last_reason = reason
        self._clear()
        return self._result("FINISHED", reason, source, target, key, now_ns)

    def advance(self, now_ns: int) -> HandoverResult:
        self._check_now(now_ns)
        expired = self._expire_if_due(now_ns)
        if expired is not None:
            return expired
        return self._result(
            "NOOP", None, self._source, self._target,
            self._source_episode_key, now_ns
        )

    def snapshot(self, now_ns: int) -> HandoverSnapshot:
        self._check_now(now_ns)
        return self._snapshot(now_ns)
