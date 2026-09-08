"""The single Resource Intent authority for MYELIN.

Resource Intent answers one question:

    "What does the current resource mean inside the active study block?"

It does not watch Windows, read browser controls, schedule SINE, show popups,
write SQLite, or calculate COSINE/MIRL truth.  ``monitor.py`` supplies one
foreground observation and the already-certified result from ``browser.py``.

Decision order
--------------
1. Normalise the supplied facts.
2. Build one stable, privacy-safe resource identity.
3. Apply lifecycle precedence (Protected Red, Study, break, COSINE).
4. Apply an exact study-material allowance, if it was safely confirmed.
5. Classify distraction or uncertainty.
6. Advance continuous off-task YouTube dwell without consulting Windows idle.
7. Publish one immutable live view for SINE and the Control Station.

Scientific safety rule
----------------------
A window title is supporting context only.  It can never prove a browser host,
a YouTube route, or a study resource.  Therefore title similarity remains
``UNCERTAIN`` at 50%.

Two routes can produce ``STUDY_ALIGNED``: factual C4 Study evidence measured
against a certified resource identity, and a current exact manual allowance.
Only the manual-allowance route additionally permits Study Mode idle handling
-- automatic alignment is a statement about the resource, not a permission.
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
import threading
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

from CORE_ENGINE.browser import BrowserUrlReadStatus, UrlEvidenceKind
from COSECANT_STUDY_MODE.study_alignment import study_evidence


# v2: factual Study evidence can now produce STUDY_ALIGNED on its own.  Before
# C4 only an exact manual allowance could, so a stored v1 verdict does not
# mean the same thing as a v2 one.  Trigger records this string as its
# source-policy provenance, so the bump keeps old research rows honest.
# v3: an exact manual allowance now also requires the CURRENT identity to be
# allowance-eligible.  Under v2 stable-key equality alone could exercise a held
# uncertified Browser read as current permission, so a stored v2
# EXACT_ALLOWANCE verdict does not mean the same thing as a v3 one.
# v4: Protected Red no longer replaces the factual resource classification.
# Under v3 every verdict recorded during Red was UNCERTAIN/PROTECTED_RED
# regardless of what the user was actually looking at, so v3 rows cannot be
# compared with v4 rows that report the real resource while Red is running.
# Red still suppresses idle permission and SINE contribution in
# ``_with_sine_policy``; only the sensory reporting changed.
# v5: a measured 50% Study uncertainty now remains scientifically uncertain
# until algorithmic or human clarification.  It no longer ages into
# distraction through ordinary off-task dwell, and user confirmation is kept
# separately from the measured classifier result.
# v6: certified OTT identity is now transported separately from COSINE
# ownership.  ACTIVE Study and its COSECANT break classify factual OTT and
# Messaging collisions as DISTRACTION and share the existing off-task dwell.
# Stored v5 verdicts cannot claim those ownership/routing semantics.
CLASSIFIER_VERSION: Final = "myelin-resource-intent-v6"
OBSERVATION_FRESHNESS_NS: Final = 5_000_000_000
STUDY_UNCERTAINTY_INTERVAL_SECONDS: Final = 300
STUDY_UNCERTAINTY_INTERVAL_NS: Final = (
    STUDY_UNCERTAINTY_INTERVAL_SECONDS * 1_000_000_000
)
STUDY_CONFIRMATION_MEMORY_CAPACITY: Final = 7
DISTRACTION_THRESHOLD: Final = 0.80

# Operational Study bands.  These live here, with the verdict authority, and
# never in the calculator -- the calculator returns evidence, this file decides
# what the evidence means.
#
# CANDIDATE ENGINEERING POLICY, not scientifically validated constants.  They
# are inherited from the pre-C2 implementation and are still awaiting forensic
# confirmation.  75 is load-bearing against the frozen calculator, which caps
# structurally weak evidence at 74 (uncertified identity, a single eligible
# keyword, unresolved background mismatch), so those cases cannot reach the
# aligned band no matter how high the lexical score is.
STUDY_ALIGNED_MIN_CONFIDENCE: Final = 75.0
STUDY_UNCERTAIN_MIN_CONFIDENCE: Final = 25.0


class ResourceIntent(str, Enum):
    STUDY_ALIGNED = "STUDY_ALIGNED"
    UNCERTAIN = "UNCERTAIN"
    DISTRACTION = "DISTRACTION"
    APPROVED_BREAK = "APPROVED_BREAK"
    BACKGROUND_AUDIO = "BACKGROUND_AUDIO"


class ResourceSurface(str, Enum):
    UNKNOWN = "unknown"
    WEB_CONTENT = "web_content"
    YOUTUBE_WATCH = "youtube_watch"
    YOUTUBE_OTHER = "youtube_other"
    YOUTUBE_SHORTS = "youtube_shorts"
    BROWSER_INTERNAL = "browser_internal"
    DOCUMENT = "document"
    LEARNING_APP = "learning_app"
    MESSAGING = "messaging"
    SOCIAL = "social"
    GAMING = "gaming"
    COSINE = "cosine"


class IntentReason(str, Enum):
    NO_ACTIVE_STUDY_BLOCK = "no_active_study_block"
    STUDY_PAUSED = "study_paused"
    APPROVED_BREAK = "approved_cosecant_break"
    PROTECTED_RED = "protected_red_precedence"
    COSINE = "cosine_precedence"
    STALE_OBSERVATION = "stale_observation"
    EMPTY_OBSERVATION = "empty_observation"
    EXACT_ALLOWANCE = "exact_study_material_allowance"
    TITLE_SUPPORT_ONLY = "title_is_supporting_context_only"
    SUBJECT_WORD_ONLY = "subject_word_alone_is_not_proof"
    BROWSER_EVIDENCE_UNAVAILABLE = "browser_evidence_unavailable"
    UNSUPPORTED_SURFACE = "unsupported_surface"
    MESSAGING_SEPARATE_POLICY = "messaging_uses_separate_policy"
    STRONG_DISTRACTION = "strong_distraction_signal"
    GAMING = "gaming_collision"
    ENTERTAINMENT = "entertainment_collision"
    EDUCATIONAL_SHORTS_UNCERTAIN = "educational_shorts_remain_uncertain"
    BACKGROUND_AUDIO = "background_audio_low_authority"
    OFF_TASK_WATCH_PENDING = "sustained_off_task_watch_pending"
    OFF_TASK_WATCH_READY = "sustained_off_task_watch_ready"
    # Operational outcomes of the Study-evidence branch.  The calculator's own
    # mathematical diagnostics (safety caps, mismatch terms, suspicious
    # keywords) stay in the calculator; these three say only what BSF decided.
    STUDY_EVIDENCE_ALIGNED = "study_evidence_aligned"
    STUDY_EVIDENCE_UNCERTAIN = "study_evidence_uncertain"
    STUDY_EVIDENCE_OFF_TASK = "study_evidence_off_task"


class SineContribution(str, Enum):
    NONE = "none"
    PENDING = "pending"
    READY = "ready"
    WITHHELD = "withheld"


class AllowanceOutcome(str, Enum):
    GRANTED = "granted"
    DENIED_NO_ACTIVE_BLOCK = "denied_no_active_block"
    DENIED_UNSAFE_SURFACE = "denied_unsafe_surface"
    DENIED_CONTEXT_CHANGED = "denied_context_changed"


class StudyUserConfirmation(str, Enum):
    NONE = "NONE"
    STUDY = "STUDY"
    OFF_TASK = "OFF_TASK"


class StudyEffectiveState(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    STUDY_ALIGNED = "STUDY_ALIGNED"
    CONFIRMED_DISTRACTION = "CONFIRMED_DISTRACTION"


class StudyConfirmationResponse(str, Enum):
    THIS_IS_STUDY_MATERIAL = "this_is_study_material"
    IM_COMING_BACK = "im_coming_back"


def _keyword_tuple(values: object, field_name: str) -> tuple[str, ...]:
    """Normalise one declared keyword collection without reinterpreting it.

    A bare string is REJECTED rather than iterated, because otherwise

        "dopamine"

    would silently become

        ("d", "o", "p", "a", "m", "i", "n", "e")

    and manufacture eight worthless single-letter Study keywords.  This
    mirrors ``COSECANT_STUDY_MODE.study._keyword_input_tuple``, which owns the
    same rule on the StudyRuntime side; both ends of the carrier fail closed.

    Elements are checked, never coerced.  ``str(value)`` would turn

        ["dopamine", 42]

    into

        ("dopamine", "42")

    and accept a Study target that ``StudyRuntime`` itself refuses: its
    ``_clean_text`` raises "text contract values must be strings" for exactly
    this input, because a fabricated keyword is false Study data.  The carrier
    must never admit a target the runtime would have rejected.

    Shape and immutability only.  The elements are NOT cleaned, normalised or
    deduplicated here: ``StudyRuntime`` already produced canonical tuples on
    the real path, and re-cleaning them would make this a second normalisation
    authority disagreeing with the first.

    ``None`` means "no keywords were declared" and yields an empty tuple.  An
    empty target simply provides nothing to score, which can never produce
    automatic Study protection, so that direction is safe.
    """

    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise TypeError(
            f"{field_name} must be an iterable of strings, not one string"
        )
    try:
        result = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{field_name} must be an iterable of strings") from exc
    # ``isinstance`` rather than ``type(...) is str`` so this matches
    # ``study._clean_text`` exactly; being stricter than the runtime would be
    # its own kind of contract divergence.
    if not all(isinstance(value, str) for value in result):
        raise TypeError(f"{field_name} entries must be strings")
    return result


@dataclass(frozen=True, slots=True)
class StudyContext:
    """Authoritative Study facts supplied to Resource Intent.

    This contract is deliberately limited to two kinds of fact:

        Study TARGET facts    subject, task, keywords, important_keywords
        Study LIFECYCLE facts block identity, generation, ACTIVE/BREAK,
                              remaining time

    It must never carry a decision -- no score, confidence, verdict, allowance
    result, browser token, resource identity, break-return target, SINE or
    MIRL state.  Those belong to the organs that own them, and putting them
    here is how this contract would become a monster.

    ``keywords`` and ``important_keywords`` default to empty so that COSECANT
    can keep constructing its BREAK-shaped context unchanged.  A BREAK context
    legitimately carries no scoring target: the exact break-return identity is
    a separate fact handled by its own contract.
    """

    block_id: str
    generation: int
    display_state: str
    subject: str
    task: str
    protection_active: bool
    planned_break_active: bool
    remaining_seconds: int
    published_monotonic_ns: int
    context_token: str = ""
    keywords: tuple[str, ...] = ()
    important_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "keywords", _keyword_tuple(self.keywords, "keywords")
        )
        object.__setattr__(
            self,
            "important_keywords",
            _keyword_tuple(self.important_keywords, "important_keywords"),
        )
        if self.generation < 0:
            raise ValueError("generation must be non-negative")
        if self.remaining_seconds < 0:
            raise ValueError("remaining_seconds must be non-negative")
        if self.published_monotonic_ns < 0:
            raise ValueError("published_monotonic_ns must be non-negative")
        state = str(self.display_state).strip().upper()
        object.__setattr__(self, "display_state", state)
        expected = study_context_token(self.block_id, self.generation)
        supplied = str(self.context_token or "")
        if supplied and supplied != expected:
            raise ValueError("context_token does not match this block generation")
        object.__setattr__(self, "context_token", expected)
        if self.protection_active != (state == "ACTIVE"):
            raise ValueError("protection_active must match the ACTIVE state")
        if self.planned_break_active != (state == "BREAK"):
            raise ValueError("planned_break_active must match the BREAK state")

    @property
    def active(self) -> bool:
        return bool(
            self.block_id
            and self.display_state == "ACTIVE"
            and self.protection_active
        )

    @property
    def approved_break(self) -> bool:
        return bool(
            self.block_id
            and self.display_state == "BREAK"
            and self.planned_break_active
        )


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    """One monitor observation enriched with certified browser facts."""

    sequence: int
    hwnd: int
    process_id: int
    process_name: str
    raw_title: str
    observed_monotonic_ns: int
    browser_supported: bool
    browser_read_ok: bool
    browser_authoritative: bool
    browser_platform: str
    browser_evidence_kind: str
    browser_marker: str
    browser_redacted_address: str
    browser_resource_token: str
    certified_ott_platform_key: str = ""
    cosine_owned: bool = False


@dataclass(frozen=True, slots=True)
class ResourceIdentity:
    """Stable identity built from process, HWND, certified route and title."""

    process_name: str
    hwnd: int
    browser_family: str
    surface: ResourceSurface
    platform_key: str
    route_marker: str
    opaque_resource_token: str
    normalised_title: str
    browser_evidence_certified: bool
    stable_key: str


@dataclass(frozen=True, slots=True)
class AllowanceRecord:
    """Session-local capability for one resource in one study context."""

    study_context_token: str
    task_fingerprint: str
    resource_key: str
    granted_monotonic_ns: int
    active: bool = True
    measured_classification: ResourceIntent = ResourceIntent.UNCERTAIN
    measured_confidence: float = 0.50
    confirmation_source: str = "USER_CONFIRMED_STUDY"


@dataclass(frozen=True, slots=True)
class StudyConfirmationRecord:
    """Human evidence kept separate from the classifier measurement."""

    study_context_token: str
    resource_key: str
    observation_token: str
    measured_classification: ResourceIntent
    measured_confidence: float
    user_confirmation: StudyUserConfirmation
    effective_operational_state: StudyEffectiveState
    confirmed_monotonic_ns: int
    source: str


@dataclass(frozen=True, slots=True)
class StudySessionMemoryEntry:
    """One exact-resource human confirmation in the active Study scope."""

    study_context_token: str
    task_fingerprint: str
    resource_key: str
    observation_token: str
    measured_classification: ResourceIntent
    measured_confidence: float
    user_confirmation: StudyUserConfirmation
    effective_operational_state: StudyEffectiveState
    confirmed_monotonic_ns: int
    confirmation_source: str
    last_used_order: int


@dataclass(frozen=True, slots=True)
class StudyConfirmationPopupRequest:
    """Exact Case-1 clarification request; this is never a SINE popup."""

    request_id: str
    uncertainty_episode_uid: str
    prompt_number: int
    study_context_token: str
    resource_key: str
    observation_token: str
    source_hwnd: int
    display_title: str
    measured_classification: ResourceIntent
    measured_confidence: float
    requested_monotonic_ns: int


@dataclass(frozen=True, slots=True)
class ResourceIntentFact:
    """Append-only session fact emitted by the Case-1 clarification authority."""

    kind: str
    message: str
    occurred_monotonic_ns: int
    study_context_token: str = ""
    resource_key: str = ""
    observation_token: str = ""
    uncertainty_episode_uid: str = ""
    popup_request_id: str = ""
    prompt_number: int = 0
    measured_classification: ResourceIntent | None = None
    measured_confidence: float | None = None
    user_confirmation: StudyUserConfirmation = StudyUserConfirmation.NONE
    effective_operational_state: StudyEffectiveState = StudyEffectiveState.UNRESOLVED
    reason: str = ""
    popup: StudyConfirmationPopupRequest | None = None


@dataclass(frozen=True, slots=True)
class AllowanceResult:
    outcome: AllowanceOutcome
    record: AllowanceRecord | None = None
    detail: str = ""

    @property
    def granted(self) -> bool:
        return self.outcome is AllowanceOutcome.GRANTED and self.record is not None


@dataclass(frozen=True, slots=True)
class IntentVerdict:
    classification: ResourceIntent
    confidence: float
    positive_reason_codes: tuple[str, ...]
    negative_reason_codes: tuple[str, ...]
    study_context_token: str
    observation_token: str
    resource_identity: ResourceIdentity
    allowance_match: bool
    off_task_dwell_seconds: float
    sine_contribution: SineContribution
    study_idle_allowed: bool
    measured_classification: ResourceIntent = ResourceIntent.UNCERTAIN
    measured_confidence: float = 0.50
    user_confirmation: StudyUserConfirmation = StudyUserConfirmation.NONE
    effective_operational_state: StudyEffectiveState = StudyEffectiveState.UNRESOLVED
    confirmation_source: str = ""
    confirmation_monotonic_ns: int = 0
    classifier_version: str = CLASSIFIER_VERSION


@dataclass(frozen=True, slots=True)
class ResourceIntentSnapshot:
    """One immutable Resource Intent result consumed by other authorities."""

    observation: ResourceObservation
    verdict: IntentVerdict
    fresh: bool
    allowance_active: bool
    protected_red_active: bool
    cosine_active: bool
    deduplicated: bool = False

    @property
    def classification(self) -> ResourceIntent:
        return self.verdict.classification

    @property
    def confidence(self) -> float:
        return self.verdict.confidence

    @property
    def resource_key(self) -> str:
        return self.verdict.resource_identity.stable_key


@dataclass(frozen=True, slots=True)
class ResourceIntentLiveView:
    study_context_token: str
    resource_key: str
    process_name: str
    display_title: str
    resource_surface: ResourceSurface
    classification: ResourceIntent
    confidence: float
    positive_reason_codes: tuple[str, ...]
    negative_reason_codes: tuple[str, ...]
    dwell_elapsed_seconds: float
    dwell_target_seconds: float
    allowance_active: bool
    study_idle_allowed: bool
    protected_red_active: bool
    cosine_active: bool
    sine_contribution: SineContribution
    browser_evidence_certified: bool
    no_nudge_reason_code: str
    measured_classification: ResourceIntent = ResourceIntent.UNCERTAIN
    measured_confidence: float = 0.50
    user_confirmation: StudyUserConfirmation = StudyUserConfirmation.NONE
    effective_operational_state: StudyEffectiveState = StudyEffectiveState.UNRESOLVED
    uncertainty_active: bool = False
    uncertainty_episode_uid: str = ""
    uncertainty_elapsed_seconds: float = 0.0
    uncertainty_target_seconds: float = float(STUDY_UNCERTAINTY_INTERVAL_SECONDS)
    uncertainty_prompt_number: int = 0
    uncertainty_popup_request_id: str = ""


_SPACES: Final = re.compile(r"\s+")
_PUNCTUATION: Final = re.compile(r"[^\w+#&'.-]+", re.UNICODE)
_BADGE_PREFIX: Final = re.compile(r"^\s*(?:\(\d+\)|\[\d+\])\s*")
_YOUTUBE_BADGE_PREFIX: Final = re.compile(
    r"^\s*youtube\s+-\s+(?:\(\d+\)|\[\d+\])\s*",
    re.IGNORECASE,
)
_MEDIA_PREFIX: Final = re.compile(r"^\s*[▶▷►⏸•·|]+\s*")

_BROWSER_SUFFIXES: Final = (
    "google chrome",
    "microsoft edge",
    "brave",
    "opera",
    "vivaldi",
    "youtube",
)
_CONTEXT_STOPWORDS: Final = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "for",
        "from",
        "general",
        "in",
        "into",
        "of",
        "on",
        "or",
        "study",
        "task",
        "the",
        "to",
        "with",
    }
)
_BROWSER_PROCESSES: Final = frozenset(
    {"chrome", "msedge", "brave", "opera", "opera_gx", "vivaldi"}
)
_DOCUMENT_PROCESSES: Final = frozenset(
    {"winword", "powerpnt", "acrord32", "sumatrapdf"}
)
_LEARNING_PROCESSES: Final = frozenset(
    {"anki", "code", "pycharm64", "jupyter", "matlab"}
)
_MESSAGING_PROCESSES: Final = frozenset(
    {"whatsapp", "discord", "telegram", "slack", "teams", "ms-teams"}
)
# Exact proven Windows process-name variants that are the same native app as
# their canonical key.  Alias lookup only -- never a substring/startswith
# match -- so a lookalike process (e.g. "whatsapp.fake") is never admitted.
_NATIVE_PROCESS_ALIASES: Final = {
    "whatsapp.root": "whatsapp",
}
_SOCIAL_PROCESSES: Final = frozenset(
    {"instagram", "facebook", "reddit", "tiktok", "twitter"}
)
_GAMING_PROCESSES: Final = frozenset(
    {"steam", "epicgameslauncher", "riotclientservices", "valorant"}
)
_SOCIAL_BROWSER_PLATFORMS: Final = frozenset(
    {"instagram", "facebook", "snapchat", "tiktok", "twitch", "x"}
)

_SAFE_STUDY_PHRASES: Final = (
    "study with me",
    "past paper",
    "worked example",
    "worked solution",
    "exam revision",
    "practice question",
    "practice problem",
    "problem set",
)
_CONTEXTUAL_STUDY_PHRASES: Final = (
    "tutorial",
    "explained",
    "lecture",
    "lesson",
    "introduction",
    "guide",
    "course",
    "revision",
    "chapter",
    "documentary",
    "demonstration",
    "explainer",
)
_BACKGROUND_AUDIO_PHRASES: Final = (
    "study music",
    "focus music",
    "lofi",
    "lo fi",
    "lo-fi",
    "ambient music",
    "rain sounds",
    "white noise",
    "brown noise",
)
_STRONG_ENTERTAINMENT_PHRASES: Final = (
    "prank",
    "meme",
    "celebrity gossip",
    "official trailer",
    "movie trailer",
    "sports highlights",
    "funny moments",
    "unboxing",
    "gameplay",
    "lets play",
    "let's play",
    "viral video",
    "music video",
    "mrbeast",
    "vlog",
    "try on haul",
    "reacts to",
    "reacting to",
)
_CLICKBAIT_PHRASES: Final = (
    "you wont believe",
    "you won't believe",
    "what happens next",
    "gone wrong",
    "shocking",
    "must watch",
    "will shock you",
)
_GAMING_TERMS: Final = (
    "gameplay",
    "minecraft",
    "fortnite",
    "valorant",
    "roblox",
    "gta",
    "call of duty",
)
_ALLOWANCE_SURFACES: Final = frozenset(
    {
        ResourceSurface.YOUTUBE_WATCH,
        ResourceSurface.DOCUMENT,
        ResourceSurface.LEARNING_APP,
    }
)


def normalise_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.casefold().replace("–", "-").replace("—", "-")
    return _SPACES.sub(" ", text).strip()


def normalise_title(value: object) -> str:
    """Remove browser chrome while preserving real title content."""

    text = normalise_text(value)
    text = _YOUTUBE_BADGE_PREFIX.sub("", text)
    text = _BADGE_PREFIX.sub("", text)
    text = _MEDIA_PREFIX.sub("", text)
    changed = True
    while changed:
        changed = False
        for suffix in _BROWSER_SUFFIXES:
            reduced = re.sub(rf"\s+-\s+{re.escape(suffix)}\s*$", "", text)
            if reduced != text:
                text = reduced.strip()
                changed = True
    return _SPACES.sub(" ", text).strip(" -|")


def searchable_text(value: object) -> str:
    text = normalise_text(value).replace("-", " ")
    return _SPACES.sub(" ", _PUNCTUATION.sub(" ", text)).strip()


def tokenise(value: object) -> tuple[str, ...]:
    return tuple(part for part in searchable_text(value).split(" ") if part)


def context_terms(subject: object, task: object) -> tuple[str, ...]:
    source = f"{subject} {task}"
    seen: set[str] = set()
    terms: list[str] = []
    for token in tokenise(source):
        if len(token) < 2 or token in _CONTEXT_STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return tuple(terms)


def _hash_parts(*parts: object, length: int) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def study_context_token(block_id: object, generation: int) -> str:
    return _hash_parts(block_id, int(generation), length=24)


def task_fingerprint(subject: object, task: object) -> str:
    return _hash_parts(
        normalise_text(subject) or "general",
        normalise_text(task),
        length=32,
    )


def observation_token(observation: ResourceObservation) -> str:
    return _hash_parts(
        observation.sequence,
        observation.hwnd,
        observation.process_id,
        observation.process_name,
        normalise_title(observation.raw_title),
        observation.browser_platform,
        observation.browser_evidence_kind,
        observation.browser_marker,
        observation.browser_resource_token,
        observation.certified_ott_platform_key,
        length=24,
    )


def _process_name(value: object) -> str:
    name = normalise_text(value).removesuffix(".exe")
    return _NATIVE_PROCESS_ALIASES.get(name, name)


def _browser_family(process_name: str) -> str:
    return "chromium" if process_name in _BROWSER_PROCESSES else ""


def _surface_from_browser(observation: ResourceObservation) -> ResourceSurface:
    """Use certified host/route facts; never infer a browser platform by title."""

    platform = observation.browser_platform
    kind = observation.browser_evidence_kind
    if platform == "browser":
        return ResourceSurface.BROWSER_INTERNAL
    if platform == "youtube":
        if kind == UrlEvidenceKind.CONFIRMED_SHORT_FEED.value:
            return ResourceSurface.YOUTUBE_SHORTS
        if kind == UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO.value:
            return ResourceSurface.YOUTUBE_WATCH
        return ResourceSurface.YOUTUBE_OTHER
    if kind == UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE.value:
        return ResourceSurface.MESSAGING
    if kind in {
        UrlEvidenceKind.CONFIRMED_STATIC_ENTRY.value,
        UrlEvidenceKind.CONFIRMED_PRODUCTIVE_PAGE.value,
    }:
        return ResourceSurface.WEB_CONTENT
    if kind in {
        UrlEvidenceKind.CONFIRMED_SHORT_FEED.value,
        UrlEvidenceKind.CONFIRMED_SOCIAL_FEED.value,
    }:
        return ResourceSurface.SOCIAL
    if platform in _SOCIAL_BROWSER_PLATFORMS:
        return ResourceSurface.SOCIAL
    return ResourceSurface.WEB_CONTENT


def build_observation(
    foreground: object,
    browser_evidence: object,
    *,
    cosine_owned: bool,
    certified_ott_platform_key: str = "",
) -> ResourceObservation:
    """Join monitor and browser facts without performing a second observation."""

    browser_status = getattr(browser_evidence, "status", None)
    browser_result = getattr(browser_evidence, "evidence", None)
    return ResourceObservation(
        sequence=int(getattr(foreground, "sequence", 0) or 0),
        hwnd=int(getattr(foreground, "hwnd", 0) or 0),
        process_id=int(getattr(foreground, "process_id", 0) or 0),
        process_name=_process_name(getattr(foreground, "process_name", "")),
        raw_title=str(getattr(foreground, "window_title", "") or ""),
        observed_monotonic_ns=int(
            getattr(foreground, "observed_monotonic_ns", 0) or 0
        ),
        browser_supported=bool(
            getattr(browser_evidence, "supported_browser", False)
        ),
        browser_read_ok=browser_status is BrowserUrlReadStatus.OK,
        browser_authoritative=bool(
            getattr(browser_evidence, "authoritative", False)
        ),
        browser_platform=str(
            getattr(browser_result, "platform_key", "") or ""
        ),
        browser_evidence_kind=str(
            getattr(getattr(browser_result, "kind", None), "value", "") or ""
        ),
        browser_marker=str(getattr(browser_result, "marker", "") or ""),
        browser_redacted_address=str(
            getattr(browser_result, "redacted_address", "") or ""
        ),
        browser_resource_token=str(
            getattr(browser_result, "resource_token", "") or ""
        ),
        certified_ott_platform_key=str(certified_ott_platform_key or ""),
        cosine_owned=bool(cosine_owned),
    )


def build_resource_identity(observation: ResourceObservation) -> ResourceIdentity:
    process = _process_name(observation.process_name)
    title = normalise_title(observation.raw_title)

    if observation.cosine_owned:
        surface = ResourceSurface.COSINE
    elif observation.browser_supported:
        surface = _surface_from_browser(observation)
    elif process in _MESSAGING_PROCESSES:
        surface = ResourceSurface.MESSAGING
    elif process in _SOCIAL_PROCESSES:
        surface = ResourceSurface.SOCIAL
    elif process in _GAMING_PROCESSES:
        surface = ResourceSurface.GAMING
    elif process in _DOCUMENT_PROCESSES:
        surface = ResourceSurface.DOCUMENT
    elif process in _LEARNING_PROCESSES:
        surface = ResourceSurface.LEARNING_APP
    else:
        surface = ResourceSurface.UNKNOWN

    # INSTRUCTION: "shorts" in a title has no authority here.  Only the
    # certified browser route above can select YOUTUBE_SHORTS.
    certified = bool(
        observation.browser_supported
        and observation.browser_read_ok
        and observation.browser_evidence_kind
        not in {
            "",
            UrlEvidenceKind.INVALID_ADDRESS.value,
            UrlEvidenceKind.URL_UNAVAILABLE.value,
        }
    )
    stable_key = _hash_parts(
        process,
        observation.hwnd,
        observation.process_id,
        surface.value,
        observation.browser_platform,
        observation.browser_evidence_kind,
        observation.browser_marker,
        observation.browser_resource_token,
        observation.certified_ott_platform_key,
        title,
        length=32,
    )
    return ResourceIdentity(
        process_name=process,
        hwnd=observation.hwnd,
        browser_family=_browser_family(process),
        surface=surface,
        platform_key=(
            observation.certified_ott_platform_key
            or observation.browser_platform
        ),
        route_marker=observation.browser_marker,
        opaque_resource_token=observation.browser_resource_token,
        normalised_title=title,
        browser_evidence_certified=certified,
        stable_key=stable_key,
    )


def is_allowance_eligible(identity: ResourceIdentity) -> bool:
    if not identity.normalised_title or identity.surface not in _ALLOWANCE_SURFACES:
        return False
    if identity.surface is ResourceSurface.YOUTUBE_WATCH:
        return bool(
            identity.browser_evidence_certified
            and identity.opaque_resource_token
        )
    return True


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {searchable_text(text)} "
    return any(f" {searchable_text(phrase)} " in padded for phrase in phrases)


def _context_support(title: str, context: StudyContext) -> tuple[bool, bool]:
    title_tokens = set(tokenise(title))
    terms = context_terms(context.subject, context.task)
    any_match = bool(title_tokens.intersection(terms))
    task_terms = tuple(
        token
        for token in tokenise(context.task)
        if token not in _CONTEXT_STOPWORDS
    )
    exact_task = len(task_terms) >= 2 and " ".join(task_terms) in title
    return any_match, exact_task


def _entertainment_score(title: str) -> float:
    score = 0.0
    if _has_phrase(title, _STRONG_ENTERTAINMENT_PHRASES):
        score = 0.92
    if _has_phrase(title, _GAMING_TERMS):
        score = max(score, 0.95)
    clickbait = sum(
        1 for phrase in _CLICKBAIT_PHRASES if searchable_text(phrase) in title
    )
    if clickbait >= 2:
        score = max(score, 0.88)
    elif clickbait == 1:
        score = max(score, 0.74)
    return score


def _reason_values(reasons: tuple[IntentReason, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason.value for reason in reasons))


class ResourceIntentAuthority:
    """One lock, one context, one allowance and one current decision."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._profile_type = "GENERAL"
        self._context: StudyContext | None = None
        self._allowance: AllowanceRecord | None = None
        self._confirmation: StudyConfirmationRecord | None = None
        self._study_memory: dict[str, StudySessionMemoryEntry] = {}
        self._study_memory_access_order = 0
        self._active_resource_key = ""
        self._latest: ResourceIntentSnapshot | None = None
        self._protected_red_active = False
        self._sine_episode_active = False
        self._cosine_active = False
        self._cosine_owned = False
        self._certified_ott_platform_key = ""
        self._dwell_key: tuple[str, str] | None = None
        self._dwell_started_ns = -1
        self._dwell_last_ns = -1
        self._stage_one_target_seconds: float | None = None
        self._uncertainty_episode_uid = ""
        self._uncertainty_started_ns = -1
        self._uncertainty_last_ns = -1
        self._uncertainty_next_prompt_ns = -1
        self._uncertainty_prompt_number = 0
        self._uncertainty_popup_request_id = ""
        self._uncertainty_popup_displayed = False
        self._uncertainty_popup_hwnd = 0
        self._uncertainty_request: StudyConfirmationPopupRequest | None = None
        self._uncertainty_request_snapshot: ResourceIntentSnapshot | None = None
        self._facts: list[ResourceIntentFact] = []
        self._started = False
        self._closed = False

    def start_session(self, *, profile_type: str) -> None:
        with self._lock:
            self._reset_all()
            self._profile_type = str(profile_type or "GENERAL").strip().upper()
            self._started = True
            self._closed = False

    def set_stage_one_target_seconds(self, target_seconds: float) -> bool:
        """Freeze Blacklist's already-resolved Stage-1 target for this session."""

        with self._lock:
            self._require_active()
            try:
                target = float(target_seconds)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(target) or target <= 0.0:
                return False
            if self._stage_one_target_seconds is None:
                self._stage_one_target_seconds = target
                return True
            return self._stage_one_target_seconds == target

    def publish_study_context(self, context: StudyContext) -> bool:
        """Accept only forward context facts; invalidate changed authority."""

        with self._lock:
            prior = self._context
            if prior is not None:
                if context.published_monotonic_ns < prior.published_monotonic_ns:
                    return False
                if (
                    context.block_id == prior.block_id
                    and context.generation < prior.generation
                ):
                    return False
            # Any change to a SEMANTIC Study-target fact changes authority, so
            # the allowance, latest verdict and dwell below are all discarded.
            # keywords/important_keywords
            # are listed because they become BSF decision inputs: a target
            # accepted under one keyword set must never keep an exemption
            # earned under a different one.
            #
            # This is a fail-closed invariant, not a description of the normal
            # path.  StudyRuntime.prepare always bumps the generation, which
            # already moves context_token, so a valid publisher can never
            # reach here with the same identity and different keywords.  The
            # comparison defends against a malformed or future publisher that
            # reuses a block/generation, which would otherwise install a new
            # target while keeping facts derived from the old one.
            memory_scope_changed = bool(
                prior is None
                or prior.context_token != context.context_token
                or task_fingerprint(prior.subject, prior.task)
                != task_fingerprint(context.subject, context.task)
                or prior.keywords != context.keywords
                or prior.important_keywords != context.important_keywords
            )
            authority_changed = bool(
                memory_scope_changed
                or (prior is not None and prior.display_state != context.display_state)
            )
            if authority_changed:
                self._retire_uncertainty(
                    max(1, int(context.published_monotonic_ns)),
                    "study_context_changed",
                )
                if memory_scope_changed:
                    self._clear_study_memory()
                self._latest = None
                self._reset_dwell()
            self._context = context
            return True

    def retire_study_context(self, expected_context_token: str = "") -> bool:
        with self._lock:
            if self._context is None:
                return False
            if (
                expected_context_token
                and self._context.context_token != expected_context_token
            ):
                return False
            occurred_ns = max(
                1,
                int(
                    self._latest.observation.observed_monotonic_ns
                    if self._latest is not None
                    else self._context.published_monotonic_ns
                ),
            )
            self._retire_uncertainty(occurred_ns, "study_context_retired")
            self._context = None
            self._clear_study_memory()
            self._latest = None
            self._reset_dwell()
            return True

    def set_protected_red(self, active: bool) -> None:
        with self._lock:
            changed = self._protected_red_active != bool(active)
            self._protected_red_active = bool(active)
            if changed:
                # A CONFIRMED exact allowance is the memory of a resource the
                # user already proved is Study material, and it is exactly the
                # evidence a manual returner needs in order to be recognised
                # during Red.  Deleting it made that return unprovable.  It is
                # only remembered here, never exercised: C8.1's eligibility
                # gate still decides whether the CURRENT identity may use it,
                # and idle permission stays withheld for as long as Red runs.
                #
                self._latest = None
                self._reset_dwell()

    def set_sine_episode_active(self, active: bool) -> None:
        """Scope Phase 3 to Case 1: clarification exists only before SINE."""

        with self._lock:
            changed = self._sine_episode_active != bool(active)
            self._sine_episode_active = bool(active)
            if changed and self._sine_episode_active:
                occurred_ns = self._latest_observed_ns()
                self._retire_uncertainty(occurred_ns, "sine_episode_already_exists")

    def set_cosine_active(self, active: bool) -> None:
        with self._lock:
            changed = self._cosine_active != bool(active)
            occurred_ns = self._latest_observed_ns()
            self._cosine_active = bool(active)
            if changed:
                if self._cosine_active:
                    self._retire_uncertainty(occurred_ns, "cosine_precedence")
                self._latest = None
                self._reset_dwell()

    def set_cosine_resource_owned(self, owned: bool) -> None:
        with self._lock:
            changed = self._cosine_owned != bool(owned)
            self._cosine_owned = bool(owned)
            if changed:
                self._latest = None
                self._reset_dwell()

    def set_certified_ott_platform_key(self, platform_key: str) -> None:
        """Accept Monitor's factual OTT identity without granting ownership."""

        with self._lock:
            self._certified_ott_platform_key = str(platform_key or "")

    def observe(
        self,
        *,
        foreground: object,
        browser_evidence: object,
        certified_ott_platform_key: str = "",
    ) -> ResourceIntentSnapshot:
        """Evaluate one monitor cycle without another Windows/browser read."""

        with self._lock:
            self._require_active()
            observation = build_observation(
                foreground,
                browser_evidence,
                cosine_owned=self._cosine_owned,
                certified_ott_platform_key=(
                    certified_ott_platform_key
                    or self._certified_ott_platform_key
                ),
            )
            if (
                self._uncertainty_popup_hwnd > 0
                and observation.hwnd == self._uncertainty_popup_hwnd
                and self._uncertainty_request_snapshot is not None
            ):
                return replace(
                    self._uncertainty_request_snapshot,
                    deduplicated=True,
                )
            identity = build_resource_identity(observation)
            self._active_resource_key = identity.stable_key

            if self._is_regressed(observation):
                assert self._latest is not None
                return replace(self._latest, deduplicated=True)

            verdict = self._classify(observation, identity)
            verdict = self._apply_confirmation(verdict)
            verdict = self._advance_study_uncertainty(observation, verdict)
            verdict = self._apply_off_task_dwell(observation, verdict)
            snapshot = ResourceIntentSnapshot(
                observation=observation,
                verdict=verdict,
                fresh=observation.observed_monotonic_ns > 0,
                allowance_active=verdict.allowance_match,
                protected_red_active=self._protected_red_active,
                cosine_active=self._cosine_active,
                deduplicated=False,
            )
            if self._latest is not None and self._same_decision(
                self._latest.verdict,
                verdict,
            ):
                snapshot = replace(snapshot, deduplicated=True)
            self._latest = snapshot
            request = self._uncertainty_request
            if (
                request is not None
                and request.observation_token == snapshot.verdict.observation_token
                and request.resource_key == snapshot.resource_key
            ):
                self._uncertainty_request_snapshot = snapshot
            return snapshot

    def live_view(self) -> ResourceIntentLiveView | None:
        with self._lock:
            if self._latest is None:
                return None
            verdict = self._latest.verdict
            identity = verdict.resource_identity
            negative = verdict.negative_reason_codes
            return ResourceIntentLiveView(
                study_context_token=verdict.study_context_token,
                resource_key=identity.stable_key,
                process_name=identity.process_name,
                display_title=identity.normalised_title[:240],
                resource_surface=identity.surface,
                classification=verdict.classification,
                confidence=verdict.confidence,
                positive_reason_codes=verdict.positive_reason_codes,
                negative_reason_codes=negative,
                dwell_elapsed_seconds=verdict.off_task_dwell_seconds,
                dwell_target_seconds=float(self._stage_one_target_seconds or 0.0),
                allowance_active=verdict.allowance_match,
                study_idle_allowed=verdict.study_idle_allowed,
                protected_red_active=self._protected_red_active,
                cosine_active=self._cosine_active,
                sine_contribution=verdict.sine_contribution,
                browser_evidence_certified=identity.browser_evidence_certified,
                no_nudge_reason_code=(negative[-1] if negative else ""),
                measured_classification=verdict.measured_classification,
                measured_confidence=verdict.measured_confidence,
                user_confirmation=verdict.user_confirmation,
                effective_operational_state=verdict.effective_operational_state,
                uncertainty_active=bool(self._uncertainty_episode_uid),
                uncertainty_episode_uid=self._uncertainty_episode_uid,
                uncertainty_elapsed_seconds=self._uncertainty_elapsed_seconds(),
                uncertainty_target_seconds=float(
                    STUDY_UNCERTAINTY_INTERVAL_SECONDS
                ),
                uncertainty_prompt_number=self._uncertainty_prompt_number,
                uncertainty_popup_request_id=self._uncertainty_popup_request_id,
            )

    def record_study_material_allowance(
        self,
        *,
        study_context_token: str,
        resource_key: str,
        granted_monotonic_ns: int,
    ) -> AllowanceResult:
        """Consume one Monitor-accepted human declaration for one exact resource."""

        with self._lock:
            context = self._context
            if context is None or not context.active:
                return self._denied(
                    AllowanceOutcome.DENIED_NO_ACTIVE_BLOCK,
                    "An active study block is required.",
                )
            if str(study_context_token or "") != context.context_token:
                return self._denied(
                    AllowanceOutcome.DENIED_CONTEXT_CHANGED,
                    "The Study block changed before the declaration arrived.",
                )
            exact_key = str(resource_key or "")
            if not exact_key:
                return self._denied(
                    AllowanceOutcome.DENIED_UNSAFE_SURFACE,
                    "An exact certified resource identity is required.",
                )

            record = AllowanceRecord(
                study_context_token=context.context_token,
                task_fingerprint=task_fingerprint(context.subject, context.task),
                resource_key=exact_key,
                granted_monotonic_ns=int(granted_monotonic_ns),
                active=True,
                measured_classification=(
                    self._latest.verdict.measured_classification
                    if self._latest is not None
                    else ResourceIntent.UNCERTAIN
                ),
                measured_confidence=(
                    self._latest.verdict.measured_confidence
                    if self._latest is not None
                    else 0.50
                ),
            )
            self._allowance = record
            confirmation = StudyConfirmationRecord(
                study_context_token=context.context_token,
                resource_key=exact_key,
                observation_token=(
                    self._latest.verdict.observation_token
                    if self._latest is not None
                    else ""
                ),
                measured_classification=record.measured_classification,
                measured_confidence=record.measured_confidence,
                user_confirmation=StudyUserConfirmation.STUDY,
                effective_operational_state=StudyEffectiveState.STUDY_ALIGNED,
                confirmed_monotonic_ns=int(granted_monotonic_ns),
                source=record.confirmation_source,
            )
            self._confirmation = confirmation
            self._remember_confirmation(context, confirmation)
            self._reset_dwell()
            return AllowanceResult(AllowanceOutcome.GRANTED, record=record)

    def drain_facts(self) -> tuple[ResourceIntentFact, ...]:
        with self._lock:
            facts = tuple(self._facts)
            self._facts.clear()
            return facts

    def record_study_confirmation_popup_shown(
        self,
        *,
        request_id: str,
        shown_monotonic_ns: int,
        popup_hwnd: int,
    ) -> bool:
        with self._lock:
            request = self._current_confirmation_request(request_id)
            if request is None or self._uncertainty_popup_displayed:
                return False
            if int(shown_monotonic_ns) < request.requested_monotonic_ns:
                return False
            if int(popup_hwnd) <= 0:
                return False
            self._uncertainty_popup_displayed = True
            self._uncertainty_popup_hwnd = int(popup_hwnd)
            self._emit_case1_fact(
                "STUDY_CONFIRMATION_POPUP_DISPLAYED",
                "Study uncertainty clarification was factually displayed.",
                int(shown_monotonic_ns),
                request=request,
            )
            return True

    def record_study_confirmation_popup_closed(
        self,
        *,
        request_id: str,
        occurred_monotonic_ns: int,
        reason: str,
    ) -> bool:
        with self._lock:
            request = self._current_confirmation_request(request_id)
            if request is None:
                return False
            if int(occurred_monotonic_ns) < request.requested_monotonic_ns:
                return False
            self._uncertainty_popup_displayed = False
            self._uncertainty_popup_hwnd = 0
            self._emit_case1_fact(
                "STUDY_CONFIRMATION_POPUP_CLOSED",
                "Study uncertainty clarification closed without changing SINE.",
                int(occurred_monotonic_ns),
                request=request,
                reason=str(reason or "presentation_closed"),
            )
            return True

    def record_study_confirmation_response(
        self,
        *,
        request_id: str,
        response: str,
        occurred_monotonic_ns: int,
        expected_study_context_token: str,
        expected_resource_key: str,
    ) -> bool:
        """Accept one exact Case-1 action without rewriting measured evidence."""

        with self._lock:
            request = self._current_confirmation_request(request_id)
            latest = self._latest
            request_snapshot = self._uncertainty_request_snapshot
            context = self._context
            if (
                request is None
                or latest is None
                or request_snapshot is None
                or context is None
                or not context.active
            ):
                return False
            occurred_ns = int(occurred_monotonic_ns)
            if occurred_ns < request.requested_monotonic_ns:
                return False
            latest_matches_request = bool(
                latest.resource_key == request.resource_key
                and latest.verdict.classification is ResourceIntent.UNCERTAIN
                and latest.verdict.measured_classification is ResourceIntent.UNCERTAIN
                and latest.verdict.measured_confidence == 0.50
            )
            latest_is_exact_popup = bool(
                self._uncertainty_popup_hwnd > 0
                and latest.observation.hwnd == self._uncertainty_popup_hwnd
            )
            if (
                str(expected_study_context_token or "") != request.study_context_token
                or str(expected_resource_key or "") != request.resource_key
                or context.context_token != request.study_context_token
                or request_snapshot.resource_key != request.resource_key
                or request_snapshot.verdict.observation_token != request.observation_token
                or request_snapshot.verdict.measured_classification
                is not ResourceIntent.UNCERTAIN
                or request_snapshot.verdict.measured_confidence != 0.50
                or not (latest_matches_request or latest_is_exact_popup)
            ):
                return False
            try:
                action = StudyConfirmationResponse(str(response))
            except ValueError:
                return False

            measured = request_snapshot.verdict
            if action is StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL:
                record = AllowanceRecord(
                    study_context_token=context.context_token,
                    task_fingerprint=task_fingerprint(context.subject, context.task),
                    resource_key=request.resource_key,
                    granted_monotonic_ns=occurred_ns,
                    active=True,
                    measured_classification=measured.measured_classification,
                    measured_confidence=measured.measured_confidence,
                    confirmation_source="USER_CONFIRMED_STUDY",
                )
                self._allowance = record
                self._confirmation = StudyConfirmationRecord(
                    study_context_token=context.context_token,
                    resource_key=request.resource_key,
                    observation_token=request.observation_token,
                    measured_classification=measured.measured_classification,
                    measured_confidence=measured.measured_confidence,
                    user_confirmation=StudyUserConfirmation.STUDY,
                    effective_operational_state=StudyEffectiveState.STUDY_ALIGNED,
                    confirmed_monotonic_ns=occurred_ns,
                    source="USER_CONFIRMED_STUDY",
                )
                event_kind = "USER_CONFIRMED_STUDY"
                message = "User confirmed that the exact uncertain resource is Study material."
            else:
                self._confirmation = StudyConfirmationRecord(
                    study_context_token=context.context_token,
                    resource_key=request.resource_key,
                    observation_token=request.observation_token,
                    measured_classification=measured.measured_classification,
                    measured_confidence=measured.measured_confidence,
                    user_confirmation=StudyUserConfirmation.OFF_TASK,
                    effective_operational_state=StudyEffectiveState.CONFIRMED_DISTRACTION,
                    confirmed_monotonic_ns=occurred_ns,
                    source="USER_CONFIRMED_OFF_TASK",
                )
                self._begin_confirmed_dwell(context.context_token, occurred_ns)
                event_kind = "USER_CONFIRMED_OFF_TASK"
                message = "User confirmed that the exact uncertain resource is off-task."

            assert self._confirmation is not None
            self._active_resource_key = request.resource_key
            self._remember_confirmation(context, self._confirmation)

            self._emit_case1_fact(
                event_kind,
                message,
                occurred_ns,
                request=request,
                confirmation=self._confirmation,
            )
            self._emit_case1_fact(
                "STUDY_CONFIRMATION_POPUP_CLOSE_REQUESTED",
                "Resource Intent resolved the clarification and requested popup close.",
                occurred_ns,
                request=request,
                confirmation=self._confirmation,
                reason="accepted_user_confirmation",
            )
            self._clear_uncertainty_state()
            applied = self._apply_confirmation(measured)
            if action is StudyConfirmationResponse.IM_COMING_BACK:
                applied = replace(
                    applied,
                    off_task_dwell_seconds=0.0,
                    sine_contribution=SineContribution.PENDING,
                    study_idle_allowed=False,
                )
            self._latest = replace(
                request_snapshot,
                verdict=applied,
                deduplicated=False,
            )
            return True

    def shutdown(self) -> None:
        with self._lock:
            self._reset_all()
            self._started = False
            self._closed = True

    def _classify(
        self,
        observation: ResourceObservation,
        identity: ResourceIdentity,
    ) -> IntentVerdict:
        context = self._context
        context_token = context.context_token if context else ""
        token = observation_token(observation)
        certified_ott = bool(observation.certified_ott_platform_key)
        messaging = identity.surface is ResourceSurface.MESSAGING
        study_owned = bool(
            context is not None
            and (context.active or context.approved_break)
        )

        # Protected Red is an EFFERENT intervention state.  It must not cut the
        # AFFERENT nerve that reports what the user is factually looking at:
        # MIRL can only verify a return it is allowed to observe, and Monitor
        # can only release Red from MIRL's verified package.  Returning
        # UNCERTAIN here made that recovery unobservable and deadlocked Red.
        #
        # Red keeps every behavioural consequence it had.  ``_with_sine_policy``
        # still forces sine_contribution NONE and study_idle_allowed False while
        # it is active, and monitor refuses to start a managed break.
        # ``snapshot.protected_red_active`` remains the separate published fact.
        if context is None or not context.block_id:
            if messaging:
                return self._verdict(
                    ResourceIntent.UNCERTAIN,
                    1.0,
                    (),
                    (IntentReason.MESSAGING_SEPARATE_POLICY,),
                    context_token,
                    token,
                    identity,
                )
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                1.0,
                (),
                (IntentReason.NO_ACTIVE_STUDY_BLOCK,),
                context_token,
                token,
                identity,
            )
        # OTT and Messaging are identity facts, not organ permissions.  While
        # ACTIVE Study or its COSECANT break owns the moment, these two factual
        # collisions must reach Study's existing distraction pathway before
        # APPROVED_BREAK or COSINE/Messaging lifecycle precedence can hide them.
        if study_owned and (certified_ott or messaging):
            reason = (
                IntentReason.ENTERTAINMENT
                if certified_ott
                else IntentReason.STRONG_DISTRACTION
            )
            return self._verdict(
                ResourceIntent.DISTRACTION,
                1.0,
                (),
                (reason,),
                context_token,
                token,
                identity,
            )
        if context.approved_break:
            return self._verdict(
                ResourceIntent.APPROVED_BREAK,
                1.0,
                (IntentReason.APPROVED_BREAK,),
                (),
                context_token,
                token,
                identity,
            )
        if not context.active:
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                1.0,
                (),
                (IntentReason.STUDY_PAUSED,),
                context_token,
                token,
                identity,
            )
        if self._cosine_active or observation.cosine_owned:
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                1.0,
                (),
                (IntentReason.COSINE,),
                context_token,
                token,
                identity,
            )
        if observation.observed_monotonic_ns <= 0:
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                1.0,
                (),
                (IntentReason.STALE_OBSERVATION,),
                context_token,
                token,
                identity,
            )

        title = searchable_text(identity.normalised_title)
        context_matched, exact_task = _context_support(title, context)
        entertainment = _entertainment_score(title)

        if identity.surface is ResourceSurface.MESSAGING:
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                1.0,
                (),
                (IntentReason.MESSAGING_SEPARATE_POLICY,),
                context_token,
                token,
                identity,
            )
        if identity.surface is ResourceSurface.SOCIAL:
            return self._verdict(
                ResourceIntent.DISTRACTION,
                0.95,
                (),
                (IntentReason.STRONG_DISTRACTION,),
                context_token,
                token,
                identity,
            )
        if identity.surface is ResourceSurface.GAMING:
            return self._verdict(
                ResourceIntent.DISTRACTION,
                0.95,
                (),
                (IntentReason.GAMING,),
                context_token,
                token,
                identity,
            )
        if identity.surface is ResourceSurface.YOUTUBE_SHORTS:
            educational = bool(
                context_matched
                or _has_phrase(title, _CONTEXTUAL_STUDY_PHRASES)
            )
            if educational:
                return self._verdict(
                    ResourceIntent.UNCERTAIN,
                    0.50,
                    (),
                    (IntentReason.EDUCATIONAL_SHORTS_UNCERTAIN,),
                    context_token,
                    token,
                    identity,
                )
            return self._verdict(
                ResourceIntent.DISTRACTION,
                0.90,
                (),
                (IntentReason.STRONG_DISTRACTION,),
                context_token,
                token,
                identity,
            )
        if (
            identity.surface is ResourceSurface.YOUTUBE_WATCH
            and entertainment >= DISTRACTION_THRESHOLD
        ):
            return self._verdict(
                ResourceIntent.DISTRACTION,
                entertainment,
                (),
                (IntentReason.ENTERTAINMENT,),
                context_token,
                token,
                identity,
            )
        if (
            identity.surface
            in {ResourceSurface.YOUTUBE_WATCH, ResourceSurface.LEARNING_APP}
            and _has_phrase(title, _BACKGROUND_AUDIO_PHRASES)
        ):
            return self._verdict(
                ResourceIntent.BACKGROUND_AUDIO,
                0.60,
                (IntentReason.BACKGROUND_AUDIO,),
                (),
                context_token,
                token,
                identity,
            )

        positive: list[IntentReason] = []
        if exact_task or _has_phrase(title, _SAFE_STUDY_PHRASES):
            positive.append(IntentReason.TITLE_SUPPORT_ONLY)
        elif context_matched and _has_phrase(title, _CONTEXTUAL_STUDY_PHRASES):
            positive.append(IntentReason.TITLE_SUPPORT_ONLY)

        negative: list[IntentReason] = []
        if context_matched:
            negative.append(IntentReason.SUBJECT_WORD_ONLY)
        if observation.browser_supported and not observation.browser_read_ok:
            negative.append(IntentReason.BROWSER_EVIDENCE_UNAVAILABLE)
        unsupported_surface = identity.surface in {
            ResourceSurface.UNKNOWN,
            ResourceSurface.YOUTUBE_OTHER,
            ResourceSurface.BROWSER_INTERNAL,
        }
        if unsupported_surface:
            negative.append(IntentReason.UNSUPPORTED_SURFACE)

        # Every higher-authority rule above has already declined this
        # observation, so certified route facts -- messaging, social, gaming,
        # Shorts, strong entertainment, background audio -- have had their say
        # and cannot be overturned by anything below.  Only now does the
        # declared Study target get weighed against the observed title.
        evidence = study_evidence(
            subject=context.subject,
            task=context.task,
            keywords=context.keywords,
            important_keywords=context.important_keywords,
            title=identity.normalised_title,
            identity_certified=identity.browser_evidence_certified,
        )

        if evidence.raw_possible_points == 0:
            # No scientific input is not proof of distraction.  The current UI
            # cannot supply Study keywords yet, so an old Study block reaches
            # here with nothing to score and must keep the pre-C4 behaviour:
            # title/context support only, UNCERTAIN, and normal off-task dwell.
            #
            # Deliberately raw_ and not effective_possible_points: raw == 0
            # means genuinely nothing was declared, whereas raw > 0 with
            # effective == 0 means the calculator STRIPPED every declared
            # keyword as suspicious.  That is a cheating signal and must never
            # inherit this innocent fallback.
            negative.append(IntentReason.TITLE_SUPPORT_ONLY)
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                0.50,
                tuple(positive),
                tuple(negative),
                context_token,
                token,
                identity,
            )

        confidence = evidence.confidence_percent
        if (
            confidence >= STUDY_ALIGNED_MIN_CONFIDENCE
            and identity.browser_evidence_certified
            and not unsupported_surface
        ):
            # The certified-identity conjunct is deliberately redundant with
            # the calculator's own 74 cap for uncertified evidence.  The cap is
            # a number that a future calculator could change; this is the
            # authority-level rule that text never certifies identity, and it
            # must hold independently.
            return self._verdict(
                ResourceIntent.STUDY_ALIGNED,
                confidence / 100.0,
                (IntentReason.STUDY_EVIDENCE_ALIGNED, *positive),
                tuple(negative),
                context_token,
                token,
                identity,
            )

        if confidence >= STUDY_UNCERTAIN_MIN_CONFIDENCE:
            negative.append(IntentReason.STUDY_EVIDENCE_UNCERTAIN)
            return self._verdict(
                ResourceIntent.UNCERTAIN,
                0.50,
                tuple(positive),
                tuple(negative),
                context_token,
                token,
                identity,
            )

        # An off-task FACT, not an intervention.  The off-task dwell below and
        # then Trigger decide whether and when anything is shown.  Confidence
        # here is confidence in the off-task reading, which is why it rises as
        # the Study evidence falls.
        negative.append(IntentReason.STUDY_EVIDENCE_OFF_TASK)
        return self._verdict(
            ResourceIntent.DISTRACTION,
            1.0 - (confidence / 100.0),
            tuple(positive),
            tuple(negative),
            context_token,
            token,
            identity,
        )

    def _apply_confirmation(self, verdict: IntentVerdict) -> IntentVerdict:
        """Apply exact human evidence while preserving the measured verdict."""

        context = self._context
        identity = verdict.resource_identity
        if context is None or not context.active:
            return verdict
        entry = self._matching_memory_entry(context, identity)
        if entry is None:
            return verdict
        entry = self._touch_memory_entry(entry)

        if entry.user_confirmation is StudyUserConfirmation.STUDY:
            positive = tuple(
                dict.fromkeys(
                    (*verdict.positive_reason_codes, IntentReason.EXACT_ALLOWANCE.value)
                )
            )
            confirmed = replace(
                verdict,
                classification=ResourceIntent.STUDY_ALIGNED,
                confidence=1.0,
                positive_reason_codes=positive,
                allowance_match=True,
                measured_classification=entry.measured_classification,
                measured_confidence=entry.measured_confidence,
                user_confirmation=StudyUserConfirmation.STUDY,
                effective_operational_state=StudyEffectiveState.STUDY_ALIGNED,
                confirmation_source=entry.confirmation_source,
                confirmation_monotonic_ns=entry.confirmed_monotonic_ns,
            )
            return self._with_sine_policy(confirmed, 0.0)

        if entry.user_confirmation is StudyUserConfirmation.OFF_TASK:
            confirmed = replace(
                verdict,
                classification=ResourceIntent.DISTRACTION,
                confidence=1.0,
                allowance_match=False,
                measured_classification=entry.measured_classification,
                measured_confidence=entry.measured_confidence,
                user_confirmation=StudyUserConfirmation.OFF_TASK,
                effective_operational_state=StudyEffectiveState.CONFIRMED_DISTRACTION,
                confirmation_source=entry.confirmation_source,
                confirmation_monotonic_ns=entry.confirmed_monotonic_ns,
            )
            return self._with_sine_policy(confirmed, 0.0)
        return verdict

    def _advance_study_uncertainty(
        self,
        observation: ResourceObservation,
        verdict: IntentVerdict,
    ) -> IntentVerdict:
        """Advance Case 1 without creating SINE, MIRL or Ebbinghaus evidence."""

        context = self._context
        now_ns = int(observation.observed_monotonic_ns)
        case1_uncertain = bool(
            context is not None
            and context.active
            and not self._protected_red_active
            and not self._sine_episode_active
            and not self._cosine_active
            and verdict.classification is ResourceIntent.UNCERTAIN
            and verdict.measured_classification is ResourceIntent.UNCERTAIN
            and verdict.measured_confidence == 0.50
            and verdict.user_confirmation is StudyUserConfirmation.NONE
        )
        if not case1_uncertain:
            if self._uncertainty_episode_uid:
                reason = (
                    "automatically_study_aligned"
                    if verdict.classification is ResourceIntent.STUDY_ALIGNED
                    else "automatically_confirmed_distraction"
                    if verdict.classification is ResourceIntent.DISTRACTION
                    else "uncertainty_precedence_changed"
                )
                self._retire_uncertainty(now_ns, reason, verdict=verdict)
            return verdict

        assert context is not None
        if not self._uncertainty_episode_uid:
            self._uncertainty_episode_uid = f"study-uncertainty-{secrets.token_hex(16)}"
            self._uncertainty_started_ns = now_ns
            self._uncertainty_next_prompt_ns = now_ns + STUDY_UNCERTAINTY_INTERVAL_NS
            self._uncertainty_prompt_number = 0
            self._emit_case1_fact(
                "STUDY_UNCERTAINTY_STARTED",
                "Resource Intent began a 50% Study clarification episode.",
                now_ns,
                verdict=verdict,
            )
        self._uncertainty_last_ns = now_ns

        if now_ns >= self._uncertainty_next_prompt_ns:
            self._uncertainty_prompt_number += 1
            request = StudyConfirmationPopupRequest(
                request_id=f"study-confirm-{secrets.token_hex(16)}",
                uncertainty_episode_uid=self._uncertainty_episode_uid,
                prompt_number=self._uncertainty_prompt_number,
                study_context_token=context.context_token,
                resource_key=verdict.resource_identity.stable_key,
                observation_token=verdict.observation_token,
                source_hwnd=observation.hwnd,
                display_title=verdict.resource_identity.normalised_title[:240],
                measured_classification=verdict.measured_classification,
                measured_confidence=verdict.measured_confidence,
                requested_monotonic_ns=now_ns,
            )
            self._uncertainty_request = request
            self._uncertainty_popup_request_id = request.request_id
            self._uncertainty_popup_displayed = False
            self._uncertainty_popup_hwnd = 0
            self._uncertainty_request_snapshot = None
            self._uncertainty_next_prompt_ns = now_ns + STUDY_UNCERTAINTY_INTERVAL_NS
            self._emit_case1_fact(
                "STUDY_CONFIRMATION_POPUP_REQUESTED",
                "Five minutes of unresolved Study uncertainty requested clarification.",
                now_ns,
                request=request,
                verdict=verdict,
            )

        return replace(
            verdict,
            off_task_dwell_seconds=0.0,
            sine_contribution=SineContribution.NONE,
            study_idle_allowed=False,
            effective_operational_state=StudyEffectiveState.UNRESOLVED,
        )

    def _current_confirmation_request(
        self,
        request_id: str,
    ) -> StudyConfirmationPopupRequest | None:
        request = self._uncertainty_request
        if (
            request is None
            or not self._uncertainty_episode_uid
            or request.request_id != str(request_id or "")
            or request.uncertainty_episode_uid != self._uncertainty_episode_uid
        ):
            return None
        return request

    def _retire_uncertainty(
        self,
        occurred_ns: int,
        reason: str,
        *,
        verdict: IntentVerdict | None = None,
    ) -> None:
        if not self._uncertainty_episode_uid:
            return
        request = self._uncertainty_request
        if request is not None:
            self._emit_case1_fact(
                "STUDY_CONFIRMATION_POPUP_CLOSE_REQUESTED",
                "Resource Intent retired the clarification popup.",
                int(occurred_ns),
                request=request,
                verdict=verdict,
                reason=reason,
            )
        self._emit_case1_fact(
            "STUDY_UNCERTAINTY_RESOLVED",
            "The Study uncertainty episode ended without backdating SINE time.",
            int(occurred_ns),
            request=request,
            verdict=verdict,
            reason=reason,
        )
        self._clear_uncertainty_state()

    def _clear_uncertainty_state(self) -> None:
        self._uncertainty_episode_uid = ""
        self._uncertainty_started_ns = -1
        self._uncertainty_last_ns = -1
        self._uncertainty_next_prompt_ns = -1
        self._uncertainty_prompt_number = 0
        self._uncertainty_popup_request_id = ""
        self._uncertainty_popup_displayed = False
        self._uncertainty_popup_hwnd = 0
        self._uncertainty_request = None
        self._uncertainty_request_snapshot = None

    def _emit_case1_fact(
        self,
        kind: str,
        message: str,
        occurred_ns: int,
        *,
        request: StudyConfirmationPopupRequest | None = None,
        verdict: IntentVerdict | None = None,
        confirmation: StudyConfirmationRecord | None = None,
        reason: str = "",
    ) -> None:
        current_request = request or self._uncertainty_request
        current_verdict = verdict or (
            self._latest.verdict if self._latest is not None else None
        )
        measured_classification = (
            confirmation.measured_classification
            if confirmation is not None
            else current_request.measured_classification
            if current_request is not None
            else current_verdict.measured_classification
            if current_verdict is not None
            else None
        )
        measured_confidence = (
            confirmation.measured_confidence
            if confirmation is not None
            else current_request.measured_confidence
            if current_request is not None
            else current_verdict.measured_confidence
            if current_verdict is not None
            else None
        )
        self._facts.append(
            ResourceIntentFact(
                kind=str(kind),
                message=str(message),
                occurred_monotonic_ns=max(1, int(occurred_ns)),
                study_context_token=(
                    current_request.study_context_token
                    if current_request is not None
                    else current_verdict.study_context_token
                    if current_verdict is not None
                    else self._context.context_token
                    if self._context is not None
                    else ""
                ),
                resource_key=(
                    current_request.resource_key
                    if current_request is not None
                    else current_verdict.resource_identity.stable_key
                    if current_verdict is not None
                    else ""
                ),
                observation_token=(
                    current_request.observation_token
                    if current_request is not None
                    else current_verdict.observation_token
                    if current_verdict is not None
                    else ""
                ),
                uncertainty_episode_uid=(
                    current_request.uncertainty_episode_uid
                    if current_request is not None
                    else self._uncertainty_episode_uid
                ),
                popup_request_id=(
                    current_request.request_id if current_request is not None else ""
                ),
                prompt_number=(
                    current_request.prompt_number if current_request is not None else 0
                ),
                measured_classification=measured_classification,
                measured_confidence=measured_confidence,
                user_confirmation=(
                    confirmation.user_confirmation
                    if confirmation is not None
                    else StudyUserConfirmation.NONE
                ),
                effective_operational_state=(
                    confirmation.effective_operational_state
                    if confirmation is not None
                    else current_verdict.effective_operational_state
                    if current_verdict is not None
                    else StudyEffectiveState.UNRESOLVED
                ),
                reason=str(reason or ""),
                popup=current_request if kind == "STUDY_CONFIRMATION_POPUP_REQUESTED" else None,
            )
        )

    def _uncertainty_elapsed_seconds(self) -> float:
        if self._uncertainty_started_ns < 0 or self._uncertainty_last_ns < 0:
            return 0.0
        return max(
            0.0,
            (self._uncertainty_last_ns - self._uncertainty_started_ns)
            / 1_000_000_000.0,
        )

    def _latest_observed_ns(self) -> int:
        if self._latest is not None:
            return max(1, int(self._latest.observation.observed_monotonic_ns))
        if self._context is not None:
            return max(1, int(self._context.published_monotonic_ns))
        return 1

    def _begin_confirmed_dwell(self, context_token: str, occurred_ns: int) -> None:
        self._dwell_key = (str(context_token), "confirmed_distraction")
        self._dwell_started_ns = int(occurred_ns)
        self._dwell_last_ns = int(occurred_ns)

    def _apply_off_task_dwell(
        self,
        observation: ResourceObservation,
        verdict: IntentVerdict,
    ) -> IntentVerdict:
        context = self._context
        candidate = bool(
            context is not None
            and (context.active or context.approved_break)
            and (
                verdict.resource_identity.surface
                in {
                    ResourceSurface.YOUTUBE_WATCH,
                    ResourceSurface.MESSAGING,
                }
                or bool(observation.certified_ott_platform_key)
            )
            # Phase 3: 50% uncertainty owns an independent clarification clock.
            # Only factual confirmed distraction may consume SINE dwell.
            and verdict.classification is ResourceIntent.DISTRACTION
            and not verdict.allowance_match
            and not self._protected_red_active
            and not self._cosine_active
            and not observation.cosine_owned
        )
        if not candidate:
            self._reset_dwell()
            return self._with_sine_policy(verdict, 0.0)

        # The confirmed behavioural episode belongs to the active Study
        # context, not one URL.  Switching among distractive videos therefore
        # preserves the same 5-minute SINE watch.
        key = (context.context_token, "confirmed_distraction")
        observed_ns = observation.observed_monotonic_ns
        continuous = bool(
            self._dwell_key == key
            and self._dwell_last_ns >= 0
            and 0 <= observed_ns - self._dwell_last_ns <= OBSERVATION_FRESHNESS_NS
        )
        if not continuous:
            self._dwell_key = key
            self._dwell_started_ns = observed_ns
        self._dwell_last_ns = observed_ns
        dwell_ns = max(0, observed_ns - self._dwell_started_ns)
        dwell_seconds = dwell_ns / 1_000_000_000.0
        target_seconds = self._stage_one_target_seconds
        if target_seconds is None:
            # Classification remains truthful for read-only consumers, but no
            # Study SINE clock may exist until Monitor supplies Blacklist's
            # already-resolved session target. Resetting also prevents a later
            # binding from backdating this unsupported interval.
            self._reset_dwell()
            return replace(
                verdict,
                off_task_dwell_seconds=0.0,
                sine_contribution=SineContribution.NONE,
                study_idle_allowed=False,
            )
        if dwell_seconds < target_seconds:
            negative = verdict.negative_reason_codes + (
                IntentReason.OFF_TASK_WATCH_PENDING.value,
            )
            pending = replace(
                verdict,
                negative_reason_codes=tuple(dict.fromkeys(negative)),
                off_task_dwell_seconds=dwell_seconds,
                sine_contribution=SineContribution.PENDING,
                study_idle_allowed=False,
            )
            return pending

        negative = verdict.negative_reason_codes + (
            IntentReason.OFF_TASK_WATCH_READY.value,
        )
        ready = replace(
            verdict,
            classification=ResourceIntent.DISTRACTION,
            confidence=max(DISTRACTION_THRESHOLD, verdict.confidence),
            negative_reason_codes=tuple(dict.fromkeys(negative)),
            off_task_dwell_seconds=dwell_seconds,
            sine_contribution=SineContribution.READY,
            study_idle_allowed=False,
        )
        return ready

    def _with_sine_policy(
        self,
        verdict: IntentVerdict,
        dwell_seconds: float,
    ) -> IntentVerdict:
        context_active = bool(self._context is not None and self._context.active)
        idle_allowed = bool(
            context_active
            and verdict.classification is ResourceIntent.STUDY_ALIGNED
            and verdict.allowance_match
            and not self._protected_red_active
            and not self._cosine_active
        )
        if not context_active or self._protected_red_active or self._cosine_active:
            contribution = SineContribution.NONE
        elif verdict.classification in {
            ResourceIntent.STUDY_ALIGNED,
            ResourceIntent.APPROVED_BREAK,
            ResourceIntent.BACKGROUND_AUDIO,
        }:
            contribution = SineContribution.WITHHELD
        elif verdict.classification is ResourceIntent.DISTRACTION:
            contribution = SineContribution.READY
        else:
            contribution = SineContribution.NONE
        return replace(
            verdict,
            off_task_dwell_seconds=float(dwell_seconds),
            sine_contribution=contribution,
            study_idle_allowed=idle_allowed,
        )

    def _verdict(
        self,
        classification: ResourceIntent,
        confidence: float,
        positive: tuple[IntentReason, ...],
        negative: tuple[IntentReason, ...],
        context_token: str,
        token: str,
        identity: ResourceIdentity,
        *,
        allowance_match: bool = False,
    ) -> IntentVerdict:
        bounded_confidence = max(0.0, min(1.0, float(confidence)))
        effective_state = (
            StudyEffectiveState.STUDY_ALIGNED
            if classification is ResourceIntent.STUDY_ALIGNED
            else StudyEffectiveState.CONFIRMED_DISTRACTION
            if classification is ResourceIntent.DISTRACTION
            else StudyEffectiveState.UNRESOLVED
        )
        verdict = IntentVerdict(
            classification=classification,
            confidence=bounded_confidence,
            positive_reason_codes=_reason_values(positive),
            negative_reason_codes=_reason_values(negative),
            study_context_token=context_token,
            observation_token=token,
            resource_identity=identity,
            allowance_match=bool(allowance_match),
            off_task_dwell_seconds=0.0,
            sine_contribution=SineContribution.NONE,
            study_idle_allowed=False,
            measured_classification=classification,
            measured_confidence=bounded_confidence,
            effective_operational_state=effective_state,
        )
        return self._with_sine_policy(verdict, 0.0)

    def study_memory_entries(self) -> tuple[StudySessionMemoryEntry, ...]:
        """Return the active Study scope's bounded memory in LRU order."""

        with self._lock:
            return tuple(
                sorted(
                    self._study_memory.values(),
                    key=lambda item: (item.last_used_order, item.resource_key),
                )
            )

    def _remember_confirmation(
        self,
        context: StudyContext,
        confirmation: StudyConfirmationRecord,
    ) -> None:
        resource_key = confirmation.resource_key
        if resource_key not in self._study_memory and len(self._study_memory) >= (
            STUDY_CONFIRMATION_MEMORY_CAPACITY
        ):
            eviction_candidates = tuple(
                entry
                for entry in self._study_memory.values()
                if entry.resource_key != self._active_resource_key
            )
            if not eviction_candidates:
                raise RuntimeError("Study confirmation memory has no inactive LRU slot")
            victim = min(
                eviction_candidates,
                key=lambda item: (item.last_used_order, item.confirmed_monotonic_ns),
            )
            del self._study_memory[victim.resource_key]

        self._study_memory_access_order += 1
        self._study_memory[resource_key] = StudySessionMemoryEntry(
            study_context_token=context.context_token,
            task_fingerprint=task_fingerprint(context.subject, context.task),
            resource_key=resource_key,
            observation_token=confirmation.observation_token,
            measured_classification=confirmation.measured_classification,
            measured_confidence=confirmation.measured_confidence,
            user_confirmation=confirmation.user_confirmation,
            effective_operational_state=confirmation.effective_operational_state,
            confirmed_monotonic_ns=confirmation.confirmed_monotonic_ns,
            confirmation_source=confirmation.source,
            last_used_order=self._study_memory_access_order,
        )
        self._refresh_legacy_confirmation_aliases()

    def _matching_memory_entry(
        self,
        context: StudyContext,
        identity: ResourceIdentity,
    ) -> StudySessionMemoryEntry | None:
        entry = self._study_memory.get(identity.stable_key)
        if (
            entry is None
            or entry.study_context_token != context.context_token
            or entry.task_fingerprint
            != task_fingerprint(context.subject, context.task)
        ):
            return None
        if (
            entry.user_confirmation is StudyUserConfirmation.STUDY
            and not is_allowance_eligible(identity)
        ):
            return None
        return entry

    def _touch_memory_entry(
        self,
        entry: StudySessionMemoryEntry,
    ) -> StudySessionMemoryEntry:
        self._study_memory_access_order += 1
        touched = replace(entry, last_used_order=self._study_memory_access_order)
        self._study_memory[entry.resource_key] = touched
        self._refresh_legacy_confirmation_aliases()
        return touched

    def _refresh_legacy_confirmation_aliases(self) -> None:
        if not self._study_memory:
            self._allowance = None
            self._confirmation = None
            return
        newest = max(
            self._study_memory.values(),
            key=lambda item: item.last_used_order,
        )
        self._confirmation = StudyConfirmationRecord(
            study_context_token=newest.study_context_token,
            resource_key=newest.resource_key,
            observation_token=newest.observation_token,
            measured_classification=newest.measured_classification,
            measured_confidence=newest.measured_confidence,
            user_confirmation=newest.user_confirmation,
            effective_operational_state=newest.effective_operational_state,
            confirmed_monotonic_ns=newest.confirmed_monotonic_ns,
            source=newest.confirmation_source,
        )
        study_entries = tuple(
            entry
            for entry in self._study_memory.values()
            if entry.user_confirmation is StudyUserConfirmation.STUDY
        )
        if not study_entries:
            self._allowance = None
            return
        newest_study = max(study_entries, key=lambda item: item.last_used_order)
        self._allowance = AllowanceRecord(
            study_context_token=newest_study.study_context_token,
            task_fingerprint=newest_study.task_fingerprint,
            resource_key=newest_study.resource_key,
            granted_monotonic_ns=newest_study.confirmed_monotonic_ns,
            active=True,
            measured_classification=newest_study.measured_classification,
            measured_confidence=newest_study.measured_confidence,
            confirmation_source=newest_study.confirmation_source,
        )

    def _clear_study_memory(self) -> None:
        self._study_memory.clear()
        self._study_memory_access_order = 0
        self._active_resource_key = ""
        self._allowance = None
        self._confirmation = None

    def _allowance_matches(
        self,
        context: StudyContext,
        identity: ResourceIdentity,
    ) -> bool:
        entry = self._matching_memory_entry(context, identity)
        return bool(
            entry is not None
            and entry.user_confirmation is StudyUserConfirmation.STUDY
        )

    def _is_regressed(self, observation: ResourceObservation) -> bool:
        if self._latest is None:
            return False
        previous = self._latest.observation
        return bool(
            observation.observed_monotonic_ns < previous.observed_monotonic_ns
            or (
                observation.observed_monotonic_ns
                == previous.observed_monotonic_ns
                and observation.sequence < previous.sequence
            )
            or (
                observation.observed_monotonic_ns
                == previous.observed_monotonic_ns
                and observation.sequence == previous.sequence
                and observation_token(observation)
                != observation_token(previous)
            )
        )

    @staticmethod
    def _same_decision(left: IntentVerdict, right: IntentVerdict) -> bool:
        return bool(
            left.study_context_token == right.study_context_token
            and left.resource_identity.stable_key
            == right.resource_identity.stable_key
            and left.classification is right.classification
            and left.confidence == right.confidence
            and left.allowance_match == right.allowance_match
            and left.sine_contribution is right.sine_contribution
            and left.off_task_dwell_seconds == right.off_task_dwell_seconds
            and left.negative_reason_codes == right.negative_reason_codes
            and left.measured_classification is right.measured_classification
            and left.measured_confidence == right.measured_confidence
            and left.user_confirmation is right.user_confirmation
            and left.effective_operational_state is right.effective_operational_state
            and left.confirmation_source == right.confirmation_source
        )

    @staticmethod
    def _denied(outcome: AllowanceOutcome, detail: str) -> AllowanceResult:
        return AllowanceResult(outcome=outcome, detail=detail)

    def _require_active(self) -> None:
        if not self._started or self._closed:
            raise RuntimeError("Resource Intent session is not active")

    def _reset_dwell(self) -> None:
        self._dwell_key = None
        self._dwell_started_ns = -1
        self._dwell_last_ns = -1

    def _reset_all(self) -> None:
        self._context = None
        self._clear_study_memory()
        self._latest = None
        self._protected_red_active = False
        self._sine_episode_active = False
        self._cosine_active = False
        self._cosine_owned = False
        self._certified_ott_platform_key = ""
        self._clear_uncertainty_state()
        self._facts.clear()
        self._reset_dwell()
        self._stage_one_target_seconds = None


__all__ = (
    "AllowanceOutcome",
    "AllowanceRecord",
    "AllowanceResult",
    "IntentReason",
    "IntentVerdict",
    "ResourceIntentFact",
    "ResourceIdentity",
    "ResourceIntent",
    "ResourceIntentAuthority",
    "ResourceIntentLiveView",
    "ResourceIntentSnapshot",
    "ResourceObservation",
    "ResourceSurface",
    "SineContribution",
    "STUDY_CONFIRMATION_MEMORY_CAPACITY",
    "STUDY_UNCERTAINTY_INTERVAL_SECONDS",
    "StudyConfirmationPopupRequest",
    "StudyConfirmationRecord",
    "StudyConfirmationResponse",
    "StudyContext",
    "StudyEffectiveState",
    "StudySessionMemoryEntry",
    "StudyUserConfirmation",
    "build_observation",
    "build_resource_identity",
    "context_terms",
    "is_allowance_eligible",
    "normalise_text",
    "normalise_title",
    "observation_token",
    "searchable_text",
    "study_context_token",
    "task_fingerprint",
    "tokenise",
)
