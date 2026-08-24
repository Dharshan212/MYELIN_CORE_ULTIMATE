"""C3 — the engine-side Study-science artery.

C3 transports facts. It decides nothing. These tests prove the declared Study
target survives intact from the engine command, through StudyRuntime, to
Resource Intent -- and that nothing else moved.

    engine command  ->  StudyRuntime  ->  StudySnapshot  ->  StudyContext

Written before the production patch. Expected to fail at C3 start.
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import Engine, LECTURE, MRBEAST

from CORE_ENGINE.resource_intent import StudyContext, ResourceIntentAuthority

KEYWORDS = ("dopamine", "striatum")
IMPORTANT = ("basal ganglia",)

# C5 admits a break only from a verified STUDY_ALIGNED resource carrying an
# exact resource token. These keywords score _lab.LECTURE at 100%, so the two
# break tests below can still reach BREAK_ACTIVE.
ALIGNING_KEYWORDS = ("direct", "indirect")
ALIGNING_IMPORTANT = ("basal ganglia",)


@pytest.fixture()
def engine():
    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as running:
        yield running


def _prepare(engine, **extra):
    engine.send(
        "study_prepare",
        subject="Neuroscience",
        task="Basal Ganglia",
        planned_seconds=3600,
        **extra,
    )
    engine.wait_until(
        lambda: bool(engine.study().block_id),
        timeout=15,
        what="the Study block to be prepared",
    )
    return engine.study()


def _start(engine):
    engine.send("study_action", action="START")
    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="Study Mode to become ACTIVE",
    )


def _published_context(engine):
    return engine.services.resource_intent._context  # read-only peek


# ---------------------------------------------------------------------------
# C3.1 / C3.2 — the prepare carrier
# ---------------------------------------------------------------------------


def test_c3_1_prepare_carries_keywords_into_study_runtime(engine):
    snapshot = _prepare(engine, keywords=KEYWORDS, important_keywords=IMPORTANT)

    assert snapshot.keywords == KEYWORDS, (
        f"study_prepare dropped keywords: got {snapshot.keywords!r}"
    )
    assert snapshot.important_keywords == IMPORTANT, (
        f"study_prepare dropped important_keywords: "
        f"got {snapshot.important_keywords!r}"
    )
    assert snapshot.subject == "Neuroscience"
    assert snapshot.task == "Basal Ganglia"


def test_c3_2_legacy_payload_without_keywords_still_works(engine):
    """The current UI sends no keyword fields. That must remain valid."""

    snapshot = _prepare(engine)

    assert snapshot.block_id
    assert snapshot.keywords == ()
    assert snapshot.important_keywords == ()


def test_c3_2b_explicit_empty_and_none_are_treated_as_absent(engine):
    snapshot = _prepare(engine, keywords=(), important_keywords=None)
    assert snapshot.keywords == ()
    assert snapshot.important_keywords == ()


# ---------------------------------------------------------------------------
# C3.3 — string corruption guard
# ---------------------------------------------------------------------------


def test_c3_3_a_bare_string_is_never_split_into_characters():
    """The carrier must not reinterpret malformed intent.

    Tested directly against StudyRuntime, which owns the fail-closed rule, so
    the assertion is about the CONTRACT and not about how the engine thread
    happens to report the failure.
    """

    from COSECANT_STUDY_MODE.study import StudyRuntime

    runtime = StudyRuntime()
    with pytest.raises(TypeError):
        runtime.prepare(
            subject="Neuroscience",
            task="Basal Ganglia",
            planned_seconds=3600,
            keywords="dopamine",
        )


def test_c3_3b_study_context_also_refuses_a_bare_string():
    with pytest.raises(TypeError):
        StudyContext(
            block_id="B",
            generation=1,
            display_state="ACTIVE",
            subject="Neuroscience",
            task="Basal Ganglia",
            protection_active=True,
            planned_break_active=False,
            remaining_seconds=60,
            published_monotonic_ns=1,
            keywords="dopamine",
        )


def test_c3_3c_study_context_normalises_a_list_to_a_tuple():
    context = StudyContext(
        block_id="B",
        generation=1,
        display_state="ACTIVE",
        subject="Neuroscience",
        task="Basal Ganglia",
        protection_active=True,
        planned_break_active=False,
        remaining_seconds=60,
        published_monotonic_ns=1,
        keywords=["dopamine", "striatum"],
    )
    assert context.keywords == ("dopamine", "striatum")


# ---------------------------------------------------------------------------
# C3.4 / C3.5 — ACTIVE publication
# ---------------------------------------------------------------------------


def test_c3_4_active_context_carries_keywords(engine):
    _prepare(engine, keywords=KEYWORDS, important_keywords=IMPORTANT)
    _start(engine)
    time.sleep(1.0)

    context = _published_context(engine)
    assert context is not None, "no ACTIVE Study context was published"
    assert context.display_state == "ACTIVE"
    assert context.keywords == KEYWORDS


def test_c3_5_active_context_carries_important_keywords(engine):
    _prepare(engine, keywords=KEYWORDS, important_keywords=IMPORTANT)
    _start(engine)
    time.sleep(1.0)

    context = _published_context(engine)
    assert context.important_keywords == IMPORTANT


def test_c3_5b_published_context_matches_the_snapshot_exactly(engine):
    _prepare(engine, keywords=KEYWORDS, important_keywords=IMPORTANT)
    _start(engine)
    time.sleep(1.0)

    snapshot = engine.study()
    context = _published_context(engine)
    assert context.keywords == snapshot.keywords
    assert context.important_keywords == snapshot.important_keywords
    assert context.subject == snapshot.subject
    assert context.task == snapshot.task
    assert context.block_id == snapshot.block_id
    assert context.generation == snapshot.generation


# ---------------------------------------------------------------------------
# C3.6 — the declared target is independent of the observed resource
# ---------------------------------------------------------------------------


def test_c3_6_changing_the_foreground_never_mutates_the_study_target(engine):
    _prepare(engine, keywords=KEYWORDS, important_keywords=IMPORTANT)
    _start(engine)
    time.sleep(1.0)

    before = _published_context(engine)
    assert before.keywords == KEYWORDS

    engine.look_at(MRBEAST)
    time.sleep(1.5)
    after = _published_context(engine)

    assert after.keywords == KEYWORDS, "the declared Study target must not drift"
    assert after.important_keywords == IMPORTANT
    assert after.subject == before.subject
    assert after.task == before.task
    assert after.block_id == before.block_id
    assert after.generation == before.generation


# ---------------------------------------------------------------------------
# C3.7 / C3.8 — ACTIVE <-> BREAK ownership is untouched
# ---------------------------------------------------------------------------


def test_c3_7_pausing_retires_the_active_context(engine):
    _prepare(engine, keywords=KEYWORDS, important_keywords=IMPORTANT)
    _start(engine)
    time.sleep(1.0)
    assert _published_context(engine) is not None

    engine.send("study_action", action="PAUSE")
    engine.wait_until(
        lambda: engine.study().state.value == "PAUSED",
        timeout=15,
        what="Study Mode to pause",
    )
    time.sleep(1.0)

    assert _published_context(engine) is None, (
        "the ACTIVE Study context must retire when Study is not ACTIVE"
    )


def test_c3_8_cosecant_still_publishes_its_break_context_unmodified(engine):
    """COSECANT's BREAK context must still construct with no keywords."""

    _prepare(engine, keywords=ALIGNING_KEYWORDS,
             important_keywords=ALIGNING_IMPORTANT)
    _start(engine)
    time.sleep(1.0)

    engine.send("study_break", selected_break_seconds=60)
    engine.wait_until(
        lambda: engine.cosecant().state.value == "BREAK_ACTIVE",
        timeout=20,
        what="the approved break to start",
    )
    time.sleep(1.0)

    context = _published_context(engine)
    assert context is not None, "COSECANT must own the context slot during a break"
    assert context.display_state == "BREAK"
    assert context.planned_break_active is True
    assert context.protection_active is False
    # C3 gave the new fields safe defaults precisely so cosecant.py did not
    # have to be reopened. A BREAK context therefore carries no keywords.
    assert context.keywords == ()
    assert context.important_keywords == ()


def test_c3_8b_only_one_publisher_owns_the_context_slot(engine):
    _prepare(engine, keywords=ALIGNING_KEYWORDS,
             important_keywords=ALIGNING_IMPORTANT)
    _start(engine)
    time.sleep(1.0)
    assert _published_context(engine).display_state == "ACTIVE"

    engine.send("study_break", selected_break_seconds=60)
    engine.wait_until(
        lambda: engine.cosecant().state.value == "BREAK_ACTIVE",
        timeout=20,
        what="the approved break to start",
    )
    time.sleep(1.5)
    assert _published_context(engine).display_state == "BREAK"


# ---------------------------------------------------------------------------
# C3.9 — no scope leak into C4
# ---------------------------------------------------------------------------


def test_c3_9_resource_intent_uses_only_the_narrow_calculator_valve():
    """RETIRED C3 GUARD, now a C4 boundary test.

    At C3 this asserted Resource Intent had NOT imported the calculator, to
    catch scope leaking into C4. C4 has since landed, so the import is now
    correct. What still matters is the narrow-valve rule: Resource Intent may
    import the public ``study_evidence`` valve and nothing else. Importing the
    calculator's internals -- the scorer, the mismatch vocabulary, private
    helpers -- would recreate the coupling C2 removed.
    """

    import ast

    import CORE_ENGINE.resource_intent as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported_from_calculator: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and "study_alignment" in (
            node.module or ""
        ):
            imported_from_calculator.extend(alias.name for alias in node.names)

    assert imported_from_calculator == ["study_evidence"], (
        "Resource Intent must import only the public study_evidence valve, "
        f"but imports {imported_from_calculator}"
    )

    for banned in (
        "StudyEvidenceCalculator",
        "StudyTitleScorer",
        "BACKGROUND_MISMATCH_PENALTIES",
        "COMMON_WORDS",
        "_meaningful_tokens",
        "_build_mismatch_evidence",
    ):
        assert banned not in imported_from_calculator, (
            f"{banned} is calculator internals; use the public valve"
        )


def test_c3_9b_study_context_carries_no_decisions():
    """StudyContext must stay target + lifecycle facts, never a verdict."""

    for banned in (
        "score",
        "confidence",
        "verdict",
        "allowance",
        "browser_token",
        "resource_identity",
        "return_target",
        "sine",
        "mirl",
    ):
        assert not any(
            banned in field for field in StudyContext.__dataclass_fields__
        ), f"StudyContext must not carry {banned!r}; it is not a Study target fact"


def test_c3_9c_declared_keywords_now_change_the_verdict():
    """RETIRED C3 GUARD, inverted at C4.

    At C3 this asserted keywords could NOT move a verdict, because C3 only
    transported them. C4 made them BSF inputs, so the same comparison now
    proves the artery is actually load-bearing: identical certified evidence,
    with and without a declared target, must reach different conclusions.
    """

    from CORE_ENGINE.browser import BrowserEvidenceAuthority
    from CORE_ENGINE.resource_intent import ResourceIntent

    class _FG:
        def __init__(self, surface, seq):
            self.sequence = seq
            self.hwnd = surface.hwnd
            self.process_id = surface.process_id
            self.process_name = surface.process_name
            self.window_title = surface.title
            self.observed_monotonic_ns = time.monotonic_ns()
            self.observed_wall_time_utc = ""
            self.idle_seconds = 0.0

    def verdict_for(keywords, important):
        holder = _lab.ScriptedForegroundReader(LECTURE)
        browser = BrowserEvidenceAuthority(reader=_lab.make_browser_reader(holder))
        browser.start_session()
        intent = ResourceIntentAuthority()
        intent.start_session(profile_type="study")
        intent.publish_study_context(
            StudyContext(
                block_id="B", generation=1, display_state="ACTIVE",
                subject="Neuroscience", task="Basal Ganglia",
                protection_active=True, planned_break_active=False,
                remaining_seconds=1800, published_monotonic_ns=time.monotonic_ns(),
                keywords=keywords, important_keywords=important,
            )
        )
        foreground = _FG(LECTURE, 1)
        snapshot = intent.observe(
            foreground=foreground, browser_evidence=browser.observe(foreground)
        )
        return snapshot.verdict.classification, snapshot.verdict.confidence

    without = verdict_for((), ())
    with_keywords = verdict_for(("basal", "ganglia", "dopamine"), ("pathways",))

    assert without[0] is ResourceIntent.UNCERTAIN, (
        "no declared target still means nothing to score"
    )
    assert without[1] == 0.50, "the legacy no-keyword fallback is preserved"

    assert with_keywords[0] is ResourceIntent.STUDY_ALIGNED, (
        "a declared target matching certified evidence must now align"
    )
    assert without != with_keywords, (
        "the carrier must be load-bearing after C4"
    )
