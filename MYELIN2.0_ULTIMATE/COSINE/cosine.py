"""The single COSINE runtime and state authority for MYELIN.

COSINE is the choice-oriented streaming companion.  This file owns its
timers, state, commands, platform continuity and durable event contracts.
It contains no Qt, SQL, Windows polling or report calculations.

Strict operating order
----------------------
1. The Core Engine supplies certified process/host evidence.
2. COSINE counts foreground OTT time with a monotonic clock.
3. A check-in request is durably admitted before presentation is requested.
4. The popup reports DISPLAYED before the COSINE session becomes active.
5. A user command mutates state only after its event batch is durably accepted.
6. Return-to-focus requires continuous confirmed-focus evidence.

Window title is supporting content text only.  It can never select an OTT
platform, begin a session, continue a session or transfer Hopper identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final, Protocol


COSINE_SCHEMA_VERSION: Final = "myelin-cosine-v2"
INITIAL_CHECKIN_SECONDS: Final = (23 * 60) + 15
TEN_MORE_MINUTES_SECONDS: Final = 10 * 60
POPUP_RESPONSE_SECONDS: Final = 5 * 60
RETURN_CONFIRMATION_SECONDS: Final = 5 * 60
MAX_CONTENT_TITLE: Final = 300


PLATFORM_LABELS: Final = {
    "netflix": "Netflix",
    "prime_video": "Prime Video",
    "jiohotstar": "JioHotstar",
    "disney_plus": "Disney+",
    "hulu": "Hulu",
    "hbo_max": "HBO Max",
    "apple_tv_plus": "Apple TV+",
    "paramount_plus": "Paramount+",
}
PLATFORM_KEYS: Final = frozenset(PLATFORM_LABELS)

_HOST_PLATFORM: Final = {
    "netflix.com": "netflix",
    "primevideo.com": "prime_video",
    "amazon.com": "prime_video",
    "jiohotstar.com": "jiohotstar",
    "hotstar.com": "jiohotstar",
    "disneyplus.com": "disney_plus",
    "hulu.com": "hulu",
    "max.com": "hbo_max",
    "hbomax.com": "hbo_max",
    "tv.apple.com": "apple_tv_plus",
    "paramountplus.com": "paramount_plus",
}

# Exact executable basenames only.  Substrings and title words are forbidden.
_PROCESS_PLATFORM: Final = {
    "netflix.exe": "netflix",
    "primevideo.exe": "prime_video",
    "amazonprimevideo.exe": "prime_video",
    "jiohotstar.exe": "jiohotstar",
    "hotstar.exe": "jiohotstar",
    "disneyplus.exe": "disney_plus",
    "hulu.exe": "hulu",
    "hbomax.exe": "hbo_max",
    "max.exe": "hbo_max",
    "appletv.exe": "apple_tv_plus",
    "paramountplus.exe": "paramount_plus",
}
_CERTIFIED_BROWSER_PROCESSES: Final = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "brave.exe",
        "vivaldi.exe",
        "opera.exe",
        "opera_gx.exe",
    }
)


class CosinePhase(str, Enum):
    IDLE = "IDLE"
    QUALIFYING = "QUALIFYING"
    CHECKIN_PENDING = "CHECKIN_PENDING"
    ACTIVE = "ACTIVE"
    RETURN_PENDING = "RETURN_PENDING"
    CLOSED = "CLOSED"
    SHUTDOWN = "SHUTDOWN"


class CheckinMode(str, Enum):
    INITIAL = "INITIAL"
    TEN_MORE_MIN = "TEN_MORE_MIN"
    FINISH_MY_SHOW = "FINISH_MY_SHOW"
    CONTINUED_WATCHING = "CONTINUED_WATCHING"


class CosineChoice(str, Enum):
    TEN_MORE_MIN = "TEN_MORE_MIN"
    FINISH_MY_SHOW = "FINISH_MY_SHOW"
    YAY = "YAY"
    IM_TIRED = "IM_TIRED"


class CommandKind(str, Enum):
    CHECKIN_DISPLAYED = "CHECKIN_DISPLAYED"
    CHECKIN_ACTION = "CHECKIN_ACTION"
    CHECKIN_EXPIRED = "CHECKIN_EXPIRED"
    WELCOME_DISPLAYED = "WELCOME_DISPLAYED"
    WELCOME_ACTION = "WELCOME_ACTION"
    WELCOME_EXPIRED = "WELCOME_EXPIRED"


class ClosureReason(str, Enum):
    RETURNED_TO_FOCUS = "RETURNED_TO_FOCUS"
    SINE_HANDOFF = "SINE_HANDOFF"
    STOPPED = "STOPPED"
    EMERGENCY = "EMERGENCY"
    SYSTEM_LOCK = "SYSTEM_LOCK"
    SYSTEM_SLEEP = "SYSTEM_SLEEP"
    NOT_ENOUGH_INFORMATION = "NOT_ENOUGH_INFORMATION"


class EffectKind(str, Enum):
    SHOW_CHECKIN = "SHOW_CHECKIN"
    CLOSE_CHECKIN = "CLOSE_CHECKIN"
    SHOW_WELCOME = "SHOW_WELCOME"
    CLOSE_WELCOME = "CLOSE_WELCOME"
    REQUEST_NORMAL_STOP = "REQUEST_NORMAL_STOP"


class EvidenceSource(str, Enum):
    CERTIFIED_HOST = "CERTIFIED_HOST"
    NATIVE_PROCESS = "NATIVE_PROCESS"


class EventClass(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    USER_ACTION = "USER_ACTION"
    PRESENTATION = "PRESENTATION"


@dataclass(frozen=True, slots=True)
class CosinePolicy:
    initial_checkin_seconds: float = INITIAL_CHECKIN_SECONDS
    ten_more_minutes_seconds: float = TEN_MORE_MINUTES_SECONDS
    popup_response_seconds: float = POPUP_RESPONSE_SECONDS
    return_confirmation_seconds: float = RETURN_CONFIRMATION_SECONDS

    def __post_init__(self) -> None:
        for name, value in (
            ("initial_checkin_seconds", self.initial_checkin_seconds),
            ("ten_more_minutes_seconds", self.ten_more_minutes_seconds),
            ("popup_response_seconds", self.popup_response_seconds),
            ("return_confirmation_seconds", self.return_confirmation_seconds),
        ):
            if not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class CertifiedPlatformEvidence:
    """Exact OTT identity supplied to COSINE by the monitoring boundary."""

    platform_key: str
    source: EvidenceSource
    process_name: str
    process_id: int
    hwnd: int
    certified_host: str
    evidence_token: str
    observed_monotonic_ns: int
    content_title: str = ""

    def __post_init__(self) -> None:
        if self.platform_key not in PLATFORM_KEYS:
            raise ValueError("platform_key is not managed by COSINE")
        if not isinstance(self.source, EvidenceSource):
            raise TypeError("source must be EvidenceSource")
        if not self.process_name or self.process_id <= 0 or self.hwnd <= 0:
            raise ValueError("platform evidence requires an exact foreground window")
        if self.observed_monotonic_ns <= 0 or not self.evidence_token:
            raise ValueError("platform evidence requires time and identity")
        if self.source is EvidenceSource.CERTIFIED_HOST and not self.certified_host:
            raise ValueError("browser platform evidence requires a certified host")


@dataclass(frozen=True, slots=True)
class CosineObservation:
    """One already-observed foreground fact; no detection occurs here."""

    platform: CertifiedPlatformEvidence | None
    focus_confirmed: bool
    sine_popup_displayed: bool
    observed_monotonic_ns: int

    def __post_init__(self) -> None:
        if self.observed_monotonic_ns <= 0:
            raise ValueError("observation monotonic time must be positive")
        if self.platform is not None and (
            self.platform.observed_monotonic_ns != self.observed_monotonic_ns
        ):
            raise ValueError("platform and observation time must describe one sample")
        if type(self.focus_confirmed) is not bool or type(self.sine_popup_displayed) is not bool:
            raise TypeError("observation flags must be booleans")


@dataclass(frozen=True, slots=True)
class CosineCommand:
    kind: CommandKind
    generation: int
    request_id: str
    choice: CosineChoice | None = None
    occurred_monotonic_ns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CommandKind):
            raise TypeError("command kind is invalid")
        if self.generation < 0 or not self.request_id:
            raise ValueError("command identity is invalid")
        if self.occurred_monotonic_ns <= 0:
            raise ValueError("command monotonic time must be positive")


@dataclass(frozen=True, slots=True)
class CosineEvent:
    """Durable append-only fact; persistence must retain this identity."""

    event_id: str
    cosine_session_id: str
    sequence: int
    event_name: str
    event_class: EventClass
    occurred_at_utc: str
    monotonic_ns: int
    generation: int
    platform_key: str
    content_title: str
    request_id: str
    evidence_token: str
    payload_json: str
    schema_version: str = COSINE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CosineEffect:
    kind: EffectKind
    generation: int
    request_id: str
    platform_key: str = ""
    content_title: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class PlatformSnapshot:
    platform_key: str
    foreground_seconds: float
    mode: CheckinMode
    content_title: str
    content_history: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CosineSnapshot:
    phase: CosinePhase
    generation: int
    cosine_session_id: str
    current_platform_key: str
    current_platform_label: str
    current_content_title: str
    foreground_ott_seconds: float
    current_platform_seconds: float
    qualification_seconds: float
    checkin_request_id: str
    checkin_displayed: bool
    checkin_response_remaining_seconds: float
    return_confirmation_remaining_seconds: float
    return_focus_continuous: bool
    welcome_request_id: str
    welcome_pending: bool
    closure_reason: str
    durable_health: bool
    durable_detail: str
    platforms: tuple[PlatformSnapshot, ...]
    schema_version: str = COSINE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CommandResult:
    accepted: bool
    close_popup: bool
    message: str
    snapshot: CosineSnapshot


class CosineEventSink(Protocol):
    """Persistence must atomically accept a complete transition batch."""

    def append_cosine_events(self, events: tuple[CosineEvent, ...]) -> bool: ...


@dataclass(slots=True)
class _PlatformState:
    platform_key: str
    foreground_ns: int = 0
    qualification_ns: int = 0
    grace_ns: int = 0
    mode: CheckinMode = CheckinMode.INITIAL
    content_title: str = ""
    content_history: tuple[str, ...] = ()


@dataclass(slots=True)
class _PendingCheckin:
    request_id: str
    platform_key: str
    requested_ns: int
    displayed_ns: int = 0


def certify_platform_evidence(
    *,
    process_name: object,
    process_id: int,
    hwnd: int,
    observed_monotonic_ns: int,
    browser_authoritative: bool = False,
    certified_host: object = "",
    window_title: object = "",
) -> CertifiedPlatformEvidence | None:
    """Build OTT evidence without consulting ``window_title`` for identity.

    For browsers, ``certified_host`` must come from the certified address-bar
    reader and ``browser_authoritative`` must be true.  For native apps, the
    exact executable basename is used.  A title such as "Netflix research" in
    Word, VS Code or an unknown browser page returns ``None``.
    """

    process = _process_name(process_name)
    host = _host_name(certified_host)
    source: EvidenceSource | None = None
    platform = _PROCESS_PLATFORM.get(process)
    if platform:
        source = EvidenceSource.NATIVE_PROCESS
        host = ""
    elif (
        process in _CERTIFIED_BROWSER_PROCESSES
        and browser_authoritative
        and host
    ):
        platform = next(
            (
                key
                for domain, key in _HOST_PLATFORM.items()
                if host == domain or host.endswith(f".{domain}")
            ),
            None,
        )
        if platform:
            source = EvidenceSource.CERTIFIED_HOST
    if not platform or source is None:
        return None
    try:
        pid = int(process_id)
        window = int(hwnd)
        observed_ns = int(observed_monotonic_ns)
    except (TypeError, ValueError):
        return None
    if pid <= 0 or window <= 0 or observed_ns <= 0:
        return None
    token = hashlib.sha256(
        f"{source.value}|{platform}|{process}|{pid}|{window}|{host}".encode()
    ).hexdigest()[:32]
    return CertifiedPlatformEvidence(
        platform_key=platform,
        source=source,
        process_name=process,
        process_id=pid,
        hwnd=window,
        certified_host=host,
        evidence_token=token,
        observed_monotonic_ns=observed_ns,
        content_title=_supporting_title(window_title, platform),
    )


class CosineRuntime:
    """Thread-safe owner of one COSINE lifecycle."""

    def __init__(
        self,
        *,
        event_sink: CosineEventSink,
        policy: CosinePolicy = CosinePolicy(),
        wall_clock_utc: Callable[[], datetime] | None = None,
    ) -> None:
        if event_sink is None:
            raise ValueError("CosineRuntime requires a durable event sink")
        self._sink = event_sink
        self._policy = policy
        self._wall_clock = wall_clock_utc or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._phase = CosinePhase.IDLE
        self._generation = 0
        self._session_id = ""
        self._event_sequence = 0
        self._platforms: dict[str, _PlatformState] = {}
        self._current_platform = ""
        self._last_evidence_token = ""
        self._last_observed_ns = 0
        self._last_foreground_platform = ""
        self._pending: _PendingCheckin | None = None
        self._return_started_ns = 0
        self._last_checkin_displayed_ns = 0
        self._welcome_request_id = ""
        self._welcome_pending = False
        self._continued_watching = False
        self._closure_reason = ""
        self._durable_health = True
        self._durable_detail = ""
        self._effects: list[CosineEffect] = []

    def snapshot(self, *, now_ns: int | None = None) -> CosineSnapshot:
        with self._lock:
            current_ns = _now_ns(now_ns)
            total_ns = sum(state.foreground_ns for state in self._platforms.values())
            current = self._platforms.get(self._current_platform)
            response_remaining = 0.0
            if self._pending and self._pending.displayed_ns:
                response_remaining = max(
                    0.0,
                    self._policy.popup_response_seconds
                    - ((current_ns - self._pending.displayed_ns) / 1e9),
                )
            return_remaining = 0.0
            if self._return_started_ns:
                return_remaining = max(
                    0.0,
                    self._policy.return_confirmation_seconds
                    - ((current_ns - self._return_started_ns) / 1e9),
                )
            return CosineSnapshot(
                phase=self._phase,
                generation=self._generation,
                cosine_session_id=self._session_id,
                current_platform_key=self._current_platform,
                current_platform_label=PLATFORM_LABELS.get(self._current_platform, ""),
                current_content_title=current.content_title if current else "",
                foreground_ott_seconds=total_ns / 1e9,
                current_platform_seconds=(current.foreground_ns / 1e9 if current else 0.0),
                qualification_seconds=(current.qualification_ns / 1e9 if current else 0.0),
                checkin_request_id=self._pending.request_id if self._pending else "",
                checkin_displayed=bool(self._pending and self._pending.displayed_ns),
                checkin_response_remaining_seconds=response_remaining,
                return_confirmation_remaining_seconds=return_remaining,
                return_focus_continuous=bool(self._return_started_ns),
                welcome_request_id=self._welcome_request_id,
                welcome_pending=self._welcome_pending,
                closure_reason=self._closure_reason,
                durable_health=self._durable_health,
                durable_detail=self._durable_detail,
                platforms=tuple(
                    PlatformSnapshot(
                        state.platform_key,
                        state.foreground_ns / 1e9,
                        state.mode,
                        state.content_title,
                        state.content_history,
                    )
                    for state in self._platforms.values()
                ),
            )

    def observe(self, observation: CosineObservation) -> tuple[CosineEffect, ...]:
        """Consume one certified foreground sample in monotonic order."""

        with self._lock:
            if self._phase is CosinePhase.SHUTDOWN:
                return ()
            now_ns = observation.observed_monotonic_ns
            if self._last_observed_ns and now_ns < self._last_observed_ns:
                return ()
            self._credit_previous(now_ns)

            if observation.sine_popup_displayed:
                self._close(ClosureReason.SINE_HANDOFF, now_ns)
            elif self._phase in {CosinePhase.IDLE, CosinePhase.CLOSED}:
                if observation.platform is not None:
                    self._start_qualification(observation.platform, now_ns)
            elif self._phase in {CosinePhase.QUALIFYING, CosinePhase.CHECKIN_PENDING}:
                self._observe_qualifying(observation.platform, now_ns)
            else:
                self._observe_active(observation, now_ns)

            self._expire_checkin_if_due(now_ns)
            self._last_observed_ns = now_ns
            self._last_foreground_platform = (
                observation.platform.platform_key if observation.platform else ""
            )
            if observation.platform:
                self._last_evidence_token = observation.platform.evidence_token
            return self.drain_effects()

    def advance(self, *, now_ns: int | None = None) -> tuple[CosineEffect, ...]:
        """Advance deadlines using the last exact foreground fact."""

        with self._lock:
            current_ns = _now_ns(now_ns)
            if self._last_observed_ns and current_ns < self._last_observed_ns:
                return ()
            self._credit_previous(current_ns)
            if self._phase is CosinePhase.QUALIFYING and self._current_platform:
                self._request_checkin_if_due(self._current_platform, current_ns)
            if self._phase is CosinePhase.RETURN_PENDING:
                self._confirm_return_if_due(current_ns)
            self._expire_checkin_if_due(current_ns)
            self._last_observed_ns = current_ns
            return self.drain_effects()

    def submit_command(self, command: CosineCommand) -> CommandResult:
        """Accept one popup command only after its event is durable."""

        with self._lock:
            if command.generation != self._generation:
                return self._reject("COSINE generation changed")
            if command.kind in {
                CommandKind.WELCOME_DISPLAYED,
                CommandKind.WELCOME_ACTION,
                CommandKind.WELCOME_EXPIRED,
            }:
                return self._handle_welcome(command)
            pending = self._pending
            if pending is None or command.request_id != pending.request_id:
                return self._reject("Check-in request is no longer current")

            if command.kind is CommandKind.CHECKIN_DISPLAYED:
                if pending.displayed_ns:
                    return CommandResult(True, False, "Check-in already displayed", self.snapshot(now_ns=command.occurred_monotonic_ns))
                if not self._commit(
                    "CHECKIN_DISPLAYED",
                    EventClass.PRESENTATION,
                    command.occurred_monotonic_ns,
                    platform=pending.platform_key,
                    request_id=pending.request_id,
                ):
                    return self._reject("Display acknowledgement was not durably accepted")
                pending.displayed_ns = command.occurred_monotonic_ns
                self._last_checkin_displayed_ns = command.occurred_monotonic_ns
                self._phase = CosinePhase.ACTIVE
                return CommandResult(True, False, "Check-in display accepted", self.snapshot(now_ns=command.occurred_monotonic_ns))

            if not pending.displayed_ns:
                return self._reject("Check-in was not acknowledged as displayed")
            if command.kind is CommandKind.CHECKIN_EXPIRED:
                return self._accept_unanswered(command.occurred_monotonic_ns)
            if command.kind is not CommandKind.CHECKIN_ACTION or command.choice not in {
                CosineChoice.TEN_MORE_MIN,
                CosineChoice.FINISH_MY_SHOW,
            }:
                return self._reject("Check-in action is invalid")
            choice = command.choice
            if not self._commit(
                "CHECKIN_ANSWERED",
                EventClass.USER_ACTION,
                command.occurred_monotonic_ns,
                platform=pending.platform_key,
                request_id=pending.request_id,
                payload={
                    "choice": choice.value,
                    "response_seconds": max(
                        0.0,
                        (command.occurred_monotonic_ns - pending.displayed_ns) / 1e9,
                    ),
                },
            ):
                return self._reject("Your choice was not durably accepted; please retry")
            state = self._platform(pending.platform_key)
            state.mode = (
                CheckinMode.TEN_MORE_MIN
                if choice is CosineChoice.TEN_MORE_MIN
                else CheckinMode.FINISH_MY_SHOW
            )
            if choice is CosineChoice.TEN_MORE_MIN:
                state.grace_ns = 0
            self._effects.append(
                CosineEffect(
                    EffectKind.CLOSE_CHECKIN,
                    self._generation,
                    pending.request_id,
                    pending.platform_key,
                )
            )
            self._pending = None
            self._phase = CosinePhase.ACTIVE
            return CommandResult(True, True, "Choice accepted", self.snapshot(now_ns=command.occurred_monotonic_ns))

    def close(
        self,
        reason: ClosureReason,
        *,
        now_ns: int | None = None,
    ) -> tuple[CosineEffect, ...]:
        with self._lock:
            current_ns = _now_ns(now_ns)
            self._credit_previous(current_ns)
            self._close(reason, current_ns)
            self._last_observed_ns = current_ns
            return self.drain_effects()

    def shutdown(self, *, now_ns: int | None = None) -> bool:
        with self._lock:
            if self._phase is CosinePhase.SHUTDOWN:
                return True
            current_ns = _now_ns(now_ns)
            if self._session_id and self._phase is not CosinePhase.CLOSED:
                self._credit_previous(current_ns)
                if not self._close(ClosureReason.STOPPED, current_ns):
                    return False
            self._phase = CosinePhase.SHUTDOWN
            return True

    def drain_effects(self) -> tuple[CosineEffect, ...]:
        effects = tuple(self._effects)
        self._effects.clear()
        return effects

    # ------------------------------------------------------------------
    # Internal state transitions.
    # ------------------------------------------------------------------

    def _start_qualification(self, evidence: CertifiedPlatformEvidence, now_ns: int) -> None:
        session_id = secrets.token_hex(16)
        self._generation += 1
        self._session_id = session_id
        self._event_sequence = 0
        self._closure_reason = ""
        self._platforms = {evidence.platform_key: _PlatformState(evidence.platform_key)}
        if not self._commit(
            "OTT_QUALIFICATION_STARTED",
            EventClass.OBSERVED,
            now_ns,
            platform=evidence.platform_key,
            content=evidence.content_title,
            evidence_token=evidence.evidence_token,
            payload={"evidence_source": evidence.source.value},
        ):
            self._reset_idle()
            return
        self._phase = CosinePhase.QUALIFYING
        self._current_platform = evidence.platform_key
        self._last_evidence_token = evidence.evidence_token
        self._record_content(evidence, now_ns)

    def _observe_qualifying(
        self,
        evidence: CertifiedPlatformEvidence | None,
        now_ns: int,
    ) -> None:
        if evidence is None:
            self._cancel_qualification(now_ns)
            return
        if evidence.platform_key != self._current_platform:
            self._cancel_qualification(now_ns)
            self._start_qualification(evidence, now_ns)
            return
        self._record_content(evidence, now_ns)
        self._request_checkin_if_due(evidence.platform_key, now_ns)

    def _observe_active(self, observation: CosineObservation, now_ns: int) -> None:
        evidence = observation.platform
        if evidence is not None:
            if self._return_started_ns:
                self._commit(
                    "RETURN_CONFIRMATION_CANCELLED",
                    EventClass.OBSERVED,
                    now_ns,
                    platform=evidence.platform_key,
                    payload={"reason": "OTT_RESUMED"},
                )
                self._return_started_ns = 0
            if evidence.platform_key != self._current_platform:
                previous = self._current_platform
                if not self._commit(
                    "HOPPER_TRANSITION",
                    EventClass.OBSERVED,
                    now_ns,
                    platform=evidence.platform_key,
                    content=evidence.content_title,
                    evidence_token=evidence.evidence_token,
                    payload={"from_platform": previous, "to_platform": evidence.platform_key},
                ):
                    return
                self._current_platform = evidence.platform_key
                self._platform(evidence.platform_key)
            self._phase = CosinePhase.ACTIVE
            self._record_content(evidence, now_ns)
            self._request_checkin_if_due(evidence.platform_key, now_ns)
            return

        # Repair of the old false-return bug: non-OTT is insufficient.
        if not observation.focus_confirmed:
            if self._return_started_ns:
                self._commit(
                    "RETURN_CONFIRMATION_CANCELLED",
                    EventClass.OBSERVED,
                    now_ns,
                    payload={"reason": "FOCUS_NOT_CONFIRMED"},
                )
                self._return_started_ns = 0
            self._phase = CosinePhase.ACTIVE
            return
        if not self._return_started_ns:
            if not self._commit(
                "RETURN_CONFIRMATION_STARTED",
                EventClass.OBSERVED,
                now_ns,
                payload={"continuous_focus_required_seconds": self._policy.return_confirmation_seconds},
            ):
                return
            self._return_started_ns = now_ns
            self._phase = CosinePhase.RETURN_PENDING
        self._confirm_return_if_due(now_ns)

    def _confirm_return_if_due(self, now_ns: int) -> None:
        if not self._return_started_ns:
            return
        verified = (now_ns - self._return_started_ns) / 1e9
        if verified < self._policy.return_confirmation_seconds:
            return
        return_time = (
            max(0.0, (self._return_started_ns - self._last_checkin_displayed_ns) / 1e9)
            if self._last_checkin_displayed_ns
            else None
        )
        if not self._commit_many(
            (
                (
                    "RETURN_CONFIRMED",
                    EventClass.DERIVED,
                    {"verification_seconds": verified, "return_time_seconds": return_time},
                ),
                (
                    "COSINE_SESSION_CLOSED",
                    EventClass.DERIVED,
                    self._closure_payload(ClosureReason.RETURNED_TO_FOCUS),
                ),
            ),
            now_ns,
        ):
            return
        self._closure_reason = ClosureReason.RETURNED_TO_FOCUS.value
        self._phase = CosinePhase.CLOSED
        self._return_started_ns = 0
        self._close_pending_effect()
        if self._continued_watching:
            self._welcome_request_id = f"cosine-welcome-{self._generation}-{secrets.token_hex(4)}"
            self._welcome_pending = True
            self._effects.append(
                CosineEffect(
                    EffectKind.SHOW_WELCOME,
                    self._generation,
                    self._welcome_request_id,
                    message="Welcome back",
                )
            )

    def _request_checkin_if_due(self, platform_key: str, now_ns: int) -> None:
        if self._pending is not None:
            return
        state = self._platform(platform_key)
        due = (
            state.mode is CheckinMode.INITIAL
            and state.qualification_ns / 1e9 >= self._policy.initial_checkin_seconds
        ) or (
            state.mode is CheckinMode.TEN_MORE_MIN
            and state.grace_ns / 1e9 >= self._policy.ten_more_minutes_seconds
        )
        if not due or state.mode in {
            CheckinMode.FINISH_MY_SHOW,
            CheckinMode.CONTINUED_WATCHING,
        }:
            return
        request_id = f"cosine-{self._generation}-{secrets.token_hex(6)}"
        if not self._commit(
            "CHECKIN_REQUESTED",
            EventClass.DERIVED,
            now_ns,
            platform=platform_key,
            content=state.content_title,
            request_id=request_id,
            payload={"mode": state.mode.value},
        ):
            return
        self._pending = _PendingCheckin(request_id, platform_key, now_ns)
        self._phase = CosinePhase.CHECKIN_PENDING
        self._effects.append(
            CosineEffect(
                EffectKind.SHOW_CHECKIN,
                self._generation,
                request_id,
                platform_key,
                state.content_title,
                "COSINE streaming check-in",
            )
        )

    def _expire_checkin_if_due(self, now_ns: int) -> None:
        pending = self._pending
        if not pending or not pending.displayed_ns:
            return
        if (now_ns - pending.displayed_ns) / 1e9 < self._policy.popup_response_seconds:
            return
        self._accept_unanswered(now_ns)

    def _accept_unanswered(self, now_ns: int) -> CommandResult:
        pending = self._pending
        if pending is None or not pending.displayed_ns:
            return self._reject("No displayed check-in is awaiting expiry")
        if not self._commit(
            "CONTINUED_WATCHING",
            EventClass.DERIVED,
            now_ns,
            platform=pending.platform_key,
            request_id=pending.request_id,
            payload={"response_seconds": None},
        ):
            return self._reject("Expiry was not durably accepted; popup remains open")
        self._platform(pending.platform_key).mode = CheckinMode.CONTINUED_WATCHING
        self._continued_watching = True
        self._effects.append(
            CosineEffect(
                EffectKind.CLOSE_CHECKIN,
                self._generation,
                pending.request_id,
                pending.platform_key,
            )
        )
        self._pending = None
        self._phase = CosinePhase.ACTIVE
        return CommandResult(True, True, "Continued watching recorded", self.snapshot(now_ns=now_ns))

    def _handle_welcome(self, command: CosineCommand) -> CommandResult:
        if not self._welcome_pending or command.request_id != self._welcome_request_id:
            return self._reject("Welcome Back request is no longer current")
        if command.kind is CommandKind.WELCOME_DISPLAYED:
            event_name = "WELCOME_BACK_DISPLAYED"
            event_class = EventClass.PRESENTATION
        elif command.kind is CommandKind.WELCOME_EXPIRED:
            event_name = "WELCOME_BACK_EXPIRED"
            event_class = EventClass.DERIVED
        elif command.kind is CommandKind.WELCOME_ACTION and command.choice in {
            CosineChoice.YAY,
            CosineChoice.IM_TIRED,
        }:
            event_name = "WELCOME_BACK_ANSWERED"
            event_class = EventClass.USER_ACTION
        else:
            return self._reject("Welcome Back action is invalid")
        if not self._commit(
            event_name,
            event_class,
            command.occurred_monotonic_ns,
            request_id=command.request_id,
            payload={"choice": command.choice.value if command.choice else ""},
        ):
            return self._reject("Welcome Back action was not durably accepted")
        close = command.kind is not CommandKind.WELCOME_DISPLAYED
        if close:
            self._welcome_pending = False
            self._effects.append(
                CosineEffect(EffectKind.CLOSE_WELCOME, self._generation, command.request_id)
            )
            if command.choice is CosineChoice.IM_TIRED:
                self._effects.append(
                    CosineEffect(EffectKind.REQUEST_NORMAL_STOP, self._generation, command.request_id)
                )
        return CommandResult(True, close, "Welcome Back action accepted", self.snapshot(now_ns=command.occurred_monotonic_ns))

    def _cancel_qualification(self, now_ns: int) -> None:
        if self._session_id:
            self._commit(
                "OTT_QUALIFICATION_CANCELLED",
                EventClass.OBSERVED,
                now_ns,
                platform=self._current_platform,
            )
        self._close_pending_effect()
        self._reset_idle()

    def _close(self, reason: ClosureReason, now_ns: int) -> bool:
        if not isinstance(reason, ClosureReason):
            raise TypeError("reason must be ClosureReason")
        if not self._session_id or self._phase in {CosinePhase.IDLE, CosinePhase.CLOSED}:
            self._closure_reason = reason.value
            self._phase = CosinePhase.CLOSED if self._session_id else CosinePhase.IDLE
            return True
        if not self._commit(
            "COSINE_SESSION_CLOSED",
            EventClass.DERIVED,
            now_ns,
            platform=self._current_platform,
            payload=self._closure_payload(reason),
        ):
            return False
        self._closure_reason = reason.value
        self._phase = CosinePhase.CLOSED
        self._return_started_ns = 0
        self._close_pending_effect()
        return True

    def _closure_payload(self, reason: ClosureReason) -> dict[str, object]:
        platform_seconds = {
            key: round(state.foreground_ns / 1e9, 6)
            for key, state in self._platforms.items()
        }
        return {
            "closure_reason": reason.value,
            "foreground_ott_seconds": round(sum(platform_seconds.values()), 6),
            "platform_seconds": platform_seconds,
            "platform_modes": {
                key: state.mode.value for key, state in self._platforms.items()
            },
        }

    def _close_pending_effect(self) -> None:
        if self._pending:
            self._effects.append(
                CosineEffect(
                    EffectKind.CLOSE_CHECKIN,
                    self._generation,
                    self._pending.request_id,
                    self._pending.platform_key,
                )
            )
            self._pending = None

    def _record_content(self, evidence: CertifiedPlatformEvidence, now_ns: int) -> None:
        title = evidence.content_title
        if not title:
            return
        state = self._platform(evidence.platform_key)
        if state.content_title.casefold() == title.casefold():
            return
        if not self._commit(
            "CONTENT_OBSERVED",
            EventClass.OBSERVED,
            now_ns,
            platform=evidence.platform_key,
            content=title,
            evidence_token=evidence.evidence_token,
        ):
            return
        state.content_title = title
        state.content_history = (*state.content_history, title)[-100:]

    def _credit_previous(self, now_ns: int) -> None:
        if self._phase not in {
            CosinePhase.QUALIFYING,
            CosinePhase.CHECKIN_PENDING,
            CosinePhase.ACTIVE,
            CosinePhase.RETURN_PENDING,
        }:
            return
        if not self._last_observed_ns or now_ns <= self._last_observed_ns:
            return
        platform_key = self._last_foreground_platform
        if not platform_key or platform_key not in self._platforms:
            return
        elapsed = now_ns - self._last_observed_ns
        state = self._platforms[platform_key]
        state.foreground_ns += elapsed
        if self._phase in {CosinePhase.QUALIFYING, CosinePhase.CHECKIN_PENDING}:
            state.qualification_ns += elapsed
        elif state.mode is CheckinMode.TEN_MORE_MIN:
            state.grace_ns += elapsed

    def _platform(self, platform_key: str) -> _PlatformState:
        state = self._platforms.get(platform_key)
        if state is None:
            state = _PlatformState(platform_key)
            self._platforms[platform_key] = state
        return state

    def _commit_many(
        self,
        specs: tuple[tuple[str, EventClass, Mapping[str, object]], ...],
        now_ns: int,
    ) -> bool:
        events = tuple(
            self._make_event(name, event_class, now_ns, payload=payload, offset=index)
            for index, (name, event_class, payload) in enumerate(specs)
        )
        return self._append(events)

    def _commit(
        self,
        name: str,
        event_class: EventClass,
        now_ns: int,
        *,
        platform: str = "",
        content: str = "",
        request_id: str = "",
        evidence_token: str = "",
        payload: Mapping[str, object] | None = None,
    ) -> bool:
        return self._append(
            (
                self._make_event(
                    name,
                    event_class,
                    now_ns,
                    platform=platform,
                    content=content,
                    request_id=request_id,
                    evidence_token=evidence_token,
                    payload=payload,
                ),
            )
        )

    def _make_event(
        self,
        name: str,
        event_class: EventClass,
        now_ns: int,
        *,
        platform: str = "",
        content: str = "",
        request_id: str = "",
        evidence_token: str = "",
        payload: Mapping[str, object] | None = None,
        offset: int = 0,
    ) -> CosineEvent:
        wall = self._wall_clock()
        if wall.tzinfo is None or wall.utcoffset() is None:
            raise RuntimeError("COSINE wall clock must be timezone-aware")
        return CosineEvent(
            event_id=secrets.token_hex(16),
            cosine_session_id=self._session_id,
            sequence=self._event_sequence + 1 + offset,
            event_name=name,
            event_class=event_class,
            occurred_at_utc=wall.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            monotonic_ns=now_ns,
            generation=self._generation,
            platform_key=platform,
            content_title=_bounded_title(content),
            request_id=request_id,
            evidence_token=evidence_token,
            payload_json=json.dumps(
                dict(payload or {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )

    def _append(self, events: tuple[CosineEvent, ...]) -> bool:
        try:
            accepted = bool(self._sink.append_cosine_events(events))
        except Exception as exc:
            accepted = False
            detail = str(exc)
        else:
            detail = "durable event sink rejected the transition"
        if not accepted:
            self._durable_health = False
            self._durable_detail = " ".join(detail.split())[:240]
            return False
        self._durable_health = True
        self._durable_detail = ""
        self._event_sequence += len(events)
        return True

    def _reject(self, message: str) -> CommandResult:
        return CommandResult(False, False, message, self.snapshot())

    def _reset_idle(self) -> None:
        self._phase = CosinePhase.IDLE
        self._session_id = ""
        self._event_sequence = 0
        self._platforms.clear()
        self._current_platform = ""
        self._last_evidence_token = ""
        self._last_observed_ns = 0
        self._last_foreground_platform = ""
        self._pending = None
        self._return_started_ns = 0
        self._last_checkin_displayed_ns = 0
        self._welcome_request_id = ""
        self._welcome_pending = False
        self._continued_watching = False


def _process_name(value: object) -> str:
    text = str(value or "").strip().casefold().replace("\\", "/").rsplit("/", 1)[-1]
    return text if text.endswith(".exe") else f"{text}.exe" if text else ""


def _host_name(value: object) -> str:
    host = str(value or "").strip().casefold().strip(".")
    if "://" in host:
        # A caller should supply only a certified host; rejecting URL-shaped
        # text avoids accidentally accepting an unverified raw address.
        return ""
    return host if host and all(c.isalnum() or c in ".-" for c in host) else ""


def _supporting_title(value: object, platform_key: str) -> str:
    title = " ".join(str(value or "").split()).strip(" -|")
    if not title:
        return ""
    suffixes = (
        PLATFORM_LABELS.get(platform_key, ""),
        "Google Chrome",
        "Microsoft Edge",
        "Mozilla Firefox",
    )
    lowered = title.casefold()
    for suffix in suffixes:
        marker = f" - {suffix}".casefold()
        if suffix and lowered.endswith(marker):
            title = title[: -len(marker)].strip(" -|")
            lowered = title.casefold()
    generic = {"home", "browse", "who's watching", PLATFORM_LABELS.get(platform_key, "").casefold()}
    return "" if lowered in generic else _bounded_title(title)


def _bounded_title(value: object) -> str:
    return " ".join(str(value or "").split())[:MAX_CONTENT_TITLE]


def _now_ns(value: int | None) -> int:
    current = time.monotonic_ns() if value is None else int(value)
    if current <= 0:
        raise ValueError("monotonic time must be positive")
    return current


__all__ = [
    "COSINE_SCHEMA_VERSION",
    "CheckinMode",
    "ClosureReason",
    "CommandKind",
    "CommandResult",
    "CosineChoice",
    "CosineCommand",
    "CosineEffect",
    "CosineEvent",
    "CosineEventSink",
    "CosineObservation",
    "CosinePhase",
    "CosinePolicy",
    "CosineRuntime",
    "CosineSnapshot",
    "CertifiedPlatformEvidence",
    "EffectKind",
    "EventClass",
    "EvidenceSource",
    "PLATFORM_KEYS",
    "PLATFORM_LABELS",
    "PlatformSnapshot",
    "certify_platform_evidence",
]
