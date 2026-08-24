"""C10.1 — the G < C invariant must be impossible to violate, not merely documented.

EXPECTED BEFORE C10.1: the G >= C rejection tests FAIL.
EXPECTED AFTER  C10.1: all PASS, and must stay passing forever.

C9-B froze G = 2.2 s against C = 3.0 s and the source comment calls the
relationship "load-bearing". But CosecantPolicy.__post_init__ only validated
that each value is a finite positive number. Nothing stopped a caller from
constructing a policy where the freshness tolerance equals or exceeds the
continuous-proof window.

WHY THAT IS A NUCLEUS DEFECT AND NOT A STYLE POINT
    Both runtime gates use a strict ``>`` comparison, so a gap of exactly G is
    legal. With G == C == 3.0 that means:

        presence observed at t = 0
        no evidence at all in between
        next observation at t = 3.0

    The 3.0 s gap is not a violation (3.0 > 3.0 is False), and that very same
    observation satisfies the 3-second confirmation deadline. Two isolated
    observations three seconds apart would then be indistinguishable from three
    seconds of CONTINUOUS observed presence -- which is precisely the thing the
    return proof exists to establish.

    So the real invariant is 0 < G < C, and C10.1 makes an unhealthy policy
    impossible to construct rather than merely discouraged.

These tests are pure constructor checks. No clock, no sleeps, no engine.
"""

from __future__ import annotations

import pytest

import _lab  # noqa: F401  (path + isolated storage)

from COSECANT_STUDY_MODE.cosecant import CosecantPolicy

FROZEN_G = 2.2
FROZEN_C = 3.0


# ---------------------------------------------------------------------------
# The frozen defaults must not drift
# ---------------------------------------------------------------------------


def test_production_defaults_are_the_frozen_c9b_values():
    policy = CosecantPolicy()
    assert policy.maximum_presence_gap_seconds == FROZEN_G
    assert policy.return_confirmation_seconds == FROZEN_C
    assert policy.already_over_delay_seconds == 5 * 60
    assert policy.final_lock_delay_seconds == 60


def test_the_default_policy_satisfies_its_own_invariant():
    policy = CosecantPolicy()
    assert 0 < policy.maximum_presence_gap_seconds < policy.return_confirmation_seconds


# ---------------------------------------------------------------------------
# Healthy policies must remain constructible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gap, confirmation",
    [
        (2.2, 3.0),      # the frozen production pair
        (2.999, 3.0),    # just inside the boundary
        (1.5, 3.0),      # the pre-C9 pair, still legal
        (0.5, 1.0),      # a shortened test policy
        (1.0, 60.0),     # a very wide proof window
    ],
)
def test_gap_strictly_below_confirmation_is_accepted(gap, confirmation):
    policy = CosecantPolicy(
        maximum_presence_gap_seconds=gap,
        return_confirmation_seconds=confirmation,
    )
    assert policy.maximum_presence_gap_seconds == gap
    assert policy.return_confirmation_seconds == confirmation


# ---------------------------------------------------------------------------
# The lesion: G >= C must be refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gap, confirmation",
    [
        (3.0, 3.0),      # equal -- the exact case that collapses the proof
        (3.001, 3.0),    # just beyond
        (4.0, 3.0),      # plainly beyond
        (10.0, 3.0),
        (1.0, 1.0),      # equality at a different scale
        (2.0, 1.0),
    ],
)
def test_gap_at_or_above_confirmation_is_rejected(gap, confirmation):
    with pytest.raises(ValueError) as excinfo:
        CosecantPolicy(
            maximum_presence_gap_seconds=gap,
            return_confirmation_seconds=confirmation,
        )
    message = str(excinfo.value).lower()
    assert "maximum_presence_gap_seconds" in message, (
        f"the refusal must name the offending field, got: {excinfo.value}"
    )
    assert "return_confirmation_seconds" in message, (
        f"the refusal must name what it was compared against, got: {excinfo.value}"
    )


def test_equality_is_the_boundary_case_that_matters_most():
    """G == C is the subtle one: both gates use strict >, so it looks legal.

    Spelled out separately from the parametrised sweep because this is the
    case a future reader is most likely to think is harmless.
    """

    CosecantPolicy(
        maximum_presence_gap_seconds=2.9999,
        return_confirmation_seconds=3.0,
    )  # accepted

    with pytest.raises(ValueError):
        CosecantPolicy(
            maximum_presence_gap_seconds=3.0,
            return_confirmation_seconds=3.0,
        )


# ---------------------------------------------------------------------------
# The existing validation must not be weakened by the new rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "already_over_delay_seconds",
        "final_lock_delay_seconds",
        "return_confirmation_seconds",
        "maximum_presence_gap_seconds",
    ],
)
def test_non_positive_values_are_still_rejected(field):
    for bad in (0, -1.0):
        with pytest.raises(ValueError):
            CosecantPolicy(**{field: bad})


@pytest.mark.parametrize(
    "field",
    [
        "already_over_delay_seconds",
        "final_lock_delay_seconds",
        "return_confirmation_seconds",
        "maximum_presence_gap_seconds",
    ],
)
def test_non_numeric_values_are_still_rejected(field):
    for bad in ("3", None, True):
        with pytest.raises(TypeError):
            CosecantPolicy(**{field: bad})


def test_non_finite_values_are_still_rejected():
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ValueError):
            CosecantPolicy(return_confirmation_seconds=bad)
        with pytest.raises(ValueError):
            CosecantPolicy(maximum_presence_gap_seconds=bad)


def test_the_numeric_checks_run_before_the_relational_one():
    """A non-numeric gap must raise TypeError, not the new ValueError.

    Order matters: comparing a string against a float would explode with an
    unhelpful TypeError from the comparison itself rather than the deliberate
    "must be a number" message.
    """

    with pytest.raises(TypeError):
        CosecantPolicy(maximum_presence_gap_seconds="3.0")
