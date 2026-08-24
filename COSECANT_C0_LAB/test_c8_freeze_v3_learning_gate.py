"""C8.2/C8.3 FREEZE CORRECTION — MIRL v3 evidence must still teach Ebbinghaus.

EXPECTED BEFORE THE CORRECTION: the v3 guard FAILS.
EXPECTED AFTER:                 all PASS, and must stay passing forever.

C8.2/C8.3 bumped MIRL's recovery-evidence generation to
``myelin-mirl-recovery-evidence-v3`` because the admissible recovery
POPULATION widened (automatic Study alignment, and Red-time recoveries). The
return-onset meaning of ``verified_recovery_elapsed_seconds`` did not change.

Monitor owns a SEPARATE literal naming the generation it can interpret for
learning. It still said v2. Monitor is deliberately built to release SINE
FIRST and check learning compatibility SECOND, so the recovery kept working
and the C8.2/C8.3 acceptance journey stayed green -- while every verified
recovery was silently dropped before Tr and lambda:

    verified recovery -> SINE released      OK
                      -> Tr / lambda        REJECTED

That silence is the whole danger: next-session Ebbinghaus adaptation would
simply have stopped learning with nothing failing loudly.

The producer/consumer independence rule is NOT relaxed here. Monitor keeps its
own literal and does not import MIRL's; a package declaring an older
generation must still be refused.
"""

from __future__ import annotations

import queue
import time
from dataclasses import replace

import pytest

from _lab import INSTAGRAM, LECTURE, QuietMonitor, SineDriver, Surface

from CORE_ENGINE.monitor import LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION
from CORE_ENGINE.resource_intent import ResourceIntent, StudyContext
from MIRL.mirl import (
    RECOVERY_EVIDENCE_SCHEMA_VERSION,
    MirlAuthority,
    MirlPolicy,
    RecoveryContext,
)

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)

HONEST_LECTURE = Surface(
    process_name="chrome.exe",
    title="Basal Ganglia Direct and Indirect Pathways - YouTube",
    url="https://www.youtube.com/watch?v=BG_LECTURE_001",
)

FAST_MIRL = MirlPolicy(
    first_display_deadline_seconds=45.0,
    return_verification_seconds=0.4,
    closure_confirmation_seconds=0.6,
    maximum_observation_gap_seconds=30.0,
)


class LearningBench:
    """A real coordinator wired for the recovery -> learning handoff."""

    def __init__(self):
        self.quiet = QuietMonitor(LECTURE)
        self.intent = self.quiet.services.resource_intent
        assert self.intent.publish_study_context(
            StudyContext(
                block_id="BLOCK-C8FREEZE",
                generation=1,
                display_state="ACTIVE",
                subject=SUBJECT,
                task=TASK,
                protection_active=True,
                planned_break_active=False,
                remaining_seconds=1800,
                published_monotonic_ns=time.monotonic_ns(),
                keywords=KEYWORDS,
                important_keywords=IMPORTANT,
            )
        )
        self.mirl = MirlAuthority(policy=FAST_MIRL)
        self.mirl.start_session(session_id=1, profile_type="study")
        # MonitorServices is a frozen dataclass, so swap in the shortened-policy
        # MIRL by rebuilding the record and re-pointing the coordinator at it.
        self.quiet.services = replace(self.quiet.services, mirl=self.mirl)
        self.quiet.coordinator.services = self.quiet.services
        self.driver = SineDriver(sine=self.quiet.services.sine, session_id=1)
        self.driver.fact_sink = self.mirl.record_sine_fact
        self.driver.mirl_token_factory = self._prepare_mirl

        # Monitor's learning path requires the session bookkeeping that run()
        # normally establishes.
        self.quiet.services.trigger.start_session(
            session_id=1, profile_type="study"
        )
        self.coordinator = self.quiet.coordinator
        self.coordinator.session_id = 1
        self.coordinator._profile_learning_key = "study"
        self.telemetry: queue.Queue = self.coordinator.telemetry_queue

    def _prepare_mirl(self, candidate, operational_event_id):
        return self.mirl.prepare_trigger(
            candidate=candidate, operational_event_id=operational_event_id
        )

    def look(self, surface):
        return self.quiet.look_at(surface)

    def feed(self, surface, *, seconds: float, step: float = 0.1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.mirl.observe(self.look(surface))
            time.sleep(step)

    def verified_package(self):
        """Run the real Red -> recovery arc and return the real v3 package."""

        self.driver.escalate_to_protected_red(self.look(INSTAGRAM))
        assert self.quiet.services.sine.protected_red_active() is True
        self.feed(HONEST_LECTURE, seconds=1.6)
        packages = tuple(self.mirl.drain_verified_recovery_evidence() or ())
        assert packages, "the lab could not produce a verified recovery package"
        return packages[0]

    def drain_telemetry(self) -> list:
        out = []
        while True:
            try:
                out.append(self.telemetry.get_nowait())
            except queue.Empty:
                return out


def _events(records, name: str) -> list:
    found = []
    for record in records:
        kind = record.get("kind") if isinstance(record, dict) else None
        if kind is None:
            kind = getattr(record, "kind", None) or getattr(record, "event", None)
        if str(kind or "") == name:
            found.append(record)
    return found


def _rejection_reasons(records) -> list:
    reasons = []
    for record in _events(records, "profile_learning_evidence_rejected"):
        payload = record if isinstance(record, dict) else getattr(record, "__dict__", {})
        reasons.append(str(payload.get("reason", "")))
    return reasons


# ---------------------------------------------------------------------------
# The provenance contract itself
# ---------------------------------------------------------------------------


def test_monitor_learning_generation_matches_what_mirl_emits():
    """The consumer must have reviewed and accepted the producer's generation.

    Monitor keeps its OWN literal on purpose -- this asserts the two agree, it
    does not make monitor import MIRL's constant.
    """

    assert LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION == (
        RECOVERY_EVIDENCE_SCHEMA_VERSION
    ), (
        "MIRL emits "
        f"{RECOVERY_EVIDENCE_SCHEMA_VERSION!r} but Monitor will only learn from "
        f"{LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION!r}, so every verified "
        "recovery releases SINE and is then silently dropped before Tr and "
        "lambda."
    )


# ---------------------------------------------------------------------------
# The regression guard: a real v3 package must reach the learning path
# ---------------------------------------------------------------------------


def test_real_v3_package_passes_the_learning_generation_gate():
    bench = LearningBench()
    package = bench.verified_package()

    assert str(package.schema_version) == RECOVERY_EVIDENCE_SCHEMA_VERSION
    assert float(package.verified_recovery_elapsed_seconds) > 0.0

    # Release first (frozen monitor ordering), then learning compatibility.
    released = bench.quiet.services.sine.confirm_verified_return(
        candidate_uid=str(package.candidate_uid),
        verified_monotonic_ns=int(package.return_verified_monotonic_ns),
        evidence_source="mirl",
    )
    assert released is True
    bench.drain_telemetry()

    # Re-queue the same real package for monitor's learning collector.
    bench.mirl._verified_recovery_outbox.append(package)

    # Reaching estimate_observed_lambda is the proof the gate was passed: this
    # candidate was never durably admitted through Trigger, so the estimator
    # legitimately refuses it and monitor raises its documented error. Before
    # the correction the version gate fired FIRST and monitor returned quietly
    # without ever consulting Trigger.
    with pytest.raises(RuntimeError) as excinfo:
        bench.coordinator._collect_verified_recovery_learning()

    assert "durably admitted trigger" in str(excinfo.value), (
        f"expected the estimator to be reached, got: {excinfo.value}"
    )

    reasons = _rejection_reasons(bench.drain_telemetry())
    assert "incompatible_mirl_recovery_evidence_version" not in reasons, (
        "Monitor rejected a current MIRL v3 recovery package for learning, so "
        "no Tr or lambda sample was taken. This is the freeze-correction "
        "lesion."
    )


# ---------------------------------------------------------------------------
# Negative control: producer/consumer independence is preserved
# ---------------------------------------------------------------------------


def test_older_generation_package_still_cannot_teach():
    """A v2-declaring package may be factual, but must not teach a v3 monitor."""

    bench = LearningBench()
    package = bench.verified_package()
    stale = replace(package, schema_version="myelin-mirl-recovery-evidence-v2")

    bench.drain_telemetry()
    bench.mirl._verified_recovery_outbox.append(stale)

    # No raise: the gate refuses it and continues, exactly as before.
    bench.coordinator._collect_verified_recovery_learning()

    reasons = _rejection_reasons(bench.drain_telemetry())
    assert "incompatible_mirl_recovery_evidence_version" in reasons, (
        "an older recovery-evidence generation was allowed into the v3 "
        "learning path; producer/consumer independence has been lost"
    )
