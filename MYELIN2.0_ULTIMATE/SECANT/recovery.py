"""Independent exact Study-return verification. No escalation or GUI authority.

supported_since_ns certifies the interval ending at at_ns. Missing continuity
interrupts an attempt without fabricating return-away or recovery. No sampling
frequency, classification rule or freshness timeout is invented here.
"""
from dataclasses import dataclass
from uuid import uuid4
from .read_model import ClosureProof, RecoveryPhase, RecoveryProjection, StudyScope, TimelineFact

VERIFY_NS = 10_000_000_000
CLOSURE_NS = 60_000_000_000


@dataclass(frozen=True, slots=True)
class AcceptedResourceEvidence:
    """Factual acceptance, bound to the current exact observation and episode.

    The isolated caller supplies this fact; no classifier or Study runtime is
    invoked. Registration must occur in the matching observation cycle, before
    later observations or clock advancement make that evidence stale.
    """
    episode_id: str
    scope: StudyScope
    resource_id: str
    at_ns: int
    evidence_id: str
    observation_id: str
    fresh: bool = True
    accepted_at_ns: int | None = None
    source_observation_id: str = ""
    source_request_id: str = ""
    provenance: str = "SYNTHETIC"


@dataclass(frozen=True, slots=True)
class ReturnEvidence:
    episode_id: str
    scope: StudyScope
    resource_id: str
    study_aligned: bool
    at_ns: int
    evidence_id: str
    supported_since_ns: int | None = None
    fresh: bool = True


class RecoveryAuthority:
    """One SECANT episode, constructed only after factual first display."""

    def __init__(self, episode_id: str, scope: StudyScope, founded_ns: int):
        if (not episode_id.startswith("secant-episode-") or not isinstance(scope, StudyScope)
                or type(founded_ns) is not int or founded_ns < 0):
            raise ValueError("SECANT identity, Study scope and founding time required")
        self._episode, self._scope, self._last_ns = episode_id, scope, founded_ns
        self._founded_ns = founded_ns
        self._seen: set[str] = set()
        self._phase = RecoveryPhase.IDLE
        self._attempt = ""
        self._started = self._verified = self._verification = self._closure = 0
        self._evidence: list[str] = []
        self._proof = None
        self._accepted_resources: dict[str, AcceptedResourceEvidence] = {}
        self._acceptance_ids: set[str] = set()
        self._attempt_resource = ""
        self._global_hold = ""
        self._revalidate = False

    def set_global_paused(self, hold_id: str, paused: bool, at_ns: int) -> bool:
        if not hold_id or type(at_ns) is not int or at_ns < self._last_ns:
            return False
        if paused:
            if self._global_hold and self._global_hold != hold_id:
                return False
            self._global_hold = hold_id
        else:
            if self._global_hold != hold_id:
                return False
            self._global_hold = ""
            self._revalidate = True
        self._last_ns = at_ns
        return True

    def register_accepted_resource(self, evidence: AcceptedResourceEvidence, *,
                                   current_observation: ReturnEvidence) -> bool:
        """Add an exact episode-local target without changing recovery state."""
        if not isinstance(evidence, AcceptedResourceEvidence) or not isinstance(current_observation, ReturnEvidence):
            return False
        if (self._phase is RecoveryPhase.CLOSED or evidence.fresh is not True
                or current_observation.fresh is not True
                or evidence.episode_id != self._episode or evidence.scope != self._scope
                or current_observation.episode_id != self._episode or current_observation.scope != self._scope
                or type(evidence.at_ns) is not int or evidence.at_ns < self._last_ns
                or evidence.at_ns != current_observation.at_ns
                or type(evidence.resource_id) is not str or not evidence.resource_id.strip()
                or evidence.resource_id != current_observation.resource_id
                or type(evidence.evidence_id) is not str or not evidence.evidence_id.strip()
                or evidence.evidence_id in self._acceptance_ids
                or type(evidence.observation_id) is not str or not evidence.observation_id.strip()
                or evidence.observation_id != current_observation.evidence_id):
            return False
        accepted_at = evidence.at_ns if evidence.accepted_at_ns is None else evidence.accepted_at_ns
        if (type(accepted_at) is not int or accepted_at < 0 or accepted_at > evidence.at_ns
                or (evidence.provenance == "USER_CONFIRMED_STUDY" and accepted_at < self._founded_ns)
                or (evidence.provenance != "SYNTHETIC"
                    and not (evidence.source_observation_id and evidence.source_request_id))):
            return False
        self._accepted_resources[evidence.resource_id] = evidence
        self._acceptance_ids.add(evidence.evidence_id)
        return True

    def snapshot(self) -> RecoveryProjection:
        return RecoveryProjection(self._phase, self._attempt, self._verification, self._closure, self._proof, self._global_hold, self._revalidate,
            verification_target_ns=VERIFY_NS, closure_target_ns=CLOSURE_NS)

    def interrupt(self, at_ns: int, reason: str, *, attempt_id: str) -> tuple[TimelineFact, ...]:
        """Only the exact current attempt may release its recovery hold."""
        if (type(at_ns) is not int or at_ns < self._last_ns or not attempt_id
                or attempt_id != self._attempt
                or self._phase not in {RecoveryPhase.VERIFYING, RecoveryPhase.CONFIRMING}):
            return ()
        fact = self._fact("SECANT_RECOVERY_INTERRUPTED", at_ns, reason)
        self._last_ns = at_ns
        self._phase = RecoveryPhase.IDLE
        self._attempt = ""
        self._attempt_resource = ""
        self._verification = self._closure = 0
        self._evidence = []
        return (fact,)

    def observe(self, evidence: ReturnEvidence) -> tuple[TimelineFact, ...]:
        if not isinstance(evidence, ReturnEvidence):
            raise TypeError("ReturnEvidence required")
        if (self._global_hold or evidence.episode_id != self._episode or evidence.scope != self._scope
                or type(evidence.at_ns) is not int or evidence.at_ns <= self._last_ns
                or type(evidence.resource_id) is not str or not evidence.resource_id.strip()
                or type(evidence.evidence_id) is not str or not evidence.evidence_id
                or evidence.evidence_id in self._seen or self._phase is RecoveryPhase.CLOSED):
            return ()
        now = evidence.at_ns
        continuous = type(evidence.supported_since_ns) is int and evidence.supported_since_ns == self._last_ns
        acceptance = self._accepted_resources.get(evidence.resource_id)
        target = (evidence.resource_id == self._scope.target_resource_id
                  or (acceptance is not None and (
                      evidence.at_ns > acceptance.at_ns
                      or (acceptance.provenance == "USER_CONFIRMED_STUDY"
                          and acceptance.accepted_at_ns is not None
                          and acceptance.accepted_at_ns < evidence.at_ns))))
        exact = (evidence.fresh is True and evidence.study_aligned is True and target
                 and (self._phase is RecoveryPhase.IDLE or evidence.resource_id == self._attempt_resource))
        self._seen.add(evidence.evidence_id)
        if self._revalidate:
            self._revalidate = False
            if self._phase is not RecoveryPhase.IDLE:
                if not exact:
                    return self.interrupt(now, "return_away_after_global_pause", attempt_id=self._attempt)
                self._last_ns = now
                self._evidence.append(evidence.evidence_id)
                return ()  # Revalidate exact presence without crediting the paused gap.
        if self._phase is not RecoveryPhase.IDLE and (not exact or not continuous):
            reason = "evidence_gap" if not evidence.fresh or not continuous else "return_away"
            return self.interrupt(now, reason, attempt_id=self._attempt)
        previous = self._last_ns
        self._last_ns = now
        facts = []
        if self._phase is RecoveryPhase.IDLE:
            if exact:
                self._attempt = "secant-return-" + uuid4().hex
                self._started = now
                self._attempt_resource = evidence.resource_id
                self._verification = self._closure = 0
                self._evidence = [evidence.evidence_id]
                if acceptance is not None and evidence.resource_id != self._scope.target_resource_id:
                    self._evidence.insert(0, acceptance.evidence_id)
                self._phase = RecoveryPhase.VERIFYING
                facts.append(self._fact("SECANT_RETURN_STARTED", now,
                    reason=(evidence.resource_id if evidence.resource_id != self._scope.target_resource_id else ""),
                    evidence_id=evidence.evidence_id))
            return tuple(facts)
        self._evidence.append(evidence.evidence_id)
        if self._phase is RecoveryPhase.VERIFYING:
            self._verification += now - previous
            if self._verification >= VERIFY_NS:
                self._verification = VERIFY_NS
                self._verified = now
                self._phase = RecoveryPhase.CONFIRMING
                self._closure = 0
                facts.append(self._fact("SECANT_RETURN_VERIFIED", now, evidence_id=evidence.evidence_id))
        elif self._phase is RecoveryPhase.CONFIRMING:
            self._closure += now - previous
            if self._closure >= CLOSURE_NS:
                self._closure = CLOSURE_NS
                self._phase = RecoveryPhase.CLOSED
                self._proof = ClosureProof(self._episode, self._scope, self._attempt,
                    self._started, self._verified, now, tuple(self._evidence))
                facts.append(self._fact("SECANT_RECOVERY_CLOSED", now, evidence_id=evidence.evidence_id))
        return tuple(facts)

    def _fact(self, name, at_ns, reason="", evidence_id=""):
        return TimelineFact(name, at_ns, self._episode, attempt_id=self._attempt,
                            reason=reason, evidence_id=evidence_id)
