"""C4.5 — W-8 Browser certified resource identity.

The producer is healthy: classify_address_value already mints distinct opaque
tokens for distinct YouTube content IDs. The lesion is solely in

    _EvidenceStabiliser._same_identity()

which compares kind / platform_key / marker and ignores resource_token, so two
different videos on the same watch route are treated as "the stable URL
evidence was observed again" and the FIRST video's token is kept for the rest
of the session.

Written before the patch.
"""

from __future__ import annotations

import time

import pytest

import _lab

from CORE_ENGINE.browser import (
    BrowserEvidenceAuthority,
    BrowserKind,
    BrowserUrlObservation,
    BrowserUrlReadStatus,
    EvidenceConfidence,
    EvidenceStabilityPolicy,
    UrlEvidenceKind,
    UrlSurfaceEvidence,
    classify_address_value,
    _EvidenceStabiliser,
)

SECRET = b"c45-identity-secret-32-bytes-xxx"

URL_A = "https://www.youtube.com/watch?v=VIDEO_AAA"
URL_B = "https://www.youtube.com/watch?v=VIDEO_BBB"


def watch(token: str, *, marker: str = "watch") -> UrlSurfaceEvidence:
    """One certified YouTube selected-video evidence with a chosen token."""

    return UrlSurfaceEvidence(
        kind=UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO,
        platform_key="youtube",
        platform_label="YouTube",
        marker=marker,
        redacted_address="youtube/watch/[redacted]",
        confidence=EvidenceConfidence.HIGH,
        reason="test evidence",
        resource_token=token,
    )


def static_entry() -> UrlSurfaceEvidence:
    """A certified route that legitimately carries no exact token."""

    return UrlSurfaceEvidence(
        kind=UrlEvidenceKind.CONFIRMED_STATIC_ENTRY,
        platform_key="instagram",
        platform_label="Instagram",
        marker="entry",
        redacted_address="instagram/entry/[redacted]",
        confidence=EvidenceConfidence.HIGH,
        reason="test evidence",
        resource_token="",
    )


def stabiliser() -> _EvidenceStabiliser:
    return _EvidenceStabiliser(EvidenceStabilityPolicy())


# ---------------------------------------------------------------------------
# PRODUCER — must already be correct before the patch
# ---------------------------------------------------------------------------


def test_producer_already_mints_distinct_tokens():
    """Should PASS before the patch. Proves the lesion is not in the producer."""

    a = classify_address_value(URL_A, identity_secret=SECRET)
    b = classify_address_value(URL_B, identity_secret=SECRET)

    assert a.kind is UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO
    assert b.kind is UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO
    assert a.resource_token and b.resource_token
    assert a.resource_token != b.resource_token
    # ... and everything the stabiliser currently compares is identical.
    assert a.kind is b.kind
    assert a.platform_key == b.platform_key
    assert a.marker == b.marker


# ---------------------------------------------------------------------------
# W8-1 .. W8-4 — the stabiliser itself
# ---------------------------------------------------------------------------


def test_w8_1_strong_a_then_strong_b_replaces_immediately():
    stab = stabiliser()
    stab.observe(watch("TOKEN-A"), 1.0)
    view = stab.observe(watch("TOKEN-B"), 2.0)

    assert view.evidence.resource_token == "TOKEN-B", (
        "a different YouTube video was treated as the same stable evidence "
        f"(kept {view.evidence.resource_token!r}). This is W-8."
    )
    assert view.holding_previous_strong_evidence is False
    assert view.consecutive_weak_samples == 0


def test_w8_2_repeated_a_remains_a():
    """Normal stable continuity must be preserved."""

    stab = stabiliser()
    first = stab.observe(watch("TOKEN-A"), 1.0)
    second = stab.observe(watch("TOKEN-A"), 2.0)

    assert first.evidence.resource_token == "TOKEN-A"
    assert second.evidence.resource_token == "TOKEN-A"
    assert second.holding_previous_strong_evidence is False
    assert second.reason == "The stable URL evidence was observed again."


def test_w8_3_token_disappearing_is_not_the_same_identity():
    """A watch route that can no longer prove a content ID is not video A."""

    stab = stabiliser()
    stab.observe(watch("TOKEN-A"), 1.0)
    view = stab.observe(watch(""), 2.0)

    assert view.evidence.resource_token == "", (
        "a route that lost its exact identity was still reported as video A"
    )


def test_w8_3b_token_appearing_is_not_the_same_identity():
    stab = stabiliser()
    stab.observe(watch(""), 1.0)
    view = stab.observe(watch("TOKEN-A"), 2.0)
    assert view.evidence.resource_token == "TOKEN-A"


def test_w8_4_non_tokenised_routes_keep_existing_behaviour():
    """The patch must not destroy stability for evidence with no exact token."""

    stab = stabiliser()
    stab.observe(static_entry(), 1.0)
    view = stab.observe(static_entry(), 2.0)

    assert view.reason == "The stable URL evidence was observed again."
    assert view.holding_previous_strong_evidence is False
    assert view.evidence.resource_token == ""


def test_w8_4b_different_marker_still_releases():
    """Pre-existing marker discrimination must survive."""

    stab = stabiliser()
    stab.observe(watch("TOKEN-A", marker="watch"), 1.0)
    view = stab.observe(watch("TOKEN-A", marker="live"), 2.0)
    assert view.evidence.marker == "live"


# ---------------------------------------------------------------------------
# WEAK-READ HOLD MUST BE UNCHANGED
# ---------------------------------------------------------------------------


def test_transient_weak_read_still_holds_the_previous_strong_evidence():
    """strong A -> weak read is NOT strong A -> strong B.

    The bounded hold protects against a momentary UIA failure and must remain.
    """

    stab = stabiliser()
    stab.observe(watch("TOKEN-A"), 1.0)

    first_weak = stab.unavailable(1.5)
    assert first_weak.holding_previous_strong_evidence is True
    assert first_weak.evidence.resource_token == "TOKEN-A"
    assert first_weak.consecutive_weak_samples == 1

    second_weak = stab.unavailable(2.0)
    assert second_weak.holding_previous_strong_evidence is True
    assert second_weak.consecutive_weak_samples == 2


def test_weak_hold_still_releases_after_the_configured_sample_count():
    stab = stabiliser()
    stab.observe(watch("TOKEN-A"), 1.0)
    stab.unavailable(1.1)
    stab.unavailable(1.2)
    released = stab.unavailable(1.3)          # release_after_weak_samples = 3
    assert released.evidence is None


def test_weak_hold_still_releases_after_the_configured_hold_seconds():
    stab = stabiliser()
    stab.observe(watch("TOKEN-A"), 1.0)
    stab.unavailable(1.1)
    released = stab.unavailable(7.0)          # maximum_hold_seconds = 5.0
    assert released.evidence is None


def test_a_strong_b_beats_a_pending_weak_hold():
    """A weak sample must not let stale A survive a real B observation."""

    stab = stabiliser()
    stab.observe(watch("TOKEN-A"), 1.0)
    held = stab.unavailable(1.5)
    assert held.evidence.resource_token == "TOKEN-A"

    view = stab.observe(watch("TOKEN-B"), 2.0)
    assert view.evidence.resource_token == "TOKEN-B"


# ---------------------------------------------------------------------------
# W8-5 .. W8-7 — black box through BrowserEvidenceAuthority
# ---------------------------------------------------------------------------


class _Foreground:
    def __init__(self, seq, title="Lecture - YouTube"):
        self.sequence = seq
        self.hwnd = 4242
        self.process_id = 9001
        self.process_name = "chrome.exe"
        self.window_title = title
        self.observed_monotonic_ns = seq * 10**9


def _authority(urls: list[str]) -> BrowserEvidenceAuthority:
    """Deterministic reader that walks a fixed URL script."""

    state = {"index": 0}

    def reader(*, hwnd, process_id, process_name, diagnostic, identity_secret):
        url = urls[min(state["index"], len(urls) - 1)]
        state["index"] += 1
        return BrowserUrlObservation(
            status=BrowserUrlReadStatus.OK,
            browser=BrowserKind.CHROME,
            browser_label="Chrome",
            process_name=process_name,
            evidence=classify_address_value(url, identity_secret=identity_secret),
            read_method="scripted",
            candidate_count=1,
            reason="scripted",
        )

    authority = BrowserEvidenceAuthority(reader=reader)
    authority.start_session()
    return authority


def test_w8_5_authority_reports_b_on_the_second_cycle():
    authority = _authority([URL_A, URL_B])

    first = authority.observe(_Foreground(1))
    second = authority.observe(_Foreground(2))

    assert first.evidence.resource_token
    assert second.evidence.resource_token != first.evidence.resource_token, (
        "BrowserEvidenceAuthority kept video A's certified token after the "
        "user moved to video B. This is W-8."
    )
    assert second.holding_previous_strong_evidence is False


def test_w8_6_autoplay_updates_identity_in_the_same_window():
    """Same HWND, same PID, same browser, same watch route -- new video."""

    authority = _authority([URL_A, URL_A, URL_B, URL_B])

    watched = authority.observe(_Foreground(1))
    authority.observe(_Foreground(2))
    autoplayed = authority.observe(_Foreground(3))

    assert autoplayed.evidence.resource_token != watched.evidence.resource_token


def test_w8_7_identical_titles_do_not_merge_identities():
    """Browser never uses the title for identity; the tokens must still differ."""

    authority = _authority([URL_A, URL_B])
    same_title = "Basal Ganglia Pathways - YouTube"

    first = authority.observe(_Foreground(1, title=same_title))
    second = authority.observe(_Foreground(2, title=same_title))

    assert first.evidence.resource_token != second.evidence.resource_token


def test_returning_to_a_is_recognised_as_a_again():
    """Identity must track the resource, not merely detect change."""

    authority = _authority([URL_A, URL_B, URL_A])

    first = authority.observe(_Foreground(1)).evidence.resource_token
    authority.observe(_Foreground(2))
    third = authority.observe(_Foreground(3)).evidence.resource_token

    assert third == first, "the same video must mint the same session token"
