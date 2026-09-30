# MYELIN map semantic color pass — acceptance receipt

**MAP COLOR PASS VERDICT: PASS** (1600×850 offscreen visual review with Windows fonts)

**Files modified:** `SECANT/dashboard_view.py`, `SECANT/dashboard_projection.py`, `SECANT/dashboard_demo.py` only. The task-scoped QA and rollback material is in this directory.

**Existing tone pipeline finding:** `FlowPanel` already read each node's tone and drew a matching translucent fill and border. Real SECANT projection supplied generic `cyan` to every event and real COSECANT supplied generic `blue`; demo fixtures had explicit but inconsistent tones. Projection now derives tones from recorded event name, SECANT stage, COSECANT fact kind, and recovered closure reason. The renderer adds yellow/neutral palette entries and a small matching glow only for explicitly opted-in SECANT/COSECANT flows. Study flows retain their previous renderer path.

| Acceptance | Verdict |
| --- | --- |
| SECANT current/recent/overview/episodes/distraction maps | PASS |
| SECANT historical/archive map | PASS |
| COSECANT current map | PASS |
| COSECANT historical maps | PASS: no historical COSECANT FlowPanel exists; break history is a table and was unchanged |
| SECANT-1 blue / SECANT-2 amber / SECANT-3 red | PASS |
| Real return/recovery green | PASS |
| Interruptions/gaps/caution yellow | PASS |
| Founding/break start purple | PASS |
| Ordinary or non-recovered terminal neutral | PASS |
| Study Jump unchanged, including 172 px connectors | PASS: all three target cards and both connectors match baseline metadata; visible map crop is pixel identical |
| Event wording, order, metrics, geometry, connector captions/width, page overflow | PASS: route captures match baseline on all non-tone metadata; demo fixture non-tone fields match backup |
| Database/schema changed | NO: no database access or writes; persistence/schema source hashes unchanged |
| Physiology changed | NO: protected SECANT/COSECANT physiology hashes unchanged |
| 1600×850 UAT | PASS: seven captured routes; readable labels, no new clipping or overflow observed |
| Compile | PASS: three changed modules compiled |
| Phase-3 projection regression | PASS: existing 18-test suite |
| Protected hash check | PASS: all eight protected files match pre-edit SHA-256 |

The Session 202 SECANT visual specimen used the cached presentation payload with only test-local tone slots recomputed by the production semantic mapper; its original factual fields and event order were retained. The Session 202 COSECANT color sequence was also verified by running `prepare_presentation` on the cached raw event snapshot. That Python runtime lacked a named timezone database, so the COSECANT projection check compared the unchanged non-time fields and tones; the cached presentation supplied recorded display times for visual UAT.

**Artifacts:** `before_hashes.csv`, `after_hashes.csv`, `source_backup/`, `baseline_fonts/`, `after_fonts/`, `visual_capture.py`, and `verify_semantics.py` in this directory. The original pre-edit Study Jump capture is also in `baseline/`.

**Source-only rollback:** copy the three files from `source_backup/` back into `SECANT/` under `MYELIN2.0_ULTIMATE_TRIAL`. This restores the exact pre-edit SHA-256 values listed in `before_hashes.csv`. No database rollback is needed.
