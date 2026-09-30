"""Chapter 6 lifetime-database summary: read-only, Qt-free.

Replaces Chapter 6's old Chapter-3-experiment-transfer Evidence data source.
Chapter 6 → EVIDENCE is a MYELIN LIFETIME SUMMARY, not a current Science Lab
experiment-results page: there is no experiment window, no transfer receipt,
no Chapter 3/5 dependency here at all.

Final Four-Card Evidence Completion (20260915): the summary now covers
exactly four cards -- BEST RETURN, WORST RETURN, TOP DISTRACTION PLATFORM,
TOP OTT PLATFORM. PRIMARY REGULATION DOMAIN and TOP FOCUS PLATFORM were
removed entirely (product decision, not an engineering gap -- neither had a
durable lifetime ledger to read). TOP DISTRACTION PLATFORM and TOP OTT
PLATFORM are now real dynamic lifetime aggregations, each reusing an
existing durable read authority:
- TOP DISTRACTION PLATFORM counts each durable SINE operational admission
  that carries a certified structured ``platform_key``
  (``PERSISTENCE.storage.read_trigger_platform_keys``, added alongside this
  patch -- the same trigger ledger ``read_trigger_identities`` already
  reads, restricted to the structured field only, no process_name
  fallback), and reports the platform with the greatest count.
- TOP OTT PLATFORM sums each platform's own certified durable supported
  seconds from every CLOSED lifetime COSINE session's own closure payload
  (``PERSISTENCE.storage.read_cosine_events``, already the canonical
  lifetime-scoped COSINE reader -- see COSINE/cosine.py's
  ``_closure_payload``, which already allocates supported seconds per
  platform for hopper/multi-platform sessions), and reports the platform
  with the greatest cumulative total.
Both ranking definitions were locked by Chief, not chosen by this module;
see MYELIN_CHAPTER6_FINAL_FOUR_CARD_LIFETIME_COMPLETION_CLAUDE_20260915.txt.

This module:
- reads approved durable historical evidence through existing read
  authorities only (``PERSISTENCE.storage.read_mirl_events``, the same
  canonical reconstruction ``PERSISTENCE.storage.read_mirl_snapshot`` /
  ``read_science_lab_mirl_events`` already use -- never a private table;
  ``PERSISTENCE.storage.read_trigger_platform_keys``; and
  ``PERSISTENCE.storage.read_cosine_events``, COSINE's own canonical
  lifetime-scoped reader);
- performs approved deterministic lifetime aggregation for all four card
  families, each against one certified, unambiguous population and
  ranking rule;
- performs NO writes, opens no engine, starts no experiment;
- imports no PyQt6 and owns no widget.

Best/Worst reuses SCIENCE_LAB.analysis's own tested, unmodified chain-walk
helpers (``_successful_return_event_chain`` and everything it calls) --
the identical durable-identity rules Codex's Chapter 3 contract already
proved: episode_id + attempt_id + attempt_index + supporting_event_ids +
monotonic ordering, requiring return_verification_started -> return_verified
-> episode_closed(reason=RETURNED) for the SAME final successful attempt.
Nothing in analysis.py is changed. Only the SCOPE changes: lifetime reads
every durable MIRL event in the database (``read_mirl_events()``, no
session filter -- MIRL's own canonical lifetime reader, already used
unfiltered by ``read_mirl_snapshot`` for the existing MIRL export feature)
instead of one experiment-window-filtered slice, and there is deliberately
no ``SuccessfulReturnOnsetLatencyExtrema`` window-boundary validation here
(that dataclass's own ``__post_init__`` hard-requires a single bounded
experiment window, which does not exist -- and cannot honestly be
constructed -- at lifetime scope, since monotonic timestamps from separate
MYELIN process runs are not globally comparable; see LIFETIME SESSION
HANDLING below). A malformed/legacy episode that cannot support the exact
same durable chain is skipped (fails closed) rather than aborting the
entire lifetime read, and the count of skipped episodes is reported in the
reason text -- this is the one deliberate behavioral difference from
analysis.py's own strict per-request abort, justified because lifetime
history can span years of episodes including ones recorded before the
current durable-identity contract existed, where Chapter 3's single
supervised experiment window could not.

LIFETIME SESSION HANDLING: latency values here are always intra-episode
differences (a return-onset event's monotonic time minus its own episode's
opening-SINE-display monotonic time), so they remain valid regardless of
which MYELIN process run produced them. Episodes are never compared or
ordered against each other by raw cross-session monotonic value; grouping
is by durable ``episode_id`` only (a 128-bit random token minted by MIRL,
globally unique -- see MIRL/mirl.py), never by session or wall-clock
proximity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from .analysis import (
    AVAILABLE,
    UNAVAILABLE,
    AnalysisIntegrityError,
    EvidenceRef,
    SuccessfulReturnOnsetLatencySample,
    _event_attempt_id,
    _event_id,
    _event_name,
    _event_time,
    _mirl_chain_ref,
    _successful_return_event_chain,
)

#: Same construct name Chapter 3's certified contract already uses --
#: never renamed (not "recovery time", "refocus time", "cognitive
#: recovery", or similar). Only the population changes: every valid
#: lifetime episode, not one experiment's episodes.
_SUCCESSFUL_RETURN_ONSET_REFERENCE: Final = (
    "opening SINE display -> final successful return_verification_started, "
    "requiring durable proof of return_verified and a successful "
    "episode_closed(reason=RETURNED) for the same attempt"
)

_CARD_KEYS: Final = (
    "best_return",
    "worst_return",
    "top_distraction_platform",
    "top_ott_platform",
)


@dataclass(frozen=True, slots=True)
class LifetimeMetricResult:
    """One card's lifetime result. Presentation formatting (e.g. turning a
    raw nanosecond ``value`` into "12 min 3 s") is deliberately NOT done
    here -- that belongs to the view's presentation layer. ``value`` is an
    ``int`` (raw nanoseconds) for the two return-latency cards, or a plain
    display ``str`` (a platform label, or the literal ``"TIE"``) for the two
    platform cards -- either way it is the exact value the view renders,
    never something the view recomputes. ``status`` is always ``AVAILABLE``
    or ``UNAVAILABLE``; a read failure is reported as UNAVAILABLE with a
    ``reason`` prefixed ``read_error:`` (the same convention
    ``SCIENCE_LAB/evidence.py`` already uses for a source that could not be
    read safely), never silently turned into zero or omitted."""

    key: str
    status: str
    value: int | str | None
    unit: str
    reason: str
    supporting_count: int | None = None

    def __post_init__(self) -> None:
        if self.key not in _CARD_KEYS:
            raise ValueError(f"unknown Chapter 6 lifetime card key: {self.key!r}")
        if self.status not in (AVAILABLE, UNAVAILABLE):
            raise ValueError("Chapter 6 lifetime result status must be AVAILABLE/UNAVAILABLE")
        if self.status == UNAVAILABLE and self.value is not None:
            raise ValueError("an UNAVAILABLE Chapter 6 lifetime result cannot carry a value")
        if self.status == AVAILABLE and self.value is None:
            raise ValueError("an AVAILABLE Chapter 6 lifetime result requires a value")


@dataclass(frozen=True, slots=True)
class Chapter6LifetimeSummary:
    """One immutable REFRESH result. Every one of the four Evidence cards
    receives exactly one ``LifetimeMetricResult`` here -- there is no
    remaining "static placeholder" card after this module exists."""

    generated_at_utc: str
    best_return: LifetimeMetricResult
    worst_return: LifetimeMetricResult
    top_distraction_platform: LifetimeMetricResult
    top_ott_platform: LifetimeMetricResult

    def __post_init__(self) -> None:
        for key in _CARD_KEYS:
            if getattr(self, key).key != key:
                raise ValueError(f"Chapter 6 lifetime summary field/key mismatch: {key}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _lifetime_successful_return_onset_latency_samples(
    events: tuple[object, ...],
) -> tuple[tuple[SuccessfulReturnOnsetLatencySample, ...], int]:
    """Every valid lifetime Best/Worst sample, plus a count of episodes
    skipped because they could not support the exact certified durable
    chain (ambiguous closure identity or any other integrity violation --
    e.g. a legacy record predating the current identity contract). Reuses
    ``_successful_return_event_chain`` verbatim; no window/experiment
    boundary is applied, since lifetime scope has none."""

    by_id = {_event_id(event): event for event in events}
    episode_ids = sorted(
        {
            str(getattr(event, "episode_id", ""))
            for event in events
            if str(getattr(event, "episode_id", ""))
        }
    )
    samples: list[SuccessfulReturnOnsetLatencySample] = []
    skipped = 0
    for episode_id in episode_ids:
        episode_events = tuple(
            event for event in events if str(getattr(event, "episode_id", "")) == episode_id
        )
        returned_closes = tuple(
            event
            for event in episode_events
            if _event_name(event) == "episode_closed"
            and str(getattr(event, "reason", "")) == "RETURNED"
        )
        if not returned_closes:
            continue
        if len(returned_closes) != 1:
            skipped += 1
            continue
        try:
            chain = _successful_return_event_chain(
                episode_id, episode_events, returned_closes[0], by_id
            )
        except AnalysisIntegrityError:
            skipped += 1
            continue
        (
            _episode_created,
            opening_display,
            return_started,
            _verification_completed,
            return_verified,
            _closure_started,
            _closure_completed,
            episode_closed,
        ) = chain
        samples.append(
            SuccessfulReturnOnsetLatencySample(
                episode_id=episode_id,
                attempt_id=_event_attempt_id(return_started),
                latency_ns=_event_time(return_started) - _event_time(opening_display),
                opening_sine_display=_mirl_chain_ref(opening_display),
                successful_return_onset=_mirl_chain_ref(return_started),
                return_verified=_mirl_chain_ref(return_verified),
                episode_closed=_mirl_chain_ref(episode_closed),
                supporting_event_chain=tuple(_mirl_chain_ref(event) for event in chain),
            )
        )
    return tuple(samples), skipped


def _legacy_note(skipped: int) -> str:
    if skipped <= 0:
        return ""
    plural = "episode" if skipped == 1 else "episodes"
    return (
        f" {skipped} historical {plural} could not support the complete "
        "durable return-onset chain and were excluded."
    )


def _best_worst_return(
    *, read_mirl_events,
) -> tuple[LifetimeMetricResult, LifetimeMetricResult]:
    try:
        events = read_mirl_events()
    except Exception as exc:  # noqa: BLE001 -- reported as a card reason, never raised
        reason = f"read_error:{type(exc).__name__}"
        return (
            LifetimeMetricResult("best_return", UNAVAILABLE, None, "ns", reason),
            LifetimeMetricResult("worst_return", UNAVAILABLE, None, "ns", reason),
        )

    samples, skipped = _lifetime_successful_return_onset_latency_samples(events)
    if not samples:
        reason = (
            "no successfully closed MIRL episode in the lifetime database has "
            "a complete durable return-onset chain." + _legacy_note(skipped)
        )
        return (
            LifetimeMetricResult("best_return", UNAVAILABLE, None, "ns", reason.strip()),
            LifetimeMetricResult("worst_return", UNAVAILABLE, None, "ns", reason.strip()),
        )

    best_value = min(sample.latency_ns for sample in samples)
    worst_value = max(sample.latency_ns for sample in samples)
    count = len(samples)
    best_reason = (
        "minimum lifetime opening-SINE-display to final-successful-return-onset "
        f"latency across {count} eligible historical episode(s)." + _legacy_note(skipped)
    )
    worst_reason = (
        "maximum lifetime opening-SINE-display to final-successful-return-onset "
        f"latency across {count} eligible historical episode(s)." + _legacy_note(skipped)
    )
    return (
        LifetimeMetricResult(
            "best_return", AVAILABLE, best_value, "ns", best_reason.strip(),
            supporting_count=count,
        ),
        LifetimeMetricResult(
            "worst_return", AVAILABLE, worst_value, "ns", worst_reason.strip(),
            supporting_count=count,
        ),
    )


def _normalize_platform_key_for_display(platform_key: str) -> str:
    """Presentation-only fallback for a platform_key not found in either
    canonical label registry (Blacklist's or COSINE's). Never changes the
    stored key -- only how it is shown, e.g. ``prime_video`` -> ``Prime
    Video``."""

    parts = [part for part in platform_key.replace("-", "_").split("_") if part]
    return " ".join(part.capitalize() for part in parts) or platform_key


def _distraction_platform_label(platform_key: str) -> str:
    """Human-readable label for a certified trigger ``platform_key``.

    Reuses CORE_ENGINE.blacklist's own canonical policy registry -- the
    exact label Blacklist itself already presents for this key -- rather
    than inventing a naming scheme. A key outside that registry (e.g. a
    Resource Intent / study-context platform_key) falls back to a plain
    presentation-only normalization."""

    try:
        from CORE_ENGINE.blacklist import policy_for_key

        policy = policy_for_key(platform_key)
    except Exception:  # noqa: BLE001 -- a label lookup failure must never break the card
        policy = None
    label = str(getattr(policy, "label", "") or "") if policy is not None else ""
    return label or _normalize_platform_key_for_display(platform_key)


def _top_distraction_platform(*, read_trigger_platform_keys) -> LifetimeMetricResult:
    """TOP DISTRACTION PLATFORM = the platform_key with the greatest number
    of exact durable SINE admissions matched to lifetime trigger records
    (count of certified structured platform_key occurrences,
    never dwell time, never foreground/title inference)."""

    try:
        platform_keys = read_trigger_platform_keys()
    except Exception as exc:  # noqa: BLE001 -- reported as a card reason, never raised
        reason = f"read_error:{type(exc).__name__}"
        return LifetimeMetricResult("top_distraction_platform", UNAVAILABLE, None, "", reason)

    counts: dict[str, int] = {}
    for raw_key in platform_keys:
        key = str(raw_key or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        return LifetimeMetricResult(
            "top_distraction_platform", UNAVAILABLE, None, "",
            "no durable lifetime trigger record carries a certified "
            "structured platform_key.",
        )

    max_count = max(counts.values())
    winners = sorted(key for key, count in counts.items() if count == max_count)

    if len(winners) > 1:
        labels = ", ".join(f"{_distraction_platform_label(key)} ({max_count})" for key in winners)
        reason = (
            f"TIE: {labels} each with {max_count} valid durable lifetime "
            "distraction-trigger record(s)."
        )
        return LifetimeMetricResult(
            "top_distraction_platform", AVAILABLE, "TIE", "", reason,
            supporting_count=max_count,
        )

    winner = winners[0]
    reason = (
        "greatest number of valid durable lifetime distraction-trigger "
        f"records: {max_count} record(s) across the lifetime trigger ledger."
    )
    return LifetimeMetricResult(
        "top_distraction_platform", AVAILABLE, _distraction_platform_label(winner), "",
        reason, supporting_count=max_count,
    )


def _ott_platform_label(platform_key: str) -> str:
    """Human-readable label for a COSINE OTT platform_key, reusing COSINE's
    own canonical ``PLATFORM_LABELS`` registry (the exact label COSINE's own
    read model already presents for this key)."""

    try:
        from COSINE.cosine import PLATFORM_LABELS

        label = str(PLATFORM_LABELS.get(platform_key) or "")
    except Exception:  # noqa: BLE001 -- a label lookup failure must never break the card
        label = ""
    return label or _normalize_platform_key_for_display(platform_key)


def _format_supported_seconds(total_seconds: float) -> str:
    """Human-readable durable-time text, e.g. ``2 h 52 min 59 s`` or
    ``9 min 59 s`` or ``49 s``. Presentation only -- never changes the
    underlying certified seconds total, and (matching
    ``chapter6_view._format_latency_ns``'s own never-silently-reduce-
    precision convention) never drops a non-zero trailing unit."""

    total = max(0, int(round(total_seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} h")
    if hours or minutes:
        parts.append(f"{minutes} min")
    parts.append(f"{seconds} s")
    return " ".join(parts)


def _closed_cosine_platform_seconds(events) -> tuple[dict[str, float], int]:
    """Every CLOSED lifetime COSINE session's own certified per-platform
    supported seconds (from its one durable ``COSINE_SESSION_CLOSED``
    closure payload -- see COSINE/cosine.py's ``_closure_payload``, which
    already allocates supported seconds to each platform separately for a
    hopper/multi-platform session), summed by platform_key, plus a count of
    contributing closed sessions.

    A session/generation identity that recorded more than one closure event
    (a malformed/legacy duplicate) keeps only its first recorded closure and
    fails closed on the duplicate, rather than double-counting or aborting
    the whole lifetime read."""

    totals: dict[str, float] = {}
    seen_sessions: set[tuple[str, int]] = set()
    contributing = 0
    for event in events:
        if str(getattr(event, "event_name", "")) != "COSINE_SESSION_CLOSED":
            continue
        identity = (
            str(getattr(event, "cosine_session_id", "")),
            int(getattr(event, "generation", 0) or 0),
        )
        if identity in seen_sessions:
            continue
        seen_sessions.add(identity)
        try:
            payload = json.loads(str(getattr(event, "payload_json", "") or ""))
        except (TypeError, ValueError):
            continue
        platform_seconds = payload.get("platform_seconds") if isinstance(payload, dict) else None
        if not isinstance(platform_seconds, dict) or not platform_seconds:
            continue
        session_contributed = False
        for raw_key, raw_value in platform_seconds.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            try:
                seconds = float(raw_value)
            except (TypeError, ValueError):
                continue
            if seconds <= 0:
                continue
            totals[key] = totals.get(key, 0.0) + seconds
            session_contributed = True
        if session_contributed:
            contributing += 1
    return totals, contributing


def _top_ott_platform(*, read_cosine_events) -> LifetimeMetricResult:
    """TOP OTT PLATFORM = the OTT platform with the greatest cumulative
    durable supported time across closed lifetime COSINE history (locked
    product definition -- total supported seconds, never session starts,
    never episode counts, never transitions)."""

    try:
        events = read_cosine_events()
    except Exception as exc:  # noqa: BLE001 -- reported as a card reason, never raised
        reason = f"read_error:{type(exc).__name__}"
        return LifetimeMetricResult("top_ott_platform", UNAVAILABLE, None, "", reason)

    totals, contributing = _closed_cosine_platform_seconds(events)
    if not totals:
        return LifetimeMetricResult(
            "top_ott_platform", UNAVAILABLE, None, "",
            "no closed lifetime COSINE session carries valid durable "
            "supported platform-seconds evidence.",
        )

    max_seconds = max(totals.values())
    winners = sorted(key for key, seconds in totals.items() if seconds == max_seconds)
    duration_text = _format_supported_seconds(max_seconds)

    if len(winners) > 1:
        labels = ", ".join(f"{_ott_platform_label(key)} ({duration_text})" for key in winners)
        reason = (
            f"TIE: {labels} each with {duration_text} cumulative supported "
            "OTT time across lifetime COSINE history."
        )
        return LifetimeMetricResult(
            "top_ott_platform", AVAILABLE, "TIE", "", reason,
            supporting_count=contributing,
        )

    winner = winners[0]
    reason = (
        "highest cumulative supported OTT time across lifetime COSINE "
        f"history: {duration_text} across {contributing} contributing "
        "closed session(s)."
    )
    return LifetimeMetricResult(
        "top_ott_platform", AVAILABLE, _ott_platform_label(winner), "",
        reason, supporting_count=contributing,
    )


def build_lifetime_summary(
    *,
    read_mirl_events=None,
    read_trigger_platform_keys=None,
    read_cosine_events=None,
) -> Chapter6LifetimeSummary:
    """Read the durable MYELIN lifetime database once and build one
    immutable summary covering all four Evidence cards. Read-only: performs
    no INSERT/UPDATE/DELETE/schema change. Safe to call repeatedly; each
    call is independent and mutates nothing.

    Every ``read_*`` reader is injectable for isolated/disposable-DB testing
    (see the mandatory lifetime tests) -- production callers should leave
    them unset so the real canonical readers are used: ``read_mirl_events``
    and ``read_cosine_events`` are the same unfiltered, all-session readers
    ``read_mirl_snapshot`` and COSINE's own read model already use;
    ``read_trigger_platform_keys`` is the narrow structured-platform-key
    reader added alongside this module for TOP DISTRACTION PLATFORM.
    """

    if read_mirl_events is None:
        from PERSISTENCE.storage import read_mirl_events as _real_read_mirl_events

        read_mirl_events = _real_read_mirl_events
    if read_trigger_platform_keys is None:
        from PERSISTENCE.storage import (
            read_trigger_platform_keys as _real_read_trigger_platform_keys,
        )

        read_trigger_platform_keys = _real_read_trigger_platform_keys
    if read_cosine_events is None:
        from PERSISTENCE.storage import read_cosine_events as _real_read_cosine_events

        read_cosine_events = _real_read_cosine_events

    best_return, worst_return = _best_worst_return(read_mirl_events=read_mirl_events)
    top_distraction_platform = _top_distraction_platform(
        read_trigger_platform_keys=read_trigger_platform_keys
    )
    top_ott_platform = _top_ott_platform(read_cosine_events=read_cosine_events)

    return Chapter6LifetimeSummary(
        generated_at_utc=_utc_now(),
        best_return=best_return,
        worst_return=worst_return,
        top_distraction_platform=top_distraction_platform,
        top_ott_platform=top_ott_platform,
    )


__all__ = [
    "Chapter6LifetimeSummary",
    "LifetimeMetricResult",
    "build_lifetime_summary",
]
