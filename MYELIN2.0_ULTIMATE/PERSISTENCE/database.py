"""Single SQLite connection/transaction authority for MYELIN 2.0.

The worker lane serialises every write.  A returned ``RUNNING`` receipt means
exactly one thing: the transaction is not terminal yet.  Callers must wait for
or later reconcile the same receipt before moving domain truth forward.

This module also owns runtime paths.  Resource paths are containment checked;
``..`` or absolute-path escapes are rejected instead of silently leaving the
MYELIN tree.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Final


DATABASE_FILENAME: Final = "myelin2.0_session.db"
WRITE_QUEUE_CAPACITY: Final = 128
SQLITE_BUSY_TIMEOUT_MS: Final = 5_000


class ReceiptState(str, Enum):
    RUNNING = "RUNNING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class TransactionResult:
    """Result identity returned by one committed write callback."""

    result_id: int | None = None
    session_id: int | None = None


@dataclass(frozen=True, slots=True)
class TransactionReceipt:
    """Immutable observation of one submitted SQLite transaction."""

    receipt_id: str
    state: ReceiptState
    operation: str
    result_id: int | None = None
    session_id: int | None = None
    error: str = ""


@dataclass(slots=True)
class _ReceiptRecord:
    operation: str
    done: threading.Event
    receipt: TransactionReceipt


WriteOperation = Callable[[sqlite3.Connection], TransactionResult | int | None]


def app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    path = (root / "MYELIN").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return app_data_dir() / DATABASE_FILENAME


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str | os.PathLike[str]) -> Path:
    """Resolve one approved runtime asset path without allowing escape."""

    relative = Path(relative_path)
    if relative.is_absolute():
        raise ValueError("resource path must be relative to MYELIN2.0_ULTIMATE")
    root = project_root()
    candidate = (root / "Required_assets" / relative).resolve()
    asset_root = (root / "Required_assets").resolve()
    try:
        candidate.relative_to(asset_root)
    except ValueError as exc:
        raise ValueError("resource path escapes Required_assets") from exc
    return candidate


def connect_database(*, read_only: bool = False) -> sqlite3.Connection:
    path = database_path()
    if read_only:
        uri = f"file:{path.as_posix()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
    else:
        connection = sqlite3.connect(
            path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    return connection


def _bounded_error(error: BaseException) -> str:
    text = " ".join(f"{type(error).__name__}: {error}".split())
    return text[:500]


class SQLiteTransactionLane:
    """One ordered background writer with durable terminal receipts."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, str, WriteOperation] | None] = queue.Queue(
            maxsize=WRITE_QUEUE_CAPACITY
        )
        self._records: dict[str, _ReceiptRecord] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="MyelinSQLiteLane",
            daemon=True,
        )
        self._thread.start()

    def submit(self, operation: str, callback: WriteOperation) -> TransactionReceipt:
        name = " ".join(str(operation).split())[:120]
        if not name:
            raise ValueError("transaction operation must not be empty")
        if not callable(callback):
            raise TypeError("transaction callback must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("SQLite transaction lane is closed")
            receipt_id = uuid.uuid4().hex
            receipt = TransactionReceipt(
                receipt_id=receipt_id,
                state=ReceiptState.RUNNING,
                operation=name,
            )
            self._records[receipt_id] = _ReceiptRecord(
                operation=name,
                done=threading.Event(),
                receipt=receipt,
            )
        try:
            self._queue.put_nowait((receipt_id, name, callback))
        except queue.Full:
            failed = TransactionReceipt(
                receipt_id=receipt_id,
                state=ReceiptState.FAILED,
                operation=name,
                error="SQLite transaction queue is full",
            )
            with self._lock:
                record = self._records[receipt_id]
                record.receipt = failed
                record.done.set()
            return failed
        return receipt

    def receipt(self, receipt_id: str) -> TransactionReceipt | None:
        with self._lock:
            record = self._records.get(str(receipt_id or ""))
            return record.receipt if record is not None else None

    def wait(
        self,
        receipt_id: str,
        *,
        timeout_seconds: float,
    ) -> TransactionReceipt | None:
        with self._lock:
            record = self._records.get(str(receipt_id or ""))
        if record is None:
            return None
        record.done.wait(max(0.0, float(timeout_seconds)))
        return self.receipt(receipt_id)

    def shutdown(self, *, timeout_seconds: float = 8.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        # FIFO ordering guarantees that the sentinel runs after previously
        # accepted writes.  Never silently discard a queued terminal write.
        remaining = max(0.0, deadline - time.monotonic())
        try:
            self._queue.put(None, timeout=remaining)
        except queue.Full as exc:
            raise RuntimeError("SQLite lane could not enqueue shutdown barrier") from exc
        self._thread.join(max(0.0, deadline - time.monotonic()))
        if self._thread.is_alive():
            raise RuntimeError("SQLite lane did not finish its ordered writes")

    def _run(self) -> None:
        connection = connect_database(read_only=False)
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    self._queue.task_done()
                    return
                receipt_id, operation, callback = item
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    raw_result = callback(connection)
                    if isinstance(raw_result, TransactionResult):
                        result = raw_result
                    elif type(raw_result) is int:
                        result = TransactionResult(result_id=raw_result)
                    elif raw_result is None:
                        result = TransactionResult()
                    else:
                        raise TypeError("transaction callback returned an invalid result")
                    connection.commit()
                    terminal = TransactionReceipt(
                        receipt_id=receipt_id,
                        state=ReceiptState.COMMITTED,
                        operation=operation,
                        result_id=result.result_id,
                        session_id=result.session_id,
                    )
                except Exception as error:
                    try:
                        connection.rollback()
                    except sqlite3.Error:
                        pass
                    terminal = TransactionReceipt(
                        receipt_id=receipt_id,
                        state=ReceiptState.FAILED,
                        operation=operation,
                        error=_bounded_error(error),
                    )
                with self._lock:
                    record = self._records.get(receipt_id)
                    if record is not None:
                        record.receipt = terminal
                        record.done.set()
                self._queue.task_done()
        finally:
            connection.close()


__all__ = [
    "ReceiptState",
    "SQLiteTransactionLane",
    "TransactionReceipt",
    "TransactionResult",
    "app_data_dir",
    "connect_database",
    "database_path",
    "project_root",
    "resource_path",
]
