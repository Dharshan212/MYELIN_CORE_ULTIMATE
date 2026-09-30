"""Bounded, one-way persistence observer. No organ commands or database handles.

All signal slots only enqueue public values; extraction and receipt observation
run in bounded GUI timer slices. EngineStorage owns the sole writer lane.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
import time
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


BOUNDED = "BOUNDED_OBSERVATION"
GAP = "RECORDING_GAP_DETECTED"
META_PREFIX = "passive_recorder:v1:run:"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2048
MAX_BATCH_BYTES = 256 * 1024
# Controller delivers up to 25 telemetry items without yielding to Qt. Allow
# two such bursts plus the active extraction; row/byte/write limits stay fixed.
MAX_REFERENCES = 64
NATIVE_NAMES = frozenset({"SECANT_EPISODE_FOUNDED", "SECANT_DISPLAYED",
    "SECANT_ACTION_INTENT", "SECANT_FROZEN", "SECANT_RESUMED",
    "SECANT_RETURN_STARTED", "SECANT_RETURN_VERIFIED", "SECANT_RECOVERY_CLOSED",
    "SECANT_RECOVERY_INTERRUPTED", "SECANT_EPISODE_CLOSED"})
COMMON_COLUMNS = ("event_id", "contract_version", "session_id", "recorder_run_id",
    "recorder_received_monotonic_ns", "recorder_received_at_utc", "recording_quality")
SECANT_COLUMNS = COMMON_COLUMNS + ("study_context_id", "study_target_resource_id",
    "episode_id", "fact_digest", "occurrence_ordinal", "event_name", "stage",
    "occurred_monotonic_ns", "request_id", "attempt_id", "evidence_id", "reason",
    "canonical_fact_json")
RESOURCE_COLUMNS = COMMON_COLUMNS + ("observation_ordinal", "event_kind",
    "study_context_token", "study_block_id", "study_generation", "resource_key",
    "display_title", "process_name", "resource_surface", "study_app_category",
    "classification", "measured_classification", "effective_operational_state",
    "confidence", "measured_confidence", "user_confirmation", "state_digest",
    "canonical_state_json", "source_lane", "timestamp_basis",
    "source_observation_sequence", "source_observed_monotonic_ns",
    "source_observed_at_utc", "provenance_json")
STATE_FIELDS = ("session_id", "study_context_token", "resource_key", "display_title",
    "process_name", "resource_surface", "study_app_category", "classification",
    "measured_classification", "effective_operational_state", "confidence",
    "measured_confidence", "user_confirmation")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 9223372036854775807:
        raise ValueError("Expected bounded non-boolean integer")
    return value


def _utc(value):
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("UTC stamp with Z required")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _text(value, nonempty=False):
    if type(value) is not str or (nonempty and not value):
        raise ValueError("Expected exact public text")
    return value


def _value(value):
    return getattr(value, "value", value)


def _covers_secant(new, old):
    """Bounded, exact prefix proof; uncertainty means retain both projections.

    Only factual timelines are superseded. Scope and target are part of the
    proof, including current-to-completed handoff and identical multiplicity.
    """
    from SECANT.read_model import SecantProjection, TimelineFact
    def timelines(p):
        if not isinstance(p, SecantProjection) or len(p.completed) > 64:
            return None
        result = []
        count = len(p.timeline)
        scope = p.scope
        for e in p.completed:
            count += len(e.timeline)
            if count > 256: return None
            result.append((e.scope, e.episode_id, e.timeline))
            if scope is None and e.episode_id == p.episode_id: scope = e.scope
        if count > 256: return None
        if p.episode_id: result.append((scope, p.episode_id, p.timeline))
        if any(s is None or any(not isinstance(f, TimelineFact) or f.episode_id != e for f in t)
               for s, e, t in result): return None
        return result
    previous, following = timelines(old), timelines(new)
    if previous is None or following is None: return False
    return all(any(s == ns and e == ne and len(t) <= len(nt) and t == nt[:len(t)]
                   for ns, ne, nt in following) for s, e, t in previous)


@dataclass(frozen=True, slots=True)
class SecantEventRecord:
    row_json: str


@dataclass(frozen=True, slots=True)
class StudyResourceEventRecord:
    row_json: str


@dataclass(frozen=True, slots=True)
class RecorderStatusRecord:
    status_json: str


@dataclass(frozen=True, slots=True)
class RecorderQuality:
    run_id: str
    writer_state: str
    coverage: str
    pending: int
    dropped: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FlushResult:
    state: str
    coverage: str
    pending: int


@dataclass(frozen=True, slots=True)
class RoleResolution:
    event_id: str
    state: str
    resource_fact_id: str = ""
    study_block_id: str = ""
    study_generation: int | None = None
    identity_kind: str = ""
    identity_version: int | None = None
    role: str = ""
    qualified_monotonic_ns: int | None = None
    qualified_at_utc: str = ""


def validate_founding_source(source, row):
    """Validate provenance separately; never change the canonical base identity."""
    from SECANT.read_model import ExactResource, FoundingSourceEvidence, validate_display_metadata
    if type(source) is not dict or set(source) - {"display_metadata"} != {
            "resource", "evidence_id", "observed_monotonic_ns", "meaning", "classification",
            "territory", "confirmed_off_task", "certified_ott"}:
        raise ValueError("Unexpected founding-source shape")
    metadata = validate_display_metadata(source.get("display_metadata"),
        observation_id=source["evidence_id"], observed_ns=source["observed_monotonic_ns"])
    evidence = FoundingSourceEvidence(**dict(source, resource=ExactResource(**source["resource"]),
                                             display_metadata=metadata))
    if (row["event_name"] != "SECANT_EPISODE_FOUNDED"
            or evidence.observed_monotonic_ns > row["occurred_monotonic_ns"]
            or evidence.meaning != "OFF_TASK"
            or not (evidence.territory != "ORDINARY" or evidence.confirmed_off_task or evidence.certified_ott)):
        raise ValueError("Source must be qualifying evidence for a founding event")
    payload = asdict(evidence)
    if metadata is None:
        payload.pop("display_metadata")
    return dict(event_id=row["event_id"], source_extension_version=1,
        source_evidence_id=evidence.evidence_id, source_resource_id=evidence.resource.key,
        source_observed_monotonic_ns=evidence.observed_monotonic_ns,
        source_evidence_json=canonical(payload))


def validate_record(record, kind):
    """Shared pure boundary validation; callers cannot spoof canonical IDs."""
    expected_type = SecantEventRecord if kind == "secant" else StudyResourceEventRecord
    if type(record) is not expected_type:
        raise TypeError("Immutable recorder record required")
    row = json.loads(record.row_json)
    columns = SECANT_COLUMNS if kind == "secant" else RESOURCE_COLUMNS
    source = row.pop("founding_source", None) if kind == "secant" and type(row) is dict else None
    if type(row) is not dict or set(row) != set(columns):
        raise ValueError("Unexpected recorder record shape")
    if type(row["contract_version"]) is not int or row["contract_version"] != 1:
        raise ValueError("Unsupported recorder contract")
    _integer(row["session_id"], 1)
    _integer(row["recorder_received_monotonic_ns"])
    _utc(row["recorder_received_at_utc"])
    _text(row["recorder_run_id"], True)
    if row["recording_quality"] not in (BOUNDED, GAP):
        raise ValueError("Unsupported recording quality")
    if kind == "secant":
        for name in ("study_context_id", "study_target_resource_id", "episode_id"):
            _text(row[name], True)
        if not row["study_context_id"].startswith(str(row["session_id"]) + ":"):
            raise ValueError("SECANT parent scope mismatch")
        for name in ("request_id", "attempt_id", "evidence_id", "reason"):
            _text(row[name])
        _integer(row["occurred_monotonic_ns"])
        _integer(row["occurrence_ordinal"], 1)
        _integer(row["stage"])
        if row["stage"] > 3 or row["event_name"] not in NATIVE_NAMES:
            raise ValueError("Unsupported native fact")
        if row["event_name"] == "SECANT_DISPLAYED" and not row["stage"]:
            raise ValueError("Display stage required")
        if row["event_name"] == "SECANT_ACTION_INTENT" and row["reason"] != "RETURN TO STUDY":
            raise ValueError("Not a Study return intent")
        if row["event_name"] in ("SECANT_FROZEN", "SECANT_RESUMED") and row["reason"] != "uncertainty":
            raise ValueError("Not an uncertainty hold")
        fact = [1, row["session_id"], row["study_context_id"], row["study_target_resource_id"],
            row["episode_id"], row["event_name"], row["stage"], row["occurred_monotonic_ns"],
            row["request_id"], row["attempt_id"], row["evidence_id"], row["reason"]]
        text = canonical(fact)
        if row["canonical_fact_json"] != text or row["fact_digest"] != digest(text):
            raise ValueError("Canonical SECANT content mismatch")
        event_id = digest(canonical(["secant-event-v1", fact, row["occurrence_ordinal"]]))
    else:
        for name in STATE_FIELDS:
            if name not in ("session_id", "confidence", "measured_confidence"):
                _text(row[name], name in ("study_context_token", "resource_key"))
        for name in ("confidence", "measured_confidence"):
            v = row[name]
            if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError("Invalid confidence")
        if row["classification"] not in {"STUDY_ALIGNED", "UNCERTAIN", "DISTRACTION", "APPROVED_BREAK", "BACKGROUND_AUDIO"} or row["measured_classification"] not in {"STUDY_ALIGNED", "UNCERTAIN", "DISTRACTION", "APPROVED_BREAK", "BACKGROUND_AUDIO"}:
            raise ValueError("Unsupported RI classification")
        if row["effective_operational_state"] not in {"UNRESOLVED", "STUDY_ALIGNED", "CONFIRMED_DISTRACTION"} or row["user_confirmation"] not in {"NONE", "STUDY", "OFF_TASK"}:
            raise ValueError("Unsupported confirmation state")
        if row["resource_surface"] not in {"unknown", "web_content", "youtube_watch", "youtube_other", "youtube_shorts", "browser_internal", "document", "learning_app", "work_app", "focus_web", "messaging", "social", "gaming", "cosine"}:
            raise ValueError("Unsupported resource surface")
        if row["study_block_id"] is None:
            if row["study_generation"] is not None:
                raise ValueError("Partial Study identity")
        else:
            _text(row["study_block_id"], True); _integer(row["study_generation"], 1)
        _integer(row["observation_ordinal"], 1)
        if row["event_kind"] not in {"RESOURCE_STATE_FIRST_OBSERVED", "RESOURCE_STATE_CHANGE_OBSERVED"}:
            raise ValueError("Unsupported observation kind")
        if row["source_lane"] not in {"CONTROL_VIEW", "RESOURCE_INTENT_LIVE_VIEW"}:
            raise ValueError("Unknown source lane")
        if row["timestamp_basis"] == "COHERENT_FOREGROUND_OBSERVATION":
            if row["source_lane"] != "CONTROL_VIEW":
                raise ValueError("Coherent timestamp requires composite source")
            _integer(row["source_observation_sequence"], 1)
            _integer(row["source_observed_monotonic_ns"])
            _utc(row["source_observed_at_utc"])
        elif row["timestamp_basis"] != "RECORDER_RECEIPT" or any(row[n] is not None for n in ("source_observation_sequence", "source_observed_monotonic_ns", "source_observed_at_utc")):
            raise ValueError("Invalid timestamp provenance")
        if type(json.loads(row["provenance_json"])) is not dict:
            raise ValueError("Provenance must be an object")
        text = canonical([1] + [row[n] for n in STATE_FIELDS])
        if text != row["canonical_state_json"] or digest(text) != row["state_digest"]:
            raise ValueError("Canonical resource state mismatch")
        event_id = digest(canonical(["resource-observation-v1", row["recorder_run_id"], row["session_id"], row["observation_ordinal"]]))
    if row["event_id"] != event_id:
        raise ValueError("Recorder identity mismatch")
    if source is not None:
        validate_founding_source(source, row)
        row["founding_source"] = source
    return row


def _contained(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self._fail(type(exc).__name__ + ": " + str(exc)[:180])
    return call


class PassiveSecantRecorder(QObject):
    quality_changed = pyqtSignal(object)

    def __init__(self, storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.run_id = uuid.uuid4().hex
        self.opened = utc_now()
        self.state, self.coverage = "STARTING", BOUNDED
        self.reasons = []
        self.dropped = self.committed = self.revision = 0
        self.sid = None
        self.sessions = set()
        self._work, self._pending = deque(), deque()
        self._generator = None
        self._history = {}
        self._history_bytes = self._pending_bytes = 0
        self._last = {}; self._ordinals = {}; self._sequences = {}
        self._committed_ordinals = {}; self._state_bytes = 0
        self._contexts = {}; self._composite = set()
        self._connections = []
        self._control_authoritative = False
        self._inflight = None
        self._initialized = False
        self._status_dirty = True
        self._accepting = True
        self._draining = False
        self._barrier_done = False
        self._closed_committed = False
        self._failure_status_attempted = False
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._pump)
        self._timer.start()

    def quality_snapshot(self):
        return RecorderQuality(self.run_id, self.state, self.coverage,
            len(self._pending), self.dropped, tuple(self.reasons))

    def _gap(self, reason):
        self.coverage = GAP
        if reason not in self.reasons and len(self.reasons) < 32:
            self.reasons.append(reason)
        self._status_dirty = True
        try:
            self.quality_changed.emit(self.quality_snapshot())
        except Exception:
            pass

    def _fail(self, reason):
        self.state = "FAILED"
        self._accepting = False
        self._gap(reason)
        # Never emit native/Controller signals or call an organ.

    @_contained
    def attach(self, controller, initial_session_id=None):
        routes = {"secant_projection_changed": self.on_secant_projection,
            "resource_intent_live_status_changed": self.on_resource_intent_live_view,
            "control_view_changed": self.on_control_view,
            "study_view_changed": self.on_study_view,
            "current_session_id_changed": self.on_session_changed}
        for name in ("engine_started", "engine_paused", "engine_resumed", "engine_stopped", "engine_failed", "engine_status_changed"):
            routes[name] = lambda *a, kind=name: self.on_lifecycle(kind, a)
        for name, slot in routes.items():
            signal = getattr(controller, name)
            signal.connect(slot)
            self._connections.append((signal, slot))
        # Monitor publishes the very same RI object in control_view each cycle.
        # The standalone copy arrives first and has no session envelope. Use
        # the bound composite lane from attachment, not only after its first row.
        self._control_authoritative = True
        self.on_session_changed(initial_session_id)

    def _enqueue(self, kind, value):
        if not self._accepting or value is None:
            return
        if kind == "resource" and (self._control_authoritative or self.sid in self._composite):
            return
        if kind == "secant":
            for index in range(len(self._work) - 1, -1, -1):
                previous = self._work[index]
                if previous[0] == kind and previous[2] == self.sid:
                    if _covers_secant(value, previous[1]):
                        del self._work[index]
                    break
        if len(self._work) + (self._generator is not None) >= MAX_REFERENCES:
            self.dropped += 1; self._gap("projection_buffer_full"); return
        # Composite envelopes contain immutable public objects; copy outer
        # metadata containers to prevent later mutation by another subscriber.
        if kind == "control" and isinstance(value, dict):
            value = dict(value)
            if isinstance(value.get("study_app_category"), dict):
                value["study_app_category"] = dict(value["study_app_category"])
        self._work.append((kind, value, self.sid, time.monotonic_ns(), utc_now()))

    @_contained
    def on_secant_projection(self, value): self._enqueue("secant", value)

    @_contained
    def on_resource_intent_live_view(self, value): self._enqueue("resource", value)

    @_contained
    def on_control_view(self, value): self._enqueue("control", value)

    @_contained
    def on_study_view(self, value): self._enqueue("study", value)

    @_contained
    def on_session_changed(self, session_id):
        if session_id is not None:
            _integer(session_id, 1)
            if session_id not in self.sessions and len(self.sessions) >= 2048:
                self._fail("session_history_limit"); return
            self.sessions.add(session_id)
        self.sid = session_id
        self._status_dirty = True

    @_contained
    def on_lifecycle(self, kind, payload=None):
        if kind == "engine_failed":
            self._gap("engine_failed_public_signal")
        self._status_dirty = True

    def _base(self, sid, received_ns, received_utc):
        return dict(contract_version=1, session_id=_integer(sid, 1), recorder_run_id=self.run_id,
            recorder_received_monotonic_ns=received_ns, recorder_received_at_utc=received_utc,
            recording_quality=self.coverage)

    def _admit(self, kind, row):
        record = (SecantEventRecord if kind == "secant" else StudyResourceEventRecord)(canonical(row))
        validate_record(record, kind)
        size = len(record.row_json.encode("utf-8"))
        if size > MAX_BATCH_BYTES or len(self._pending) >= MAX_ROWS or self._history_bytes + self._state_bytes + self._pending_bytes + size > MAX_BYTES:
            self.dropped += 1; self._fail("record_buffer_full"); return False
        self._pending.append((kind, record, size)); self._pending_bytes += size
        return True

    def _secant(self, projection, sid, ns, wall):
        from SECANT.read_model import SecantProjection, TimelineFact
        if not isinstance(projection, SecantProjection) or sid is None:
            self._gap("unbound_secant_projection"); return
        if len(projection.completed) > 50000:
            self._fail("projection_size_limit"); return
        # Process each tuple against its remembered prefix. Current and
        # completed copies share the same history; no concatenation occurs.
        def episodes():
            current_scope = projection.scope
            for e in projection.completed:
                if e.episode_id == projection.episode_id and current_scope is None:
                    current_scope = e.scope
                yield e.scope, e.episode_id, e.timeline, False
            if projection.episode_id:
                yield current_scope, projection.episode_id, projection.timeline, True
        for scope, episode, timeline, is_current in episodes():
            if scope is None or not scope.context_id.startswith(str(sid) + ":") or not scope.context_id.split(":", 1)[1]:
                self._gap("secant_scope_mismatch"); continue
            if len(timeline) > 50000:
                self._fail("projection_size_limit"); return
            key = (sid, scope.context_id, episode)
            history, counts, target = self._history.setdefault(key, ([], {}, scope.target_resource_id))
            if target != scope.target_resource_id:
                self._gap("secant_target_conflict"); continue
            index = 0
            for fact in timeline:
                if not isinstance(fact, TimelineFact):
                    self._gap("invalid_timeline_fact"); break
                if not fact.episode_id:
                    yield; continue
                if fact.episode_id != episode:
                    self._gap("fact_episode_mismatch"); break
                values = [1, sid, scope.context_id, target, episode, fact.name,
                    int(fact.stage), fact.at_ns, fact.request_id, fact.attempt_id, fact.evidence_id, fact.reason]
                text = canonical(values)
                source = asdict(fact.founding_source) if fact.founding_source is not None else None
                # Prefix comparison includes provenance, but fact identity does not.
                history_text = canonical([text, source])
                if index < len(history):
                    if history[index] != history_text:
                        self._gap("secant_prefix_changed"); break
                else:
                    size = len(history_text.encode("utf-8"))
                    if self._history_bytes + self._state_bytes + self._pending_bytes + size > MAX_BYTES:
                        self._fail("history_memory_limit"); return
                    history.append(history_text); self._history_bytes += size
                    counts[text] = counts.get(text, 0) + 1
                    selected = fact.name in NATIVE_NAMES
                    if fact.name == "SECANT_ACTION_INTENT": selected = fact.reason == "RETURN TO STUDY"
                    if fact.name in ("SECANT_FROZEN", "SECANT_RESUMED"): selected = fact.reason == "uncertainty"
                    if selected:
                        ordinal = counts[text]
                        row = self._base(sid, ns, wall)
                        row.update(event_id=digest(canonical(["secant-event-v1", values, ordinal])),
                            study_context_id=scope.context_id, study_target_resource_id=target,
                            episode_id=episode, fact_digest=digest(text), occurrence_ordinal=ordinal,
                            event_name=fact.name, stage=int(fact.stage), occurred_monotonic_ns=fact.at_ns,
                            request_id=fact.request_id, attempt_id=fact.attempt_id,
                            evidence_id=fact.evidence_id, reason=fact.reason, canonical_fact_json=text)
                        if source is not None:
                            row["founding_source"] = source
                        if not self._admit("secant", row): return
                index += 1
                yield
            # Completed copies can be frozen at closure. A shorter current
            # timeline without that durable-in-projection copy is a real
            # observable regression; never reinterpret it as new facts.
            if is_current and index < len(history) and not any(e.episode_id == episode for e in projection.completed):
                self._gap("secant_timeline_regressed")
            yield

    def _resource(self, payload, sid, ns, wall, composite):
        from CORE_ENGINE.resource_intent import ResourceIntentLiveView, ResourceObservation
        if sid is None:
            self._gap("unbound_resource_projection"); return
        if not composite and sid in self._composite: return
        view = payload.get("resource_intent") if composite and isinstance(payload, dict) else payload
        if not isinstance(view, ResourceIntentLiveView): return
        token = view.study_context_token
        if not token or not view.resource_key: return
        category, rejection, coherent = "", "no_composite_source", False
        sequence = observed_ns = observed_utc = None
        meta = {}; fg = source = None
        if composite:
            if type(payload.get("session_id")) is not int or payload["session_id"] != sid:
                self._gap("composite_session_mismatch"); return
            meta = payload.get("study_app_category")
            if not isinstance(meta, dict): meta = {}
            fg = payload.get("foreground"); source = meta.get("source_observation")
            # RI identity is independently carried by the envelope. Category
            # and source time require the stronger same-observation proof.
            try:
                coherent = bool(meta.get("schema_version") == "myelin-study-app-category-v1-prototype"
                    and type(meta.get("session_id")) is int and meta["session_id"] == sid
                    and meta.get("resource_key") == view.resource_key
                    and meta.get("study_context_token") == token
                    and meta.get("canonical_process_name") == view.process_name
                    and isinstance(source, ResourceObservation)
                    and source.process_name == view.process_name
                    and source.sequence == meta.get("observation_sequence") == fg.sequence
                    and source.observed_monotonic_ns == meta.get("observed_monotonic_ns") == fg.observed_monotonic_ns
                    and source.process_id == meta.get("process_id") == fg.process_id
                    and source.hwnd == meta.get("hwnd") == fg.hwnd
                    and source.raw_title == fg.window_title
                    and meta.get("process_name") == fg.process_name.strip().casefold().removesuffix(".exe")
                    and type(meta.get("observation_token")) is str and bool(meta["observation_token"]))
                if coherent:
                    _integer(source.sequence, 1); _integer(source.observed_monotonic_ns, 1)
                    _integer(source.process_id, 1); _integer(source.hwnd, 1)
                    observed_utc = _utc(fg.observed_wall_time_utc)
                    sequence, observed_ns = source.sequence, source.observed_monotonic_ns
            except (AttributeError, ValueError, TypeError): coherent = False
            if coherent:
                rejection = ""
                if meta.get("evidence_available") is True and type(meta.get("category")) is str:
                    category = meta["category"]
            else:
                sequence = observed_ns = observed_utc = None
                rejection = "unavailable_or_mismatched_source_metadata"
            self._composite.add(sid)
            if (sid, token) not in self._contexts and len(self._contexts) >= 2048:
                self._fail("context_history_limit"); return
            self._contexts.setdefault((sid, token), (None, None))
        elif (sid, token) not in self._contexts:
            self._gap("unbound_ri_context"); return
        row = self._base(sid, ns, wall)
        for name in STATE_FIELDS:
            if name not in ("session_id", "study_app_category"):
                row[name] = _value(getattr(view, name))
        row["study_app_category"] = category
        text = canonical([1] + [row[n] for n in STATE_FIELDS])
        context = (sid, token)
        if coherent:
            previous = self._sequences.get(sid)
            if previous and (sequence < previous[0] or observed_ns < previous[1] or (sequence == previous[0] and text != previous[2])):
                self._gap("resource_observation_order_conflict"); return
            self._sequences[sid] = (sequence, observed_ns, text)
        if self._last.get(context) == text: return
        previous_size = len(self._last.get(context, "").encode("utf-8"))
        new_size = len(text.encode("utf-8"))
        if self._state_bytes - previous_size + new_size + self._history_bytes + self._pending_bytes > MAX_BYTES:
            self._fail("resource_state_memory_limit"); return
        ordinal = self._ordinals.get(sid, 0) + 1
        block, generation = self._contexts.get(context, (None, None))
        # Copy existing certified identity components, never call RI identity
        # builders or infer identity from a title, category, or process.
        exact_identity = None
        if (coherent and view.browser_evidence_certified is True
                and source.browser_supported is True and source.browser_read_ok is True
                and source.browser_evidence_kind not in ("", "invalid_address", "url_unavailable")):
            platform = source.certified_ott_platform_key or source.browser_platform
            if type(platform) is str and platform and type(source.browser_resource_token) is str and source.browser_resource_token:
                exact_identity = dict(kind="BROWSER", version=1, platform_key=platform,
                    resource_token=source.browser_resource_token)
        row.update(event_id=digest(canonical(["resource-observation-v1", self.run_id, sid, ordinal])),
            observation_ordinal=ordinal,
            event_kind="RESOURCE_STATE_CHANGE_OBSERVED" if context in self._last else "RESOURCE_STATE_FIRST_OBSERVED",
            study_block_id=block, study_generation=generation,
            state_digest=digest(text), canonical_state_json=text,
            source_lane="CONTROL_VIEW" if composite else "RESOURCE_INTENT_LIVE_VIEW",
            timestamp_basis="COHERENT_FOREGROUND_OBSERVATION" if coherent else "RECORDER_RECEIPT",
            source_observation_sequence=sequence, source_observed_monotonic_ns=observed_ns,
            source_observed_at_utc=observed_utc,
            provenance_json=canonical(dict(source_rejection_reason=rejection,
                exact_resource_identity=exact_identity,
                observation_token=meta.get("observation_token", "") if coherent else "",
                category_evidence_available=bool(coherent and meta.get("evidence_available") is True),
                session_binding="composite_envelope" if composite else "previous_public_context",
                timestamp_semantics="foreground_observation" if coherent else "recorder_receipt")))
        self._state_bytes += new_size - previous_size
        if self._admit("resource", row):
            self._last[context] = text; self._ordinals[sid] = ordinal
        else:
            self._state_bytes -= new_size - previous_size

    def _extract(self, item):
        kind, value, sid, ns, wall = item
        if kind == "secant":
            yield from self._secant(value, sid, ns, wall)
        elif kind in ("control", "resource"):
            self._resource(value, sid, ns, wall, kind == "control")
        elif kind == "study":
            from COSECANT_STUDY_MODE.study import StudySnapshot
            if not isinstance(value, StudySnapshot): return
            # Public data only. Do not invoke the context_token property: it
            # calls an RI helper. Durable resource values already carry tokens.
            for resource in getattr(value, "resources", ()):
                if getattr(resource, "session_id", None) == sid:
                    if (sid, resource.study_context_token) not in self._contexts and len(self._contexts) >= 2048:
                        self._fail("context_history_limit"); return
                    self._contexts[(sid, resource.study_context_token)] = (resource.study_block_id, resource.study_generation)
                yield

    def _status(self, state=None, final=False):
        self.revision += 1
        return RecorderStatusRecord(canonical(dict(run_id=self.run_id, contract_version=1,
            status_revision=self.revision, writer_state=state or self.state,
            coverage=self.coverage, opened_at_utc=self.opened, last_recorded_at_utc=utc_now(),
            closed_at_utc=utc_now() if final else None, attached_session_ids=sorted(self.sessions),
            pending=len(self._pending), dropped=self.dropped, gap_reasons=list(self.reasons),
            committed_rows=self.committed, final_flush_committed=final,
            last_committed_resource_ordinals=dict(self._committed_ordinals))))

    def _submit(self, kind, value):
        if kind in ("status", "final"):
            receipt = self.storage.record_passive_recorder_status(value)
        elif kind == "barrier": receipt = self.storage.flush_passive_recorder()
        elif kind == "secant": receipt = self.storage.append_secant_events(value)
        else: receipt = self.storage.append_study_resource_events(value)
        self._inflight = [kind, value, receipt, time.monotonic(), 0]

    @_contained
    def _pump(self):
        # Extraction is independent of writer receipt latency. Still only one
        # write may be in flight; pending rows remain until its commit is seen.
        if self.state not in ("FAILED", "CLOSED"):
            stop = time.perf_counter() + .002
            for _ in range(64):
                if time.perf_counter() >= stop: break
                if self._generator is None:
                    if not self._work: break
                    self._generator = self._extract(self._work.popleft())
                try: next(self._generator)
                except StopIteration: self._generator = None
                if self.state == "FAILED": break
        if self._inflight:
            kind, value, initial, started, retries = self._inflight
            receipt = self.storage.receipt(initial.receipt_id)
            if receipt is None: self._fail("missing_writer_receipt"); return
            state = _value(receipt.state)
            if state == "RUNNING":
                if time.monotonic() - started > 8: self._fail("writer_outcome_unknown")
                return
            if state == "FAILED":
                if "queue is full" in (receipt.error or "") and retries == 0:
                    if time.monotonic() - started < .25: return
                    self.storage.forget_receipt(receipt.receipt_id)
                    self._submit(kind, value); self._inflight[4] = 1; return
                self.storage.forget_receipt(receipt.receipt_id)
                self._inflight = None; self._fail("writer_failed: " + (receipt.error or "")[:120]); return
            self.storage.forget_receipt(receipt.receipt_id); self._inflight = None
            if kind == "status": self._initialized = True
            elif kind == "barrier": self._barrier_done = True
            elif kind == "final": self._closed_committed = True; self.state = "CLOSED"
            else:
                for record in value:
                    _, _, size = self._pending.popleft(); self._pending_bytes -= size
                    if kind == "resource":
                        row = json.loads(record.row_json)
                        self._committed_ordinals[row["session_id"]] = row["observation_ordinal"]
                self.committed += len(value)
        if self.state == "FAILED":
            if self._initialized and not self._failure_status_attempted:
                self._failure_status_attempted = True
                self._submit("status", self._status())
            return
        if self.state == "CLOSED": return
        if not self._initialized:
            self.state = "ACTIVE" if not self._draining else "DRAINING"
            self._status_dirty = False; self._submit("status", self._status()); return
        if self._pending:
            kind = self._pending[0][0]; batch = []; size = 0
            for row_kind, record, nbytes in self._pending:
                if row_kind != kind or len(batch) >= 64 or size + nbytes > MAX_BATCH_BYTES: break
                batch.append(record); size += nbytes
            self._submit(kind, tuple(batch)); return
        if self._draining and not self._work and self._generator is None:
            if not self._barrier_done: self._submit("barrier", None)
            else: self._submit("final", self._status("CLOSED", True))
        elif self._status_dirty:
            self._status_dirty = False; self._submit("status", self._status())

    @_contained
    def begin_shutdown(self):
        self._accepting = False; self._draining = True
        self._timer.stop()
        for signal, slot in self._connections:
            try: signal.disconnect(slot)
            except (TypeError, RuntimeError): pass
        self._connections.clear()
        if self.state != "FAILED": self.state = "DRAINING"

    def finish_shutdown(self, timeout_seconds=8.0):
        self.begin_shutdown()
        deadline = time.monotonic() + max(0, timeout_seconds)
        while time.monotonic() < deadline:
            self._pump()
            if self._closed_committed: return FlushResult("COMMITTED", self.coverage, 0)
            if self.state == "FAILED" and not self._inflight: break
            time.sleep(.001)  # Only post-event-loop exit; never a signal slot.
        self._gap("shutdown_flush_incomplete")
        return FlushResult("OUTCOME_UNKNOWN" if self._inflight else "INCOMPLETE", self.coverage, len(self._pending))
