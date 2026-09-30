"""SECANT factual report composition; no historical conversion or persistence."""
from dataclasses import dataclass
from .read_model import SecantProjection, TimelineFact


@dataclass(frozen=True, slots=True)
class ReportSection:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecantReport:
    title: str
    sections: tuple[ReportSection, ...]


def _timeline(facts: tuple[TimelineFact, ...]) -> tuple[str, ...]:
    return tuple(
        f"{fact.at_ns} ns | {fact.name} | {fact.stage.name}"
        f" | request={fact.request_id} | attempt={fact.attempt_id}"
        f" | reason={fact.reason} | evidence={fact.evidence_id}"
        for fact in facts
    )


def compose(snapshot: SecantProjection) -> SecantReport:
    """Format current facts and completed projections without inventing outcomes."""
    if not isinstance(snapshot, SecantProjection):
        raise TypeError("SecantProjection required")
    scope = snapshot.scope
    sections = [ReportSection("Current SECANT state", (
        f"Episode: {snapshot.episode_id or 'No episode'}",
        f"Study context: {scope.context_id if scope else ''}",
        f"Study resource: {scope.target_resource_id if scope else ''}",
        f"Stage: {snapshot.stage.name}",
        f"Founding dwell: {snapshot.dwell_elapsed_ns} ns",
        f"Escalation remainder: {snapshot.escalation_remaining_ns} ns",
        f"Frozen reasons: {', '.join(snapshot.frozen_reasons)}",
        f"Recovery: {snapshot.recovery.phase.value}",
        f"Verification: {snapshot.recovery.verification_elapsed_ns} ns / 10000000000 ns",
        f"Closure: {snapshot.recovery.closure_elapsed_ns} ns / 60000000000 ns",
        f"Terminal reason: {snapshot.terminal_reason or 'Not terminal'}",
    )), ReportSection("Current timeline (monotonic timestamps)", _timeline(snapshot.timeline))]
    for episode in snapshot.completed:
        proof = episode.recovery.proof
        summary = (
            f"Study context: {episode.scope.context_id}",
            f"Study resource: {episode.scope.target_resource_id}",
            f"Final stage: {episode.stage.name}",
            f"Founded: {episode.founded_ns} ns; closed: {episode.closed_ns} ns",
            f"Terminal reason: {episode.terminal_reason}",
            f"Recovery proof: {proof.attempt_id if proof else 'None'}",
        )
        if proof:
            summary += (f"Return onset: {proof.return_started_ns}; verified: {proof.verified_ns}; closed: {proof.closed_ns}",
                        "Recovery evidence: " + ", ".join(proof.evidence_ids))
        sections.append(ReportSection(episode.episode_id, summary + _timeline(episode.timeline)))
    return SecantReport("MYELIN SECANT episode report", tuple(sections))


def text(report: SecantReport) -> str:
    if not isinstance(report, SecantReport):
        raise TypeError("SecantReport required")
    return report.title + "\n\n" + "\n\n".join(
        section.title + "\n" + "\n".join(section.lines) for section in report.sections
    ) + "\n"
