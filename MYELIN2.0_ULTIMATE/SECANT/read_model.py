"""SECANT-native immutable projections; no runtime or persistence access."""
from dataclasses import dataclass, field, asdict
import json
from enum import Enum, IntEnum


class Stage(IntEnum):
    NONE = 0
    SECANT_1 = 1
    SECANT_2 = 2
    SECANT_3 = 3


class RecoveryPhase(str, Enum):
    IDLE = "IDLE"
    VERIFYING = "VERIFYING"
    CONFIRMING = "CONFIRMING"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class StudyScope:
    """Opaque factual identity; supplied by a future adapter, not classified here."""
    context_id: str
    target_resource_id: str

    def __post_init__(self):
        if any(type(v) is not str or not v.strip() for v in (self.context_id, self.target_resource_id)):
            raise ValueError("Exact Study context and accepted/planned resource required")


@dataclass(frozen=True, slots=True)
class TimelineFact:
    name: str
    at_ns: int
    episode_id: str = ""
    stage: Stage = Stage.NONE
    request_id: str = ""
    attempt_id: str = ""
    reason: str = ""
    evidence_id: str = ""
    founding_source: "FoundingSourceEvidence | None" = None


@dataclass(frozen=True, slots=True)
class ClosureProof:
    episode_id: str
    scope: StudyScope
    attempt_id: str
    return_started_ns: int
    verified_ns: int
    closed_ns: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryProjection:
    phase: RecoveryPhase = RecoveryPhase.IDLE
    attempt_id: str = ""
    verification_elapsed_ns: int = 0
    closure_elapsed_ns: int = 0
    proof: ClosureProof | None = None
    global_hold_id: str = ""
    revalidation_pending: bool = False
    verification_target_ns: int | None = None
    closure_target_ns: int | None = None


@dataclass(frozen=True, slots=True)
class EpisodeProjection:
    episode_id: str
    scope: StudyScope
    stage: Stage
    founded_ns: int
    closed_ns: int
    terminal_reason: str
    recovery: RecoveryProjection
    timeline: tuple[TimelineFact, ...]


@dataclass(frozen=True, slots=True)
class PresentationLifecycle:
    """Read-only reconciliation state; an unresolved display is not no episode."""
    request_id: str = ""
    display_id: str = ""
    sequence: int = 0
    occurred_at_ns: int = 0
    received_at_ns: int = 0
    unresolved_display: bool = False
    buffered_sequences: tuple[int, ...] = ()
    pending_evidence_count: int = 0
    pre_episode_reset_waiting: bool = False


@dataclass(frozen=True, slots=True)
class SecantProjection:
    scope: StudyScope | None
    episode_id: str
    stage: Stage
    dwell_elapsed_ns: int
    escalation_remaining_ns: int | None
    frozen_reasons: tuple[str, ...]
    popup_request_id: str
    popup_state: str
    requested_stage: Stage
    recovery: RecoveryProjection
    terminal_reason: str
    timeline: tuple[TimelineFact, ...]
    completed: tuple[EpisodeProjection, ...]
    presentation: PresentationLifecycle = PresentationLifecycle()
    resources: tuple["StudyResourceFact", ...] = ()
    uncertainty_hold_id: str = ""
    break_pause: "BreakPauseProjection | None" = None
    global_hold_id: str = ""
    cleanup_pending: bool = False
    dwell_active: bool = False
    dwell_target_ns: int | None = None
    # Read-only clock-face anchor; never consumed by SECANT decisions/evidence.
    escalation_deadline_monotonic_ns: int | None = None


@dataclass(frozen=True, slots=True)
class ExactResource:
    """V1 browser token or existing desktop window identity; no file sensing."""
    kind: str
    key: str
    platform_key: str = ""
    resource_token: str = ""
    process_name: str = ""
    process_id: int = 0
    hwnd: int = 0
    normalized_title: str = ""
    version: int = 1

    def __post_init__(self):
        if self.kind not in {"BROWSER", "DESKTOP"} or not self.key or self.version != 1:
            raise ValueError("Typed versioned exact resource required")
        if self.kind == "BROWSER" and not (self.platform_key and self.resource_token):
            raise ValueError("Certified browser platform/resource identity required")
        if self.kind == "DESKTOP" and not (self.process_name and self.process_id > 0 and self.hwnd > 0):
            raise ValueError("Existing app/PID/HWND/title identity required")


@dataclass(frozen=True, slots=True)
class ResourceDisplayMetadata:
    """Observed foreground browser window caption, never identity authority."""
    observed_caption: str
    normalized_caption: str
    source_observation_id: str
    source_observation_sequence: int
    source_observed_monotonic_ns: int
    metadata_version: int = 1
    normalization_version: str = "resource-intent-normalise-title-v1"

    def __post_init__(self):
        if (type(self.metadata_version) is not int or self.metadata_version != 1
                or self.normalization_version != "resource-intent-normalise-title-v1"
                or any(type(v) is not str or not v.strip() or len(v) > 16384
                       for v in (self.observed_caption, self.normalized_caption))
                or len(self.observed_caption) > 4096
                or type(self.source_observation_id) is not str
                or not self.source_observation_id or len(self.source_observation_id) > 1024
                or any(type(v) is not int or not 0 <= v <= 9223372036854775807
                       for v in (self.source_observation_sequence, self.source_observed_monotonic_ns))):
            raise ValueError("Bounded versioned foreground-caption metadata required")
        # Leave room for existing authority evidence inside its 30 KB envelope.
        # Do not truncate a caption and present the result as the observed value.
        if len(json.dumps(asdict(self), ensure_ascii=True).encode("utf-8")) > 8192:
            raise ValueError("Display metadata exceeds its optional payload budget")


def validate_display_metadata(value, *, observation_id=None, sequence=None, observed_ns=None):
    """Validate a separate optional envelope and its originating observation."""
    if value is None:
        return None
    if isinstance(value, ResourceDisplayMetadata):
        metadata = value
    elif type(value) is dict and set(value) == set(ResourceDisplayMetadata.__dataclass_fields__):
        metadata = ResourceDisplayMetadata(**value)
    else:
        raise ValueError("Unexpected display metadata shape")
    for actual, expected in ((metadata.source_observation_id, observation_id),
                             (metadata.source_observation_sequence, sequence),
                             (metadata.source_observed_monotonic_ns, observed_ns)):
        if expected is not None and actual != expected:
            raise ValueError("Display metadata observation mismatch")
    return metadata


@dataclass(frozen=True, slots=True)
class FoundingSourceEvidence:
    """Exact qualifying observation; independent of the canonical SECANT fact."""
    resource: ExactResource
    evidence_id: str
    observed_monotonic_ns: int
    meaning: str
    classification: str
    territory: str
    confirmed_off_task: bool
    certified_ott: bool
    display_metadata: ResourceDisplayMetadata | None = field(default=None, compare=False)

    def __post_init__(self):
        if self.display_metadata is not None and not isinstance(self.display_metadata, ResourceDisplayMetadata):
            raise ValueError("Immutable source display metadata required")
        validate_display_metadata(self.display_metadata, observation_id=self.evidence_id,
                                  observed_ns=self.observed_monotonic_ns)
        if (not isinstance(self.resource, ExactResource)
                or type(self.evidence_id) is not str or not self.evidence_id
                or type(self.observed_monotonic_ns) is not int
                or not 0 <= self.observed_monotonic_ns <= 9223372036854775807
                or self.meaning not in {"OFF_TASK", "STUDY_ALIGNED", "UNCERTAIN", "ACTIVITY"}
                or self.classification not in {"STUDY_ALIGNED", "UNCERTAIN", "DISTRACTION", "APPROVED_BREAK", "BACKGROUND_AUDIO"}
                or self.territory not in {"ORDINARY", "VIDEO", "SHORT_VIDEO", "MESSAGING", "SOCIAL", "GAMING"}
                or type(self.confirmed_off_task) is not bool or type(self.certified_ott) is not bool):
            raise ValueError("Exact source observation required")


@dataclass(frozen=True, slots=True)
class StudyResourceFact:
    resource_fact_id: str
    session_id: int
    study_block_id: str
    study_generation: int
    study_context_token: str
    resource: ExactResource
    role: str
    first_aligned_monotonic_ns: int
    qualified_monotonic_ns: int
    first_aligned_at_utc: str
    qualified_at_utc: str
    provenance_json: str
    contract_version: int = 1

    def __post_init__(self):
        if (not self.resource_fact_id or self.session_id <= 0 or not self.study_block_id
                or self.study_generation <= 0 or not self.study_context_token
                or not isinstance(self.resource, ExactResource) or self.role not in {"PRIMARY", "LATER"}
                or self.first_aligned_monotonic_ns < 0
                or self.qualified_monotonic_ns < self.first_aligned_monotonic_ns
                or not self.first_aligned_at_utc or not self.qualified_at_utc
                or self.contract_version != 1):
            raise ValueError("Complete immutable Study-resource fact required")


@dataclass(frozen=True, slots=True)
class BreakPauseProjection:
    pause_id: str = ""
    cosecant_break_id: str = ""
    state: str = "IDLE"


@dataclass(frozen=True, slots=True)
class PauseEligibility:
    session_id: int
    revision: int
    allowed: bool
    reason: str = ""
