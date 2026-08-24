"""C9-A — real-runtime measurement of COSECANT's effective presence gap.

THIS IS A MEASUREMENT INSTRUMENT. IT CHANGES NO PRODUCTION FILE AND CHOOSES
NO CONSTANT.

The old ``measure_cadence.py`` (kept untouched as historical C0 evidence)
measured only the foreground observation cadence. That is not the quantity
COSECANT actually gates on.

Monitor's real per-cycle order is:

    O(i)  foreground observation timestamp
      -> real Win32 foreground read
      -> real Browser / UIA address-bar read
      -> Resource Intent
      -> COSINE / MIRL / SINE / Blacklist / break admission / Study advance
      -> COSECANT.advance()          <-- A(i)
      -> COSECANT.observe_return(O(i))

COSECANT has TWO continuity gates, and ``advance()`` runs FIRST:

    advance()        while RETURN_CONFIRMING:  A(i) - O(i-1) > G  -> stale
    observe_return():                          O(i) - O(i-1) > G  -> restart

Because A(i) happens after O(i), the dominant quantity is

    E(i) = A(i) - O(i-1) = [O(i) - O(i-1)] + [A(i) - O(i)]
                         =        dO(i)     +      L(i)

so E is what C9-B must be calibrated against, not dO.

HOW A(i) IS CAPTURED
    ``CosecantRuntime.advance()`` returns EARLY, before reading its clock,
    whenever no break is active. So its internal monotonic value only exists
    while a break is running. This instrument therefore records BOTH:

        advance_call_ns      taken at wrapper entry, always available
        advance_internal_ns  the exact value production used, when available

    ``advance_call_ns`` is taken before the lock and the state check, so it is
    a LOWER BOUND on the internal value. Every row states which one it used
    via ``advance_source``, and the summary reports the measured bias between
    them wherever both exist, so the size of that under-estimate is a number
    rather than an assumption.

PRIVACY
    No URL, no window title, no page content is ever recorded. Only process
    name, browser read status, evidence-held flag, and engine states.

USAGE
    py -3 measure_c9_runtime_gap.py --condition A_idle_desktop --intervals 300
    py -3 measure_c9_runtime_gap.py --condition B_browser --intervals 300
    py -3 measure_c9_runtime_gap.py --list-conditions
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import queue
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ULTIMATE = Path(r"C:\Users\Dharshan\Downloads\MYELIN_GENALOGY\MYELIN2.0_ULTIMATE")
ARTIFACT_DIR = Path(__file__).resolve().parent / "c9_artifacts"


def _isolate_storage() -> Path:
    """Redirect APPDATA BEFORE PERSISTENCE is imported. Never touch the real DB."""

    scratch = Path(tempfile.mkdtemp(prefix="myelin_c9_"))
    os.environ["APPDATA"] = str(scratch)
    os.environ["XDG_DATA_HOME"] = str(scratch)
    return scratch


SCRATCH = _isolate_storage()

if str(ULTIMATE) not in sys.path:
    sys.path.insert(0, str(ULTIMATE))


# ---------------------------------------------------------------------------
# Recording wrappers -- LAB ONLY. They delegate and never reorder production.
# ---------------------------------------------------------------------------


class Collector:
    """One row per Monitor cycle, assembled from the real call order."""

    def __init__(self, condition: str, run_number: int) -> None:
        self.condition = condition
        self.run_number = run_number
        self.rows: list[dict] = []
        self.lock = threading.RLock()
        self._current: dict | None = None
        self._prev_observation_ns: int | None = None
        self.browser_status = ""
        self.holding_previous = ""
        self.resource_stable_key = ""
        self.hwnd = 0

    def on_observation(self, observation, read_ns: int) -> None:
        with self.lock:
            self._current = {
                "sequence": int(getattr(observation, "sequence", 0) or 0),
                "observation_ns": int(
                    getattr(observation, "observed_monotonic_ns", 0) or 0
                ),
                "process_name": str(getattr(observation, "process_name", "") or ""),
                "foreground_read_ms": round(read_ns / 1_000_000, 4),
            }

    def on_browser(self, evidence) -> None:
        with self.lock:
            status = getattr(evidence, "status", None)
            self.browser_status = str(getattr(status, "value", status) or "")
            self.holding_previous = str(
                bool(getattr(evidence, "holding_previous_strong_evidence", False))
            )

    def on_intent(self, snapshot) -> None:
        """Record the OPAQUE resource identity so transitions are detectable.

        ``stable_key`` is Resource Intent's own irreversible hash -- the same
        value production already persists as ``resource_key``. It carries no
        URL, title or page content and cannot be reversed into any. It is
        recorded because a Chrome TAB switch keeps process_name == "chrome",
        so without it a tab-level transition is indistinguishable from a
        stable cycle.
        """

        with self.lock:
            try:
                identity = snapshot.verdict.resource_identity
                self.resource_stable_key = str(getattr(identity, "stable_key", "") or "")
                self.hwnd = int(getattr(identity, "hwnd", 0) or 0)
            except Exception:
                self.resource_stable_key = ""
                self.hwnd = 0

    def on_advance(
        self,
        *,
        call_ns: int,
        internal_ns: int | None,
        study_state: str,
        cosecant_state: str,
    ) -> None:
        with self.lock:
            current = self._current
            self._current = None
            if current is None:
                return
            observation_ns = current["observation_ns"]
            previous_ns = self._prev_observation_ns
            self._prev_observation_ns = observation_ns
            if not previous_ns or observation_ns <= 0:
                return  # first cycle has no interval

            advance_ns = internal_ns if internal_ns is not None else call_ns
            source = "advance_internal_ns" if internal_ns is not None else "advance_call_ns"

            observation_gap = (observation_ns - previous_ns) / 1e9
            pre_advance_latency = (advance_ns - observation_ns) / 1e9
            effective_gap = (advance_ns - previous_ns) / 1e9

            self.rows.append(
                {
                    "condition": self.condition,
                    "run_number": self.run_number,
                    "sequence": current["sequence"],
                    "observation_ns": observation_ns,
                    "previous_observation_ns": previous_ns,
                    "observation_gap_seconds": round(observation_gap, 6),
                    "cosecant_advance_ns": advance_ns,
                    "advance_source": source,
                    "advance_call_ns": call_ns,
                    "advance_internal_ns": internal_ns if internal_ns is not None else "",
                    "pre_advance_latency_seconds": round(pre_advance_latency, 6),
                    "effective_gap_seconds": round(effective_gap, 6),
                    "foreground_read_ms": current["foreground_read_ms"],
                    "process_name": current["process_name"],
                    "browser_status": self.browser_status,
                    "holding_previous_strong_evidence": self.holding_previous,
                    "resource_stable_key": self.resource_stable_key,
                    "hwnd": self.hwnd,
                    "study_state": study_state,
                    "cosecant_state": cosecant_state,
                }
            )

    def count(self) -> int:
        with self.lock:
            return len(self.rows)


class RecordingForegroundReader:
    """Delegates to the REAL WindowsForegroundReader and times the read."""

    def __init__(self, collector: Collector) -> None:
        from CORE_ENGINE.monitor import WindowsForegroundReader

        self._real = WindowsForegroundReader()
        self._collector = collector

    def observe(self):
        started = time.monotonic_ns()
        observation = self._real.observe()
        elapsed = time.monotonic_ns() - started
        self._collector.on_observation(observation, elapsed)
        return observation


def make_recording_browser(real_browser, collector: Collector):
    """Wrap the REAL BrowserEvidenceAuthority; record status only, never a URL."""

    real_observe = real_browser.observe

    def observe(observation):
        evidence = real_observe(observation)
        collector.on_browser(evidence)
        return evidence

    real_browser.observe = observe
    return real_browser


def make_recording_intent(real_intent, collector: Collector):
    """Wrap the REAL ResourceIntentAuthority; record only the opaque identity."""

    real_observe = real_intent.observe

    def observe(*args, **kwargs):
        snapshot = real_observe(*args, **kwargs)
        collector.on_intent(snapshot)
        return snapshot

    real_intent.observe = observe
    return real_intent


def make_recording_cosecant(intent, collector: Collector, services_ref: dict):
    """Subclass the REAL CosecantRuntime so advance() timing is captured exactly.

    ``_read_monotonic`` is overridden only to OBSERVE the value production
    already computes -- it adds no second clock read and changes no ordering.
    """

    from COSECANT_STUDY_MODE.cosecant import CosecantRuntime

    class RecordingCosecant(CosecantRuntime):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._in_advance = False
            self._advance_internal_ns = None

        def _read_monotonic(self) -> int:
            value = super()._read_monotonic()
            if self._in_advance and self._advance_internal_ns is None:
                self._advance_internal_ns = value
            return value

        def advance(self):
            call_ns = time.monotonic_ns()
            self._in_advance = True
            self._advance_internal_ns = None
            try:
                result = super().advance()
            finally:
                internal_ns = self._advance_internal_ns
                self._in_advance = False
            services = services_ref.get("services")
            study_state = ""
            cosecant_state = ""
            try:
                snapshot = services.study.snapshot()
                state = getattr(snapshot, "state", "")
                study_state = str(getattr(state, "value", state) or "")
            except Exception:
                study_state = "unavailable"
            try:
                snapshot = self.snapshot()
                state = getattr(snapshot, "state", "")
                cosecant_state = str(getattr(state, "value", state) or "")
            except Exception:
                cosecant_state = "unavailable"
            collector.on_advance(
                call_ns=call_ns,
                internal_ns=internal_ns,
                study_state=study_state,
                cosecant_state=cosecant_state,
            )
            return result

    return RecordingCosecant(context_authority=intent)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

PERCENTILE_METHOD = (
    "nearest-rank on the sorted sample: p_k = sorted[ceil(k/100 * n) - 1], "
    "1-indexed, no interpolation. For n < 100 the p99 rank collapses onto the "
    "maximum, which is exactly why a >=300 sample is required."
)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def describe(values: list[float]) -> dict:
    if not values:
        return {}
    return {
        "n": len(values),
        "min": min(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
    }


def fmt(stats: dict) -> str:
    if not stats:
        return "  (no samples)"
    return (
        f"  n={stats['n']}  min={stats['min']:.4f}  mean={stats['mean']:.4f}  "
        f"median={stats['median']:.4f}  p95={stats['p95']:.4f}  "
        f"p99={stats['p99']:.4f}  max={stats['max']:.4f}"
    )


E_THRESHOLDS = (1.5, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0)


# ---------------------------------------------------------------------------
# Run one condition
# ---------------------------------------------------------------------------


STUDY_SUBJECT = "Neuroscience"
STUDY_TASK = "basal ganglia"
STUDY_KEYWORDS = ("direct", "indirect", "dopamine")
STUDY_IMPORTANT = ("basal ganglia",)


def activate_study(command_queue, services, timeout: float = 20.0,
                   subject: str = STUDY_SUBJECT, task: str = STUDY_TASK,
                   keywords=STUDY_KEYWORDS, important=STUDY_IMPORTANT) -> str:
    """Drive the REAL Study authority to ACTIVE through the real command queue.

    Uses monitor's own ``_drain_commands`` path -- the same one the Control
    Station uses -- so nothing about Study lifecycle is simulated.
    """

    command_queue.put(
        {
            "kind": "study_prepare",
            "payload": {
                "subject": subject,
                "task": task,
                "planned_seconds": 3600,
                "keywords": list(keywords),
                "important_keywords": list(important),
            },
        }
    )
    command_queue.put({"kind": "study_action", "payload": {"action": "START"}})

    deadline = time.monotonic() + timeout
    state = ""
    while time.monotonic() < deadline:
        snapshot = services.study.snapshot()
        raw = getattr(snapshot, "state", "")
        state = str(getattr(raw, "value", raw) or "")
        if state == "ACTIVE":
            return state
        time.sleep(0.25)
    return state


def start_break(command_queue, services, telemetry, seconds: int = 900,
                timeout: float = 180.0) -> tuple[str, list[str]]:
    """Ask for a REAL managed break and wait for genuine C5 admission.

    Admission is NOT forced. C5 requires Study ACTIVE, a fresh STUDY_ALIGNED
    verdict, matching Study context token, authoritative non-held Browser
    evidence, a non-empty certified platform and resource token, and Browser/RI
    agreement on both. If the real engine refuses, that refusal is reported and
    condition E is declared NOT MEASURED -- never simulated.
    """

    from COSECANT_STUDY_MODE.cosecant import CosecantState

    active = {
        CosecantState.BREAK_ACTIVE,
        CosecantState.BREAK_COMPLETE,
        CosecantState.BREAK_ALREADY_OVER,
        CosecantState.FINAL_LOCK,
        CosecantState.RETURN_CONFIRMING,
    }
    reasons: list[str] = []
    deadline = time.monotonic() + timeout
    requested = 0.0

    while time.monotonic() < deadline:
        state = services.cosecant.snapshot().state
        if state in active:
            return str(getattr(state, "value", state)), reasons

        # Re-request periodically: C5 decides one parked request against ONE
        # observation and discards it, so a refusal must be retried as the user
        # settles onto a genuinely certified Study resource.
        if time.monotonic() - requested > 6.0:
            requested = time.monotonic()
            command_queue.put(
                {
                    "kind": "study_break",
                    "payload": {"selected_break_seconds": int(seconds)},
                }
            )

        while True:
            try:
                item = telemetry.get_nowait()
            except queue.Empty:
                break
            kind = item.get("kind") if isinstance(item, dict) else None
            if str(kind or "") == "engine_command_rejected":
                message = str(item.get("message", ""))
                if message and message not in reasons:
                    reasons.append(message)
                    print(f"[C9]   refused: {message}", flush=True)
        time.sleep(0.5)

    state = services.cosecant.snapshot().state
    return str(getattr(state, "value", state)), reasons


def run_condition(condition: str, intervals: int, run_number: int,
                  poll_seconds: float | None = None,
                  study_active: bool = False,
                  break_seconds: int = 0,
                  target: dict | None = None) -> Collector:
    from CORE_ENGINE.monitor import (
        DEFAULT_POLL_SECONDS,
        WindowsMonitorCoordinator,
        _build_services,
    )

    poll = DEFAULT_POLL_SECONDS if poll_seconds is None else float(poll_seconds)
    collector = Collector(condition, run_number)

    services = _build_services(profile_type="study")
    services_ref: dict = {}
    services = replace(
        services,
        browser=make_recording_browser(services.browser, collector),
        resource_intent=make_recording_intent(services.resource_intent, collector),
        cosecant=make_recording_cosecant(
            services.resource_intent, collector, services_ref
        ),
    )
    services_ref["services"] = services

    stop_event = threading.Event()
    ready_event = threading.Event()
    command_queue: queue.Queue = queue.Queue()
    telemetry_queue: queue.Queue = queue.Queue()
    coordinator = WindowsMonitorCoordinator(
        profile_type="study",
        services=services,
        foreground_reader=RecordingForegroundReader(collector),
        stop_event=stop_event,
        pause_event=threading.Event(),
        ready_event=ready_event,
        loop_stopped_event=threading.Event(),
        cleanup_complete_event=threading.Event(),
        telemetry_queue=telemetry_queue,
        command_queue=command_queue,
        poll_seconds=poll,
    )

    thread = threading.Thread(target=coordinator.run, name="c9-measure", daemon=True)
    started = time.monotonic()
    thread.start()
    if not ready_event.wait(timeout=60):
        stop_event.set()
        raise RuntimeError("the monitor never became ready")

    if study_active:
        target = target or {}
        state = activate_study(
            command_queue,
            services,
            subject=target.get("subject", STUDY_SUBJECT),
            task=target.get("task", STUDY_TASK),
            keywords=target.get("keywords", STUDY_KEYWORDS),
            important=target.get("important", STUDY_IMPORTANT),
        )
        if state != "ACTIVE":
            stop_event.set()
            thread.join(timeout=30)
            raise RuntimeError(
                f"Study Mode did not reach ACTIVE (got {state!r}); condition "
                "not measured rather than measured under the wrong state"
            )
        print("[C9] Study Mode is ACTIVE (real command path)", flush=True)

    if break_seconds:
        print(
            "[C9] requesting a REAL managed break -- waiting for genuine C5 "
            "admission (this needs a certified Study-aligned resource in the "
            "foreground)",
            flush=True,
        )
        state, reasons = start_break(
            command_queue, services, telemetry_queue, seconds=break_seconds
        )
        if state not in {
            "BREAK_ACTIVE", "BREAK_COMPLETE", "BREAK_ALREADY_OVER",
            "FINAL_LOCK", "RETURN_CONFIRMING",
        }:
            stop_event.set()
            thread.join(timeout=30)
            raise RuntimeError(
                "CONDITION E NOT MEASURED: the real engine never admitted a "
                f"managed break (COSECANT stayed {state!r}). Refusals seen: "
                + ("; ".join(reasons) if reasons else "(none reported)")
            )
        print(f"[C9] COSECANT is {state} -- measuring the active break", flush=True)

    print(
        f"[C9] condition={condition} run={run_number} poll={poll}s "
        f"target={intervals} intervals (~{intervals * poll / 60:.1f} min)",
        flush=True,
    )
    last_report = 0
    # Generous ceiling: a stalled machine must not hang the instrument forever.
    deadline = time.monotonic() + intervals * poll * 4 + 120
    while collector.count() < intervals and time.monotonic() < deadline:
        time.sleep(1.0)
        have = collector.count()
        if have - last_report >= 50:
            last_report = have
            print(f"[C9]   {have}/{intervals} intervals", flush=True)

    stop_event.set()
    thread.join(timeout=30)
    elapsed = time.monotonic() - started
    print(
        f"[C9] condition={condition} collected {collector.count()} intervals "
        f"in {elapsed:.1f}s",
        flush=True,
    )
    return collector


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

FIELDS = (
    "condition",
    "run_number",
    "sequence",
    "observation_ns",
    "previous_observation_ns",
    "observation_gap_seconds",
    "cosecant_advance_ns",
    "advance_source",
    "advance_call_ns",
    "advance_internal_ns",
    "pre_advance_latency_seconds",
    "effective_gap_seconds",
    "foreground_read_ms",
    "process_name",
    "browser_status",
    "holding_previous_strong_evidence",
    "resource_stable_key",
    "hwnd",
    "study_state",
    "cosecant_state",
)


def append_csv(path: Path, rows: list[dict]) -> None:
    """Append rows, refusing to append under a mismatched header.

    Appending 20-field rows beneath an 18-field header silently misaligns every
    later column -- the values are all present but read back against the wrong
    names, which is worse than a crash because it looks like valid data. If the
    instrument's schema has changed since the file was created, stop and say so
    rather than corrupt an already-collected dataset.
    """

    exists = path.exists()
    if exists:
        with path.open("r", newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle), [])
        if header and list(header) != list(FIELDS):
            raise RuntimeError(
                "CSV schema drift: existing header has "
                f"{len(header)} fields, instrument writes {len(FIELDS)}. "
                "Migrate or move the existing file before collecting more."
            )
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def verify_identity(rows: list[dict]) -> tuple[int, float]:
    """Every row must satisfy E ~= dO + L. Return (violations, worst delta)."""

    violations = 0
    worst = 0.0
    for row in rows:
        expected = (
            row["observation_gap_seconds"] + row["pre_advance_latency_seconds"]
        )
        delta = abs(expected - row["effective_gap_seconds"])
        worst = max(worst, delta)
        if delta > 1e-5:
            violations += 1
    return violations, worst


def summarise(condition: str, rows: list[dict]) -> str:
    if not rows:
        return f"CONDITION {condition}\n  NO SAMPLES\n"

    gaps = [r["observation_gap_seconds"] for r in rows]
    lat = [r["pre_advance_latency_seconds"] for r in rows]
    eff = [r["effective_gap_seconds"] for r in rows]

    internal = [r for r in rows if r["advance_source"] == "advance_internal_ns"]
    bias = [
        (r["advance_internal_ns"] - r["advance_call_ns"]) / 1e9
        for r in internal
        if isinstance(r["advance_internal_ns"], int)
    ]

    violations, worst = verify_identity(rows)

    out = [f"CONDITION {condition}", f"  rows: {len(rows)}"]
    out.append("  observation_gap_seconds  dO = O(i) - O(i-1)")
    out.append(fmt(describe(gaps)))
    out.append("  pre_advance_latency_seconds  L = A(i) - O(i)")
    out.append(fmt(describe(lat)))
    out.append("  effective_gap_seconds  E = A(i) - O(i-1)   <-- THE C9 QUANTITY")
    out.append(fmt(describe(eff)))
    out.append("  E exceedance counts:")
    for threshold in E_THRESHOLDS:
        count = sum(1 for value in eff if value > threshold) if threshold < 3.0 else sum(
            1 for value in eff if value >= threshold
        )
        label = ">=3.0" if threshold == 3.0 else f"> {threshold}"
        out.append(
            f"    E {label:<6} : {count:5d}  ({100.0 * count / len(eff):6.2f}%)"
        )
    out.append(
        f"  advance source: internal={len(internal)}  call-entry={len(rows) - len(internal)}"
    )
    if bias:
        out.append(
            "  measured call-entry under-estimate (internal - call), seconds:"
        )
        out.append(fmt(describe(bias)))
    else:
        out.append(
            "  measured call-entry under-estimate: NOT AVAILABLE in this condition "
            "(COSECANT.advance() returns before reading its clock when no break "
            "is active), so E here is a LOWER BOUND by that unmeasured amount."
        )
    out.append(
        f"  identity check E == dO + L: violations={violations} worst_delta={worst:.9f}s"
    )

    # Per-browser_status breakdown. Condition B showed the E tail is strongly
    # status-dependent -- failed/degraded UIA reads cost far more than
    # successful ones -- so an overall p99 can hide whether a required COSECANT
    # tolerance is covering ordinary sensing latency or UIA failure behaviour.
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["browser_status"] or "(none)", []).append(row)
    out.append("  BY browser_status:")
    for status in sorted(groups, key=lambda key: -len(groups[key])):
        group = groups[status]
        g_lat = [r["pre_advance_latency_seconds"] for r in group]
        g_eff = [r["effective_gap_seconds"] for r in group]
        lat_stats = describe(g_lat)
        eff_stats = describe(g_eff)
        note = "" if len(group) >= 100 else "   [n<100: p99 == max, not a true percentile]"
        out.append(f"    {status}  n={len(group)}{note}")
        out.append(
            f"      L  median={lat_stats['median']:.4f}  p95={lat_stats['p95']:.4f}  "
            f"p99={lat_stats['p99']:.4f}  max={lat_stats['max']:.4f}"
        )
        out.append(
            f"      E  median={eff_stats['median']:.4f}  p95={eff_stats['p95']:.4f}  "
            f"p99={eff_stats['p99']:.4f}  max={eff_stats['max']:.4f}"
        )
    # STABLE vs TRANSITION. D's central question is whether UIA is slow merely
    # because it sometimes fails, or specifically because the sensory target is
    # changing underneath it. Classification is done AFTER the fact from the
    # recorded opaque identity; nothing in production was altered to obtain it.
    keyed = [r for r in rows if r.get("resource_stable_key")]
    if keyed:
        stable: list[dict] = []
        transition: list[dict] = []
        previous_key = None
        for row in rows:
            key = row.get("resource_stable_key") or ""
            if previous_key is not None and key and key != previous_key:
                transition.append(row)
            elif previous_key is not None and key:
                stable.append(row)
            if key:
                previous_key = key
        out.append("  STABLE vs TRANSITION (by opaque resource identity):")
        for label, group in (("STABLE", stable), ("TRANSITION", transition)):
            if not group:
                out.append(f"    {label}  n=0")
                continue
            g_lat = [r["pre_advance_latency_seconds"] for r in group]
            g_eff = [r["effective_gap_seconds"] for r in group]
            lat_stats = describe(g_lat)
            eff_stats = describe(g_eff)
            fails = sum(1 for r in group if r["browser_status"] != "ok")
            note = "" if len(group) >= 100 else "   [n<100: p99 == max]"
            out.append(
                f"    {label}  n={len(group)}  non-ok reads={fails}"
                f" ({100.0 * fails / len(group):.1f}%){note}"
            )
            out.append(
                f"      L  median={lat_stats['median']:.4f}  p95={lat_stats['p95']:.4f}  "
                f"p99={lat_stats['p99']:.4f}  max={lat_stats['max']:.4f}"
            )
            out.append(
                f"      E  median={eff_stats['median']:.4f}  p95={eff_stats['p95']:.4f}  "
                f"p99={eff_stats['p99']:.4f}  max={eff_stats['max']:.4f}"
            )
    else:
        out.append(
            "  STABLE vs TRANSITION: NOT DERIVABLE -- this run predates the "
            "opaque resource_stable_key column."
        )
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="C9-A runtime gap measurement")
    parser.add_argument("--condition", required=True)
    parser.add_argument("--intervals", type=int, default=300)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--study-active", action="store_true")
    parser.add_argument("--break-seconds", type=int, default=0)
    parser.add_argument("--subject", default=STUDY_SUBJECT)
    parser.add_argument("--task", default=STUDY_TASK)
    parser.add_argument("--keywords", default=",".join(STUDY_KEYWORDS))
    parser.add_argument("--important", default=",".join(STUDY_IMPORTANT))
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    # EXCLUSIVITY GUARD. Two concurrent monitors contend for CPU and for the
    # same CSV, which silently corrupts BOTH datasets -- this happened once
    # during C9-A setup when a backgrounded run outlived the shell that
    # launched it. A measurement that cannot prove it ran alone is not
    # authoritative, so refuse rather than produce quietly contaminated data.
    lock_path = ARTIFACT_DIR / "measurement.lock"
    if lock_path.exists():
        print(
            f"[C9] REFUSING TO START: {lock_path} exists, so another "
            "measurement may still be running. Confirm no python measurement "
            "process is alive, then delete the lock file.",
            file=sys.stderr,
        )
        return 2
    lock_path.write_text(
        f"pid={os.getpid()} condition={args.condition} "
        f"started={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    try:
        return _run(args)
    finally:
        lock_path.unlink(missing_ok=True)


def _run(args) -> int:
    """Collect one condition. Rows are written per run so a later interruption
    cannot destroy an already-completed run's evidence."""

    raw_path = ARTIFACT_DIR / "C9_RUNTIME_GAP_RAW.csv"
    summary_path = ARTIFACT_DIR / "C9_RUNTIME_GAP_SUMMARY.txt"

    all_rows: list[dict] = []
    for run_number in range(1, args.runs + 1):
        collector = run_condition(
            args.condition,
            args.intervals,
            run_number,
            args.poll_seconds,
            study_active=args.study_active,
            break_seconds=args.break_seconds,
            target={
                "subject": args.subject,
                "task": args.task,
                "keywords": tuple(k.strip() for k in args.keywords.split(",") if k.strip()),
                "important": tuple(k.strip() for k in args.important.split(",") if k.strip()),
            },
        )
        append_csv(raw_path, collector.rows)
        all_rows.extend(collector.rows)

    text = summarise(args.condition, all_rows)
    stamp = datetime.now(timezone.utc).isoformat()
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== {args.condition} @ {stamp} =====\n")
        handle.write(text)
    print(text)
    print(f"[C9] raw -> {raw_path}")
    print(f"[C9] summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
