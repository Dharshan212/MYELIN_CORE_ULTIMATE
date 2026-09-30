"""Dashboard presentation regions consuming immutable SECANT projections only.

No final visual design, window creation, runtime access or database connection.
"""
from dataclasses import dataclass
from .read_model import SecantProjection


@dataclass(frozen=True, slots=True)
class DashboardRegion:
    name: str
    rows: tuple[tuple[str, str], ...]


def regions(snapshot: SecantProjection) -> tuple[DashboardRegion, ...]:
    if not isinstance(snapshot, SecantProjection):
        raise TypeError("SecantProjection required")
    scope = snapshot.scope
    recovery = snapshot.recovery
    return (
        DashboardRegion("Current episode", (
            ("Episode", snapshot.episode_id or "No episode"),
            ("Study context", scope.context_id if scope else ""),
            ("Study resource", scope.target_resource_id if scope else ""),
            ("Stage", snapshot.stage.name),
            ("Founding dwell (seconds)", str(snapshot.dwell_elapsed_ns / 1_000_000_000)),
            ("Escalation remaining (seconds)", "" if snapshot.escalation_remaining_ns is None else str(snapshot.escalation_remaining_ns / 1_000_000_000)),
            ("Frozen reasons", ", ".join(snapshot.frozen_reasons)),
            ("Popup", snapshot.popup_state))),
        DashboardRegion("Recovery", (
            ("Phase", recovery.phase.value), ("Attempt", recovery.attempt_id),
            ("Verification (seconds)", str(recovery.verification_elapsed_ns / 1_000_000_000)),
            ("Closure confirmation (seconds)", str(recovery.closure_elapsed_ns / 1_000_000_000)))),
        DashboardRegion("Episode timeline", tuple(
            (str(fact.at_ns), fact.name + (": " + fact.reason if fact.reason else ""))
            for fact in snapshot.timeline)),
        DashboardRegion("Completed episodes", tuple(
            (episode.episode_id, episode.terminal_reason) for episode in snapshot.completed)),
    )
