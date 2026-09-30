"""Durable repositories, readers and report-safety authority for MYELIN 2.0.

Domain runtimes do not write SQL.  They submit immutable facts here.  COSINE
and other transitions that require a durable acknowledgement wait for the
single SQLite lane to reach a terminal receipt before returning success.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import uuid
import json
import math
import os
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Callable, Final, Optional

from PERSISTENCE.database import (
    ReceiptState,
    SQLiteTransactionLane,
    TransactionReceipt,
    TransactionResult,
    connect_database,
)
from PERSISTENCE.schema import ensure_production_schema
from PROFILES.profiles import PROFILE_KEYS


DURABLE_WAIT_SECONDS = 8.0


# The semantic generation of the Tr that produced a learning row.  This is the
# SINGLE provenance authority for profile learning -- it reuses the existing
# ``profile_learning_state.model_version`` column rather than adding a second,
# overlapping version field, so there is never a question about which marker
# decides compatibility.
#
# v1 (the column DEFAULT, still stamped on every legacy row) anchored Tr at the
# MIRL verification/proof completion.  v2 anchors it at the behavioural return
# ONSET -- see ``MIRL.mirl.VerifiedRecoveryEvidence``.  The two are not
# interchangeable and the old value cannot be corrected by subtracting the
# verification window, because RETURN_VERIFIED lands on the first observation
# at or after the window closes and NEUTRAL stretches stall focus accrual
# without interrupting it.  A v1 row is therefore ineligible to drive
# adaptation, not repairable.
#
# NOTE ON DIRECTION: this value is stamped at WRITE time by the code that
# actually produced the evidence, which is genuine provenance.  It is the exact
# opposite of inferring an old row's generation at READ time from whatever
# version the running program happens to be -- that would prove nothing.
PROFILE_LEARNING_MODEL_VERSION = (
    "myelin-ebbinghaus-profile-learning-v2-return-onset"
)


@dataclass(frozen=True, slots=True)
class ProfileLearningState:
    """Durable learned Ebbinghaus state for exactly one profile.

    ``learned_lambda is None`` means that profile has no valid completed-session
    learning yet.  This object is a read model only; it does not calculate the
    Ebbinghaus equation and it does not choose SINE timing.

    ``learned_return_latency_seconds`` is the ACTUAL verified MIRL return
    latency (Tr) from the previous eligible session. ``learned_lambda`` is the
    corresponding learned Ebbinghaus recovery-rate evidence. Both are retained
    together so MYELIN preserves the factual observation and its mathematical
    Ebbinghaus derivation. Storage does not invent a reference time, reference
    lambda, factor bound, or SINE timing decision.
    """

    profile_key: str
    learned_lambda: float | None
    learned_return_latency_seconds: float | None
    valid_session_count: int
    valid_episode_count: int
    last_learning_session_id: int | None
    last_updated_utc: str
    model_version: str

    @property
    def is_learned(self) -> bool:
        return self.learned_lambda is not None


def _profile_learning_key(value: object) -> str:
    key = str(value or "").strip().lower()
    if key not in PROFILE_KEYS:
        raise ValueError("profile_key is not one of the five MYELIN profiles")
    return key


def _positive_finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def _positive_int(value: object, *, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _profile_learning_state_from_row(profile_key: str, row) -> ProfileLearningState:
    if row is None:
        return ProfileLearningState(
            profile_key=profile_key,
            learned_lambda=None,
            learned_return_latency_seconds=None,
            valid_session_count=0,
            valid_episode_count=0,
            last_learning_session_id=None,
            last_updated_utc="",
            model_version="",
        )

    learned_lambda = row["learned_lambda"]
    if learned_lambda is None:
        parsed_lambda = None
    else:
        parsed_lambda = _positive_finite_number(float(learned_lambda), name="learned_lambda")

    learned_latency = row["learned_return_latency_seconds"]
    if learned_latency is None:
        parsed_latency = None
    else:
        parsed_latency = _positive_finite_number(
            float(learned_latency), name="learned_return_latency_seconds"
        )

    if (parsed_lambda is None) != (parsed_latency is None):
        raise RuntimeError(
            "learned profile state has lambda/return-latency without the other"
        )

    state = ProfileLearningState(
        profile_key=profile_key,
        learned_lambda=parsed_lambda,
        learned_return_latency_seconds=parsed_latency,
        valid_session_count=int(row["valid_session_count"]),
        valid_episode_count=int(row["valid_episode_count"]),
        last_learning_session_id=(
            int(row["last_learning_session_id"])
            if row["last_learning_session_id"] is not None
            else None
        ),
        last_updated_utc=str(row["last_updated_utc"]),
        model_version=str(row["model_version"]),
    )
    if state.is_learned:
        if state.valid_session_count <= 0:
            raise RuntimeError("learned profile state has no contributing session")
        if state.valid_episode_count < state.valid_session_count:
            raise RuntimeError("learned profile state has inconsistent episode count")
        if state.last_learning_session_id is None:
            raise RuntimeError("learned profile state has no session provenance")
        if not state.model_version:
            raise RuntimeError("learned profile state has no model version")
    elif (
        state.valid_session_count != 0
        or state.valid_episode_count != 0
        or state.last_learning_session_id is not None
    ):
        raise RuntimeError("unlearned profile state contains learned counters")
    return state


_OBSERVATION_EVIDENCE_FIELDS = ("evidence_id", "extension_version", "kind", "session_id",
    "interval_capture_id", "boundary_capture_id", "study_context_token", "study_block_id", "study_generation",
    "resource_key", "identity_json", "observation_id", "observation_sequence", "observed_monotonic_ns",
    "interval_id", "request_id", "confirmation_applied_monotonic_ns", "authority_json")


@dataclass(frozen=True, slots=True)
class StudyObservationEvidenceRecord:
    """Authority history linked to existing captures, not a Study Jump decision."""
    row_json: str


def _observation_evidence_id(row):
    return hashlib.sha256(_boundary_json([1, row["interval_capture_id"], row["kind"],
        row["session_id"], row["observation_id"], row["request_id"]]).encode()).hexdigest()


def _validate_observation_evidence(record):
    from SECANT.read_model import ExactResource, validate_display_metadata
    from CORE_ENGINE.resource_intent import ResourceIntent, StudyEffectiveState, StudyUserConfirmation
    if type(record) is not StudyObservationEvidenceRecord or len(record.row_json.encode()) > 65536:
        raise ValueError("Bounded immutable Study observation evidence required")
    row = json.loads(record.row_json)
    if type(row) is not dict or set(row) != set(_OBSERVATION_EVIDENCE_FIELDS):
        raise ValueError("Unexpected Study observation evidence shape")
    if type(row["extension_version"]) is not int or row["extension_version"] != 1:
        raise ValueError("Unsupported Study observation evidence version")
    for name in ("session_id", "observation_sequence", "observed_monotonic_ns"):
        if type(row[name]) is not int or not (1 if name == "session_id" else 0) <= row[name] <= 9223372036854775807:
            raise ValueError("Invalid observation identity/time")
    for name in ("interval_capture_id", "boundary_capture_id", "study_context_token", "resource_key", "observation_id"):
        if type(row[name]) is not str or not row[name]:
            raise ValueError("Exact observation identity required")
    block, generation = row["study_block_id"], row["study_generation"]
    if not (block is None and generation is None):
        if type(block) is not str or not block or type(generation) is not int or not 0 < generation <= 9223372036854775807:
            raise ValueError("Partial observation scope")
    payload = json.loads(row["authority_json"])
    validate_display_metadata(payload.get("display_metadata"),
        observation_id=row["observation_id"], sequence=row["observation_sequence"],
        observed_ns=row["observed_monotonic_ns"])
    exact = ExactResource(**json.loads(row["identity_json"]))
    if (exact.key != row["resource_key"] or dataclasses.asdict(exact) != payload["resource"]
            or json.dumps(dataclasses.asdict(exact), sort_keys=True, separators=(",", ":")) != row["identity_json"]):
        raise ValueError("Exact resource evidence mismatch")
    for key in ("study_context_token", "observation_id", "observation_sequence", "observed_monotonic_ns"):
        if payload[key] != row[key]:
            raise ValueError("Observation authority mismatch")
    if (payload["study_block_id"] or None) != block or (payload["study_generation"] if block else None) != generation:
        raise ValueError("Observation scope mismatch")
    ResourceIntent(payload["classification"]); ResourceIntent(payload["measured_classification"])
    StudyEffectiveState(payload["effective_operational_state"]); StudyUserConfirmation(payload["user_confirmation"])
    for key in ("confidence", "measured_confidence"):
        if type(payload[key]) not in (int, float) or not math.isfinite(payload[key]) or not 0 <= payload[key] <= 1:
            raise ValueError("Invalid authoritative confidence")
    if type(payload["confirmation_monotonic_ns"]) is not int or payload["confirmation_monotonic_ns"] < 0:
        raise ValueError("Invalid authoritative confirmation time")
    confirmation = payload["confirmation"]
    if confirmation is not None:
        if (confirmation["confirmed_monotonic_ns"] != payload["confirmation_monotonic_ns"]
                or confirmation["authority_resource_key"] != payload["authority_resource_key"]
                or confirmation["user_confirmation"] != payload["user_confirmation"]):
            raise ValueError("Confirmation authority mismatch")
    if row["kind"] == "OBSERVATION":
        if row["request_id"] != "" or row["confirmation_applied_monotonic_ns"] is not None:
            raise ValueError("A foreground poll is not a confirmation action")
        if row["interval_id"] is not None and (type(row["interval_id"]) is not str or not row["interval_id"]):
            raise ValueError("Invalid exact span reference")
    elif row["kind"] == "CONFIRMATION":
        stamp = row["confirmation_applied_monotonic_ns"]
        if (row["interval_id"] is not None or type(row["request_id"]) is not str or not row["request_id"]
                or type(stamp) is not int or not row["observed_monotonic_ns"] <= stamp <= 9223372036854775807
                or stamp != payload["confirmation_monotonic_ns"] or confirmation is None
                or not confirmation["case1_popup_confirmed"]):
            raise ValueError("Exact accepted confirmation evidence required")
    else:
        raise ValueError("Unsupported observation evidence kind")
    if row["evidence_id"] != _observation_evidence_id(row):
        raise ValueError("Observation evidence identity mismatch")
    return row


class _StudyObservationEvidenceCapture:
    """Bounded, independent writer receipts; missing evidence remains unresolved."""
    def __init__(self, storage):
        self.storage = storage
        self.pending = []
        self.last_error = ""

    def reap(self):
        pending = []
        for rid in self.pending:
            receipt = self.storage.receipt(rid)
            if receipt is not None and receipt.state is ReceiptState.RUNNING:
                pending.append(rid)
                continue
            if receipt is None or receipt.state is not ReceiptState.COMMITTED:
                self.last_error = "Study observation evidence write failed; evidence unresolved"
            if receipt is not None:
                self.storage.forget_receipt(rid)
        self.pending = pending

    def capture(self, session_id, authority_json, request_id, applied_ns):
        self.reap()
        if type(authority_json) is not str or len(authority_json.encode()) > 30000:
            raise ValueError("Bounded immutable authority evidence required")
        authority = json.loads(authority_json)
        intervals, boundaries = self.storage._study_interval_observer, self.storage._study_boundary_observer
        if intervals is None or boundaries is None:
            raise ValueError("No exact resource capture lifetime exists")
        block = authority["study_block_id"] or None
        scope = (session_id, authority["study_context_token"], block, authority["study_generation"] if block else None)
        row = dict(extension_version=1, kind="CONFIRMATION" if request_id else "OBSERVATION",
            session_id=session_id, interval_capture_id=intervals.capture_id, boundary_capture_id=boundaries.capture_id,
            study_context_token=scope[1], study_block_id=scope[2], study_generation=scope[3],
            resource_key=authority["resource"]["key"],
            identity_json=json.dumps(authority["resource"], sort_keys=True, separators=(",", ":")),
            observation_id=authority["observation_id"], observation_sequence=authority["observation_sequence"],
            observed_monotonic_ns=authority["observed_monotonic_ns"], interval_id=None,
            request_id=request_id, confirmation_applied_monotonic_ns=applied_ns, authority_json=authority_json)
        current = intervals.current
        if not request_id and current is not None:
            current_scope, identity, first, last, count, limit = current
            if (scope == current_scope and identity[0] == row["resource_key"]
                    and last == (row["observation_id"], row["observation_sequence"], row["observed_monotonic_ns"])):
                row["interval_id"] = _interval_id(dict(capture_id=intervals.capture_id,
                    span_ordinal=intervals.ordinal + 1, session_id=session_id,
                    study_context_token=scope[1], first_observation_id=first[0]))
        row["evidence_id"] = _observation_evidence_id(row)
        record = StudyObservationEvidenceRecord(_boundary_json(row))
        _validate_observation_evidence(record)
        if len(self.pending) >= 16:
            self.last_error = "Study observation evidence capacity reached; evidence unresolved"
            return
        receipt = self.storage.append_study_observation_evidence(record)
        self.pending.append(receipt.receipt_id)
        self.reap()




_INTERVAL_FIELDS = ("interval_id", "interval_extension_version", "session_id", "capture_id",
    "span_ordinal", "study_context_token", "study_block_id", "study_generation", "resource_key",
    "first_observation_id", "last_observation_id", "first_observation_ordinal", "last_observation_ordinal",
    "first_observed_monotonic_ns", "last_observed_monotonic_ns", "observation_count",
    "continuity_max_gap_ns", "supported_duration_ns", "continuity_status", "close_reason")
_INTERVAL_CLOSE_REASONS = frozenset({"RESOURCE_CHANGE", "SCOPE_CHANGE", "GLOBAL_PAUSE", "STUDY_INACTIVE",
    "STUDY_EXIT", "BREAK_PENDING", "SESSION_STOP", "STORAGE_SHUTDOWN", "UNSUPPORTED_OBSERVATION",
    "INACTIVE_STUDY", "CAPTURE_ERROR", "OBSERVATION_SEQUENCE_GAP", "OBSERVATION_TIME_GAP",
    "NONMONOTONIC_OBSERVATION", "IDENTITY_CONFLICT", "CONTINUITY_POLICY_CHANGE"})


@dataclass(frozen=True, slots=True)
class StudyResourceIntervalRecord:
    """Completed observation-supported span, never attention or physical exit time."""
    row_json: str


def _interval_id(row):
    return hashlib.sha256(_boundary_json([1, row["capture_id"], row["span_ordinal"],
        row["session_id"], row["study_context_token"], row["first_observation_id"]]).encode()).hexdigest()


def _validate_interval(record):
    if type(record) is not StudyResourceIntervalRecord or len(record.row_json.encode()) > 16384:
        raise ValueError("Bounded immutable Study interval required")
    row = json.loads(record.row_json)
    if type(row) is not dict or set(row) != set(_INTERVAL_FIELDS):
        raise ValueError("Unexpected Study interval shape")
    if type(row["interval_extension_version"]) is not int or row["interval_extension_version"] != 1:
        raise ValueError("Unsupported Study interval contract")
    for key in ("session_id", "span_ordinal", "observation_count", "continuity_max_gap_ns",
            "first_observation_ordinal", "last_observation_ordinal", "first_observed_monotonic_ns",
            "last_observed_monotonic_ns", "supported_duration_ns"):
        minimum = 1 if key in {"session_id", "span_ordinal", "observation_count", "continuity_max_gap_ns"} else 0
        if type(row[key]) is not int or not minimum <= row[key] <= 9223372036854775807:
            raise ValueError("Invalid Study interval integer")
    for key in ("capture_id", "study_context_token", "resource_key", "first_observation_id", "last_observation_id"):
        if type(row[key]) is not str or not row[key]:
            raise ValueError("Exact Study interval identity required")
    block, generation = row["study_block_id"], row["study_generation"]
    if not (block is None and generation is None):
        if type(block) is not str or not block or type(generation) is not int or not 0 < generation <= 9223372036854775807:
            raise ValueError("Partial Study interval scope")
    count, duration = row["observation_count"], row["supported_duration_ns"]
    if (row["last_observation_ordinal"] - row["first_observation_ordinal"] != count - 1
            or row["last_observed_monotonic_ns"] - row["first_observed_monotonic_ns"] != duration):
        raise ValueError("Study interval endpoint mismatch")
    if count == 1:
        if duration != 0 or row["first_observation_id"] != row["last_observation_id"] or row["continuity_status"] != "SINGLE_OBSERVATION":
            raise ValueError("Single observation supports no positive duration")
    elif (not count - 1 <= duration <= (count - 1) * row["continuity_max_gap_ns"]
            or row["first_observation_id"] == row["last_observation_id"] or row["continuity_status"] != "SUPPORTED_SPAN"):
        raise ValueError("Unsupported Study span")
    if row["close_reason"] not in _INTERVAL_CLOSE_REASONS or row["interval_id"] != _interval_id(row):
        raise ValueError("Invalid Study interval closure/identity")
    return row


class _StudyIntervalObserver:
    """Compress consecutive exact samples into immutable supported spans.

    Only sample monotonic timestamps bound duration. Lifecycle signals flush
    existing endpoints without supplying a timestamp. A crash loses the open
    span; a new observer never resumes it. Each completed row stands alone.
    """
    def __init__(self, storage):
        self.storage = storage
        self.capture_id = uuid.uuid4().hex
        self.ordinal = 0
        self.current = None
        self.last_seen = None
        self.pending = []
        self.last_error = ""

    def reap(self):
        running = []
        for rid in self.pending:
            receipt = self.storage.receipt(rid)
            if receipt is not None and receipt.state is ReceiptState.RUNNING:
                running.append(rid)
                continue
            if receipt is None or receipt.state is not ReceiptState.COMMITTED:
                self.last_error = "Study interval write failed; missing span unavailable"
            if receipt is not None:
                self.storage.forget_receipt(rid)
        self.pending = running

    def close(self, reason):
        self.reap()
        current, self.current = self.current, None
        if current is None:
            return
        scope, identity, first, last, count, limit = current
        self.ordinal += 1  # A dropped write leaves an ordinal hole, never a guessed span.
        row = dict(interval_extension_version=1, session_id=scope[0], capture_id=self.capture_id,
            span_ordinal=self.ordinal, study_context_token=scope[1], study_block_id=scope[2], study_generation=scope[3],
            resource_key=identity[0], first_observation_id=first[0], last_observation_id=last[0],
            first_observation_ordinal=first[1], last_observation_ordinal=last[1],
            first_observed_monotonic_ns=first[2], last_observed_monotonic_ns=last[2], observation_count=count,
            continuity_max_gap_ns=limit, supported_duration_ns=last[2]-first[2],
            continuity_status="SUPPORTED_SPAN" if count > 1 else "SINGLE_OBSERVATION",
            close_reason=reason if reason in _INTERVAL_CLOSE_REASONS else "CAPTURE_ERROR")
        row["interval_id"] = _interval_id(row)
        record = StudyResourceIntervalRecord(_boundary_json(row))
        _validate_interval(record)
        if len(self.pending) >= 32:
            self.last_error = "Study interval receipt capacity reached; missing span unavailable"
            return
        receipt = self.storage.append_study_resource_interval(record)
        self.pending.append(receipt.receipt_id)
        self.reap()

    def observe(self, session_id, sample, limit, reason):
        self.reap()
        if sample is None:
            self.close(reason or "UNSUPPORTED_OBSERVATION")
            return
        from SECANT.read_model import ExactResource
        if (type(session_id) is not int or session_id <= 0 or not isinstance(sample.resource, ExactResource)
                or type(limit) is not int or not 0 < limit <= 9223372036854775807):
            raise ValueError("Authoritative Study interval sample/policy required")
        block = sample.block_id or None
        scope = (session_id, sample.study_context_token, block, sample.generation if block is not None else None)
        identity = (sample.resource.key, _boundary_json(dataclasses.asdict(sample.resource)))
        endpoint = (sample.observation_id, sample.observation_sequence, sample.observed_monotonic_ns)
        if (type(scope[1]) is not str or not scope[1] or type(identity[0]) is not str or not identity[0]
                or type(endpoint[0]) is not str or not endpoint[0]
                or any(type(v) is not int or not 0 <= v <= 9223372036854775807 for v in endpoint[1:])
                or (block is not None and (type(block) is not str or type(scope[3]) is not int or scope[3] <= 0))
                or len(_boundary_json([scope, identity, endpoint]).encode()) > 8000):
            raise ValueError("Invalid exact Study interval sample")
        seen = (scope, identity, endpoint)
        if self.last_seen is not None:
            if seen == self.last_seen:
                return  # Classification/wall-clock changes cannot turn a replay into new evidence.
            prior = self.last_seen[2]
            if endpoint[0] == prior[0] or endpoint[1] <= prior[1] or endpoint[2] <= prior[2]:
                self.close("NONMONOTONIC_OBSERVATION")
                return
        self.last_seen = seen
        if self.current is not None:
            old_scope, old_identity, first, last, count, old_limit = self.current
            gap = ("SCOPE_CHANGE" if scope != old_scope else
                "IDENTITY_CONFLICT" if identity[0] == old_identity[0] and identity != old_identity else
                "OBSERVATION_SEQUENCE_GAP" if endpoint[1] != last[1] + 1 else
                "OBSERVATION_TIME_GAP" if endpoint[2] - last[2] > old_limit else
                "CONTINUITY_POLICY_CHANGE" if limit != old_limit else
                "RESOURCE_CHANGE" if identity != old_identity else "")
            if gap:
                self.close(gap)
                if gap == "IDENTITY_CONFLICT":
                    return  # Contradictory identity is not a fresh supported endpoint.
            else:
                self.current = (scope, identity, first, endpoint, count + 1, limit)
                return
        self.current = (scope, identity, endpoint, endpoint, 1, limit)


_BOUNDARY_ENDPOINT_FIELDS = ("observation_id", "resource_key", "observation_ordinal",
    "observed_monotonic_ns", "observed_at_utc", "identity_json")
_BOUNDARY_FACT_FIELDS = ("boundary_id", "contract_version", "session_id", "capture_id",
    "boundary_ordinal", "study_context_token", "study_block_id", "study_generation") + tuple(
    prefix + name for prefix in ("from_", "to_") for name in _BOUNDARY_ENDPOINT_FIELDS) + ("capture_gap_reasons_json",)
_BOUNDARY_GAPS = frozenset({"UNSUPPORTED_OBSERVATION", "GLOBAL_PAUSE", "INACTIVE_STUDY",
    "OBSERVATION_SEQUENCE_GAP", "OBSERVATION_TIME_GAP", "NONMONOTONIC_OBSERVATION",
    "IDENTITY_CONFLICT", "RECORDING_GAP", "CAPTURE_ERROR"})


def _boundary_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _boundary_id(row):
    anchor = [1, row["capture_id"], row["boundary_ordinal"], row["session_id"],
        row["study_context_token"], row["from_observation_id"], row["to_observation_id"]]
    return hashlib.sha256(_boundary_json(anchor).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class StudyResourceBoundaryRecord:
    """Immutable pre-transport observed change; contains no classification/duration."""
    row_json: str


def _validate_boundary(record):
    from SECANT.read_model import ExactResource
    if type(record) is not StudyResourceBoundaryRecord or len(record.row_json.encode()) > 65536:
        raise ValueError("Bounded immutable Study boundary required")
    row = json.loads(record.row_json)
    if type(row) is not dict or set(row) != set(_BOUNDARY_FACT_FIELDS):
        raise ValueError("Unexpected Study boundary shape")
    if type(row["contract_version"]) is not int or row["contract_version"] != 1:
        raise ValueError("Unsupported Study boundary contract")
    for name in ("session_id", "boundary_ordinal"):
        if type(row[name]) is not int or not 0 < row[name] <= 9223372036854775807:
            raise ValueError("Positive boundary ordinal/session required")
    for name in ("capture_id", "study_context_token"):
        if type(row[name]) is not str or not row[name]:
            raise ValueError("Exact Study capture/scope required")
    block, generation = row["study_block_id"], row["study_generation"]
    if not (block is None and generation is None):
        if type(block) is not str or not block or type(generation) is not int or generation <= 0:
            raise ValueError("Partial Study block identity")
    for prefix in ("from_", "to_"):
        for name in ("observation_id", "resource_key", "observed_at_utc", "identity_json"):
            if type(row[prefix + name]) is not str or not row[prefix + name]:
                raise ValueError("Exact observation endpoint required")
        for name in ("observation_ordinal", "observed_monotonic_ns"):
            value = row[prefix + name]
            if type(value) is not int or not 0 <= value <= 9223372036854775807:
                raise ValueError("Factual observation sequence/time required")
        stamp = row[prefix + "observed_at_utc"]
        if not stamp.endswith("Z"):
            raise ValueError("Observed UTC stamp required")
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        raw = json.loads(row[prefix + "identity_json"])
        exact = ExactResource(**raw)
        if _boundary_json(dataclasses.asdict(exact)) != row[prefix + "identity_json"] or exact.key != row[prefix + "resource_key"]:
            raise ValueError("Exact resource identity mismatch")
    if (row["from_resource_key"] == row["to_resource_key"]
            or row["from_observation_id"] == row["to_observation_id"]
            or row["from_observation_ordinal"] >= row["to_observation_ordinal"]
            or row["from_observed_monotonic_ns"] >= row["to_observed_monotonic_ns"]):
        raise ValueError("An ordered observed identity change is required")
    gaps = json.loads(row["capture_gap_reasons_json"])
    if type(gaps) is not list or any(type(g) is not str or g not in _BOUNDARY_GAPS for g in gaps):
        raise ValueError("Unsupported boundary gap evidence")
    if gaps != sorted(set(gaps)) or _boundary_json(gaps) != row["capture_gap_reasons_json"]:
        raise ValueError("Canonical gap evidence required")
    if row["boundary_id"] != _boundary_id(row):
        raise ValueError("Boundary identity mismatch")
    return row


class _StudyBoundaryObserver:
    """Monitor-owned observation state, ahead of all replaceable UI transport.

    Uses the existing non-blocking writer lane. No organ decisions or Qt access.
    Every observed resource change advances ordinal even if recording fails;
    the writer independently detects holes before certifying continuity.
    """
    def __init__(self, storage):
        self.storage = storage
        self.capture_id = uuid.uuid4().hex
        self.previous = None
        self.ordinal = 0
        self.gaps = set()
        self.pending = []
        self.last_error = ""

    def gap(self, reason):
        self.gaps.add(reason if reason in _BOUNDARY_GAPS else "CAPTURE_ERROR")

    def reap(self):
        pending = []
        for receipt_id in self.pending:
            receipt = self.storage.receipt(receipt_id)
            if receipt is not None and receipt.state is ReceiptState.RUNNING:
                pending.append(receipt_id)
                continue
            if receipt is None or receipt.state is not ReceiptState.COMMITTED:
                self.gap("RECORDING_GAP")
                self.last_error = "Study boundary write failed"
            if receipt is not None:
                self.storage.forget_receipt(receipt_id)
        self.pending = pending

    def observe(self, session_id, sample, observed_at_utc, max_interval_ns, gap_reason):
        self.reap()
        if sample is None:
            self.gap(gap_reason or "UNSUPPORTED_OBSERVATION")
            return
        from SECANT.read_model import ExactResource
        if type(session_id) is not int or session_id <= 0 or not isinstance(sample.resource, ExactResource):
            raise ValueError("Authoritative Study sample required")
        block = sample.block_id or None
        scope = (session_id, sample.study_context_token, block,
            sample.generation if block is not None else None)
        endpoint = dict(observation_id=sample.observation_id, resource_key=sample.resource.key,
            observation_ordinal=sample.observation_sequence, observed_monotonic_ns=sample.observed_monotonic_ns,
            observed_at_utc=observed_at_utc, identity_json=_boundary_json(dataclasses.asdict(sample.resource)))
        if len(_boundary_json(endpoint).encode()) > 30000:
            raise ValueError("Observation endpoint exceeds capture bound")
        if self.previous is None or self.previous[0] != scope:
            self.previous = (scope, endpoint)
            self.gaps.clear()  # Never bridge unrelated Study scopes or a restart.
            return
        prior = self.previous[1]
        if endpoint == prior:
            return  # Identical observation replay is harmless.
        if (endpoint["observation_id"] == prior["observation_id"]
                or endpoint["observation_ordinal"] <= prior["observation_ordinal"]
                or endpoint["observed_monotonic_ns"] <= prior["observed_monotonic_ns"]):
            self.gap("NONMONOTONIC_OBSERVATION")
            return
        if endpoint["observation_ordinal"] != prior["observation_ordinal"] + 1:
            self.gap("OBSERVATION_SEQUENCE_GAP")
        if endpoint["observed_monotonic_ns"] - prior["observed_monotonic_ns"] > max_interval_ns:
            self.gap("OBSERVATION_TIME_GAP")
        if endpoint["resource_key"] == prior["resource_key"]:
            if endpoint["identity_json"] != prior["identity_json"]:
                self.gap("IDENTITY_CONFLICT")
                return
            self.previous = (scope, endpoint)  # Last observed A, not its first sighting.
            return
        self.previous = (scope, endpoint)
        self.ordinal += 1
        row = dict(contract_version=1, session_id=session_id, capture_id=self.capture_id,
            boundary_ordinal=self.ordinal, study_context_token=scope[1], study_block_id=scope[2],
            study_generation=scope[3], capture_gap_reasons_json=_boundary_json(sorted(self.gaps)))
        row.update({"from_" + k: v for k, v in prior.items()})
        row.update({"to_" + k: v for k, v in endpoint.items()})
        row["boundary_id"] = _boundary_id(row)
        fact = StudyResourceBoundaryRecord(_boundary_json(row))
        _validate_boundary(fact)
        if len(self.pending) >= 64:
            self.gap("RECORDING_GAP")
            self.last_error = "Study boundary receipt capacity reached"
            return
        receipt = self.storage.append_study_resource_boundary(fact)
        self.pending.append(receipt.receipt_id)
        self.gaps.clear()
        self.reap()


def _append_passive_events(storage, events, kind):
    from PERSISTENCE.secant_recorder import validate_record, validate_founding_source, META_PREFIX
    if type(events) is not tuple or not events or len(events) > 64:
        raise ValueError("Passive batch requires 1..64 immutable records")
    if sum(len(v.row_json.encode("utf-8")) for v in events) > 256 * 1024:
        raise ValueError("Passive batch exceeds byte limit")
    rows = tuple(validate_record(v, kind) for v in events)
    sources = tuple(validate_founding_source(row.pop("founding_source"), row)
        if "founding_source" in row else None for row in rows)
    table = "secant_events" if kind == "secant" else "study_resource_events"
    # SECANT identity survives attachments; first-capture provenance is immutable.
    capture = {"recorder_run_id", "recorder_received_monotonic_ns", "recorder_received_at_utc", "recording_quality"} if kind == "secant" else set()
    def write(connection):
        for row, source in zip(rows, sources):
            meta = connection.execute("SELECT value FROM myelin_meta WHERE key=?", (META_PREFIX + row["recorder_run_id"],)).fetchone()
            if not meta:
                raise ValueError("Recorder run must commit before event rows")
            prior = connection.execute(f"SELECT * FROM {table} WHERE event_id=?", (row["event_id"],)).fetchone()
            if prior:
                if any(prior[name] != value for name, value in row.items() if name not in capture):
                    raise ValueError("Conflicting immutable passive event retry")
                if source is not None:
                    recorded = connection.execute("SELECT * FROM secant_founding_source WHERE event_id=?",
                        (row["event_id"],)).fetchone()
                    # An old founding fact without provenance stays unrecorded.
                    # A retry must never backfill or replace the first capture.
                    if recorded is None or any(recorded[name] != value for name, value in source.items()):
                        raise ValueError("Conflicting immutable founding-source retry")
                if kind == "secant" and row["event_name"] == "SECANT_EPISODE_FOUNDED":
                    from PERSISTENCE.presentation_aliases import assign_secant_event
                    assign_secant_event(connection, row["event_id"])
                continue
            columns = tuple(row)
            connection.execute(f"INSERT INTO {table}(" + ",".join(columns) + ",recorded_at_utc) VALUES(" + ",".join("?" for _ in range(len(columns) + 1)) + ")", tuple(row.values()) + (_utc_now(),))
            if source is not None:
                columns = tuple(source)
                connection.execute("INSERT INTO secant_founding_source(" + ",".join(columns)
                    + ") VALUES(" + ",".join("?" for _ in columns) + ")", tuple(source.values()))
            if kind == "secant" and row["event_name"] == "SECANT_EPISODE_FOUNDED":
                from PERSISTENCE.presentation_aliases import assign_secant_event
                assign_secant_event(connection, row["event_id"])
        return TransactionResult()
    return storage._submit("append passive " + kind + " batch", write)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _field(value: object, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_value(value: object):
    return value.value if isinstance(value, Enum) else value


def _jsonable(value: object):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.name != "display_metadata" or getattr(value, field.name) is not None
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _validate_cosecant_target_payload(payload):
    """Preserve the exact frozen target structure, with no target/title lookups."""
    from COSECANT_STUDY_MODE.cosecant import (
        CosecantFactKind, CosecantReturnTarget, _validate_cosecant_return_target)
    extension = payload.get("return_target_extension_version")
    raw = payload.get("return_target")
    target = None
    if raw is not None:
        if type(raw) is not dict or set(raw) != {field.name for field in dataclasses.fields(CosecantReturnTarget)} - {"display_metadata"}:
            raise ValueError("Complete typed return-target payload required")
        target = CosecantReturnTarget(**raw)
    from SECANT.read_model import validate_display_metadata
    metadata = payload.get("return_target_display_metadata")
    if metadata is not None:
        if target is None or payload.get("kind") != "BREAK_STARTED":
            raise ValueError("Display metadata requires its frozen return target")
        validate_display_metadata(metadata, observed_ns=target.observed_monotonic_ns)
    _validate_cosecant_return_target(
        kind=CosecantFactKind.BREAK_STARTED if payload.get("kind") == "BREAK_STARTED" else None,
        extension_version=extension, target=target, study_block_id=payload.get("study_block_id"),
        study_generation=payload.get("return_target_study_generation"),
        effective_monotonic_ns=payload.get("effective_monotonic_ns"))
    if extension is None or payload.get("kind") != "BREAK_STARTED":
        for name in ("return_target_extension_version", "return_target", "return_target_study_generation"):
            payload.pop(name, None)


def _json_text(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _exact_index(value: object, name: str) -> int:
    """Return one exact non-negative int, refusing look-alikes.

    ``bool`` is a subclass of ``int`` and ``"1"`` coerces cleanly, so a plain
    ``int(value)`` would silently accept both.  Durable version and revision
    numbers are identity, and identity is never inferred from a coercion.
    """

    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _terminal(lane: SQLiteTransactionLane, receipt: TransactionReceipt) -> TransactionReceipt:
    """Drive one submission to a terminal outcome and CONSUME its receipt.

    Every caller of this helper observes the outcome inline and never looks the
    receipt up again -- storage is the whole owner, start to finish.  So this
    is the natural consumption point: once the terminal receipt has been
    handed back, the lane's registry copy has no remaining reader and is
    released (C12-D).

    A still-RUNNING receipt is deliberately NOT forgotten.  Its fate is
    unknown, monitor cleanup can still reconcile it, and an outstanding
    transaction must stay observable.
    """

    if receipt.state is ReceiptState.RUNNING:
        waited = lane.wait(receipt.receipt_id, timeout_seconds=DURABLE_WAIT_SECONDS)
        if waited is not None:
            receipt = waited
    if receipt.state is ReceiptState.RUNNING:
        # The caller must never mistake this for failure or success.  Escalate
        # the unknown terminal state; monitor cleanup can still reconcile it.
        raise RuntimeError(f"persistence is still RUNNING for {receipt.operation}")
    lane.forget(receipt.receipt_id)
    return receipt


# ---------------------------------------------------------------------------
# Shared report/session safety.  This is harvested from the old strong gate,
# but kept here because the clean plan assigns report-safety helpers to storage.
# ---------------------------------------------------------------------------

ACTIVE_SESSION_MESSAGE = (
    "Report generation is unavailable while MYELIN monitoring or session "
    "activity is active. Stop the current session, then try again."
)
EXPORT_IN_PROGRESS_MESSAGE = (
    "Another report export is already in progress. Wait for it to finish, then try again."
)
SESSION_STATE_UNAVAILABLE_MESSAGE = (
    "Report generation is unavailable because MYELIN could not verify the current session state."
)


class ReportRefusalCode(str, Enum):
    ACTIVE_SESSION = "active_session"
    EXPORT_IN_PROGRESS = "export_in_progress"
    SESSION_STATE_UNAVAILABLE = "session_state_unavailable"


@dataclass(frozen=True, slots=True)
class ReportAccessRefusal:
    code: ReportRefusalCode
    message: str
    active_export_owner: str | None = None


class ReportExportRefused(RuntimeError):
    def __init__(self, refusal: ReportAccessRefusal) -> None:
        super().__init__(refusal.message)
        self.refusal = refusal
        self.user_message = refusal.message


class _SessionActiveSource:
    def __init__(self, provider: Callable[[], bool]) -> None:
        self._strong: Callable[[], bool] | None = None
        self._weak = None
        try:
            self._weak = weakref.WeakMethod(provider)
        except TypeError:
            self._strong = provider

    def resolve(self):
        return self._weak() if self._weak is not None else self._strong


class SessionActiveSourceBinding:
    def __init__(self, coordinator: "ReportAccessCoordinator", token: object) -> None:
        self._coordinator = coordinator
        self._token = token
        self._released = False

    def release(self) -> bool:
        if self._released:
            return False
        released = self._coordinator._unbind_session_active_source(self._token)
        self._released = True
        return released


class SessionStartReservation:
    def __init__(self, coordinator: "ReportAccessCoordinator") -> None:
        self._coordinator = coordinator
        self._released = False

    def release(self) -> bool:
        return self._coordinator.end_session_start(self)


class ReportExportLease:
    def __init__(self, coordinator: "ReportAccessCoordinator", owner: str) -> None:
        self._coordinator = coordinator
        self.owner = owner
        self._released = False

    def release(self) -> bool:
        return self._coordinator.end_export(self)


class ReportAccessCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._source: _SessionActiveSource | None = None
        self._source_token: object | None = None
        self._active_export: ReportExportLease | None = None
        self._session_start: SessionStartReservation | None = None

    def bind_session_active_source(self, provider: Callable[[], bool]) -> SessionActiveSourceBinding:
        if not callable(provider):
            raise TypeError("session-active source must be callable")
        with self._lock:
            if self._source is not None and self._source.resolve() is not None:
                raise RuntimeError("a session-active source is already bound")
            token = object()
            self._source = _SessionActiveSource(provider)
            self._source_token = token
            return SessionActiveSourceBinding(self, token)

    def _unbind_session_active_source(self, token: object) -> bool:
        with self._lock:
            if self._source_token is not token:
                return False
            self._source = None
            self._source_token = None
            return True

    def _session_state(self) -> tuple[bool, bool]:
        if self._source is None:
            return False, False
        provider = self._source.resolve()
        if provider is None:
            return False, True
        try:
            return bool(provider()), False
        except Exception:
            return False, True

    def refusal(self) -> ReportAccessRefusal | None:
        with self._lock:
            active, unavailable = self._session_state()
            if unavailable:
                return ReportAccessRefusal(
                    ReportRefusalCode.SESSION_STATE_UNAVAILABLE,
                    SESSION_STATE_UNAVAILABLE_MESSAGE,
                )
            if active or self._session_start is not None:
                return ReportAccessRefusal(
                    ReportRefusalCode.ACTIVE_SESSION,
                    ACTIVE_SESSION_MESSAGE,
                )
            if self._active_export is not None:
                return ReportAccessRefusal(
                    ReportRefusalCode.EXPORT_IN_PROGRESS,
                    EXPORT_IN_PROGRESS_MESSAGE,
                    self._active_export.owner,
                )
            return None

    def begin_session_start(self) -> SessionStartReservation:
        with self._lock:
            refusal = self.refusal()
            if refusal is not None:
                raise ReportExportRefused(refusal)
            reservation = SessionStartReservation(self)
            self._session_start = reservation
            return reservation

    def end_session_start(self, reservation: SessionStartReservation) -> bool:
        with self._lock:
            if reservation._released:
                return False
            if self._session_start is not reservation:
                raise RuntimeError("session-start reservation is not active")
            self._session_start = None
            reservation._released = True
            return True

    def begin_export(self, owner: str) -> ReportExportLease:
        clean_owner = " ".join(str(owner).split())[:80]
        if not clean_owner:
            raise ValueError("report export owner must not be empty")
        with self._lock:
            refusal = self.refusal()
            if refusal is not None:
                raise ReportExportRefused(refusal)
            lease = ReportExportLease(self, clean_owner)
            self._active_export = lease
            return lease

    def end_export(self, lease: ReportExportLease) -> bool:
        with self._lock:
            if lease._released:
                return False
            if self._active_export is not lease:
                raise RuntimeError("report export lease is not the active owner")
            self._active_export = None
            lease._released = True
            return True


REPORT_ACCESS_COORDINATOR = ReportAccessCoordinator()


# ---------------------------------------------------------------------------
# Engine storage
# ---------------------------------------------------------------------------

class _SharedStorageLane:
    """The one process-wide SQLite write lane, held by explicit owner tokens.

    MYELIN serialises every durable write through a single ordered lane.  That
    held while a Monitor session was the only writer, but Planner and Notes
    must persist OUTSIDE a monitoring session, so more than one
    ``EngineStorage`` facade now exists at once.  A lane per facade would give
    one database two independent writer queues -- two orderings and two
    shutdown lifetimes -- which is exactly what the architecture forbids.

    The facade therefore stays per-owner while the LANE becomes shared:

        Control Station acquires  -> lane created,    owners = 1
        Monitor acquires          -> same lane,       owners = 2
        Monitor releases          -> lane KEPT ALIVE, owners = 1
        Control Station releases  -> lane shut down,  owners = 0

    Two properties are load-bearing and easy to get subtly wrong.

    OWNERSHIP IS IDENTITY, NOT A COUNT.  Owners are held as a set of opaque
    tokens, so releasing the same owner twice is arithmetically incapable of
    evicting a different owner.  A bare integer could be decremented twice by
    one facade and close a lane another facade was still writing through.

    THE SLOT IS NOT FREED UNTIL THE OLD WRITER IS GONE.  A lane does not
    vanish when ``shutdown`` is called: it marks itself closed, drains its
    FIFO and joins its writer thread.  Clearing ``_lane`` before that finishes
    would let the next ``acquire`` build a second writer against the same
    database while the first was still draining -- briefly restoring the exact
    two-lane condition this class exists to prevent.  So the lane stays
    registered for the whole drain and the state machine gates acquisition:

        IDLE     -> no lane; the next acquire builds one
        ACTIVE   -> lane exists and is accepting owners
        CLOSING  -> last owner released; old writer still draining.
                    acquire WAITS; it never builds a second lane
        POISONED -> the drain failed or timed out.  We cannot prove the old
                    writer is gone, so we never start another one.  Every
                    later acquisition fails closed until the process restarts

    Failing closed is deliberate.  A second writer against a half-drained
    database is a correctness failure; refusing new persistence is an outage
    the operator can see.
    """

    IDLE: Final = "IDLE"
    ACTIVE: Final = "ACTIVE"
    CLOSING: Final = "CLOSING"
    POISONED: Final = "POISONED"

    #: How long an acquisition waits for an in-progress drain before giving up.
    CLOSING_WAIT_SECONDS: Final = DURABLE_WAIT_SECONDS + 2.0

    _lock = threading.RLock()
    _ready = threading.Condition(_lock)
    _lane: SQLiteTransactionLane | None = None
    _owners: set = set()
    _state: str = IDLE

    @classmethod
    def acquire(cls, owner_token: object) -> SQLiteTransactionLane:
        with cls._ready:
            deadline = time.monotonic() + cls.CLOSING_WAIT_SECONDS
            while cls._state == cls.CLOSING:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "shared persistence is still closing; refusing to open "
                        "a second SQLite lane"
                    )
                cls._ready.wait(timeout=remaining)
            if cls._state == cls.POISONED:
                raise RuntimeError(
                    "shared persistence is unavailable: the previous SQLite "
                    "lane did not shut down cleanly. Restart MYELIN."
                )
            if cls._lane is None:
                cls._lane = SQLiteTransactionLane()
                cls._state = cls.ACTIVE
            cls._owners.add(owner_token)
            return cls._lane

    @classmethod
    def release(cls, lane: SQLiteTransactionLane, owner_token: object) -> None:
        with cls._ready:
            # Releasing a token that is not registered, or one holding a lane
            # that has already been superseded, must change nothing at all.
            if cls._lane is not lane or owner_token not in cls._owners:
                return
            cls._owners.discard(owner_token)
            if cls._owners:
                return
            # Last owner.  Mark CLOSING but KEEP the lane registered so no
            # acquisition can slip a second writer into the gap.
            cls._state = cls.CLOSING
            closing = cls._lane

        try:
            # Drain OUTSIDE the lock: the lane joins its writer thread, and
            # holding the class lock across that would stall every acquirer.
            closing.shutdown(timeout_seconds=DURABLE_WAIT_SECONDS)
        except BaseException:
            with cls._ready:
                # The old writer's fate is unknown, so the slot is never
                # reopened.  Do NOT clear _lane here.
                cls._state = cls.POISONED
                cls._ready.notify_all()
            raise

        with cls._ready:
            cls._lane = None
            cls._state = cls.IDLE
            cls._ready.notify_all()

    @classmethod
    def owners(cls) -> int:
        with cls._lock:
            return len(cls._owners)

# ---------------------------------------------------------------------------
# Schema bootstrap.  C12-B.
# ---------------------------------------------------------------------------
#
# ``ensure_production_schema()`` is NOT a read.  It opens its own writable
# SQLite connection and runs ``BEGIN IMMEDIATE``.  Calling it from runtime
# reader entry points therefore let a dashboard refresh open a second writable
# transaction against the database the shared writer lane already owned --
# exactly the two-writer condition ``_SharedStorageLane`` exists to prevent.
#
# The law is now:
#
#     PROCESS BOOTSTRAP  -> schema installed and verified, exactly once
#     runtime writes     -> ONE shared SQLite lane
#     runtime reads      -> read-only connections, never schema mutation
#
# Bootstrap stays reachable from storage so a standalone tool or LAB process
# that never goes through the launcher still gets a usable database.  It is
# latched, so the launcher's startup call is the only one that does work in a
# normal MYELIN process.  The owners check makes the ordering an invariant
# rather than a convention: once a shared writer lane exists, its creator has
# already bootstrapped, so reaching an uninstalled schema here would mean a
# lane was built out of order and we fail closed instead of opening a second
# writable connection underneath it.

_SCHEMA_BOOTSTRAP_LOCK = threading.Lock()
_SCHEMA_BOOTSTRAPPED = False


def bootstrap_production_schema() -> None:
    """Install and verify the production schema once per process."""

    global _SCHEMA_BOOTSTRAPPED
    with _SCHEMA_BOOTSTRAP_LOCK:
        if _SCHEMA_BOOTSTRAPPED:
            return
        if _SharedStorageLane.owners():
            raise RuntimeError(
                "schema bootstrap was reached while a shared SQLite writer "
                "lane is already active; refusing to open a second writable "
                "connection"
            )
        ensure_production_schema()
        _SCHEMA_BOOTSTRAPPED = True


class EngineStorage:
    """One durable-writer facade over the shared lane, plus readers.

    Each facade owns its own lifetime but shares one ordered write lane with
    every other facade in the process.  ``shutdown`` releases this facade's
    ownership; the lane closes only when the last owner lets go.
    """

    def __init__(self) -> None:
        # Bootstrap, not reinstall.  A second facade joining a live lane does
        # no schema work at all (C12-B).
        bootstrap_production_schema()
        # An opaque per-facade token.  Ownership of the shared lane is held by
        # identity, so this facade releasing twice can never evict another.
        self._owner_token = object()
        self._lifetime_lock = threading.Lock()
        self._closed = False
        self._lane = _SharedStorageLane.acquire(self._owner_token)
        self._study_boundary_observer = None
        self._study_interval_observer = None
        self._study_observation_evidence_capture = None

    # The shared lane is deliberately NOT exposed.  Publishing it would hand
    # every consumer a ``shutdown()`` handle on process-wide persistence and
    # let them bypass the owner protocol entirely.  Writes go through the
    # methods below; the LAB inspects ``_lane`` for white-box assertions.

    # ------------------------------------------------------------------
    # Write admission.  C12-A.
    # ------------------------------------------------------------------
    #
    # ``shutdown`` ends THIS facade's writer lifetime, but the shared lane
    # outlives it whenever another owner is still holding on.  A write method
    # calling ``self._lane.submit`` directly therefore could not tell the
    # difference between "the lane is alive" and "I am still allowed to use
    # it", and a released owner could commit durable rows after its own
    # lifetime had ended.
    #
    # Every MUTATING operation now enters the lane through ``_submit``, so
    # closed-facade admission is decided in exactly one place.  Reads are NOT
    # routed here: they open their own read-only connection and never touch
    # the lane, so a closed facade stays readable.  ``receipt``/``wait`` are
    # observations of work this facade submitted while it was still open --
    # refusing those would strand a caller that shut down mid-flight.

    def _require_open(self) -> None:
        with self._lifetime_lock:
            if self._closed:
                raise RuntimeError(
                    "EngineStorage facade is closed; this owner released the "
                    "shared persistence lane and may no longer write"
                )

    def _submit(self, operation: str, callback) -> TransactionReceipt:
        self._require_open()
        return self._lane.submit(operation, callback)

    def capture_study_resource_observation(self, *, session_id, sample=None,
            observed_at_utc="", max_interval_ns=0, gap_reason=""):
        """Observational side channel; failure must never affect Monitor decisions."""
        if self._study_boundary_observer is None:
            self._study_boundary_observer = _StudyBoundaryObserver(self)
        observer = self._study_boundary_observer
        try:
            observer.observe(session_id, sample, observed_at_utc, max_interval_ns, gap_reason)
        except Exception as error:
            observer.gap("CAPTURE_ERROR")
            observer.last_error = type(error).__name__ + ": " + str(error)[:180]
        # Independent capture and failure containment preserve Correction 2.
        if self._study_interval_observer is None:
            self._study_interval_observer = _StudyIntervalObserver(self)
        intervals = self._study_interval_observer
        try:
            intervals.observe(session_id, sample, max_interval_ns, gap_reason)
        except Exception as error:
            intervals.current = None  # Incomplete evidence must never extend a later span.
            intervals.last_error = type(error).__name__ + ": " + str(error)[:180]
        return observer.last_error or intervals.last_error

    def end_study_resource_interval(self, reason="SESSION_STOP"):
        """Flush only already-observed evidence; no lifecycle timestamp is accepted."""
        observer = self._study_interval_observer
        if observer is not None:
            try:
                observer.close(reason)
            except Exception as error:
                observer.current = None
                observer.last_error = type(error).__name__ + ": " + str(error)[:180]

    def append_study_resource_interval(self, record):
        row = _validate_interval(record)
        def write(connection):
            prior = connection.execute("SELECT * FROM study_resource_intervals WHERE interval_id=?",
                (row["interval_id"],)).fetchone()
            if prior is not None:
                if any(prior[name] != value for name, value in row.items()):
                    raise ValueError("Conflicting immutable Study interval retry")
                return TransactionResult()
            overlap = connection.execute("SELECT interval_id FROM study_resource_intervals WHERE capture_id=? "
                "AND first_observation_ordinal<=? AND last_observation_ordinal>=? LIMIT 1",
                (row["capture_id"], row["last_observation_ordinal"], row["first_observation_ordinal"])).fetchone()
            if overlap is not None:
                raise ValueError("Overlapping Study interval evidence")
            connection.execute("INSERT INTO study_resource_intervals(" + ",".join(row)
                + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
            return TransactionResult()
        return self._submit("append supported Study foreground interval", write)

    def append_study_resource_boundary(self, record):
        row = _validate_boundary(record)
        def write(connection):
            prior = connection.execute("SELECT * FROM study_resource_boundaries WHERE boundary_id=?",
                (row["boundary_id"],)).fetchone()
            if prior is not None:
                if any(prior[name] != value for name, value in row.items()):
                    raise ValueError("Conflicting immutable Study boundary retry")
                return TransactionResult()
            # FIFO commit order makes a skipped/failed earlier boundary visible
            # even when its failure receipt has not reached the capture thread.
            previous = connection.execute("SELECT MAX(boundary_ordinal) FROM study_resource_boundaries "
                "WHERE capture_id=?", (row["capture_id"],)).fetchone()[0] or 0
            gaps = set(json.loads(row["capture_gap_reasons_json"]))
            if previous != row["boundary_ordinal"] - 1:
                gaps.add("RECORDING_GAP")
            durable = dict(row, continuity="CHANGE_ACROSS_EVIDENCE_GAP" if gaps else "CONTIGUOUS_OBSERVED_CHANGE",
                gap_reasons_json=_boundary_json(sorted(gaps)))
            connection.execute("INSERT INTO study_resource_boundaries(" + ",".join(durable)
                + ") VALUES(" + ",".join("?" for _ in durable) + ")", tuple(durable.values()))
            return TransactionResult()
        return self._submit("append Study resource boundary", write)

    def capture_study_observation_evidence(self, *, session_id, authority_json, request_id="", applied_ns=None):
        """Independent evidence side channel; cannot change physiology decisions."""
        if self._study_observation_evidence_capture is None:
            self._study_observation_evidence_capture = _StudyObservationEvidenceCapture(self)
        capture = self._study_observation_evidence_capture
        try:
            capture.capture(session_id, authority_json, request_id, applied_ns)
        except Exception as error:
            capture.last_error = type(error).__name__ + ": " + str(error)[:180]
        return capture.last_error

    def append_study_observation_evidence(self, record):
        row = _validate_observation_evidence(record)
        def write(connection):
            prior = connection.execute("SELECT * FROM study_resource_observation_evidence WHERE evidence_id=?",
                (row["evidence_id"],)).fetchone()
            if prior is not None:
                if any(prior[name] != value for name, value in row.items()):
                    raise ValueError("Conflicting immutable Study observation evidence retry")
                return TransactionResult()
            connection.execute("INSERT INTO study_resource_observation_evidence(" + ",".join(row)
                + ") VALUES(" + ",".join("?" for _ in row) + ")", tuple(row.values()))
            return TransactionResult()
        return self._submit("append authoritative Study observation evidence", write)

    def load_profile_learning(self, *, profile_key: str) -> ProfileLearningState:
        """Load the latest committed learning state for one profile.

        Missing rows are represented explicitly as an unlearned state.  This
        read never invents a fallback lambda.

        The stored ``model_version`` is reported faithfully, whatever it says.
        Storage states what is stored; it does not decide whether that
        generation is scientifically eligible for the session about to start --
        that judgement belongs to the session composition in
        ``CORE_ENGINE.monitor``.
        """

        key = _profile_learning_key(profile_key)
        connection = connect_database(read_only=True)
        try:
            row = connection.execute(
                "SELECT profile_key, learned_lambda, learned_return_latency_seconds, "
                "valid_session_count, valid_episode_count, last_learning_session_id, "
                "last_updated_utc, model_version FROM profile_learning_state "
                "WHERE profile_key=?",
                (key,),
            ).fetchone()
        finally:
            connection.close()
        return _profile_learning_state_from_row(key, row)

    def update_profile_learning_session(
        self,
        *,
        profile_key: str,
        session_id: int,
        session_lambda: float,
        session_return_latency_seconds: float,
        valid_episode_count: int,
    ) -> TransactionReceipt:
        """Submit one completed-session learning update.

        ``session_return_latency_seconds`` is factual previous-session MIRL
        recovery evidence (the mean of this session's ACTUAL verified return
        latencies, computed upstream). ``session_lambda`` is the matching
        Ebbinghaus recovery-rate evidence derived upstream. Storage preserves
        both facts and does not choose how a future session normalizes them.

        Policy boundary: persistence never invents a reference return time, a
        reference lambda, factor bounds, or SINE timing. Those are not storage
        decisions.

        BUGFIX (locked-design conformance): this previously stored a
        cumulative, unweighted running mean of ``session_lambda`` across the
        profile's ENTIRE session history, so a session from months ago and
        yesterday's session carried equal weight forever. That directly
        contradicted the project's explicitly locked rule: the stored values
        must reflect the previous ELIGIBLE session only, never an average of
        many. ``learned_lambda`` and ``learned_return_latency_seconds`` are
        both a pure replace -- the freshest eligible session's values become
        the new stored values outright.

        ``valid_session_count`` and ``valid_episode_count`` remain cumulative
        lifetime counters (how many sessions/episodes have ever contributed
        learning data). That is informational provenance only -- it no
        longer weights or blends into either stored value in any way.

        The returned receipt must reach COMMITTED before callers treat the new
        profile state as authoritative.
        """

        key = _profile_learning_key(profile_key)
        sid = _positive_int(session_id, name="session_id")
        episode_count = _positive_int(
            valid_episode_count, name="valid_episode_count"
        )
        observed_lambda = _positive_finite_number(session_lambda, name="session_lambda")
        observed_latency = _positive_finite_number(
            session_return_latency_seconds, name="session_return_latency_seconds"
        )

        def write(connection):
            session = connection.execute(
                "SELECT profile_type, closed_at_utc FROM sessions WHERE id=?",
                (sid,),
            ).fetchone()
            if session is None:
                raise RuntimeError("profile learning session does not exist")
            session_profile = str(session["profile_type"] or "").strip().lower()
            if session_profile != key:
                raise RuntimeError("profile learning session belongs to another profile")
            if not str(session["closed_at_utc"] or "").strip():
                raise RuntimeError("profile learning requires a completed session")

            row = connection.execute(
                "SELECT learned_lambda, learned_return_latency_seconds, "
                "valid_session_count, valid_episode_count, "
                "last_learning_session_id FROM profile_learning_state "
                "WHERE profile_key=?",
                (key,),
            ).fetchone()

            if row is None or row["learned_lambda"] is None:
                if row is not None:
                    if (
                        int(row["valid_session_count"]) != 0
                        or int(row["valid_episode_count"]) != 0
                        or row["last_learning_session_id"] is not None
                    ):
                        raise RuntimeError(
                            "unlearned profile row contains invalid learning counters"
                        )
                new_session_count = 1
                new_episode_count = episode_count
                # First-ever eligible session for this profile: nothing to
                # replace, the observed values are simply the new state.
                new_lambda = observed_lambda
                new_latency = observed_latency
                if row is None:
                    connection.execute(
                        "INSERT INTO profile_learning_state("
                        "profile_key, learned_lambda, learned_return_latency_seconds, "
                        "valid_session_count, valid_episode_count, "
                        "last_learning_session_id, last_updated_utc, model_version"
                        ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            key,
                            new_lambda,
                            new_latency,
                            new_session_count,
                            new_episode_count,
                            sid,
                            _utc_now(),
                            # Explicit, never the column DEFAULT: relying on the
                            # default would stamp brand-new onset-based evidence
                            # with the legacy v1 marker.
                            PROFILE_LEARNING_MODEL_VERSION,
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE profile_learning_state SET learned_lambda=?, "
                        "learned_return_latency_seconds=?, "
                        "valid_session_count=?, valid_episode_count=?, "
                        "last_learning_session_id=?, last_updated_utc=?, "
                        "model_version=? WHERE profile_key=?",
                        (
                            new_lambda,
                            new_latency,
                            new_session_count,
                            new_episode_count,
                            sid,
                            _utc_now(),
                            PROFILE_LEARNING_MODEL_VERSION,
                            key,
                        ),
                    )
            else:
                old_session_count = int(row["valid_session_count"])
                old_episode_count = int(row["valid_episode_count"])
                last_session_id = int(row["last_learning_session_id"])
                if old_session_count <= 0:
                    raise RuntimeError("stored learned profile state has invalid session count")
                if old_episode_count < old_session_count:
                    raise RuntimeError("stored learned profile state has invalid episode count")
                if sid <= last_session_id:
                    raise RuntimeError(
                        "profile learning update is duplicate or out of chronological order"
                    )

                new_session_count = old_session_count + 1
                new_episode_count = old_episode_count + episode_count
                # PREVIOUS-ELIGIBLE-SESSION-ONLY: replace outright. Do not
                # blend with the old stored values -- that would resurrect the
                # running mean this fix removes. The lifetime counters above
                # still accumulate for provenance/telemetry; neither stored
                # value does.
                new_lambda = observed_lambda
                new_latency = observed_latency
                if not math.isfinite(new_lambda) or new_lambda <= 0.0:
                    raise RuntimeError("observed session lambda is not finite and positive")
                if not math.isfinite(new_latency) or new_latency <= 0.0:
                    raise RuntimeError(
                        "observed session return latency is not finite and positive"
                    )
                connection.execute(
                    # This is also the natural v1 -> v2 upgrade path: a legacy
                    # row keeps its lifetime counters and simply has its stale
                    # scalars replaced by real onset-based evidence, and is
                    # re-stamped with the generation that produced them.  No
                    # migration, no reset, no fabricated data.
                    "UPDATE profile_learning_state SET learned_lambda=?, "
                    "learned_return_latency_seconds=?, "
                    "valid_session_count=?, valid_episode_count=?, "
                    "last_learning_session_id=?, last_updated_utc=?, "
                    "model_version=? WHERE profile_key=?",
                    (
                        new_lambda,
                        new_latency,
                        new_session_count,
                        new_episode_count,
                        sid,
                        _utc_now(),
                        PROFILE_LEARNING_MODEL_VERSION,
                        key,
                    ),
                )

            return TransactionResult(
                result_id=new_session_count,
                session_id=sid,
            )

        return self._submit("update profile learning session", write)

    def open_monitor_session(self, *, profile_type: str) -> TransactionReceipt:
        profile = " ".join(str(profile_type).split())[:80]
        if not profile:
            raise ValueError("profile_type must not be empty")

        def write(connection):
            cursor = connection.execute(
                "INSERT INTO sessions(profile_type, started_at_utc) VALUES(?, ?)",
                (profile, _utc_now()),
            )
            session_id = int(cursor.lastrowid)
            return TransactionResult(result_id=session_id, session_id=session_id)

        return self._submit("open monitor session", write)

    def persist_trigger(self, *, session_id: int, candidate: object) -> TransactionReceipt:
        if type(session_id) is not int or session_id <= 0:
            raise ValueError("session_id must be positive")
        candidate_uid = str(_field(candidate, "candidate_uid", "") or "")
        if not candidate_uid:
            raise ValueError("trigger candidate has no candidate_uid")
        candidate_session = _field(candidate, "session_id")
        if candidate_session != session_id:
            raise ValueError("trigger candidate session does not match storage session")
        evidence = _field(candidate, "evidence")
        occurred_ns = int(_field(evidence, "observed_monotonic_ns", 0) or 0)
        if occurred_ns <= 0:
            raise ValueError("trigger candidate has no positive observation time")
        payload = _json_text(candidate)

        def write(connection):
            cursor = connection.execute(
                "INSERT INTO triggers(session_id, candidate_uid, occurred_monotonic_ns, payload_json, created_at_utc) "
                "VALUES(?, ?, ?, ?, ?)",
                (session_id, candidate_uid, occurred_ns, payload, _utc_now()),
            )
            return TransactionResult(result_id=int(cursor.lastrowid), session_id=session_id)

        return self._submit("persist trigger", write)

    def receipt(self, receipt_id: str) -> TransactionReceipt | None:
        return self._lane.receipt(receipt_id)

    def wait(self, receipt_id: str, *, timeout_seconds: float) -> TransactionReceipt | None:
        return self._lane.wait(receipt_id, timeout_seconds=timeout_seconds)

    def forget_receipt(self, receipt_id: str) -> bool:
        """Release a terminal receipt this facade handed to its owner.

        Storage consumes the receipts it owns end to end (see ``_terminal``).
        The lifecycle receipts returned raw -- session open/close, emergency,
        trigger persistence -- belong to their caller, so only that caller can
        say when it has finished reading one.  A RUNNING receipt is refused.
        """

        return self._lane.forget(receipt_id)

    def close_monitor_session(self, *, session_id: int, reason: str) -> TransactionReceipt:
        clean_reason = " ".join(str(reason).split())[:80] or "STOPPED"

        def write(connection):
            cursor = connection.execute(
                "UPDATE sessions SET closed_at_utc=?, close_reason=? WHERE id=? AND closed_at_utc IS NULL",
                (_utc_now(), clean_reason, session_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("session close did not update exactly one open session")
            return TransactionResult(result_id=session_id, session_id=session_id)

        return self._submit("close monitor session", write)

    def record_emergency(self, *, session_id: int) -> TransactionReceipt:
        def write(connection):
            session = connection.execute(
                "SELECT id FROM sessions WHERE id=? AND closed_at_utc IS NULL",
                (session_id,),
            ).fetchone()
            if session is None:
                raise RuntimeError("emergency session is not open")
            cursor = connection.execute(
                "INSERT INTO emergency_events(session_id, occurred_at_utc) VALUES(?, ?)",
                (session_id, _utc_now()),
            )
            emergency_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE sessions SET emergency=1 WHERE id=?",
                (session_id,),
            )
            connection.execute(
                "INSERT INTO emergency_followup(singleton_id, pending, emergency_event_id, reason_code, answered_at_utc) "
                "VALUES(1, 1, ?, '', '') "
                "ON CONFLICT(singleton_id) DO UPDATE SET pending=1, emergency_event_id=excluded.emergency_event_id, reason_code='', answered_at_utc=''",
                (emergency_id,),
            )
            return TransactionResult(result_id=emergency_id, session_id=session_id)

        return self._submit("record emergency", write)

    def append_cosine_events(self, events) -> bool:
        batch = tuple(events)
        if not batch:
            return True
        raw_parent_session_ids = [_field(event, "session_id") for event in batch]
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in raw_parent_session_ids):
            return False
        parent_session_ids = set(raw_parent_session_ids)
        cosine_session_ids = {str(_field(event, "cosine_session_id", "")) for event in batch}
        generations = {int(_field(event, "generation", 0) or 0) for event in batch}
        event_ids = [str(_field(event, "event_id", "")) for event in batch]
        sequences = [int(_field(event, "sequence", 0) or 0) for event in batch]
        if len(parent_session_ids) != 1:
            return False
        if len(cosine_session_ids) != 1 or "" in cosine_session_ids:
            return False
        if len(generations) != 1 or 0 in generations:
            return False
        if len(event_ids) != len(set(event_ids)) or any(not value for value in event_ids):
            return False
        if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
            return False
        parent_session_id = next(iter(parent_session_ids))
        cosine_session_id = next(iter(cosine_session_ids))
        generation = next(iter(generations))

        def write(connection):
            existing_rows = connection.execute(
                "SELECT session_id, generation, MAX(sequence) AS max_sequence "
                "FROM cosine_events WHERE cosine_session_id=? "
                "GROUP BY session_id, generation",
                (cosine_session_id,),
            ).fetchall()
            if len(existing_rows) > 1:
                raise RuntimeError("COSINE durable episode has conflicting identity")
            existing = existing_rows[0] if existing_rows else None
            if existing is not None and existing["max_sequence"] is not None:
                if existing["session_id"] is None or int(existing["session_id"]) != parent_session_id:
                    raise RuntimeError("COSINE parent session changed inside one durable episode")
                if int(existing["generation"]) != generation:
                    raise RuntimeError("COSINE generation changed inside one durable session")
                expected = int(existing["max_sequence"]) + 1
            else:
                expected = 1
            if sequences[0] != expected:
                raise RuntimeError("COSINE event sequence is not contiguous")
            for event in batch:
                connection.execute(
                    "INSERT INTO cosine_events(event_id, session_id, cosine_session_id, generation, sequence, event_name, event_class, occurred_at_utc, monotonic_ns, platform_key, content_title, request_id, evidence_token, payload_json, schema_version) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(_field(event, "event_id", "")),
                        parent_session_id,
                        cosine_session_id,
                        generation,
                        int(_field(event, "sequence", 0)),
                        str(_field(event, "event_name", "")),
                        str(_enum_value(_field(event, "event_class", ""))),
                        str(_field(event, "occurred_at_utc", "")),
                        int(_field(event, "monotonic_ns", 0)),
                        str(_field(event, "platform_key", "")),
                        str(_field(event, "content_title", ""))[:500],
                        str(_field(event, "request_id", "")),
                        str(_field(event, "evidence_token", "")),
                        str(_field(event, "payload_json", "{}")),
                        str(_field(event, "schema_version", "")),
                    ),
                )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("append COSINE event batch", write))
        return receipt.state is ReceiptState.COMMITTED

    def append_mine_events(self, events) -> bool:
        """Commit one contiguous MINE generation batch on the shared lane.

        Candidate facts legitimately precede a formal ``mine_episode_id``.
        Continuity is therefore parent-session + generation + sequence; the
        episode identity is descriptive and may change from empty to formal
        within that one stream.
        """

        batch = tuple(events)
        if not batch:
            return True
        raw_parent_ids = [_field(event, "parent_session_id") for event in batch]
        raw_generations = [_field(event, "generation") for event in batch]
        raw_sequences = [_field(event, "sequence") for event in batch]
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (*raw_parent_ids, *raw_generations, *raw_sequences)
        ):
            return False
        parent_ids = set(raw_parent_ids)
        generations = set(raw_generations)
        event_ids = [str(_field(event, "event_id", "") or "") for event in batch]
        sequences = list(raw_sequences)
        if len(parent_ids) != 1 or len(generations) != 1:
            return False
        if len(event_ids) != len(set(event_ids)) or any(not value for value in event_ids):
            return False
        if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
            return False
        parent_id = next(iter(parent_ids))
        generation = next(iter(generations))

        def write(connection):
            parent = connection.execute(
                "SELECT id FROM sessions WHERE id=?", (parent_id,)
            ).fetchone()
            if parent is None:
                raise RuntimeError("MINE parent session is not durable")
            existing = connection.execute(
                "SELECT MAX(sequence) AS max_sequence FROM mine_events "
                "WHERE session_id=? AND generation=?",
                (parent_id, generation),
            ).fetchone()
            expected = (
                int(existing["max_sequence"]) + 1
                if existing is not None and existing["max_sequence"] is not None
                else 1
            )
            if sequences[0] != expected:
                raise RuntimeError("MINE event sequence is not contiguous")
            for event in batch:
                connection.execute(
                    "INSERT INTO mine_events(event_id, session_id, mine_episode_id, generation, sequence, event_name, event_class, occurred_at_utc, monotonic_ns, platform_key, platform_label, request_id, evidence_token, payload_json, schema_version) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(_field(event, "event_id", "")),
                        parent_id,
                        str(_field(event, "mine_episode_id", "")),
                        generation,
                        int(_field(event, "sequence", 0)),
                        str(_field(event, "event_name", "")),
                        str(_enum_value(_field(event, "event_class", ""))),
                        str(_field(event, "occurred_at_utc", "")),
                        int(_field(event, "monotonic_ns", 0)),
                        str(_field(event, "platform_key", "")),
                        str(_field(event, "platform_label", "")),
                        str(_field(event, "request_id", "")),
                        str(_field(event, "evidence_token", "")),
                        str(_field(event, "payload_json", "{}")),
                        str(_field(event, "schema_version", "")),
                    ),
                )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("append MINE event batch", write))
        return receipt.state is ReceiptState.COMMITTED

    def append_mirl_events(self, events) -> bool:
        batch = tuple(events)
        if not batch:
            return True

        def write(connection):
            for event in batch:
                connection.execute(
                    "INSERT INTO mirl_events(event_id, session_id, episode_id, episode_sequence, event_name, occurred_monotonic_ns, payload_json, created_at_utc) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(_field(event, "event_id", "")),
                        _field(event, "session_id"),
                        str(_field(event, "episode_id", "")),
                        int(_field(event, "episode_sequence", 0) or 0),
                        str(_enum_value(_field(event, "event_name", ""))),
                        int(_field(event, "occurred_monotonic_ns", 0) or 0),
                        _json_text(event),
                        _utc_now(),
                    ),
                )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("append MIRL event batch", write))
        return receipt.state is ReceiptState.COMMITTED

    def append_sine_facts(self, facts) -> bool:
        batch = tuple(facts)
        if not batch:
            return True

        def write(connection):
            for fact in batch:
                connection.execute(
                    "INSERT INTO sine_facts(session_id, episode_uid, candidate_uid, kind, popup_request_id, occurred_monotonic_ns, payload_json, created_at_utc) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _field(fact, "session_id"),
                        str(_field(fact, "episode_uid", "")),
                        str(_field(fact, "candidate_uid", "")),
                        str(_field(fact, "kind", "")),
                        str(_field(fact, "popup_request_id", "")),
                        int(_field(fact, "occurred_monotonic_ns", 0) or 0),
                        _json_text(fact),
                        _utc_now(),
                    ),
                )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("append SINE fact batch", write))
        return receipt.state is ReceiptState.COMMITTED

    def append_normal_break_facts(self, facts) -> bool:
        """Durably append immutable Normal Break lifecycle facts.

        Storage preserves the authority's identity and timestamps verbatim.  It
        does not validate duration policy or decide ownership transfer.
        """

        batch = tuple(facts)
        if not batch:
            return True

        def write(connection):
            for fact in batch:
                connection.execute(
                    "INSERT INTO normal_break_events(event_id, session_id, "
                    "break_id, generation, sequence, episode_uid, candidate_uid, "
                    "kind, occurred_monotonic_ns, payload_json, created_at_utc, "
                    "schema_version) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(_field(fact, "event_id", "")),
                        _field(fact, "session_id"),
                        str(_field(fact, "break_id", "")),
                        int(_field(fact, "generation", 0) or 0),
                        int(_field(fact, "sequence", 0) or 0),
                        str(_field(fact, "episode_uid", "")),
                        str(_field(fact, "candidate_uid", "")),
                        str(_enum_value(_field(fact, "kind", ""))),
                        int(_field(fact, "occurred_monotonic_ns", 0) or 0),
                        _json_text(fact),
                        _utc_now(),
                        str(_field(fact, "schema_version", "")),
                    ),
                )
            return TransactionResult()

        receipt = _terminal(
            self._lane,
            self._submit("append Normal Break fact batch", write),
        )
        return receipt.state is ReceiptState.COMMITTED

    def append_cosecant_facts(self, *, session_id: int | None, facts) -> bool:
        batch = tuple(facts)
        if not batch:
            return True

        # Freeze serialized evidence before queueing; never consult runtime later.
        rows = []
        for fact in batch:
            payload = json.loads(_json_text(fact))
            if type(payload) is not dict:
                raise ValueError("Structured COSECANT fact required")
            # Keep the V1 identity payload byte-compatible; metadata is independent.
            raw_target = payload.get("return_target")
            if type(raw_target) is dict and "display_metadata" in raw_target:
                metadata = raw_target.pop("display_metadata")
                if metadata is not None:
                    payload["return_target_display_metadata"] = metadata
            version, kind = payload.get("schema_version"), payload.get("kind")
            selected = payload.get("selected_break_seconds")
            extension = payload.get("selected_break_extension_version")
            if kind == "BREAK_STARTED":
                if version != "myelin-cosecant-v2":
                    raise ValueError("Unsupported COSECANT start payload version")
                if extension is not None and (type(extension) is not int or extension != 1
                        or type(selected) is not int or not 60 <= selected <= 86400):
                    raise ValueError("New BREAK_STARTED requires its exact integer selected allowance")
                if extension is None and selected is not None:
                    raise ValueError("Selected allowance requires its payload extension version")
            elif selected is not None:
                raise ValueError("Selected allowance belongs only to BREAK_STARTED")
            if selected is None:
                payload.pop("selected_break_seconds", None)  # Absent on old and non-start facts.
            if kind != "BREAK_STARTED" or extension is None:
                payload.pop("selected_break_extension_version", None)
            _validate_cosecant_target_payload(payload)
            rows.append((session_id, str(_field(fact, "break_id", "")),
                int(_field(fact, "sequence", 0) or 0), str(_enum_value(_field(fact, "kind", ""))),
                int(_field(fact, "observed_monotonic_ns", 0) or 0), _boundary_json(payload)))

        def write(connection):
            for values in rows:
                prior = connection.execute("SELECT session_id,break_id,sequence,kind,occurred_monotonic_ns,payload_json "
                    "FROM cosecant_events WHERE break_id=? AND sequence=?", (values[1], values[2])).fetchone()
                if prior is not None:
                    if tuple(prior[:5]) != values[:5] or json.loads(prior[5]) != json.loads(values[5]):
                        raise ValueError("Conflicting immutable COSECANT fact retry")
                    if values[3] == "BREAK_STARTED":
                        from PERSISTENCE.presentation_aliases import assign_cosecant_event
                        event_id = connection.execute("SELECT id FROM cosecant_events WHERE break_id=? AND sequence=?",
                            (values[1], values[2])).fetchone()[0]
                        assign_cosecant_event(connection, event_id)
                    continue
                if values[3] == "BREAK_STARTED" and json.loads(values[5]).get("selected_break_extension_version") != 1:
                    raise ValueError("Legacy BREAK_STARTED may be replayed, but new starts require selected allowance")
                if values[3] == "BREAK_STARTED" and json.loads(values[5]).get("return_target_extension_version") != 1:
                    raise ValueError("Legacy BREAK_STARTED may be replayed, but new starts require exact return target")
                inserted = connection.execute(
                    "INSERT INTO cosecant_events(session_id, break_id, sequence, kind, occurred_monotonic_ns, payload_json, created_at_utc) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    values + (_utc_now(),),
                )
                if values[3] == "BREAK_STARTED":
                    from PERSISTENCE.presentation_aliases import assign_cosecant_event
                    assign_cosecant_event(connection, inserted.lastrowid)
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("append COSECANT fact batch", write))
        return receipt.state is ReceiptState.COMMITTED

    def record_study_resource(self, fact) -> TransactionReceipt:
        """Return the ordered-lane receipt; RUNNING is never treated as committed."""
        from SECANT.read_model import StudyResourceFact, validate_display_metadata
        if not isinstance(fact, StudyResourceFact):
            raise TypeError("Immutable StudyResourceFact required")
        identity_json = json.dumps(dataclasses.asdict(fact.resource),sort_keys=True,separators=(",", ":"))
        provenance = json.loads(fact.provenance_json)
        if provenance.get("display_metadata") is not None:
            if not provenance.get("observation_id"):
                raise ValueError("Caption requires its qualifying observation")
            validate_display_metadata(provenance["display_metadata"],
                observation_id=provenance["observation_id"], observed_ns=fact.qualified_monotonic_ns)
        provenance_json = json.dumps(provenance,sort_keys=True,separators=(",", ":"))
        values = (fact.resource_fact_id, fact.session_id, fact.study_block_id, fact.study_generation,
            fact.study_context_token, fact.resource.key, fact.resource.kind, fact.resource.version,
            identity_json, fact.role, fact.first_aligned_monotonic_ns, fact.qualified_monotonic_ns,
            fact.first_aligned_at_utc, fact.qualified_at_utc, provenance_json, fact.contract_version)
        columns = "resource_fact_id,session_id,study_block_id,study_generation,study_context_token,resource_key,identity_kind,identity_version,identity_json,role,first_aligned_monotonic_ns,qualified_monotonic_ns,first_aligned_at_utc,qualified_at_utc,provenance_json,contract_version"
        def write(connection):
            prior = connection.execute("SELECT " + columns + " FROM study_resources WHERE resource_fact_id=?",(fact.resource_fact_id,)).fetchone()
            if prior is not None:
                if tuple(prior) != values:
                    raise ValueError("Conflicting immutable Study-resource retry")
                return TransactionResult(session_id=fact.session_id)
            connection.execute("INSERT INTO study_resources("+columns+",inserted_at_utc) VALUES("+",".join("?" for _ in range(17))+")",values+(_utc_now(),))
            return TransactionResult(session_id=fact.session_id)
        return self._submit("record immutable Study resource", write)

    def record_study_snapshot(self, *, session_id: int | None, action: str, snapshot: object) -> bool:
        block_id = str(_field(snapshot, "block_id", ""))
        occurred_ns = int(_field(snapshot, "observed_monotonic_ns", 0) or 0)
        if occurred_ns <= 0:
            occurred_ns = time.monotonic_ns()

        def write(connection):
            connection.execute(
                "INSERT INTO study_events(session_id, study_block_id, action, occurred_monotonic_ns, payload_json, created_at_utc) VALUES(?, ?, ?, ?, ?, ?)",
                (session_id, block_id, str(action)[:80], occurred_ns, _json_text(snapshot), _utc_now()),
            )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("record Study snapshot", write))
        return receipt.state is ReceiptState.COMMITTED

    def start_science_lab_experiment(
        self,
        *,
        parent_session_id: int,
        date_key: str,
        started_at_utc: str,
        started_monotonic_ns: int,
        runtime_instance_id: str,
    ) -> int:
        """Durably allocate and start one explicit Science Lab experiment."""

        sid = _science_lab_session_id(parent_session_id)
        day = _science_lab_date_key(date_key)
        started_utc = _science_lab_nonempty_text(
            started_at_utc, name="started_at_utc"
        )
        started_ns = _positive_int(
            started_monotonic_ns, name="started_monotonic_ns"
        )
        runtime_id = _science_lab_nonempty_text(
            runtime_instance_id, name="runtime_instance_id"
        )

        def write(connection):
            parent = connection.execute(
                "SELECT id, closed_at_utc FROM sessions WHERE id=?",
                (sid,),
            ).fetchone()
            if parent is None:
                raise RuntimeError("parent MYELIN session does not exist")
            if parent["closed_at_utc"] is not None:
                raise RuntimeError("parent MYELIN session is already closed")

            existing = connection.execute(
                "SELECT experiment_id FROM science_lab_experiments "
                "WHERE status='RUNNING'"
            ).fetchall()
            if existing:
                raise RuntimeError("a Science Lab experiment is already running")

            row = connection.execute(
                "SELECT MAX(daily_sequence) AS max_sequence "
                "FROM science_lab_experiments WHERE date_key=?",
                (day,),
            ).fetchone()
            max_sequence = (
                int(row["max_sequence"])
                if row is not None and row["max_sequence"] is not None
                else 0
            )
            sequence = max_sequence + 1
            if sequence > 99:
                raise RuntimeError(
                    "Science Lab daily experiment sequence is exhausted"
                )

            experiment_id = _science_lab_experiment_id(day, sequence)
            connection.execute(
                "INSERT INTO science_lab_experiments("
                "experiment_id, parent_session_id, date_key, daily_sequence, "
                "status, started_at_utc, started_monotonic_ns, "
                "ended_at_utc, ended_monotonic_ns, end_reason, "
                "runtime_instance_id, created_at_utc, updated_at_utc"
                ") VALUES(?, ?, ?, ?, 'RUNNING', ?, ?, NULL, NULL, '', ?, ?, ?)",
                (
                    experiment_id,
                    sid,
                    day,
                    sequence,
                    started_utc,
                    started_ns,
                    runtime_id,
                    started_utc,
                    started_utc,
                ),
            )
            return TransactionResult(result_id=sequence, session_id=sid)

        receipt = _terminal(
            self._lane,
            self._submit("start Science Lab experiment", write),
        )
        if receipt.state is not ReceiptState.COMMITTED:
            raise RuntimeError(
                "Science Lab experiment start was not committed: "
                f"{receipt.error or 'refused'}"
            )
        if receipt.session_id != sid or type(receipt.result_id) is not int:
            raise RuntimeError(
                "Science Lab experiment start returned invalid durable identity"
            )
        return receipt.result_id

    def complete_science_lab_experiment(
        self,
        *,
        experiment_id: str,
        parent_session_id: int,
        ended_at_utc: str,
        ended_monotonic_ns: int,
        end_reason: str,
    ) -> bool:
        """Durably complete one RUNNING experiment without closing MYELIN."""

        target = _science_lab_experiment_identifier(experiment_id)
        sid = _science_lab_session_id(parent_session_id)
        ended_utc = _science_lab_nonempty_text(
            ended_at_utc, name="ended_at_utc"
        )
        ended_ns = _positive_int(
            ended_monotonic_ns, name="ended_monotonic_ns"
        )
        reason = _science_lab_nonempty_text(end_reason, name="end_reason")
        if reason not in {"USER_END", "PARENT_SESSION_ENDED"}:
            raise ValueError("end_reason is not an approved completion reason")

        def write(connection):
            row = connection.execute(
                "SELECT * FROM science_lab_experiments WHERE experiment_id=?",
                (target,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Science Lab experiment does not exist")
            record = _science_lab_experiment_from_row(row)
            if record.status != "RUNNING":
                raise RuntimeError("Science Lab experiment is not RUNNING")
            if record.parent_session_id != sid:
                raise RuntimeError(
                    "Science Lab experiment belongs to another parent session"
                )
            if ended_ns < record.started_monotonic_ns:
                raise RuntimeError(
                    "Science Lab experiment end precedes its start boundary"
                )

            cursor = connection.execute(
                "UPDATE science_lab_experiments SET "
                "status='COMPLETED', ended_at_utc=?, ended_monotonic_ns=?, "
                "end_reason=?, updated_at_utc=? "
                "WHERE experiment_id=? AND parent_session_id=? "
                "AND status='RUNNING'",
                (ended_utc, ended_ns, reason, ended_utc, target, sid),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Science Lab completion did not update exactly one RUNNING experiment"
                )
            return TransactionResult(result_id=1, session_id=sid)

        receipt = _terminal(
            self._lane,
            self._submit("complete Science Lab experiment", write),
        )
        if receipt.state is not ReceiptState.COMMITTED:
            raise RuntimeError(
                "Science Lab experiment completion was not committed: "
                f"{receipt.error or 'refused'}"
            )
        return True

    def interrupt_stale_science_lab_experiment(
        self,
        *,
        experiment_id: str,
        current_runtime_instance_id: str,
        interrupted_at_utc: str,
    ) -> bool:
        """Preserve a RUNNING experiment from an older process as interrupted."""

        target = _science_lab_experiment_identifier(experiment_id)
        current_runtime = _science_lab_nonempty_text(
            current_runtime_instance_id,
            name="current_runtime_instance_id",
        )
        interrupted_utc = _science_lab_nonempty_text(
            interrupted_at_utc, name="interrupted_at_utc"
        )

        def write(connection):
            row = connection.execute(
                "SELECT * FROM science_lab_experiments WHERE experiment_id=?",
                (target,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Science Lab experiment does not exist")
            record = _science_lab_experiment_from_row(row)
            if record.status != "RUNNING":
                raise RuntimeError("Science Lab experiment is not RUNNING")
            if record.runtime_instance_id == current_runtime:
                return TransactionResult(
                    result_id=0,
                    session_id=record.parent_session_id,
                )

            cursor = connection.execute(
                "UPDATE science_lab_experiments SET "
                "status='INTERRUPTED', ended_at_utc=?, "
                "ended_monotonic_ns=NULL, end_reason='CRASH_RECOVERY', "
                "updated_at_utc=? "
                "WHERE experiment_id=? AND status='RUNNING' "
                "AND runtime_instance_id<>?",
                (interrupted_utc, interrupted_utc, target, current_runtime),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Science Lab interruption did not update exactly one stale experiment"
                )
            return TransactionResult(
                result_id=1,
                session_id=record.parent_session_id,
            )

        receipt = _terminal(
            self._lane,
            self._submit("interrupt stale Science Lab experiment", write),
        )
        if receipt.state is not ReceiptState.COMMITTED:
            raise RuntimeError(
                "Science Lab experiment interruption was not committed: "
                f"{receipt.error or 'refused'}"
            )
        return receipt.result_id == 1

    # ------------------------------------------------------------------
    # C11-B: Planner and Notes repositories.
    #
    # Planner and Notes own their domains; they do not write SQL.  These are
    # the narrow durable contracts they submit through, using the existing
    # ``planner_blocks`` and ``notes`` tables -- no schema migration.
    #
    # Both are OPTIMISTIC: the caller declares the version/revision it believes
    # is durable, and a mismatch is refused rather than overwritten.  Both wait
    # for a terminal receipt, so RUNNING is never reported as COMMITTED and a
    # caller can never advance its own truth on a write that did not land.
    # ------------------------------------------------------------------

    def list_planner_blocks(self, *, plan_id: str) -> tuple[object, ...]:
        """Read every stored block for one planner collection."""

        from COSECANT_STUDY_MODE.planner import plan_block_from_payload

        connection = connect_database(read_only=True)
        try:
            rows = connection.execute(
                "SELECT payload_json FROM planner_blocks "
                "WHERE plan_id=? AND archived=0 ORDER BY block_id",
                (str(plan_id),),
            ).fetchall()
        finally:
            connection.close()
        return tuple(plan_block_from_payload(row[0]) for row in rows)

    def save_planner_block(
        self,
        *,
        plan_id: str,
        block: object,
        expected_version: int,
    ) -> object:
        """Store one planner block, refusing a stale durable write.

        ``expected_version`` is the version the caller believes is DURABLE --
        0 for a block that has never been stored.  The comparison happens
        inside the write transaction, so two facades racing on the same block
        cannot both believe they won.
        """

        from COSECANT_STUDY_MODE.planner import (
            plan_block_payload,
            plan_block_from_payload,
        )

        key = str(plan_id)
        block_id = str(_field(block, "block_id", ""))
        if not key or not block_id:
            raise ValueError("planner block requires plan_id and block_id")

        # LINEAGE, not just position.  Comparing only the durable version
        # protects the row we are replacing but says nothing about the
        # candidate replacing it: a caller could rewrite content at the SAME
        # version (durable truth changes while its version does not, so no
        # reader can detect it) or jump the version arbitrarily.  A legitimate
        # candidate is always exactly one step beyond the durable state.
        expected = _exact_index(expected_version, "expected_version")
        candidate = _exact_index(_field(block, "version", None), "block.version")
        if candidate != expected + 1:
            raise ValueError(
                "planner lineage must advance by exactly one: expected durable "
                f"version {expected} requires candidate version {expected + 1}, "
                f"got {candidate}"
            )
        payload = plan_block_payload(block)

        def write(connection):
            row = connection.execute(
                "SELECT payload_json FROM planner_blocks "
                "WHERE plan_id=? AND block_id=?",
                (key, block_id),
            ).fetchone()
            durable = (
                0
                if row is None
                else int(_field(plan_block_from_payload(row[0]), "version", 0) or 0)
            )
            if durable != expected:
                raise ValueError(
                    "stale planner write: expected durable version "
                    f"{expected}, found {durable}"
                )
            connection.execute(
                "INSERT INTO planner_blocks"
                "(plan_id, block_id, archived, payload_json, updated_at_utc) "
                "VALUES(?, ?, 0, ?, ?) "
                "ON CONFLICT(plan_id, block_id) DO UPDATE SET "
                "archived=0, payload_json=excluded.payload_json, "
                "updated_at_utc=excluded.updated_at_utc",
                (key, block_id, payload, _utc_now()),
            )
            return TransactionResult()

        receipt = _terminal(
            self._lane, self._submit("save planner block", write)
        )
        if receipt.state is not ReceiptState.COMMITTED:
            raise RuntimeError(
                f"planner block was not durably accepted: {receipt.error or 'refused'}"
            )
        return block

    def archive_planner_block(
        self,
        *,
        plan_id: str,
        block_id: str,
        expected_version: int,
    ) -> bool:
        """Archive one stored block, refusing a stale durable write."""

        from COSECANT_STUDY_MODE.planner import plan_block_from_payload

        key = str(plan_id)
        target = str(block_id)
        expected = _exact_index(expected_version, "expected_version")

        def write(connection):
            row = connection.execute(
                "SELECT payload_json FROM planner_blocks "
                "WHERE plan_id=? AND block_id=? AND archived=0",
                (key, target),
            ).fetchone()
            if row is None:
                raise ValueError("planner block is not stored")
            durable = int(_field(plan_block_from_payload(row[0]), "version", 0) or 0)
            if durable != expected:
                raise ValueError(
                    "stale planner archive: expected durable version "
                    f"{expected}, found {durable}"
                )
            connection.execute(
                "UPDATE planner_blocks SET archived=1, updated_at_utc=? "
                "WHERE plan_id=? AND block_id=?",
                (_utc_now(), key, target),
            )
            return TransactionResult()

        receipt = _terminal(
            self._lane, self._submit("archive planner block", write)
        )
        return receipt.state is ReceiptState.COMMITTED

    def load_note(self, note_id: str) -> object:
        """Read one stored note.  Missing is an error, never an empty note."""

        from COSECANT_STUDY_MODE.notes import document_from_json

        connection = connect_database(read_only=True)
        try:
            row = connection.execute(
                "SELECT payload_json FROM notes WHERE note_id=? AND archived=0",
                (str(note_id),),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"unknown note {note_id}")
        return document_from_json(row[0])

    def list_notes(self, note_kind=None) -> tuple[object, ...]:
        """Summarise stored notes without loading every document body."""

        from COSECANT_STUDY_MODE.notes import NoteSummary, document_from_json

        connection = connect_database(read_only=True)
        try:
            rows = connection.execute(
                "SELECT payload_json FROM notes WHERE archived=0 "
                "ORDER BY updated_at_utc DESC",
                (),
            ).fetchall()
        finally:
            connection.close()
        summaries = []
        for row in rows:
            document = document_from_json(row[0])
            if note_kind is not None and document.note_kind is not note_kind:
                continue
            summaries.append(
                NoteSummary(
                    note_id=document.note_id,
                    title=document.title,
                    note_kind=document.note_kind,
                    updated_at_utc=document.updated_at_utc,
                    linked_study_block_id=document.linked_study_block_id,
                    linked_plan_id=document.linked_plan_id,
                )
            )
        return tuple(summaries)

    def save_note(self, document: object, *, expected_revision: int) -> object:
        """Store one note, refusing a stale revision.

        On success the committed document carries ``revision_number`` advanced
        by exactly one, which is what ``NoteSession`` adopts as its new base.
        """

        from COSECANT_STUDY_MODE.notes import document_to_json

        note_id = str(_field(document, "note_id", ""))
        if not note_id:
            raise ValueError("note requires a note_id")

        # Persistence is an authority boundary: it must not trust the caller to
        # keep the document and the expected revision consistent.  Without this
        # a stale body carrying revision 0 could be submitted as expected 1 and
        # be published as revision 2 -- stale content under a newer number.
        expected = _exact_index(expected_revision, "expected_revision")
        carried = _exact_index(
            _field(document, "revision_number", None), "document.revision_number"
        )
        if carried != expected:
            raise ValueError(
                "note revision mismatch: the document carries revision "
                f"{carried} but the write claims durable revision {expected}"
            )
        committed = dataclasses.replace(document, revision_number=expected + 1)
        payload = document_to_json(committed)

        def write(connection):
            row = connection.execute(
                "SELECT revision FROM notes WHERE note_id=?",
                (note_id,),
            ).fetchone()
            durable = 0 if row is None else int(row[0])
            if durable != expected:
                raise ValueError(
                    "stale note write: expected durable revision "
                    f"{expected}, found {durable}"
                )
            connection.execute(
                "INSERT INTO notes"
                "(note_id, revision, archived, payload_json, updated_at_utc) "
                "VALUES(?, ?, 0, ?, ?) "
                "ON CONFLICT(note_id) DO UPDATE SET "
                "revision=excluded.revision, archived=0, "
                "payload_json=excluded.payload_json, "
                "updated_at_utc=excluded.updated_at_utc",
                (note_id, expected + 1, payload, _utc_now()),
            )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("save note", write))
        if receipt.state is not ReceiptState.COMMITTED:
            raise RuntimeError(
                f"note was not durably accepted: {receipt.error or 'refused'}"
            )
        return committed

    def archive_note(self, note_id: str, *, expected_revision: int) -> bool:
        """Archive one stored note, refusing a stale revision."""

        target = str(note_id)
        expected = _exact_index(expected_revision, "expected_revision")

        def write(connection):
            row = connection.execute(
                "SELECT revision FROM notes WHERE note_id=? AND archived=0",
                (target,),
            ).fetchone()
            if row is None:
                raise ValueError("note is not stored")
            if int(row[0]) != expected:
                raise ValueError(
                    "stale note archive: expected durable revision "
                    f"{expected}, found {int(row[0])}"
                )
            connection.execute(
                "UPDATE notes SET archived=1, updated_at_utc=? WHERE note_id=?",
                (_utc_now(), target),
            )
            return TransactionResult()

        receipt = _terminal(self._lane, self._submit("archive note", write))
        return receipt.state is ReceiptState.COMMITTED

    def read_cosine_events(self):
        return read_cosine_events()

    def read_mine_events(self):
        return read_mine_events()

    def append_secant_events(self, events) -> TransactionReceipt:
        """Submit immutable passive SECANT facts on the existing shared lane."""
        return _append_passive_events(self, events, "secant")

    def append_study_resource_events(self, events) -> TransactionReceipt:
        """Submit observed resource changes; never infer domain transitions."""
        return _append_passive_events(self, events, "resource")

    def record_passive_recorder_status(self, status) -> TransactionReceipt:
        from PERSISTENCE.secant_recorder import RecorderStatusRecord, META_PREFIX, _utc
        if type(status) is not RecorderStatusRecord:
            raise TypeError("Immutable recorder status required")
        value = json.loads(status.status_json)
        if (type(value) is not dict or type(value.get("contract_version")) is not int or value.get("contract_version") != 1
                or type(value.get("run_id")) is not str or not value["run_id"]
                or type(value.get("status_revision")) is not int or value["status_revision"] <= 0
                or value.get("writer_state") not in {"STARTING", "ACTIVE", "DRAINING", "CLOSED", "FAILED"}
                or value.get("coverage") not in {"BOUNDED_OBSERVATION", "RECORDING_GAP_DETECTED"}):
            raise ValueError("Invalid recorder status")
        _utc(value["opened_at_utc"])
        _utc(value["last_recorded_at_utc"])
        if value.get("closed_at_utc") is not None:
            _utc(value["closed_at_utc"])
        if value.get("writer_state") == "CLOSED" and value.get("final_flush_committed") is not True:
            raise ValueError("Closed recorder requires confirmed flush")
        key = META_PREFIX + value["run_id"]
        payload = status.status_json
        def write(connection):
            row = connection.execute("SELECT value FROM myelin_meta WHERE key=?", (key,)).fetchone()
            if row:
                prior = json.loads(row[0])
                if prior["opened_at_utc"] != value["opened_at_utc"]:
                    raise ValueError("Recorder run identity conflict")
                if prior["status_revision"] == value["status_revision"] and row[0] == payload:
                    return TransactionResult()
                if prior["status_revision"] >= value["status_revision"]:
                    raise ValueError("Recorder status revision conflict")
                if prior["coverage"] == "RECORDING_GAP_DETECTED" and value["coverage"] != prior["coverage"]:
                    raise ValueError("Recorder quality cannot improve")
            connection.execute("INSERT INTO myelin_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, payload))
            return TransactionResult()
        return self._submit("passive recorder status", write)

    def flush_passive_recorder(self) -> TransactionReceipt:
        """FIFO barrier only; caller still checks all its earlier receipts."""
        return self._submit("passive recorder flush barrier", lambda connection: TransactionResult())

    def read_passive_recorder_status(self, recorder_run_id):
        from PERSISTENCE.secant_recorder import META_PREFIX, RecorderStatusRecord
        if type(recorder_run_id) is not str or not recorder_run_id:
            raise ValueError("Recorder run ID required")
        connection = connect_database(read_only=True)
        try:
            row = connection.execute("SELECT value FROM myelin_meta WHERE key=?", (META_PREFIX + recorder_run_id,)).fetchone()
            return RecorderStatusRecord(row[0]) if row else None
        finally:
            connection.close()

    def read_study_resource_event_roles(self, event_ids):
        """Join only committed qualification facts; ambiguity remains explicit."""
        from PERSISTENCE.secant_recorder import RoleResolution
        if type(event_ids) is not tuple or len(event_ids) > 2048 or any(type(v) is not str for v in event_ids):
            raise ValueError("Bounded tuple of event IDs required")
        connection = connect_database(read_only=True)
        try:
            connection.execute("BEGIN")
            output = []
            for event_id in event_ids:
                event = connection.execute("SELECT * FROM study_resource_events WHERE event_id=?", (event_id,)).fetchone()
                if event is None:
                    output.append(RoleResolution(event_id, "EVENT_NOT_FOUND")); continue
                candidates = connection.execute("SELECT * FROM study_resources WHERE session_id=? AND study_context_token=?", (event["session_id"], event["study_context_token"])).fetchall()
                provenance = json.loads(event["provenance_json"])
                exact = provenance.get("exact_resource_identity")
                certified = (event["source_lane"] == "CONTROL_VIEW"
                    and event["timestamp_basis"] == "COHERENT_FOREGROUND_OBSERVATION"
                    and provenance.get("source_rejection_reason") == ""
                    and isinstance(exact, dict) and exact.get("kind") == "BROWSER"
                    and type(exact.get("version")) is int and exact["version"] == 1
                    and type(exact.get("platform_key")) is str and bool(exact["platform_key"])
                    and type(exact.get("resource_token")) is str and bool(exact["resource_token"]))
                rows = []
                for candidate in candidates:
                    same_key = candidate["resource_key"] == event["resource_key"]
                    same_identity = False
                    if certified and candidate["identity_kind"] == "BROWSER" and candidate["identity_version"] == 1:
                        identity = json.loads(candidate["identity_json"])
                        same_identity = all(identity.get(k) == exact[k] for k in ("kind", "version", "platform_key", "resource_token"))
                    if same_key or same_identity:
                        rows.append(candidate)
                if event["study_block_id"] is not None:
                    rows = [r for r in rows if r["study_block_id"] == event["study_block_id"] and r["study_generation"] == event["study_generation"]]
                if len(rows) != 1:
                    output.append(RoleResolution(event_id, "AMBIGUOUS" if rows else "PENDING_OR_UNQUALIFIED")); continue
                r = rows[0]
                output.append(RoleResolution(event_id, "RESOLVED", r["resource_fact_id"], r["study_block_id"], r["study_generation"], r["identity_kind"], r["identity_version"], r["role"], r["qualified_monotonic_ns"], r["qualified_at_utc"]))
            return tuple(output)
        finally:
            connection.close()

    def shutdown(self) -> None:
        """Release this facade's ownership of the shared lane.

        Idempotent.  The lane itself shuts down only when the LAST owner
        releases it, so one Monitor session ending never closes persistence
        that the Control Station is still using.
        """

        self.end_study_resource_interval("STORAGE_SHUTDOWN")
        if self._study_boundary_observer is not None:
            self._study_boundary_observer.reap()
        # The claim is made under a lock so two threads shutting this SAME
        # facade cannot both pass the check and release the owner twice.
        with self._lifetime_lock:
            if self._closed:
                return
            self._closed = True
            lane = self._lane
        _SharedStorageLane.release(lane, self._owner_token)
        if self._study_observation_evidence_capture is not None:
            self._study_observation_evidence_capture.reap()


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ScienceLabExperimentRecord:
    experiment_id: str
    parent_session_id: int
    date_key: str
    daily_sequence: int
    status: str
    started_at_utc: str
    started_monotonic_ns: int
    ended_at_utc: str | None
    ended_monotonic_ns: int | None
    end_reason: str
    runtime_instance_id: str
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class ScienceLabSourceRecord:
    """One immutable persisted source row exposed for Science Lab reading.

    This object is factual persistence evidence only.  ``kind`` is the exact
    persisted event/fact/action label.  ``payload_json`` is preserved verbatim;
    this reader performs no behavioral interpretation.
    """

    source_system: str
    source_event_id: str
    session_id: int
    kind: str
    occurred_monotonic_ns: int
    payload_json: str
    created_at_utc: str


def _science_lab_session_id(value: object) -> int:
    return _positive_int(value, name="session_id")


def _science_lab_nonempty_text(value: object, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")
    return value


def _science_lab_date_key(value: object) -> str:
    key = _science_lab_nonempty_text(value, name="date_key")
    if len(key) != 8 or any(character < "0" or character > "9" for character in key):
        raise ValueError("date_key must contain exactly 8 ASCII digits")
    return key


def _science_lab_experiment_id(date_key: str, daily_sequence: int) -> str:
    return f"MYL-{date_key}-SCI{daily_sequence:02d}"


def _science_lab_experiment_identifier(value: object) -> str:
    return _science_lab_nonempty_text(value, name="experiment_id")


def _science_lab_exact_row_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"stored {name} is not an exact integer")
    return value


def _science_lab_exact_row_text(value: object, *, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise RuntimeError(f"stored {name} is not a valid non-empty string")
    return value


def _science_lab_experiment_from_row(row) -> ScienceLabExperimentRecord:
    parent_session_id = _science_lab_exact_row_int(
        row["parent_session_id"], name="parent_session_id"
    )
    if parent_session_id <= 0:
        raise RuntimeError("stored parent_session_id is not positive")

    date_key = _science_lab_exact_row_text(row["date_key"], name="date_key")
    if len(date_key) != 8 or any(
        character < "0" or character > "9" for character in date_key
    ):
        raise RuntimeError("stored date_key is not exactly 8 ASCII digits")

    daily_sequence = _science_lab_exact_row_int(
        row["daily_sequence"], name="daily_sequence"
    )
    if not 1 <= daily_sequence <= 99:
        raise RuntimeError("stored daily_sequence is outside 1 through 99")

    experiment_id = _science_lab_exact_row_text(
        row["experiment_id"], name="experiment_id"
    )
    if experiment_id != _science_lab_experiment_id(date_key, daily_sequence):
        raise RuntimeError("stored experiment_id does not match its date and sequence")

    status = _science_lab_exact_row_text(row["status"], name="status")
    if status not in {"RUNNING", "COMPLETED", "INTERRUPTED"}:
        raise RuntimeError("stored Science Lab experiment status is invalid")

    started_at_utc = _science_lab_exact_row_text(
        row["started_at_utc"], name="started_at_utc"
    )
    started_monotonic_ns = _science_lab_exact_row_int(
        row["started_monotonic_ns"], name="started_monotonic_ns"
    )
    if started_monotonic_ns <= 0:
        raise RuntimeError("stored started_monotonic_ns is not positive")

    ended_at_value = row["ended_at_utc"]
    ended_at_utc = (
        None
        if ended_at_value is None
        else _science_lab_exact_row_text(ended_at_value, name="ended_at_utc")
    )
    ended_ns_value = row["ended_monotonic_ns"]
    ended_monotonic_ns = (
        None
        if ended_ns_value is None
        else _science_lab_exact_row_int(
            ended_ns_value, name="ended_monotonic_ns"
        )
    )
    end_reason_value = row["end_reason"]
    if type(end_reason_value) is not str:
        raise RuntimeError("stored end_reason is not text")
    end_reason = end_reason_value

    if status == "RUNNING":
        if (
            ended_at_utc is not None
            or ended_monotonic_ns is not None
            or end_reason != ""
        ):
            raise RuntimeError("stored RUNNING experiment has terminal fields")
    elif status == "COMPLETED":
        if (
            ended_at_utc is None
            or ended_monotonic_ns is None
            or ended_monotonic_ns < started_monotonic_ns
            or end_reason not in {"USER_END", "PARENT_SESSION_ENDED"}
        ):
            raise RuntimeError("stored COMPLETED experiment is malformed")
    elif (
        ended_at_utc is None
        or ended_monotonic_ns is not None
        or end_reason != "CRASH_RECOVERY"
    ):
        raise RuntimeError("stored INTERRUPTED experiment is malformed")

    return ScienceLabExperimentRecord(
        experiment_id=experiment_id,
        parent_session_id=parent_session_id,
        date_key=date_key,
        daily_sequence=daily_sequence,
        status=status,
        started_at_utc=started_at_utc,
        started_monotonic_ns=started_monotonic_ns,
        ended_at_utc=ended_at_utc,
        ended_monotonic_ns=ended_monotonic_ns,
        end_reason=end_reason,
        runtime_instance_id=_science_lab_exact_row_text(
            row["runtime_instance_id"], name="runtime_instance_id"
        ),
        created_at_utc=_science_lab_exact_row_text(
            row["created_at_utc"], name="created_at_utc"
        ),
        updated_at_utc=_science_lab_exact_row_text(
            row["updated_at_utc"], name="updated_at_utc"
        ),
    )


def read_science_lab_experiment(
    experiment_id: str,
) -> ScienceLabExperimentRecord | None:
    target = _science_lab_experiment_identifier(experiment_id)
    connection = connect_database(read_only=True)
    try:
        row = connection.execute(
            "SELECT * FROM science_lab_experiments WHERE experiment_id=?",
            (target,),
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else _science_lab_experiment_from_row(row)


def read_running_science_lab_experiment() -> ScienceLabExperimentRecord | None:
    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT * FROM science_lab_experiments WHERE status='RUNNING' "
            "ORDER BY started_monotonic_ns, experiment_id"
        ).fetchall()
    finally:
        connection.close()
    if len(rows) > 1:
        raise RuntimeError("multiple RUNNING Science Lab experiments are durable")
    return None if not rows else _science_lab_experiment_from_row(rows[0])


def read_science_lab_experiments_for_session(
    parent_session_id: int,
) -> tuple[ScienceLabExperimentRecord, ...]:
    sid = _science_lab_session_id(parent_session_id)
    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT * FROM science_lab_experiments WHERE parent_session_id=? "
            "ORDER BY started_monotonic_ns, experiment_id",
            (sid,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(_science_lab_experiment_from_row(row) for row in rows)


def read_all_science_lab_experiments() -> tuple[ScienceLabExperimentRecord, ...]:
    """Every durable Science Lab experiment across every parent session.

    Read-only; no schema change; reuses ``_science_lab_experiment_from_row``
    unchanged.  Ordered newest-first by ``created_at_utc`` -- a durable
    wall-clock commit timestamp -- deliberately NOT by
    ``started_monotonic_ns``, which is a per-process monotonic counter that
    is not comparable across a MYELIN restart (Chapter 5 history feature,
    Chief's 20260917 instruction).
    """

    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT * FROM science_lab_experiments "
            "ORDER BY created_at_utc DESC, experiment_id DESC"
        ).fetchall()
    finally:
        connection.close()
    return tuple(_science_lab_experiment_from_row(row) for row in rows)


def read_session_closed_at_utc(session_id: int) -> str | None:
    """The parent MYELIN session's own durable closure timestamp, if any.

    Read-only.  This is the same durable field
    ``start_science_lab_experiment`` already checks internally
    (``sessions.closed_at_utc``) -- the authoritative record of when a
    session ended, reused here (Chapter 5 history feature) as the source
    of a historical experiment's session-finalization time, since the
    original in-memory ``ScienceLabFinalizedSession.finalized_at_utc`` from
    a past process run is never itself persisted anywhere.
    """

    sid = _science_lab_session_id(session_id)
    connection = connect_database(read_only=True)
    try:
        row = connection.execute(
            "SELECT closed_at_utc FROM sessions WHERE id=?",
            (sid,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    value = row["closed_at_utc"]
    return None if value is None else str(value)


def read_science_lab_sine_records(
    session_id: int,
) -> tuple[ScienceLabSourceRecord, ...]:
    sid = _science_lab_session_id(session_id)
    bootstrap_production_schema()
    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT id AS source_event_id, session_id, kind, "
            "occurred_monotonic_ns, payload_json, created_at_utc "
            "FROM sine_facts WHERE session_id=? "
            "ORDER BY occurred_monotonic_ns, id",
            (sid,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        ScienceLabSourceRecord(
            source_system="SINE",
            source_event_id=f"sine_facts:{int(row['source_event_id'])}",
            session_id=int(row["session_id"]),
            kind=str(row["kind"]),
            occurred_monotonic_ns=int(row["occurred_monotonic_ns"]),
            payload_json=str(row["payload_json"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows
    )


def read_science_lab_normal_break_records(
    session_id: int,
) -> tuple[ScienceLabSourceRecord, ...]:
    sid = _science_lab_session_id(session_id)
    bootstrap_production_schema()
    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT event_id AS source_event_id, session_id, kind, "
            "occurred_monotonic_ns, payload_json, created_at_utc "
            "FROM normal_break_events WHERE session_id=? "
            "ORDER BY occurred_monotonic_ns, event_id",
            (sid,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        ScienceLabSourceRecord(
            source_system="NORMAL_BREAK",
            source_event_id=str(row["source_event_id"]),
            session_id=int(row["session_id"]),
            kind=str(row["kind"]),
            occurred_monotonic_ns=int(row["occurred_monotonic_ns"]),
            payload_json=str(row["payload_json"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows
    )


def read_science_lab_study_records(
    session_id: int,
) -> tuple[ScienceLabSourceRecord, ...]:
    sid = _science_lab_session_id(session_id)
    bootstrap_production_schema()
    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT id AS source_event_id, session_id, action AS kind, "
            "occurred_monotonic_ns, payload_json, created_at_utc "
            "FROM study_events WHERE session_id=? "
            "ORDER BY occurred_monotonic_ns, id",
            (sid,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        ScienceLabSourceRecord(
            source_system="STUDY",
            source_event_id=f"study_events:{int(row['source_event_id'])}",
            session_id=int(row["session_id"]),
            kind=str(row["kind"]),
            occurred_monotonic_ns=int(row["occurred_monotonic_ns"]),
            payload_json=str(row["payload_json"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows
    )


def read_science_lab_cosecant_records(
    session_id: int,
) -> tuple[ScienceLabSourceRecord, ...]:
    sid = _science_lab_session_id(session_id)
    bootstrap_production_schema()
    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT id AS source_event_id, session_id, kind, "
            "occurred_monotonic_ns, payload_json, created_at_utc "
            "FROM cosecant_events WHERE session_id=? "
            "ORDER BY occurred_monotonic_ns, id",
            (sid,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        ScienceLabSourceRecord(
            source_system="COSECANT",
            source_event_id=f"cosecant_events:{int(row['source_event_id'])}",
            session_id=int(row["session_id"]),
            kind=str(row["kind"]),
            occurred_monotonic_ns=int(row["occurred_monotonic_ns"]),
            payload_json=str(row["payload_json"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows
    )


def read_science_lab_mirl_events(session_id: int):
    """Return every durable MIRL event for exactly one parent MYELIN session.

    This intentionally bypasses Live MIRL's presentation-only recent-history
    cap while still using the canonical persistence reconstruction performed by
    ``read_mirl_events``.  No SQL is opened by Science Lab itself.
    """

    sid = _science_lab_session_id(session_id)
    return tuple(
        event
        for event in read_mirl_events()
        if getattr(event, "session_id", None) == sid
    )


def read_cosine_events():
    from COSINE.cosine import CosineEvent, EventClass

    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT * FROM cosine_events ORDER BY cosine_session_id, generation, sequence, event_id"
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        CosineEvent(
            event_id=str(row["event_id"]),
            session_id=(int(row["session_id"]) if row["session_id"] is not None else None),
            cosine_session_id=str(row["cosine_session_id"]),
            sequence=int(row["sequence"]),
            event_name=str(row["event_name"]),
            event_class=EventClass(str(row["event_class"])),
            occurred_at_utc=str(row["occurred_at_utc"]),
            monotonic_ns=int(row["monotonic_ns"]),
            generation=int(row["generation"]),
            platform_key=str(row["platform_key"]),
            content_title=str(row["content_title"]),
            request_id=str(row["request_id"]),
            evidence_token=str(row["evidence_token"]),
            payload_json=str(row["payload_json"]),
            schema_version=str(row["schema_version"]),
        )
        for row in rows
    )


def read_mine_events():
    """Read the complete durable MINE ledger through a read-only connection."""

    from MINE.mine import MineEvent, MineEventClass

    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT event_id, session_id, mine_episode_id, generation, sequence, "
            "event_name, event_class, occurred_at_utc, monotonic_ns, platform_key, "
            "platform_label, request_id, evidence_token, payload_json, schema_version "
            "FROM mine_events "
            "ORDER BY session_id, generation, sequence, event_id"
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        MineEvent(
            event_id=str(row["event_id"]),
            parent_session_id=int(row["session_id"]),
            mine_episode_id=str(row["mine_episode_id"]),
            sequence=int(row["sequence"]),
            event_name=str(row["event_name"]),
            event_class=MineEventClass(str(row["event_class"])),
            occurred_at_utc=str(row["occurred_at_utc"]),
            monotonic_ns=int(row["monotonic_ns"]),
            generation=int(row["generation"]),
            platform_key=str(row["platform_key"]),
            platform_label=str(row["platform_label"]),
            request_id=str(row["request_id"]),
            evidence_token=str(row["evidence_token"]),
            payload_json=str(row["payload_json"]),
            schema_version=str(row["schema_version"]),
        )
        for row in rows
    )


def read_mirl_events():
    from MIRL.mirl import MirlEvent, MirlEventClass, MirlEventName

    connection = connect_database(read_only=True)
    try:
        rows = connection.execute(
            "SELECT payload_json FROM mirl_events ORDER BY occurred_monotonic_ns, event_id"
        ).fetchall()
    finally:
        connection.close()
    events = []
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        events.append(
            MirlEvent(
                kind=str(payload["kind"]),
                event_name=MirlEventName(str(payload["event_name"])),
                event_class=MirlEventClass(str(payload["event_class"])),
                event_id=str(payload["event_id"]),
                episode_id=str(payload["episode_id"]),
                episode_sequence=int(payload["episode_sequence"]),
                occurred_monotonic_ns=int(payload["occurred_monotonic_ns"]),
                occurred_wall_time_utc=str(payload["occurred_wall_time_utc"]),
                session_id=(int(payload["session_id"]) if payload.get("session_id") is not None else None),
                candidate_uid=str(payload.get("candidate_uid", "")),
                operational_event_id=(int(payload["operational_event_id"]) if payload.get("operational_event_id") is not None else None),
                attempt_id=str(payload.get("attempt_id", "")),
                attempt_index=int(payload.get("attempt_index", 0)),
                sine_stage=int(payload.get("sine_stage", 0)),
                sine_occurrence=int(payload.get("sine_occurrence", 0)),
                reason=str(payload.get("reason", "")),
                response=str(payload.get("response", "")),
                elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
                target_seconds=float(payload.get("target_seconds", 0.0)),
                supporting_event_ids=tuple(payload.get("supporting_event_ids", ())),
                detail=str(payload.get("detail", "")),
                schema_version=str(payload.get("schema_version", "")),
            )
        )
    return tuple(events)


@dataclass(frozen=True, slots=True)
class ControlStationAnalyticsSnapshot:
    metric_hub: object
    # Distinct four-organ lifetime contract for the active Metric Hub page.
    # The legacy MIRL-owned ``metric_hub`` field above remains unchanged for
    # its existing report/export consumers.
    lifetime_metric_hub: object
    # Renamed from ``science_lab`` (Phase C evidence audit): this is MIRL's
    # own pre-existing "Science Lab" formulas/evidence-scope projection
    # (``mirl.science_lab`` below, from MIRL/read_model.py -- untouched),
    # not the SCIENCE_LAB/ organ's future evidence.  Freed the name so
    # SCIENCE_LAB/evidence.py can own ``science_lab`` without colliding
    # with this legacy MIRL-sourced projection.
    legacy_evidence_summary: object
    live_mirl: object
    cosine: object
    generated_at_utc: str
    mine: object | None = None


def _counts() -> tuple[int, int]:
    connection = connect_database(read_only=True)
    try:
        sessions = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        triggers = len(_operational_trigger_rows(connection))
        return sessions, triggers
    finally:
        connection.close()


def _trigger_evidence(payload_text: str) -> dict:
    """The evidence mapping inside one stored trigger payload.

    ``_json_text`` stringifies nested values on the way in, so ``evidence``
    comes back out as a Python literal repr rather than nested JSON.  Both
    shapes are accepted.  Anything unreadable yields an empty mapping instead
    of raising: one malformed row must not cost the whole table its names.
    ``ast.literal_eval`` evaluates literals only -- it never executes stored
    text as code.
    """

    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError):
        return {}
    evidence = payload.get("evidence") if isinstance(payload, dict) else None
    if isinstance(evidence, dict):
        return evidence
    if isinstance(evidence, str):
        try:
            parsed = ast.literal_eval(evidence)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _operational_trigger_rows(connection) -> tuple[dict, ...]:
    """Join factual SINE acceptance to immutable candidate evidence.

    A candidate or PREPARED event is never sufficient. Invalid acceptance
    evidence fails the read instead of producing a plausible wrong count.
    JSON is validated in Python; SQLite JSON1 is not required.
    """
    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
        connection.execute("BEGIN")
    try:
        return _operational_trigger_rows_in_snapshot(connection)
    finally:
        if owns_snapshot:
            connection.rollback()


def _operational_trigger_rows_in_snapshot(connection) -> tuple[dict, ...]:
    """Both append-only ledgers are read from the same SQLite snapshot."""
    candidates = {
        (row["session_id"], row["candidate_uid"], row["id"]): dict(row)
        for row in connection.execute(
            "SELECT id, session_id, candidate_uid, payload_json, created_at_utc "
            "FROM triggers ORDER BY id"
        ).fetchall()
    }
    accepted: dict[tuple, dict] = {}
    for row in connection.execute(
        "SELECT session_id, candidate_uid, episode_uid, kind, payload_json "
        "FROM sine_facts WHERE kind='SINE_TRIGGER_ACCEPTED' ORDER BY id"
    ).fetchall():
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError("SINE acceptance payload must be an object")
        event_id = payload.get("operational_event_id")
        stamp = payload.get("occurred_wall_time_utc")
        episode_uid = payload.get("episode_uid")
        key = (row["session_id"], row["candidate_uid"], event_id)
        if (
            type(event_id) is not int or event_id <= 0
            or payload.get("kind") != row["kind"]
            or payload.get("session_id") != row["session_id"]
            or payload.get("candidate_uid") != row["candidate_uid"]
            or not episode_uid or episode_uid != row["episode_uid"]
            or not isinstance(stamp, str) or not stamp
            or key not in candidates
        ):
            raise ValueError("Unbound SINE operational acceptance")
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("SINE acceptance time must be timezone-aware")
        prior = accepted.get(key)
        if prior is not None:
            if prior["episode_uid"] != episode_uid or prior["accepted_at_utc"] != stamp:
                raise ValueError("Conflicting SINE operational acceptance")
            continue
        accepted[key] = {
            **candidates[key], "episode_uid": episode_uid, "accepted_at_utc": stamp,
        }
    return tuple(sorted(accepted.values(), key=lambda row: row["id"]))


def read_trigger_candidate_evidence() -> tuple[dict, ...]:
    """Raw committed candidates, including candidates that never intervened."""
    connection = connect_database(read_only=True)
    try:
        return tuple(dict(row) for row in connection.execute(
            "SELECT id, session_id, candidate_uid, payload_json, created_at_utc "
            "FROM triggers ORDER BY id"
        ).fetchall())
    finally:
        connection.close()


def read_trigger_fire_times() -> dict[str, str]:
    """Exact operational acceptance times; these are not display times."""

    connection = connect_database(read_only=True)
    try:
        rows = _operational_trigger_rows(connection)
    finally:
        connection.close()

    fired: dict[str, str] = {}
    for row in rows:
        candidate_uid = str(row["candidate_uid"] or "").strip()
        stamp = str(row["accepted_at_utc"] or "").strip()
        if candidate_uid and stamp:
            fired[candidate_uid] = stamp
    return fired


def read_trigger_identities() -> dict[str, str]:
    """Map each trigger's ``candidate_uid`` to the surface it actually fired on.

    MIRL events carry only the opaque ``trg_...`` token Trigger mints; the
    readable identity of what pulled attention away lives here, in the
    trigger's own recorded evidence.  This reader exists so a presentation
    surface can name it without ever reaching into the database itself.

    Read-only, and it invents nothing: the recorded ``platform_key`` first,
    else the ``process_name`` it was observed in, and a trigger that recorded
    neither is simply absent from the map -- leaving the caller to show the
    token it already has rather than a guess.
    """

    connection = connect_database(read_only=True)
    try:
        rows = _operational_trigger_rows(connection)
    finally:
        connection.close()

    identities: dict[str, str] = {}
    for row in rows:
        candidate_uid = str(row["candidate_uid"] or "").strip()
        if not candidate_uid:
            continue
        evidence = _trigger_evidence(str(row["payload_json"] or ""))
        label = str(evidence.get("platform_key") or "").strip()
        if not label:
            label = str(evidence.get("process_name") or "").strip()
        if label:
            identities[candidate_uid] = label
    return identities


def read_trigger_platform_keys() -> tuple[str, ...]:
    """Each operationally accepted trigger's certified platform key.

    Read-only, and it invents nothing: unlike ``read_trigger_identities``
    (which falls back to ``process_name`` for a presentation label), this
    reader returns ONLY the trigger's own recorded structured
    ``evidence.platform_key`` -- a trigger whose evidence carries no
    platform_key (for example a Resource Intent / study-context trigger
    with no Blacklist platform identity) is simply absent from the result,
    never a guess and never a zero. Built for Chapter 6's lifetime TOP
    DISTRACTION PLATFORM count, which must count only certified structured
    platform identity.
    """

    connection = connect_database(read_only=True)
    try:
        rows = _operational_trigger_rows(connection)
    finally:
        connection.close()

    keys: list[str] = []
    for row in rows:
        evidence = _trigger_evidence(str(row["payload_json"] or ""))
        platform_key = str(evidence.get("platform_key") or "").strip()
        if platform_key:
            keys.append(platform_key)
    return tuple(keys)


def read_mirl_snapshot(presentation_timezone: str = "local"):
    """One authoritative MIRL read-model snapshot over all recorded evidence.

    Extracted so the dashboard read and the report export project from exactly
    the same envelope; two call sites assembling their own ``MirlReadInput``
    would eventually disagree about scope or identity.
    """

    from MIRL.read_model import IntegrityStatus, MirlReadAuthority, MirlReadInput

    session_count, trigger_count = _counts()
    return MirlReadAuthority().project(
        MirlReadInput(
            events=read_mirl_events(),
            source_name="MYELIN SQLite",
            source_revision="production-schema-v1",
            source_generated_at=_utc_now(),
            upstream_integrity_status=IntegrityStatus.CONFIRMED,
            total_session_count=session_count,
            total_trigger_count=trigger_count,
            trigger_identities=read_trigger_identities(),
            trigger_fire_times=read_trigger_fire_times(),
            presentation_timezone=presentation_timezone,
        )
    )


def _deep_jsonable(value: object):
    """Recursively convert a read-model snapshot into JSON-ready primitives.

    Deliberately NOT ``_jsonable``: that one stringifies nested values on
    purpose, which is right for a durable event payload but would flatten every
    episode and timeline in this export into an unreadable repr string.  It is
    also not ``dataclasses.asdict``, which deep-copies and fails outright on the
    frozen ``mappingproxy`` values the read model publishes.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _deep_jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _deep_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_deep_jsonable(item) for item in value]
    return str(value)


MIRL_EXPORT_FORMATS: Final = ("pdf", "json")


def export_mirl_report(
    output_format: str,
    presentation_timezone: str = "local",
) -> str:
    """Write ONE MIRL export in the requested format and return its path.

    ``pdf`` is the compact three-page recovery-history report: cover, current
    or latest episode, episode history, event timeline, history evidence, data
    quality and About MIRL.

    ``json`` is that archive: every field behind all five dashboard tabs, at
    full fidelity, with no episode cap and no timeline truncation.

    One format per call, because the two answer different questions and
    writing both every time left unwanted files behind.  Each is written to a
    temporary name and moved into place, so a failed render can never leave a
    half-written export on disk.
    """

    if output_format not in MIRL_EXPORT_FORMATS:
        raise ValueError(f"output_format must be one of {MIRL_EXPORT_FORMATS}")

    snapshot = read_mirl_snapshot(presentation_timezone)
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if output_format == "pdf":
        from MIRL.report import MirlReportRequest, build_mirl_report_pdf

        pdf_path = downloads / f"MYELIN_MIRL_Report_{stamp}.pdf"
        build_mirl_report_pdf(
            snapshot,
            MirlReportRequest(
                output_path=pdf_path,
                overwrite=True,
            ),
        )
        return str(pdf_path)

    json_path = downloads / f"MYELIN_MIRL_Report_{stamp}.json"
    temporary = json_path.with_name(f".{json_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(_deep_jsonable(snapshot), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, json_path)
    return str(json_path)


def read_control_station_analytics(
    presentation_timezone: str = "local",
) -> ControlStationAnalyticsSnapshot:
    from COSINE.read_model import CosineReadAuthority
    from METRIC_HUB.read_model import read_lifetime_metric_hub
    from MINE.read_model import MineReadAuthority

    lifetime_metric_hub = read_lifetime_metric_hub()
    mirl = read_mirl_snapshot(presentation_timezone)

    class _CosineReader:
        def read_cosine_events(self):
            return read_cosine_events()

    class _MineReader:
        def read_mine_events(self):
            return read_mine_events()

    cosine = CosineReadAuthority(event_reader=_CosineReader()).project(presentation_timezone)
    mine = MineReadAuthority(event_reader=_MineReader()).project(presentation_timezone)
    return ControlStationAnalyticsSnapshot(
        metric_hub=mirl.metric_hub,
        lifetime_metric_hub=lifetime_metric_hub,
        legacy_evidence_summary=mirl.science_lab,
        live_mirl=mirl.live_mirl,
        cosine=cosine,
        generated_at_utc=_utc_now(),
        mine=mine,
    )


def export_cosine_report(presentation_timezone: str = "local") -> str:
    """Write one COSINE three-page PDF report and return its path.

    Shares the same certified analytics route ``read_control_station_
    analytics`` already uses -- the report never opens a second reader and
    never touches the OLD COSINE.report projection. Written to a temporary
    name and moved into place, matching ``export_mirl_report``.
    """

    from COSINE.report import CosinePdfReportRequest, build_cosine_report_pdf

    snapshot = read_control_station_analytics(presentation_timezone)
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    pdf_path = downloads / f"MYELIN_COSINE_Report_{stamp}.pdf"
    build_cosine_report_pdf(
        snapshot.cosine,
        CosinePdfReportRequest(output_path=pdf_path, overwrite=True),
    )
    return str(pdf_path)


# ---------------------------------------------------------------------------
# Emergency follow-up facts.  Lifecycle owns all presentation.
# ---------------------------------------------------------------------------

def emergency_followup_required() -> bool:
    bootstrap_production_schema()
    connection = connect_database(read_only=True)
    try:
        row = connection.execute(
            "SELECT pending FROM emergency_followup WHERE singleton_id=1"
        ).fetchone()
        return bool(row is not None and int(row[0]) == 1)
    finally:
        connection.close()


def record_emergency_followup_reason(reason_code: str) -> bool:
    reason = " ".join(str(reason_code).split())[:80]
    if not reason:
        return False
    bootstrap_production_schema()
    connection = connect_database(read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            "UPDATE emergency_followup SET pending=0, reason_code=?, answered_at_utc=? WHERE singleton_id=1 AND pending=1",
            (reason, _utc_now()),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        return False
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Analytics Sheet export.  The UI chooses sections; this function only renders
# the already-prepared immutable projection and commits one PDF safely.
# ---------------------------------------------------------------------------

def _read_study_records_for_report(snapshot: object) -> tuple:
    """Read durable Study snapshots for report sessions without schema bootstrap."""

    hub = getattr(snapshot, "lifetime_metric_hub", None)
    if hub is None:
        raise RuntimeError("the session list needed to read Study Mode is unavailable")
    session_ids = {int(row.session_id) for row in tuple(getattr(hub, "session_rows", ()) or ())}
    if not session_ids:
        return ()
    connection = connect_database(read_only=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT id, session_id, action, occurred_monotonic_ns, payload_json, created_at_utc "
            "FROM study_events ORDER BY session_id, occurred_monotonic_ns, id"
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        ScienceLabSourceRecord(
            source_system="STUDY",
            source_event_id=f"study_events:{int(row['id'])}",
            session_id=int(row["session_id"]),
            kind=str(row["action"]),
            occurred_monotonic_ns=int(row["occurred_monotonic_ns"]),
            payload_json=str(row["payload_json"]),
            created_at_utc=str(row["created_at_utc"]),
        )
        for row in rows if int(row["session_id"]) in session_ids
    )


def export_analytics_sheet(*, snapshot: object, request: object) -> str:
    # Presentation and period filtering live in ANALYTICS_SHEET.  This function
    # keeps the safe-commit responsibilities: choose the file, render to a
    # temporary name, verify, then publish without clobbering.
    from ANALYTICS_SHEET.render import build_analytics_sheet_pdf

    selected = tuple(request.selected_sections())
    if not selected:
        raise ValueError("at least one analytics section is required")
    study_records = None
    study_error = None
    study_family = None
    study_family_error = None
    if "study-mode" in selected:
        try:
            study_records = _read_study_records_for_report(snapshot)
        except Exception as error:  # reported as "unavailable", never as zero
            study_error = type(error).__name__
        try:
            from GET_CHART.study_family_evidence import read_study_family
            from PERSISTENCE.database import database_path

            study_family = read_study_family(database_path(create_parent=False))
        except Exception as error:
            study_family_error = type(error).__name__
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = downloads / f"MYELIN_Analytics_{stamp}.pdf"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        build_analytics_sheet_pdf(
            snapshot=snapshot,
            request=request,
            output_path=temporary,
            study_records=study_records,
            study_error=study_error,
            study_family=study_family,
            study_family_error=study_family_error,
        )
        # Never claim no-clobber after a check/replace race.  A hard-link commit
        # is atomic on the same filesystem and fails if the target appeared.
        os.link(temporary, output)
        temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(output)


__all__ = [
    "EngineStorage",
    "bootstrap_production_schema",
    "PROFILE_LEARNING_MODEL_VERSION",
    "ProfileLearningState",
    "ScienceLabExperimentRecord",
    "ScienceLabSourceRecord",
    "REPORT_ACCESS_COORDINATOR",
    "ReportAccessCoordinator",
    "ReportAccessRefusal",
    "ReportExportLease",
    "ReportExportRefused",
    "ControlStationAnalyticsSnapshot",
    "MIRL_EXPORT_FORMATS",
    "export_cosine_report",
    "export_mirl_report",
    "emergency_followup_required",
    "export_analytics_sheet",
    "read_control_station_analytics",
    "read_cosine_events",
    "read_mine_events",
    "read_mirl_events",
    "read_running_science_lab_experiment",
    "read_science_lab_experiment",
    "read_science_lab_experiments_for_session",
    "read_science_lab_cosecant_records",
    "read_science_lab_mirl_events",
    "read_science_lab_normal_break_records",
    "read_science_lab_sine_records",
    "read_science_lab_study_records",
    "record_emergency_followup_reason",
]


def read_study_resources(*, session_id: int, study_block_id: str | None = None):
    """Read-only query with no EngineStorage construction, bootstrap or migration."""
    from SECANT.read_model import ExactResource, StudyResourceFact
    if type(session_id) is not int or session_id <= 0:
        raise ValueError("Positive parent session ID required")
    connection = connect_database(read_only=True)
    try:
        sql = "SELECT * FROM study_resources WHERE session_id=?"
        args = [session_id]
        if study_block_id is not None:
            sql += " AND study_block_id=?"
            args.append(study_block_id)
        sql += " ORDER BY qualified_monotonic_ns, resource_fact_id"
        rows = connection.execute(sql,args).fetchall()
        return tuple(StudyResourceFact(row["resource_fact_id"],row["session_id"],row["study_block_id"],
            row["study_generation"],row["study_context_token"],ExactResource(**json.loads(row["identity_json"])),
            row["role"],row["first_aligned_monotonic_ns"],row["qualified_monotonic_ns"],
            row["first_aligned_at_utc"],row["qualified_at_utc"],row["provenance_json"],row["contract_version"]) for row in rows)
    finally:
        connection.close()
