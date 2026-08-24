"""C0 regression guard for W-8 — certified resource identity does not update.

DISCOVERED DURING C0. Not in the N0/N1 forensic report.
EXPECTED AT C0: FAIL.

CORE_ENGINE/browser.py, _EvidenceStabiliser._same_identity:

    return (
        left.kind is right.kind
        and left.platform_key == right.platform_key
        and left.marker == right.marker
    )

``resource_token`` is NOT compared. Two different YouTube videos both reduce
to kind=CONFIRMED_SELECTED_VIDEO, platform_key="youtube", marker="watch", so
the stabiliser treats the second video as "the stable URL evidence was
observed again" and keeps returning the FIRST video's resource_token for the
rest of the session.

Why this is load-bearing for COSECANT:

  * C5 binds the break-return target to a certified resource identity. If the
    token never changes, returning to ANY YouTube watch page satisfies the
    return, and "wrong lecture is not a return" is violated at the identity
    layer -- below anything cosecant.py can defend against.
  * A Study-material allowance is keyed on ResourceIdentity.stable_key, which
    mixes the token with the window title. Two videos sharing a window title
    therefore share a stable_key, and the allowance transfers between them.
    That contradicts the locked rule that approval never transfers across
    autoplay or a resource change.

NOTE ON SCOPE: browser.py is not in the roadmap's allowed surgery set and is
not in the protected set either. Chief must rule on this before C5.
"""

from __future__ import annotations

import time

import pytest

import _lab

from CORE_ENGINE.browser import BrowserEvidenceAuthority
from CORE_ENGINE.resource_intent import build_observation, build_resource_identity

VIDEO_A = _lab.Surface(
    process_name="chrome.exe",
    title="Basal Ganglia Pathways - YouTube",
    url="https://www.youtube.com/watch?v=VIDEO_AAA",
)
VIDEO_B = _lab.Surface(
    process_name="chrome.exe",
    title="Cerebellum Motor Learning - YouTube",
    url="https://www.youtube.com/watch?v=VIDEO_BBB",
)
# Same window title, different video: a title that has not repainted yet, a
# duplicate re-upload, or any generic/identical title.
VIDEO_B_SAME_TITLE = _lab.Surface(
    process_name="chrome.exe",
    title="Basal Ganglia Pathways - YouTube",
    url="https://www.youtube.com/watch?v=VIDEO_BBB",
)


class _Foreground:
    def __init__(self, surface, seq):
        self.sequence = seq
        self.hwnd = surface.hwnd
        self.process_id = surface.process_id
        self.process_name = surface.process_name
        self.window_title = surface.title
        self.observed_monotonic_ns = time.monotonic_ns()
        self.observed_wall_time_utc = ""
        self.idle_seconds = 0.0


class _Browser:
    def __init__(self, first):
        self.holder = _lab.ScriptedForegroundReader(first)
        self.authority = BrowserEvidenceAuthority(
            reader=_lab.make_browser_reader(self.holder)
        )
        self.authority.start_session()
        self.seq = 0

    def identity_for(self, surface):
        self.seq += 1
        self.holder.set_surface(surface)
        foreground = _Foreground(surface, self.seq)
        snapshot = self.authority.observe(foreground)
        return build_resource_identity(
            build_observation(foreground, snapshot, cosine_owned=False)
        )


def test_switching_video_updates_the_certified_resource_token():
    """The core defect, stated as plainly as possible."""

    browser = _Browser(VIDEO_A)
    first = browser.identity_for(VIDEO_A)
    second = browser.identity_for(VIDEO_B)

    assert first.opaque_resource_token, "precondition: video A must be certified"
    assert second.opaque_resource_token != first.opaque_resource_token, (
        "Switching YouTube videos did not change the certified resource token "
        f"({first.opaque_resource_token[:12]} was reused). "
        "_EvidenceStabiliser._same_identity ignores resource_token. This is W-8."
    )


def test_allowance_identity_cannot_transfer_between_videos():
    """stable_key must never collide across two genuinely different videos."""

    browser = _Browser(VIDEO_A)
    approved = browser.identity_for(VIDEO_A)
    other = browser.identity_for(VIDEO_B_SAME_TITLE)

    assert other.stable_key != approved.stable_key, (
        "Two different YouTube videos produced the SAME stable_key, so a "
        "Study-material allowance granted on one silently covers the other. "
        "Approval must never transfer across a resource change. This is W-8."
    )


def test_autoplay_to_a_new_video_is_a_new_identity():
    """Autoplay keeps kind/platform/marker identical -- the exact W-8 blind spot."""

    browser = _Browser(VIDEO_A)
    watched = browser.identity_for(VIDEO_A)
    autoplayed = browser.identity_for(VIDEO_B)

    assert autoplayed.opaque_resource_token != watched.opaque_resource_token, (
        "Autoplaying to the next video kept the previous certified identity. "
        "This is W-8."
    )


def test_leaving_youtube_entirely_does_release_the_identity():
    """The platform-change release path works; only same-host changes are blind.

    Passes at C0. It documents that the stabiliser is not wholly broken --
    ``_same_identity`` short-circuits correctly when platform_key differs --
    so the C-phase fix should be narrow.
    """

    browser = _Browser(VIDEO_A)
    watched = browser.identity_for(VIDEO_A)
    instagram = browser.identity_for(_lab.INSTAGRAM)

    assert instagram.platform_key == "instagram"
    assert instagram.opaque_resource_token != watched.opaque_resource_token


def test_shorts_and_watch_are_distinguished():
    """Different markers release correctly. Passes at C0."""

    browser = _Browser(VIDEO_A)
    watched = browser.identity_for(VIDEO_A)
    shorts = browser.identity_for(_lab.SHORTS)

    assert watched.surface.value == "youtube_watch"
    assert shorts.surface.value == "youtube_shorts"
