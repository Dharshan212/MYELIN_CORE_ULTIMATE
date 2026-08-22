"""Trigger candidate and durable admission authority for MYELIN.

This module is the narrow gate between observed evidence and an intervention.
It does not detect Windows activity, calculate dwell, write a database, run
MIRL, schedule SINE, or build presentation text.

Decision order
--------------
1. Receive the current immutable monitor context and blacklist result.
2. Prefer a ready Study off-task event; otherwise use a blacklist threshold
   offer.
3. Prove that the offer belongs to the exact current observation.
4. Bind the candidate to privacy-safe evidence and mint one candidate UID.
5. Hold that same candidate until persistence admits or rejects it.
6. Start cooldown only after persistence returns a durable event identifier.

Scientific boundary
-------------------
All inputs are observable software activity.  The Ebbinghaus/MBRM section in
this file is a non-biological behavioural estimate: it applies the exponential
decay form D(t) = D0 * exp(-lambda * t), derives t* from a frozen session
lambda, and can solve the same equation backwards from a factual verified
recovery duration to one observed lambda estimate.  It does not measure memory,
neural activity, or any hidden personal state.  This authority still creates no
generated intervention copy or presentation instruction.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from CORE_ENGINE.blacklist import Disposition
from CORE_ENGINE.resource_intent import ResourceIntent, SineContribution


# v4: Executive Blacklist evidence may not found an intervention while Resource
# Intent factually reports APPROVED_BREAK.  A threshold offer that was eligible
# under v3 is deliberately rejected under v4, so candidate admissibility itself
# changed and stored rows must not share a version across the boundary.
#
# Blacklist observation is unchanged -- the activity is still measured and
# still described.  Only the conversion of that evidence into an intervention
# is refused, because COSECANT owns break-return regulation for the duration of
# an approved break.
TRIGGER_SCHEMA_VERSION: Final = "myelin-trigger-v4"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
DEFAULT_COOLDOWN_SECONDS: Final = 300.0
DEFAULT_REJECTION_RETRY_SECONDS: Final = 20.0
MAX_RECORDED_RESULTS: Final = 128

# ---------------------------------------------------------------------------
# Ebbinghaus / MBRM behavioural recovery model
# ---------------------------------------------------------------------------
#
# Canonical mathematical lineage used by MYELIN:
#
#     dD/dt     = -lambda * D
#     D(t)        = D0 * exp(-lambda * t)
#     t*          = (1 / lambda) * ln(D0 / D_threshold)
#     lambda_hat  = ln(D0 / D_threshold) / T_verified
#
# The old MYELIN donor implemented the same kernel in its legacy recovery-model
# path and later renamed the persisted parameters to neutral MBRM terms.  That
# legacy module is intentionally not restored here: only the neutral mathematics
# and factual category/magnitude mapping are harvested.
MBRM_MODEL_VERSION: Final = "mbrm-ebbinghaus-v1"
INITIAL_MAGNITUDE_UNITLESS: Final = 1.0
RESOLUTION_THRESHOLD_UNITLESS: Final = 0.15

# Lambda is intentionally NOT stored here.  Durable profile learning belongs to
# PERSISTENCE; monitor.py will later load and freeze the exact learned value for
# the selected profile, then pass it into start_session().  Until that handoff is
# wired, the model reports an explicit unconfigured state rather than inventing
# or silently borrowing a legacy profile value.
# Donor APP_SEVERITY values reduced to the model categories that the clean
# Executive Blacklist can factually hand to trigger.py.  This is model input
# scaling only; trigger.py does not re-detect or re-classify the foreground app.
MODEL_MAGNITUDE_MULTIPLIERS: Final[tuple[tuple[str, float], ...]] = (
    ("short_form_video", 1.00),
    ("social_feed", 0.85),
    # The late donor mapped ordinary YouTube video to ``media_hub``; because
    # APP_SEVERITY had no media_hub entry, its factual fallback was generic .70.
    ("media_hub", 0.70),
    ("generic", 0.70),
)

# Mapping from the already-authoritative Executive Blacklist surface into the
# legacy model category.  No platform/title lookup is performed here.
MODEL_CATEGORY_BY_SURFACE: Final[tuple[tuple[str, str], ...]] = (
    ("short_feed", "short_form_video"),
    ("social_feed", "social_feed"),
    ("selected_video", "media_hub"),
)


class TriggerSource(str, Enum):
    STUDY_OFF_TASK = "study_off_task"
    EXECUTIVE_BLACKLIST = "executive_blacklist"


class TriggerStatus(str, Enum):
    PENDING_DURABILITY = "pending_durability"
    DURABLY_ADMITTED = "durably_admitted"
    REJECTED = "rejected"


class EbbinghausStatus(str, Enum):
    COMPUTED = "computed"
    PROFILE_LAMBDA_UNCONFIGURED = "profile_lambda_unconfigured"


@dataclass(frozen=True, slots=True)
class EbbinghausEstimate:
    """Immutable Ebbinghaus/MBRM parameters frozen with one trigger candidate.

    This is a behavioural model snapshot, not a biological measurement.
    ``t_star_minutes`` is the direct mathematical result.  The legacy donor's
    half-minute lockout rounding is deliberately not transplanted: SINE policy
    is a separate authority in MYELIN 2.0.
    """

    model_version: str
    status: EbbinghausStatus
    profile_type: str
    lambda_source: str
    model_category: str
    initial_magnitude_unitless: float
    magnitude_multiplier: float
    decay_rate_per_minute: float | None
    resolution_threshold_unitless: float
    t_star_minutes: float | None

    def __post_init__(self) -> None:
        for name, value in (
            ("initial_magnitude_unitless", self.initial_magnitude_unitless),
            ("magnitude_multiplier", self.magnitude_multiplier),
            ("resolution_threshold_unitless", self.resolution_threshold_unitless),
        ):
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.resolution_threshold_unitless <= 0:
            raise ValueError("resolution_threshold_unitless must be positive")
        if not isinstance(self.status, EbbinghausStatus):
            raise TypeError("status must be an EbbinghausStatus")
        if (
            not self.model_version
            or not self.profile_type
            or not self.lambda_source
            or not self.model_category
        ):
            raise ValueError(
                "Ebbinghaus estimate requires model/profile/lambda/category identity"
            )

        if self.status is EbbinghausStatus.COMPUTED:
            if self.decay_rate_per_minute is None or self.decay_rate_per_minute <= 0:
                raise ValueError("computed Ebbinghaus estimate requires positive lambda")
            if not math.isfinite(self.decay_rate_per_minute):
                raise ValueError("decay_rate_per_minute must be finite")
            if (
                self.t_star_minutes is None
                or not math.isfinite(self.t_star_minutes)
                or self.t_star_minutes < 0
            ):
                raise ValueError("computed Ebbinghaus estimate requires valid t_star_minutes")
        else:
            if (
                self.decay_rate_per_minute is not None
                or self.t_star_minutes is not None
            ):
                raise ValueError("unconfigured Ebbinghaus estimate cannot carry computed values")


def ebbinghaus_residual_engagement(
    initial_magnitude_unitless: float,
    decay_rate_per_minute: float,
    elapsed_minutes: float,
) -> float:
    """Return D(t) = D0 * exp(-lambda * t) with strict finite inputs."""

    d0 = float(initial_magnitude_unitless)
    lam = float(decay_rate_per_minute)
    elapsed = float(elapsed_minutes)
    if not math.isfinite(d0) or d0 < 0:
        raise ValueError("initial_magnitude_unitless must be finite and non-negative")
    if not math.isfinite(lam) or lam <= 0:
        raise ValueError("decay_rate_per_minute must be finite and positive")
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("elapsed_minutes must be finite and non-negative")
    return d0 * math.exp(-lam * elapsed)


def ebbinghaus_t_star_minutes(
    initial_magnitude_unitless: float,
    decay_rate_per_minute: float,
    resolution_threshold_unitless: float = RESOLUTION_THRESHOLD_UNITLESS,
) -> float:
    """Solve D(t*) = threshold for t* without operational rounding."""

    d0 = float(initial_magnitude_unitless)
    lam = float(decay_rate_per_minute)
    threshold = float(resolution_threshold_unitless)
    if not math.isfinite(d0) or d0 < 0:
        raise ValueError("initial_magnitude_unitless must be finite and non-negative")
    if not math.isfinite(lam) or lam <= 0:
        raise ValueError("decay_rate_per_minute must be finite and positive")
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("resolution_threshold_unitless must be finite and positive")
    if d0 <= threshold:
        return 0.0
    return math.log(d0 / threshold) / lam


def ebbinghaus_lambda_from_verified_recovery(
    initial_magnitude_unitless: float,
    verified_recovery_minutes: float,
    resolution_threshold_unitless: float = RESOLUTION_THRESHOLD_UNITLESS,
) -> float:
    """Solve the Ebbinghaus equation backwards for one observed lambda.

    ``verified_recovery_minutes`` must already be a factual, consistently
    anchored recovery duration supplied by the recovery authority.  This
    function does not decide whether a return is verified and does not infer
    recovery from buttons, popup closure, titles, or UI state.
    """

    d0 = float(initial_magnitude_unitless)
    recovery = float(verified_recovery_minutes)
    threshold = float(resolution_threshold_unitless)
    if not math.isfinite(d0) or d0 <= 0:
        raise ValueError("initial_magnitude_unitless must be finite and positive")
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("resolution_threshold_unitless must be finite and positive")
    if d0 <= threshold:
        raise ValueError(
            "initial_magnitude_unitless must be greater than the resolution threshold"
        )
    if not math.isfinite(recovery) or recovery <= 0:
        raise ValueError("verified_recovery_minutes must be finite and positive")

    observed_lambda = math.log(d0 / threshold) / recovery
    if not math.isfinite(observed_lambda) or observed_lambda <= 0:
        raise RuntimeError("observed Ebbinghaus lambda calculation became invalid")

    # Round-trip the same equation so a future refactor cannot silently change
    # the forward and reverse mathematical kernels independently.
    resolved = ebbinghaus_residual_engagement(d0, observed_lambda, recovery)
    if not math.isclose(resolved, threshold, rel_tol=1e-12, abs_tol=1e-12):
        raise RuntimeError("observed Ebbinghaus lambda consistency check failed")
    return observed_lambda


@dataclass(frozen=True, slots=True)
class ObservedLambdaEstimate:
    """One immutable lambda estimate derived from factual verified recovery.

    The exact D0 and threshold are copied from the trigger's already-frozen
    Ebbinghaus snapshot.  This object is evidence for later session/profile
    learning; it does not update persistence or change the current session.
    """

    model_version: str
    candidate_uid: str
    profile_type: str
    model_category: str
    initial_magnitude_unitless: float
    resolution_threshold_unitless: float
    verified_recovery_minutes: float
    observed_decay_rate_per_minute: float

    def __post_init__(self) -> None:
        if (
            not self.model_version
            or not self.candidate_uid
            or not self.profile_type
            or not self.model_category
        ):
            raise ValueError("observed lambda estimate requires complete provenance")
        for name, value in (
            ("initial_magnitude_unitless", self.initial_magnitude_unitless),
            ("resolution_threshold_unitless", self.resolution_threshold_unitless),
            ("verified_recovery_minutes", self.verified_recovery_minutes),
            ("observed_decay_rate_per_minute", self.observed_decay_rate_per_minute),
        ):
            if not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.initial_magnitude_unitless <= self.resolution_threshold_unitless:
            raise ValueError("observed lambda estimate requires D0 above threshold")


# ---------------------------------------------------------------------------
# MBRM session personalization factor
# ---------------------------------------------------------------------------
#
# Locked design (PERSISTENCE/storage.py freezes
# ``learned_return_latency_seconds`` as the previous ELIGIBLE session's
# actual verified MIRL return latency only -- never a running average; see
# ``update_profile_learning_session``). F is the locked identity implemented
# literally, directly on that authoritative Tr fact:
#
#     F = Tr_ref / Tr_previous
#
# CORRECTION (Chief audit): an earlier version of this authority reconstructed
# Tr_previous from the stored lambda via ``t* = ln(D0/D_threshold) / lambda``
# using a fixed D0 = INITIAL_MAGNITUDE_UNITLESS. But the stored lambda had
# itself been derived per-episode with a CATEGORY-SPECIFIC D0
# (short_form_video=1.00, social_feed=0.85, media_hub/generic=0.70 -- see
# MODEL_MAGNITUDE_MULTIPLIERS). D0 only cancels out of F when the SAME D0 is
# used on both sides of the ratio; reconstructing lambda's Tr through a
# *different*, fixed D0 silently reintroduced category-dependent
# personalization into what must be a pure return-time ratio -- two users
# with an identical real 5-minute return latency got different F depending on
# which distraction category triggered the episode. Tr is now carried as its
# own durable fact end to end (MIRL -> monitor.py ->
# PERSISTENCE.storage.ProfileLearningState -> here), so this function never
# touches D0/D_threshold at all. Lambda remains stored and reported elsewhere
# purely as an audit/telemetry value; it is not an input to F.
#
# Tr_ref is the "typical" verified return latency the static SINE baseline
# (F = 1.0) implicitly assumes. A previous return slower than Tr_ref yields
# F < 1 (SINE escalates sooner); a faster previous return yields F > 1 (SINE
# waits longer). F_min/F_max bound one session's personalization so a single
# extreme return latency can never collapse or balloon the SINE timers.
# These three numbers are still placeholders pending product calibration --
# see the module-level note in CORE_ENGINE/monitor.py.
REFERENCE_RETURN_LATENCY_MINUTES: Final = 8.0
PERSONALIZATION_FACTOR_MINIMUM: Final = 0.5
PERSONALIZATION_FACTOR_MAXIMUM: Final = 1.5


@dataclass(frozen=True, slots=True)
class MbrmSessionPersonalization:
    """One frozen MBRM personalization snapshot derived from a prior
    session's actual verified MIRL return latency.

    Pure evidence-to-factor conversion only. No SINE/session-timing type is
    built here -- this module does not schedule SINE (see module docstring);
    the caller (CORE_ENGINE/monitor.py) turns this into one
    ``SINE.sine.SineSessionTiming`` for ``SineAuthority.start_session``.
    """

    personalization_factor: float
    previous_return_latency_minutes: float
    reference_return_latency_minutes: float

    def __post_init__(self) -> None:
        for name, value in (
            ("personalization_factor", self.personalization_factor),
            ("previous_return_latency_minutes", self.previous_return_latency_minutes),
            ("reference_return_latency_minutes", self.reference_return_latency_minutes),
        ):
            if not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


def mbrm_session_personalization(
    *,
    previous_return_latency_minutes: float,
    reference_return_latency_minutes: float = REFERENCE_RETURN_LATENCY_MINUTES,
    minimum_factor: float = PERSONALIZATION_FACTOR_MINIMUM,
    maximum_factor: float = PERSONALIZATION_FACTOR_MAXIMUM,
) -> MbrmSessionPersonalization:
    """Derive one session's clamped SINE personalization factor F = Tr_ref / Tr_previous.

    ``previous_return_latency_minutes`` must already be the durably stored,
    previous-eligible-session-only, ACTUAL verified MIRL return latency from
    ``PERSISTENCE.storage.ProfileLearningState.learned_return_latency_seconds``
    -- this function does not read storage, does not average across sessions,
    and (deliberately, after the D0-contamination fix) never reconstructs Tr
    from lambda or touches D0/D_threshold.
    """

    previous_latency = float(previous_return_latency_minutes)
    if not math.isfinite(previous_latency) or previous_latency <= 0:
        raise ValueError("previous_return_latency_minutes must be finite and positive")
    reference_latency = float(reference_return_latency_minutes)
    if not math.isfinite(reference_latency) or reference_latency <= 0:
        raise ValueError("reference_return_latency_minutes must be finite and positive")
    if not math.isfinite(minimum_factor) or minimum_factor <= 0:
        raise ValueError("minimum_factor must be finite and positive")
    if not math.isfinite(maximum_factor) or maximum_factor < minimum_factor:
        raise ValueError("maximum_factor must be finite and >= minimum_factor")

    raw_factor = reference_latency / previous_latency
    if not math.isfinite(raw_factor) or raw_factor <= 0:
        raise RuntimeError("MBRM personalization factor became invalid")
    clamped_factor = min(maximum_factor, max(minimum_factor, raw_factor))

    return MbrmSessionPersonalization(
        personalization_factor=clamped_factor,
        previous_return_latency_minutes=previous_latency,
        reference_return_latency_minutes=reference_latency,
    )


@dataclass(frozen=True, slots=True)
class TriggerPolicy:
    """Admission timing only; detection thresholds remain with their owners."""

    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    rejection_retry_seconds: float = DEFAULT_REJECTION_RETRY_SECONDS

    def __post_init__(self) -> None:
        for name, value in (
            ("cooldown_seconds", self.cooldown_seconds),
            ("rejection_retry_seconds", self.rejection_retry_seconds),
        ):
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative value")


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    """Privacy-safe facts proving why one candidate exists.

    ``correlation_keys`` are session-private opaque identifiers.  They prevent
    the same dwell episode from entering through Resource Intent and the
    blacklist as two different interventions.
    """

    source: TriggerSource
    source_rule_id: str
    source_policy_version: str
    correlation_keys: tuple[str, ...]
    observation_sequence: int
    observed_monotonic_ns: int
    process_name: str
    process_id: int
    hwnd: int
    platform_key: str
    surface_class: str
    resource_key: str
    study_context_token: str
    resource_observation_token: str
    browser_evidence_kind: str
    browser_route_marker: str
    browser_resource_token: str
    dwell_seconds: float
    threshold_seconds: float
    evidence_digest: str

    def __post_init__(self) -> None:
        if self.observation_sequence < 0:
            raise ValueError("observation_sequence cannot be negative")
        if self.observed_monotonic_ns <= 0:
            raise ValueError("observed_monotonic_ns must be positive")
        if not self.process_name or self.process_id <= 0 or self.hwnd <= 0:
            raise ValueError("evidence requires an exact foreground source")
        if not self.correlation_keys or any(not key for key in self.correlation_keys):
            raise ValueError("evidence requires non-empty correlation keys")
        if not self.source_rule_id or not self.evidence_digest:
            raise ValueError("evidence requires a rule and digest")
        if not math.isfinite(self.dwell_seconds) or self.dwell_seconds < 0:
            raise ValueError("dwell_seconds must be finite and non-negative")
        if not math.isfinite(self.threshold_seconds) or self.threshold_seconds <= 0:
            raise ValueError("threshold_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class TriggerCandidate:
    """One immutable candidate awaiting durable persistence."""

    candidate_uid: str
    candidate_number: int
    session_id: int
    profile_type: str
    reason: str
    evidence: EvidenceBinding
    created_monotonic_ns: int
    recovery_model: EbbinghausEstimate | None = None
    trigger: bool = True
    schema_version: str = TRIGGER_SCHEMA_VERSION

    @property
    def app(self) -> str:
        """Compatibility-friendly factual label; not an inferred category."""

        return self.evidence.platform_key or self.evidence.process_name

    @property
    def resource_key(self) -> str:
        return self.evidence.resource_key

    @property
    def context_token(self) -> str:
        return self.evidence.study_context_token

    @property
    def app_category(self) -> str:
        return self.recovery_model.model_category if self.recovery_model else "generic"

    @property
    def d0(self) -> float | None:
        return (
            self.recovery_model.initial_magnitude_unitless
            if self.recovery_model is not None
            else None
        )

    @property
    def decay_constant(self) -> float | None:
        return (
            self.recovery_model.decay_rate_per_minute
            if self.recovery_model is not None
            else None
        )

    @property
    def t_star(self) -> float | None:
        return self.recovery_model.t_star_minutes if self.recovery_model else None


@dataclass(frozen=True, slots=True)
class TriggerResult:
    """Terminal or pending truth for exactly one candidate UID."""

    candidate_uid: str
    status: TriggerStatus
    reason: str
    operational_event_id: int | None
    candidate_created_monotonic_ns: int
    resolved_monotonic_ns: int | None
    cooldown_committed: bool
    recovery_model: EbbinghausEstimate | None = None


@dataclass(frozen=True, slots=True)
class TriggerLiveView:
    session_id: int | None
    profile_type: str
    pending_candidate_uid: str
    pending_reason: str
    last_result: TriggerResult | None
    cooldown_active: bool
    cooldown_remaining_seconds: float
    admitted_count: int
    rejected_count: int
    last_intervention_fact: str
    last_intervention_candidate_uid: str
    model_version: str = MBRM_MODEL_VERSION
    profile_decay_rate_per_minute: float | None = None
    model_ready: bool = False
    schema_version: str = TRIGGER_SCHEMA_VERSION


def _field(value: object, name: str, default=None):
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value) or "")


def _normalise_process(value: object) -> str:
    return str(value or "").strip().casefold()


class TriggerAuthority:
    """One unresolved candidate and one admission/cooldown truth source."""

    def __init__(
        self,
        *,
        profile_type: str = "GENERAL",
        policy: TriggerPolicy = TriggerPolicy(),
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")
        self._lock = threading.RLock()
        self._clock = monotonic_ns
        self._policy = policy
        self._profile_type = str(profile_type or "GENERAL").strip().upper()
        self._session_decay_rate_per_minute: float | None = None
        self._session_id: int | None = None
        self._session_secret = secrets.token_bytes(32)
        self._candidate_sequence = 0
        self._pending: TriggerCandidate | None = None
        self._results: dict[str, TriggerResult] = {}
        self._result_order: list[str] = []
        self._consumed_evidence: set[str] = set()
        self._rejected_until_ns: dict[str, int] = {}
        self._cooldown_anchor_ns = -1
        self._last_result: TriggerResult | None = None
        self._admitted_count = 0
        self._rejected_count = 0
        self._last_intervention_fact = ""
        self._last_intervention_candidate_uid = ""
        self._started = False
        self._closed = False

    def start_session(
        self,
        *,
        session_id: int,
        profile_type: str,
        decay_rate_per_minute: float | None = None,
    ) -> None:
        """Start after durable session creation and freeze this session's lambda.

        ``decay_rate_per_minute`` is the clean handoff point for PROFILES.
        Trigger owns the Ebbinghaus equation, not the profile-to-lambda table.
        If the caller has no approved lambda yet, the model is marked visibly
        unconfigured and trigger admission continues without fabricated science.
        """

        if type(session_id) is not int or session_id <= 0:
            raise ValueError("session_id must be a positive integer")
        session_decay = self._validate_optional_decay_rate(decay_rate_per_minute)
        with self._lock:
            self._session_id = session_id
            self._profile_type = str(profile_type or "GENERAL").strip().upper()
            self._session_decay_rate_per_minute = session_decay
            self._session_secret = secrets.token_bytes(32)
            self._candidate_sequence = 0
            self._pending = None
            self._results.clear()
            self._result_order.clear()
            self._consumed_evidence.clear()
            self._rejected_until_ns.clear()
            self._cooldown_anchor_ns = -1
            self._last_result = None
            self._admitted_count = 0
            self._rejected_count = 0
            self._last_intervention_fact = ""
            self._last_intervention_candidate_uid = ""
            self._started = True
            self._closed = False

    def evaluate(self, *, context: object, blacklist: object) -> TriggerCandidate | None:
        """Return one evidence-bound candidate, or no candidate.

        INSTRUCTION: a pending candidate is immutable.  Repeated evaluation
        returns that exact object until monitor.py resolves its persistence.
        """

        with self._lock:
            self._require_active()
            if self._pending is not None:
                return self._pending

            now_ns = self._now_ns()
            self._release_expired_rejections(now_ns)
            binding = self._study_binding(context, blacklist)
            reason = "study_off_task_dwell"
            if binding is None:
                binding = self._blacklist_binding(context, blacklist)
                reason = "executive_blacklist_dwell"
            if binding is None:
                return None
            if any(key in self._consumed_evidence for key in binding.correlation_keys):
                return None
            if any(
                self._rejected_until_ns.get(key, -1) > now_ns
                for key in binding.correlation_keys
            ):
                return None
            if self._cooldown_remaining_ns(now_ns) > 0:
                return None

            self._candidate_sequence += 1
            model = self._build_ebbinghaus_estimate(binding)
            candidate = TriggerCandidate(
                candidate_uid=self._mint_candidate_uid(binding),
                candidate_number=self._candidate_sequence,
                session_id=self._required_session_id(),
                profile_type=self._profile_type,
                reason=reason,
                evidence=binding,
                created_monotonic_ns=now_ns,
                recovery_model=model,
            )
            self._pending = candidate
            result = TriggerResult(
                candidate_uid=candidate.candidate_uid,
                status=TriggerStatus.PENDING_DURABILITY,
                reason=reason,
                operational_event_id=None,
                candidate_created_monotonic_ns=now_ns,
                resolved_monotonic_ns=None,
                cooldown_committed=False,
                recovery_model=candidate.recovery_model,
            )
            self._record_result(result)
            return candidate

    def candidate_uid(self, candidate: object) -> str:
        """Return a UID only for a candidate minted by this active session."""

        with self._lock:
            if not isinstance(candidate, TriggerCandidate):
                return ""
            if candidate.session_id != self._session_id:
                return ""
            uid = str(candidate.candidate_uid or "")
            if self._pending is not None and self._pending is candidate:
                return uid
            return ""

    def confirm_durable_admission(
        self,
        *,
        candidate_uid: str,
        operational_event_id: int,
    ) -> bool:
        """Admit exactly the pending candidate after a COMMITTED receipt.

        Cooldown and evidence consumption happen here—not during evaluation.
        A malformed event ID, stale UID, duplicate call, or rejected candidate
        fails closed without changing state.
        """

        if type(operational_event_id) is not int or operational_event_id <= 0:
            return False
        with self._lock:
            self._require_active()
            pending = self._pending
            uid = str(candidate_uid or "")
            if pending is None or not uid or pending.candidate_uid != uid:
                return False
            current = self._results.get(uid)
            if current is None or current.status is not TriggerStatus.PENDING_DURABILITY:
                return False

            admitted_ns = self._now_ns()
            self._cooldown_anchor_ns = admitted_ns
            self._consumed_evidence.update(pending.evidence.correlation_keys)
            self._pending = None
            self._admitted_count += 1
            result = TriggerResult(
                candidate_uid=uid,
                status=TriggerStatus.DURABLY_ADMITTED,
                reason=pending.reason,
                operational_event_id=operational_event_id,
                candidate_created_monotonic_ns=pending.created_monotonic_ns,
                resolved_monotonic_ns=admitted_ns,
                cooldown_committed=True,
                recovery_model=pending.recovery_model,
            )
            self._record_result(result)
            return True

    def reject_candidate(self, *, candidate_uid: str, reason: str) -> bool:
        """Reject exactly one pending candidate without consuming cooldown."""

        with self._lock:
            self._require_active()
            pending = self._pending
            uid = str(candidate_uid or "")
            if pending is None or not uid or pending.candidate_uid != uid:
                return False
            current = self._results.get(uid)
            if current is None or current.status is not TriggerStatus.PENDING_DURABILITY:
                return False

            rejected_ns = self._now_ns()
            retry_ns = int(
                self._policy.rejection_retry_seconds * NANOSECONDS_PER_SECOND
            )
            for key in pending.evidence.correlation_keys:
                self._rejected_until_ns[key] = rejected_ns + retry_ns
            self._pending = None
            self._rejected_count += 1
            result = TriggerResult(
                candidate_uid=uid,
                status=TriggerStatus.REJECTED,
                reason=str(reason or "candidate_rejected"),
                operational_event_id=None,
                candidate_created_monotonic_ns=pending.created_monotonic_ns,
                resolved_monotonic_ns=rejected_ns,
                cooldown_committed=False,
                recovery_model=pending.recovery_model,
            )
            self._record_result(result)
            return True

    def record_intervention_fact(self, fact: object) -> None:
        """Remember only the factual SINE lifecycle label for live status.

        The full payload belongs to SINE/MIRL/persistence.  Trigger deliberately
        does not copy presentation text or reinterpret the event.
        """

        with self._lock:
            if not self._started or self._closed:
                return
            kind = str(_field(fact, "kind", _field(fact, "event", "")) or "").upper()
            uid = str(_field(fact, "candidate_uid", "") or "")
            event_id = _field(fact, "operational_event_id", None)
            if uid and uid not in self._results:
                return
            if not uid and type(event_id) is int:
                uid = self._candidate_for_event_id(event_id)
            self._last_intervention_fact = kind[:80]
            self._last_intervention_candidate_uid = uid

    def live_view(self) -> TriggerLiveView:
        with self._lock:
            now_ns = self._now_ns() if self._started and not self._closed else 0
            remaining_ns = self._cooldown_remaining_ns(now_ns)
            pending = self._pending
            configured_decay = self._configured_decay_rate()
            return TriggerLiveView(
                session_id=self._session_id,
                profile_type=self._profile_type,
                pending_candidate_uid=pending.candidate_uid if pending else "",
                pending_reason=pending.reason if pending else "",
                last_result=self._last_result,
                cooldown_active=remaining_ns > 0,
                cooldown_remaining_seconds=remaining_ns / NANOSECONDS_PER_SECOND,
                admitted_count=self._admitted_count,
                rejected_count=self._rejected_count,
                last_intervention_fact=self._last_intervention_fact,
                last_intervention_candidate_uid=self._last_intervention_candidate_uid,
                profile_decay_rate_per_minute=configured_decay,
                model_ready=bool(
                    self._started and not self._closed and configured_decay is not None
                ),
            )

    def trigger_result(self, candidate_uid: str) -> TriggerResult | None:
        """Return immutable truth for one known candidate."""

        with self._lock:
            return self._results.get(str(candidate_uid or ""))

    def estimate_observed_lambda(
        self,
        *,
        candidate_uid: str,
        verified_recovery_minutes: float,
    ) -> ObservedLambdaEstimate | None:
        """Return one reverse-Ebbinghaus estimate for a durably admitted trigger.

        Recovery truth is not decided here.  A later MIRL/monitor phase must
        supply the factual verified duration and the exact candidate UID.  This
        method is read-only: it never updates the profile learning table and it
        never mutates the lambda frozen for the active session.
        """

        uid = str(candidate_uid or "").strip()
        if not uid:
            return None
        with self._lock:
            self._require_active()
            result = self._results.get(uid)
            if result is None or result.status is not TriggerStatus.DURABLY_ADMITTED:
                return None
            model = result.recovery_model
            if model is None:
                return None

            observed_lambda = ebbinghaus_lambda_from_verified_recovery(
                model.initial_magnitude_unitless,
                verified_recovery_minutes,
                model.resolution_threshold_unitless,
            )
            return ObservedLambdaEstimate(
                model_version=model.model_version,
                candidate_uid=uid,
                profile_type=model.profile_type,
                model_category=model.model_category,
                initial_magnitude_unitless=model.initial_magnitude_unitless,
                resolution_threshold_unitless=model.resolution_threshold_unitless,
                verified_recovery_minutes=float(verified_recovery_minutes),
                observed_decay_rate_per_minute=observed_lambda,
            )

    def shutdown(self) -> None:
        with self._lock:
            self._pending = None
            self._results.clear()
            self._result_order.clear()
            self._consumed_evidence.clear()
            self._rejected_until_ns.clear()
            self._session_secret = secrets.token_bytes(32)
            self._session_id = None
            self._session_decay_rate_per_minute = None
            self._cooldown_anchor_ns = -1
            self._last_result = None
            self._started = False
            self._closed = True

    @staticmethod
    def _validate_optional_decay_rate(value: float | None) -> float | None:
        if value is None:
            return None
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError("decay_rate_per_minute must be finite and positive")
        return result

    def _configured_decay_rate(self) -> float | None:
        return self._session_decay_rate_per_minute

    def _build_ebbinghaus_estimate(
        self,
        binding: EvidenceBinding,
    ) -> EbbinghausEstimate:
        category = self._model_category(binding)
        multipliers = dict(MODEL_MAGNITUDE_MULTIPLIERS)
        multiplier = multipliers.get(category, multipliers["generic"])
        d0 = INITIAL_MAGNITUDE_UNITLESS * multiplier
        decay = self._configured_decay_rate()
        source = (
            "session_profile_snapshot"
            if decay is not None
            else "unconfigured_profile"
        )
        if decay is None:
            return EbbinghausEstimate(
                model_version=MBRM_MODEL_VERSION,
                status=EbbinghausStatus.PROFILE_LAMBDA_UNCONFIGURED,
                profile_type=self._profile_type,
                lambda_source=source,
                model_category=category,
                initial_magnitude_unitless=d0,
                magnitude_multiplier=multiplier,
                decay_rate_per_minute=None,
                resolution_threshold_unitless=RESOLUTION_THRESHOLD_UNITLESS,
                t_star_minutes=None,
            )

        t_star = ebbinghaus_t_star_minutes(
            d0,
            decay,
            RESOLUTION_THRESHOLD_UNITLESS,
        )
        # Exercise Equation 1 with the exact t* as a runtime consistency check.
        # Floating-point tolerance is deliberately narrow but not exact.
        resolved = ebbinghaus_residual_engagement(d0, decay, t_star)
        expected = min(d0, RESOLUTION_THRESHOLD_UNITLESS)
        if not math.isclose(resolved, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise RuntimeError("Ebbinghaus model consistency check failed")

        return EbbinghausEstimate(
            model_version=MBRM_MODEL_VERSION,
            status=EbbinghausStatus.COMPUTED,
            profile_type=self._profile_type,
            lambda_source=source,
            model_category=category,
            initial_magnitude_unitless=d0,
            magnitude_multiplier=multiplier,
            decay_rate_per_minute=decay,
            resolution_threshold_unitless=RESOLUTION_THRESHOLD_UNITLESS,
            t_star_minutes=t_star,
        )

    @staticmethod
    def _model_category(binding: EvidenceBinding) -> str:
        surface = str(binding.surface_class or "").strip().casefold()
        return dict(MODEL_CATEGORY_BY_SURFACE).get(surface, "generic")

    def _study_binding(self, context: object, blacklist: object) -> EvidenceBinding | None:
        foreground = _field(context, "foreground")
        intent_snapshot = _field(context, "resource_intent")
        verdict = _field(intent_snapshot, "verdict")
        if not self._context_scope_matches(foreground, intent_snapshot, blacklist):
            return None
        if bool(_field(intent_snapshot, "protected_red_active", False)):
            return None
        if bool(_field(intent_snapshot, "cosine_active", False)):
            return None
        if _field(verdict, "sine_contribution") is not SineContribution.READY:
            return None
        if _field(verdict, "classification") is not ResourceIntent.DISTRACTION:
            return None

        study_token = str(_field(verdict, "study_context_token", "") or "")
        resource_identity = _field(verdict, "resource_identity")
        resource_key = str(_field(resource_identity, "stable_key", "") or "")
        observation_token = str(_field(verdict, "observation_token", "") or "")
        if not study_token or not resource_key or not observation_token:
            return None

        dwell_seconds = float(_field(verdict, "off_task_dwell_seconds", 0.0) or 0.0)
        blacklist_target = float(_field(blacklist, "target_seconds", 300.0) or 300.0)
        if not math.isfinite(dwell_seconds) or dwell_seconds < blacklist_target:
            return None

        study_episode = self._opaque_evidence_key(
            "study",
            study_token,
            resource_key,
        )
        aliases = [study_episode]
        offer = _field(blacklist, "threshold_offer")
        offer_uid = str(_field(offer, "offer_uid", "") or "")
        if offer_uid and self._blacklist_offer_matches(context, blacklist, offer):
            aliases.append(self._opaque_evidence_key("blacklist", offer_uid))

        return self._make_binding(
            context=context,
            source=TriggerSource.STUDY_OFF_TASK,
            source_rule_id="RI-STUDY-OFF-TASK-READY-001",
            source_policy_version=str(_field(verdict, "classifier_version", "") or ""),
            correlation_keys=tuple(dict.fromkeys(aliases)),
            platform_key=str(_field(resource_identity, "platform_key", "") or ""),
            surface_class=_enum_value(_field(resource_identity, "surface", "")),
            resource_key=resource_key,
            study_context_token=study_token,
            observation_token=observation_token,
            dwell_seconds=dwell_seconds,
            threshold_seconds=blacklist_target,
        )

    def _blacklist_binding(self, context: object, blacklist: object) -> EvidenceBinding | None:
        intent_verdict = _field(_field(context, "resource_intent"), "verdict")

        # An approved COSECANT break already granted the user temporary
        # behavioural permission, and COSECANT alone owns the return
        # regulation for its duration.  Founding a SINE intervention from
        # break-time activity would put a second authority on the same moment
        # and could fire halfway through the very break it is supervising.
        #
        # This suppresses INTERVENTION FOUNDING only.  Blacklist keeps
        # observing, measuring dwell and describing the resource, so MYELIN
        # can still report truthfully what happened during the break; it
        # simply may not conclude "therefore intervene".
        #
        # Trigger deliberately reads the factual policy result and not any
        # COSECANT state: it does not know or need BREAK_ACTIVE,
        # BREAK_COMPLETE, BREAK_ALREADY_OVER, FINAL_LOCK or RETURN_CONFIRMING.
        # The moment that factual break ownership ends, normal intervention
        # policy returns by itself -- this is state-scoped, never session-wide.
        if _field(intent_verdict, "classification") is ResourceIntent.APPROVED_BREAK:
            return None

        offer = _field(blacklist, "threshold_offer")
        if offer is None or not self._blacklist_offer_matches(context, blacklist, offer):
            return None
        resource_identity = _field(intent_verdict, "resource_identity")
        offer_uid = str(_field(offer, "offer_uid", "") or "")
        return self._make_binding(
            context=context,
            source=TriggerSource.EXECUTIVE_BLACKLIST,
            source_rule_id=str(_field(offer, "rule_id", "") or ""),
            source_policy_version=str(_field(offer, "policy_version", "") or ""),
            correlation_keys=(self._opaque_evidence_key("blacklist", offer_uid),),
            platform_key=str(_field(offer, "platform_key", "") or ""),
            surface_class=str(_field(offer, "surface_class", "") or ""),
            resource_key=str(_field(offer, "resource_key", "") or ""),
            study_context_token=str(_field(intent_verdict, "study_context_token", "") or ""),
            observation_token=str(_field(intent_verdict, "observation_token", "") or ""),
            dwell_seconds=float(_field(offer, "dwell_seconds", 0.0) or 0.0),
            threshold_seconds=float(_field(offer, "threshold_seconds", 0.0) or 0.0),
        )

    def _context_scope_matches(
        self,
        foreground: object,
        intent_snapshot: object,
        blacklist: object,
    ) -> bool:
        if foreground is None or intent_snapshot is None or blacklist is None:
            return False
        sequence = int(_field(foreground, "sequence", -1) or 0)
        observed_ns = int(_field(foreground, "observed_monotonic_ns", 0) or 0)
        observation = _field(intent_snapshot, "observation")
        if observation is None or not bool(_field(intent_snapshot, "fresh", False)):
            return False
        return bool(
            sequence == int(_field(observation, "sequence", -2) or 0)
            and sequence == int(_field(blacklist, "observation_sequence", -3) or 0)
            and observed_ns == int(_field(observation, "observed_monotonic_ns", -1) or 0)
            and _normalise_process(_field(foreground, "process_name", ""))
            == _normalise_process(_field(observation, "process_name", ""))
            and int(_field(foreground, "process_id", 0) or 0)
            == int(_field(observation, "process_id", -1) or 0)
            and int(_field(foreground, "hwnd", 0) or 0)
            == int(_field(observation, "hwnd", -1) or 0)
        )

    def _blacklist_offer_matches(
        self,
        context: object,
        blacklist: object,
        offer: object,
    ) -> bool:
        foreground = _field(context, "foreground")
        intent_snapshot = _field(context, "resource_intent")
        if not self._context_scope_matches(foreground, intent_snapshot, blacklist):
            return False
        verdict = _field(blacklist, "verdict")
        source = _field(blacklist, "source_identity")
        resource_identity = _field(_field(intent_snapshot, "verdict"), "resource_identity")
        offer_uid = str(_field(offer, "offer_uid", "") or "")
        return bool(
            offer_uid
            and bool(_field(blacklist, "threshold_reached", False))
            and _field(verdict, "disposition") in {Disposition.ACCUSED, Disposition.UNKNOWN}
            and bool(_field(verdict, "actionable", False))
            and int(_field(offer, "observed_monotonic_ns", -1) or 0)
            == int(_field(foreground, "observed_monotonic_ns", 0) or 0)
            and _normalise_process(_field(offer, "source_process", ""))
            == _normalise_process(_field(foreground, "process_name", ""))
            and int(_field(offer, "source_process_id", -1) or 0)
            == int(_field(foreground, "process_id", 0) or 0)
            and int(_field(offer, "source_hwnd", -1) or 0)
            == int(_field(foreground, "hwnd", 0) or 0)
            and _normalise_process(_field(source, "process_name", ""))
            == _normalise_process(_field(foreground, "process_name", ""))
            and int(_field(source, "process_id", -1) or 0)
            == int(_field(foreground, "process_id", 0) or 0)
            and int(_field(source, "hwnd", -1) or 0)
            == int(_field(foreground, "hwnd", 0) or 0)
            and str(_field(offer, "platform_key", "") or "")
            == str(_field(verdict, "platform_key", "") or "")
            and str(_field(offer, "rule_id", "") or "")
            == str(_field(verdict, "rule_id", "") or "")
            and str(_field(offer, "resource_key", "") or "")
            == str(_field(resource_identity, "stable_key", "") or "")
            and float(_field(offer, "dwell_seconds", 0.0) or 0.0)
            >= float(_field(offer, "threshold_seconds", math.inf) or math.inf)
        )

    def _make_binding(
        self,
        *,
        context: object,
        source: TriggerSource,
        source_rule_id: str,
        source_policy_version: str,
        correlation_keys: tuple[str, ...],
        platform_key: str,
        surface_class: str,
        resource_key: str,
        study_context_token: str,
        observation_token: str,
        dwell_seconds: float,
        threshold_seconds: float,
    ) -> EvidenceBinding:
        foreground = _field(context, "foreground")
        browser_snapshot = _field(context, "browser_evidence")
        browser_evidence = _field(browser_snapshot, "evidence")
        facts = (
            source.value,
            source_rule_id,
            *correlation_keys,
            str(_field(foreground, "sequence", 0) or 0),
            str(_field(foreground, "observed_monotonic_ns", 0) or 0),
            _normalise_process(_field(foreground, "process_name", "")),
            str(_field(foreground, "process_id", 0) or 0),
            str(_field(foreground, "hwnd", 0) or 0),
            platform_key,
            surface_class,
            resource_key,
            study_context_token,
            observation_token,
            _enum_value(_field(browser_evidence, "kind", "")),
            str(_field(browser_evidence, "marker", "") or ""),
            str(_field(browser_evidence, "resource_token", "") or ""),
        )
        digest = self._keyed_digest("|".join(facts))
        return EvidenceBinding(
            source=source,
            source_rule_id=source_rule_id,
            source_policy_version=source_policy_version,
            correlation_keys=correlation_keys,
            observation_sequence=int(_field(foreground, "sequence", 0) or 0),
            observed_monotonic_ns=int(
                _field(foreground, "observed_monotonic_ns", 0) or 0
            ),
            process_name=_normalise_process(_field(foreground, "process_name", "")),
            process_id=int(_field(foreground, "process_id", 0) or 0),
            hwnd=int(_field(foreground, "hwnd", 0) or 0),
            platform_key=platform_key,
            surface_class=surface_class,
            resource_key=resource_key,
            study_context_token=study_context_token,
            resource_observation_token=observation_token,
            browser_evidence_kind=_enum_value(_field(browser_evidence, "kind", "")),
            browser_route_marker=str(_field(browser_evidence, "marker", "") or ""),
            browser_resource_token=str(
                _field(browser_evidence, "resource_token", "") or ""
            ),
            dwell_seconds=dwell_seconds,
            threshold_seconds=threshold_seconds,
            evidence_digest=digest,
        )

    def _mint_candidate_uid(self, binding: EvidenceBinding) -> str:
        nonce = secrets.token_hex(16)
        material = (
            f"{self._required_session_id()}|{self._candidate_sequence}|"
            f"{binding.evidence_digest}|{nonce}"
        )
        return f"trg_{self._keyed_digest(material)[:32]}"

    def _opaque_evidence_key(self, *parts: str) -> str:
        return f"ev_{self._keyed_digest('|'.join(str(part) for part in parts))[:32]}"

    def _keyed_digest(self, value: str) -> str:
        return hashlib.blake2s(
            value.encode("utf-8", errors="replace"),
            key=self._session_secret,
            digest_size=32,
        ).hexdigest()

    def _cooldown_remaining_ns(self, now_ns: int) -> int:
        if self._cooldown_anchor_ns < 0:
            return 0
        duration = int(self._policy.cooldown_seconds * NANOSECONDS_PER_SECOND)
        elapsed = now_ns - self._cooldown_anchor_ns
        if elapsed < 0:
            return duration
        return max(0, duration - elapsed)

    def _release_expired_rejections(self, now_ns: int) -> None:
        expired = [key for key, deadline in self._rejected_until_ns.items() if deadline <= now_ns]
        for key in expired:
            self._rejected_until_ns.pop(key, None)

    def _record_result(self, result: TriggerResult) -> None:
        uid = result.candidate_uid
        if uid not in self._results:
            self._result_order.append(uid)
        self._results[uid] = result
        self._last_result = result
        while len(self._result_order) > MAX_RECORDED_RESULTS:
            oldest = self._result_order.pop(0)
            if self._pending is None or self._pending.candidate_uid != oldest:
                self._results.pop(oldest, None)

    def _candidate_for_event_id(self, operational_event_id: int) -> str:
        for uid in reversed(self._result_order):
            result = self._results.get(uid)
            if result is not None and result.operational_event_id == operational_event_id:
                return uid
        return ""

    def _now_ns(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0:
            raise RuntimeError("monotonic clock returned an invalid value")
        return value

    def _required_session_id(self) -> int:
        if self._session_id is None:
            raise RuntimeError("trigger session has no durable session id")
        return self._session_id

    def _require_active(self) -> None:
        if not self._started or self._closed:
            raise RuntimeError("Trigger session is not active")


__all__ = (
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_REJECTION_RETRY_SECONDS",
    "EbbinghausEstimate",
    "EbbinghausStatus",
    "EvidenceBinding",
    "INITIAL_MAGNITUDE_UNITLESS",
    "MBRM_MODEL_VERSION",
    "MODEL_CATEGORY_BY_SURFACE",
    "MODEL_MAGNITUDE_MULTIPLIERS",
    "MbrmSessionPersonalization",
    "ObservedLambdaEstimate",
    "PERSONALIZATION_FACTOR_MAXIMUM",
    "PERSONALIZATION_FACTOR_MINIMUM",
    "REFERENCE_RETURN_LATENCY_MINUTES",
    "RESOLUTION_THRESHOLD_UNITLESS",
    "TriggerAuthority",
    "TriggerCandidate",
    "TriggerLiveView",
    "TriggerPolicy",
    "TriggerResult",
    "TriggerSource",
    "TriggerStatus",
    "ebbinghaus_lambda_from_verified_recovery",
    "ebbinghaus_residual_engagement",
    "ebbinghaus_t_star_minutes",
    "mbrm_session_personalization",
)
