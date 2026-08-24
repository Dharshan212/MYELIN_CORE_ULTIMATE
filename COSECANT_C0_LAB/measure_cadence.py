"""C0 cadence measurement for W-7.

Chief's requirement:

    P = observed monitoring period
    J = realistic scheduling jitter
    G = maximum allowed presence gap
    C = 3-sec confirmation window  (LOCKED)

    required:  P + J < G < C

This script measures the ACTUAL distribution of the interval between
consecutive ``foreground.observed_monotonic_ns`` values, because that is the
exact quantity COSECANT compares against maximum_presence_gap_seconds:

    cosecant.observe_return:
        if now_ns - self._last_presence_ns > maximum_gap_ns: RESTART

It runs the REAL WindowsMonitorCoordinator with the REAL organs, in three
phases, and reports min / median / p95 / p99 / max plus the count of
intervals that would have restarted a return confirmation.

HONEST SCOPE NOTE
-----------------
The foreground and browser READS are scripted, so this measurement is a
LOWER BOUND on real-world jitter: it includes the full per-cycle work of
every organ, storage, telemetry and OS scheduling, but not the cost of the
real Win32 foreground read and the real UIA address-bar read. Those only
ADD time and variance. Any gap-violation rate reported here is therefore a
floor, not a ceiling.
"""

from __future__ import annotations

import statistics
import sys
import time

import _lab
from _lab import Engine, INSTAGRAM, LECTURE

PRODUCTION_POLL_SECONDS = 1.5
PRODUCTION_GAP_SECONDS = 1.5
CONFIRMATION_SECONDS = 3.0


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _collect(engine: Engine, seconds: float) -> list[float]:
    """Sample consecutive foreground observation timestamps from the live loop."""

    stamps: list[int] = []
    seen: set[int] = set()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        snapshot = engine.services.resource_intent._latest  # read-only peek
        if snapshot is not None:
            ns = snapshot.observation.observed_monotonic_ns
            if ns not in seen:
                seen.add(ns)
                stamps.append(ns)
        time.sleep(0.01)
    stamps.sort()
    return [
        (b - a) / 1_000_000_000.0 for a, b in zip(stamps, stamps[1:])
    ]


def _report(label: str, intervals: list[float]) -> dict:
    if len(intervals) < 3:
        print(f"  {label:<28} INSUFFICIENT SAMPLES ({len(intervals)})")
        return {}
    violations = [d for d in intervals if d > PRODUCTION_GAP_SECONDS]
    stats = {
        "label": label,
        "n": len(intervals),
        "min": min(intervals),
        "median": statistics.median(intervals),
        "p95": _percentile(intervals, 0.95),
        "p99": _percentile(intervals, 0.99),
        "max": max(intervals),
        "violations": len(violations),
        "violation_pct": 100.0 * len(violations) / len(intervals),
    }
    print(
        f"  {label:<28} n={stats['n']:<4} "
        f"min={stats['min']:.4f} med={stats['median']:.4f} "
        f"p95={stats['p95']:.4f} p99={stats['p99']:.4f} max={stats['max']:.4f} "
        f"| >G: {stats['violations']}/{stats['n']} ({stats['violation_pct']:.1f}%)"
    )
    return stats


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0

    print("=" * 78)
    print("C0 CADENCE MEASUREMENT (W-7)")
    print("=" * 78)
    print(f"  configured poll interval      : {PRODUCTION_POLL_SECONDS} s")
    print(f"  configured max presence gap G : {PRODUCTION_GAP_SECONDS} s")
    print(f"  locked confirmation window C  : {CONFIRMATION_SECONDS} s")
    print(f"  sampling window per phase     : {duration} s")
    print(f"  isolated storage              : {_lab.SCRATCH}")
    print()

    results = []
    with Engine(
        surface=LECTURE,
        poll_seconds=PRODUCTION_POLL_SECONDS,
        fast_cosecant=True,
    ) as engine:
        print("PHASE 1 — normal monitoring, no Study block")
        results.append(_report("idle monitoring", _collect(engine, duration)))

        print()
        print("PHASE 2 — Study Mode ACTIVE, certified browser evidence")
        engine.send(
            "study_prepare",
            subject="Neuroscience",
            task="basal ganglia",
            planned_seconds=3600,
        )
        engine.send("study_action", action="START")
        time.sleep(3.0)
        results.append(_report("study active", _collect(engine, duration)))

        print()
        print("PHASE 3 — COSECANT break ACTIVE, user off on social media")
        engine.send("study_break", selected_break_seconds=60)
        time.sleep(3.0)
        engine.look_at(INSTAGRAM)
        results.append(_report("cosecant break active", _collect(engine, duration)))

    print()
    print("=" * 78)
    usable = [r for r in results if r]
    if not usable:
        print("  NO USABLE SAMPLES — investigate before C1.")
        return 1

    worst_p99 = max(r["p99"] for r in usable)
    worst_max = max(r["max"] for r in usable)
    total_violations = sum(r["violations"] for r in usable)
    total_samples = sum(r["n"] for r in usable)

    print("SUMMARY")
    print(f"  worst p99 interval            : {worst_p99:.4f} s")
    print(f"  worst max interval            : {worst_max:.4f} s")
    print(
        f"  intervals exceeding G=1.5 s   : {total_violations}/{total_samples} "
        f"({100.0 * total_violations / total_samples:.1f}%)"
    )
    print()
    print("  Chief's required relationship : P + J < G < C")
    print(f"  observed P + J (worst p99)    : {worst_p99:.4f} s")
    print(f"  current G                     : {PRODUCTION_GAP_SECONDS} s")
    print(f"  locked C                      : {CONFIRMATION_SECONDS} s")
    print()
    if worst_p99 >= PRODUCTION_GAP_SECONDS:
        print("  VERDICT: P + J >= G. The current G=1.5 s is UNSAFE.")
    else:
        print("  VERDICT: P + J < G held in this run. Margin is still thin.")
    print()
    print("  NOTE: browser/foreground reads are scripted here, so these are")
    print("        LOWER BOUNDS. Real UIA reads only add time and variance.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
