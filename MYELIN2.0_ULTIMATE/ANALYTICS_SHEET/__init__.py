"""MYELIN Analytics Sheet: presentation-only A4 report (no database access).

``model``  turns the already-prepared analytics projections into document structures.
``render`` lays those structures out as a paginated A4 PDF with reportlab.
"""

from .model import SECTION_KEYS, build_report

__all__ = ["SECTION_KEYS", "build_report"]
