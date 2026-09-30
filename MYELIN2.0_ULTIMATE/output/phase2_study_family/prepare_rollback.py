"""Package pre-Phase-2 source copies without altering the active checkout."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ROLLBACK = OUT / "rollback"
originals = (
    "CONTROL_STATION/analytics.py",
    "PERSISTENCE/storage.py",
    "ANALYTICS_SHEET/model.py",
    "ANALYTICS_SHEET/render.py",
    "GET_CHART/read_model.py",
    "GET_CHART/poster.py",
)

report_test = (ROOT / "ANALYTICS_SHEET/test_report.py").read_text(encoding="utf-8")
assert "Report sections \\u00b7 Selected dates only" in report_test
assert "Select at least one report section" in report_test
report_test = report_test.replace("Report sections \\u00b7 Selected dates only",
                                  "Four individual organs \\u00b7 Selected dates only")
report_test = report_test.replace("Select at least one report section", "Select at least one organ")

poster_test = (ROOT / "GET_CHART/test_poster.py").read_text(encoding="utf-8")
assert "Interventions and returns await shared definitions" in poster_test
poster_test = poster_test.replace("Interventions and returns await shared definitions",
                                  "Whole-system metrics awaiting approved definitions")

readme = """Pre-Phase-2 source rollback copies.

Restore the eight files in this archive to the corresponding paths under
MYELIN2.0_ULTIMATE_TRIAL. Then remove the two Phase-2-only source files:
GET_CHART/study_family_evidence.py and ANALYTICS_SHEET/test_phase2_family.py.

This archive does not delete generated PDF, PNG or JPG deliverables.
The original six production files were copied before edits. The two test
files reconstruct only the three Phase-2 assertion wording changes.
"""
archive = OUT / "MYELIN_Phase2_Rollback_Source.zip"
with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
    for name in originals:
        source = ROLLBACK / name.replace("/", "__")
        assert source.is_file(), source
        bundle.write(source, name)
    bundle.writestr("ANALYTICS_SHEET/test_report.py", report_test)
    bundle.writestr("GET_CHART/test_poster.py", poster_test)
    bundle.writestr("ROLLBACK_README.txt", readme)
print(archive)
