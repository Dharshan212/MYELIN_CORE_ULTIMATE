"""Executive Blacklist policy and continuous dwell authority for MYELIN.

This module answers two questions only:

1. Is the *certified current resource* managed by the Executive Blacklist?
2. Has one continuous visit reached the threshold offered to SINE?

Authority order
---------------
1. Accept the foreground fact already produced by ``monitor.py``.
2. Resolve a platform from a certified browser host, or an exact native
   process name.
3. Classify the content surface from ``browser.py`` and
   ``resource_intent.py`` facts.
4. Advance one monotonic dwell watch for the same window and platform,
   against this session's personalized stage-one threshold.
5. Offer threshold evidence to Trigger after the configured threshold.

Critical identity rule
----------------------
A window title never identifies Instagram, YouTube, X, or any other managed
platform.  This deliberately removes the old loose title-substring fallback.
For example, ``Instagram marketing plan - Word`` remains a Word document.

Canonical process identity
--------------------------
``monitor.py`` reports an extensionless foreground process (``chrome``) while
``browser.py`` canonicalises the same executable with its suffix
(``chrome.exe``).  Both name one executable, so this module folds every process
name it is given -- foreground, browser snapshot and registry entry alike --
through :func:`_normalise_process` before any comparison.  Extensionless is the
canonical MYELIN internal form already used by ``resource_intent.py`` and
``trigger.py``; this file adapts to it rather than asking monitor to change.

Ownership boundary
------------------
Only ``trigger.py`` mints a ``TriggerCandidate``.  This module publishes a
``BlacklistThresholdOffer`` -- the factual statement that one continuous visit
reached the threshold -- and never decides that a trigger happened.

This file does not read Windows, inspect a browser, calculate Resource Intent,
open SINE, persist events, or create a thread.  It consumes one immutable
``MonitorContext`` per cycle and publishes one immutable snapshot.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Final

from CORE_ENGINE.browser import BrowserUrlReadStatus, UrlEvidenceKind
from CORE_ENGINE.resource_intent import ResourceIntent, ResourceSurface


POLICY_VERSION: Final = "myelin-executive-blacklist-v2"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
MAX_CONTINUITY_GAP_SECONDS: Final = 6.0


class AccusedClass(str, Enum):
    NONE = "none"
    SHORT_FORM = "short_form"
    LONG_FORM = "long_form"


class SurfaceClass(str, Enum):
    SHORT_FEED = "short_feed"
    SELECTED_VIDEO = "selected_video"
    SOCIAL_FEED = "social_feed"
    EDUCATION = "education"
    STATIC_ENTRY = "static_entry"
    PRODUCTIVE = "productive"
    MESSAGING = "messaging"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class Disposition(str, Enum):
    ACCUSED = "accused"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"
    HANDOFF = "handoff"
    UNSUPPORTED = "unsupported"


class EvidenceSource(str, Enum):
    CERTIFIED_URL = "certified_url"
    EXACT_NATIVE_PROCESS = "exact_native_process"
    RESOURCE_INTENT = "resource_intent"
    CERTIFIED_URL_AND_INTENT = "certified_url_and_intent"
    NONE = "none"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    NONE = "none"


class WatchState(str, Enum):
    INACTIVE = "inactive"
    WATCHING = "watching"
    THRESHOLD_REACHED = "threshold_reached"
    SUBMITTED = "submitted"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class SineThresholdPolicy:
    """Threshold facts owned by policy, not by the popup layer."""

    stage_one_seconds: float = 300.0
    stage_two_cumulative_seconds: float = 900.0
    offer_retry_seconds: float = 20.0

    def __post_init__(self) -> None:
        values = (
            self.stage_one_seconds,
            self.stage_two_cumulative_seconds,
            self.offer_retry_seconds,
        )
        if not all(math.isfinite(float(value)) and value > 0 for value in values):
            raise ValueError("SINE thresholds must be finite positive seconds")
        if self.stage_two_cumulative_seconds <= self.stage_one_seconds:
            raise ValueError("Stage two must occur after stage one")


DEFAULT_THRESHOLDS: Final = SineThresholdPolicy()


def _normalise_process(value: object) -> str:
    """Fold one executable name to its canonical extensionless identity.

    ``Chrome.exe``, ``chrome.exe`` and ``chrome`` are the same executable.  The
    suffix is removed rather than added because every other MYELIN authority
    already compares extensionless process names.
    """

    return str(value or "").strip().casefold().removesuffix(".exe")


@dataclass(frozen=True, slots=True)
class PlatformPolicy:
    """One registry entry with exact native executable names."""

    key: str
    label: str
    native_processes: tuple[str, ...] = ()


# INSTRUCTION: browser platform identity never comes from this process map.
# Browser identity must come from certified host evidence supplied by browser.py.
PLATFORM_REGISTRY: Final = (
    PlatformPolicy("instagram", "Instagram", ("instagram.exe",)),
    PlatformPolicy("youtube", "YouTube", ("youtube.exe",)),
    PlatformPolicy("facebook", "Facebook", ("facebook.exe",)),
    PlatformPolicy("linkedin", "LinkedIn", ("linkedin.exe",)),
    PlatformPolicy("x", "X", ("x.exe", "twitter.exe")),
    PlatformPolicy("tiktok", "TikTok", ("tiktok.exe",)),
    PlatformPolicy("snapchat", "Snapchat", ("snapchat.exe",)),
    PlatformPolicy("twitch", "Twitch", ("twitch.exe",)),
    PlatformPolicy("reddit", "Reddit", ("reddit.exe",)),
    PlatformPolicy("quora", "Quora", ("quora.exe",)),
    PlatformPolicy("9gag", "9GAG", ("9gag.exe",)),
    PlatformPolicy("threads", "Threads", ("threads.exe",)),
    PlatformPolicy("bluesky", "Bluesky", ("bluesky.exe",)),
    PlatformPolicy("pinterest", "Pinterest", ("pinterest.exe",)),
    PlatformPolicy("tumblr", "Tumblr", ("tumblr.exe",)),
    PlatformPolicy("flickr", "Flickr", ("flickr.exe",)),
    PlatformPolicy("4chan", "4chan", ("4chan.exe",)),
)

_POLICY_BY_KEY: Final = {policy.key: policy for policy in PLATFORM_REGISTRY}
# Registry entries are written as executables; they are indexed by the one
# canonical identity rule so an extensionless foreground name still matches.
_POLICY_BY_PROCESS: Final = {
    _normalise_process(process): policy
    for policy in PLATFORM_REGISTRY
    for process in policy.native_processes
}


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Exact foreground source used to guard dwell continuity."""

    process_name: str
    process_id: int
    hwnd: int

    @property
    def valid(self) -> bool:
        return bool(self.process_name and self.process_id > 0 and self.hwnd > 0)


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    policy: PlatformPolicy
    source: EvidenceSource
    browser_host_certified: bool


@dataclass(frozen=True, slots=True)
class BlacklistVerdict:
    platform_key: str
    platform_label: str
    accused_class: AccusedClass
    surface_class: SurfaceClass
    disposition: Disposition
    confidence: Confidence
    evidence_source: EvidenceSource
    rule_id: str
    reason: str
    watch_eligible: bool
    policy_version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if self.disposition is Disposition.ACCUSED:
            if self.accused_class is AccusedClass.NONE or not self.watch_eligible:
                raise ValueError("An accused verdict requires a class and watch")
        elif self.accused_class is not AccusedClass.NONE:
            raise ValueError("Only an accused verdict may carry an accused class")
        if self.disposition in {
            Disposition.EXCLUDED,
            Disposition.HANDOFF,
            Disposition.UNSUPPORTED,
        } and self.watch_eligible:
            raise ValueError("Excluded, handoff and unsupported resources cannot watch")

    @property
    def actionable(self) -> bool:
        return self.watch_eligible and self.disposition in {
            Disposition.ACCUSED,
            Disposition.UNKNOWN,
        }

    @property
    def display_label(self) -> str:
        suffix = (
            self.accused_class.value
            if self.accused_class is not AccusedClass.NONE
            else self.surface_class.value
        )
        return f"{self.platform_label} · {suffix.replace('_', ' ').upper()}"


@dataclass(frozen=True, slots=True)
class BlacklistThresholdOffer:
    """A factual threshold offer; Trigger alone mints the TriggerCandidate."""

    offer_uid: str
    event_name: str
    source_authority: str
    platform_key: str
    platform_label: str
    accused_class: str
    surface_class: str
    rule_id: str
    dwell_seconds: float
    threshold_seconds: float
    source_process: str
    source_process_id: int
    source_hwnd: int
    resource_key: str
    observed_monotonic_ns: int
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True, slots=True)
class BlacklistSnapshot:
    source_identity: SourceIdentity
    verdict: BlacklistVerdict
    state: WatchState
    elapsed_seconds: float
    target_seconds: float
    restarted: bool
    threshold_reached: bool
    threshold_offer: BlacklistThresholdOffer | None
    study_context_active: bool
    resource_key: str
    observation_sequence: int

    @property
    def should_submit(self) -> bool:
        return self.threshold_offer is not None


@dataclass(frozen=True, slots=True)
class BlacklistLiveView:
    platform_key: str
    resource_label: str
    resource_title: str
    disposition: Disposition
    accused_class: AccusedClass
    surface_class: SurfaceClass
    confidence: Confidence
    rule_id: str
    reason: str
    dwell_elapsed_seconds: float
    dwell_target_seconds: float
    state: WatchState
    next_sine_stage: int | None
    seconds_to_next_stage: float | None
    study_context_active: bool
    policy_version: str = POLICY_VERSION


def policy_for_key(value: object) -> PlatformPolicy | None:
    """Return a registry policy by exact canonical key."""

    return _POLICY_BY_KEY.get(str(value or "").strip().casefold())


def policy_for_native_process(value: object) -> PlatformPolicy | None:
    """Return a policy only for an exact executable name.

    INSTRUCTION: do not add title, category or substring fallback here.
    """

    return _POLICY_BY_PROCESS.get(_normalise_process(value))


def resolve_platform(foreground: object, browser_snapshot: object) -> PlatformIdentity | None:
    """Resolve platform identity without using the foreground title."""

    process_name = _normalise_process(getattr(foreground, "process_name", ""))
    hwnd = int(getattr(foreground, "hwnd", 0) or 0)
    process_id = int(getattr(foreground, "process_id", 0) or 0)

    evidence = getattr(browser_snapshot, "evidence", None)
    browser_scope_matches = bool(
        evidence is not None
        and bool(getattr(browser_snapshot, "supported_browser", False))
        and int(getattr(browser_snapshot, "hwnd", 0) or 0) == hwnd
        and int(getattr(browser_snapshot, "process_id", 0) or 0) == process_id
        and _normalise_process(getattr(browser_snapshot, "process_name", ""))
        == process_name
        and getattr(browser_snapshot, "status", None) is BrowserUrlReadStatus.OK
    )
    if browser_scope_matches:
        policy = policy_for_key(getattr(evidence, "platform_key", ""))
        if policy is not None:
            return PlatformIdentity(policy, EvidenceSource.CERTIFIED_URL, True)

    # A held strong result is still certified by browser.py's bounded stability
    # contract and is accepted only for the exact same foreground scope.
    held_scope_matches = bool(
        evidence is not None
        and bool(getattr(browser_snapshot, "authoritative", False))
        and bool(getattr(browser_snapshot, "holding_previous_strong_evidence", False))
        and int(getattr(browser_snapshot, "hwnd", 0) or 0) == hwnd
        and int(getattr(browser_snapshot, "process_id", 0) or 0) == process_id
        and _normalise_process(getattr(browser_snapshot, "process_name", ""))
        == process_name
    )
    if held_scope_matches:
        policy = policy_for_key(getattr(evidence, "platform_key", ""))
        if policy is not None:
            return PlatformIdentity(policy, EvidenceSource.CERTIFIED_URL, True)

    policy = policy_for_native_process(process_name)
    if policy is not None:
        return PlatformIdentity(policy, EvidenceSource.EXACT_NATIVE_PROCESS, False)
    return None


def _unsupported(reason: str) -> BlacklistVerdict:
    return BlacklistVerdict(
        platform_key="",
        platform_label="",
        accused_class=AccusedClass.NONE,
        surface_class=SurfaceClass.UNSUPPORTED,
        disposition=Disposition.UNSUPPORTED,
        confidence=Confidence.NONE,
        evidence_source=EvidenceSource.NONE,
        rule_id="EB-UNSUPPORTED-000",
        reason=reason,
        watch_eligible=False,
    )


def _verdict(
    identity: PlatformIdentity,
    *,
    accused: AccusedClass,
    surface: SurfaceClass,
    disposition: Disposition,
    confidence: Confidence,
    source: EvidenceSource,
    rule_id: str,
    reason: str,
    watch: bool,
) -> BlacklistVerdict:
    return BlacklistVerdict(
        platform_key=identity.policy.key,
        platform_label=identity.policy.label,
        accused_class=accused,
        surface_class=surface,
        disposition=disposition,
        confidence=confidence,
        evidence_source=source,
        rule_id=rule_id,
        reason=reason,
        watch_eligible=watch,
    )


def classify_resource(
    identity: PlatformIdentity | None,
    browser_snapshot: object,
    intent_snapshot: object,
) -> BlacklistVerdict:
    """Classify one already-identified platform and content surface."""

    if identity is None:
        return _unsupported("No certified browser host or exact native process matched.")

    policy = identity.policy
    intent = getattr(intent_snapshot, "verdict", None)
    classification = getattr(intent, "classification", None)
    resource_identity = getattr(intent, "resource_identity", None)
    resource_surface = getattr(resource_identity, "surface", ResourceSurface.UNKNOWN)
    allowance_match = bool(getattr(intent, "allowance_match", False))

    # Resource Intent is the only authority that can confirm study alignment.
    if classification in {ResourceIntent.STUDY_ALIGNED, ResourceIntent.BACKGROUND_AUDIO}:
        return _verdict(
            identity,
            accused=AccusedClass.NONE,
            surface=SurfaceClass.EDUCATION,
            disposition=Disposition.EXCLUDED,
            confidence=Confidence.HIGH,
            source=EvidenceSource.RESOURCE_INTENT,
            rule_id="EB-STUDY-EXCLUDE-001",
            reason="Resource Intent confirmed this exact resource as study-aligned.",
            watch=False,
        )
    if allowance_match:
        return _verdict(
            identity,
            accused=AccusedClass.NONE,
            surface=SurfaceClass.EDUCATION,
            disposition=Disposition.EXCLUDED,
            confidence=Confidence.HIGH,
            source=EvidenceSource.RESOURCE_INTENT,
            rule_id="EB-STUDY-ALLOWANCE-001",
            reason="An exact current study-material allowance is active.",
            watch=False,
        )
    if resource_surface is ResourceSurface.MESSAGING:
        return _verdict(
            identity,
            accused=AccusedClass.NONE,
            surface=SurfaceClass.MESSAGING,
            disposition=Disposition.HANDOFF,
            confidence=Confidence.HIGH,
            source=EvidenceSource.RESOURCE_INTENT,
            rule_id="EB-MESSAGING-HANDOFF-001",
            reason="Messaging belongs to its separate MYELIN policy.",
            watch=False,
        )

    evidence = getattr(browser_snapshot, "evidence", None)
    evidence_kind = getattr(evidence, "kind", None)
    certified_for_platform = bool(
        identity.browser_host_certified
        and getattr(evidence, "platform_key", "") == policy.key
    )

    if certified_for_platform and evidence_kind is UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE:
        return _verdict(identity, accused=AccusedClass.NONE, surface=SurfaceClass.MESSAGING,
                        disposition=Disposition.HANDOFF, confidence=Confidence.HIGH,
                        source=EvidenceSource.CERTIFIED_URL,
                        rule_id=f"EB-{policy.key.upper()}-HANDOFF-001",
                        reason="A certified messaging route was observed.", watch=False)
    if certified_for_platform and evidence_kind is UrlEvidenceKind.CONFIRMED_PRODUCTIVE_PAGE:
        return _verdict(identity, accused=AccusedClass.NONE, surface=SurfaceClass.PRODUCTIVE,
                        disposition=Disposition.EXCLUDED, confidence=Confidence.HIGH,
                        source=EvidenceSource.CERTIFIED_URL,
                        rule_id=f"EB-{policy.key.upper()}-PRODUCTIVE-001",
                        reason="A certified productive route was observed.", watch=False)
    if certified_for_platform and evidence_kind is UrlEvidenceKind.CONFIRMED_STATIC_ENTRY:
        return _verdict(identity, accused=AccusedClass.NONE, surface=SurfaceClass.STATIC_ENTRY,
                        disposition=Disposition.EXCLUDED, confidence=Confidence.HIGH,
                        source=EvidenceSource.CERTIFIED_URL,
                        rule_id=f"EB-{policy.key.upper()}-STATIC-001",
                        reason="A certified login, signup or static route was observed.", watch=False)
    if certified_for_platform and evidence_kind is UrlEvidenceKind.CONFIRMED_SHORT_FEED:
        return _verdict(identity, accused=AccusedClass.SHORT_FORM, surface=SurfaceClass.SHORT_FEED,
                        disposition=Disposition.ACCUSED, confidence=Confidence.HIGH,
                        source=EvidenceSource.CERTIFIED_URL,
                        rule_id=f"EB-{policy.key.upper()}-SHORT-001",
                        reason="A certified short-form route was observed.", watch=True)
    if certified_for_platform and evidence_kind is UrlEvidenceKind.CONFIRMED_SOCIAL_FEED:
        return _verdict(identity, accused=AccusedClass.LONG_FORM, surface=SurfaceClass.SOCIAL_FEED,
                        disposition=Disposition.ACCUSED, confidence=Confidence.HIGH,
                        source=EvidenceSource.CERTIFIED_URL,
                        rule_id=f"EB-{policy.key.upper()}-FEED-001",
                        reason="A certified social-feed route was observed.", watch=True)
    if certified_for_platform and evidence_kind is UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO:
        return _verdict(identity, accused=AccusedClass.LONG_FORM, surface=SurfaceClass.SELECTED_VIDEO,
                        disposition=Disposition.ACCUSED, confidence=Confidence.HIGH,
                        source=EvidenceSource.CERTIFIED_URL,
                        rule_id=f"EB-{policy.key.upper()}-VIDEO-001",
                        reason="A certified selected-video route was observed.", watch=True)

    # A known host/native app with an unknown internal surface receives the
    # conservative five-minute watch. It is not called SHORT or LONG without
    # evidence, and its confidence remains NONE.
    return _verdict(
        identity,
        accused=AccusedClass.NONE,
        surface=SurfaceClass.UNKNOWN,
        disposition=Disposition.UNKNOWN,
        confidence=Confidence.NONE,
        source=identity.source,
        rule_id=f"EB-{policy.key.upper()}-UNKNOWN-001",
        reason="The platform is certified, but its active content surface is unknown.",
        watch=True,
    )


class BlacklistAuthority:
    """One registry, matcher and monotonic dwell watch for one session."""

    def __init__(self, *, thresholds: SineThresholdPolicy = DEFAULT_THRESHOLDS) -> None:
        self._lock = threading.RLock()
        self._thresholds = thresholds
        # Frozen once per session by monitor.py from the previous session's
        # verified return latency.  1.0 means "no learned personalization yet"
        # (session 1, or a profile with no eligible previous session).
        self._personalization_factor = 1.0
        self._session_secret = secrets.token_bytes(32)
        self._started = False
        self._closed = False
        self._paused = False
        self._watch_generation = 0
        self._platform_key = ""
        self._source = SourceIdentity("", 0, 0)
        self._started_ns = -1
        self._last_seen_ns = -1
        self._last_observed_ns = -1
        self._last_sequence = -1
        self._last_offer_ns = -1
        self._admitted_offer_uid = ""
        self._resource_title = ""
        self._latest: BlacklistSnapshot | None = None

    def start_session(self, *, personalization_factor: float = 1.0) -> None:
        """Begin one session, optionally personalized by this session's F.

        ``personalization_factor`` arrives already clamped from
        ``trigger.mbrm_session_personalization``.  Blacklist neither derives
        nor re-clamps it; it only applies it to its own stage-one threshold so
        the first SINE adapts exactly like stages two and three.
        """

        with self._lock:
            self._personalization_factor = self._normalise_factor(personalization_factor)
            self._reset_watch()
            self._session_secret = secrets.token_bytes(32)
            self._started = True
            self._closed = False
            self._paused = False
            self._last_observed_ns = -1
            self._last_sequence = -1
            self._latest = None

    def observe(self, context: object) -> BlacklistSnapshot:
        """Advance exactly once from the facts supplied by monitor.py."""

        with self._lock:
            self._require_active()
            foreground = getattr(context, "foreground")
            browser_snapshot = getattr(context, "browser_evidence")
            intent_snapshot = getattr(context, "resource_intent")
            sequence = int(getattr(foreground, "sequence", 0) or 0)
            now_ns = int(getattr(foreground, "observed_monotonic_ns", 0) or 0)

            # A regressed or duplicate monitor fact must not advance time twice.
            if self._latest is not None and (
                sequence <= self._last_sequence
                or now_ns <= self._last_observed_ns
            ):
                return self._latest

            source = SourceIdentity(
                _normalise_process(getattr(foreground, "process_name", "")),
                int(getattr(foreground, "process_id", 0) or 0),
                int(getattr(foreground, "hwnd", 0) or 0),
            )
            identity = resolve_platform(foreground, browser_snapshot)
            verdict = classify_resource(identity, browser_snapshot, intent_snapshot)
            intent_verdict = getattr(intent_snapshot, "verdict", None)
            study_active = bool(getattr(intent_verdict, "study_context_token", ""))
            resource_identity = getattr(intent_verdict, "resource_identity", None)
            resource_key = str(getattr(resource_identity, "stable_key", "") or "")
            resource_title = str(getattr(resource_identity, "normalised_title", "") or "")[:240]

            restarted = False
            offer = None
            target = self._stage_one_target()
            if self._paused or not verdict.actionable or not source.valid or now_ns <= 0:
                self._reset_watch()
                state = WatchState.PAUSED if self._paused else WatchState.INACTIVE
                elapsed = 0.0
            else:
                gap_ns = now_ns - self._last_seen_ns if self._last_seen_ns >= 0 else 0
                continuity_broken = bool(
                    self._started_ns < 0
                    or source != self._source
                    or verdict.platform_key != self._platform_key
                    or gap_ns > int(MAX_CONTINUITY_GAP_SECONDS * NANOSECONDS_PER_SECOND)
                    or gap_ns < 0
                )
                if continuity_broken:
                    self._begin_watch(source, verdict.platform_key, now_ns)
                    restarted = True

                self._last_seen_ns = now_ns
                self._last_sequence = sequence
                self._resource_title = resource_title
                elapsed = max(0.0, (now_ns - self._started_ns) / NANOSECONDS_PER_SECOND)
                threshold_reached = elapsed >= target
                retry_ns = int(self._thresholds.offer_retry_seconds * NANOSECONDS_PER_SECOND)
                retry_due = self._last_offer_ns < 0 or now_ns - self._last_offer_ns >= retry_ns
                if threshold_reached and not self._admitted_offer_uid and retry_due:
                    offer = self._threshold_offer(
                        verdict=verdict,
                        source=source,
                        resource_key=resource_key,
                        elapsed_seconds=elapsed,
                        now_ns=now_ns,
                    )
                    self._last_offer_ns = now_ns
                state = (
                    WatchState.SUBMITTED
                    if self._admitted_offer_uid
                    else WatchState.THRESHOLD_REACHED
                    if threshold_reached
                    else WatchState.WATCHING
                )

            # For inactive samples, remember sequence/time only for deduplication;
            # the next actionable sample starts a fresh visit.
            self._last_sequence = sequence
            self._last_observed_ns = now_ns
            threshold_reached = elapsed >= target and state not in {
                WatchState.INACTIVE,
                WatchState.PAUSED,
            }
            snapshot = BlacklistSnapshot(
                source_identity=source,
                verdict=verdict,
                state=state,
                elapsed_seconds=elapsed,
                target_seconds=target,
                restarted=restarted,
                threshold_reached=threshold_reached,
                threshold_offer=offer,
                study_context_active=study_active,
                resource_key=resource_key,
                observation_sequence=sequence,
            )
            self._latest = snapshot
            return snapshot

    def confirm_admitted(self, offer_uid: str) -> bool:
        """Record durable trigger admission without opening SINE here."""

        with self._lock:
            expected = self._offer_uid()
            if (
                not expected
                or self._last_offer_ns < 0
                or str(offer_uid or "") != expected
            ):
                return False
            self._admitted_offer_uid = expected
            return True

    def reject_offer(self, offer_uid: str) -> bool:
        """Allow a rejected offer to retry after the policy interval."""

        with self._lock:
            if str(offer_uid or "") != self._offer_uid():
                return False
            self._admitted_offer_uid = ""
            return True

    def rearm(self) -> None:
        """Rearm the current visit after SINE has safely completed."""

        with self._lock:
            self._admitted_offer_uid = ""
            self._last_offer_ns = -1

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            self._reset_watch()

    def live_view(self) -> BlacklistLiveView | None:
        with self._lock:
            snapshot = self._latest
            if snapshot is None:
                return None
            verdict = snapshot.verdict
            next_stage = 1 if snapshot.state is WatchState.WATCHING else None
            seconds_to_next = (
                max(0.0, snapshot.target_seconds - snapshot.elapsed_seconds)
                if next_stage is not None
                else None
            )
            return BlacklistLiveView(
                platform_key=verdict.platform_key,
                resource_label=verdict.display_label.upper() if verdict.platform_key else "",
                resource_title=self._resource_title,
                disposition=verdict.disposition,
                accused_class=verdict.accused_class,
                surface_class=verdict.surface_class,
                confidence=verdict.confidence,
                rule_id=verdict.rule_id,
                reason=verdict.reason,
                dwell_elapsed_seconds=snapshot.elapsed_seconds,
                dwell_target_seconds=snapshot.target_seconds,
                state=snapshot.state,
                next_sine_stage=next_stage,
                seconds_to_next_stage=seconds_to_next,
                study_context_active=snapshot.study_context_active,
            )

    def shutdown(self) -> None:
        with self._lock:
            self._reset_watch()
            self._latest = None
            self._started = False
            self._closed = True
            self._last_observed_ns = -1
            self._last_sequence = -1

    def _begin_watch(self, source: SourceIdentity, platform_key: str, now_ns: int) -> None:
        self._watch_generation += 1
        self._source = source
        self._platform_key = platform_key
        self._started_ns = now_ns
        self._last_seen_ns = now_ns
        self._last_offer_ns = -1
        self._admitted_offer_uid = ""

    def _reset_watch(self) -> None:
        self._platform_key = ""
        self._source = SourceIdentity("", 0, 0)
        self._started_ns = -1
        self._last_seen_ns = -1
        self._last_offer_ns = -1
        self._admitted_offer_uid = ""
        self._resource_title = ""

    def _offer_uid(self) -> str:
        if self._started_ns < 0 or not self._platform_key:
            return ""
        payload = (
            f"{self._watch_generation}|{self._platform_key}|"
            f"{self._source.process_name}|{self._source.process_id}|"
            f"{self._source.hwnd}|{self._started_ns}"
        ).encode("utf-8")
        return hashlib.blake2s(
            payload,
            key=self._session_secret,
            digest_size=16,
        ).hexdigest()

    def _threshold_offer(
        self,
        *,
        verdict: BlacklistVerdict,
        source: SourceIdentity,
        resource_key: str,
        elapsed_seconds: float,
        now_ns: int,
    ) -> BlacklistThresholdOffer:
        return BlacklistThresholdOffer(
            offer_uid=self._offer_uid(),
            event_name="executive_blacklist_dwell",
            source_authority="blacklist",
            platform_key=verdict.platform_key,
            platform_label=verdict.platform_label,
            accused_class=verdict.accused_class.value,
            surface_class=verdict.surface_class.value,
            rule_id=verdict.rule_id,
            dwell_seconds=elapsed_seconds,
            threshold_seconds=self._stage_one_target(),
            source_process=source.process_name,
            source_process_id=source.process_id,
            source_hwnd=source.hwnd,
            resource_key=resource_key,
            observed_monotonic_ns=now_ns,
        )

    @staticmethod
    def _normalise_factor(value: object) -> float:
        """Accept only a finite positive factor; anything else means 1.0.

        A malformed factor must never be able to collapse the dwell threshold
        to zero and fire SINE instantly.
        """

        try:
            factor = float(value)
        except (TypeError, ValueError):
            return 1.0
        if not math.isfinite(factor) or factor <= 0.0:
            return 1.0
        return factor

    @property
    def personalization_factor(self) -> float:
        """This session's frozen F, for display and telemetry only."""

        with self._lock:
            return self._personalization_factor

    def stage_one_target_seconds(self) -> float:
        """The personalized stage-one dwell target actually in force."""

        with self._lock:
            return self._stage_one_target()

    def _stage_one_target(self) -> float:
        return self._thresholds.stage_one_seconds * self._personalization_factor

    def _require_active(self) -> None:
        if not self._started or self._closed:
            raise RuntimeError("Blacklist session is not active")


__all__ = (
    "AccusedClass",
    "BlacklistAuthority",
    "BlacklistLiveView",
    "BlacklistSnapshot",
    "BlacklistThresholdOffer",
    "BlacklistVerdict",
    "Confidence",
    "DEFAULT_THRESHOLDS",
    "Disposition",
    "EvidenceSource",
    "PLATFORM_REGISTRY",
    "PlatformPolicy",
    "SineThresholdPolicy",
    "SourceIdentity",
    "SurfaceClass",
    "WatchState",
    "classify_resource",
    "policy_for_key",
    "policy_for_native_process",
    "resolve_platform",
)
