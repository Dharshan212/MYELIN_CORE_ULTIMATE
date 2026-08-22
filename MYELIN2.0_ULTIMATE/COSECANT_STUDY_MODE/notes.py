"""Study Notes for the final MYELIN Study Mode subsystem.

This file owns note documents, safe editing, autosave and the Notes workspace.
It does not own SQLite tables.  Persistence is injected through ``NoteStore``
so the future persistence lane remains the only database authority.

The most important rule in this file
------------------------------------
Table, formula and drawing blocks are *opaque structured blocks*.  Their
canonical JSON payload and SHA-256 digest remain attached to the block while
ordinary text is edited.  The generic editor never converts one of these
blocks into display text.  Only its matching structured editor may replace
its payload.  Invalid payloads fail visibly instead of becoming placeholders.

The runtime order is deliberately small:

1. load or create one immutable ``NoteDocument``;
2. edit through validated document operations;
3. mark the new immutable generation dirty;
4. autosave one generation at a time on one worker; and
5. flush the latest accepted generation before navigation or shutdown.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from html.parser import HTMLParser
from typing import Final, Protocol, TypeAlias


NOTES_SCHEMA_VERSION: Final = "myelin-study-notes-v1"
OPAQUE_SCHEMA_VERSION: Final = 1
AUTOSAVE_SECONDS: Final = 1.5

TITLE_MAX: Final = 300
TEXT_BLOCK_MAX: Final = 100_000
DOCUMENT_TEXT_MAX: Final = 1_000_000
BLOCKS_MAX: Final = 2_000
PASTE_TEXT_MAX: Final = 100_000
PASTE_HTML_MAX: Final = 500_000
PASTE_SEGMENTS_MAX: Final = 10_000
OPAQUE_JSON_MAX: Final = 4_000_000

TABLE_ROWS_MAX: Final = 100
TABLE_COLUMNS_MAX: Final = 50
TABLE_CELLS_MAX: Final = 2_000
FORMULA_SOURCE_MAX: Final = 20_000
DRAWING_DIMENSION_MAX: Final = 8_192
DRAWING_STROKES_MAX: Final = 20_000
DRAWING_POINTS_MAX: Final = 500_000


class NoteValidationError(ValueError):
    """The note is unsafe, malformed or outside a bounded contract."""


class NoteKind(str, Enum):
    SESSION = "SESSION"
    PLAN = "PLAN"
    QUICK_CAPTURE = "QUICK_CAPTURE"


class BlockKind(str, Enum):
    PARAGRAPH = "PARAGRAPH"
    HEADING = "HEADING"
    TABLE = "TABLE"
    FORMULA = "FORMULA"
    DRAWING = "DRAWING"
    DIVIDER = "DIVIDER"


OPAQUE_BLOCK_KINDS: Final = frozenset(
    {BlockKind.TABLE, BlockKind.FORMULA, BlockKind.DRAWING}
)


class SaveState(str, Enum):
    SAVED = "SAVED"
    UNSAVED = "UNSAVED"
    SAVING = "SAVING"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class TextSpan:
    """One safe text run.  No HTML or executable content is stored."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise NoteValidationError("text span must contain text")
        if any(type(value) is not bool for value in (self.bold, self.italic, self.underline)):
            raise NoteValidationError("text style flags must be booleans")


@dataclass(frozen=True, slots=True)
class OpaquePayload:
    """A structured block payload preserved exactly by the generic editor.

    ``payload_json`` is canonical JSON, not a display label.  Its digest makes
    accidental replacement or partial persistence detectable at load time.
    """

    schema_version: int
    renderer_version: int
    payload_json: str
    sha256: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise NoteValidationError("opaque schema version must be positive")
        if type(self.renderer_version) is not int or self.renderer_version < 1:
            raise NoteValidationError("opaque renderer version must be positive")
        if not isinstance(self.payload_json, str):
            raise NoteValidationError("opaque payload must be canonical JSON text")
        payload_bytes = self.payload_json.encode("utf-8")
        if len(payload_bytes) > OPAQUE_JSON_MAX:
            raise NoteValidationError("opaque payload exceeds its byte limit")
        expected = hashlib.sha256(payload_bytes).hexdigest()
        if not secrets.compare_digest(expected, str(self.sha256)):
            raise NoteValidationError("opaque payload digest does not match")
        try:
            decoded = json.loads(self.payload_json)
        except (TypeError, ValueError) as exc:
            raise NoteValidationError("opaque payload is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise NoteValidationError("opaque payload root must be an object")

    @classmethod
    def from_data(
        cls,
        data: dict[str, object],
        *,
        renderer_version: int = 1,
    ) -> OpaquePayload:
        payload_json = _canonical_json(data)
        return cls(
            schema_version=OPAQUE_SCHEMA_VERSION,
            renderer_version=renderer_version,
            payload_json=payload_json,
            sha256=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        )

    def data(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        assert isinstance(value, dict)
        return value


BlockContent: TypeAlias = tuple[TextSpan, ...] | OpaquePayload | None


@dataclass(frozen=True, slots=True)
class NoteBlock:
    block_id: str
    kind: BlockKind
    content: BlockContent
    version: int = 1

    def __post_init__(self) -> None:
        _clean_id(self.block_id, "block_id")
        if not isinstance(self.kind, BlockKind):
            raise NoteValidationError("block kind is unsupported")
        if type(self.version) is not int or self.version < 1:
            raise NoteValidationError("block version must be positive")
        if self.kind in {BlockKind.PARAGRAPH, BlockKind.HEADING}:
            _validate_spans(self.content)
        elif self.kind in OPAQUE_BLOCK_KINDS:
            if not isinstance(self.content, OpaquePayload):
                raise NoteValidationError(
                    f"{self.kind.value.lower()} block requires an opaque payload"
                )
            _validate_opaque_for_kind(self.kind, self.content)
        elif self.kind is BlockKind.DIVIDER and self.content is not None:
            raise NoteValidationError("divider cannot contain arbitrary data")


@dataclass(frozen=True, slots=True)
class NoteDocument:
    note_id: str
    title: str
    note_kind: NoteKind
    blocks: tuple[NoteBlock, ...]
    revision_number: int
    created_at_utc: str
    updated_at_utc: str
    linked_study_block_id: str = ""
    linked_plan_id: str = ""
    linked_plan_block_id: str = ""
    linked_task: str = ""
    schema_version: str = NOTES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _clean_id(self.note_id, "note_id")
        if not isinstance(self.note_kind, NoteKind):
            raise NoteValidationError("note kind is unsupported")
        title = " ".join(str(self.title).split())
        if not title or len(title) > TITLE_MAX:
            raise NoteValidationError(f"title must contain 1 to {TITLE_MAX} characters")
        if type(self.revision_number) is not int or self.revision_number < 0:
            raise NoteValidationError("revision number cannot be negative")
        _utc_text(self.created_at_utc, "created_at_utc")
        _utc_text(self.updated_at_utc, "updated_at_utc")
        if self.schema_version != NOTES_SCHEMA_VERSION:
            raise NoteValidationError("note schema version is unsupported")
        if not isinstance(self.blocks, tuple) or not self.blocks:
            raise NoteValidationError("note must contain at least one block")
        if len(self.blocks) > BLOCKS_MAX:
            raise NoteValidationError("note contains too many blocks")
        ids: set[str] = set()
        total_text = len(title)
        for block in self.blocks:
            if not isinstance(block, NoteBlock):
                raise NoteValidationError("note contains an invalid block")
            if block.block_id in ids:
                raise NoteValidationError("block IDs must be unique")
            ids.add(block.block_id)
            if isinstance(block.content, tuple):
                total_text += sum(len(span.text) for span in block.content)
        if total_text > DOCUMENT_TEXT_MAX:
            raise NoteValidationError("note text exceeds its limit")
        for name in (
            "linked_study_block_id",
            "linked_plan_id",
            "linked_plan_block_id",
        ):
            value = getattr(self, name)
            if value:
                _clean_id(value, name)
        if len(str(self.linked_task)) > 1_000:
            raise NoteValidationError("linked task exceeds its limit")
        object.__setattr__(self, "title", title)


@dataclass(frozen=True, slots=True)
class NoteSummary:
    note_id: str
    title: str
    note_kind: NoteKind
    updated_at_utc: str
    linked_study_block_id: str = ""
    linked_plan_id: str = ""


@dataclass(frozen=True, slots=True)
class NoteSessionSnapshot:
    document: NoteDocument | None
    save_state: SaveState
    detail: str
    edit_generation: int
    saved_generation: int


class NoteStore(Protocol):
    """Narrow persistence connection; implementation belongs elsewhere."""

    def load_note(self, note_id: str) -> NoteDocument: ...

    def list_notes(self, note_kind: NoteKind | None = None) -> tuple[NoteSummary, ...]: ...

    def save_note(
        self,
        document: NoteDocument,
        *,
        expected_revision: int,
    ) -> NoteDocument: ...


# ---------------------------------------------------------------------------
# Structured block creation and validation.
# ---------------------------------------------------------------------------


def make_table_payload(
    rows: int = 3,
    columns: int = 3,
    *,
    header_row: bool = False,
    cells: Sequence[Sequence[str]] | None = None,
) -> OpaquePayload:
    _bounded_int(rows, "table rows", 1, TABLE_ROWS_MAX)
    _bounded_int(columns, "table columns", 1, TABLE_COLUMNS_MAX)
    if rows * columns > TABLE_CELLS_MAX:
        raise NoteValidationError("table contains too many cells")
    if type(header_row) is not bool:
        raise NoteValidationError("table header flag must be a boolean")
    source = cells or tuple(tuple("" for _ in range(columns)) for _ in range(rows))
    if len(source) != rows or any(len(row) != columns for row in source):
        raise NoteValidationError("table must remain rectangular")
    values: list[list[str]] = []
    for row in source:
        values.append([_bounded_text(value, "table cell", 20_000) for value in row])
    return OpaquePayload.from_data(
        {"rows": rows, "columns": columns, "header_row": header_row, "cells": values}
    )


def make_formula_payload(source: str) -> OpaquePayload:
    return OpaquePayload.from_data(
        {
            "source": _bounded_text(source, "formula source", FORMULA_SOURCE_MAX),
            "syntax_version": 1,
        }
    )


def make_drawing_payload(
    width: int = 900,
    height: int = 500,
    *,
    strokes: Sequence[dict[str, object]] = (),
) -> OpaquePayload:
    _bounded_int(width, "drawing width", 1, DRAWING_DIMENSION_MAX)
    _bounded_int(height, "drawing height", 1, DRAWING_DIMENSION_MAX)
    if len(strokes) > DRAWING_STROKES_MAX:
        raise NoteValidationError("drawing contains too many strokes")
    total_points = 0
    clean_strokes: list[dict[str, object]] = []
    for raw in strokes:
        if not isinstance(raw, dict):
            raise NoteValidationError("drawing stroke is invalid")
        points = raw.get("points")
        if not isinstance(points, (list, tuple)) or not points:
            raise NoteValidationError("drawing stroke must contain points")
        clean_points: list[list[float]] = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise NoteValidationError("drawing point is invalid")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1:
                raise NoteValidationError("drawing point must be normalized")
            clean_points.append([x, y])
        total_points += len(clean_points)
        if total_points > DRAWING_POINTS_MAX:
            raise NoteValidationError("drawing contains too many points")
        clean_strokes.append(
            {
                "stroke_id": _clean_id(raw.get("stroke_id") or _new_id(), "stroke_id"),
                "color": _safe_color(raw.get("color", "#dcecff")),
                "width": _bounded_float(raw.get("width", 2.0), "stroke width", 0.25, 64.0),
                "points": clean_points,
            }
        )
    return OpaquePayload.from_data(
        {"width": width, "height": height, "strokes": clean_strokes}
    )


def create_note(
    *,
    title: str = "Untitled Note",
    note_kind: NoteKind = NoteKind.SESSION,
    linked_study_block_id: str = "",
    linked_plan_id: str = "",
    linked_plan_block_id: str = "",
    linked_task: str = "",
    note_id: str = "",
) -> NoteDocument:
    now = _now_utc()
    return NoteDocument(
        note_id=note_id or _new_id(),
        title=title,
        note_kind=note_kind,
        blocks=(NoteBlock(_new_id(), BlockKind.PARAGRAPH, (TextSpan(""),)),),
        revision_number=0,
        created_at_utc=now,
        updated_at_utc=now,
        linked_study_block_id=linked_study_block_id,
        linked_plan_id=linked_plan_id,
        linked_plan_block_id=linked_plan_block_id,
        linked_task=" ".join(str(linked_task).split()),
    )


def rename_note(document: NoteDocument, title: str) -> NoteDocument:
    return _changed(document, title=title)


def replace_text_block(
    document: NoteDocument,
    block_id: str,
    spans: tuple[TextSpan, ...],
) -> NoteDocument:
    _validate_spans(spans)
    return _replace_block(
        document,
        block_id,
        lambda block: replace(block, content=spans, version=block.version + 1),
        allowed={BlockKind.PARAGRAPH, BlockKind.HEADING},
    )


def insert_text_block(
    document: NoteDocument,
    *,
    after_block_id: str = "",
    heading: bool = False,
) -> NoteDocument:
    block = NoteBlock(
        _new_id(),
        BlockKind.HEADING if heading else BlockKind.PARAGRAPH,
        (TextSpan(""),),
    )
    return _insert_block(document, block, after_block_id)


def insert_table_block(
    document: NoteDocument,
    *,
    rows: int = 3,
    columns: int = 3,
    after_block_id: str = "",
) -> NoteDocument:
    return _insert_block(
        document,
        NoteBlock(_new_id(), BlockKind.TABLE, make_table_payload(rows, columns)),
        after_block_id,
    )


def insert_formula_block(
    document: NoteDocument,
    source: str,
    *,
    after_block_id: str = "",
) -> NoteDocument:
    return _insert_block(
        document,
        NoteBlock(_new_id(), BlockKind.FORMULA, make_formula_payload(source)),
        after_block_id,
    )


def insert_drawing_block(
    document: NoteDocument,
    payload: OpaquePayload | None = None,
    *,
    after_block_id: str = "",
) -> NoteDocument:
    return _insert_block(
        document,
        NoteBlock(_new_id(), BlockKind.DRAWING, payload or make_drawing_payload()),
        after_block_id,
    )


def replace_structured_payload(
    document: NoteDocument,
    block_id: str,
    kind: BlockKind,
    payload: OpaquePayload,
) -> NoteDocument:
    """Replace one structured payload without permitting a type change."""

    if kind not in OPAQUE_BLOCK_KINDS:
        raise NoteValidationError("replacement kind is not structured")
    _validate_opaque_for_kind(kind, payload)
    return _replace_block(
        document,
        block_id,
        lambda block: replace(block, content=payload, version=block.version + 1),
        allowed={kind},
    )


def delete_block(document: NoteDocument, block_id: str) -> NoteDocument:
    remaining = tuple(block for block in document.blocks if block.block_id != block_id)
    if len(remaining) == len(document.blocks):
        raise NoteValidationError("block was not found")
    if not remaining:
        remaining = (NoteBlock(_new_id(), BlockKind.PARAGRAPH, (TextSpan(""),)),)
    return _changed(document, blocks=remaining)


def link_note_to_study(
    document: NoteDocument,
    *,
    study_block_id: str,
    task: str = "",
) -> NoteDocument:
    _clean_id(study_block_id, "study_block_id")
    return _changed(
        document,
        linked_study_block_id=study_block_id,
        linked_task=" ".join(str(task).split()),
    )


def link_note_to_plan(
    document: NoteDocument,
    *,
    plan_id: str,
    plan_block_id: str = "",
) -> NoteDocument:
    _clean_id(plan_id, "plan_id")
    if plan_block_id:
        _clean_id(plan_block_id, "plan_block_id")
    return _changed(
        document,
        linked_plan_id=plan_id,
        linked_plan_block_id=plan_block_id,
    )


# ---------------------------------------------------------------------------
# Lossless JSON boundary.  Structured payload_json is copied, never rebuilt.
# ---------------------------------------------------------------------------


def document_to_json(document: NoteDocument) -> str:
    if not isinstance(document, NoteDocument):
        raise NoteValidationError("document contract is invalid")
    data: dict[str, object] = {
        "schema_version": document.schema_version,
        "note_id": document.note_id,
        "title": document.title,
        "note_kind": document.note_kind.value,
        "revision_number": document.revision_number,
        "created_at_utc": document.created_at_utc,
        "updated_at_utc": document.updated_at_utc,
        "linked_study_block_id": document.linked_study_block_id,
        "linked_plan_id": document.linked_plan_id,
        "linked_plan_block_id": document.linked_plan_block_id,
        "linked_task": document.linked_task,
        "blocks": [_block_to_data(block) for block in document.blocks],
    }
    return _canonical_json(data)


def document_from_json(source: str) -> NoteDocument:
    try:
        data = json.loads(str(source))
    except (TypeError, ValueError) as exc:
        raise NoteValidationError("note JSON is invalid") from exc
    if not isinstance(data, dict):
        raise NoteValidationError("note JSON root must be an object")
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        raise NoteValidationError("note blocks must be a list")
    try:
        return NoteDocument(
            note_id=str(data["note_id"]),
            title=str(data["title"]),
            note_kind=NoteKind(str(data["note_kind"])),
            blocks=tuple(_block_from_data(item) for item in blocks),
            revision_number=_exact_int(data["revision_number"], "revision_number"),
            created_at_utc=str(data["created_at_utc"]),
            updated_at_utc=str(data["updated_at_utc"]),
            linked_study_block_id=str(data.get("linked_study_block_id", "")),
            linked_plan_id=str(data.get("linked_plan_id", "")),
            linked_plan_block_id=str(data.get("linked_plan_block_id", "")),
            linked_task=str(data.get("linked_task", "")),
            schema_version=str(data["schema_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, NoteValidationError):
            raise
        raise NoteValidationError("note JSON contract is incomplete") from exc


# ---------------------------------------------------------------------------
# Safe paste.  HTML becomes bounded text plus B/I/U flags only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SafePasteResult:
    spans: tuple[TextSpan, ...]
    accepted: bool
    removed_unsafe_content: bool = False
    reason: str = ""

    @property
    def plain_text(self) -> str:
        return "".join(span.text for span in self.spans)


def sanitize_plain_text(value: object) -> SafePasteResult:
    try:
        text = _normalize_paste_text(str(value or ""))
    except Exception:
        return SafePasteResult((), False, reason="Clipboard text could not be read")
    if len(text) > PASTE_TEXT_MAX:
        return SafePasteResult((), False, reason="Clipboard text is too large")
    return SafePasteResult((TextSpan(text),), True)


class _PasteHtmlParser(HTMLParser):
    _SUPPRESSED = frozenset(
        {"script", "style", "iframe", "object", "embed", "svg", "math", "video", "audio"}
    )
    _BLOCKS = frozenset(
        {"p", "div", "li", "tr", "table", "section", "article", "header", "footer", "br"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.spans: list[TextSpan] = []
        self.bold = 0
        self.italic = 0
        self.underline = 0
        self.suppressed = 0
        self.removed = False
        self.failed = ""

    def _append(self, text: str) -> None:
        if self.suppressed or self.failed or not text:
            return
        text = _normalize_paste_text(text)
        total = sum(len(span.text) for span in self.spans) + len(text)
        if total > PASTE_TEXT_MAX or len(self.spans) >= PASTE_SEGMENTS_MAX:
            self.failed = "Clipboard content is too large"
            self.spans.clear()
            return
        value = TextSpan(text, self.bold > 0, self.italic > 0, self.underline > 0)
        if self.spans and (
            self.spans[-1].bold,
            self.spans[-1].italic,
            self.spans[-1].underline,
        ) == (value.bold, value.italic, value.underline):
            previous = self.spans[-1]
            self.spans[-1] = replace(previous, text=previous.text + value.text)
        else:
            self.spans.append(value)

    def _break(self) -> None:
        if self.spans and not self.spans[-1].text.endswith("\n"):
            self._append("\n")

    def handle_starttag(self, tag: str, attrs) -> None:
        name = tag.casefold()
        if attrs:
            self.removed = True
        if name in self._SUPPRESSED:
            self.suppressed += 1
            self.removed = True
        elif self.suppressed:
            return
        elif name in {"b", "strong"}:
            self.bold += 1
        elif name in {"i", "em"}:
            self.italic += 1
        elif name == "u":
            self.underline += 1
        elif name in self._BLOCKS:
            self._break()
        else:
            self.removed = True

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if name in self._SUPPRESSED:
            self.suppressed = max(0, self.suppressed - 1)
        elif self.suppressed:
            return
        elif name in {"b", "strong"}:
            self.bold = max(0, self.bold - 1)
        elif name in {"i", "em"}:
            self.italic = max(0, self.italic - 1)
        elif name == "u":
            self.underline = max(0, self.underline - 1)
        elif name in self._BLOCKS:
            self._break()

    def handle_data(self, data: str) -> None:
        self._append(data)


def sanitize_html(value: object) -> SafePasteResult:
    try:
        source = str(value or "")
    except Exception:
        return SafePasteResult((), False, True, "Clipboard HTML could not be read")
    if len(source) > PASTE_HTML_MAX:
        return SafePasteResult((), False, True, "Clipboard HTML is too large")
    parser = _PasteHtmlParser()
    try:
        parser.feed(source)
        parser.close()
    except (AssertionError, ValueError):
        return SafePasteResult((), False, True, "Clipboard HTML is malformed")
    if parser.failed:
        return SafePasteResult((), False, parser.removed, parser.failed)
    while parser.spans and parser.spans[-1].text == "\n":
        parser.spans.pop()
    return SafePasteResult(tuple(parser.spans) or (TextSpan(""),), True, parser.removed)


def sanitize_mime_payload(mime_data: object) -> SafePasteResult:
    """Read a QMimeData-like object without trusting its HTML or objects."""

    try:
        if bool(getattr(mime_data, "hasHtml", lambda: False)()):
            return sanitize_html(getattr(mime_data, "html", lambda: "")())
        return sanitize_plain_text(getattr(mime_data, "text", lambda: "")())
    except Exception:
        return SafePasteResult((), False, True, "Clipboard payload could not be read")


# ---------------------------------------------------------------------------
# Note-scoped autosave.  Repository work never runs on the Qt/main thread.
# ---------------------------------------------------------------------------


class NoteSession:
    """Thread-safe owner of one open note and its latest autosave generation."""

    def __init__(
        self,
        *,
        store: NoteStore,
        debounce_seconds: float = AUTOSAVE_SECONDS,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        if store is None:
            raise ValueError("NoteSession requires a NoteStore")
        if not 1.0 <= float(debounce_seconds) <= 2.0:
            raise ValueError("autosave debounce must be between 1 and 2 seconds")
        self._store = store
        self._debounce_seconds = float(debounce_seconds)
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="myelin-note-save"
        )
        self._owns_executor = executor is None
        self._lock = threading.RLock()
        self._document: NoteDocument | None = None
        self._timer: threading.Timer | None = None
        self._future: Future[NoteDocument] | None = None
        self._public_future: Future[bool] | None = None
        self._edit_generation = 0
        self._saved_generation = 0
        self._state = SaveState.SAVED
        self._detail = ""
        self._closing = False
        self._closed = False

    def snapshot(self) -> NoteSessionSnapshot:
        with self._lock:
            return NoteSessionSnapshot(
                self._document,
                self._state,
                self._detail,
                self._edit_generation,
                self._saved_generation,
            )

    def open_document(
        self,
        document: NoteDocument,
        *,
        requires_save: bool = False,
        timeout: float = 2.0,
    ) -> bool:
        """Admit a loaded note or a new unsaved note.

        ``requires_save`` must be true for a newly created document.  Opening
        any document first drains every accepted edit in the current note,
        even when the caller supplies the same note ID again.
        """

        if not isinstance(document, NoteDocument):
            raise TypeError("document must be a NoteDocument")
        with self._lock:
            current_id = self._document.note_id if self._document else ""
            dirty = self._saved_generation != self._edit_generation
        if current_id and dirty and not self.flush(timeout=timeout):
            return False
        with self._lock:
            if self._closed or self._closing:
                return False
            if (
                current_id
                and current_id == document.note_id
                and self._document is not None
            ):
                # Do not let a stale caller copy overwrite the exact document
                # that the drain just committed.
                document = self._document
            self._cancel_timer_locked()
            self._document = document
            self._edit_generation = 1 if requires_save else 0
            self._saved_generation = 0
            self._state = SaveState.UNSAVED if requires_save else SaveState.SAVED
            self._detail = ""
            if requires_save:
                self._schedule_locked()
            return True

    def edit(self, operation: Callable[[NoteDocument], NoteDocument]) -> NoteDocument:
        with self._lock:
            if self._closed or self._closing:
                raise RuntimeError("note session is closing or closed")
            if self._document is None:
                raise RuntimeError("no note is open")
            candidate = operation(self._document)
            if not isinstance(candidate, NoteDocument):
                raise TypeError("note edit must return a NoteDocument")
            if candidate.note_id != self._document.note_id:
                raise NoteValidationError("note edit changed document identity")
            self._document = candidate
            self._edit_generation += 1
            self._state = SaveState.UNSAVED
            self._detail = ""
            self._schedule_locked()
            return candidate

    def flush_async(self) -> Future[bool]:
        with self._lock:
            if self._closed:
                return _completed_future(False)
            self._cancel_timer_locked()
            if self._document is None or self._saved_generation == self._edit_generation:
                return _completed_future(True)
            if self._future is not None:
                assert self._public_future is not None
                return self._public_future
            document = self._document
            generation = self._edit_generation
            self._state = SaveState.SAVING
            public: Future[bool] = Future()
            self._public_future = public
            try:
                worker = self._executor.submit(
                    self._store.save_note,
                    document,
                    expected_revision=document.revision_number,
                )
            except Exception as exc:
                self._public_future = None
                self._state = SaveState.FAILED
                self._detail = _short_error(exc)
                public.set_result(False)
                return public
            self._future = worker
            worker.add_done_callback(
                lambda result: self._finish_save(result, generation, public)
            )
            return public

    def flush(self, *, timeout: float = 2.0) -> bool:
        if timeout <= 0:
            raise ValueError("flush timeout must be positive")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                completed = self.flush_async().result(timeout=remaining)
            except TimeoutError:
                return False
            with self._lock:
                if completed and self._saved_generation == self._edit_generation:
                    return True
                if self._state is SaveState.FAILED:
                    return False

    def shutdown(self, *, timeout: float = 2.0) -> bool:
        with self._lock:
            if self._closed:
                return True
            if self._closing:
                return False
            self._closing = True
        saved = self.flush(timeout=timeout)
        with self._lock:
            if not saved:
                self._closing = False
                return False
            self._closed = True
            self._closing = False
            self._state = SaveState.CLOSED
            self._cancel_timer_locked()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=False)
        return True

    def _schedule_locked(self) -> None:
        self._cancel_timer_locked()
        timer = threading.Timer(self._debounce_seconds, self.flush_async)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _cancel_timer_locked(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()

    def _finish_save(
        self,
        worker: Future[NoteDocument],
        generation: int,
        public: Future[bool],
    ) -> None:
        try:
            saved = worker.result()
            if not isinstance(saved, NoteDocument):
                raise TypeError("NoteStore returned an invalid document")
        except Exception as exc:
            with self._lock:
                self._future = None
                self._public_future = None
                self._state = SaveState.FAILED
                self._detail = _short_error(exc)
            public.set_result(False)
            return
        with self._lock:
            self._future = None
            self._public_future = None
            current = self._document
            if current is None or current.note_id != saved.note_id:
                self._state = SaveState.FAILED
                self._detail = "saved note identity changed unexpectedly"
                public.set_result(False)
                return
            if generation == self._edit_generation:
                self._document = saved
                self._saved_generation = generation
                self._state = SaveState.SAVED
                self._detail = ""
                public.set_result(True)
                return

            # A newer edit arrived during I/O.  Preserve all newer blocks,
            # especially opaque payloads, but advance the optimistic base.
            self._document = replace(
                current,
                revision_number=saved.revision_number,
                created_at_utc=saved.created_at_utc,
            )
            self._saved_generation = generation
            self._state = SaveState.UNSAVED
            self._schedule_locked()
            public.set_result(False)


# ---------------------------------------------------------------------------
# Qt presentation.  The core above remains importable for headless testing.
# Missing PyQt is a clear dependency error, never a mock Notes workspace.
# ---------------------------------------------------------------------------


try:
    from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen, QTextCharFormat, QTextCursor
    from PyQt6.QtWidgets import (
        QDialog,
        QDialogButtonBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as _qt_import_failure:
    _QT_IMPORT_DETAIL = str(_qt_import_failure)

    class NotesWorkspace:  # type: ignore[no-redef]
        """Clear dependency boundary used only when PyQt6 is unavailable."""

        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                f"NotesWorkspace requires PyQt6: {_QT_IMPORT_DETAIL}"
            )

else:
    class SafeNoteTextEdit(QTextEdit):
        """Text-only block editor with one bounded clipboard boundary."""

        spans_changed = pyqtSignal(str, object)
        paste_warning = pyqtSignal(str)

        def __init__(self, block: NoteBlock, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.block_id = block.block_id
            self.setObjectName("studyNoteTextBlock")
            self.setAcceptRichText(False)
            self._loading = True
            self._set_spans(block.content)
            self._loading = False
            self.textChanged.connect(self._emit_plain_change)

        def _set_spans(self, content: BlockContent) -> None:
            assert isinstance(content, tuple)
            cursor = self.textCursor()
            for span in content:
                formatting = QTextCharFormat()
                formatting.setFontWeight(700 if span.bold else 400)
                formatting.setFontItalic(span.italic)
                formatting.setFontUnderline(span.underline)
                cursor.insertText(span.text, formatting)

        def insertFromMimeData(self, source) -> None:  # noqa: N802
            result = sanitize_mime_payload(source)
            if not result.accepted:
                self.paste_warning.emit(result.reason)
                return
            cursor = self.textCursor()
            for span in result.spans:
                formatting = QTextCharFormat()
                formatting.setFontWeight(700 if span.bold else 400)
                formatting.setFontItalic(span.italic)
                formatting.setFontUnderline(span.underline)
                cursor.insertText(span.text, formatting)
            if result.removed_unsafe_content:
                self.paste_warning.emit("Unsafe clipboard content was removed")

        def _emit_plain_change(self) -> None:
            if not self._loading:
                # Keyboard editing is deliberately stored as safe plain text.
                # Structured blocks are separate widgets and cannot enter here.
                self.spans_changed.emit(
                    self.block_id,
                    (TextSpan(self.toPlainText()),),
                )


    class DrawingCanvas(QWidget):
        """Small normalized-stroke canvas; it never rasterizes stored truth."""

        def __init__(self, payload: OpaquePayload, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            data = payload.data()
            self._document_width = int(data.get("width", 900))
            self._document_height = int(data.get("height", 500))
            self._strokes = list(data.get("strokes", []))
            self._current: list[list[float]] = []
            self.setMinimumSize(540, 300)
            self.setMouseTracking(True)

        def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self._current = [self._normalized(event.position())]
                self.update()

        def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
            if self._current and event.buttons() & Qt.MouseButton.LeftButton:
                self._current.append(self._normalized(event.position()))
                self.update()

        def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
            if self._current and event.button() == Qt.MouseButton.LeftButton:
                self._current.append(self._normalized(event.position()))
                self._strokes.append(
                    {
                        "stroke_id": _new_id(),
                        "color": "#dcecff",
                        "width": 2.0,
                        "points": self._current,
                    }
                )
                self._current = []
                self.update()

        def paintEvent(self, event) -> None:  # noqa: N802
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#081727"))
            for stroke in [*self._strokes, {"points": self._current, "color": "#dcecff", "width": 2.0}]:
                points = stroke.get("points", [])
                if len(points) < 2:
                    continue
                painter.setPen(QPen(QColor(str(stroke.get("color", "#dcecff"))), float(stroke.get("width", 2.0))))
                for left, right in zip(points, points[1:]):
                    painter.drawLine(self._pixel(left), self._pixel(right))

        def payload(self) -> OpaquePayload:
            # Resizing the dialog is presentation only; it must not rewrite
            # the drawing's authoritative canvas dimensions.
            return make_drawing_payload(
                self._document_width,
                self._document_height,
                strokes=self._strokes,
            )

        def clear(self) -> None:
            self._strokes.clear()
            self._current.clear()
            self.update()

        def _normalized(self, point: QPointF) -> list[float]:
            return [
                max(0.0, min(1.0, point.x() / max(1, self.width()))),
                max(0.0, min(1.0, point.y() / max(1, self.height()))),
            ]

        def _pixel(self, point: Sequence[float]) -> QPointF:
            return QPointF(float(point[0]) * self.width(), float(point[1]) * self.height())


    class _StructuredDialog(QDialog):
        """Matching editor for exactly one opaque block kind."""

        def __init__(self, kind: BlockKind, payload: OpaquePayload, parent=None) -> None:
            super().__init__(parent)
            self.kind = kind
            self.setWindowTitle(f"Edit {kind.value.title()} Block")
            root = QVBoxLayout(self)
            if kind is BlockKind.FORMULA:
                self.formula = QTextEdit(self)
                self.formula.setPlainText(str(payload.data().get("source", "")))
                root.addWidget(self.formula)
            elif kind is BlockKind.TABLE:
                data = payload.data()
                rows, columns = int(data["rows"]), int(data["columns"])
                self.table = QTableWidget(rows, columns, self)
                cells = data["cells"]
                for row in range(rows):
                    for column in range(columns):
                        self.table.setItem(row, column, QTableWidgetItem(str(cells[row][column])))
                root.addWidget(self.table)
            else:
                self.canvas = DrawingCanvas(payload, self)
                root.addWidget(self.canvas)
                clear_button = QPushButton("CLEAR DRAWING", self)
                clear_button.clicked.connect(self.canvas.clear)
                root.addWidget(clear_button)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
                parent=self,
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            root.addWidget(buttons)

        def payload(self) -> OpaquePayload:
            if self.kind is BlockKind.FORMULA:
                return make_formula_payload(self.formula.toPlainText())
            if self.kind is BlockKind.TABLE:
                cells = tuple(
                    tuple(
                        self.table.item(row, column).text()
                        if self.table.item(row, column) is not None
                        else ""
                        for column in range(self.table.columnCount())
                    )
                    for row in range(self.table.rowCount())
                )
                return make_table_payload(self.table.rowCount(), self.table.columnCount(), cells=cells)
            return self.canvas.payload()


    class _OpaqueBlockCard(QFrame):
        """Presentation card; its label is never note content."""

        edit_requested = pyqtSignal(str, object)
        delete_requested = pyqtSignal(str)

        def __init__(self, block: NoteBlock, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("studyNoteStructuredBlock")
            row = QHBoxLayout(self)
            label = QLabel(f"{block.kind.value} BLOCK", self)
            label.setObjectName("studyNoteStructuredLabel")
            row.addWidget(label, 1)
            edit = QPushButton("EDIT", self)
            edit.clicked.connect(lambda: self.edit_requested.emit(block.block_id, block.kind))
            remove = QPushButton("DELETE", self)
            remove.clicked.connect(lambda: self.delete_requested.emit(block.block_id))
            row.addWidget(edit)
            row.addWidget(remove)


    class NotesWorkspace(QWidget):  # type: ignore[no-redef]
        """Study Notes UI reading one exact ``NoteSessionSnapshot``."""

        leave_requested = pyqtSignal()
        note_open_requested = pyqtSignal(str)

        def __init__(self, *, session: NoteSession, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            if not isinstance(session, NoteSession):
                raise TypeError("NotesWorkspace requires a NoteSession")
            self._session = session
            self._document: NoteDocument | None = None
            self._loading = False
            self.setObjectName("studyNotesWorkspace")

            root = QVBoxLayout(self)
            header = QHBoxLayout()
            back = QPushButton("CONTROL STATION", self)
            back.clicked.connect(self.leave_requested)
            self.title = QLineEdit(self)
            self.title.setPlaceholderText("Note title")
            self.title.editingFinished.connect(self._rename)
            self.save_label = QLabel("SAVED", self)
            save = QPushButton("SAVE NOW", self)
            save.clicked.connect(self._session.flush_async)
            header.addWidget(back)
            header.addWidget(self.title, 1)
            header.addWidget(self.save_label)
            header.addWidget(save)
            root.addLayout(header)

            tools = QHBoxLayout()
            for label, callback in (
                ("TEXT", self._add_text),
                ("TABLE", self._add_table),
                ("FORMULA", self._add_formula),
                ("DRAWING", self._add_drawing),
            ):
                button = QPushButton(label, self)
                button.clicked.connect(callback)
                tools.addWidget(button)
            tools.addStretch(1)
            self.link_label = QLabel("Not linked", self)
            tools.addWidget(self.link_label)
            root.addLayout(tools)

            self.scroll = QScrollArea(self)
            self.scroll.setWidgetResizable(True)
            self.block_host = QWidget(self.scroll)
            self.blocks = QVBoxLayout(self.block_host)
            self.blocks.addStretch(1)
            self.scroll.setWidget(self.block_host)
            root.addWidget(self.scroll, 1)

            self._status_timer = QTimer(self)
            self._status_timer.setInterval(250)
            self._status_timer.timeout.connect(self._refresh_status)
            self._status_timer.start()

        def open_document(
            self,
            document: NoteDocument,
            *,
            requires_save: bool = False,
            timeout: float = 2.0,
        ) -> bool:
            if not self._session.open_document(
                document,
                requires_save=requires_save,
                timeout=timeout,
            ):
                return False
            # Adopt the SESSION's document, never the caller's copy.  When the
            # same note ID is reopened, ``NoteSession.open_document`` keeps the
            # document its drain just committed and discards the caller's --
            # re-adopting the caller here would put a stale copy back on screen
            # and let the next keystroke be computed from it.
            self._document = self._session.snapshot().document
            self._render()
            return True

        def new_note(
            self,
            *,
            title: str = "Untitled Note",
            note_kind: NoteKind = NoteKind.SESSION,
            linked_study_block_id: str = "",
            linked_plan_id: str = "",
            linked_plan_block_id: str = "",
            linked_task: str = "",
        ) -> NoteDocument:
            document = create_note(
                title=title,
                note_kind=note_kind,
                linked_study_block_id=linked_study_block_id,
                linked_plan_id=linked_plan_id,
                linked_plan_block_id=linked_plan_block_id,
                linked_task=linked_task,
            )
            if not self.open_document(document, requires_save=True):
                raise RuntimeError("current note could not be saved before creating a new note")
            return document

        def link_current_study(self, study_block_id: str, task: str = "") -> None:
            self._apply(lambda doc: link_note_to_study(doc, study_block_id=study_block_id, task=task))

        def link_current_plan(self, plan_id: str, plan_block_id: str = "") -> None:
            self._apply(lambda doc: link_note_to_plan(doc, plan_id=plan_id, plan_block_id=plan_block_id))

        def prepare_to_leave(self, *, timeout: float = 2.0) -> bool:
            return self._session.flush(timeout=timeout)

        def shutdown(self, *, timeout: float = 2.0) -> bool:
            self._status_timer.stop()
            return self._session.shutdown(timeout=timeout)

        def _rename(self) -> None:
            if not self._loading and self._document is not None:
                # ``_apply`` handles the validation failure itself and reports
                # it; it does not re-raise, so the restore has to be driven by
                # its result rather than by an except branch that never runs.
                if not self._apply(lambda doc: rename_note(doc, self.title.text())):
                    self.title.setText(self._document.title)

        def _apply(
            self,
            operation: Callable[[NoteDocument], NoteDocument],
            *,
            render: bool = True,
        ) -> bool:
            """Apply one edit.  Returns True only when authority accepted it.

            A REJECTED edit always re-renders, whatever ``render`` says: the
            widget still shows the text the model just refused, so leaving it
            alone would present rejected content as if it had been accepted.
            ``render=False`` is an accepted-keystroke optimisation only -- it
            must never be read as permission to skip reconciliation.
            """

            try:
                self._document = self._session.edit(operation)
            except (NoteValidationError, RuntimeError, TypeError) as exc:
                self._show_error(str(exc))
                self._render()
                return False
            if render:
                self._render()
            return True

        def _add_text(self) -> None:
            self._apply(lambda doc: insert_text_block(doc))

        def _add_table(self) -> None:
            self._apply(lambda doc: insert_table_block(doc))

        def _add_formula(self) -> None:
            self._apply(lambda doc: insert_formula_block(doc, "x = y"))

        def _add_drawing(self) -> None:
            self._apply(lambda doc: insert_drawing_block(doc))

        def _text_changed(self, block_id: str, spans: tuple[TextSpan, ...]) -> None:
            self._apply(lambda doc: replace_text_block(doc, block_id, spans), render=False)

        def _edit_structured(self, block_id: str, kind: BlockKind) -> None:
            if self._document is None:
                return
            block = next((item for item in self._document.blocks if item.block_id == block_id), None)
            if block is None or block.kind is not kind or not isinstance(block.content, OpaquePayload):
                self._show_error("Structured block identity changed; reload the note")
                return
            dialog = _StructuredDialog(kind, block.content, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    payload = dialog.payload()
                except NoteValidationError as exc:
                    self._show_error(str(exc))
                    return
                self._apply(
                    lambda doc: replace_structured_payload(doc, block_id, kind, payload)
                )

        def _delete(self, block_id: str) -> None:
            self._apply(lambda doc: delete_block(doc, block_id))

        def _render(self) -> None:
            if self._document is None:
                return
            self._loading = True
            self.title.setText(self._document.title)
            self.link_label.setText(_link_text(self._document))
            while self.blocks.count() > 1:
                item = self.blocks.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            for block in self._document.blocks:
                if block.kind in {BlockKind.PARAGRAPH, BlockKind.HEADING}:
                    editor = SafeNoteTextEdit(block, self.block_host)
                    editor.spans_changed.connect(self._text_changed)
                    editor.paste_warning.connect(self._show_error)
                    self.blocks.insertWidget(self.blocks.count() - 1, editor)
                elif block.kind in OPAQUE_BLOCK_KINDS:
                    card = _OpaqueBlockCard(block, self.block_host)
                    card.edit_requested.connect(self._edit_structured)
                    card.delete_requested.connect(self._delete)
                    self.blocks.insertWidget(self.blocks.count() - 1, card)
                else:
                    divider = QFrame(self.block_host)
                    divider.setFrameShape(QFrame.Shape.HLine)
                    self.blocks.insertWidget(self.blocks.count() - 1, divider)
            self._loading = False

        def _refresh_status(self) -> None:
            snapshot = self._session.snapshot()
            self.save_label.setText(snapshot.save_state.value)
            self.save_label.setToolTip(snapshot.detail)
            # A completed save may only advance revision metadata.  Keep the
            # user's live widgets untouched; adopt that snapshot in memory.
            if snapshot.document is not None and self._document is not None:
                if snapshot.document.note_id == self._document.note_id:
                    self._document = snapshot.document

        def _show_error(self, message: str) -> None:
            QMessageBox.warning(self, "Study Notes", str(message))


# ---------------------------------------------------------------------------
# Private validation helpers.
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return secrets.token_hex(16)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _utc_text(value: str, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise NoteValidationError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NoteValidationError(f"{name} must contain a timezone")
    return str(value)


def _clean_id(value: object, name: str) -> str:
    clean = str(value).strip()
    if not clean or len(clean) > 200 or any(character.isspace() for character in clean):
        raise NoteValidationError(f"{name} is invalid")
    return clean


def _bounded_text(value: object, name: str, maximum: int) -> str:
    clean = str(value)
    if len(clean) > maximum:
        raise NoteValidationError(f"{name} exceeds its limit")
    return clean


def _exact_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise NoteValidationError(f"{name} must be an integer")
    return value


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    number = _exact_int(value, name)
    if not minimum <= number <= maximum:
        raise NoteValidationError(f"{name} is outside its limit")
    return number


def _bounded_float(value: object, name: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NoteValidationError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise NoteValidationError(f"{name} is outside its limit")
    return number


def _safe_color(value: object) -> str:
    clean = str(value).lower()
    if len(clean) != 7 or clean[0] != "#" or any(c not in "0123456789abcdef" for c in clean[1:]):
        raise NoteValidationError("drawing color must be #RRGGBB")
    return clean


def _validate_spans(value: object) -> tuple[TextSpan, ...]:
    if not isinstance(value, tuple) or not value:
        raise NoteValidationError("text block must contain at least one span")
    if any(not isinstance(span, TextSpan) for span in value):
        raise NoteValidationError("text block contains an invalid span")
    if sum(len(span.text) for span in value) > TEXT_BLOCK_MAX:
        raise NoteValidationError("text block exceeds its limit")
    return value


def _validate_opaque_for_kind(kind: BlockKind, payload: OpaquePayload) -> None:
    data = payload.data()
    # Unknown future schemas remain preserved but cannot be edited here.
    if payload.schema_version != OPAQUE_SCHEMA_VERSION:
        return
    if kind is BlockKind.FORMULA:
        _bounded_text(data.get("source", ""), "formula source", FORMULA_SOURCE_MAX)
        _bounded_int(data.get("syntax_version"), "formula syntax version", 1, 1)
    elif kind is BlockKind.TABLE:
        rows = _bounded_int(data.get("rows"), "table rows", 1, TABLE_ROWS_MAX)
        columns = _bounded_int(data.get("columns"), "table columns", 1, TABLE_COLUMNS_MAX)
        if rows * columns > TABLE_CELLS_MAX:
            raise NoteValidationError("table contains too many cells")
        cells = data.get("cells")
        if not isinstance(cells, list) or len(cells) != rows:
            raise NoteValidationError("table row data is invalid")
        if any(not isinstance(row, list) or len(row) != columns for row in cells):
            raise NoteValidationError("table must remain rectangular")
        for row in cells:
            for cell in row:
                _bounded_text(cell, "table cell", 20_000)
        if type(data.get("header_row")) is not bool:
            raise NoteValidationError("table header flag is invalid")
    elif kind is BlockKind.DRAWING:
        width = _bounded_int(data.get("width"), "drawing width", 1, DRAWING_DIMENSION_MAX)
        height = _bounded_int(data.get("height"), "drawing height", 1, DRAWING_DIMENSION_MAX)
        strokes = data.get("strokes")
        if not isinstance(strokes, list):
            raise NoteValidationError("drawing strokes are invalid")
        # Reuse the creation validator without mutating the stored payload.
        make_drawing_payload(width, height, strokes=strokes)


def _canonical_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _changed(document: NoteDocument, **changes: object) -> NoteDocument:
    return replace(document, updated_at_utc=_now_utc(), **changes)


def _insert_block(document: NoteDocument, block: NoteBlock, after_block_id: str) -> NoteDocument:
    blocks = list(document.blocks)
    if after_block_id:
        index = next((i + 1 for i, item in enumerate(blocks) if item.block_id == after_block_id), -1)
        if index < 0:
            raise NoteValidationError("block insertion anchor was not found")
    else:
        index = len(blocks)
    blocks.insert(index, block)
    return _changed(document, blocks=tuple(blocks))


def _replace_block(
    document: NoteDocument,
    block_id: str,
    operation: Callable[[NoteBlock], NoteBlock],
    *,
    allowed: set[BlockKind],
) -> NoteDocument:
    found = False
    output: list[NoteBlock] = []
    for block in document.blocks:
        if block.block_id != block_id:
            output.append(block)
            continue
        if block.kind not in allowed:
            raise NoteValidationError("block type cannot change during editing")
        candidate = operation(block)
        if candidate.kind is not block.kind or candidate.block_id != block.block_id:
            raise NoteValidationError("block identity changed during editing")
        output.append(candidate)
        found = True
    if not found:
        raise NoteValidationError("block was not found")
    return _changed(document, blocks=tuple(output))


def _span_to_data(span: TextSpan) -> dict[str, object]:
    return {
        "text": span.text,
        "bold": span.bold,
        "italic": span.italic,
        "underline": span.underline,
    }


def _span_from_data(data: object) -> TextSpan:
    if not isinstance(data, dict):
        raise NoteValidationError("text span JSON is invalid")
    for name in ("bold", "italic", "underline"):
        if type(data.get(name)) is not bool:
            raise NoteValidationError(f"text span {name} flag is invalid")
    return TextSpan(
        str(data.get("text", "")),
        data["bold"],
        data["italic"],
        data["underline"],
    )


def _block_to_data(block: NoteBlock) -> dict[str, object]:
    data: dict[str, object] = {
        "block_id": block.block_id,
        "kind": block.kind.value,
        "version": block.version,
    }
    if isinstance(block.content, tuple):
        data["text_spans"] = [_span_to_data(span) for span in block.content]
    elif isinstance(block.content, OpaquePayload):
        data["opaque"] = {
            "schema_version": block.content.schema_version,
            "renderer_version": block.content.renderer_version,
            "payload_json": block.content.payload_json,
            "sha256": block.content.sha256,
        }
    else:
        data["divider"] = True
    return data


def _block_from_data(data: object) -> NoteBlock:
    if not isinstance(data, dict):
        raise NoteValidationError("note block JSON is invalid")
    kind = BlockKind(str(data.get("kind")))
    if kind in {BlockKind.PARAGRAPH, BlockKind.HEADING}:
        raw_spans = data.get("text_spans")
        if not isinstance(raw_spans, list):
            raise NoteValidationError("text block JSON is incomplete")
        content: BlockContent = tuple(_span_from_data(span) for span in raw_spans)
    elif kind in OPAQUE_BLOCK_KINDS:
        raw = data.get("opaque")
        if not isinstance(raw, dict):
            raise NoteValidationError("structured block JSON is incomplete")
        content = OpaquePayload(
            schema_version=_exact_int(raw.get("schema_version"), "opaque schema version"),
            renderer_version=_exact_int(raw.get("renderer_version"), "opaque renderer version"),
            payload_json=str(raw.get("payload_json", "")),
            sha256=str(raw.get("sha256", "")),
        )
    else:
        content = None
    return NoteBlock(
        block_id=str(data.get("block_id", "")),
        kind=kind,
        content=content,
        version=_exact_int(data.get("version"), "block version"),
    )


def _normalize_paste_text(value: str) -> str:
    return value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def _completed_future(value: bool) -> Future[bool]:
    future: Future[bool] = Future()
    future.set_result(value)
    return future


def _short_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:240] or type(exc).__name__


def _link_text(document: NoteDocument) -> str:
    links: list[str] = []
    if document.linked_study_block_id:
        links.append("Study block linked")
    if document.linked_plan_id:
        links.append("Plan linked")
    return " · ".join(links) or "Not linked"


__all__ = [
    "AUTOSAVE_SECONDS",
    "BlockKind",
    "NoteBlock",
    "NoteDocument",
    "NoteKind",
    "NoteSession",
    "NoteSessionSnapshot",
    "NoteStore",
    "NoteSummary",
    "NoteValidationError",
    "NotesWorkspace",
    "OpaquePayload",
    "SafePasteResult",
    "SaveState",
    "TextSpan",
    "create_note",
    "delete_block",
    "document_from_json",
    "document_to_json",
    "insert_drawing_block",
    "insert_formula_block",
    "insert_table_block",
    "insert_text_block",
    "link_note_to_plan",
    "link_note_to_study",
    "make_drawing_payload",
    "make_formula_payload",
    "make_table_payload",
    "rename_note",
    "replace_structured_payload",
    "replace_text_block",
    "sanitize_html",
    "sanitize_mime_payload",
    "sanitize_plain_text",
]
