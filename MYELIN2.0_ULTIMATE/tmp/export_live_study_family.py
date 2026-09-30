"""One read-only live MYELIN projection and local export for Phase-2 verification."""
from datetime import date
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase

from ANALYTICS_SHEET.model import build_report
from ANALYTICS_SHEET.render import build_analytics_sheet_pdf
from CONTROL_STATION.analytics import AnalyticsSheetRequest
from GET_CHART.poster import (
    A3_LANDSCAPE_PX,
    build_poster_model,
    load_official_logo,
    render_poster_image,
    write_poster_pdf,
)
from GET_CHART.read_model import read_poster_chart_data
from GET_CHART.study_family_evidence import read_study_family
from PERSISTENCE.database import database_path
from PERSISTENCE.storage import _read_study_records_for_report, read_control_station_analytics


root = Path(__file__).resolve().parents[1]
pdf_dir = root / "output" / "pdf"
poster_dir = root / "output" / "live_study_family_fix"
pdf_dir.mkdir(parents=True, exist_ok=True)
poster_dir.mkdir(parents=True, exist_ok=True)
report_pdf = pdf_dir / "MYELIN_Analytics_20260915-30_StudyFamily_Corrected.pdf"
poster_pdf = poster_dir / "MYELIN_Poster_Live_StudyFamily_A3.pdf"
poster_jpg = poster_dir / "MYELIN_Poster_Live_StudyFamily_A3.jpg"
preview_png = poster_dir / "MYELIN_Poster_Live_1600x850.png"
for output in (report_pdf, poster_pdf, poster_jpg, preview_png):
    if output.exists():
        raise FileExistsError(output)

database = database_path(create_parent=False)
snapshot = read_control_station_analytics("Asia/Kolkata")
records = _read_study_records_for_report(snapshot)
family = read_study_family(database)
request = AnalyticsSheetRequest(
    date(2026, 9, 15), date(2026, 9, 30),
    True, True, True, True, "Asia/Kolkata", True, True,
)
model = build_report(snapshot, request, study_records=records, study_family=family)
print("REPORT_STATES", model.states)
print("REPORT_COUNTS", {key: len(value) for key, value in model.included.items()})
print("REPORT_COVER", model.cover_items)
if model.states["secant"] != "AVAILABLE" or model.states["cosecant"] != "AVAILABLE":
    raise RuntimeError("Live child evidence is not available")
if len(model.cover_items) != 4:
    raise RuntimeError("Study-family cover hierarchy changed")
result = build_analytics_sheet_pdf(
    snapshot=snapshot, request=request, output_path=report_pdf,
    study_records=records, study_family=family,
)
print("REPORT_PDF", report_pdf, "PAGES", result.page_count if hasattr(result, "page_count") else result)

app = QApplication.instance() or QApplication([])
for font_name in ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoesc.ttf", "arial.ttf"):
    if QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font_name}") < 0:
        raise RuntimeError(f"Poster font unavailable: {font_name}")
poster_data = read_poster_chart_data(database)
poster_model = build_poster_model(poster_data)
logo = load_official_logo()
write_poster_pdf(poster_model, logo, poster_pdf)
image = render_poster_image(poster_model, logo, A3_LANDSCAPE_PX[0],
                            height_px=A3_LANDSCAPE_PX[1], dpi=300)
if not image.save(str(poster_jpg), "JPG", 95):
    raise OSError("Poster JPG export failed")
preview = render_poster_image(poster_model, logo, 1600, height_px=850)
if not preview.save(str(preview_png), "PNG"):
    raise OSError("Poster preview export failed")
print("POSTER_STATES", poster_data.secant.status, poster_data.cosecant.status)
print("POSTER_COUNTS", poster_data.secant.founded_episodes, poster_data.cosecant.break_denominator)
print("POSTER_PDF", poster_pdf)
print("POSTER_JPG", poster_jpg)
print("POSTER_PREVIEW", preview_png)
del app
