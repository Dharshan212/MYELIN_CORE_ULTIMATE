"""The single SINE state and escalation authority for MYELIN.

SINE owns the intervention sequence after ``CORE_ENGINE.trigger`` has durably
admitted one factual trigger.  It does not watch Windows, classify resources,
draw a popup, write MIRL truth, or grant a Study Material allowance.

The order is deliberately strict:

1. accept one durably admitted trigger;
2. request SINE 1;
3. wait for the UI to report that the popup was actually displayed;
4. keep every deadline on a monotonic clock;
5. request SINE 2 and SINE 3 only when their deadlines become due;
6. accept popup lifecycle facts and user responses through this authority; and
7. release Protected Red only after an authoritative recovery fact.

Scientific framing
------------------
SINE is the Weber–Fechner side of MYELIN: stronger factual behavioral evidence
is represented by progressively stronger intervention stages.  The canonical
logarithmic equation ``P = k * ln(I / I0)`` is implemented as a pure helper,
but MYELIN Core does not invent psychophysical ``I``, ``I0`` or ``k`` values.
The current Blue -> Amber -> Red state machine remains the Weber–Fechner
intervention ladder.

Timing contract (frozen)
-------------------------
SINE owns exactly two baseline gaps: SINE-1 -> SINE-2 (``stage_2_delay_seconds``)
and SINE-2 -> SINE-3 (``stage_3_delay_seconds``).  It does NOT own the initial
pre-trigger dwell (that belongs to CORE_ENGINE/blacklist.py as a separate organ).

SINE never recomputes Ebbinghaus/MBRM. It consumes exactly one already-derived,
policy-authorized personalization factor F for the whole session:

    stage_2_delay_seconds_applied = stage_2_delay_seconds (baseline) * F
    stage_3_delay_seconds_applied = stage_3_delay_seconds (baseline) * F

F is never a full substitution for the baseline -- it is a small nudge on top
of it.  Both gaps move together, from the same F, because F represents one
verified fact about the user's last session, not two.

F must arrive from the upstream MBRM/Ebbinghaus authority already computed
from explicitly authorized model inputs. SINE never invents a reference value
or factor bound; it performs only a mathematical sanity check (finite, positive)
before trusting the frozen session snapshot.

If F is missing, invalid, or the candidate carries no learned recovery model at
all (first-use / learning-session profile), SINE fails closed: F = 1.0, and
both gaps use their exact static baseline.  Broken or absent learning must
degrade to normal SINE, never to a broken or invented timer.

Important UI boundary
---------------------
The UI renders ``SinePopupRequest`` and reports lifecycle facts.  It must not
change stages, calculate deadlines, grant Study Material, or release Protected
Red.  A button click is only a response request until its owning authority
confirms the resulting action.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Final


# v2: the Study-return hold now accepts any verdict Resource Intent factually
# publishes as STUDY_ALIGNED for this episode's Study context -- C4 automatic
# alignment as well as an exact manual allowance -- and Protected Red no longer
# resolves through APPROVED_BREAK.  A v1 fact therefore describes a narrower
# recovery population and a different Red release surface than a v2 one.
# v3: MIRL's factual ten-second return-entry verification may withhold the
# current Study SINE presentation without resolving the intervention episode.
# Relapse restores the same Protected-Red presentation; final MIRL recovery is
# still the only return path that terminally resolves SINE.
SINE_SCHEMA_VERSION: Final = "myelin-sine-v3"
WEBER_FECHNER_MODEL_VERSION: Final = "myelin-weber-fechner-v1"
WEBER_FECHNER_EQUATION: Final = "P = k * ln(I / I0)"
EBBINGHAUS_TIMING_SOURCE: Final = "learned_ebbinghaus_t_star"
STATIC_TIMING_SOURCE: Final = "static_sine_policy"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
MAX_RETAINED_POPUPS: Final = 24
MAX_RETAINED_CONSUMED_CANDIDATES: Final = 256


class SineStage(IntEnum):
    """The only intervention stages in final MYELIN."""

    NONE = 0
    SINE_1 = 1
    SINE_2 = 2
    SINE_3 = 3


class SinePhase(str, Enum):
    IDLE = "idle"
    WAITING_FOR_DISPLAY = "waiting_for_display"
    ACTIVE = "active"
    PROTECTED_RED = "protected_red"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    EMERGENCY_STOPPED = "emergency_stopped"


class PopupState(str, Enum):
    REQUESTED = "requested"
    DISPLAYED = "displayed"
    CLOSE_REQUESTED = "close_requested"
    CLOSED = "closed"
    FAILED = "failed"


class SineResponse(str, Enum):
    """Responses the UI may report; SINE still decides their meaning."""

    RETURN_TO_FOCUS = "return_to_focus"
    REQUEST_BREAK = "request_break"
    THIS_IS_STUDY_MATERIAL = "this_is_study_material"
    CONTINUE_SINE = "continue_sine"


@dataclass(frozen=True, slots=True)
class SinePolicy:
    """All SINE timing decisions in one visible, testable contract."""

    stage_1_visible_seconds: float = 45.0
    stage_2_delay_seconds: float = 600.0
    stage_2_visible_seconds: float = 60.0
    stage_3_delay_seconds: float = 795.0
    stage_3_visible_seconds: float = 600.0
    display_retry_seconds: float = 10.0
    maximum_display_failures: int = 3

    def __post_init__(self) -> None:
        for name, value in (
            ("stage_1_visible_seconds", self.stage_1_visible_seconds),
            ("stage_2_delay_seconds", self.stage_2_delay_seconds),
            ("stage_2_visible_seconds", self.stage_2_visible_seconds),
            ("stage_3_delay_seconds", self.stage_3_delay_seconds),
            ("stage_3_visible_seconds", self.stage_3_visible_seconds),
            ("display_retry_seconds", self.display_retry_seconds),
        ):
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative value")
        if type(self.maximum_display_failures) is not int:
            raise TypeError("maximum_display_failures must be an integer")
        if self.maximum_display_failures < 0:
            raise ValueError("maximum_display_failures cannot be negative")


@dataclass(frozen=True, slots=True)
class WeberFechnerProjection:
    """Auditable Weber–Fechner framing for one factual SINE stage.

    MYELIN already has a fixed, three-stage behavioral SINE baseline.  The
    classic logarithmic law is carried here without inventing a fitted
    psychophysical calibration.  ``stage_ordinal`` and ``intensity_label``
    describe the factual SINE stage; they do not claim that a human perceptual
    quantity was measured.  A numeric Weber–Fechner response is only valid when
    explicit positive ``I``, ``I0`` and ``k`` values are supplied to
    :func:`weber_fechner_response`.
    """

    model_version: str
    equation: str
    stage_ordinal: int
    intensity_label: str
    calibrated: bool = False


def weber_fechner_response(
    *,
    stimulus: float,
    reference_stimulus: float,
    scale_constant: float,
) -> float:
    """Return ``k * ln(I / I0)`` for explicitly supplied model inputs.

    This pure mathematical helper never selects a SINE stage or deadline.
    MYELIN Core currently keeps its proven static SINE timing as the behavioral
    baseline; no undocumented ``I``, ``I0`` or ``k`` constants are guessed.
    """

    values = {
        "stimulus": float(stimulus),
        "reference_stimulus": float(reference_stimulus),
        "scale_constant": float(scale_constant),
    }
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("Weber-Fechner inputs must be finite")
    if values["stimulus"] <= 0 or values["reference_stimulus"] <= 0:
        raise ValueError("stimulus and reference_stimulus must be positive")
    if values["scale_constant"] <= 0:
        raise ValueError("scale_constant must be positive")
    return values["scale_constant"] * math.log(
        values["stimulus"] / values["reference_stimulus"]
    )


def _weber_fechner_projection(stage: SineStage) -> WeberFechnerProjection:
    """Project the factual three-stage SINE ladder without fake calibration."""

    if stage not in {SineStage.SINE_1, SineStage.SINE_2, SineStage.SINE_3}:
        raise ValueError("Weber-Fechner projection requires SINE 1, 2 or 3")
    return WeberFechnerProjection(
        model_version=WEBER_FECHNER_MODEL_VERSION,
        equation=WEBER_FECHNER_EQUATION,
        stage_ordinal=int(stage),
        intensity_label={
            SineStage.SINE_1: "Gentle",
            SineStage.SINE_2: "Aware",
            SineStage.SINE_3: "Direct",
        }[stage],
        calibrated=False,
    )


@dataclass(frozen=True, slots=True)
class SineSessionTiming:
    """One immutable personalization snapshot, frozen for exactly one session.

    SINE does not derive or clamp ``personalization_factor``. It must already
    have been computed from policy-authorized Ebbinghaus inputs from a
    verified previous session. SINE's job is narrow: trust the snapshot only
    if it is well-formed and was produced specifically for THIS session, else
    fail closed to the exact static baseline.

    Fixes two defects found in an earlier draft of this pattern:
    1. F was validated as a float locally but the original (possibly a
       string) was left stored on the frozen instance, so a later
       ``baseline * F`` could raise ``TypeError`` at multiply time instead of
       at construction time. Here the canonicalized float is written back via
       ``object.__setattr__`` -- the only correct way to normalise a field on
       a frozen dataclass -- and non-numeric/bool input is rejected outright.
    2. "Previous session" was enforced only as ``source_session_id <
       session_id``, which accepts a stale snapshot from many sessions ago.
       ``target_session_id`` makes provenance explicit: a snapshot is only
       usable for the exact session it was produced for.
    """

    timing_source: str = STATIC_TIMING_SOURCE
    personalization_factor: float = 1.0
    source_session_id: int | None = None
    target_session_id: int | None = None
    previous_return_latency_seconds: float | None = None
    ebbinghaus_t_star_minutes: float | None = None
    ebbinghaus_lambda_per_minute: float | None = None

    def __post_init__(self) -> None:
        raw_factor = self.personalization_factor
        if type(raw_factor) is bool or type(raw_factor) not in (int, float):
            raise TypeError("personalization_factor must be an int or float, not bool/str/etc.")
        factor = float(raw_factor)
        if not math.isfinite(factor) or factor <= 0.0:
            raise ValueError("personalization_factor must be finite and positive")
        object.__setattr__(self, "personalization_factor", factor)

        if self.timing_source == STATIC_TIMING_SOURCE:
            if factor != 1.0:
                raise ValueError("static SINE timing requires F = 1.0 exactly")
            return
        if self.timing_source != EBBINGHAUS_TIMING_SOURCE:
            raise ValueError("unknown SINE session timing source")
        if type(self.source_session_id) is not int or self.source_session_id <= 0:
            raise ValueError("personalized timing requires a positive source_session_id")
        if type(self.target_session_id) is not int or self.target_session_id <= 0:
            raise ValueError("personalized timing requires a positive target_session_id")
        if self.source_session_id >= self.target_session_id:
            raise ValueError("source_session_id must precede target_session_id")
        latency = self.previous_return_latency_seconds
        if latency is None or type(latency) is bool or type(latency) not in (int, float):
            raise ValueError("personalized timing requires a numeric previous return latency")
        if not math.isfinite(float(latency)) or float(latency) <= 0.0:
            raise ValueError(
                "personalized timing requires a finite positive previous return latency"
            )
        object.__setattr__(self, "previous_return_latency_seconds", float(latency))
        for name, value in (
            ("ebbinghaus_t_star_minutes", self.ebbinghaus_t_star_minutes),
            ("ebbinghaus_lambda_per_minute", self.ebbinghaus_lambda_per_minute),
        ):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite when supplied")


@dataclass(frozen=True, slots=True)
class SinePresentation:
    """Presentation facts selected by SINE, not by the popup widget."""

    world: str
    badge: str
    headline: str
    message: str
    study_mode: bool
    resource_title: str
    allowed_responses: tuple[SineResponse, ...]
    weber_fechner: WeberFechnerProjection | None = None


@dataclass(frozen=True, slots=True)
class SinePopupRequest:
    """One exact popup occurrence for the UI to render once."""

    request_id: str
    episode_uid: str
    candidate_uid: str
    operational_event_id: int
    stage: SineStage
    occurrence: int
    requested_monotonic_ns: int
    visible_seconds: float
    protected: bool
    presentation: SinePresentation
    mirl_display_token: object | None = None
    schema_version: str = SINE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class SineFact:
    """An immutable SINE fact or presentation command routed by monitor.py."""

    kind: str
    message: str
    occurred_monotonic_ns: int
    occurred_wall_time_utc: str
    session_id: int | None
    episode_uid: str = ""
    candidate_uid: str = ""
    operational_event_id: int | None = None
    stage: int = 0
    occurrence: int = 0
    popup_request_id: str = ""
    reason: str = ""
    response: str = ""
    study_context_token: str = ""
    resource_key: str = ""
    popup: SinePopupRequest | None = None
    mirl_display_token: object | None = None
    normal_break_id: str = ""
    normal_break_generation: int = 0
    normal_break_completion_kind: str = ""
    schema_version: str = SINE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class SineLiveView:
    """Read-only state for the Control Station and telemetry."""

    session_id: int | None
    profile_type: str
    phase: SinePhase
    stage: SineStage
    episode_uid: str
    candidate_uid: str
    operational_event_id: int | None
    popup_state: PopupState | None
    popup_request_id: str
    stage_2_deadline_monotonic_ns: int | None
    stage_3_deadline_monotonic_ns: int | None
    next_deadline_seconds: float | None
    protected_red_active: bool
    study_mode: bool
    last_response: str
    last_fact: str
    schema_version: str = SINE_SCHEMA_VERSION
    stage_2_timing_source: str = STATIC_TIMING_SOURCE
    stage_2_delay_seconds_applied: float | None = None
    stage_3_timing_source: str = STATIC_TIMING_SOURCE
    stage_3_delay_seconds_applied: float | None = None
    personalization_factor: float = 1.0
    ebbinghaus_t_star_minutes: float | None = None
    ebbinghaus_lambda_per_minute: float | None = None
    presentation_withheld_for_recovery: bool = False
    normal_break_held: bool = False
    normal_break_id: str = ""
    normal_break_generation: int = 0
    post_normal_break_completion_kind: str = ""


@dataclass(slots=True)
class _PopupOccurrence:
    request: SinePopupRequest
    state: PopupState = PopupState.REQUESTED
    shown_monotonic_ns: int | None = None
    visible_deadline_monotonic_ns: int | None = None
    closed_monotonic_ns: int | None = None
    popup_hwnd: int = 0
    response: str = ""
    close_reason: str = ""
    protected_wait_announced: bool = False


@dataclass(slots=True)
class _Episode:
    episode_uid: str
    candidate: object
    candidate_uid: str
    operational_event_id: int
    mirl_display_token: object | None
    accepted_monotonic_ns: int
    trigger_observed_monotonic_ns: int
    stage_2_deadline_monotonic_ns: int
    stage_3_deadline_monotonic_ns: int | None
    process_name: str
    process_id: int
    hwnd: int
    platform_key: str
    resource_key: str
    resource_title: str
    study_context_token: str
    study_mode: bool
    study_material_action_allowed: bool
    stage_2_timing_source: str = STATIC_TIMING_SOURCE
    stage_2_delay_seconds_applied: float | None = None
    stage_3_timing_source: str = STATIC_TIMING_SOURCE
    stage_3_delay_seconds_applied: float | None = None
    personalization_factor: float = 1.0
    ebbinghaus_t_star_minutes: float | None = None
    ebbinghaus_lambda_per_minute: float | None = None
    first_displayed_monotonic_ns: int | None = None
    phase: SinePhase = SinePhase.WAITING_FOR_DISPLAY
    current_stage: SineStage = SineStage.NONE
    requested_stage: SineStage = SineStage.NONE
    current_popup_request_id: str = ""
    protected_red: bool = False
    terminal_reason: str = ""
    last_response: str = ""
    last_response_monotonic_ns: int | None = None
    stage_occurrences: dict[SineStage, int] = field(default_factory=dict)
    display_failures: dict[SineStage, int] = field(default_factory=dict)
    retry_stage: SineStage = SineStage.NONE
    retry_due_monotonic_ns: int | None = None
    study_alignment_announced: bool = False
    presentation_withheld_for_recovery: bool = False
    normal_break_held: bool = False
    normal_break_id: str = ""
    normal_break_generation: int = 0
    normal_break_started_monotonic_ns: int | None = None
    normal_break_source_popup_request_id: str = ""
    post_normal_break_completion_kind: str = ""

    @property
    def terminal(self) -> bool:
        return self.phase in {
            SinePhase.RESOLVED,
            SinePhase.CANCELLED,
            SinePhase.EMERGENCY_STOPPED,
        }


def _field(value: object, name: str, default=None):
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_text(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip().upper()


def _normalise_process(value: object) -> str:
    return str(value or "").strip().casefold()


def _seconds_to_ns(value: float) -> int:
    return int(float(value) * NANOSECONDS_PER_SECOND)


class SineAuthority:
    """One thread-safe owner for SINE stages, deadlines and responses."""

    def __init__(
        self,
        *,
        storage: object | None = None,
        policy: SinePolicy = SinePolicy(),
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")

        # INSTRUCTION: monitor.py routes every SINE fact to the durable Trigger
        # and MIRL lanes.  SINE accepts ``storage`` for the composition contract
        # but never invents a second database-writing path here.
        del storage
        self._lock = threading.RLock()
        self._clock = monotonic_ns
        self._policy = policy
        self._session_id: int | None = None
        self._profile_type = "GENERAL"
        self._episode: _Episode | None = None
        self._popups: dict[str, _PopupOccurrence] = {}
        self._popup_order: list[str] = []
        self._pending_facts: list[SineFact] = []
        self._latest_context: object | None = None
        self._last_advance_ns = 0
        self._last_fact = ""
        self._started = False
        self._closed = False
        self._emergency_stopped = False
        self._session_timing = SineSessionTiming()
        # Bounded memory of trigger identities already consumed this session,
        # so a durably-committed candidate cannot start a second SINE episode
        # after its first episode has already resolved or been cancelled.
        # Capped and FIFO-evicted -- this is idempotency guidance, not an
        # audit log; unbounded growth for a long-running session is not safe.
        self._consumed_candidates: dict[str, int] = {}
        self._consumed_candidate_order: list[str] = []

    # ------------------------------------------------------------------
    # Session and trigger admission
    # ------------------------------------------------------------------

    def start_session(
        self,
        *,
        session_id: int,
        profile_type: str,
        timing: SineSessionTiming | None = None,
    ) -> None:
        """Reset SINE only after the monitor has a durable session ID.

        ``timing`` is the one personalization snapshot for this whole
        session, produced upstream by the MBRM/Ebbinghaus authority. It is
        frozen here and never re-read from individual trigger candidates
        again -- see ``_normalise_session_timing``. Starting a new session
        always clears any prior Emergency Stop; that is the only way
        Emergency Stop may be cleared.
        """

        if type(session_id) is not int or session_id <= 0:
            raise ValueError("session_id must be a positive integer")
        with self._lock:
            self._session_id = session_id
            self._profile_type = str(profile_type or "GENERAL").strip().upper()
            self._episode = None
            self._popups.clear()
            self._popup_order.clear()
            self._pending_facts.clear()
            self._latest_context = None
            self._last_advance_ns = 0
            self._last_fact = ""
            self._started = True
            self._closed = False
            self._emergency_stopped = False
            self._session_timing = self._normalise_session_timing(timing, session_id)
            self._consumed_candidates.clear()
            self._consumed_candidate_order.clear()

    def observe(self, context: object) -> None:
        """Receive the monitor's already-classified immutable observation.

        INSTRUCTION: SINE never reads Windows itself and never treats a title
        as resource identity.  Exact Study alignment can resolve an episode;
        uncertain evidence can neither resolve nor cancel it.
        """

        with self._lock:
            if not self._active_session():
                return
            self._latest_context = context
            episode = self._episode
            if episode is None or episode.terminal:
                return

            # Normal Break owns the sanctioned pause while this exact episode
            # is held. SINE retains identity and diagnostics, but ordinary
            # observations cannot resolve, cancel, or advance the episode.
            if episode.normal_break_held:
                return

            foreground = _field(context, "foreground")
            snapshot = _field(context, "resource_intent")
            verdict = _field(snapshot, "verdict")
            now_ns = int(_field(foreground, "observed_monotonic_ns", 0) or 0)
            if now_ns <= 0:
                return

            classification = _enum_text(_field(verdict, "classification", ""))
            study_token = str(_field(verdict, "study_context_token", "") or "")

            # Protected Red cannot be displaced by another distracting window.
            # Only a verified recovery, emergency or shutdown may release it.
            # An approved break explicitly may NOT -- see the branch below.
            if episode.protected_red:
                # Protected Red NEVER resolves from an observation.  The
                # APPROVED_BREAK resolution that used to sit here was dormant
                # only because Resource Intent masked every Red observation as
                # UNCERTAIN.  Now that Red can see facts again, leaving it would
                # turn "start a break" into a one-click escape from the
                # strongest intervention MYELIN has.  Red is released solely by
                # confirm_verified_return(evidence_source="mirl") or by the
                # existing emergency/shutdown terminal paths.
                if self._is_verified_study_alignment(episode, snapshot, verdict):
                    # The Red surface literally reads "AWAITING VERIFIED FOCUS
                    # RETURN".  Reaching the exact Study resource proves the
                    # resource, not the return, so Red is NOT released here --
                    # that is strictly stronger than before, never weaker.
                    # MIRL is watching the same observation and will verify the
                    # return; monitor.py then calls confirm_verified_return.
                    # Red is topmost-hinted but does not hold the foreground,
                    # and it self-restores only when its window is closed, so
                    # the user can work in the Study resource while it is up
                    # and MIRL can observe that work.
                    self._announce_study_alignment_hold(episode, now_ns)
                return

            if bool(_field(snapshot, "cosine_active", False)):
                self._cancel_episode("cosine_precedence", now_ns)
                return

            if classification == "APPROVED_BREAK":
                self._resolve_episode("approved_break", now_ns)
                return

            if self._is_verified_study_alignment(episode, snapshot, verdict):
                # AUTHORITY BOUNDARY: exact Study alignment proves "this is the
                # intended Study resource".  It does not prove "the behavioural
                # return survived verification".  Those are different facts, and
                # only MIRL owns the second one -- in Study Mode exactly as in
                # normal mode.
                #
                # Resolving here used to end the episode in the same monitor
                # cycle in which MIRL had just started RETURN_VERIFICATION, so
                # MIRL consumed SINE_EPISODE_RESOLVED and closed ABORTED: a
                # Study return could never produce Tr.  The episode now stays
                # ACTIVE and resolution arrives only through
                # confirm_verified_return(evidence_source="mirl").
                self._announce_study_alignment_hold(episode, now_ns)
                return

            # A changed Study block invalidates the captured Study popup facts.
            # An empty/uncertain observation is not enough; it may be MYELIN's
            # own popup or a temporary unsupported surface.
            if (
                episode.study_mode
                and study_token
                and study_token != episode.study_context_token
            ):
                self._cancel_episode("study_context_changed", now_ns)
                return

            if self._foreground_is_current_popup(foreground):
                return

            # Resource switching does not release intervention ownership.
            # The episode was founded by one durable trigger and remains the
            # same unresolved SINE/MIRL episode across later distracting apps
            # or resources. Only an existing authoritative terminal path may
            # release it; UNCERTAIN evidence remains non-terminal as before.

    def request_trigger(
        self,
        *,
        candidate: object,
        operational_event_id: int,
        mirl_display_token: object | None,
    ) -> bool:
        """Accept exactly one trigger that persistence has already committed.

        Timing is read only from the immutable ``self._session_timing`` frozen
        by ``start_session`` -- a candidate's own recovery model, if any, is
        not consulted here, so a running session cannot pick up a different F
        partway through from a later candidate.
        """

        if type(operational_event_id) is not int or operational_event_id <= 0:
            return False
        with self._lock:
            if not self._active_session():
                return False
            candidate_uid = str(_field(candidate, "candidate_uid", "") or "")
            candidate_session = _field(candidate, "session_id", None)
            candidate_profile = _enum_text(_field(candidate, "profile_type", ""))
            evidence = _field(candidate, "evidence")
            observed_ns = int(_field(evidence, "observed_monotonic_ns", 0) or 0)
            if (
                not candidate_uid
                or candidate_session != self._session_id
                or candidate_profile != self._profile_type
                or evidence is None
                or observed_ns <= 0
            ):
                return False

            # A candidate whose episode already reached a terminal state this
            # session (resolved, cancelled, or emergency-stopped) must not be
            # allowed to start a second episode on replay. The current-episode
            # check below only guards a still-running episode, which is not
            # enough once that episode has already finished.
            consumed_event_id = self._consumed_candidates.get(candidate_uid)
            if consumed_event_id is not None:
                return consumed_event_id == operational_event_id

            timing = self._session_timing
            timing_source = timing.timing_source
            personalization_factor = timing.personalization_factor
            stage_2_delay_seconds_applied = (
                self._policy.stage_2_delay_seconds * personalization_factor
            )
            stage_3_delay_seconds_applied = (
                self._policy.stage_3_delay_seconds * personalization_factor
            )
            if (
                not math.isfinite(stage_2_delay_seconds_applied)
                or not math.isfinite(stage_3_delay_seconds_applied)
                or stage_2_delay_seconds_applied < 0.0
                or stage_3_delay_seconds_applied < 0.0
            ):
                # A validly-constructed SineSessionTiming should make this
                # unreachable; baseline is still safer than propagating it.
                timing_source = STATIC_TIMING_SOURCE
                personalization_factor = 1.0
                stage_2_delay_seconds_applied = self._policy.stage_2_delay_seconds
                stage_3_delay_seconds_applied = self._policy.stage_3_delay_seconds

            current = self._episode
            if current is not None and not current.terminal:
                if current.candidate_uid == candidate_uid:
                    return current.operational_event_id == operational_event_id
                if current.protected_red:
                    self._emit(
                        "SINE_TRIGGER_WITHHELD_PROTECTED_RED",
                        "A later durable trigger was recorded while Protected Red remained active.",
                        self._now_ns(),
                        episode=current,
                        reason="protected_red_precedence",
                    )
                    return True
                self._cancel_episode("superseded_by_later_durable_trigger", self._now_ns())

            accepted_ns = self._now_ns()
            dwell_seconds = max(0.0, float(_field(evidence, "dwell_seconds", 0.0) or 0.0))
            threshold_seconds = max(
                0.0, float(_field(evidence, "threshold_seconds", 0.0) or 0.0)
            )
            dwell_start_ns = observed_ns - _seconds_to_ns(dwell_seconds)
            threshold_ns = dwell_start_ns + _seconds_to_ns(threshold_seconds)
            stage_2_deadline_ns = threshold_ns + _seconds_to_ns(
                stage_2_delay_seconds_applied
            )

            study_token = str(_field(evidence, "study_context_token", "") or "")
            resource_key = str(_field(evidence, "resource_key", "") or "")
            resource_title = self._current_resource_title()
            episode = _Episode(
                episode_uid=f"sine_{secrets.token_hex(16)}",
                candidate=candidate,
                candidate_uid=candidate_uid,
                operational_event_id=operational_event_id,
                mirl_display_token=mirl_display_token,
                accepted_monotonic_ns=accepted_ns,
                trigger_observed_monotonic_ns=observed_ns,
                stage_2_deadline_monotonic_ns=stage_2_deadline_ns,
                stage_3_deadline_monotonic_ns=None,
                process_name=_normalise_process(_field(evidence, "process_name", "")),
                process_id=int(_field(evidence, "process_id", 0) or 0),
                hwnd=int(_field(evidence, "hwnd", 0) or 0),
                platform_key=str(_field(evidence, "platform_key", "") or ""),
                resource_key=resource_key,
                resource_title=resource_title,
                study_context_token=study_token,
                study_mode=bool(study_token),
                study_material_action_allowed=self._safe_study_material_action(evidence),
                stage_2_timing_source=timing_source,
                stage_2_delay_seconds_applied=stage_2_delay_seconds_applied,
                stage_3_timing_source=timing_source,
                stage_3_delay_seconds_applied=stage_3_delay_seconds_applied,
                personalization_factor=personalization_factor,
                ebbinghaus_t_star_minutes=timing.ebbinghaus_t_star_minutes,
                ebbinghaus_lambda_per_minute=timing.ebbinghaus_lambda_per_minute,
            )
            self._episode = episode
            self._consumed_candidates[candidate_uid] = operational_event_id
            self._consumed_candidate_order.append(candidate_uid)
            if len(self._consumed_candidate_order) > MAX_RETAINED_CONSUMED_CANDIDATES:
                oldest = self._consumed_candidate_order.pop(0)
                self._consumed_candidates.pop(oldest, None)
            self._emit(
                "SINE_TRIGGER_ACCEPTED",
                "SINE accepted the durably admitted trigger.",
                accepted_ns,
                episode=episode,
            )
            self._emit(
                "SINE_STAGE_2_TIMING_BOUND",
                (
                    "Learned personalization factor F was bound to both the "
                    "SINE-1 -> SINE-2 and SINE-2 -> SINE-3 windows."
                    if timing_source == EBBINGHAUS_TIMING_SOURCE
                    else "No learned personalization factor was available; static SINE-2/SINE-3 timing remains active."
                ),
                accepted_ns,
                episode=episode,
                reason=timing_source,
            )
            self._request_stage(episode, SineStage.SINE_1, accepted_ns, "durable_trigger")
            return True

    # ------------------------------------------------------------------
    # Monotonic scheduler
    # ------------------------------------------------------------------

    def advance(self, *, now_monotonic_ns: int) -> tuple[SineFact, ...]:
        """Advance deadlines and return every fact produced since last call."""

        with self._lock:
            if not self._active_session():
                return ()
            if type(now_monotonic_ns) is not int or now_monotonic_ns <= 0:
                raise ValueError("now_monotonic_ns must be a positive integer")
            if self._last_advance_ns and now_monotonic_ns < self._last_advance_ns:
                self._emit(
                    "SINE_MONOTONIC_REGRESSION_REJECTED",
                    "A stale monotonic observation was ignored.",
                    self._last_advance_ns,
                    episode=self._episode,
                    reason="monotonic_time_moved_backwards",
                )
                return self._take_facts()
            self._last_advance_ns = now_monotonic_ns

            episode = self._episode
            if episode is not None and not episode.terminal:
                # MIRL has verified recovery ENTRY but not final stability.
                # Deadlines retain their original timestamps, while the
                # presentation remains inhibited until relapse or closure.
                if (
                    not episode.presentation_withheld_for_recovery
                    and not episode.normal_break_held
                ):
                    self._advance_popup_deadline(episode, now_monotonic_ns)
                    self._advance_display_retry(episode, now_monotonic_ns)

                    if (
                        episode.current_stage >= SineStage.SINE_1
                        and episode.requested_stage < SineStage.SINE_2
                        and now_monotonic_ns >= episode.stage_2_deadline_monotonic_ns
                    ):
                        self._request_stage(
                            episode,
                            SineStage.SINE_2,
                            now_monotonic_ns,
                            "stage_2_deadline_reached",
                        )

                    if (
                        episode.current_stage >= SineStage.SINE_2
                        and episode.requested_stage < SineStage.SINE_3
                        and episode.stage_3_deadline_monotonic_ns is not None
                        and now_monotonic_ns >= episode.stage_3_deadline_monotonic_ns
                    ):
                        self._request_stage(
                            episode,
                            SineStage.SINE_3,
                            now_monotonic_ns,
                            "stage_3_deadline_reached",
                        )

            return self._take_facts()

    # ------------------------------------------------------------------
    # Factual popup lifecycle reported by the presentation layer
    # ------------------------------------------------------------------

    def popup_shown(
        self,
        *,
        request_id: str,
        shown_monotonic_ns: int,
        popup_hwnd: int = 0,
    ) -> bool:
        """Activate a stage only after its exact popup is factually visible."""

        with self._lock:
            occurrence = self._current_occurrence(request_id)
            episode = self._episode
            if occurrence is None or episode is None or episode.terminal:
                return False
            if not self._valid_event_time(
                shown_monotonic_ns,
                occurrence.request.requested_monotonic_ns,
            ):
                return False
            if occurrence.state is not PopupState.REQUESTED:
                return False

            occurrence.state = PopupState.DISPLAYED
            occurrence.shown_monotonic_ns = shown_monotonic_ns
            occurrence.popup_hwnd = popup_hwnd if type(popup_hwnd) is int and popup_hwnd > 0 else 0
            occurrence.visible_deadline_monotonic_ns = shown_monotonic_ns + _seconds_to_ns(
                occurrence.request.visible_seconds
            )
            episode.current_stage = occurrence.request.stage
            episode.phase = (
                SinePhase.PROTECTED_RED
                if occurrence.request.stage is SineStage.SINE_3
                else SinePhase.ACTIVE
            )

            if occurrence.request.stage is SineStage.SINE_1:
                # BUGFIX: previously this re-anchor only ran when
                # stage_2_timing_source == EBBINGHAUS_TIMING_SOURCE, so a
                # STATIC (session-1 / no-F) episode kept its stage_2 deadline
                # computed from the original cumulative dwell instead of the
                # factual SINE-1 DISPLAYED moment. Both cases must anchor to
                # the same fact -- only the delay VALUE should differ, exactly
                # like the existing SINE-2 -> SINE-3 anchor below already does
                # correctly. Verified: SINE-1 displayed at 10s now correctly
                # yields a stage_2 deadline of 10s + delay, in both cases.
                episode.first_displayed_monotonic_ns = shown_monotonic_ns
                stage_2_delay = (
                    episode.stage_2_delay_seconds_applied
                    if episode.stage_2_delay_seconds_applied is not None
                    else self._policy.stage_2_delay_seconds
                )
                episode.stage_2_deadline_monotonic_ns = (
                    shown_monotonic_ns + _seconds_to_ns(stage_2_delay)
                )
            if occurrence.request.stage is SineStage.SINE_2:
                # Anchor to the factual SINE-2 DISPLAYED event, same pattern as
                # SINE-1 -> SINE-2 above. Per the frozen contract, SINE-3 now
                # adapts from the same session-wide F as SINE-2 -- it is no
                # longer permanently fixed to the static baseline.
                stage_3_delay = (
                    episode.stage_3_delay_seconds_applied
                    if (
                        episode.stage_3_timing_source == EBBINGHAUS_TIMING_SOURCE
                        and episode.stage_3_delay_seconds_applied is not None
                    )
                    else self._policy.stage_3_delay_seconds
                )
                episode.stage_3_deadline_monotonic_ns = shown_monotonic_ns + _seconds_to_ns(
                    stage_3_delay
                )
            if occurrence.request.stage is SineStage.SINE_3:
                episode.protected_red = True

            # MIRL consumes this fact. A request or animation start is not a
            # display fact and therefore cannot start a MIRL episode.
            self._emit(
                "SINE_DISPLAYED",
                f"SINE {int(occurrence.request.stage)} popup was factually displayed.",
                shown_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                mirl_display_token=(
                    episode.mirl_display_token
                    if occurrence.request.stage is SineStage.SINE_1
                    else None
                ),
            )
            if occurrence.request.stage is SineStage.SINE_1:
                self._emit(
                    "SINE_STAGE_2_SCHEDULED",
                    (
                        "SINE 2 was scheduled from the factual SINE 1 display using the learned Ebbinghaus t*."
                        if episode.stage_2_timing_source == EBBINGHAUS_TIMING_SOURCE
                        else "SINE 2 remains bound to the original cumulative dwell deadline."
                    ),
                    shown_monotonic_ns,
                    episode=episode,
                    occurrence=occurrence,
                    reason=episode.stage_2_timing_source,
                )
            elif occurrence.request.stage is SineStage.SINE_2:
                self._emit(
                    "SINE_STAGE_3_SCHEDULED",
                    "SINE 3 was scheduled from the factual SINE 2 display.",
                    shown_monotonic_ns,
                    episode=episode,
                    occurrence=occurrence,
                )
            else:
                self._emit(
                    "SINE_PROTECTED_RED_ACTIVATED",
                    "Protected Red became active after the factual SINE 3 display.",
                    shown_monotonic_ns,
                    episode=episode,
                    occurrence=occurrence,
                )
            return True

    def popup_failed(
        self,
        *,
        request_id: str,
        reason: str,
        occurred_monotonic_ns: int,
    ) -> bool:
        """Record a real display failure; a failure never advances the stage."""

        with self._lock:
            occurrence = self._current_occurrence(request_id)
            episode = self._episode
            if occurrence is None or episode is None or episode.terminal:
                return False
            if not self._valid_event_time(
                occurred_monotonic_ns,
                occurrence.request.requested_monotonic_ns,
            ):
                return False
            if occurrence.state is not PopupState.REQUESTED:
                return False
            occurrence.state = PopupState.FAILED
            occurrence.close_reason = str(reason or "display_failed")
            stage = occurrence.request.stage
            failures = episode.display_failures.get(stage, 0) + 1
            episode.display_failures[stage] = failures
            self._emit(
                "SINE_DISPLAY_FAILED",
                f"SINE {int(stage)} popup did not display.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=occurrence.close_reason,
            )
            if failures <= self._policy.maximum_display_failures:
                episode.retry_stage = stage
                episode.retry_due_monotonic_ns = occurred_monotonic_ns + _seconds_to_ns(
                    self._policy.display_retry_seconds
                )
            else:
                episode.retry_stage = SineStage.NONE
                episode.retry_due_monotonic_ns = None
                self._emit(
                    "SINE_DISPLAY_RETRY_EXHAUSTED",
                    f"SINE {int(stage)} reached its bounded display retry limit.",
                    occurred_monotonic_ns,
                    episode=episode,
                    occurrence=occurrence,
                    reason="bounded_retry_limit",
                )
            return True

    def popup_response(
        self,
        *,
        request_id: str,
        response: SineResponse | str,
        occurred_monotonic_ns: int,
    ) -> bool:
        """Validate a button response and emit a request to its real owner."""

        with self._lock:
            occurrence = self._current_occurrence(request_id)
            episode = self._episode
            if occurrence is None or episode is None or episode.terminal:
                return False
            if not self._valid_event_time(
                occurred_monotonic_ns,
                occurrence.request.requested_monotonic_ns,
            ):
                return False
            if occurrence.state is not PopupState.DISPLAYED or occurrence.response:
                return False
            if (
                occurrence.shown_monotonic_ns is None
                or occurred_monotonic_ns < occurrence.shown_monotonic_ns
            ):
                return False
            try:
                selected = (
                    response
                    if isinstance(response, SineResponse)
                    else SineResponse(str(response))
                )
            except ValueError:
                return False
            if selected not in occurrence.request.presentation.allowed_responses:
                return False

            occurrence.response = selected.value
            episode.last_response = selected.value
            episode.last_response_monotonic_ns = occurred_monotonic_ns
            self._emit(
                "SINE_RESPONSE_RECORDED",
                "SINE recorded a user response; the UI did not change engine state.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                response=selected.value,
            )
            response_kind = {
                SineResponse.RETURN_TO_FOCUS: "SINE_RETURN_INTENT_RECORDED",
                SineResponse.REQUEST_BREAK: "SINE_BREAK_REQUESTED",
                SineResponse.THIS_IS_STUDY_MATERIAL: "SINE_STUDY_MATERIAL_REQUESTED",
                SineResponse.CONTINUE_SINE: "SINE_CONTINUE_REQUESTED",
            }[selected]
            self._emit(
                response_kind,
                self._response_message(selected),
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                response=selected.value,
            )
            # A click is an intent, never verified recovery.  Presentation
            # closure and recovery truth are deliberately separate:
            #
            #   RETURN_TO_FOCUS
            #       -> record the user's intent
            #       -> request closure of this popup immediately
            #       -> keep the SINE episode ACTIVE
            #       -> keep MIRL recovery UNVERIFIED
            #       -> continue SINE/MIRL observation in the background
            #
            # Closing the surface therefore does NOT call _resolve_episode(),
            # does NOT confirm MIRL recovery, and does NOT cancel escalation.
            # Only later authoritative MIRL evidence may resolve the episode.
            #
            # THIS_IS_STUDY_MATERIAL remains open while Resource Intent decides
            # that separate request. REQUEST_BREAK and CONTINUE_SINE still close
            # immediately after SINE accepts them.
            if selected is not SineResponse.THIS_IS_STUDY_MATERIAL:
                self._request_popup_close(
                    episode,
                    occurrence,
                    occurred_monotonic_ns,
                    f"response:{selected.value}",
                )
            return True

    def popup_expired(
        self,
        *,
        request_id: str,
        occurred_monotonic_ns: int,
    ) -> bool:
        """Accept expiry only when SINE's own monotonic deadline is due."""

        with self._lock:
            occurrence = self._current_occurrence(request_id)
            episode = self._episode
            if occurrence is None or episode is None or episode.terminal:
                return False
            if not self._valid_event_time(
                occurred_monotonic_ns,
                occurrence.request.requested_monotonic_ns,
            ):
                return False
            deadline = occurrence.visible_deadline_monotonic_ns
            if (
                occurrence.request.stage is SineStage.SINE_3
                or deadline is None
                or occurred_monotonic_ns < deadline
            ):
                return False
            if occurrence.state is PopupState.DISPLAYED:
                self._expire_popup(episode, occurrence, occurred_monotonic_ns)
            return occurrence.state is PopupState.CLOSE_REQUESTED

    def popup_closed(
        self,
        *,
        request_id: str,
        reason: str,
        occurred_monotonic_ns: int,
    ) -> bool:
        """Record factual UI closure without letting it release SINE state."""

        with self._lock:
            occurrence = self._popups.get(str(request_id or ""))
            episode = self._episode
            if occurrence is None or episode is None:
                return False
            if occurrence.request.episode_uid != episode.episode_uid:
                return False
            if not self._valid_event_time(
                occurred_monotonic_ns,
                occurrence.request.requested_monotonic_ns,
            ):
                return False
            if occurrence.state not in {
                PopupState.DISPLAYED,
                PopupState.CLOSE_REQUESTED,
            }:
                return False
            if (
                occurrence.shown_monotonic_ns is None
                or occurred_monotonic_ns < occurrence.shown_monotonic_ns
            ):
                return False
            occurrence.state = PopupState.CLOSED
            occurrence.closed_monotonic_ns = occurred_monotonic_ns
            occurrence.close_reason = str(reason or "closed")
            self._emit(
                "SINE_POPUP_CLOSED",
                f"SINE {int(occurrence.request.stage)} popup factually closed.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=occurrence.close_reason,
            )

            # A Red window disappearing does not release Protected Red. Reopen
            # it through the authority unless recovery/emergency already ended
            # the episode.
            if (
                occurrence.request.stage is SineStage.SINE_3
                and episode.protected_red
                and not episode.terminal
                and not episode.presentation_withheld_for_recovery
                and episode.current_popup_request_id == occurrence.request.request_id
            ):
                episode.retry_stage = SineStage.SINE_3
                episode.retry_due_monotonic_ns = occurred_monotonic_ns
                self._emit(
                    "SINE_PROTECTED_RED_SURFACE_LOST",
                    "Protected Red remains active and its surface must be restored.",
                    occurred_monotonic_ns,
                    episode=episode,
                    occurrence=occurrence,
                    reason=occurrence.close_reason,
                )
            return True

    # ------------------------------------------------------------------
    # Confirmations from authoritative non-UI owners
    # ------------------------------------------------------------------

    def withhold_presentation_for_verified_return_entry(
        self,
        *,
        candidate_uid: str,
        verified_monotonic_ns: int,
        evidence_source: str,
    ) -> bool:
        """Hide an eligible SINE surface after MIRL verifies return entry."""

        with self._lock:
            episode = self._episode
            eligible_for_return_entry_withhold = bool(
                episode is not None
                and (
                    episode.study_mode
                    or (
                        episode.current_stage is SineStage.SINE_3
                        and episode.protected_red
                    )
                )
            )
            if (
                episode is None
                or episode.terminal
                or not eligible_for_return_entry_withhold
                or episode.candidate_uid != str(candidate_uid or "")
                or not str(evidence_source or "").strip()
                or episode.first_displayed_monotonic_ns is None
                or not self._valid_event_time(
                    verified_monotonic_ns,
                    episode.first_displayed_monotonic_ns,
                )
            ):
                return False
            if episode.presentation_withheld_for_recovery:
                return True

            episode.presentation_withheld_for_recovery = True
            episode.retry_stage = SineStage.NONE
            episode.retry_due_monotonic_ns = None
            occurrence = self._current_popup(episode)
            self._emit(
                "SINE_PRESENTATION_WITHHELD_FOR_RECOVERY",
                "MIRL verified return entry; SINE presentation is withheld "
                "while final recovery remains unverified.",
                verified_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=str(evidence_source).strip(),
            )
            if occurrence is not None and occurrence.state in {
                PopupState.REQUESTED,
                PopupState.DISPLAYED,
            }:
                self._request_popup_close(
                    episode,
                    occurrence,
                    verified_monotonic_ns,
                    "mirl_return_entry_verified",
                )
            return True

    def resume_presentation_after_recovery_relapse(
        self,
        *,
        candidate_uid: str,
        occurred_monotonic_ns: int,
        evidence_source: str,
    ) -> bool:
        """End a recovery presentation hold without founding a new episode."""

        with self._lock:
            episode = self._episode
            if (
                episode is None
                or episode.terminal
                or episode.normal_break_held
                or episode.candidate_uid != str(candidate_uid or "")
                or not str(evidence_source or "").strip()
                or episode.first_displayed_monotonic_ns is None
                or not self._valid_event_time(
                    occurred_monotonic_ns,
                    episode.first_displayed_monotonic_ns,
                )
            ):
                return False
            if not episode.presentation_withheld_for_recovery:
                return True

            episode.presentation_withheld_for_recovery = False
            episode.study_alignment_announced = False
            occurrence = self._current_popup(episode)
            self._emit(
                "SINE_PRESENTATION_RESUMED_AFTER_RELAPSE",
                "MIRL detected relapse; the same SINE episode resumed its "
                "presentation authority.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=str(evidence_source).strip(),
            )
            if episode.protected_red and (
                occurrence is None
                or occurrence.request.stage is not SineStage.SINE_3
                or occurrence.state
                not in {PopupState.REQUESTED, PopupState.DISPLAYED}
            ):
                episode.retry_stage = SineStage.SINE_3
                episode.retry_due_monotonic_ns = occurred_monotonic_ns
            return True

    def confirm_verified_return(
        self,
        *,
        candidate_uid: str,
        verified_monotonic_ns: int,
        evidence_source: str,
    ) -> bool:
        """Release SINE after a recovery authority verifies sustained focus.

        The UI must never call this method merely because a button was clicked.

        BUGFIX: previously validated against ``episode.accepted_monotonic_ns``,
        which meant a verified-return confirmation could be accepted even if
        SINE-1 was never actually displayed to the user -- e.g. trigger
        accepted, no popup shown yet, MIRL confirms anyway. That return
        latency (Tr) would be meaningless for MBRM/lambda training, since
        Tr must be measured from the factual moment the user was actually
        nudged, not from a backend acceptance event they never saw. Now
        requires ``first_displayed_monotonic_ns`` to exist and validates
        against that fact instead.
        """

        with self._lock:
            episode = self._episode
            if (
                episode is None
                or episode.terminal
                or episode.normal_break_held
                or episode.candidate_uid != str(candidate_uid or "")
                or not str(evidence_source or "").strip()
                or episode.first_displayed_monotonic_ns is None
                or not self._valid_event_time(
                    verified_monotonic_ns,
                    episode.first_displayed_monotonic_ns,
                )
            ):
                return False
            self._resolve_episode(
                f"verified_return:{str(evidence_source).strip()}",
                verified_monotonic_ns,
            )
            return True

    def confirm_break_started(
        self,
        *,
        candidate_uid: str,
        occurred_monotonic_ns: int,
    ) -> bool:
        """Resolve only after COSECANT/lifecycle confirms the break is real."""

        with self._lock:
            episode = self._episode
            if (
                episode is None
                or episode.terminal
                or episode.candidate_uid != str(candidate_uid or "")
                or not self._valid_event_time(
                    occurred_monotonic_ns,
                    episode.accepted_monotonic_ns,
                )
            ):
                return False
            self._resolve_episode("approved_break_started", occurred_monotonic_ns)
            return True

    def hold_for_normal_break(
        self,
        *,
        candidate_uid: str,
        episode_uid: str,
        break_id: str,
        break_generation: int,
        started_monotonic_ns: int,
        source_popup_request_id: str,
    ) -> bool:
        """Hold one exact Normal SINE-1 episode without resolving it."""

        identities = (
            candidate_uid,
            episode_uid,
            break_id,
            source_popup_request_id,
        )
        if any(type(value) is not str or not value for value in identities):
            return False
        if type(break_generation) is not int or break_generation <= 0:
            return False
        if type(started_monotonic_ns) is not int or started_monotonic_ns <= 0:
            return False

        with self._lock:
            episode = self._episode
            if episode is None or episode.terminal:
                return False
            if episode.normal_break_held:
                return bool(
                    episode.candidate_uid == candidate_uid
                    and episode.episode_uid == episode_uid
                    and episode.normal_break_id == break_id
                    and episode.normal_break_generation == break_generation
                    and episode.normal_break_started_monotonic_ns
                    == started_monotonic_ns
                    and episode.normal_break_source_popup_request_id
                    == source_popup_request_id
                )

            occurrence = self._popups.get(source_popup_request_id)
            earliest = max(
                episode.accepted_monotonic_ns,
                int(episode.first_displayed_monotonic_ns or 0),
                int(episode.last_response_monotonic_ns or 0),
            )
            if (
                episode.candidate_uid != candidate_uid
                or episode.episode_uid != episode_uid
                or episode.study_mode
                or episode.protected_red
                or episode.current_stage is not SineStage.SINE_1
                or episode.requested_stage is not SineStage.SINE_1
                or episode.current_popup_request_id != source_popup_request_id
                or episode.last_response != SineResponse.REQUEST_BREAK.value
                or episode.first_displayed_monotonic_ns is None
                or episode.last_response_monotonic_ns is None
                or started_monotonic_ns
                >= episode.stage_2_deadline_monotonic_ns
                or occurrence is None
                or occurrence.request.stage is not SineStage.SINE_1
                or occurrence.request.episode_uid != episode_uid
                or occurrence.request.candidate_uid != candidate_uid
                or occurrence.response != SineResponse.REQUEST_BREAK.value
                or not self._valid_event_time(started_monotonic_ns, earliest)
            ):
                return False

            episode.normal_break_held = True
            episode.normal_break_id = break_id
            episode.normal_break_generation = break_generation
            episode.normal_break_started_monotonic_ns = started_monotonic_ns
            episode.normal_break_source_popup_request_id = source_popup_request_id
            episode.post_normal_break_completion_kind = ""
            episode.retry_stage = SineStage.NONE
            episode.retry_due_monotonic_ns = None
            self._emit(
                "SINE_NORMAL_BREAK_HELD",
                "The same Normal SINE episode was held by factual Normal Break authority.",
                started_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason="normal_break_started",
            )
            return True

    def cancel_normal_break_hold(
        self,
        *,
        candidate_uid: str,
        episode_uid: str,
        break_id: str,
        break_generation: int,
        occurred_monotonic_ns: int,
        reason: str,
    ) -> bool:
        """Restore original SINE-1 flow after a failed ownership handoff."""

        with self._lock:
            episode = self._matching_normal_break_hold(
                candidate_uid=candidate_uid,
                episode_uid=episode_uid,
                break_id=break_id,
                break_generation=break_generation,
                occurred_monotonic_ns=occurred_monotonic_ns,
            )
            if episode is None or type(reason) is not str or not reason.strip():
                return False
            occurrence = self._current_popup(episode)
            held_break_id = episode.normal_break_id
            held_generation = episode.normal_break_generation
            self._clear_normal_break_hold(episode)
            episode.post_normal_break_completion_kind = ""
            self._emit(
                "SINE_NORMAL_BREAK_HOLD_CANCELLED",
                "Normal Break handoff failed; the original SINE flow remained authoritative.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=reason.strip(),
                normal_break_id=held_break_id,
                normal_break_generation=held_generation,
            )
            return True

    def resume_from_normal_break_as_sine2(
        self,
        *,
        candidate_uid: str,
        episode_uid: str,
        break_id: str,
        break_generation: int,
        occurred_monotonic_ns: int,
        completion_kind: str,
    ) -> bool:
        """Resume the exact held episode by requesting SINE 2 immediately."""

        allowed_completion_kinds = {
            "NORMAL_BREAK_COMPLETED",
            "NORMAL_BREAK_STOPPED",
        }
        if type(completion_kind) is not str or completion_kind not in allowed_completion_kinds:
            return False
        with self._lock:
            episode = self._matching_normal_break_hold(
                candidate_uid=candidate_uid,
                episode_uid=episode_uid,
                break_id=break_id,
                break_generation=break_generation,
                occurred_monotonic_ns=occurred_monotonic_ns,
            )
            if episode is None:
                return False
            occurrence = self._current_popup(episode)
            held_break_id = episode.normal_break_id
            held_generation = episode.normal_break_generation
            self._clear_normal_break_hold(episode)
            episode.post_normal_break_completion_kind = completion_kind
            self._emit(
                "SINE_NORMAL_BREAK_RESUMED_AS_SINE_2",
                "Normal Break ended; the same SINE episode resumed immediately at SINE 2.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=completion_kind,
                normal_break_id=held_break_id,
                normal_break_generation=held_generation,
                normal_break_completion_kind=completion_kind,
            )
            self._request_stage(
                episode,
                SineStage.SINE_2,
                occurred_monotonic_ns,
                "normal_break_resumed_immediately",
            )
            return True

    def record_study_material_result(
        self,
        *,
        request_id: str,
        granted: bool,
        occurred_monotonic_ns: int,
        reason: str,
    ) -> bool:
        """Record Monitor's answer to a Study Material declaration."""

        with self._lock:
            occurrence = self._popups.get(str(request_id or ""))
            episode = self._episode
            if occurrence is None or episode is None or episode.terminal:
                return False
            if occurrence.request.episode_uid != episode.episode_uid:
                return False
            if not self._valid_event_time(
                occurred_monotonic_ns,
                occurrence.request.requested_monotonic_ns,
            ):
                return False
            if occurrence.response != SineResponse.THIS_IS_STUDY_MATERIAL.value:
                return False
            self._emit(
                "SINE_STUDY_MATERIAL_RESULT",
                "Monitor returned the Study Material declaration result.",
                occurred_monotonic_ns,
                episode=episode,
                occurrence=occurrence,
                reason=str(reason or ("granted" if granted else "denied")),
                response="granted" if granted else "denied",
            )
            if granted:
                # UI action is not recovery truth -- the same principle already
                # settled for I'M BACK.  Granting the allowance means Resource
                # Intent accepted the resource identity, so this popup
                # occurrence may close and let the user reach the underlying
                # Study resource. The SINE episode deliberately stays ACTIVE,
                # waiting for MIRL.
                self._request_popup_close(
                    episode,
                    occurrence,
                    occurred_monotonic_ns,
                    "study_material_allowance_granted",
                )
            else:
                # BUGFIX: denial is a factual result, but the SINE surface
                # remains active and the user must still be able to respond
                # (e.g. RETURN_TO_FOCUS). Without this, popup_response's
                # "occurrence.state is not DISPLAYED or occurrence.response"
                # guard permanently rejects every later response on this same
                # popup occurrence, since occurrence.response was left set to
                # "this_is_study_material" forever.
                occurrence.response = ""
            return True

    # ------------------------------------------------------------------
    # Protected Red, read model and shutdown
    # ------------------------------------------------------------------

    def restore_protected_red(self) -> bool:
        """Ensure the Red surface exists without changing Red truth."""

        with self._lock:
            episode = self._episode
            if episode is None or episode.terminal or not episode.protected_red:
                return False
            if episode.presentation_withheld_for_recovery:
                return True
            current = self._current_popup(episode)
            if (
                current is not None
                and current.request.stage is SineStage.SINE_3
                and current.state
                in {
                    PopupState.REQUESTED,
                    PopupState.DISPLAYED,
                    PopupState.CLOSE_REQUESTED,
                }
            ):
                return True
            now_ns = self._now_ns()
            self._request_stage(
                episode,
                SineStage.SINE_3,
                now_ns,
                "protected_red_restore",
            )
            self._emit(
                "SINE_PROTECTED_RED_RESTORE_REQUESTED",
                "Protected Red surface restoration was requested.",
                now_ns,
                episode=episode,
                occurrence=self._current_popup(episode),
            )
            return True

    def protected_red_active(self) -> bool:
        with self._lock:
            episode = self._episode
            return bool(episode is not None and not episode.terminal and episode.protected_red)

    def live_view(self) -> SineLiveView:
        with self._lock:
            episode = self._episode
            if episode is None:
                return SineLiveView(
                    session_id=self._session_id,
                    profile_type=self._profile_type,
                    phase=SinePhase.IDLE,
                    stage=SineStage.NONE,
                    episode_uid="",
                    candidate_uid="",
                    operational_event_id=None,
                    popup_state=None,
                    popup_request_id="",
                    stage_2_deadline_monotonic_ns=None,
                    stage_3_deadline_monotonic_ns=None,
                    next_deadline_seconds=None,
                    protected_red_active=False,
                    study_mode=False,
                    last_response="",
                    last_fact=self._last_fact,
                    stage_2_timing_source=STATIC_TIMING_SOURCE,
                    stage_2_delay_seconds_applied=None,
                    stage_3_timing_source=STATIC_TIMING_SOURCE,
                    stage_3_delay_seconds_applied=None,
                    personalization_factor=1.0,
                    ebbinghaus_t_star_minutes=None,
                    ebbinghaus_lambda_per_minute=None,
                    presentation_withheld_for_recovery=False,
                    normal_break_held=False,
                    normal_break_id="",
                    normal_break_generation=0,
                    post_normal_break_completion_kind="",
                )
            occurrence = self._current_popup(episode)
            now_ns = self._now_ns() if self._active_session() else 0
            deadline = None if episode.normal_break_held else self._next_deadline(episode)
            remaining = (
                None
                if deadline is None
                else max(0.0, (deadline - now_ns) / NANOSECONDS_PER_SECOND)
            )
            return SineLiveView(
                session_id=self._session_id,
                profile_type=self._profile_type,
                phase=episode.phase,
                stage=episode.current_stage,
                episode_uid=episode.episode_uid,
                candidate_uid=episode.candidate_uid,
                operational_event_id=episode.operational_event_id,
                popup_state=occurrence.state if occurrence else None,
                popup_request_id=occurrence.request.request_id if occurrence else "",
                stage_2_deadline_monotonic_ns=episode.stage_2_deadline_monotonic_ns,
                stage_3_deadline_monotonic_ns=episode.stage_3_deadline_monotonic_ns,
                next_deadline_seconds=remaining,
                protected_red_active=bool(episode.protected_red and not episode.terminal),
                study_mode=episode.study_mode,
                last_response=episode.last_response,
                last_fact=self._last_fact,
                stage_2_timing_source=episode.stage_2_timing_source,
                stage_2_delay_seconds_applied=episode.stage_2_delay_seconds_applied,
                stage_3_timing_source=episode.stage_3_timing_source,
                stage_3_delay_seconds_applied=episode.stage_3_delay_seconds_applied,
                personalization_factor=episode.personalization_factor,
                ebbinghaus_t_star_minutes=episode.ebbinghaus_t_star_minutes,
                ebbinghaus_lambda_per_minute=episode.ebbinghaus_lambda_per_minute,
                presentation_withheld_for_recovery=(
                    episode.presentation_withheld_for_recovery
                ),
                normal_break_held=episode.normal_break_held,
                normal_break_id=episode.normal_break_id,
                normal_break_generation=episode.normal_break_generation,
                post_normal_break_completion_kind=(
                    episode.post_normal_break_completion_kind
                ),
            )

    def emergency_stop(self) -> None:
        """Stop SINE for the rest of this session, unconditionally.

        The sticky ``_emergency_stopped`` flag is set here regardless of
        whether an episode is currently running -- Emergency Stop must lock
        out FUTURE triggers too, not just close the current popup. It is
        only ever cleared by ``start_session`` starting a genuinely new
        session.
        """

        with self._lock:
            if not self._active_session():
                return
            self._emergency_stopped = True
            episode = self._episode
            now_ns = self._now_ns()
            occurrence = None
            if episode is not None and not episode.terminal:
                occurrence = self._current_popup(episode)
                if occurrence is not None and occurrence.state in {
                    PopupState.REQUESTED,
                    PopupState.DISPLAYED,
                }:
                    self._request_popup_close(episode, occurrence, now_ns, "emergency")
                episode.protected_red = False
                self._clear_normal_break_hold(episode)
                episode.phase = SinePhase.EMERGENCY_STOPPED
                episode.terminal_reason = "emergency"
            self._emit(
                "SINE_EMERGENCY_STOPPED",
                "SINE stopped after the lifecycle emergency command.",
                now_ns,
                episode=episode,
                occurrence=occurrence,
                reason="emergency",
            )

    def shutdown(self) -> None:
        with self._lock:
            self._episode = None
            self._popups.clear()
            self._popup_order.clear()
            self._pending_facts.clear()
            self._latest_context = None
            self._session_id = None
            self._last_advance_ns = 0
            self._started = False
            self._closed = True

    # ------------------------------------------------------------------
    # Internal state transitions
    # ------------------------------------------------------------------

    def _request_stage(
        self,
        episode: _Episode,
        stage: SineStage,
        occurred_ns: int,
        reason: str,
    ) -> None:
        if episode.terminal or episode.normal_break_held:
            return
        current = self._current_popup(episode)
        if current is not None and current.state in {PopupState.REQUESTED, PopupState.DISPLAYED}:
            self._request_popup_close(episode, current, occurred_ns, "superseded")

        occurrence_number = episode.stage_occurrences.get(stage, 0) + 1
        episode.stage_occurrences[stage] = occurrence_number
        request = SinePopupRequest(
            request_id=f"popup_{secrets.token_hex(16)}",
            episode_uid=episode.episode_uid,
            candidate_uid=episode.candidate_uid,
            operational_event_id=episode.operational_event_id,
            stage=stage,
            occurrence=occurrence_number,
            requested_monotonic_ns=occurred_ns,
            visible_seconds=self._visible_seconds(stage),
            protected=stage is SineStage.SINE_3,
            presentation=self._presentation(episode, stage),
            mirl_display_token=(episode.mirl_display_token if stage is SineStage.SINE_1 else None),
        )
        occurrence = _PopupOccurrence(request=request)
        self._popups[request.request_id] = occurrence
        self._popup_order.append(request.request_id)
        self._trim_popup_history()
        episode.current_popup_request_id = request.request_id
        episode.requested_stage = max(episode.requested_stage, stage)
        episode.phase = SinePhase.WAITING_FOR_DISPLAY
        episode.retry_stage = SineStage.NONE
        episode.retry_due_monotonic_ns = None
        self._emit(
            "SINE_POPUP_REQUESTED",
            f"SINE {int(stage)} popup display was requested.",
            occurred_ns,
            episode=episode,
            occurrence=occurrence,
            reason=reason,
            popup=request,
        )

    def _advance_popup_deadline(self, episode: _Episode, now_ns: int) -> None:
        occurrence = self._current_popup(episode)
        if occurrence is None or occurrence.state is not PopupState.DISPLAYED:
            return
        deadline = occurrence.visible_deadline_monotonic_ns
        if deadline is None or now_ns < deadline:
            return
        if occurrence.request.stage is SineStage.SINE_3:
            if not occurrence.protected_wait_announced:
                occurrence.protected_wait_announced = True
                self._emit(
                    "SINE_PROTECTED_RED_AWAITING_RECOVERY",
                    "The Red display period elapsed; Protected Red remains "
                    "until verified recovery.",
                    now_ns,
                    episode=episode,
                    occurrence=occurrence,
                    reason="recovery_not_verified",
                )
            return
        self._expire_popup(episode, occurrence, now_ns)

    def _expire_popup(
        self,
        episode: _Episode,
        occurrence: _PopupOccurrence,
        now_ns: int,
    ) -> None:
        self._emit(
            "SINE_POPUP_EXPIRED",
            f"SINE {int(occurrence.request.stage)} reached its authority-owned display deadline.",
            now_ns,
            episode=episode,
            occurrence=occurrence,
            reason="display_deadline",
        )
        self._request_popup_close(episode, occurrence, now_ns, "display_deadline")

    def _advance_display_retry(self, episode: _Episode, now_ns: int) -> None:
        if (
            episode.retry_stage is SineStage.NONE
            or episode.retry_due_monotonic_ns is None
            or now_ns < episode.retry_due_monotonic_ns
        ):
            return
        stage = episode.retry_stage
        episode.retry_stage = SineStage.NONE
        episode.retry_due_monotonic_ns = None
        self._request_stage(episode, stage, now_ns, "display_retry")

    def _request_popup_close(
        self,
        episode: _Episode,
        occurrence: _PopupOccurrence,
        occurred_ns: int,
        reason: str,
    ) -> None:
        if occurrence.state in {PopupState.CLOSED, PopupState.FAILED, PopupState.CLOSE_REQUESTED}:
            return
        occurrence.state = PopupState.CLOSE_REQUESTED
        occurrence.close_reason = reason
        self._emit(
            "SINE_POPUP_CLOSE_REQUESTED",
            f"SINE requested closure of the SINE {int(occurrence.request.stage)} surface.",
            occurred_ns,
            episode=episode,
            occurrence=occurrence,
            reason=reason,
        )

    def _resolve_episode(self, reason: str, occurred_ns: int) -> None:
        episode = self._episode
        if episode is None or episode.terminal:
            return
        occurrence = self._current_popup(episode)
        if occurrence is not None and occurrence.state in {
            PopupState.REQUESTED,
            PopupState.DISPLAYED,
        }:
            self._request_popup_close(episode, occurrence, occurred_ns, "episode_resolved")
        was_red = episode.protected_red
        episode.protected_red = False
        self._clear_normal_break_hold(episode)
        episode.phase = SinePhase.RESOLVED
        episode.terminal_reason = reason
        if was_red:
            self._emit(
                "SINE_PROTECTED_RED_RELEASED",
                "Protected Red was released by authoritative recovery evidence.",
                occurred_ns,
                episode=episode,
                occurrence=occurrence,
                reason=reason,
            )
        self._emit(
            "SINE_EPISODE_RESOLVED",
            "The SINE episode ended after authoritative recovery evidence.",
            occurred_ns,
            episode=episode,
            occurrence=occurrence,
            reason=reason,
        )

    def _cancel_episode(self, reason: str, occurred_ns: int) -> None:
        episode = self._episode
        if episode is None or episode.terminal:
            return
        occurrence = self._current_popup(episode)
        if occurrence is not None and occurrence.state in {
            PopupState.REQUESTED,
            PopupState.DISPLAYED,
        }:
            self._request_popup_close(episode, occurrence, occurred_ns, "episode_cancelled")
        episode.protected_red = False
        self._clear_normal_break_hold(episode)
        episode.phase = SinePhase.CANCELLED
        episode.terminal_reason = reason
        self._emit(
            "SINE_EPISODE_CANCELLED",
            "The pending SINE episode was cancelled because its factual scope changed.",
            occurred_ns,
            episode=episode,
            occurrence=occurrence,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Internal decisions and projections
    # ------------------------------------------------------------------

    def _normalise_session_timing(
        self,
        timing: SineSessionTiming | None,
        session_id: int,
    ) -> SineSessionTiming:
        """Return one safe, session-scoped timing snapshot for this session.

        SINE does not recalculate Ebbinghaus and does not invent normalization
        references or factor bounds. Those belong outside SINE and require
        explicit policy authorization before ``timing`` may exist. SINE's only
        job is provenance: a
        snapshot is usable only if it explicitly names THIS session as its
        target. A bare ``source_session_id < session_id`` check would accept
        an arbitrarily stale snapshot from many sessions ago; requiring an
        exact ``target_session_id`` match closes that gap.

        Missing, malformed, or wrongly-targeted timing all fail closed to the
        exact static baseline -- never a guess, never a crash.
        """

        if timing is None or not isinstance(timing, SineSessionTiming):
            return SineSessionTiming()
        if timing.timing_source == STATIC_TIMING_SOURCE:
            return SineSessionTiming()
        if timing.target_session_id != session_id:
            return SineSessionTiming()
        if (
            type(timing.source_session_id) is not int
            or timing.source_session_id <= 0
            or timing.source_session_id >= session_id
        ):
            return SineSessionTiming()
        return timing

    def _presentation(
        self,
        episode: _Episode,
        stage: SineStage,
    ) -> SinePresentation:
        title = episode.resource_title
        if episode.study_mode:
            if stage is SineStage.SINE_1:
                headline = "Study focus notice"
                message = (
                    "The active study block is running. Return to the "
                    "registered study resource."
                )
            elif stage is SineStage.SINE_2:
                headline = "Study focus needs attention"
                message = "The off-task episode continued after the first study notice."
            else:
                headline = "Study recovery required"
                message = "Protected Red remains active until recovery is factually verified."
            responses: tuple[SineResponse, ...]
            if stage is SineStage.SINE_3:
                responses = ()
            else:
                responses = (SineResponse.RETURN_TO_FOCUS,)
        else:
            if stage is SineStage.SINE_1:
                headline = "Cognitive Drift Detected"
                message = "The current resource reached its intervention threshold."
                responses = (
                    SineResponse.RETURN_TO_FOCUS,
                    SineResponse.REQUEST_BREAK,
                )
            elif stage is SineStage.SINE_2:
                if _field(episode, "post_normal_break_completion_kind", "") in {
                    "NORMAL_BREAK_COMPLETED",
                    "NORMAL_BREAK_STOPPED",
                }:
                    headline = "WELCOME BACK"
                    message = (
                        "Hope you have refreshed and enjoyed your break. "
                        "Let's come back to focus."
                    )
                else:
                    headline = "Still Here?"
                    message = (
                        "You stepped away for a moment, but the loop pulled you back. "
                        "Your focus window is still open."
                    )
                # Normal SINE 2 now has one return action.  The compatibility
                # enum/handler for CONTINUE_SINE remains available for old
                # persisted inputs, but new presentation never offers it.
                responses = (SineResponse.RETURN_TO_FOCUS,)
            else:
                headline = "Long Drift Detected"
                message = (
                    "You've been away for a while. "
                    "Protected Red remains active until recovery is factually verified."
                )
                responses = ()
        return SinePresentation(
            world={1: "blue", 2: "amber", 3: "red"}[int(stage)],
            badge=f"SINE {int(stage)}",
            headline=headline,
            message=message,
            study_mode=episode.study_mode,
            resource_title=title,
            allowed_responses=responses,
            weber_fechner=_weber_fechner_projection(stage),
        )

    def _current_resource_title(self) -> str:
        snapshot = _field(self._latest_context, "resource_intent")
        observation = _field(snapshot, "observation")
        return str(_field(observation, "raw_title", "") or "").strip()[:240]

    def _safe_study_material_action(self, evidence: object) -> bool:
        if not str(_field(evidence, "study_context_token", "") or ""):
            return False
        if not str(_field(evidence, "resource_key", "") or ""):
            return False
        if not str(_field(evidence, "resource_observation_token", "") or ""):
            return False
        surface = str(_field(evidence, "surface_class", "") or "").casefold()
        if surface not in {"youtube_watch", "web_content", "document", "learning_app"}:
            return False
        if surface in {"youtube_watch", "web_content"}:
            evidence_kind = str(
                _field(evidence, "browser_evidence_kind", "") or ""
            ).casefold()
            return evidence_kind not in {"", "none", "unknown", "unavailable", "title_only"}
        return True

    def _is_verified_study_alignment(
        self,
        episode: _Episode,
        snapshot: object,
        verdict: object,
    ) -> bool:
        """True when Resource Intent factually reports THIS episode's Study
        resource in focus.

        AUTHORITY BOUNDARY: Resource Intent is the Study verdict authority.
        Requiring allowance_match/allowance_active here re-derived WHY the
        verdict was issued and silently excluded C4's automatic route, in
        which a genuine certified lecture aligns with no manual allowance at
        all.  SINE now trusts the published classification and checks only
        that it belongs to this episode's Study block.

        This is recognition, not release.  The caller records a hold; only
        ``confirm_verified_return(evidence_source="mirl")`` may end an episode.
        """

        if not episode.study_mode:
            return False
        return bool(
            bool(_field(snapshot, "fresh", False))
            and _enum_text(_field(verdict, "classification", "")) == "STUDY_ALIGNED"
            and str(_field(verdict, "study_context_token", "") or "")
            == episode.study_context_token
        )

    def _announce_study_alignment_hold(
        self,
        episode: _Episode,
        now_ns: int,
    ) -> None:
        """Record once that SINE is holding open, waiting for MIRL to verify.

        Emitted at most once per episode so a per-cycle observation cannot
        flood the research ledger, mirroring the existing
        ``protected_wait_announced`` pattern.
        """

        if episode.study_alignment_announced:
            return
        episode.study_alignment_announced = True
        self._emit(
            "SINE_STUDY_ALIGNMENT_AWAITING_RECOVERY",
            "The exact Study resource is in focus; SINE is holding this "
            "episode open until MIRL verifies the return.",
            now_ns,
            episode=episode,
            occurrence=self._current_popup(episode),
            reason="awaiting_mirl_verified_return",
        )

    def _foreground_is_current_popup(self, foreground: object) -> bool:
        episode = self._episode
        if episode is None:
            return False
        occurrence = self._current_popup(episode)
        if occurrence is None or occurrence.popup_hwnd <= 0:
            return False
        return int(_field(foreground, "hwnd", 0) or 0) == occurrence.popup_hwnd

    def _visible_seconds(self, stage: SineStage) -> float:
        return {
            SineStage.SINE_1: self._policy.stage_1_visible_seconds,
            SineStage.SINE_2: self._policy.stage_2_visible_seconds,
            SineStage.SINE_3: self._policy.stage_3_visible_seconds,
        }[stage]

    def _response_message(self, response: SineResponse) -> str:
        return {
            SineResponse.RETURN_TO_FOCUS: (
                "Return intent was recorded; verified recovery is still required."
            ),
            SineResponse.REQUEST_BREAK: (
                "A break was requested; SINE waits for lifecycle confirmation."
            ),
            SineResponse.THIS_IS_STUDY_MATERIAL: (
                "A Study Material allowance was requested from Resource Intent."
            ),
            SineResponse.CONTINUE_SINE: (
                "The user asked SINE to continue; escalation deadlines remain active."
            ),
        }[response]

    def _current_occurrence(self, request_id: str) -> _PopupOccurrence | None:
        episode = self._episode
        if episode is None or episode.current_popup_request_id != str(request_id or ""):
            return None
        occurrence = self._popups.get(episode.current_popup_request_id)
        if occurrence is None or occurrence.request.episode_uid != episode.episode_uid:
            return None
        return occurrence

    def _current_popup(self, episode: _Episode) -> _PopupOccurrence | None:
        occurrence = self._popups.get(episode.current_popup_request_id)
        if occurrence is None or occurrence.request.episode_uid != episode.episode_uid:
            return None
        return occurrence

    def _next_deadline(self, episode: _Episode) -> int | None:
        if episode.terminal:
            return None
        occurrence = self._current_popup(episode)
        if occurrence is not None and occurrence.state is PopupState.DISPLAYED:
            if occurrence.request.stage is not SineStage.SINE_3:
                return occurrence.visible_deadline_monotonic_ns
        if episode.requested_stage < SineStage.SINE_2:
            return episode.stage_2_deadline_monotonic_ns
        if episode.requested_stage < SineStage.SINE_3:
            return episode.stage_3_deadline_monotonic_ns
        return occurrence.visible_deadline_monotonic_ns if occurrence else None

    def _trim_popup_history(self) -> None:
        while len(self._popup_order) > MAX_RETAINED_POPUPS:
            oldest = self._popup_order.pop(0)
            episode = self._episode
            if episode is None or oldest != episode.current_popup_request_id:
                self._popups.pop(oldest, None)

    # ------------------------------------------------------------------
    # Fact creation and invariants
    # ------------------------------------------------------------------

    def _emit(
        self,
        kind: str,
        message: str,
        occurred_ns: int,
        *,
        episode: _Episode | None,
        occurrence: _PopupOccurrence | None = None,
        reason: str = "",
        response: str = "",
        popup: SinePopupRequest | None = None,
        mirl_display_token: object | None = None,
        normal_break_id: str | None = None,
        normal_break_generation: int | None = None,
        normal_break_completion_kind: str | None = None,
    ) -> None:
        stage = occurrence.request.stage if occurrence is not None else (
            episode.current_stage if episode is not None else SineStage.NONE
        )
        fact = SineFact(
            kind=kind,
            message=message,
            occurred_monotonic_ns=max(0, int(occurred_ns)),
            occurred_wall_time_utc=datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            session_id=self._session_id,
            episode_uid=episode.episode_uid if episode else "",
            candidate_uid=episode.candidate_uid if episode else "",
            operational_event_id=episode.operational_event_id if episode else None,
            stage=int(stage),
            occurrence=occurrence.request.occurrence if occurrence else 0,
            popup_request_id=occurrence.request.request_id if occurrence else "",
            reason=reason,
            response=response,
            study_context_token=episode.study_context_token if episode else "",
            resource_key=episode.resource_key if episode else "",
            popup=popup,
            mirl_display_token=mirl_display_token,
            normal_break_id=(
                normal_break_id
                if normal_break_id is not None
                else (episode.normal_break_id if episode else "")
            ),
            normal_break_generation=(
                normal_break_generation
                if normal_break_generation is not None
                else (episode.normal_break_generation if episode else 0)
            ),
            normal_break_completion_kind=(
                normal_break_completion_kind
                if normal_break_completion_kind is not None
                else (episode.post_normal_break_completion_kind if episode else "")
            ),
        )
        self._pending_facts.append(fact)
        self._last_fact = kind

    def _take_facts(self) -> tuple[SineFact, ...]:
        facts = tuple(self._pending_facts)
        self._pending_facts.clear()
        return facts

    def _matching_normal_break_hold(
        self,
        *,
        candidate_uid: object,
        episode_uid: object,
        break_id: object,
        break_generation: object,
        occurred_monotonic_ns: object,
    ) -> _Episode | None:
        identities = (candidate_uid, episode_uid, break_id)
        if any(type(value) is not str or not value for value in identities):
            return None
        if type(break_generation) is not int or break_generation <= 0:
            return None
        episode = self._episode
        if (
            episode is None
            or episode.terminal
            or not episode.normal_break_held
            or episode.candidate_uid != candidate_uid
            or episode.episode_uid != episode_uid
            or episode.normal_break_id != break_id
            or episode.normal_break_generation != break_generation
            or episode.normal_break_started_monotonic_ns is None
            or not self._valid_event_time(
                occurred_monotonic_ns,
                episode.normal_break_started_monotonic_ns,
            )
        ):
            return None
        return episode

    @staticmethod
    def _clear_normal_break_hold(episode: _Episode) -> None:
        episode.normal_break_held = False
        episode.normal_break_id = ""
        episode.normal_break_generation = 0
        episode.normal_break_started_monotonic_ns = None
        episode.normal_break_source_popup_request_id = ""

    def _active_session(self) -> bool:
        """Return whether SINE will accept observations and new triggers.

        Emergency Stop is deliberately session-scoped, not episode-scoped: the
        old check only marked one EPISODE as EMERGENCY_STOPPED, which left
        ``request_trigger`` free to accept a brand new candidate and start a
        second episode in the same session immediately after. Emergency Stop
        must remain authoritative until lifecycle explicitly starts a new
        session via ``start_session`` -- that is the only place it is cleared.
        """
        return bool(
            self._started
            and not self._closed
            and not self._emergency_stopped
            and self._session_id is not None
        )

    def _valid_event_time(self, value: object, earliest_ns: int) -> bool:
        """Reject malformed or stale callback times without changing state."""

        return bool(type(value) is int and value > 0 and value >= earliest_ns)

    def _now_ns(self) -> int:
        value = self._clock()
        if type(value) is not int or value <= 0:
            raise RuntimeError("monotonic clock returned an invalid value")
        return value


__all__ = (
    "EBBINGHAUS_TIMING_SOURCE",
    "PopupState",
    "STATIC_TIMING_SOURCE",
    "WEBER_FECHNER_EQUATION",
    "WEBER_FECHNER_MODEL_VERSION",
    "SineAuthority",
    "SineFact",
    "SineLiveView",
    "SinePhase",
    "SinePolicy",
    "SinePopupRequest",
    "SinePresentation",
    "SineResponse",
    "SineSessionTiming",
    "SineStage",
    "WeberFechnerProjection",
    "weber_fechner_response",
)
