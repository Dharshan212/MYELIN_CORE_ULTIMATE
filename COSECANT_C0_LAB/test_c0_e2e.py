"""C0 end-to-end guard — the whole break-return path through the real engine.

EXPECTED AT C0: FAIL.
EXPECTED AFTER C7: PASS. This is the test that defines "COSECANT is fixed".

The roadmap's C7 acceptance path, exactly:

    NO previous SINE popup
    NO "THIS IS STUDY MATERIAL" click
    NO manual allowance dependency

    user starts Study normally
        -> user starts break
        -> break target captured
        -> user browses social media
        -> escalation to FINAL_LOCK
        -> user returns to the exact intended resource
        -> 3 continuous seconds
        -> COSECANT CONFIRMED
        -> Monitor calls StudyRuntime.resume()

Everything below the scripted foreground/browser readers is the real
production engine, running on a throwaway database.

These are slow (a real break has a 60-second production minimum). Run with:
    py -3 -m pytest test_c0_e2e.py -q -m slow
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import Engine, INSTAGRAM, LECTURE, MRBEAST, OTHER_LECTURE

pytestmark = pytest.mark.slow

MIN_BREAK_SECONDS = 60      # production floor in cosecant.py
POLL = 0.25


def _state(engine) -> str:
    return engine.cosecant().state.value


def _start_study(engine) -> None:
    # C5 admits a break only from a verified STUDY_ALIGNED resource carrying an
    # exact resource token, so the journey must now declare a real Study target
    # that matches _lab.LECTURE. This makes the E2E closer to the real user
    # story rather than weaker: the break is founded on evidence.
    engine.send(
        "study_prepare",
        subject="Neuroscience",
        task="basal ganglia",
        planned_seconds=3600,
        keywords=("direct", "indirect"),
        important_keywords=("basal ganglia",),
    )
    engine.send("study_action", action="START")
    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="Study Mode to become ACTIVE",
    )


def _drive_to_final_lock(engine) -> None:
    """Start a break, wander off, and let the real escalation run."""

    engine.send("study_break", selected_break_seconds=MIN_BREAK_SECONDS)
    engine.wait_until(
        lambda: _state(engine) == "BREAK_ACTIVE",
        timeout=15,
        what="the approved break to start",
    )
    engine.look_at(INSTAGRAM)

    # fast_cosecant shortens only +5min -> 2s and +1min -> 1s.
    engine.wait_until(
        lambda: _state(engine) == "FINAL_LOCK",
        timeout=MIN_BREAK_SECONDS + 30,
        what="the escalation to reach FINAL_LOCK",
    )


@pytest.fixture()
def engine():
    with Engine(surface=LECTURE, poll_seconds=POLL, fast_cosecant=True) as running:
        yield running


# ---------------------------------------------------------------------------
# Passing at C0 — the escalation half already works
# ---------------------------------------------------------------------------


def test_escalation_reaches_final_lock_with_no_buttons(engine):
    _start_study(engine)
    _drive_to_final_lock(engine)

    snapshot = engine.cosecant()
    assert snapshot.state.value == "FINAL_LOCK"
    assert snapshot.allowed_actions == (), "FINAL_LOCK must expose no actions"
    assert snapshot.popup_must_remain_open is True
    assert snapshot.final_locked is True


def test_study_cannot_be_resumed_around_the_break(engine):
    """A UI command must not be able to escape the lock."""

    _start_study(engine)
    _drive_to_final_lock(engine)

    engine.send("study_action", action="RESUME")
    engine.send("study_action", action="COMPLETE")
    time.sleep(2.0)

    assert _state(engine) == "FINAL_LOCK", "a Study command escaped FINAL_LOCK"
    assert engine.study().state.value == "PAUSED"


def test_return_intent_button_alone_never_confirms(engine):
    """Clicking is intent. It is not evidence, and at FINAL_LOCK it is refused."""

    _start_study(engine)
    _drive_to_final_lock(engine)

    for _ in range(5):
        engine.send("cosecant_return_intent")
    time.sleep(2.0)

    assert _state(engine) == "FINAL_LOCK"
    assert engine.cosecant().return_confirmed is False


# ---------------------------------------------------------------------------
# Failing at C0 — the return half
# ---------------------------------------------------------------------------


def test_wrong_video_never_confirms_the_return(engine):
    """Passes at C0, but for the WRONG reason: nothing can confirm today.

    It must keep passing after C6/C7, when confirmation becomes possible.
    """

    _start_study(engine)
    _drive_to_final_lock(engine)

    engine.look_at(MRBEAST)
    time.sleep(4.0)
    assert _state(engine) == "FINAL_LOCK", "entertainment must never confirm a return"

    engine.look_at(OTHER_LECTURE)
    time.sleep(4.0)
    assert _state(engine) == "FINAL_LOCK", (
        "a DIFFERENT lecture is not the intended return resource"
    )


def test_returning_to_the_exact_resource_confirms_and_resumes_study(engine):
    """THE acceptance test. If this fails, COSECANT is not fixed."""

    _start_study(engine)
    _drive_to_final_lock(engine)

    engine.look_at(LECTURE)

    try:
        engine.wait_until(
            lambda: engine.cosecant().return_confirmed,
            timeout=20,
            what="the 3-second return confirmation to complete",
        )
    except AssertionError:
        snapshot = engine.cosecant()
        pytest.fail(
            "Returning to the exact intended Study resource never confirmed. "
            f"COSECANT is still {snapshot.state.value}, "
            f"confirmation_elapsed={snapshot.confirmation_elapsed_seconds}s. "
            "Blocked by W-1 (observations rejected as out of order) and "
            "W-2 (exact_resource_confirmed is always False during a break)."
        )

    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="Monitor to call StudyRuntime.resume()",
    )
