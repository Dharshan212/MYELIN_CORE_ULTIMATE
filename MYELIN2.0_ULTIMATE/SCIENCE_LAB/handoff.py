"""In-memory authority for explicit Chapter 3 -> Chapter 5 transfer.

This module performs no analysis, source reads, persistence, Qt work, or
report generation.  It retains one receipt that points to the exact immutable
Phase 2.4 package selected by an explicit user transfer action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .analysis import CERTIFIED, Chapter3AnalysisOutcome, Chapter3ResultPackage


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True, slots=True)
class Chapter3TransferReceipt:
    """One immutable record of an explicit in-memory package handoff."""

    package: Chapter3ResultPackage
    experiment_id: str
    parent_session_id: int
    transferred_at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.package, Chapter3ResultPackage):
            raise TypeError("transfer receipt requires a Chapter3ResultPackage")
        if self.package.analysis_status != CERTIFIED:
            raise ValueError("only a CERTIFIED package may be transferred")
        if (
            self.experiment_id != self.package.experiment_id
            or self.parent_session_id != self.package.parent_session_id
        ):
            raise ValueError("transfer receipt identity differs from its package")
        if type(self.transferred_at_utc) is not str or not self.transferred_at_utc:
            raise ValueError("transfer receipt requires a UTC transfer time")


class Chapter3ResultHandoff:
    """Retain the latest explicitly transferred certified package."""

    def __init__(self) -> None:
        self._last_receipt: Chapter3TransferReceipt | None = None

    @property
    def last_receipt(self) -> Chapter3TransferReceipt | None:
        return self._last_receipt

    @staticmethod
    def can_transfer(outcome: Chapter3AnalysisOutcome | None) -> bool:
        return (
            isinstance(outcome, Chapter3AnalysisOutcome)
            and outcome.status == CERTIFIED
            and isinstance(outcome.package, Chapter3ResultPackage)
            and outcome.package.analysis_status == CERTIFIED
        )

    def transfer(
        self,
        outcome: Chapter3AnalysisOutcome | None,
    ) -> Chapter3TransferReceipt:
        """Transfer the exact package, idempotently for equal package truth."""

        if not self.can_transfer(outcome):
            raise RuntimeError("a CERTIFIED Chapter 3 package is required")
        package = outcome.package
        if self._last_receipt is not None and self._last_receipt.package == package:
            return self._last_receipt
        receipt = Chapter3TransferReceipt(
            package=package,
            experiment_id=package.experiment_id,
            parent_session_id=package.parent_session_id,
            transferred_at_utc=_utc_now(),
        )
        self._last_receipt = receipt
        return receipt

    def rollback_failed_delivery(
        self,
        *,
        attempted: Chapter3TransferReceipt,
        previous: Chapter3TransferReceipt | None,
    ) -> None:
        """Restore authority after Chapter 5 rejects the attempted receipt.

        The identity guard prevents an unrelated or stale caller from rolling
        back a newer successful transfer.
        """

        if self._last_receipt is not attempted:
            raise RuntimeError("cannot roll back a superseded transfer receipt")
        self._last_receipt = previous


__all__ = ["Chapter3ResultHandoff", "Chapter3TransferReceipt"]
