"""C3.1 — harden the Study-target carrier before it acquires meaning.

Two narrow contract fixes, both in CORE_ENGINE/resource_intent.py.

C3.1-A  StudyContext must FAIL CLOSED on malformed keyword elements.
        C3 shipped ``tuple(str(value) for value in values)``, which silently
        widened the contract: StudyRuntime rejects ["dopamine", 42] via
        _clean_text ("text contract values must be strings"), but StudyContext
        turned it into ("dopamine", "42"). The carrier must not accept a
        target StudyRuntime would have refused.

C3.1-B  A change to ANY semantic Study-target fact must invalidate Resource
        Intent authority. Today only context_token, the subject/task
        fingerprint and display_state do that. keywords and important_keywords
        become BSF inputs at C4, so from now on they are target authority too.

        This is a fail-closed invariant, not a claim that StudyRuntime changes
        keywords in place. It defends against a malformed or future publisher
        that reuses a block/generation with a different target.
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import LECTURE

from CORE_ENGINE.resource_intent import (
    ResourceIntentAuthority,
    StudyContext,
)

KEYWORDS = ("dopamine", "striatum")
IMPORTANT = ("basal ganglia",)


def context(**overrides) -> StudyContext:
    base = dict(
        block_id="BLOCK-C31",
        generation=1,
        display_state="ACTIVE",
        subject="Neuroscience",
        task="Basal Ganglia",
        protection_active=True,
        planned_break_active=False,
        remaining_seconds=1800,
        published_monotonic_ns=time.monotonic_ns(),
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
    )
    base.update(overrides)
    if "display_state" in overrides:
        state = overrides["display_state"]
        base["protection_active"] = state == "ACTIVE"
        base["planned_break_active"] = state == "BREAK"
    return StudyContext(**base)


# ---------------------------------------------------------------------------
# C3.1-A — strict element typing
# ---------------------------------------------------------------------------


def test_a_integer_element_is_rejected_not_stringified():
    """The exact case Chief named: StudyRuntime refuses it, so must the carrier."""

    with pytest.raises(TypeError):
        context(keywords=["dopamine", 42])


def test_a_arbitrary_object_element_is_rejected():
    with pytest.raises(TypeError):
        context(important_keywords=[object()])


def test_a_none_element_is_rejected():
    with pytest.raises(TypeError):
        context(keywords=["dopamine", None])


def test_a_bool_element_is_rejected():
    with pytest.raises(TypeError):
        context(keywords=["dopamine", True])


def test_a_bytes_element_is_rejected():
    with pytest.raises(TypeError):
        context(keywords=["dopamine", b"striatum"])


def test_a_bare_string_is_still_rejected():
    """C3's guard against splitting into characters must survive C3.1."""

    with pytest.raises(TypeError):
        context(keywords="dopamine")
    with pytest.raises(TypeError):
        context(important_keywords=b"dopamine")


def test_a_list_of_strings_is_accepted_exactly():
    result = context(keywords=["dopamine", "striatum"])
    assert result.keywords == ("dopamine", "striatum")


def test_a_tuple_of_strings_is_accepted_exactly():
    result = context(keywords=("dopamine",))
    assert result.keywords == ("dopamine",)


def test_a_none_collection_still_means_none_declared():
    result = context(keywords=None, important_keywords=None)
    assert result.keywords == ()
    assert result.important_keywords == ()


def test_a_carrier_does_not_clean_or_normalise_elements():
    """Shape and immutability only. StudyRuntime already produced canonical
    tuples on the real path, so re-cleaning here would be a second authority."""

    result = context(keywords=["  dopamine  ", "Striatum"])
    assert result.keywords == ("  dopamine  ", "Striatum")


def test_a_matches_study_runtime_on_the_same_malformed_input():
    """Both ends of the carrier must refuse the identical target."""

    from COSECANT_STUDY_MODE.study import StudyRuntime

    malformed = ["dopamine", 42]

    with pytest.raises(TypeError):
        StudyRuntime().prepare(
            subject="Neuroscience",
            task="Basal Ganglia",
            planned_seconds=3600,
            keywords=malformed,
        )
    with pytest.raises(TypeError):
        context(keywords=malformed)


# ---------------------------------------------------------------------------
# C3.1-B — keywords are Study-target authority
# ---------------------------------------------------------------------------


@pytest.fixture()
def authority():
    intent = ResourceIntentAuthority()
    intent.start_session(profile_type="study")
    return intent


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


def _observe(intent, seq=1):
    from CORE_ENGINE.browser import BrowserEvidenceAuthority

    holder = _lab.ScriptedForegroundReader(LECTURE)
    browser = BrowserEvidenceAuthority(reader=_lab.make_browser_reader(holder))
    browser.start_session()
    foreground = _Foreground(LECTURE, seq)
    return intent.observe(
        foreground=foreground, browser_evidence=browser.observe(foreground)
    )


def _dependent_facts_present(intent) -> bool:
    return intent._latest is not None


def test_b_identical_target_is_not_an_authority_change(authority):
    authority.publish_study_context(context())
    _observe(authority, seq=1)
    assert _dependent_facts_present(authority)

    authority.publish_study_context(context())
    assert _dependent_facts_present(authority), (
        "republishing an identical target must not reset dependent facts"
    )


def test_b_changed_keywords_reset_authority(authority):
    authority.publish_study_context(context())
    _observe(authority, seq=1)
    assert _dependent_facts_present(authority)

    authority.publish_study_context(context(keywords=("dopamine", "pallidum")))

    assert not _dependent_facts_present(authority), (
        "a changed Study target must invalidate Resource Intent authority"
    )


def test_b_changed_important_keywords_reset_authority(authority):
    authority.publish_study_context(context())
    _observe(authority, seq=1)
    assert _dependent_facts_present(authority)

    authority.publish_study_context(context(important_keywords=("cerebellum",)))

    assert not _dependent_facts_present(authority)


def test_b_removing_all_keywords_resets_authority(authority):
    authority.publish_study_context(context())
    _observe(authority, seq=1)

    authority.publish_study_context(context(keywords=()))
    assert not _dependent_facts_present(authority)


def test_b_keyword_change_clears_allowance_and_dwell(authority):
    """The reset is load-bearing: prove every dependent fact is cleared."""

    authority.publish_study_context(context())
    _observe(authority, seq=1)

    now = time.monotonic_ns()
    latest = authority._latest
    assert latest is not None and latest.resource_key, "allowance path unavailable"
    assert authority.record_study_material_allowance(
        study_context_token=latest.verdict.study_context_token,
        resource_key=latest.resource_key,
        granted_monotonic_ns=now,
    ).granted
    assert authority._allowance is not None

    authority.publish_study_context(context(keywords=("dopamine", "pallidum")))

    assert authority._allowance is None, "allowance survived a target change"
    assert authority._latest is None
    assert authority._dwell_key is None
    assert authority._dwell_started_ns == -1
    assert authority._dwell_last_ns == -1


def test_b_existing_authority_rules_are_unchanged(authority):
    """ACTIVE -> BREAK and a new generation must still reset, as before C3.1."""

    authority.publish_study_context(context())
    _observe(authority, seq=1)
    assert _dependent_facts_present(authority)

    authority.publish_study_context(
        context(display_state="BREAK", published_monotonic_ns=time.monotonic_ns())
    )
    assert not _dependent_facts_present(authority), "ACTIVE -> BREAK must reset"

    authority.publish_study_context(
        context(display_state="ACTIVE", published_monotonic_ns=time.monotonic_ns())
    )
    _observe(authority, seq=2)
    assert _dependent_facts_present(authority)

    authority.publish_study_context(
        context(generation=2, published_monotonic_ns=time.monotonic_ns())
    )
    assert not _dependent_facts_present(authority), "new generation must reset"


def test_b_changed_subject_still_resets(authority):
    authority.publish_study_context(context())
    _observe(authority, seq=1)
    authority.publish_study_context(context(subject="Pharmacology"))
    assert not _dependent_facts_present(authority)


def test_b_backward_context_is_still_refused(authority):
    """C3.1 must not weaken the existing forward-only rule."""

    first = context(published_monotonic_ns=10_000)
    assert authority.publish_study_context(first)
    assert not authority.publish_study_context(
        context(published_monotonic_ns=5_000, keywords=("anything",))
    )
    assert authority._context.keywords == KEYWORDS


def test_b_no_classification_behaviour_changed(authority):
    """C3.1 is a carrier fix. It must not move any verdict."""

    from CORE_ENGINE.resource_intent import ResourceIntent

    authority.publish_study_context(context())
    snapshot = _observe(authority, seq=1)
    assert snapshot.verdict.classification is ResourceIntent.UNCERTAIN
    assert snapshot.verdict.confidence == 0.50
