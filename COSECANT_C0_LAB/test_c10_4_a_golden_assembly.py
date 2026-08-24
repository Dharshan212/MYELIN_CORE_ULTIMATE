"""C10.4-A — the golden assembled COSECANT journey.

LAB VERIFICATION ONLY. No production file is modified.

This is the first time the COMPLETE break-return reflex is stimulated end to
end through the real assembled coordinator:

    Study ACTIVE
      -> Browser factual evidence
      -> Resource Intent STUDY_ALIGNED
      -> exact return target frozen
      -> Study PAUSED
      -> BREAK_STARTED durable
      -> BREAK_ACTIVE
      -> +600 s  BREAK_COMPLETE
      -> +900 s  BREAK_ALREADY_OVER
      -> +960 s  FINAL_LOCK
      -> exact Lecture A returns
      -> RETURN_CONFIRMING
      -> 3 s continuous proof (G = 2.2)
      -> RETURN_CONFIRMED
      -> BREAK context retired
      -> Study ACTIVE, fresh epoch

CLOCK CONTRACT -- READ BEFORE QUOTING ANY TIMING RESULT FROM THIS FILE

    The coordinator's real organ-routing path is exercised without the
    production sleep loop, by calling ``coordinator._route_context(context)``
    directly. Every MonitorContext is produced by the real Browser and
    Resource Intent pathway; no STUDY_ALIGNED or APPROVED_BREAK verdict is
    manufactured by hand.

    DETERMINISTICALLY CONTROLLED
        Study, COSECANT and SINE (injected ``monotonic_ns``)
        foreground observation timestamps (hand-stamped)

    REAL PRODUCTION CLOCKS, NOT CONTROLLED
        MIRL, Blacklist, Trigger

    This is therefore NOT a single globally deterministic clock, and nothing
    here may be cited as an absolute-timing claim about MIRL, Blacklist or
    Trigger. Only the controlled authorities carry timing assertions.

The exact G boundary (2.199 / 2.200 / 2.201) is deliberately NOT tested here.
It belongs to the controlled C10.4-B lane.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

import _lab
from _lab import INSTAGRAM, LECTURE

from COSECANT_STUDY_MODE.cosecant import (
    CosecantFactKind,
    CosecantRuntime,
    CosecantState,
)
from COSECANT_STUDY_MODE.study import StudyRuntime, StudyState
from CORE_ENGINE.resource_intent import ResourceIntent
from SINE.sine import SineAuthority

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)

BREAK_SECONDS = 600          # the canonical 10-minute break
ALREADY_OVER_AT = 900        # +5 min
FINAL_LOCK_AT = 960          # +1 min


class Clock:
    """One hand-advanced monotonic clock shared by Study, COSECANT and SINE."""

    def __init__(self, start: int) -> None:
        self.now = int(start)

    def __call__(self) -> int:
        return self.now

    def set_seconds_from(self, base: int, seconds: float) -> int:
        self.now = base + int(round(seconds * NS))
        return self.now


class Journey:
    """The real assembled nucleus, routed one hand-stamped cycle at a time."""

    def __init__(self) -> None:
        from CORE_ENGINE.monitor import WindowsMonitorCoordinator
        import queue
        import threading

        self.clock = Clock(time.monotonic_ns())
        self.reader = _lab.ScriptedForegroundReader(LECTURE)

        services = _lab.build_services(
            foreground=self.reader,
            fast_cosecant=False,   # production 10 / +5 / +1 physiology
        )
        # Give the authorities whose timing this journey asserts one shared,
        # controlled timebase. MIRL / Blacklist / Trigger keep their real
        # production clocks and carry no timing assertions here.
        services = replace(
            services,
            study=StudyRuntime(monotonic_ns=self.clock),
            cosecant=CosecantRuntime(
                context_authority=services.resource_intent,
                monotonic_ns=self.clock,
            ),
            sine=SineAuthority(storage=services.storage, monotonic_ns=self.clock),
        )
        self.services = services

        # Durability is observed, never stubbed: the real append route runs.
        self.fact_kinds: list[str] = []
        self.batches_accepted: list[bool] = []
        real_append = services.storage.append_cosecant_facts

        def append(*, session_id, facts):
            accepted = real_append(session_id=session_id, facts=facts)
            self.batches_accepted.append(bool(accepted))
            if accepted:
                for fact in facts:
                    kind = getattr(fact, "kind", None)
                    self.fact_kinds.append(str(getattr(kind, "value", kind)))
            return accepted

        services.storage.append_cosecant_facts = append

        self.coordinator = WindowsMonitorCoordinator(
            profile_type="study",
            services=services,
            foreground_reader=self.reader,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
            ready_event=threading.Event(),
            loop_stopped_event=threading.Event(),
            cleanup_complete_event=threading.Event(),
            telemetry_queue=queue.Queue(),
            command_queue=queue.Queue(),
            poll_seconds=1.5,
        )

        # A legitimate isolated LAB session identity via the real storage path.
        services.browser.start_session()
        services.resource_intent.start_session(profile_type="study")
        self.coordinator._start_session()
        assert self.coordinator.session_id, "the LAB needs a real session identity"

        self.base = self.clock.now

    # -- routing -------------------------------------------------------

    def route(self, surface, at_seconds: float):
        """One complete real Monitor cycle at a controlled instant."""

        self.clock.set_seconds_from(self.base, at_seconds)
        self.reader.set_surface(surface)
        observation = replace(
            self.reader.observe(), observed_monotonic_ns=self.clock.now
        )
        context = self.coordinator._classify_observation(observation)
        self.coordinator._route_context(context)
        self.last_context = context
        return context

    # -- views ---------------------------------------------------------

    def cosecant(self):
        return self.services.cosecant.snapshot()

    def study(self):
        return self.services.study.snapshot()

    def study_state(self) -> str:
        state = self.study().state
        return str(getattr(state, "value", state))

    def sine_is_live(self) -> bool:
        phase = self.services.sine.live_view().phase
        return str(getattr(phase, "value", phase)) in {
            "waiting_for_display",
            "active",
            "protected_red",
        }

    def ri_view(self):
        return self.services.resource_intent.live_view()


@pytest.fixture()
def journey() -> Journey:
    return Journey()


def test_golden_assembled_break_return_journey(journey: Journey):
    services = journey.services

    # ------------------------------------------------------------------
    # 1. Study ACTIVE on a genuinely certified exact resource
    # ------------------------------------------------------------------
    prepared = services.study.prepare(
        subject=SUBJECT,
        task=TASK,
        planned_seconds=3600,
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
    )
    assert getattr(prepared, "accepted", False), "study prepare failed"
    started = services.study.start()
    assert getattr(started, "accepted", False), "study start failed"

    # Classification happens in _classify_observation, which runs BEFORE
    # _route_context publishes the Study context to Resource Intent. So the
    # very first routed cycle is necessarily classified against "no active
    # study block". One warm-up cycle lets the real coordinator publish the
    # context; the journey is then asserted on genuine steady-state evidence.
    warmup = journey.route(LECTURE, 1.0)
    assert warmup.resource_intent.verdict.classification is ResourceIntent.UNCERTAIN

    context = journey.route(LECTURE, 2.0)
    assert journey.study_state() == "ACTIVE"

    verdict = context.resource_intent.verdict
    identity = verdict.resource_identity
    evidence = context.browser_evidence.evidence

    assert verdict.classification is ResourceIntent.STUDY_ALIGNED, (
        f"Lecture A must align through the real pathway, got "
        f"{verdict.classification.value}"
    )
    assert evidence.platform_key, "exact Browser platform must be non-empty"
    assert evidence.resource_token, "exact Browser resource token must be non-empty"
    assert identity.platform_key == evidence.platform_key
    assert identity.opaque_resource_token == evidence.resource_token
    assert identity.browser_evidence_certified is True

    lecture_platform = evidence.platform_key
    lecture_token = evidence.resource_token
    study_before = journey.study()
    block_id = study_before.block_id
    context_token = study_before.context_token
    epoch_before = study_before.active_epoch_monotonic_ns

    # ------------------------------------------------------------------
    # 2. Break admitted on the next factual Lecture A observation
    # ------------------------------------------------------------------
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, 3.0)

    snapshot = journey.cosecant()
    assert journey.study_state() == "PAUSED", "Study must pause before the break"
    assert snapshot.state is CosecantState.BREAK_ACTIVE

    target = snapshot.intended_return_target
    assert target is not None, "C5 must have frozen an exact return target"
    assert target.platform_key == lecture_platform
    assert target.resource_token == lecture_token
    assert target.study_context_token == context_token

    assert "BREAK_STARTED" in journey.fact_kinds
    assert all(journey.batches_accepted), (
        "every COSECANT fact batch must be durably accepted by the real route"
    )
    assert not journey.sine_is_live(), (
        "no SINE episode may own the break"
    )

    # ------------------------------------------------------------------
    # 3. Escalation, driven only by production advance() through the
    #    coordinator. A non-target surface is used so return confirmation
    #    cannot begin by accident.
    # ------------------------------------------------------------------
    # Deadlines are relative to the FACTUAL break start, which is when the
    # admission cycle ran -- not to the journey's own zero. Anchoring on
    # COSECANT's own recorded start keeps the boundaries exact.
    started_at = (snapshot.break_started_monotonic_ns - journey.base) / NS

    journey.route(INSTAGRAM, started_at + BREAK_SECONDS - 1)
    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE

    journey.route(INSTAGRAM, started_at + BREAK_SECONDS)
    assert journey.cosecant().state is CosecantState.BREAK_COMPLETE

    journey.route(INSTAGRAM, started_at + ALREADY_OVER_AT - 1)
    assert journey.cosecant().state is CosecantState.BREAK_COMPLETE

    journey.route(INSTAGRAM, started_at + ALREADY_OVER_AT)
    assert journey.cosecant().state is CosecantState.BREAK_ALREADY_OVER

    journey.route(INSTAGRAM, started_at + FINAL_LOCK_AT - 1)
    assert journey.cosecant().state is CosecantState.BREAK_ALREADY_OVER

    journey.route(INSTAGRAM, started_at + FINAL_LOCK_AT)
    locked = journey.cosecant()
    assert locked.state is CosecantState.FINAL_LOCK
    assert locked.allowed_actions == (), "FINAL_LOCK exposes no actions"
    assert locked.popup_must_remain_open is True

    escalation = [
        kind
        for kind in journey.fact_kinds
        if kind in {
            "BREAK_STARTED",
            "BREAK_COMPLETE",
            "BREAK_ALREADY_OVER",
            "FINAL_LOCKED",
        }
    ]
    assert escalation == [
        "BREAK_STARTED",
        "BREAK_COMPLETE",
        "BREAK_ALREADY_OVER",
        "FINAL_LOCKED",
    ], f"durable escalation order is wrong: {escalation}"

    # ------------------------------------------------------------------
    # 4. Return to the SAME exact Lecture A, inside the frozen G window
    # ------------------------------------------------------------------
    r = started_at + FINAL_LOCK_AT + 5.0

    journey.route(LECTURE, r)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    assert journey.cosecant().return_confirmed is False
    assert journey.study_state() == "PAUSED"

    journey.route(LECTURE, r + 1.5)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    assert journey.cosecant().return_confirmed is False

    journey.route(LECTURE, r + 3.0)
    confirmed = journey.cosecant()
    assert confirmed.state is CosecantState.CONFIRMED
    assert confirmed.return_confirmed is True

    # ------------------------------------------------------------------
    # 5. Study resumed only by that factual confirmation
    # ------------------------------------------------------------------
    study_after = journey.study()
    assert study_after.state is StudyState.ACTIVE, (
        "Study must resume after a confirmed factual return"
    )
    assert study_after.block_id == block_id, "the SAME Study block must resume"
    assert study_after.active_epoch_monotonic_ns > epoch_before, (
        "resume must open a FRESH ACTIVE epoch, not continue the old one"
    )

    # COSECANT retired its BREAK authority; Resource Intent owns an ACTIVE
    # Study context again rather than the APPROVED_BREAK one.
    final_context = journey.route(LECTURE, r + 4.5)
    final_verdict = final_context.resource_intent.verdict
    assert final_verdict.classification is not ResourceIntent.APPROVED_BREAK, (
        "the BREAK context must have been retired"
    )
    assert final_verdict.study_context_token == context_token, (
        "Resource Intent must own the SAME Study block's context again"
    )

    assert not journey.sine_is_live(), "no SINE episode may have taken the break"

    # ------------------------------------------------------------------
    # 6. The durable golden fact sequence
    # ------------------------------------------------------------------
    golden = [
        kind
        for kind in journey.fact_kinds
        if kind
        in {
            "BREAK_STARTED",
            "BREAK_COMPLETE",
            "BREAK_ALREADY_OVER",
            "FINAL_LOCKED",
            "RETURN_CONFIRMATION_STARTED",
            "RETURN_CONFIRMED",
        }
    ]
    assert golden == [
        "BREAK_STARTED",
        "BREAK_COMPLETE",
        "BREAK_ALREADY_OVER",
        "FINAL_LOCKED",
        "RETURN_CONFIRMATION_STARTED",
        "RETURN_CONFIRMED",
    ], f"golden durable order is wrong: {golden}"

    assert "RETURN_CONFIRMATION_RESTARTED" not in journey.fact_kinds, (
        "a clean journey must not restart confirmation"
    )
    assert "RETURN_CONFIRMATION_LOST" not in journey.fact_kinds, (
        "a clean journey must not lose confirmation"
    )
    assert journey.fact_kinds.count("RETURN_CONFIRMED") == 1, (
        "exactly one confirmed return may exist"
    )
    assert all(journey.batches_accepted), (
        "every fact batch must have been durably accepted"
    )
