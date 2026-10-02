"""Isolated SECANT admission and escalation authority.

Single serialized owner; inputs are immutable factual values with monotonic
nanoseconds. No sensing, classification, background clock, GUI, persistence,
Study/RI/COSECANT adapter, Monitor connection or Normal-world dependency.
"""
from dataclasses import dataclass
from enum import Enum
from uuid import uuid4
from .popup import Action, PopupReceipt, PopupRequest, presentation
from .read_model import FoundingSourceEvidence, BreakPauseProjection, PresentationLifecycle, EpisodeProjection, RecoveryPhase, RecoveryProjection, SecantProjection, Stage, StudyScope, TimelineFact
from .recovery import AcceptedResourceEvidence, RecoveryAuthority, ReturnEvidence, VERIFY_NS, CLOSURE_NS

DWELL_NS = 300_000_000_000
STAGE_2_NS = 600_000_000_000
STAGE_3_NS = 795_000_000_000


class Meaning(str, Enum):
    OFF_TASK = "OFF_TASK"
    STUDY_ALIGNED = "STUDY_ALIGNED"
    UNCERTAIN = "UNCERTAIN"
    ACTIVITY = "ACTIVITY"


class Territory(str, Enum):
    ORDINARY = "ORDINARY"
    VIDEO = "VIDEO"
    SHORT_VIDEO = "SHORT_VIDEO"
    MESSAGING = "MESSAGING"
    SOCIAL = "SOCIAL"
    GAMING = "GAMING"


@dataclass(frozen=True, slots=True)
class StudyEvidence:
    scope: StudyScope
    resource_id: str
    meaning: Meaning
    at_ns: int
    evidence_id: str
    territory: Territory = Territory.ORDINARY
    confirmed_off_task: bool = False
    certified_ott: bool = False
    supported_since_ns: int | None = None
    fresh: bool = True
    acceptance: AcceptedResourceEvidence | None = None
    founding_source: FoundingSourceEvidence | None = None

    def __post_init__(self):
        source = self.founding_source
        if source is not None and (not isinstance(source, FoundingSourceEvidence)
                or source.resource.key != self.resource_id or source.evidence_id != self.evidence_id
                or source.observed_monotonic_ns != self.at_ns or source.meaning != self.meaning.value
                or source.territory != self.territory.value
                or source.confirmed_off_task != self.confirmed_off_task
                or source.certified_ott != self.certified_ott):
            raise ValueError("Source must describe this exact SECANT input")


@dataclass(frozen=True, slots=True)
class ReturnActionResult:
    request_id: str
    display_id: str
    action_sequence: int
    episode_id: str
    accepted: bool
    at_ns: int


class SecantAuthority:
    def __init__(self):
        self._scope = None
        self._retired: set[StudyScope] = set()
        self._last_ns = -1
        self._observation_ns = None
        self._latest_observation = None
        self._seen: set[str] = set()
        self._qualifying = False
        self._dwell = 0
        self._episode = ""
        self._stage = Stage.NONE
        self._founded = 0
        self._deadline = None
        self._remaining = None
        self._holds: set[str] = set()
        self._break_id = ""
        self._seen_breaks: set[str] = set()
        self._request = None
        self._pending_founding_source = None
        self._pending_founding_request_id = ""
        self._popup_state = "EMPTY"
        self._action_sent = False
        self._recovery = None
        self._terminal = ""
        self._facts: list[TimelineFact] = []
        self._outbox: list[TimelineFact | PopupRequest] = []
        self._completed: list[EpisodeProjection] = []
        self._display_id = ""
        self._receipt_sequence = 0
        self._receipt_ns = self._delivery_ns = 0
        self._protocol = ""
        self._receipt_buffer = {}
        self._unresolved_display = False
        self._deferred = []
        self._deferred_ids = set()
        self._ingress_ns = -1
        self._replaying = False
        self._reset_waiting = False
        self._uncertainty_id = ""
        self._global_id = ""
        self._resources = ()
        self._committed_break_id = ""
        self._revalidate_dwell = False
        self._action_sequence = 0
        self._return_action_results = []
        self._return_withdrawn_stage = Stage.NONE
        self._return_close_retry = False
        self._post_break_evidence_after = None

    def _time_valid(self, at_ns):
        floor = self._last_ns if self._replaying else max(self._last_ns, self._ingress_ns)
        return type(at_ns) is int and at_ns >= 0 and at_ns >= floor

    def open_scope(self, scope: StudyScope, at_ns: int) -> bool:
        """Isolated admission context; does not start or call Study runtime."""
        if (not isinstance(scope, StudyScope) or self._scope is not None or scope in self._retired
                or not self._time_valid(at_ns)
                or self._popup_state in {"REQUESTED", "DISPLAYED", "CLOSE_REQUESTED"}):
            return False
        self._scope = scope
        self._last_ns = at_ns
        self._reset_episode()
        self._fact("SECANT_SCOPE_OPENED", at_ns)
        return True

    def _reset_episode(self):
        self._return_withdrawn_stage = Stage.NONE
        self._return_close_retry = False
        self._post_break_evidence_after = None
        self._episode, self._stage, self._terminal = "", Stage.NONE, ""
        self._founded = self._dwell = 0
        self._deadline = self._remaining = None
        self._holds.clear()
        self._break_id = ""
        self._request, self._popup_state = None, "EMPTY"
        self._pending_founding_source = None
        self._pending_founding_request_id = ""
        self._recovery = None
        self._qualifying = False
        self._observation_ns = None
        self._latest_observation = None
        self._facts = []
        self._display_id = ""
        self._receipt_sequence = 0
        self._receipt_ns = self._delivery_ns = 0
        self._protocol = ""
        self._receipt_buffer.clear()
        self._unresolved_display = False
        self._deferred.clear()
        self._deferred_ids.clear()
        self._ingress_ns = self._last_ns
        self._reset_waiting = False
        self._uncertainty_id = self._global_id = self._committed_break_id = ""
        self._revalidate_dwell = False
        self._action_sequence = 0

    def register_accepted_resource(self, evidence: AcceptedResourceEvidence) -> bool:
        """Register factual Study-material acceptance; never imply recovery.

        The evidence must match the current observation cycle exactly. A future
        adapter supplies acceptance only after the user's choice was accepted;
        this isolated boundary does not call Resource Intent or Study Mode.
        """
        current = self._latest_observation
        if (self._unresolved_display or not isinstance(evidence, AcceptedResourceEvidence) or current is None
                or not self._episode or self._terminal or self._scope is None or self._break_id
                or evidence.episode_id != self._episode or evidence.scope != self._scope
                or evidence.at_ns != self._last_ns or evidence.at_ns != current.at_ns):
            return False
        observation = ReturnEvidence(self._episode, current.scope, current.resource_id,
            current.meaning is Meaning.STUDY_ALIGNED, current.at_ns, current.evidence_id,
            current.supported_since_ns, current.fresh)
        if not self._recovery.register_accepted_resource(evidence, current_observation=observation):
            return False
        self._fact("SECANT_RESOURCE_ACCEPTED", evidence.at_ns,
                   reason=evidence.resource_id, evidence_id=evidence.evidence_id)
        return True

    def observe(self, evidence: StudyEvidence) -> bool:
        if not isinstance(evidence, StudyEvidence):
            raise TypeError("StudyEvidence required")
        if (self._scope is None or evidence.scope != self._scope or not isinstance(evidence.meaning, Meaning)
                or not self._time_valid(evidence.at_ns) or not evidence.resource_id
                or type(evidence.evidence_id) is not str or not evidence.evidence_id
                or evidence.evidence_id in self._seen or evidence.evidence_id in self._deferred_ids
                or (self._observation_ns is not None and evidence.at_ns <= self._observation_ns)):
            return False
        now = evidence.at_ns
        if (self._post_break_evidence_after is not None
                and now <= self._post_break_evidence_after):
            return False  # The confirming break sample is not post-break evidence.
        if self._global_id:
            return False
        if self._unresolved_display and not self._replaying:
            if any(kind == "observe" and value.at_ns >= now for kind, value in self._deferred):
                return False
            self._deferred_ids.add(evidence.evidence_id)
            self._defer("observe", evidence, now)
            if evidence.meaning is not Meaning.OFF_TASK or not evidence.fresh:
                self._close_popup(now, "unresolved_display_evidence_changed")
            return True
        if self._terminal:
            # Retain the exact old request until its factual closure arrives.
            # A new dwell must not orphan a still-visible terminal surface.
            if self._popup_state in {"REQUESTED", "DISPLAYED", "CLOSE_REQUESTED"}:
                return False
            self._reset_episode()
        previous = self._observation_ns
        resumed_dwell = self._revalidate_dwell
        self._revalidate_dwell = False
        continuous = type(evidence.supported_since_ns) is int and evidence.supported_since_ns == previous
        self._seen.add(evidence.evidence_id)
        self._observation_ns = now
        self._latest_observation = evidence
        self._last_ns = now
        # Classification is input; admission remains SECANT's responsibility.
        founding_territory = (
            isinstance(evidence.territory, Territory) and evidence.territory is not Territory.ORDINARY
        ) or evidence.confirmed_off_task is True or evidence.certified_ott is True
        qualifies = (evidence.fresh is True and evidence.meaning is Meaning.OFF_TASK
                     and founding_territory)
        if not self._episode:
            if resumed_dwell and qualifies and self._qualifying:
                pass  # First fresh sample revalidates; no paused interval credit.
            elif qualifies and self._qualifying and continuous:
                self._dwell = min(DWELL_NS, self._dwell + now - previous)
            else:
                self._dwell = 0
            self._qualifying = qualifies
            if not qualifies:
                self._close_popup(now, "founding_evidence_lost")
            elif self._dwell >= DWELL_NS:
                self._request_stage(Stage.SECANT_1, now)
            return True
        # A break grant is separate factual ownership; evidence cannot release it.
        if self._break_id:
            return True
        uncertain = evidence.meaning is Meaning.UNCERTAIN or evidence.fresh is not True
        if uncertain:
            if not self._uncertainty_id:
                self._uncertainty_id = "secant-uncertainty-" + uuid4().hex
            self._hold("uncertainty", now)
            self._close_popup(now, "uncertainty")
            self._interrupt_recovery(now, "uncertainty")
            return True
        # Register the original human fact together with the fresh exact
        # observation, before releasing uncertainty or advancing presentation.
        # Separate observe/register calls could reopen a withdrawn popup.
        if evidence.acceptance is not None:
            self.register_accepted_resource(evidence.acceptance)
        if evidence.meaning is Meaning.OFF_TASK:
            self._post_break_evidence_after = None
        self._release("uncertainty", now)
        self._uncertainty_id = ""
        # Recovery owns exact planned/accepted-target matching. Classification
        # alone still cannot qualify an arbitrary resource.
        aligned = evidence.meaning is Meaning.STUDY_ALIGNED
        facts = self._recovery.observe(ReturnEvidence(self._episode, self._scope,
            evidence.resource_id, aligned, now, evidence.evidence_id, evidence.supported_since_ns, evidence.fresh))
        for fact in facts:
            self._facts.append(fact)
            self._outbox.append(fact)
            if fact.name == "SECANT_RETURN_STARTED":
                self._post_break_evidence_after = None
                self._hold("recovery", now)
            elif fact.name == "SECANT_RETURN_VERIFIED":
                self._close_popup(now, "verified_entry")
            elif fact.name == "SECANT_RECOVERY_INTERRUPTED":
                self._release("recovery", now)
            elif fact.name == "SECANT_RECOVERY_CLOSED":
                self._finish(now, "recovered")
        self.advance(now)
        return True

    def advance(self, at_ns: int) -> bool:
        """Escalation only; elapsed wall time cannot prove recovery or founding."""
        if not self._time_valid(at_ns):
            return False
        if self._unresolved_display and not self._replaying:
            self._defer("advance", at_ns, at_ns)
            return True
        self._last_ns = at_ns
        if self._return_close_retry and self._popup_state == "CLOSE_REQUESTED":
            self._return_close_retry = False
            self._fact("SECANT_POPUP_CLOSE_REQUESTED", at_ns,
                request_id=self._request.request_id, reason="return_close_retry")
        if (not self._episode or self._terminal or self._holds
                or self._post_break_evidence_after is not None):
            return True
        if self._deadline is not None and at_ns >= self._deadline:
            self._request_stage(Stage(self._stage + 1), at_ns)
        elif (self._popup_state in {"EMPTY", "CLOSED", "FAILED"}
                and self._return_withdrawn_stage != self._stage):
            self._request_stage(self._stage, at_ns)
        return True

    def _hold(self, reason, now):
        if reason in self._holds:
            return
        if not self._holds:
            self._remaining = None if self._deadline is None else max(0, self._deadline - now)
            self._deadline = None
        self._holds.add(reason)
        # Undisplayed next-stage requests must not appear after a freeze began.
        if self._popup_state == "REQUESTED":
            self._close_popup(now, reason)
        self._fact("SECANT_FROZEN", now, reason=reason)

    def _release(self, reason, now):
        if reason not in self._holds:
            return
        self._holds.remove(reason)
        if not self._holds:
            self._deadline = None if self._remaining is None else now + self._remaining
            self._remaining = None
        self._fact("SECANT_RESUMED", now, reason=reason)

    def _interrupt_recovery(self, now, reason):
        if self._recovery:
            current = self._recovery.snapshot()
            for fact in self._recovery.interrupt(now, reason, attempt_id=current.attempt_id):
                self._facts.append(fact)
                self._outbox.append(fact)
            self._release("recovery", now)

    def yield_break(self, scope: StudyScope, episode_id: str, break_id: str, at_ns: int) -> bool:
        """Consume a synthetic grant only; never call or start COSECANT."""
        if (self._unresolved_display or scope != self._scope or episode_id != self._episode or not self._episode or self._terminal
                or self._stage is not Stage.SECANT_1
                or type(break_id) is not str or not break_id or break_id in self._seen_breaks
                or self._break_id or not self._time_valid(at_ns)):
            return False
        self._last_ns = at_ns
        self._hold("break", at_ns)
        self._interrupt_recovery(at_ns, "break_yield")
        self._break_id = break_id
        self._seen_breaks.add(break_id)
        self._close_popup(at_ns, "break_yield")
        self._fact("SECANT_BREAK_YIELDED", at_ns, reason=break_id)
        return True

    def release_break(self, scope: StudyScope, episode_id: str, break_id: str, at_ns: int) -> bool:
        if (scope != self._scope or episode_id != self._episode or not break_id
                or break_id != self._break_id or not self._time_valid(at_ns) or self._terminal):
            return False
        self._last_ns = at_ns
        # Committed COSECANT return awaits new evidence; an uncommitted
        # reservation abort retains its existing presentation/re-arm path.
        if self._committed_break_id:
            self._post_break_evidence_after = at_ns
        self._break_id = ""
        self._committed_break_id = ""
        self._release("break", at_ns)
        self._fact("SECANT_BREAK_RELEASED", at_ns, reason=break_id)
        self.advance(at_ns)
        return True

    def complete(self, scope: StudyScope, at_ns: int, reason: str = "study_complete") -> bool:
        if scope != self._scope or self._scope is None or not self._time_valid(at_ns):
            return False
        if reason not in {"study_complete", "emergency", "session_end"}:
            return False
        if self._unresolved_display and not self._replaying:
            self._defer("complete", (scope, at_ns, reason), at_ns)
            self._close_popup(at_ns, reason)
            return True  # Accepted intent; projection remains unresolved until GUI truth.
        self._last_ns = at_ns
        self._interrupt_recovery(at_ns, reason)
        self._close_popup(at_ns, reason)
        if self._episode and not self._terminal:
            self._finish(at_ns, reason)
        self._retired.add(scope)
        self._scope = None
        self._qualifying = False
        self._dwell = 0
        return True

    def _finish(self, now, reason):
        self._terminal = reason
        self._deadline = self._remaining = None
        self._holds.clear()
        self._break_id = ""
        self._global_id = self._uncertainty_id = self._committed_break_id = ""
        self._close_popup(now, reason)
        self._fact("SECANT_EPISODE_CLOSED", now, reason=reason)
        self._completed.append(EpisodeProjection(self._episode, self._scope, self._stage,
            self._founded, now, reason, self._recovery.snapshot(), tuple(self._facts)))
        self._dwell = 0
        self._qualifying = False

    def _request_stage(self, stage, now):
        if self._replaying or self._reset_waiting or self._scope is None or self._holds or self._terminal:
            return
        if self._popup_state in {"REQUESTED", "DISPLAYED", "CLOSE_REQUESTED"}:
            if self._request.stage != stage:
                self._close_popup(now, "stage_transition")
            return  # New surface waits for factual old-window closure.
        request = PopupRequest("secant-popup-" + uuid4().hex, self._scope, self._episode, stage, now)
        self._request, self._popup_state = request, "REQUESTED"
        # Freeze only after admission actually creates this request. Deferred
        # observations and cancellation intent cannot replace its source.
        self._pending_founding_request_id = request.request_id
        current = self._latest_observation
        self._pending_founding_source = (current.founding_source
            if stage is Stage.SECANT_1 and not self._episode and current is not None
            and current.fresh and current.meaning is Meaning.OFF_TASK else None)
        self._action_sent = False
        self._display_id = ""
        self._receipt_sequence = 0
        self._receipt_ns = self._delivery_ns = 0
        self._protocol = ""
        self._receipt_buffer.clear()
        self._unresolved_display = True
        self._outbox.append(request)
        self._fact("SECANT_POPUP_REQUESTED", now, request_id=request.request_id)

    def _take_founding_source(self, request_id):
        source = (self._pending_founding_source
            if request_id == self._pending_founding_request_id else None)
        self._pending_founding_source = None
        self._pending_founding_request_id = ""
        return source

    def _close_popup(self, now, reason):
        if self._request and self._popup_state in {"REQUESTED", "DISPLAYED"}:
            self._popup_state = "CLOSE_REQUESTED"
            self._fact("SECANT_POPUP_CLOSE_REQUESTED", now, request_id=self._request.request_id, reason=reason)

    def _legacy_receipt(self, receipt: PopupReceipt) -> bool:
        request = self._request
        if (not isinstance(receipt, PopupReceipt) or request is None or receipt.request_id != request.request_id
                or receipt.scope != request.scope or not self._time_valid(receipt.at_ns)
                or receipt.at_ns < request.at_ns):
            return False
        now = receipt.at_ns
        if receipt.kind == "DISPLAYED":
            if self._popup_state != "REQUESTED" or self._holds or self._terminal or self._scope != request.scope:
                return False
            if not self._episode:
                if request.stage is not Stage.SECANT_1 or not self._qualifying or self._dwell < DWELL_NS:
                    return False
                self._episode = "secant-episode-" + uuid4().hex
                self._founded = now
                self._recovery = RecoveryAuthority(self._episode, self._scope, now)
                self._fact("SECANT_EPISODE_FOUNDED", now, request_id=request.request_id,
                    founding_source=self._take_founding_source(request.request_id))
            if request.stage != self._stage:
                self._stage = request.stage
                delay = {Stage.SECANT_1: STAGE_2_NS, Stage.SECANT_2: STAGE_3_NS}.get(self._stage)
                self._deadline = None if delay is None else now + delay
            self._popup_state = "DISPLAYED"
            self._fact("SECANT_DISPLAYED", now, request_id=request.request_id)
        elif receipt.kind == "CLOSED":
            if self._popup_state not in {"DISPLAYED", "CLOSE_REQUESTED"}:
                return False
            self._popup_state = "CLOSED"
            self._return_close_retry = False
            self._fact("SECANT_POPUP_CLOSED", now, request_id=request.request_id)
        elif receipt.kind == "FAILED":
            if self._popup_state != "REQUESTED":
                return False
            self._popup_state = "FAILED"
            self._take_founding_source(request.request_id)
            self._fact("SECANT_DELIVERY_FAILED", now, request_id=request.request_id, reason=receipt.detail)
        elif receipt.kind == "CLOSE_FAILED":
            if self._popup_state != "CLOSE_REQUESTED":
                return False
            self._fact("SECANT_CLOSE_FAILED", now, request_id=request.request_id, reason=receipt.detail)
            self._return_close_retry = (self._return_withdrawn_stage is not Stage.NONE
                and self._return_withdrawn_stage == self._stage)
        elif receipt.kind == "ACTION":
            if (self._popup_state != "DISPLAYED" or self._holds or self._terminal or self._action_sent
                    or not isinstance(receipt.action, Action) or receipt.action not in presentation(self._stage).actions):
                self._return_action_result(receipt, False)
                return False
            self._action_sent = True
            self._fact("SECANT_ACTION_INTENT", now, request_id=request.request_id, reason=receipt.action.value)
            self._return_action_result(receipt, True)
            # Intent is not recovery, break grant or episode closure.
        else:
            return False
        self._last_ns = now
        return True

    def _return_action_result(self, receipt, accepted):
        if receipt.action is not Action.RETURN_TO_STUDY:
            return
        self._return_action_results.append(ReturnActionResult(
            receipt.request_id, receipt.display_id, receipt.sequence,
            self._episode, accepted, receipt.at_ns))
        if accepted:
            # Withdraw this stage's surface, not its episode or running clock.
            self._return_withdrawn_stage = self._stage
            self._close_popup(receipt.at_ns, "return_to_study")

    def drain_return_action_results(self):
        results = tuple(self._return_action_results)
        self._return_action_results.clear()
        return results

    def _fact(self, name, now, **fields):
        fact = TimelineFact(name, now, self._episode, self._stage, **fields)
        self._facts.append(fact)
        self._outbox.append(fact)

    def drain(self) -> tuple[TimelineFact | PopupRequest, ...]:
        output = tuple(self._outbox)
        self._outbox.clear()
        return output

    def snapshot(self) -> SecantProjection:
        remaining = self._remaining if self._holds else (
            None if self._deadline is None else max(0, self._deadline - self._last_ns))
        return SecantProjection(self._scope, self._episode, self._stage, self._dwell, remaining,
            tuple(sorted(self._holds)), self._request.request_id if self._request else "",
            self._popup_state, self._request.stage if self._request else Stage.NONE,
            self._recovery.snapshot() if self._recovery else RecoveryProjection(
                verification_target_ns=VERIFY_NS, closure_target_ns=CLOSURE_NS), self._terminal,
            tuple(self._facts), tuple(self._completed),
            PresentationLifecycle(self._request.request_id if self._request else "",
                self._display_id, self._receipt_sequence, self._receipt_ns, self._delivery_ns,
                self._unresolved_display, tuple(sorted(self._receipt_buffer)),
                len(self._deferred), self._reset_waiting), self._resources, self._uncertainty_id,
            BreakPauseProjection(self._break_id, self._committed_break_id,
                "COMMITTED" if self._committed_break_id else "HELD" if self._break_id else "IDLE"),
            self._global_id, self._unresolved_display or self._popup_state == "CLOSE_REQUESTED",
            dwell_active=bool(self._qualifying and not self._episode and not self._terminal),
            dwell_target_ns=DWELL_NS,
            escalation_deadline_monotonic_ns=self._deadline if not self._holds else None)

    def _defer(self, kind, value, at_ns):
        self._deferred.append((kind, value))
        self._ingress_ns = at_ns

    @staticmethod
    def _operation_time(kind, value):
        if kind == "global":
            return value[2]
        return value.at_ns if kind == "observe" else value[1] if kind == "complete" else value

    def _replay_deferred(self, *, before_ns=None):
        """Replay factual samples against display occurrence, not delivery time.

        A COMPLETE received while display is unresolved is an intent. Its
        finalization waits for presentation truth, even if its request was earlier.
        """
        ready, waiting = [], []
        for kind, value in self._deferred:
            if before_ns is None or (kind != "complete" and self._operation_time(kind, value) < before_ns):
                ready.append((kind, value))
            else:
                waiting.append((kind, value))
        self._deferred = waiting
        self._replaying = True
        try:
            for kind, value in ready:
                if kind == "observe":
                    self._deferred_ids.discard(value.evidence_id)
                    self.observe(value)
                elif kind == "advance":
                    self.advance(value)
                elif kind == "global":
                    self.set_global_paused(*value)
                else:
                    scope, at_ns, reason = value
                    self.complete(scope, max(at_ns, self._last_ns), reason)
        finally:
            self._replaying = False

    def reset_pre_episode(self, scope: StudyScope, at_ns: int) -> bool:
        """False means no reset/grant: retry only after factual presentation truth.

        CLOSED with no display or FAILED permits the no-episode branch. A real
        DISPLAYED founds an episode and permanently rules out that branch for it.
        """
        if scope != self._scope or self._scope is None or self._episode or not self._time_valid(at_ns):
            return False
        if self._unresolved_display or self._popup_state in {"REQUESTED", "DISPLAYED", "CLOSE_REQUESTED"}:
            self._reset_waiting = True
            self._close_popup(at_ns, "pre_episode_break_waiting_for_display_truth")
            if self._unresolved_display:
                self._defer("advance", at_ns, at_ns)
            else:
                self._ingress_ns = max(self._ingress_ns, at_ns)
            return False
        self._last_ns = at_ns
        self._dwell = 0
        self._qualifying = False
        self._observation_ns = None
        self._latest_observation = None
        self._reset_waiting = False
        self._fact("SECANT_PRE_EPISODE_RESET", at_ns)
        return True

    def receipt(self, receipt: PopupReceipt) -> bool:
        """Accept into an ordered inbox; True need not mean applied yet.

        sequence=0 is the strict legacy isolated-test contract. It cannot prove
        reordered GUI truth, or downgrade a request once ordered receipts appear.
        The presenter always emits the identity-bearing sequenced protocol.
        """
        request = self._request
        if (not isinstance(receipt, PopupReceipt) or request is None
                or receipt.request_id != request.request_id or receipt.scope != request.scope
                or type(receipt.at_ns) is not int or receipt.at_ns < request.at_ns
                or type(receipt.sequence) is not int or receipt.sequence < 0
                or type(receipt.received_at_ns) is not int or receipt.received_at_ns < 0
                or (receipt.received_at_ns and receipt.received_at_ns < receipt.at_ns)):
            return False
        if receipt.sequence == 0:
            if self._protocol == "ordered" or receipt.display_id:
                return False
            self._protocol = "legacy"
            self._replay_deferred()
            accepted = self._legacy_receipt(receipt)
            if accepted and receipt.kind in {"DISPLAYED", "CLOSED", "FAILED"}:
                self._unresolved_display = False
            return accepted
        if self._protocol == "legacy":
            return False
        if (receipt.kind not in {"DISPLAYED", "CLOSED", "FAILED", "CLOSE_FAILED", "ACTION"}
                or receipt.sequence <= self._receipt_sequence
                or receipt.sequence in self._receipt_buffer
                or receipt.sequence > self._receipt_sequence + 64
                or type(receipt.display_id) is not str
                or (receipt.kind == "DISPLAYED" and not receipt.display_id.strip())
                or (receipt.kind == "FAILED" and receipt.display_id)
                or (receipt.kind == "ACTION" and (not receipt.display_id or not isinstance(receipt.action, Action)))):
            return False
        self._protocol = "ordered"
        self._receipt_buffer[receipt.sequence] = receipt
        accepted = True
        while self._receipt_sequence + 1 in self._receipt_buffer:
            item = self._receipt_buffer.pop(self._receipt_sequence + 1)
            if not self._ordered_receipt(item):
                accepted = item.sequence != receipt.sequence
                break  # Invalid envelope is rejected; a corrected sequence may retry.
        return accepted

    def _ordered_receipt(self, receipt):
        request = self._request
        now = receipt.at_ns
        if now < self._receipt_ns:
            return False
        if receipt.kind == "DISPLAYED":
            if not self._unresolved_display or self._popup_state not in {"REQUESTED", "CLOSE_REQUESTED"}:
                return False
            self._replay_deferred(before_ns=now)
            closing = self._popup_state == "CLOSE_REQUESTED"
            # Request admission proved founding eligibility. Cancellation is
            # intent, not evidence that the GUI never displayed the request.
            if not self._episode:
                if request.stage is not Stage.SECANT_1 or self._scope != request.scope:
                    return False
                self._episode = "secant-episode-" + uuid4().hex
                self._founded = now
                self._recovery = RecoveryAuthority(self._episode, request.scope, now)
                self._fact("SECANT_EPISODE_FOUNDED", now, request_id=request.request_id,
                    founding_source=self._take_founding_source(request.request_id))
            if request.stage != self._stage:
                self._stage = request.stage
                delay = {Stage.SECANT_1: STAGE_2_NS, Stage.SECANT_2: STAGE_3_NS}.get(self._stage)
                self._deadline = None if delay is None or self._holds else now + delay
                if self._holds:
                    self._remaining = delay
            self._display_id = receipt.display_id
            self._popup_state = "CLOSE_REQUESTED" if closing else "DISPLAYED"
            self._unresolved_display = False
            self._reset_waiting = False  # A factual episode defeats the no-episode branch.
            self._fact("SECANT_DISPLAYED", now, request_id=request.request_id)
            latest = self._latest_observation
            if latest and (latest.meaning is Meaning.UNCERTAIN or not latest.fresh):
                self._hold("uncertainty", now)
                self._close_popup(now, "uncertainty")
        else:
            if receipt.display_id != self._display_id:
                return False
            if self._unresolved_display:
                self._replay_deferred(before_ns=now)
            if receipt.kind == "CLOSED":
                if self._popup_state not in {"DISPLAYED", "CLOSE_REQUESTED"}:
                    return False
                self._popup_state = "CLOSED"
                self._return_close_retry = False
                self._unresolved_display = False
                self._fact("SECANT_POPUP_CLOSED", now, request_id=request.request_id)
            elif receipt.kind == "FAILED":
                if not self._unresolved_display or self._popup_state not in {"REQUESTED", "CLOSE_REQUESTED"}:
                    return False
                self._popup_state = "FAILED"
                self._take_founding_source(request.request_id)
                self._unresolved_display = False
                self._fact("SECANT_DELIVERY_FAILED", now, request_id=request.request_id, reason=receipt.detail)
            elif receipt.kind == "CLOSE_FAILED":
                if self._popup_state != "CLOSE_REQUESTED":
                    return False
                self._fact("SECANT_CLOSE_FAILED", now, request_id=request.request_id, reason=receipt.detail)
                self._return_close_retry = (self._return_withdrawn_stage is not Stage.NONE
                and self._return_withdrawn_stage == self._stage)
            else:
                # Intent may be delivered after withdrawal/termination. Consume
                # its sequence, but never grant stale authority or block CLOSED.
                permitted = (self._popup_state == "DISPLAYED" and not self._holds
                    and not self._terminal and not self._action_sent
                    and receipt.action in presentation(self._stage).actions)
                if permitted:
                    self._action_sent = True
                    self._action_sequence = receipt.sequence
                self._fact("SECANT_ACTION_INTENT" if permitted else "SECANT_ACTION_REJECTED",
                    now, request_id=request.request_id, reason=receipt.action.value)
                self._return_action_result(receipt, permitted)
        self._receipt_sequence = receipt.sequence
        self._receipt_ns = now
        self._delivery_ns = receipt.received_at_ns
        self._last_ns = max(self._last_ns, now)
        if not self._unresolved_display:
            self._replay_deferred()
        return True


    def set_resources(self, resources) -> None:
        from .read_model import StudyResourceFact
        values = tuple(resources)
        if any(not isinstance(item, StudyResourceFact) for item in values):
            raise TypeError("Immutable Study-resource facts required")
        self._resources = values

    def confirm_break(self, pause_id: str, cosecant_break_id: str) -> bool:
        if not pause_id or pause_id != self._break_id or not cosecant_break_id:
            return False
        if self._committed_break_id and self._committed_break_id != cosecant_break_id:
            return False
        self._committed_break_id = cosecant_break_id
        return True

    def action_result(self, request_id: str, accepted: bool, at_ns: int, *, action_sequence=None) -> bool:
        if (not self._request or request_id != self._request.request_id or self._terminal
                or not self._time_valid(at_ns)
                or (action_sequence is not None and action_sequence != self._action_sequence)):
            return False
        if not accepted:
            self._action_sent = False
            self._fact("SECANT_ACTION_REJECTED", at_ns, request_id=request_id)
        self._last_ns = at_ns
        return True

    def set_global_paused(self, hold_id: str, paused: bool, at_ns: int) -> bool:
        if not hold_id or not self._time_valid(at_ns) or self._scope is None or self._break_id:
            return False
        if self._unresolved_display and not self._replaying:
            self._defer("global", (hold_id, paused, at_ns), at_ns)
            if paused:
                self._close_popup(at_ns, "global_pause")
            return True
        if paused:
            if self._global_id and self._global_id != hold_id:
                return False
            self._global_id = hold_id
            self._hold("global", at_ns)
            if self._recovery:
                self._recovery.set_global_paused(hold_id, True, at_ns)
        else:
            if self._global_id != hold_id:
                return False
            self._global_id = ""
            self._release("global", at_ns)
            self._revalidate_dwell = True
            if self._recovery:
                self._recovery.set_global_paused(hold_id, False, at_ns)
        self._last_ns = at_ns
        return True
