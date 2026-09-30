"""SECANT report export mechanics only. No runtime, sensing or database access."""
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import os
import tempfile
from xml.sax.saxutils import escape
from .report import SecantReport, text


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: str
    byte_count: int
    format: str


def suggested_filename(at: datetime | None = None, *, format: str = "pdf") -> str:
    if format not in {"pdf", "txt"}:
        raise ValueError("Supported formats: pdf, txt")
    stamp = (at or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"MYELIN_SECANT_Report_{stamp}.{format}"


def _pdf(report: SecantReport) -> bytes:
    # Same generic A4/Paragraph/export separation used elsewhere in MYELIN;
    # import the rendering library lazily, never another organ's report.
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    output = BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(report.title), styles['Title'])]
    for section in report.sections:
        story.append(Paragraph(escape(section.title), styles['Heading2']))
        for line in section.lines:
            story.append(Paragraph(escape(line), styles['BodyText']))
        story.append(Spacer(1, 8))
    SimpleDocTemplate(output, pagesize=A4).build(story)
    return output.getvalue()


def export_report(report: SecantReport, output_path: str | Path, *, overwrite: bool = False) -> ExportResult:
    """Render before touching destination; publish atomically or report failure."""
    temporary = None
    try:
        if not isinstance(report, SecantReport):
            raise TypeError("SecantReport required")
        target = Path(output_path).expanduser().absolute()
        suffix = target.suffix.lower()
        if suffix not in {".pdf", ".txt"}:
            raise ValueError("Output path must end in .pdf or .txt")
        if not target.parent.is_dir():
            raise ValueError("Output directory does not exist")
        data = _pdf(report) if suffix == ".pdf" else text(report).encode('utf-8')
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.secant-export-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            # No overwrite race: hard-link publication fails if target exists.
            os.link(temporary, target)
        return ExportResult(str(target), len(data), suffix[1:])
    except Exception as error:
        raise ExportError(f"SECANT export failed: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
