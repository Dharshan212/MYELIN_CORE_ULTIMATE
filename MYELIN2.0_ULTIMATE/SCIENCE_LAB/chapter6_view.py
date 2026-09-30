"""Chapter 6 -- Conclusion & Future Scope: the closing, research-oriented
page of the Science Lab.

Phase 1 built page structure, hero, the research-style conclusion, the
four-organ pathway summary, the "why recovery matters" concept, the
always-visible scientific boundary, and the closing research question.
Phase 2 replaces the Phase 1 Evidence at a Glance placeholder with a real
six-card dashboard (Best Return, Worst Return, Primary Regulation Domain,
Top Distraction Platform, Top OTT Platform, Top Focus Platform), each gated
by its own certified-evidence audit rather than made to show a value on
demand. The original forensic audit found that all six cards were
architecturally UNAVAILABLE. A later Chief-approved Chapter 3 extension
now certifies only Best/Worst successful behavioral return-onset latency.
This module presents those two transferred values without recalculating
them. The other four cards remain honest static UNAVAILABLE results. The
source is still only the certified Chapter 3 transfer receipt; this module
never reads Chapter 5, an organ, persistence, or raw evidence.

Phase 3 adds two purely explanatory sections below Phase 2's evidence
dashboard: "MYELIN as a Research Tool" (a conceptual experiment flow,
research-use cards, research questions, and a future controlled-study
concept) and "Privacy by Minimum Observation" (what the present
architecture does and does not need to observe, local-first processing,
and research-responsibility norms). Every sentence in both sections is
static presentation copy backed by a read-only forensic audit of
CORE_ENGINE/browser.py, CORE_ENGINE/monitor.py, CORE_ENGINE/blacklist.py,
CORE_ENGINE/resource_intent.py and COSINE/cosine.py (none of those files
were modified, and none of their types are imported here); Phase 3 adds no
new certified-data consumption beyond what Phase 2 already established.

Phase 4 adds a single Future Scope section, "Mi -- MYELIN Intelligence":
a conceptual adaptive-intelligence layer envisioned to sit above SINE,
MINE, COSINE, SECANT and COSECANT, an Ask Mi conversational concept, a local-LLM
architecture concept, and a late-night/rest-aware guidance concept. Every
sentence is static presentation copy, clearly badged FUTURE SCOPE /
CONCEPT / ILLUSTRATIVE FUTURE EXAMPLE / FUTURE BEHAVIORAL GUIDANCE as
appropriate. Phase 4 implements no AI, adds no model, no inference
dependency, no network call, and no new import -- it is a concept
description only, exactly like Phase 3 added no new evidence computation.

Phase 5 closes the scientific content architecture: Platform Direction
(Windows today, a Future Scope-badged macOS/portability note -- no
cross-platform code), Research Basis (five theme cards grounding MYELIN's
research questions in prior literature, plus a compact numbered reference
list using exactly the citation metadata supplied by Chief -- no invented
author, year, DOI or result), Currently Defensible / Not Yet Established
(a plain restatement of what Phases 1-4 already established and did not
establish -- no new capability claim), and a Final Synthesis / Final
Research Position closing the chapter. Every reference is presentation
copy only; none of it is read back by any widget, and no citation is
treated as evidence that MYELIN itself works.

Lifetime Database Refresh wiring (20260915) replaces Chapter 6 -> EVIDENCE's
old Chapter-3-experiment-transfer data source with a manual, read-only MYELIN
LIFETIME SUMMARY: pressing REFRESH emits ``refresh_lifetime_requested``; the
Control Station host reads the durable lifetime database through
``SCIENCE_LAB.chapter6_lifetime.build_lifetime_summary`` (itself read-only,
Qt-free, and the only place in this feature that ever imports PERSISTENCE)
and calls back ``render_lifetime_summary(summary)``. There is no Science Lab
experiment requirement and no Chapter 3 transfer requirement for these
cards any more -- Chapter 3 -> Chapter 5's own transfer is completely
unaffected and unchanged. Every card receives one result on every refresh;
an architecturally-unsupported card renders UNAVAILABLE with a precise
engineering reason from the lifetime service, never a static permanent
placeholder chosen by this view.

Final Four-Card Evidence Completion (20260915) removes PRIMARY REGULATION
DOMAIN and TOP FOCUS PLATFORM entirely (no durable lifetime ledger exists
for either) and wires the two remaining cards to real durable lifetime
evidence: TOP DISTRACTION PLATFORM (the platform_key with the greatest
number of certified durable lifetime SINE admissions) and TOP OTT PLATFORM
(the OTT platform with the greatest cumulative durable supported time
across closed lifetime COSINE history). Both aggregations happen entirely
in ``SCIENCE_LAB.chapter6_lifetime``; this view still only formats and
renders the ``LifetimeMetricResult`` it is handed. EVIDENCE AT A GLANCE is
now exactly four cards: BEST RETURN, WORST RETURN, TOP DISTRACTION
PLATFORM, TOP OTT PLATFORM.


Import boundary (same one-directional composition every Science Lab chapter
module already uses): this module may import PyQt6, UI_THEMES.theme,
SCIENCE_LAB.analysis (only its ``AVAILABLE``/``UNAVAILABLE`` status
constants -- presentation-only comparisons, never a scientific calculation)
and SCIENCE_LAB.chapter6_lifetime (its immutable summary contract only). It
must NOT import CORE_ENGINE, SINE, MINE, COSINE, MIRL, COSECANT_STUDY_MODE,
PERSISTENCE, sqlite3, or SCIENCE_LAB.lab (lab.py hosts this module; this
module never reaches back into lab.py). It also does not import
SCIENCE_LAB.chapter3_view, SCIENCE_LAB.chapter5_view or SCIENCE_LAB.handoff:
Chapter 6's EVIDENCE page no longer consumes a Chapter 3 transfer receipt at
all -- that transfer now reaches only Chapter 5, exactly as it did before,
untouched by this change.
"""

from __future__ import annotations

from typing import Final

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from UI_THEMES.theme import make_font
from .analysis import AVAILABLE, UNAVAILABLE
from .chapter6_lifetime import Chapter6LifetimeSummary


def _allow_shrink(widget: QWidget) -> None:
    """Let a word-wrapped label -- or a card built from several of them --
    shrink below its natural width (same technique every other Science Lab
    chapter module already uses)."""

    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)


def _paragraph(text: str, *, role: str | None = None, size: float = 11.5) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    _allow_shrink(label)
    label.setFont(make_font(size, 400))
    if role:
        label.setProperty("role", role)
    return label


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    _allow_shrink(frame)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)
    return frame, layout


def _section_heading(text: str, *, role: str = "cyan") -> QLabel:
    heading = QLabel(text)
    heading.setProperty("role", role)
    heading.setFont(make_font(12, 700, spacing=1.2))
    return heading


#: The five regulation pathways (Chapter 6 Phase 1 spec).  Presentation
#: copy only -- names and taglines never redefine an organ; the underlying
#: SINE/MINE/COSINE/COSECANT behaviour is documented in Chapter 2 and stays
#: authoritative there.
_PATHWAYS: Final = (
    {
        "key": "SINE",
        "tagline": "Social / distracting digital activity",
        "purpose": "Context-sensitive intervention during distracting social/application use.",
    },
    {
        "key": "MINE",
        "tagline": "Messaging activity",
        "purpose": "A dedicated pathway for persistent messaging-related distraction.",
    },
    {
        "key": "COSINE",
        "tagline": "OTT / streaming activity",
        "purpose": "Streaming check-ins and prolonged entertainment-use regulation.",
    },
    {
        "key": "SECANT",
        "tagline": "Study-resource drift",
        "purpose": "Factual intervention and supported Study-return recovery.",
    },
    {
        "key": "COSECANT",
        "tagline": "Break-return regulation",
        "purpose": "Overdue-break handling and verified study return.",
    },
)

#: The conceptual recovery sequence (Chapter 6 Phase 1 spec).  Clearly
#: labelled BEHAVIORAL REGULATION CONCEPT wherever it is shown -- it is
#: never live participant data.
_RECOVERY_SEQUENCE: Final = (
    "FOCUSED WORK",
    "DIGITAL DRIFT",
    "INTERVENTION",
    "RETURN",
    "VERIFIED RETURN",
    "RELAPSE OR CLOSURE",
)

_RESEARCH_QUESTION: Final = (
    "Can a privacy-preserving, context-sensitive behavioral regulation system "
    "help people recover more effectively from digital distraction across "
    "repeated focused-work sessions?"
)

#: Card identity only -- title text. Each card's live value/status/reason
#: now comes exclusively from a ``Chapter6LifetimeSummary`` (see
#: ``SCIENCE_LAB/chapter6_lifetime.py``) produced by pressing REFRESH; this
#: file computes nothing itself. Before the first REFRESH of the running
#: process, every card renders NOT REFRESHED (see ``_EvidenceCard
#: .render_not_refreshed``).
_EVIDENCE_CARDS: Final = (
    {"key": "best_return", "title": "BEST RETURN"},
    {"key": "worst_return", "title": "WORST RETURN"},
    {"key": "top_distraction_platform", "title": "TOP DISTRACTION PLATFORM"},
    {"key": "top_ott_platform", "title": "TOP OTT PLATFORM"},
)


def _format_latency_ns(value_ns: int) -> str:
    """Format one certified integer nanosecond value without changing it."""

    if type(value_ns) is not int or value_ns < 0:
        raise ValueError("certified latency must be a non-negative integer")
    whole_seconds, fractional_ns = divmod(value_ns, 1_000_000_000)
    minutes, seconds = divmod(whole_seconds, 60)
    seconds_text = str(seconds)
    if fractional_ns:
        seconds_text += f".{fractional_ns:09d}".rstrip("0")
    if minutes:
        return f"{minutes} min {seconds_text} s"
    return f"{seconds_text} s"


#: Phase 3 privacy forensic audit (CORE_ENGINE/browser.py,
#: CORE_ENGINE/monitor.py, CORE_ENGINE/blacklist.py,
#: CORE_ENGINE/resource_intent.py, COSINE/cosine.py -- read-only; none
#: modified, none imported here). Findings that ground every sentence in
#: the Privacy by Minimum Observation section below:
#:
#: OBSERVED -- the present architecture reads: the active process identity
#: (monitor.py's ForegroundObservation.process_name); an OS-level window
#: title (ForegroundObservation.window_title); for supported browsers, a
#: REDUCED host and route classification from the address bar
#: (browser.py's UrlSurfaceEvidence.certified_host / .platform_key /
#: .marker); timestamps (monotonic + UTC); and organ event/stage
#: identifiers (SINE/MINE/COSINE/MIRL/COSECANT).
#:
#: DELIBERATELY REDUCED, NOT RAW -- browser.py's own docstring states its
#: privacy boundary directly: "The raw address never leaves the local
#: reader function ... Query text, fragments, account names and content
#: IDs are never returned or logged here." blacklist.py's own docstring is
#: equally explicit: "A window title never identifies Instagram, YouTube,
#: X, or any other managed platform" -- platform/messaging classification
#: is resolved from the certified host only, never from title-substring
#: matching.
#:
#: WINDOW TITLE IS CAPTURED, NOT CLAIMED ABSENT -- window-title text IS
#: read at the OS level and does reach: live UI telemetry (monitor.py's
#: ``_telemetry`` "title" field -- presentation-only, not classification),
#: COSINE's internal ``content_title`` (a cleaned title used only for a
#: live popup's own display, e.g. a show name), and Resource Intent's
#: ``raw_title`` (captured, but Resource Intent itself is architecturally
#: UNAVAILABLE and never reaches certified Science Lab evidence -- the
#: same finding Phase 2 already established for
#: ``SourceCoverage["RESOURCE_INTENT"]``). SECANT can carry validated,
#: observation-bound display captions into its result package. Captions
#: are presentation metadata, never classification or alias authority.
#: Private message and document bodies are not required as evidence.
#:
#: LOCAL / NETWORK -- a repository-wide search found no network client
#: import (no ``requests``, ``urllib.request``, ``socket``, ``aiohttp``,
#: ``httpx``) and no remote-API reference anywhere in the tree.
#: PERSISTENCE/database.py uses local ``sqlite3`` only. This supports the
#: "local-first, no remote MYELIN server required" claim below -- not a
#: claim that the user's own browsing is offline.
_RESEARCH_USE_CASES: Final = (
    {
        "title": "ATTENTION-RECOVERY EXPERIMENTS",
        "body": "Study behavioral return following digital interruption.",
    },
    {
        "title": "INTERVENTION-RESPONSE STUDIES",
        "body": "Compare what happens following different approved intervention conditions.",
    },
    {
        "title": "DISTRACTION-PATTERN STUDIES",
        "body": "Examine when and under what digital contexts distraction episodes appear.",
    },
    {
        "title": "LONGITUDINAL BEHAVIOR STUDIES",
        "body": (
            "Future repeated-session work could examine whether recovery and "
            "relapse patterns change over time."
        ),
        "badge": "FUTURE RESEARCH",
    },
)

_RESEARCH_QUESTIONS: Final = (
    "When during a focused-work session do distraction episodes emerge?",
    "Which digital contexts are associated with repeated interruption of the declared task?",
    "How long does behavioral return take when an authoritative return measure is available?",
    "How frequently does relapse occur after an apparent or verified return?",
    "Do social, messaging, OTT and overdue-break contexts show different behavioral trajectories?",
    "Does intervention-response behavior change across repeated controlled sessions?",
    (
        "How does MYELIN-assisted regulation compare with no intervention or a "
        "conventional focus condition?"
    ),
)

#: The conceptual experiment flow (Chapter 6 Phase 3 spec).  Not every
#: certified experiment necessarily contains every stage -- see the
#: factual-stage caption rendered beside it.
_EXPERIMENT_FLOW_STEPS: Final = (
    "FOCUSED-WORK CONDITION",
    "SOFTWARE-OBSERVED DIGITAL DRIFT",
    "RELEVANT MYELIN ORGAN",
    "INTERVENTION",
    "CONTINUED ACTIVITY OR RETURN",
    "RETURN EVIDENCE",
    "VERIFIED RETURN",
    "RELAPSE OR EPISODE CLOSURE",
)

#: Candidate outcome measures for a FUTURE controlled study.  Status is
#: drawn directly from the Phase 2 card-authority audit -- "verified
#: returns" and "relapses" are the only two measures in this list that
#: Chapter 3 can already certify (as a count, when MIRL evidence exists);
#: every other candidate has no certified basis today.
_CONTROLLED_STUDY_OUTCOMES: Final = (
    {"label": "Verified returns", "status": "CURRENTLY CERTIFIED (count, when MIRL evidence exists)"},
    {"label": "Relapses", "status": "CURRENTLY CERTIFIED (count, when MIRL evidence exists)"},
    {"label": "Return latency", "status": "FUTURE MEASUREMENT TARGET"},
    {"label": "Task-aligned work duration", "status": "FUTURE MEASUREMENT TARGET"},
    {"label": "Task completion / task accuracy", "status": "FUTURE MEASUREMENT TARGET"},
    {"label": "Uninterrupted work bouts", "status": "FUTURE MEASUREMENT TARGET"},
    {"label": "Distraction episode counts (unified, cross-organ)", "status": "FUTURE MEASUREMENT TARGET"},
)

_RESEARCH_RESPONSIBILITY_POINTS: Final = (
    "INFORMED CONSENT",
    "MINIMUM NECESSARY OBSERVATION",
    "TRANSPARENT DATA USE",
    "SECURE LOCAL STORAGE",
    "CLEAR EXPERIMENT BOUNDARIES",
    "PARTICIPANT CONTROL",
)

#: Phase 4 -- Mi (MYELIN Intelligence) is a Future Scope CONCEPT section
#: only. Nothing below is wired to a model, a network call, or live data;
#: every list is presentation copy describing a possible future
#: architecture, badged accordingly on screen.
_MI_ARCHITECTURE_ORGANS: Final = ("SINE", "MINE", "COSINE", "SECANT", "COSECANT")

_MI_EVIDENCE_AUTHORITY_STEPS: Final = (
    "OBSERVED BEHAVIOR",
    "MYELIN ORGAN / EVIDENCE SYSTEM",
    "CERTIFIED FACTS",
    "Mi",
    "GUIDANCE",
)

_MI_FUTURE_INPUTS: Final = (
    "TIME OF DAY",
    "SESSION DURATION",
    "ORGAN-ACTIVATION HISTORY",
    "RETURN HISTORY",
    "VERIFIED-RETURN HISTORY",
    "RELAPSE HISTORY",
    "INTERVENTION-RESPONSE HISTORY",
    "REPEATED SOCIAL DRIFT",
    "MESSAGING PATTERN",
    "OTT PATTERN",
    "BREAK-OVERRUN PATTERN",
    "USER-DECLARED TASK",
    "USER PREFERENCES",
)

_MI_ADAPTATION_LOOP_STEPS: Final = (
    "OBSERVE",
    "IDENTIFY RECURRING PATTERN",
    "SELECT APPROVED RESPONSE",
    "INTERVENE THROUGH CORRECT ORGAN",
    "OBSERVE RECOVERY",
    "ACCUMULATE LONGITUDINAL EVIDENCE",
    "ADAPT FUTURE GUIDANCE",
)

_MI_POLICY_BOUNDARY_ITEMS: Final = (
    "SINE timing",
    "MINE timing",
    "COSINE timing",
    "COSECANT timing",
    "return-verification rules",
    "intervention stages",
    "scientific metrics",
    "clinical labels",
    "fatigue diagnoses",
    "sleep thresholds",
)

_MI_ILLUSTRATIVE_PATTERNS: Final = (
    {
        "title": "SOCIAL RECOVERY",
        "body": (
            "Repeated sessions may show that an early SINE intervention is "
            "often sufficient for a particular user."
        ),
    },
    {
        "title": "MESSAGING",
        "body": (
            "Messaging episodes may show a different recovery pattern from "
            "social-media episodes."
        ),
    },
    {
        "title": "OTT",
        "body": "COSINE episodes may cluster around particular times or work conditions.",
    },
    {
        "title": "BREAK RETURN",
        "body": (
            "COSECANT history may reveal recurring difficulty returning after "
            "long breaks."
        ),
    },
)

_ASK_MI_EXAMPLE_QUESTIONS: Final = (
    "“What distracted me most today?”",
    "“Why was my recovery slower tonight?”",
    "“How have my returns changed recently?”",
    "“Should I keep working?”",
    "“Help me plan the next two hours.”",
    "“Show my messaging-distraction pattern.”",
)

#: Chief's Phase 4 narrow correction (post-freeze-review): the model must
#: not sit upstream of MYELIN evidence as though it reasons first and then
#: looks for evidence to support that reasoning. Mi's orchestration/policy
#: and the certified evidence it retrieves are established BEFORE the
#: local language model ever runs, and its own output is checked against
#: policy/evidence again before becoming a response -- MYELIN retrieves
#: the facts; the model only helps communicate and reason over the facts
#: it is given, never decides which facts to believe.
_LOCAL_LLM_FLOW_STEPS: Final = (
    "USER QUESTION",
    "ASK Mi",
    "Mi ORCHESTRATION / POLICY",
    "CERTIFIED MYELIN EVIDENCE",
    "LOCAL LANGUAGE MODEL (e.g. Llama)",
    "POLICY / EVIDENCE CHECK",
    "NATURAL-LANGUAGE RESPONSE",
)

_LLM_MAY_ASSIST_WITH: Final = (
    "Natural-language interaction",
    "Explanation",
    "Summarization",
    "Planning",
    "Query interpretation",
)

_LLM_MUST_NOT_DECIDE: Final = (
    "That distraction occurred",
    "That return occurred",
    "That return was verified",
    "That the user is fatigued",
    "That the user medically needs sleep",
    "That the user has an attention disorder",
    "That MYELIN policy should change",
)

_LATE_NIGHT_CONDITIONS: Final = (
    "LATE HOUR",
    "LONG SESSION",
    "REPEATED DIGITAL DRIFT",
    "REPEATED INTERVENTIONS",
    "SLOWER OBSERVED RECOVERY",
)

_USER_CONTROL_OPTIONS: Final = ("CONTINUE", "RETURN TO TASK", "TAKE A BREAK", "END SESSION", "REST")

#: Phase 5 -- Research Basis, Platform Direction, Currently Defensible /
#: Not Yet Established, and Final Synthesis.  Every reference below uses
#: exactly the citation metadata Chief supplied (author, year, journal,
#: DOI) -- nothing here is invented, and none of it is read back by any
#: widget or used as evidence that MYELIN itself is effective.
_RESEARCH_BASIS_THEMES: Final = (
    {
        "title": "ATTENTION OVER TIME",
        "body": (
            "Mind-wandering has been shown to increase in frequency across "
            "time-on-task, supporting the importance of studying when "
            "behavioral drift emerges during sustained work."
        ),
        "ref": "[1]",
    },
    {
        "title": "TASK FOCUS & SWITCHING",
        "body": (
            "Research on cognitive control distinguishes maintaining task "
            "focus from switching between tasks and emphasizes adaptive "
            "regulation of cognitive stability and flexibility."
        ),
        "ref": "[2]",
    },
    {
        "title": "INTERRUPTION & RECOVERY",
        "body": (
            "Interruption research treats post-interruption recovery, "
            "including resumption lag, as an important task-performance "
            "outcome and provides evidence that intervention design can "
            "influence recovery behavior."
        ),
        "ref": "[3]",
    },
    {
        "title": "ADAPTIVE INTERVENTION",
        "body": (
            "Just-in-time adaptive intervention research provides a "
            "scientific framework for adapting support according to "
            "changing individual and contextual information using explicit "
            "decision rules."
        ),
        "ref": "[4]",
    },
    {
        "title": "PRIVACY & DIGITAL BEHAVIOR",
        "body": (
            "Digital behavioral research raises important issues involving "
            "privacy, consent, transparency, security and governance, "
            "supporting MYELIN's minimum-observation and local-first design "
            "goals."
        ),
        "ref": "[5]",
    },
)

_REFERENCES: Final = (
    "[1] Zanesco AP, Denkova E, Jha AP. Mind-wandering increases in frequency "
    "over time during task performance: An individual-participant "
    "meta-analytic review. Psychological Bulletin, 151(2), 217–239, 2025. "
    "DOI: 10.1037/bul0000424",
    "[2] Egner T. Principles of cognitive control over task focus and task "
    "switching. Nature Reviews Psychology, 2, 702–714, 2023. "
    "DOI: 10.1038/s44159-023-00234-4",
    "[3] Guo J, Chen T, Xie Z, Or CKL. Effects of interventions to reduce the "
    "negative consequences of interruptions on task performance: A "
    "systematic review, meta-analysis, and narrative synthesis of "
    "laboratory studies. Applied Ergonomics, 97, 103506, 2021. "
    "DOI: 10.1016/j.apergo.2021.103506",
    "[4] Nahum-Shani I, Smith SN, Spring BJ, Collins LM, Witkiewitz K, Tewari "
    "A, Murphy SA. Just-in-Time Adaptive Interventions (JITAIs) in Mobile "
    "Health: Key Components and Design Principles for Ongoing Health "
    "Behavior Support. Annals of Behavioral Medicine, 52(6), 446–462, "
    "2018. DOI: 10.1007/s12160-016-9830-8",
    "[5] Tomičić A, Malešević A, Čartolovni A. Ethical, "
    "Legal and Social Issues of Digital Phenotyping as a Future Solution for "
    "Present-Day Challenges: A Scoping Review. Science and Engineering "
    "Ethics, 28, Article 1, 2022. DOI: 10.1007/s11948-021-00354-1",
    "[6] Nahum-Shani I, Murphy SA. Just-in-Time Adaptive Interventions: Where "
    "Are We Now and What Is Next? Annual Review of Psychology, 77, 679–703, "
    "2026. DOI: 10.1146/annurev-psych-121024-044244",
    # Added for the four-foundational-frameworks Research Basis extension.
    # JITAI is already covered by [4] above (same Nahum-Shani et al. 2018
    # paper) -- not duplicated.
    "[7] Murre JMJ, Dros J. Replication and Analysis of Ebbinghaus' "
    "Forgetting Curve. PLOS ONE, 10(7), e0120644, 2015. "
    "DOI: 10.1371/journal.pone.0120644",
    "[8] Stevens SS. On the Psychophysical Law. Psychological Review, 64(3), "
    "153–181, 1957. DOI: 10.1037/h0046162",
    "[9] Mark G, González VM, Harris J. No Task Left Behind? Examining the "
    "Nature of Fragmented Work. Proceedings of CHI 2005, 321–330, 2005. "
    "DOI: 10.1145/1054972.1055017",
    "[10] Mark G, Gudith D, Klocke U. The Cost of Interrupted Work: More "
    "Speed and Stress. Proceedings of CHI 2008, 107–110, 2008. "
    "DOI: 10.1145/1357054.1357072",
)

#: Research Basis extension -- four foundational scientific frameworks
#: (Ebbinghaus, JITAI, Weber-Fechner, Gloria Mark), inserted between the
#: existing PLATFORM DIRECTION and RESEARCH BASIS blocks per Chief's
#: supplied research dossier (source-authority PDF: "MYELIN and Four
#: Foundational Frameworks"). Every sentence below is drawn directly from
#: that PDF's page-1/2 executive summary, per-framework sections and its
#: page-18 compact Research Basis wording -- nothing here is invented.
#: The PDF's own repeated caution governs every line: these four bodies of
#: work do not "prove MYELIN"; they supply different layers of scientific
#: context from which MYELIN can generate testable hypotheses, and Mi
#: remains future scope throughout. American "behavioral" spelling is used
#: throughout to match this file's existing spelling convention (the PDF
#: itself uses British "behavioural").
_INTEGRATION_INTRO: Final = (
    "MYELIN does not treat Ebbinghaus, JITAI, Weber–Fechner, and "
    "Gloria Mark's interruption research as interchangeable theories. Each "
    "contributes a different scientific question. Ebbinghaus motivates "
    "investigation of whether behavioral return changes with elapsed time "
    "away from a task. JITAI provides a framework for deciding when, how, "
    "and whether an intervention should be delivered. Weber–Fechner "
    "motivates controlled investigation of intervention salience, while "
    "Gloria Mark's interruption research motivates measurement of "
    "interruption, intervening activity, and task resumption. MYELIN "
    "brings these questions together within one observable behavioral "
    "architecture."
)

_FOUNDATIONS: Final = (
    {
        "name": "EBBINGHAUS",
        "subtitle": "Time-dependent retention",
        "derived_label": "TEMPORAL HYPOTHESIS",
        "derived_question": "Does return difficulty change with time away?",
        "interpretation": (
            "Time and recovery: motivates testing whether behavioral "
            "return changes as time away grows; it does not imply that "
            "memory itself is being measured by MYELIN."
        ),
        "maps_to": "SINE · MINE · COSINE · SECANT · COSECANT → Mi",
    },
    {
        "name": "JITAI",
        "subtitle": "Decision points + tailoring + options + rules",
        "derived_label": "",
        "derived_question": "",
        "interpretation": (
            "Adaptive intervention: provides the strongest formal basis "
            "for future Mi decision points, tailoring variables, "
            "intervention options and evidence-guided decision rules."
        ),
        "maps_to": "All four organs + Mi — strongest theoretical match",
    },
    {
        "name": "WEBER–FECHNER",
        "subtitle": "Perceptual scaling",
        "derived_label": "INTERVENTION",
        "derived_question": "Presentation / salience",
        "interpretation": (
            "Perceptual salience: motivates controlled tests of graded "
            "intervention presentation, but not a claim that focus or "
            "productivity follows a psychophysical logarithmic law."
        ),
        "maps_to": "Shared intervention-presentation layer across all organs",
    },
    {
        "name": "GLORIA MARK",
        "subtitle": "Interruption → intervening work → resumption",
        "derived_label": "",
        "derived_question": "",
        "interpretation": (
            "Interruption and resumption: motivates measuring the "
            "trajectory from drift through intervening activity to "
            "behavioral return. The often-cited 23:15 is an observed mean "
            "same-day resumption interval reported by Mark in a 2006 "
            "interview, not a universal “brain refocus time”; "
            "the peer-reviewed 2005 study reported 25:26 for its observed "
            "sample."
        ),
        "maps_to": "All organs, particularly SINE/MINE; Mi for recovery modeling",
    },
)

_INTEGRATION_CAPTION: Final = (
    "Research mapping between four foundational frameworks and the MYELIN "
    "behavioral architecture. This figure represents scientific "
    "inspiration and testable correspondence rather than evidence that "
    "MYELIN has validated or fully implemented these theories. Mi remains "
    "future scope; present evidence authority remains with MYELIN's "
    "certified behavioral evidence system."
)

_INTEGRATION_SYNTHESIS: Final = (
    "Ebbinghaus asks what elapsed time may change; Gloria Mark asks what "
    "happens between interruption and resumption; JITAI asks when and how "
    "support should be delivered; Weber–Fechner asks how changes in "
    "signal intensity become perceptually meaningful. MYELIN provides a "
    "behavioral research architecture in which these questions can be "
    "investigated within the same observable episode without collapsing "
    "them into one theory."
)

_INTEGRATION_TRANSITION: Final = (
    "The references below provide the scientific context for the major "
    "research questions and conceptual correspondences represented in "
    "this mapping."
)

#: The page-13 systems-flow figure, added as a follow-up to the native-Qt
#: foundation cards above (which stay exactly as they were -- this is an
#: addition, not a replacement). Authored directly as inline SVG rather
#: than a raster image asset: no image file, no filesystem path, no
#: asset-resolution risk (this codebase has a known-fragile history there),
#: and a vector figure scales losslessly at any card width. Every node and
#: connection mirrors the cross-theory table already established above
#: (_FOUNDATIONS) -- Ebbinghaus and Weber-Fechner each produce a derived
#: sub-question box; JITAI and Gloria Mark fan directly into the organ
#: layer; two long bypass curves (from Temporal Hypothesis and from Gloria
#: Mark) reach Mi directly, matching the reference figure's own bypass
#: curves. Mi is explicitly labelled "(FUTURE SCOPE)" inside the figure
#: itself, not only in the surrounding prose. American "behavioral"
#: spelling used throughout, matching this file's convention.
_INTEGRATION_FIGURE_SVG: Final = (
    '<svg viewBox="0 0 1800 900" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial, sans-serif">'
    '<rect x="0" y="0" width="1800" height="900" rx="18" fill="#0a1628" stroke="#1e3a5f" stroke-width="2"/>'
    '<defs>'
    '<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    '<path d="M0,0 L10,5 L0,10 z" fill="#4a7fa8"/>'
    '</marker>'
    '</defs>'
    '<text x="900.0" y="35.6" text-anchor="middle" font-size="16" font-weight="700" fill="#5ec8f0">'
    'SCIENTIFIC FOUNDATIONS → MYELIN ARCHITECTURE</text>'
    '<rect x="40" y="65.0" width="380" height="130" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2"/>'
    '<text x="230.0" y="110.7" text-anchor="middle" font-size="19" font-weight="700" fill="#eaf4ff">'
    'EBBINGHAUS</text>'
    '<text x="230.0" y="136.7" text-anchor="middle" font-size="19" font-weight="700" fill="#eaf4ff">'
    'time-dependent</text>'
    '<text x="230.0" y="162.7" text-anchor="middle" font-size="19" font-weight="700" fill="#eaf4ff">'
    'retention</text>'
    '<rect x="40" y="270.0" width="380" height="130" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2"/>'
    '<text x="230.0" y="315.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'JITAI</text>'
    '<text x="230.0" y="341.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'decision points + tailoring</text>'
    '<text x="230.0" y="367.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    '+ options + rules</text>'
    '<rect x="40" y="490.0" width="380" height="110" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2"/>'
    '<text x="230.0" y="538.6" text-anchor="middle" font-size="19" font-weight="700" fill="#eaf4ff">'
    'WEBER–FECHNER</text>'
    '<text x="230.0" y="564.6" text-anchor="middle" font-size="19" font-weight="700" fill="#eaf4ff">'
    'perceptual scaling</text>'
    '<rect x="40" y="685.0" width="380" height="130" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2"/>'
    '<text x="230.0" y="730.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'GLORIA MARK</text>'
    '<text x="230.0" y="756.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'interruption → intervening</text>'
    '<text x="230.0" y="782.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'work → resumption</text>'
    '<rect x="450" y="65.0" width="330" height="130" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="615.0" y="110.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'TEMPORAL HYPOTHESIS</text>'
    '<text x="615.0" y="136.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'Does return difficulty</text>'
    '<text x="615.0" y="162.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'change with time away?</text>'
    '<line x1="424" y1="130" x2="446" y2="130" stroke="#4a7fa8" stroke-width="2" marker-end="url(#arrow)"/>'
    '<rect x="450" y="490.0" width="330" height="110" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="615.0" y="538.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'INTERVENTION</text>'
    '<text x="615.0" y="564.3" text-anchor="middle" font-size="18" font-weight="700" fill="#eaf4ff">'
    'presentation / salience</text>'
    '<line x1="424" y1="545" x2="446" y2="545" stroke="#4a7fa8" stroke-width="2" marker-end="url(#arrow)"/>'
    '<rect x="830" y="93.0" width="170" height="74" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="915.0" y="137.3" text-anchor="middle" font-size="21" font-weight="700" fill="#eaf4ff">'
    'SINE</text>'
    '<rect x="830" y="298.0" width="170" height="74" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="915.0" y="342.4" text-anchor="middle" font-size="21" font-weight="700" fill="#eaf4ff">'
    'MINE</text>'
    '<rect x="830" y="508.0" width="170" height="74" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="915.0" y="552.4" text-anchor="middle" font-size="21" font-weight="700" fill="#eaf4ff">'
    'COSINE</text>'
    '<rect x="830" y="610.0" width="170" height="74" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="915.0" y="654.4" text-anchor="middle" font-size="21" font-weight="700" fill="#eaf4ff">SECANT</text>'
    '<path d="M784,130 C805,130 805,647 826,647" fill="none" stroke="#4a7fa8" stroke-width="1.6" marker-end="url(#arrow)"/>'
    '<path d="M1004,647 C1042,647 1042,440 1080,440" fill="none" stroke="#4a7fa8" stroke-width="1.6" marker-end="url(#arrow)"/>'
    '<rect x="830" y="713.0" width="170" height="74" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="915.0" y="757.4" text-anchor="middle" font-size="21" font-weight="700" fill="#eaf4ff">'
    'COSECANT</text>'
    '<line x1="881.0" y1="167.0" x2="881.0" y2="298.0" stroke="#4a7fa8" stroke-width="1.6" marker-start="url(#arrow)" marker-end="url(#arrow)" opacity="0.6"/>'
    '<line x1="949.0" y1="167.0" x2="949.0" y2="298.0" stroke="#4a7fa8" stroke-width="1.6" marker-start="url(#arrow)" marker-end="url(#arrow)" opacity="0.6"/>'
    '<line x1="881.0" y1="372.0" x2="881.0" y2="508.0" stroke="#4a7fa8" stroke-width="1.6" marker-start="url(#arrow)" marker-end="url(#arrow)" opacity="0.6"/>'
    '<line x1="949.0" y1="372.0" x2="949.0" y2="508.0" stroke="#4a7fa8" stroke-width="1.6" marker-start="url(#arrow)" marker-end="url(#arrow)" opacity="0.6"/>'
    '<line x1="881.0" y1="582.0" x2="881.0" y2="610.0" stroke="#4a7fa8" stroke-width="1.6" marker-start="url(#arrow)" marker-end="url(#arrow)" opacity="0.6"/>'
    '<line x1="949.0" y1="684.0" x2="949.0" y2="713.0" stroke="#4a7fa8" stroke-width="1.6" marker-start="url(#arrow)" marker-end="url(#arrow)" opacity="0.6"/>'
    '<path d="M424,335 C645.1,335 645.1,130 826,130" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M424,335 C645.1,335 645.1,335 826,335" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M424,335 C645.1,335 645.1,545 826,545" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M424,335 C645.1,335 645.1,750 826,750" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,130 C805.0,130 805.0,130 826,130" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,130 C805.0,130 805.0,335 826,335" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,130 C805.0,130 805.0,545 826,545" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,130 C805.0,130 805.0,750 826,750" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,545 C805.0,545 805.0,130 826,130" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,545 C805.0,545 805.0,335 826,335" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,545 C805.0,545 805.0,545 826,545" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,545 C805.0,545 805.0,750 826,750" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M424,750 C645.1,750 645.1,130 826,130" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M424,750 C645.1,750 645.1,335 826,335" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<rect x="1080" y="360.0" width="250" height="160" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="1205.0" y="433.0" text-anchor="middle" font-size="20" font-weight="700" fill="#eaf4ff">'
    'CERTIFIED</text>'
    '<text x="1205.0" y="461.0" text-anchor="middle" font-size="20" font-weight="700" fill="#eaf4ff">'
    'BEHAVIORAL EVIDENCE</text>'
    '<path d="M1004,130 C1043.6,130 1043.6,440.0 1076,440.0" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M1004,335 C1043.6,335 1043.6,440.0 1076,440.0" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M1004,545 C1043.6,545 1043.6,440.0 1076,440.0" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M1004,750 C1043.6,750 1043.6,440.0 1076,440.0" fill="none" stroke="#4a7fa8" stroke-width="1.6" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M784,100 C1250.5,100 1250.5,393.0 1406,393.0" fill="none" stroke="#4a7fa8" stroke-width="1.4" opacity="0.75" marker-end="url(#arrow)"/>'
    '<path d="M424,770 C1160.5,770 1160.5,487.0 1406,487.0" fill="none" stroke="#4a7fa8" stroke-width="1.4" opacity="0.75" marker-end="url(#arrow)"/>'
    '<rect x="1410" y="375.0" width="110" height="130" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.6"/>'
    '<text x="1465.0" y="432.4" text-anchor="middle" font-size="24" font-weight="700" fill="#eaf4ff">'
    'Mi</text>'
    '<text x="1465.0" y="458.0" text-anchor="middle" font-size="11.5" font-weight="700" fill="#5ec8f0">'
    '(FUTURE</text>'
    '<text x="1465.0" y="474.0" text-anchor="middle" font-size="11.5" font-weight="700" fill="#5ec8f0">'
    'SCOPE)</text>'
    '<line x1="1334" y1="440.0" x2="1406" y2="440.0" stroke="#4a7fa8" stroke-width="2" marker-end="url(#arrow)"/>'
    '<rect x="1600" y="385.0" width="130" height="110" rx="10" fill="#0f2744" stroke="#5ec8f0" stroke-width="2.4"/>'
    '<text x="1665.0" y="421.9" text-anchor="middle" font-size="17" font-weight="700" fill="#eaf4ff">'
    'POLICY-</text>'
    '<text x="1665.0" y="445.9" text-anchor="middle" font-size="17" font-weight="700" fill="#eaf4ff">'
    'CONSTRAINED</text>'
    '<text x="1665.0" y="469.9" text-anchor="middle" font-size="17" font-weight="700" fill="#eaf4ff">'
    'GUIDANCE</text>'
    '<line x1="1524" y1="440.0" x2="1596" y2="440.0" stroke="#4a7fa8" stroke-width="2" marker-end="url(#arrow)"/>'
    '</svg>'
)

_INTEGRATION_FIGURE_CAPTION_V2: Final = (
    "Figure — Scientific foundations mapped into MYELIN architecture. "
    "This figure summarizes how Ebbinghaus, JITAI, Weber–Fechner, and "
    "Gloria Mark's interruption work relate to MYELIN's behavioral organs, "
    "certified evidence pipeline, and future Mi guidance layer."
)

_CURRENTLY_DEFENSIBLE_ITEMS: Final = (
    "MYELIN can observe software-visible behavioral context.",
    "MYELIN can deliver distinct regulation pathways through SINE, MINE, COSINE, SECANT and COSECANT.",
    "MYELIN can preserve certified event evidence for supported sources.",
    "MYELIN can distinguish return-related events where the underlying organ evidence supports them.",
    "MYELIN's Science Lab can preserve UNAVAILABLE as UNAVAILABLE rather than inventing a result.",
    "The present core workflow is local-first.",
)

_NOT_YET_ESTABLISHED_ITEMS: Final = (
    "MYELIN has not yet been shown in controlled human studies to improve focus.",
    "MYELIN has not yet been shown to improve productivity.",
    "MYELIN does not directly measure brain activity.",
    "MYELIN does not currently have a certified complete task-aligned work-duration measure.",
    "Mi does not yet exist as a running intelligence system.",
    "The current prototype does not yet establish longitudinal improvement across users or sessions.",
)


def _badge(text: str) -> QLabel:
    """A small pill-shaped 'not a certified value' marker -- reuses the
    same theme-tested chip style the Phase 1 Coming Soon pages and the
    Phase 2 evidence placeholder already used."""

    badge = QLabel(text)
    badge.setObjectName("comingSoonPageBadge")
    badge.setFont(make_font(8, 700, spacing=0.7))
    return badge


def _vertical_flow(tag: str, steps: tuple[str, ...], *, max_width: int | None = None) -> QFrame:
    """A labelled, centered, top-to-bottom step sequence -- the same
    technique the Phase 1 'Why Recovery Matters' concept box already uses,
    factored out here since Phase 3 needs it twice more. Never implies
    live/certified data; the caller supplies the tag that says so.

    Phase 6 root-cause fix: every wrapped step label now calls
    ``_allow_shrink`` -- without it, a word-wrapped QLabel's minimum size
    hint does not shrink to its wrapped width, so the ancestor
    heightForWidth chain that ``_TopicStack``/``_sync_stack_height`` relies
    on under-reserved vertical space for any step whose text wrapped to
    more lines than its unconstrained sizeHint assumed, silently clipping
    the last line (confirmed by the exact reported defects: "SOFTWARE-
    OBSERVED DIGITAL" losing "DRIFT", "CONTINUED ACTIVITY OR" losing
    "RETURN", "MYELIN ORGAN /" losing "EVIDENCE SYSTEM" -- all three are
    ``_vertical_flow`` steps). This is the single shared helper behind the
    Research Use Example, Mi Evidence Authority, Evidence-Guided Adaptation
    and Local LLM Concept flows, so the one fix repairs all four.

    ``max_width`` caps the box so a short-step flow does not stretch edge
    to edge on a very wide card (the Phase 5/6 audit's "diagram whitespace"
    finding); the caller centers the returned frame. Leave it unset for a
    flow meant to fill its column, such as the Privacy pipelines."""

    frame = QFrame()
    frame.setObjectName("statBox")
    _allow_shrink(frame)
    if max_width is not None:
        frame.setMaximumWidth(max_width)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(7)
    # Deliberately NOT layout.setAlignment(AlignHCenter) -- this was the
    # actual native-rendering root cause (found only after a Chief-provided
    # screenshot proved geometry testing alone had missed it): an alignment
    # set on the LAYOUT ITSELF sizes every child at its own unconstrained
    # sizeHint() (single-line width) and centers that, rather than
    # stretching each child to the frame's real width -- so a step label
    # never actually receives enough width to trigger correct wrapping,
    # and heightForWidth is computed against the wrong (too-narrow)
    # number. Each step label below centers its own TEXT via
    # setAlignment(AlignHCenter) instead, which only affects text
    # rendering within the label's rect, not how wide the layout makes it.

    tag_label = QLabel(tag)
    tag_label.setProperty("role", "cyan")
    tag_label.setFont(make_font(8.5, 700, spacing=0.8))
    tag_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(tag_label)

    for index, step in enumerate(steps):
        if index:
            arrow = QLabel("↓")
            arrow.setProperty("role", "muted")
            arrow.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(arrow)
        step_label = QLabel(step)
        step_label.setWordWrap(True)
        _allow_shrink(step_label)
        step_label.setFont(make_font(10.5, 700, spacing=0.3))
        step_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(step_label)

    return frame


class _CenteredCapFrame(QWidget):
    """Centers ``widget`` at up to ``max_width``, driving its width
    directly from this wrapper's own ``resizeEvent``/``heightForWidth``
    instead of from ``widget.sizeHint()`` (Phase 6 native-rendering fix --
    this replaced two earlier, both-wrong attempts at the same problem,
    each only caught by a native Windows screenshot, not by this
    sandbox's offscreen tests):

    Attempt 1 was ``layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)``.
    Attempt 2 replaced it with an HBoxLayout + two ``addStretch(1)``. Both
    failed for the identical underlying reason: every widget these boxes
    center (``_vertical_flow`` frames, the Mi Architecture diagram, the
    late-night concept box) is built from ``_allow_shrink`` children --
    an ``Ignored`` horizontal size policy, which is correct for a widget
    meant to stretch and fill whatever width an ordinary layout gives it,
    but tells Qt "I have no width preference" when the CONTAINER's own
    preferred width is asked for. With every child Ignored, the
    container's aggregate ``sizeHint().width()`` collapses to near zero,
    and neither alignment-based centering nor stretch-based centering can
    recover from that -- both ultimately ask the widget for a sizeHint
    that was never meaningful to begin with (confirmed by direct geometry
    inspection both times: a zero-width frame, or a ~40px frame with
    every label squashed into single-character-wide, many-line wrapping).

    Driving ``widget.setFixedWidth(...)`` from this wrapper's own
    resizeEvent sidesteps the whole sizeHint negotiation: a fixed width is
    a hard constraint Qt always honors regardless of what the widget's own
    children report, and once the widget's width is genuinely fixed for a
    layout pass, its internal QVBoxLayout correctly distributes height to
    its Ignored/wrapped children (Ignored only causes trouble for WIDTH
    negotiation, not for laying out children at an already-known width)."""

    def __init__(self, widget: QWidget, max_width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widget = widget
        self._max_width = max_width
        # Phase 6 native-rendering finding (found only via a direct
        # geometry probe after Chief reported every centered diagram
        # rendering pinned to the right edge with a large empty gap on the
        # left): every widget this wrapper centers was built with
        # ``_allow_shrink`` -- QSizePolicy.Ignored -- so it can shrink
        # below its natural width in the ORDINARY (uncentered) layouts it
        # is also used in. But QSizePolicy.Ignored does more than permit
        # shrinking: Qt's QBoxLayout treats an Ignored item as wanting to
        # *expand*, which skews how the two addStretch(1) spacers below
        # split the leftover space around it -- confirmed by direct
        # geometry measurement (a 560px-wide child in a 1850px frame
        # measured left_gap=925/right_gap=365 with Ignored, vs a correct
        # 623/623 once the policy below is applied). This wrapper already
        # drives the child's width with a hard ``setFixedWidth`` in
        # ``_apply_width``, so the child never actually needs Ignored's
        # shrink permission here -- only Preferred is needed for the
        # QBoxLayout stretch math to split the two spacers evenly.
        policy = widget.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        widget.setSizePolicy(policy)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(widget)
        row.addStretch(1)

    def _apply_width(self, width: int) -> int:
        target = max(1, min(self._max_width, width))
        self._widget.setFixedWidth(target)
        return target

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        self._apply_width(event.size().width())

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        target = self._apply_width(width)
        if self._widget.hasHeightForWidth():
            return self._widget.heightForWidth(target)
        return self._widget.sizeHint().height()

    def sizeHint(self):  # noqa: N802 -- Qt override
        return self._widget.sizeHint()


def _add_centered(layout: QVBoxLayout, widget: QWidget, max_width: int) -> None:
    """Add ``widget`` to ``layout``, centered at up to ``max_width`` wide.
    See ``_CenteredCapFrame`` for why this needs to be more than a plain
    alignment flag."""

    layout.addWidget(_CenteredCapFrame(widget, max_width))


class _SvgFigureWidget(QWidget):
    """Renders a fixed SVG figure (vector, not a raster asset -- no image
    file, no filesystem path, no asset-resolution risk) scaled to this
    widget's own width with its intrinsic aspect ratio preserved exactly.

    Deliberately never uses ``QSvgWidget`` (which stretches to fill its
    rect without preserving aspect ratio by default): instead this widget
    reports its own correct ``heightForWidth`` from the SVG's known
    intrinsic aspect ratio and renders through ``QSvgRenderer`` directly in
    ``paintEvent``, so its height is always exactly right for its width --
    the same hard-constraint approach ``_CenteredCapFrame`` already uses
    for centering, applied here to aspect ratio instead of to width."""

    def __init__(self, svg_source: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = QSvgRenderer(QByteArray(svg_source.encode("utf-8")), self)
        default_size = self._renderer.defaultSize()
        self._aspect_ratio = (
            default_size.height() / default_size.width() if default_size.width() > 0 else 0.5
        )
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        return max(1, round(width * self._aspect_ratio))

    def sizeHint(self):  # noqa: N802 -- Qt override
        width = max(self.width(), 300)
        return QSize(width, self.heightForWidth(width))

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(painter, QRectF(0, 0, self.width(), self.height()))
        painter.end()


def _reflow_grid_height_for_width(
    grid: QGridLayout, items: list[QWidget], columns: int, width: int
) -> int:
    """Manually compute the height a QGridLayout of ``items`` arranged into
    ``columns`` equal-width columns needs at ``width``.

    Phase 6 native-rendering finding: ``QGridLayout.heightForWidth()`` is a
    known Qt weak spot for nested word-wrapped content -- geometry testing
    confirmed it under-reported height for a ``_vertical_flow`` frame (and
    for a research-basis theme card) nested inside a grid cell, clipping
    their last line, even after each grid was fixed to relayout to the
    correct column count before answering. Computing row heights directly
    from each cell's own ``heightForWidth`` removes the dependency on
    QGridLayout's own (unreliable) implementation entirely. Every reflow
    grid in this chapter uses equal, unstretched columns (no column
    stretch factor is ever set), so dividing width equally matches what
    QGridLayout actually renders."""

    if not items or columns <= 0:
        return 0
    h_spacing = grid.horizontalSpacing()
    v_spacing = grid.verticalSpacing()
    margins = grid.contentsMargins()
    available = width - margins.left() - margins.right() - h_spacing * (columns - 1)
    col_width = max(1, available // columns)
    rows = (len(items) + columns - 1) // columns
    row_heights = [0] * rows
    for index, item in enumerate(items):
        row = index // columns
        height = item.heightForWidth(col_width) if item.hasHeightForWidth() else -1
        if height < 0:
            height = item.sizeHint().height()
        row_heights[row] = max(row_heights[row], height)
    total = sum(row_heights) + v_spacing * max(0, rows - 1)
    return total + margins.top() + margins.bottom()


def _apply_reflow_min_heights(
    grid: QGridLayout, items: list[QWidget], columns: int, width: int
) -> None:
    """Force every cell's true wrapped-content height as an explicit
    ``setMinimumHeight`` floor.

    This is the paint-time half of the same Phase 6 finding
    ``_reflow_grid_height_for_width`` fixes for the *reported* height:
    even after a grid frame correctly reports a taller ``heightForWidth``
    to its ancestors, QGridLayout's own internal row-height distribution
    can still under-allocate a specific row at actual layout time (the
    same unreliable-with-wrapped-content behavior). ``setMinimumHeight``
    is a hard floor QGridLayout must respect regardless of its own
    height-computation quality, so this closes the gap between "the grid
    reports the right total height" and "each cell actually receives
    enough of it." Safe to call repeatedly -- it always overwrites the
    previous floor, so a widened column (needing less height) shrinks the
    floor back down instead of leaving stale dead space."""

    if not items or columns <= 0:
        return
    h_spacing = grid.horizontalSpacing()
    margins = grid.contentsMargins()
    available = width - margins.left() - margins.right() - h_spacing * (columns - 1)
    col_width = max(1, available // columns)
    for item in items:
        needed = item.heightForWidth(col_width) if item.hasHeightForWidth() else -1
        item.setMinimumHeight(max(needed, 0))


class _LabelReflowGrid(QFrame):
    """Reflow grid for a flat list of already-built label widgets (as
    opposed to ``_UseCaseGrid``'s cards) -- same technique, kept local
    since it is a distinct widget shape.  Column counts are configurable
    per caller so a short-item list (e.g. the 13 Future Mi Inputs) can use
    more columns at a given width than a long-item list would."""

    def __init__(
        self,
        items: list[QWidget],
        *,
        wide_columns: int,
        medium_columns: int,
        narrow_columns: int,
        wide_min_width: int = 760,
        medium_min_width: int = 460,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter6LabelReflowGrid")
        self._items = items
        self._wide_columns = wide_columns
        self._medium_columns = medium_columns
        self._narrow_columns = narrow_columns
        self._wide_min_width = wide_min_width
        self._medium_min_width = medium_min_width
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(7)
        self._current_columns = -1
        self._relayout(wide_columns)

    def _relayout(self, columns: int) -> None:
        if columns == self._current_columns:
            return
        self._current_columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, item in enumerate(self._items):
            row, col = divmod(index, columns)
            self._grid.addWidget(item, row, col)

    def _columns_for_width(self, width: int) -> int:
        if width >= self._wide_min_width:
            return self._wide_columns
        elif width >= self._medium_min_width:
            return self._medium_columns
        return self._narrow_columns

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        width = event.size().width()
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        # Phase 6 native-rendering fix: querying heightForWidth(w) for a
        # width this grid has not actually been resized to yet previously
        # answered using whatever column count it happened to be in
        # (typically its construction-time default), which disagreed with
        # the column count resizeEvent would actually use at that width --
        # the ancestor heightForWidth chain then reserved too little
        # vertical space, and real content painted at the (correct, taller)
        # column count read as clipped. Relaying out to the width's real
        # column count before answering makes the two paths structurally
        # identical, so they cannot diverge again.
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)
        return _reflow_grid_height_for_width(self._grid, self._items, columns, width)

    def sizeHint(self):  # noqa: N802 -- Qt override
        return self._grid.sizeHint()


class _UseCaseCard(QFrame):
    """One scientist-use-case card.  All four use identical layout, same
    reason the four pathway cards do -- no card visually outranks another.
    Phase 6: padding trimmed from (16,14,16,14) -- a card holding one title
    line and one short sentence does not need the same padding as a
    multi-paragraph card, and the grid still equalizes each row to its
    tallest cell either way."""

    def __init__(self, title: str, body: str, *, badge: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setWordWrap(True)
        _allow_shrink(title_label)
        title_label.setFont(make_font(10.5, 700, spacing=0.3))
        layout.addWidget(title_label)

        layout.addWidget(_paragraph(body, role="muted", size=10))

        if badge:
            row = QHBoxLayout()
            row.addWidget(_badge(badge))
            row.addStretch(1)
            layout.addLayout(row)


class _UseCaseGrid(QFrame):
    """Reflow grid for the four research-use-case cards: same technique,
    kept as its own local copy rather than reopening the frozen Phase 1/2
    grid classes (_PathwayGrid, _EvidenceGrid)."""

    def __init__(self, items: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter6UseCaseGrid")
        self._items = items
        self._wide_columns = 4
        self._medium_columns = 2
        self._narrow_columns = 1
        self._wide_min_width = 900
        self._medium_min_width = 560
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._current_columns = -1
        self._relayout(4)

    def _relayout(self, columns: int) -> None:
        if columns == self._current_columns:
            return
        self._current_columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, item in enumerate(self._items):
            row, col = divmod(index, columns)
            self._grid.addWidget(item, row, col)

    def _columns_for_width(self, width: int) -> int:
        if width >= self._wide_min_width:
            return self._wide_columns
        elif width >= self._medium_min_width:
            return self._medium_columns
        return self._narrow_columns

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        width = event.size().width()
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        # Same Phase 6 native-rendering fix as _LabelReflowGrid: relayout
        # to the width's real column count before answering, so a stale
        # (construction-time) column count can never under-report height.
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)
        return _reflow_grid_height_for_width(self._grid, self._items, columns, width)

    def sizeHint(self):  # noqa: N802 -- Qt override
        return self._grid.sizeHint()


def _build_foundation_card(entry: dict) -> QFrame:
    """One of the four scientific-foundation cards in the Research Basis
    integration figure (Ebbinghaus / JITAI / Weber-Fechner / Gloria Mark).
    Same card technique as ``_UseCaseCard`` -- kept as its own function
    since this card additionally carries an optional nested derived-question
    box (only Ebbinghaus and Weber-Fechner have one, matching the supplied
    reference figure) and a small organ-mapping caption line."""

    card = QFrame()
    card.setObjectName("card")
    _allow_shrink(card)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(6)

    name_label = QLabel(entry["name"])
    name_label.setProperty("role", "cyan")
    name_label.setWordWrap(True)
    _allow_shrink(name_label)
    name_label.setFont(make_font(11, 800, spacing=0.4))
    layout.addWidget(name_label)

    subtitle_label = _paragraph(entry["subtitle"], role="muted", size=9.5)
    layout.addWidget(subtitle_label)

    if entry["derived_label"]:
        derived = QFrame()
        derived.setObjectName("statBox")
        _allow_shrink(derived)
        derived_layout = QVBoxLayout(derived)
        derived_layout.setContentsMargins(10, 8, 10, 8)
        derived_layout.setSpacing(3)
        derived_tag = QLabel(entry["derived_label"])
        derived_tag.setProperty("role", "cyan")
        derived_tag.setWordWrap(True)
        _allow_shrink(derived_tag)
        derived_tag.setFont(make_font(8.5, 700, spacing=0.6))
        derived_layout.addWidget(derived_tag)
        derived_question = QLabel(entry["derived_question"])
        derived_question.setWordWrap(True)
        _allow_shrink(derived_question)
        derived_question.setFont(make_font(9.5, 700))
        derived_layout.addWidget(derived_question)
        layout.addWidget(derived)

    layout.addWidget(_paragraph(entry["interpretation"], role="muted", size=9.5))

    maps_to_label = QLabel(f"→ {entry['maps_to']}")
    maps_to_label.setWordWrap(True)
    _allow_shrink(maps_to_label)
    maps_to_label.setProperty("role", "muted")
    maps_to_label.setFont(make_font(8.5, 700, spacing=0.2))
    layout.addWidget(maps_to_label)

    return card


class _PathwayCard(QFrame):
    """One of the four regulation-pathway cards.  All four use identical
    layout and typography so none of them visually outranks another --
    they are different functional pathways, not a primary organ and three
    secondary ones."""

    def __init__(self, key: str, tagline: str, purpose: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAccessibleName(f"{key} regulation pathway")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        name = QLabel(key)
        name.setProperty("role", "cyan")
        name.setFont(make_font(15, 800, spacing=0.6))
        layout.addWidget(name)

        tagline_label = _paragraph(tagline, role="muted", size=10.5)
        layout.addWidget(tagline_label)

        purpose_caption = QLabel("PURPOSE")
        purpose_caption.setFont(make_font(8.5, 700, spacing=0.8))
        purpose_caption.setProperty("role", "muted")
        layout.addWidget(purpose_caption)

        layout.addWidget(_paragraph(purpose, size=10.5))


class _PathwayGrid(QFrame):
    """Reflow grid for the four pathway cards: four columns above
    ``wide_min_width``, two above ``medium_min_width``, one below it (same
    reflow technique every other Science Lab chapter grid already uses --
    kept as a local copy here rather than a cross-chapter import)."""

    def __init__(self, items: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter6PathwayGrid")
        self._items = items
        self._wide_columns = 4
        self._medium_columns = 2
        self._narrow_columns = 1
        self._wide_min_width = 980
        self._medium_min_width = 560
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._current_columns = -1
        self._relayout(4)

    def _relayout(self, columns: int) -> None:
        if columns == self._current_columns:
            return
        self._current_columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, item in enumerate(self._items):
            row, col = divmod(index, columns)
            self._grid.addWidget(item, row, col)

    def _columns_for_width(self, width: int) -> int:
        if width >= self._wide_min_width:
            return self._wide_columns
        elif width >= self._medium_min_width:
            return self._medium_columns
        return self._narrow_columns

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        width = event.size().width()
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        # Same Phase 6 native-rendering fix as _LabelReflowGrid: relayout
        # to the width's real column count before answering, so a stale
        # (construction-time) column count can never under-report height.
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)
        return _reflow_grid_height_for_width(self._grid, self._items, columns, width)

    def sizeHint(self):  # noqa: N802 -- Qt override
        return self._grid.sizeHint()


class _EvidenceCard(QFrame):
    """One fixed-layout card whose labels may present certified state."""

    def __init__(self, title: str, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAccessibleName(f"{title} evidence card")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setWordWrap(True)
        _allow_shrink(title_label)
        title_label.setFont(make_font(11.5, 700))
        layout.addWidget(title_label)

        self._value_label = QLabel()
        self._value_label.setProperty("role", "muted")
        self._value_label.setWordWrap(True)
        _allow_shrink(self._value_label)
        self._value_label.setFont(make_font(14, 800, spacing=0.4))
        layout.addWidget(self._value_label)

        self._chip = QLabel()
        self._chip.setProperty("role", "muted")
        self._chip.setWordWrap(True)
        _allow_shrink(self._chip)
        self._chip.setFont(make_font(8, 700, spacing=0.8))
        layout.addWidget(self._chip)

        self._reason = _paragraph("", role="muted", size=10.5)
        layout.addWidget(self._reason)
        self.render_not_refreshed()

    def _set_state(self, value: str, status: str, reason: str, role: str) -> None:
        self._value_label.setText(value)
        self._chip.setText(status)
        self._reason.setText(reason)
        for label in (self._value_label, self._chip):
            label.setProperty("role", role)
            label.style().unpolish(label)
            label.style().polish(label)

    def render_not_refreshed(self) -> None:
        """Initial/pre-refresh state -- no Chapter 3 transfer is expected any
        more, so this deliberately never says AWAITING TRANSFER."""

        self._set_state(
            "NOT REFRESHED",
            "NOT REFRESHED",
            "Press REFRESH to read the current MYELIN lifetime database summary.",
            "muted",
        )

    def render_unavailable(self, reason: str) -> None:
        self._set_state("UNAVAILABLE", "UNAVAILABLE", reason, "muted")

    def render_available(self, value: str, *, reason: str) -> None:
        self._set_state(value, "AVAILABLE", reason, "green")

    def presentation_state(self) -> tuple[str, str, str]:
        """Return rendered text for isolated presentation-contract tests."""

        return self._value_label.text(), self._chip.text(), self._reason.text()


class _EvidenceGrid(QFrame):
    """Reflow grid for the four evidence cards: two columns above
    ``wide_min_width`` (a natural 2x2 at desktop width), still two above
    ``medium_min_width``, one below it (same reflow technique every other
    Science Lab chapter grid already uses -- kept as a local copy here
    rather than a cross-chapter import)."""

    def __init__(self, items: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter6EvidenceGrid")
        self._items = items
        self._wide_columns = 2
        self._medium_columns = 2
        self._narrow_columns = 1
        self._wide_min_width = 900
        self._medium_min_width = 600
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._current_columns = -1
        self._relayout(3)

    def _relayout(self, columns: int) -> None:
        if columns == self._current_columns:
            return
        self._current_columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, item in enumerate(self._items):
            row, col = divmod(index, columns)
            self._grid.addWidget(item, row, col)

    def _columns_for_width(self, width: int) -> int:
        if width >= self._wide_min_width:
            return self._wide_columns
        elif width >= self._medium_min_width:
            return self._medium_columns
        return self._narrow_columns

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        width = event.size().width()
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        # Same Phase 6 native-rendering fix as _LabelReflowGrid: relayout
        # to the width's real column count before answering, so a stale
        # (construction-time) column count can never under-report height.
        columns = self._columns_for_width(width)
        self._relayout(columns)
        _apply_reflow_min_heights(self._grid, self._items, columns, width)
        return _reflow_grid_height_for_width(self._grid, self._items, columns, width)

    def sizeHint(self):  # noqa: N802 -- Qt override
        return self._grid.sizeHint()


class _EvidenceProvenanceStrip(QFrame):
    """States whether the four cards above reflect a fresh read of the MYELIN
    lifetime database, and hosts the REFRESH control itself. Outer QFrame,
    object style, margins, spacing and the two-column text/status layout are
    all preserved from the Chapter-3-transfer-era strip this replaces --
    only its meaning and right-hand control changed: STATUS text became a
    REFRESH button."""

    refresh_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statBox")
        self.setAccessibleName("Chapter 6 lifetime evidence source")
        _allow_shrink(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        source = QLabel("SOURCE: MYELIN LIFETIME DATABASE")
        source.setProperty("role", "cyan")
        source.setFont(make_font(9, 800, spacing=0.5))
        source.setWordWrap(True)
        _allow_shrink(source)
        text_column.addWidget(source)
        self._body = QLabel(
            "Press REFRESH to read the current durable lifetime summary."
        )
        self._body.setProperty("role", "muted")
        self._body.setWordWrap(True)
        _allow_shrink(self._body)
        self._body.setFont(make_font(9.5, 400))
        text_column.addWidget(self._body)
        layout.addLayout(text_column, 1)

        self._refresh_button = QPushButton("REFRESH")
        self._refresh_button.setObjectName("analyticsRefreshButton")
        self._refresh_button.setAccessibleName("Refresh Chapter 6 lifetime evidence")
        self._refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_button.clicked.connect(self.refresh_clicked.emit)
        layout.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def render_not_refreshed(self) -> None:
        self._body.setText("Press REFRESH to read the current durable lifetime summary.")

    def begin_refresh(self) -> None:
        self._refresh_button.setEnabled(False)
        self._refresh_button.setText("REFRESHING...")

    def render_refreshed(self, generated_at_utc: str) -> None:
        self._body.setText(
            f"Lifetime summary refreshed from durable MYELIN history. "
            f"Last refreshed: {generated_at_utc}"
        )
        self._refresh_button.setEnabled(True)
        self._refresh_button.setText("REFRESH")

    def render_read_error(self, reason: str) -> None:
        self._body.setText(f"Lifetime database refresh failed: {reason}")
        self._refresh_button.setEnabled(True)
        self._refresh_button.setText("REFRESH")


#: Phase 6 -- the eight-subtopic navigator (key, tab label).  Order here is
#: the fixed tab order and the fixed page order in the inner stack. Do not
#: rename or reorder without Chief approval -- other chapters, and this
#: file's own defaults ("OVERVIEW selected on open"), assume this exact
#: list.
_TOPICS: Final = (
    ("overview", "OVERVIEW"),
    ("evidence", "EVIDENCE"),
    ("research", "RESEARCH"),
    ("privacy", "PRIVACY"),
    ("mi", "Mi"),
    ("ask_mi", "ASK Mi"),
    ("wellbeing", "WELL-BEING"),
    ("research_basis", "RESEARCH BASIS"),
)


class _TopicTabButton(QFrame):
    """One entry in the Chapter 6 topic navigator.  A plain clickable
    QFrame rather than a QPushButton -- QSS type selectors do not match
    across widget classes, so reusing the already theme-tested
    ``#chapterCentralQuestion`` (cyan-tinted emphasis surface, used
    elsewhere in this chapter for a highlighted card) for the ACTIVE state
    and ``#statBox`` (plain muted surface) for INACTIVE requires the tab to
    literally be a QFrame. No new theme.py rule; both object names are
    already resolved per-theme."""

    clicked_topic = pyqtSignal(str)

    def __init__(self, key: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        _allow_shrink(self)
        # Fixed vertical policy is the actual fix, not just tidiness: with
        # the default Preferred policy, an initial layout pass that runs
        # before ``_sync_stack_height`` has constrained the page stack (the
        # QTimer.singleShot(0, ...) deferral in __init__) left this button
        # free to absorb the *entire* leftover chapter height, rendering as
        # a near-full-page vertical bar instead of a compact tab -- caught
        # in this phase's own offscreen screenshot audit, not by any
        # earlier code review.
        policy = self.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Chapter 6 topic: {label}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        _allow_shrink(self._label)
        layout.addWidget(self._label)

        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.setObjectName("chapterCentralQuestion" if active else "statBox")
        self._label.setProperty("role", "cyan" if active else "muted")
        self._label.setFont(make_font(9.5, 800 if active else 600, spacing=0.4))
        for widget in (self, self._label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_topic.emit(self.key)
        super().mousePressEvent(event)


class _TopicNavigator(QFrame):
    """The compact topic-selector row: 8 across when it fits, reflowing to
    fewer columns (never shrinking the labels) at narrower widths -- same
    technique every reflow grid in this chapter already uses."""

    topic_selected = pyqtSignal(str)

    def __init__(self, topics: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter6TopicNavigator")
        _allow_shrink(self)
        # Same Fixed-height reasoning as _TopicTabButton: the navigator
        # itself must never absorb leftover vertical space that belongs to
        # the page stack below it.
        policy = self.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)
        self._buttons: dict[str, _TopicTabButton] = {}
        items: list[QWidget] = []
        for key, label in topics:
            button = _TopicTabButton(key, label)
            button.clicked_topic.connect(self.topic_selected.emit)
            self._buttons[key] = button
            items.append(button)
        self._grid = _LabelReflowGrid(
            items,
            wide_columns=8,
            medium_columns=4,
            narrow_columns=2,
            wide_min_width=1100,
            medium_min_width=620,
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._grid)

    def set_active(self, key: str) -> None:
        for button_key, button in self._buttons.items():
            button.set_active(button_key == key)


class _TopicStack(QStackedWidget):
    """A stack that sizes to its CURRENT topic page only -- the identical
    technique SCIENCE_LAB/lab.py's own ``_ChapterStack`` already uses one
    level up (Chapter 6 is itself one page inside that outer stack), kept
    as a local copy per this file's own established convention rather than
    importing lab.py (which this module must never reach back into)."""

    def sizeHint(self):  # noqa: N802 -- Qt override
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 -- Qt override
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        current = self.currentWidget()
        return current.hasHeightForWidth() if current is not None else super().hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        current = self.currentWidget()
        if current is not None and current.hasHeightForWidth():
            return current.heightForWidth(width)
        return super().heightForWidth(width)


class Chapter6ConclusionView(QWidget):
    """Chapter 6's page: an eight-subtopic research workspace (OVERVIEW,
    EVIDENCE, RESEARCH, PRIVACY, Mi, ASK Mi, WELL-BEING, RESEARCH BASIS)
    behind a compact topic navigator, replacing the Phase 1-5 flat vertical
    stack of the same sections (Phase 6: navigation/layout only -- every
    approved sentence from Phases 1-5 still exists exactly once, just
    grouped by subtopic instead of stacked top to bottom).  OVERVIEW is
    selected by default.  Presentation-only for every topic except EVIDENCE:
    no engine call, no database read or write anywhere in this class. The
    EVIDENCE page's six cards are driven entirely by whatever
    ``Chapter6LifetimeSummary`` was last delivered to
    ``render_lifetime_summary`` -- this view never reads the database
    itself; pressing REFRESH only emits ``refresh_lifetime_requested`` and
    waits for the host to call back. The most recent summary survives topic
    switching, because QStackedWidget keeps every page instance alive; only
    the CURRENT page is hidden, never destroyed or rebuilt.

    Emits ``topic_changed`` after every topic switch, once this view's own
    internal stack has re-synced to the new topic's height. This mirrors
    the existing ``ChapterTwoOrganViewer.organ_changed`` signal SCIENCE_LAB
    /lab.py already listens to -- and for the identical reason: lab.py's
    own outer chapter stack is height-fixed once, when Chapter 6 is first
    selected (based on whichever topic is visible then, i.e. OVERVIEW), and
    is never re-queried afterward on its own. A direct geometry probe
    confirmed this leaves the outer stack's fixed height frozen at the
    OVERVIEW-sized value across every later in-chapter topic switch: ~1360px
    of dead blank space below a short topic (EVIDENCE), and content taller
    than the frozen height -- genuinely unreachable by scrolling -- below a
    tall one (Mi). That is Chief's exact "too much empty space" / "content
    stops partway down, can't scroll further" report. This signal is the
    hook lab.py needs to re-sync its own stack on every Chapter 6 topic
    switch, not only on first chapter selection.
    """

    topic_changed = pyqtSignal(str)
    refresh_lifetime_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_topic_key = "overview"

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(12)

        self._navigator = _TopicNavigator(_TOPICS)
        self._navigator.topic_selected.connect(self._select_topic)
        root.addWidget(self._navigator)

        self._stack = _TopicStack()
        root.addWidget(self._stack, 1)

        page_builders = {
            "overview": self._build_overview_page,
            "evidence": self._build_evidence_page,
            "research": self._build_research_page,
            "privacy": self._build_privacy_page,
            "mi": self._build_mi_page,
            "ask_mi": self._build_ask_mi_page,
            "wellbeing": self._build_wellbeing_page,
            "research_basis": self._build_research_basis_page,
        }
        self._topic_index: dict[str, int] = {}
        for key, _label in _TOPICS:
            page = page_builders[key]()
            self._topic_index[key] = self._stack.addWidget(page)

        self._navigator.set_active("overview")
        self._stack.setCurrentIndex(self._topic_index["overview"])
        QTimer.singleShot(0, self._sync_stack_height)

    # ------------------------------------------------------------------
    # Topic navigation -- presentation-only: no engine call, no database
    # write, no widget recreation, no receipt mutation.  Switching topics
    # only changes which already-built page is visible.
    # ------------------------------------------------------------------

    def _select_topic(self, key: str) -> None:
        index = self._topic_index.get(key)
        if index is None:
            return
        self._current_topic_key = key
        self._stack.setCurrentIndex(index)
        self._navigator.set_active(key)
        self._reset_ancestor_scroll()
        # Deferred one event-loop turn, same reason lab.py's own
        # ScienceLabWorkspace._sync_stack_height is deferred: the stack's
        # real width is not yet valid immediately after setCurrentIndex.
        QTimer.singleShot(0, self._sync_stack_height)

    def current_topic_key(self) -> str:
        return self._current_topic_key

    def _sync_stack_height(self) -> None:
        current = self._stack.currentWidget()
        if current is None:
            return
        width = self._stack.width()
        if width <= 0:
            width = self._stack.sizeHint().width()
        if width > 0 and current.hasHeightForWidth():
            height = current.heightForWidth(width)
        else:
            height = current.sizeHint().height()
        self._stack.setFixedHeight(max(height, 1))
        # Emitted only after this view's own internal stack has already
        # been resized to the new topic's real height, so a lab.py
        # listener's own (further-deferred) outer re-sync reads correct,
        # settled geometry rather than a stale in-progress value.
        self.topic_changed.emit(self._current_topic_key)

    def _reset_ancestor_scroll(self) -> None:
        """Scroll the enclosing QScrollArea (owned by the Control Station
        host, not this view -- the same ancestor
        ScienceLabWorkspace._reset_ancestor_scroll already walks up to)
        back to the top on topic change, so switching topics never leaves
        the viewport scrolled to a position that belongs to the previous
        topic's content."""

        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QScrollArea):
                widget.verticalScrollBar().setValue(0)
                return
            widget = widget.parentWidget()

    # ------------------------------------------------------------------
    # Public lifetime-refresh contract. The view never opens the database
    # itself: the REFRESH button only emits ``refresh_lifetime_requested``;
    # the Control Station host reads the lifetime database through
    # ``SCIENCE_LAB.chapter6_lifetime.build_lifetime_summary`` and calls
    # ``render_lifetime_summary`` back with the immutable result. Works
    # regardless of which topic is currently visible: ``_evidence_cards``
    # and ``_evidence_provenance`` are persistent instance attributes on the
    # EVIDENCE page, which QStackedWidget never destroys just because it is
    # not the current page.
    # ------------------------------------------------------------------

    def _request_lifetime_refresh(self) -> None:
        self._evidence_provenance.begin_refresh()
        self.refresh_lifetime_requested.emit()

    def render_lifetime_summary(self, summary: Chapter6LifetimeSummary) -> None:
        """Update all four existing card widgets in place from one immutable
        lifetime summary. Presentation formatting only: never queries the
        database, never computes a scientific winner, never calls
        min()/max() for scientific selection -- the summary already carries
        the certified result or the precise reason it is UNAVAILABLE."""

        if not isinstance(summary, Chapter6LifetimeSummary):
            raise TypeError("Chapter 6 requires a Chapter6LifetimeSummary")
        for key, card in self._evidence_cards.items():
            result = getattr(summary, key)
            if result.status == AVAILABLE:
                value = _format_latency_ns(result.value) if result.unit == "ns" else str(result.value)
                card.render_available(value, reason=result.reason)
            else:
                card.render_unavailable(result.reason)
        self._evidence_provenance.render_refreshed(summary.generated_at_utc)
        self._resync_after_evidence_content_change()

    def render_lifetime_read_error(self, reason: str) -> None:
        """Best-effort failure path: a database read error is not the same
        as no evidence. The app stays usable and REFRESH re-enables; no
        card is silently turned into zero or left permanently disabled."""

        self._evidence_provenance.render_read_error(reason)
        self._resync_after_evidence_content_change()

    def _resync_after_evidence_content_change(self) -> None:
        """A REFRESH replaces card text in place rather than switching
        topics, so ``topic_changed`` never fires on its own -- but the new
        lifetime reason text is dramatically longer than the old static
        placeholders, so the page's real height can grow just as much as it
        does on a topic switch. Direct geometry probe confirmed this: six
        reason labels reported needing 37-89px but were left at a stale 24px
        floor, and the outer scrollbar's max stayed frozen at 0 even though
        real content extended well past the visible viewport -- the exact
        same frozen-height bug class the Phase 6 ``topic_changed`` fix
        addressed for topic switching, here triggered by in-place content
        change instead.

        Needs two deferred passes, not the one topic-switching uses: a
        direct trace confirmed the first ``_sync_stack_height`` call already
        applies the correct ``setMinimumHeight`` floor on each card (as a
        side effect of ``_apply_reflow_min_heights``) and sets the correct
        total stack height, but Qt does not synchronously reflow the card's
        own children to fill that new floor within the same call -- that
        reflow is scheduled for the next layout pass. Topic switching never
        needed a second pass because becoming newly visible already forces
        a full layout pass through Qt's own show/currentChanged machinery;
        an already-visible page's in-place content change has no such
        trigger. Measured empirically, not assumed: one deferred call left
        a card's real height at 116px against its own reported need of
        181px; a second deferred call (after the first has run) settled it
        at 181px exactly."""

        QTimer.singleShot(0, self._sync_stack_height)
        QTimer.singleShot(0, lambda: QTimer.singleShot(0, self._sync_stack_height))

    # ------------------------------------------------------------------
    # Topic pages -- each assembles the same section builders Phases 1-5
    # already defined, in the same order, grouped per Chief's Phase 6
    # content-to-subtopic map.  No section body was rewritten here; only
    # which page a given section's widget is added to changed.
    # ------------------------------------------------------------------

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_hero())
        layout.addWidget(self._build_what_myelin_does())
        layout.addWidget(self._build_pathways())
        layout.addWidget(self._build_why_recovery_matters())
        layout.addWidget(self._build_scientific_boundary())
        layout.addWidget(self._build_research_question())
        layout.addStretch(1)
        return page

    def _build_evidence_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_evidence_section())
        layout.addStretch(1)
        return page

    def _build_research_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_research_tool_intro())
        layout.addWidget(self._build_experiment_flow())
        layout.addWidget(self._build_use_cases())
        layout.addWidget(self._build_research_questions())
        layout.addWidget(self._build_controlled_study_concept())
        layout.addWidget(self._build_why_this_matters())
        layout.addStretch(1)
        return page

    def _build_privacy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_privacy_section())
        layout.addWidget(self._build_local_first_section())
        layout.addWidget(self._build_research_responsibility())
        layout.addStretch(1)
        return page

    def _build_mi_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_mi_overview())
        layout.addWidget(self._build_mi_architecture())
        layout.addWidget(self._build_mi_evidence_authority())
        layout.addWidget(self._build_mi_future_inputs())
        layout.addWidget(self._build_mi_adaptation_loop())
        layout.addWidget(self._build_mi_policy_boundary())
        layout.addWidget(self._build_mi_illustrative_patterns())
        layout.addWidget(self._build_mi_research_value())
        layout.addStretch(1)
        return page

    def _build_ask_mi_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_ask_mi())
        layout.addWidget(self._build_ask_mi_distinction())
        layout.addWidget(self._build_local_llm_concept())
        layout.addWidget(self._build_llm_authority_boundary())
        layout.addWidget(self._build_local_first_mi())
        layout.addStretch(1)
        return page

    def _build_wellbeing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_late_night_guidance())
        layout.addWidget(self._build_user_control())
        layout.addWidget(self._build_sustainable_self_regulation())
        layout.addStretch(1)
        return page

    def _build_research_basis_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(16)
        layout.addWidget(self._build_platform_direction())
        layout.addWidget(self._build_integration_foundations())
        layout.addWidget(self._build_integration_figure_image())
        layout.addWidget(self._build_research_basis())
        layout.addWidget(self._build_defensibility())
        layout.addWidget(self._build_final_synthesis())
        layout.addWidget(self._build_final_research_position())
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Hero
    # ------------------------------------------------------------------

    def _build_hero(self) -> QFrame:
        hero, layout = _card()
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(6)

        eyebrow = QLabel("CHAPTER 6")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.6))
        layout.addWidget(eyebrow)

        title = QLabel("CONCLUSION & FUTURE SCOPE")
        title.setWordWrap(True)
        _allow_shrink(title)
        title.setFont(make_font(26, 800, spacing=0.6))
        layout.addWidget(title)

        subtitle = QLabel("From Behavioral Evidence to Adaptive Self-Regulation")
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        _allow_shrink(subtitle)
        subtitle.setFont(make_font(14, 500))
        layout.addWidget(subtitle)
        layout.addSpacing(4)

        supporting = _paragraph(
            "MYELIN examines how digital distraction develops, how intervention "
            "occurs, and how behavioral return can be observed over time.",
            role="muted",
            size=11.5,
        )
        layout.addWidget(supporting)

        return hero

    # ------------------------------------------------------------------
    # What MYELIN Does
    # ------------------------------------------------------------------

    def _build_what_myelin_does(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("WHAT MYELIN DOES"))

        blocks = (
            (
                "A behavioral regulation system",
                "MYELIN is a privacy-oriented behavioral regulation system designed "
                "to observe how focused computer work is interrupted, how digital "
                "distraction develops, how interventions are delivered, and how a "
                "person returns to the original task.",
            ),
            (
                "More than accumulated screen time",
                "Rather than treating distraction only as accumulated screen time, "
                "MYELIN records a behavioral sequence that can include drift, "
                "intervention, continued activity, return initiation, verified "
                "return, relapse and episode closure.",
            ),
            (
                "One framework, four pathways",
                "SINE, MINE, COSINE, SECANT and COSECANT allow different forms of digital "
                "behavior to be regulated through separate pathways while remaining "
                "part of one common MYELIN framework.",
            ),
        )
        for sub_heading, body in blocks:
            heading = QLabel(sub_heading)
            heading.setFont(make_font(11.5, 700))
            heading.setWordWrap(True)
            _allow_shrink(heading)
            layout.addWidget(heading)
            layout.addWidget(_paragraph(body, role="muted", size=11))

        return frame

    # ------------------------------------------------------------------
    # The Four Regulation Pathways
    # ------------------------------------------------------------------

    def _build_pathways(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("THE FOUR REGULATION PATHWAYS"))
        layout.addWidget(
            _paragraph(
                "Different behaviors require different regulatory pathways.",
                role="muted",
                size=11,
            )
        )

        cards = [
            _PathwayCard(pathway["key"], pathway["tagline"], pathway["purpose"])
            for pathway in _PATHWAYS
        ]
        layout.addWidget(_PathwayGrid(cards))

        return frame

    # ------------------------------------------------------------------
    # Why Recovery Matters
    # ------------------------------------------------------------------

    def _build_why_recovery_matters(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("WHY RECOVERY MATTERS"))

        layout.addWidget(
            _paragraph(
                "The important event is not only that distraction occurred, but "
                "what happened afterwards. MYELIN is designed to preserve evidence "
                "of intervention, attempted return, verified behavioral return, "
                "relapse and eventual episode closure where those facts are "
                "available."
            )
        )
        layout.addWidget(
            _paragraph(
                "This creates a basis for studying behavioral recovery rather than "
                "treating distraction only as total screen time.",
                role="muted",
            )
        )

        concept_frame = QFrame()
        concept_frame.setObjectName("statBox")
        _allow_shrink(concept_frame)
        concept_layout = QVBoxLayout(concept_frame)
        concept_layout.setContentsMargins(16, 14, 16, 14)
        concept_layout.setSpacing(6)
        # No layout-level AlignHCenter -- see _vertical_flow's comment for
        # why that sizes children at sizeHint() instead of the frame's
        # real width and breaks wrapped-text heightForWidth.

        concept_tag = QLabel("BEHAVIORAL REGULATION CONCEPT")
        concept_tag.setProperty("role", "cyan")
        concept_tag.setFont(make_font(8.5, 700, spacing=0.8))
        concept_tag.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        concept_layout.addWidget(concept_tag)

        for index, step in enumerate(_RECOVERY_SEQUENCE):
            if index:
                arrow = QLabel("↓")
                arrow.setProperty("role", "muted")
                arrow.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                concept_layout.addWidget(arrow)
            step_label = QLabel(step)
            step_label.setFont(make_font(10.5, 700, spacing=0.4))
            step_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            concept_layout.addWidget(step_label)

        layout.addWidget(concept_frame)

        return frame

    # ------------------------------------------------------------------
    # Scientific Boundary (always visible -- never behind a button)
    # ------------------------------------------------------------------

    def _build_scientific_boundary(self) -> QFrame:
        frame, layout = _card()

        heading = QLabel("SCIENTIFIC BOUNDARY")
        heading.setProperty("role", "red")
        heading.setFont(make_font(12, 800, spacing=1.2))
        layout.addWidget(heading)

        layout.addWidget(
            _paragraph(
                "MYELIN does not directly measure neural activity, dopamine, "
                "fatigue or attention inside the brain. Its present evidence is "
                "behavioral and software-observed."
            )
        )
        layout.addWidget(
            _paragraph(
                "MYELIN can therefore describe observed digital behavior and "
                "intervention-response patterns, but it must not convert those "
                "observations into unsupported physiological or diagnostic claims.",
                role="muted",
            )
        )
        layout.addWidget(
            _paragraph(
                "MYELIN has not yet been demonstrated through controlled "
                "scientific trials to improve human attention or productivity. "
                "It provides a framework through which such hypotheses can be "
                "tested.",
                role="muted",
            )
        )

        return frame

    # ------------------------------------------------------------------
    # Closing research question
    # ------------------------------------------------------------------

    def _build_research_question(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapterCentralQuestion")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        eyebrow = QLabel("RESEARCH QUESTION")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.2))
        layout.addWidget(eyebrow)

        question = QLabel(_RESEARCH_QUESTION)
        question.setWordWrap(True)
        _allow_shrink(question)
        question.setFont(make_font(16, 700))
        layout.addWidget(question)

        note = _paragraph(
            "This is a research question MYELIN can be designed to test -- not "
            "an answered claim.",
            role="muted",
            size=10.5,
        )
        layout.addWidget(note)

        return frame

    # ------------------------------------------------------------------
    # Evidence at a Glance -- four cards, each driven by one lifetime
    # database REFRESH: BEST RETURN, WORST RETURN, TOP DISTRACTION
    # PLATFORM, TOP OTT PLATFORM. No raw read, local min/max, platform
    # inference, or cross-card invention happens in this view -- every
    # aggregation lives in SCIENCE_LAB.chapter6_lifetime.
    # ------------------------------------------------------------------

    def _build_evidence_section(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("EVIDENCE AT A GLANCE"))
        layout.addWidget(
            _paragraph(
                "These cards summarize durable MYELIN history. Press REFRESH "
                "to read the current lifetime database. A card remains "
                "UNAVAILABLE when the stored evidence or approved metric "
                "contract cannot support that summary.",
                role="muted",
                size=10.5,
            )
        )

        self._evidence_provenance = _EvidenceProvenanceStrip()
        self._evidence_provenance.refresh_clicked.connect(self._request_lifetime_refresh)
        layout.addWidget(self._evidence_provenance)

        self._evidence_cards: dict[str, _EvidenceCard] = {}
        cards: list[_EvidenceCard] = []
        for entry in _EVIDENCE_CARDS:
            card = _EvidenceCard(entry["title"])
            self._evidence_cards[entry["key"]] = card
            cards.append(card)
        layout.addWidget(_EvidenceGrid(cards))

        return frame

    # ------------------------------------------------------------------
    # MYELIN as a Research Tool (Phase 3)
    # ------------------------------------------------------------------

    def _build_research_tool_intro(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("MYELIN AS A RESEARCH TOOL"))

        layout.addWidget(
            _paragraph(
                "MYELIN can be treated not only as a behavioral regulation "
                "interface, but as an experimental framework for observing the "
                "sequence surrounding digital distraction and recovery."
            )
        )
        layout.addWidget(
            _paragraph(
                "A researcher can define a focused-work condition, observe "
                "software-visible behavioral events, record when an "
                "intervention occurs, and examine how the participant "
                "subsequently returns, relapses or closes the episode where "
                "those events are certified.",
                role="muted",
            )
        )

        conventional = QFrame()
        conventional.setObjectName("statBox")
        _allow_shrink(conventional)
        conventional_layout = QVBoxLayout(conventional)
        conventional_layout.setContentsMargins(14, 12, 14, 12)
        conventional_layout.setSpacing(6)
        conventional_heading = QLabel("A CONVENTIONAL FOCUS TOOL MAY REPORT")
        conventional_heading.setWordWrap(True)
        conventional_heading.setFont(make_font(9.5, 700, spacing=0.4))
        conventional_layout.addWidget(conventional_heading)
        for item in ("Time used", "Blocked app", "Screen time"):
            row = QLabel(f"•  {item}")
            row.setProperty("role", "muted")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            conventional_layout.addWidget(row)

        research = QFrame()
        research.setObjectName("statBox")
        _allow_shrink(research)
        research_layout = QVBoxLayout(research)
        research_layout.setContentsMargins(14, 12, 14, 12)
        research_layout.setSpacing(6)
        research_heading = QLabel("MYELIN'S RESEARCH FOCUS PRESERVES")
        research_heading.setProperty("role", "cyan")
        research_heading.setWordWrap(True)
        research_heading.setFont(make_font(9.5, 700, spacing=0.4))
        research_layout.addWidget(research_heading)
        for item in ("Behavioral context", "Intervention", "Return", "Verification", "Relapse / closure"):
            row = QLabel(f"•  {item}")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            research_layout.addWidget(row)

        layout.addWidget(
            _LabelReflowGrid(
                [conventional, research],
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=560,
                medium_min_width=560,
            )
        )

        layout.addWidget(
            _paragraph(
                "MYELIN's research focus is on the behavioral transition "
                "surrounding distraction and recovery, rather than relying "
                "only on accumulated usage duration.",
                role="muted",
                size=10.5,
            )
        )

        return frame

    def _build_experiment_flow(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        heading = QLabel("RESEARCH USE EXAMPLE")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(12, 700, spacing=1.2))
        header.addWidget(heading, 1)
        header.addWidget(_badge("CONCEPTUAL EXPERIMENT FLOW"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        subheading = QLabel("Attention Recovery Following Digital Distraction")
        subheading.setProperty("role", "muted")
        subheading.setWordWrap(True)
        _allow_shrink(subheading)
        subheading.setFont(make_font(11, 500))
        layout.addWidget(subheading)

        _add_centered(
            layout,
            _vertical_flow("CONCEPTUAL EXPERIMENT FLOW", _EXPERIMENT_FLOW_STEPS, max_width=560),
            560,
        )

        layout.addWidget(
            _paragraph(
                "Actual experiments contain only the events supported by their "
                "certified evidence.",
                role="muted",
                size=9.5,
            )
        )

        return frame

    def _build_use_cases(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("SCIENTIST USE CASES"))

        cards = [
            _UseCaseCard(entry["title"], entry["body"], badge=entry.get("badge", ""))
            for entry in _RESEARCH_USE_CASES
        ]
        layout.addWidget(_UseCaseGrid(cards))

        return frame

    def _build_research_questions(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("QUESTIONS MYELIN CAN HELP TEST"))

        for question in _RESEARCH_QUESTIONS:
            row = QLabel(f"•  {question}")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(11.5, 400))
            layout.addWidget(row)

        return frame

    def _build_controlled_study_concept(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_section_heading("A FUTURE CONTROLLED-EXPERIMENT CONCEPT"), 1)
        header.addWidget(_badge("FUTURE CONTROLLED STUDY DESIGN"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        condition_a = QLabel("CONDITION A — NORMAL WORK")
        condition_a.setProperty("role", "cyan")
        condition_a.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        condition_a.setFont(make_font(10, 700, spacing=0.3))
        layout.addWidget(condition_a)

        arrow = QLabel("↓")
        arrow.setProperty("role", "muted")
        arrow.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(arrow)

        branch = QHBoxLayout()
        branch.setSpacing(14)
        for label in ("CONDITION B\nConventional focus tool", "CONDITION C\nMYELIN-assisted regulation"):
            title_text, sub_text = label.split("\n")
            box = QFrame()
            box.setObjectName("statBox")
            _allow_shrink(box)
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 10, 12, 10)
            box_layout.setSpacing(3)
            title_label = QLabel(title_text)
            title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            title_label.setFont(make_font(9.5, 700, spacing=0.3))
            box_layout.addWidget(title_label)
            sub_label = QLabel(sub_text)
            sub_label.setProperty("role", "muted")
            sub_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            sub_label.setWordWrap(True)
            _allow_shrink(sub_label)
            sub_label.setFont(make_font(9, 400))
            box_layout.addWidget(sub_label)
            branch.addWidget(box, 1)
        layout.addLayout(branch)

        arrow2 = QLabel("↓\nCOMPARE OUTCOMES")
        arrow2.setProperty("role", "muted")
        arrow2.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        arrow2.setFont(make_font(9.5, 700, spacing=0.4))
        layout.addWidget(arrow2)

        layout.addWidget(
            _paragraph(
                "Possible future outcome measures for such a study, and their "
                "current certification status:",
                role="muted",
                size=9.5,
            )
        )
        # Compact two-column outcome grid (Phase 6 density fix): each
        # measure was previously one full-width row, leaving large empty
        # horizontal space beside a short label -- seven of those stacked
        # rows read as excessive vertical gap. Grouping two per row and
        # tightening the cell's own padding halves the height without
        # changing which measure is CURRENTLY CERTIFIED vs FUTURE
        # MEASUREMENT TARGET.
        outcome_cells: list[QWidget] = []
        for entry in _CONTROLLED_STUDY_OUTCOMES:
            cell = QFrame()
            cell.setObjectName("statBox")
            _allow_shrink(cell)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(10, 8, 10, 8)
            cell_layout.setSpacing(3)
            label = QLabel(entry["label"])
            label.setWordWrap(True)
            _allow_shrink(label)
            label.setFont(make_font(9.5, 700))
            cell_layout.addWidget(label)
            status = QLabel(entry["status"])
            status.setProperty("role", "cyan" if entry["status"].startswith("CURRENTLY") else "muted")
            status.setFont(make_font(8, 700, spacing=0.2))
            status.setWordWrap(True)
            _allow_shrink(status)
            cell_layout.addWidget(status)
            outcome_cells.append(cell)
        layout.addWidget(
            _LabelReflowGrid(
                outcome_cells,
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=500,
                medium_min_width=500,
            )
        )

        return frame

    def _build_why_this_matters(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("WHY THIS MATTERS"))

        layout.addWidget(
            _paragraph(
                "Digital distraction is not only a question of whether a person "
                "left the task. For research, the trajectory after that "
                "transition can also matter: whether intervention occurred, "
                "whether the person returned, whether the return was verified, "
                "and whether the person subsequently relapsed."
            )
        )
        layout.addWidget(
            _paragraph(
                "MYELIN's potential contribution is to make that trajectory "
                "observable and experimentally structured.",
                role="muted",
            )
        )
        layout.addWidget(
            _paragraph(
                "If future controlled studies demonstrate meaningful "
                "differences in recovery behavior, MYELIN could provide a "
                "platform for studying adaptive digital self-regulation rather "
                "than functioning only as a blocking or timing utility.",
                role="muted",
            )
        )

        return frame

    # ------------------------------------------------------------------
    # Privacy by Minimum Observation (Phase 3)
    # ------------------------------------------------------------------

    def _build_privacy_section(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("PRIVACY BY MINIMUM OBSERVATION"))

        layout.addWidget(
            _paragraph(
                "Behavioral research requires observation, but useful "
                "observation does not require unlimited access to a "
                "participant's private content."
            )
        )
        layout.addWidget(
            _paragraph(
                "MYELIN is designed around a minimum-observation principle: "
                "collect the contextual and behavioral evidence necessary for "
                "regulation and research while avoiding unnecessary inspection "
                "of private content.",
                role="muted",
            )
        )
        layout.addWidget(
            _paragraph(
                "The present architecture can use application, browser-host, "
                "platform and route-level context for behavioral "
                "classification. An OS-level window title is also read by the "
                "foreground reader, but it is deliberately excluded from "
                "platform/classification certification. SECANT may preserve a "
                "validated observation-bound caption for display only. The "
                "raw browser address, query text, account names and content "
                "identifiers are likewise never returned by the browser "
                "reader.",
                role="muted",
                size=11,
            )
        )

        # Side by side at comfortable width, stacked at narrow width (Phase
        # 6 responsiveness fix) -- reuses the same widget-reflow grid every
        # other multi-column group in this chapter already uses, so two
        # columns never get squeezed unreadably thin.
        observed_flow = _vertical_flow(
            "OBSERVED FOR REGULATION",
            (
                "APPLICATION / TAB CONTEXT",
                "BEHAVIORAL CLASSIFICATION",
                "MYELIN ORGAN",
                "EVENT / TIMING EVIDENCE",
                "SCIENCE LAB",
            ),
        )
        not_required_flow = _vertical_flow(
            "NOT REQUIRED AS SCIENCE-LAB EVIDENCE",
            (
                "PRIVATE MESSAGE CONTENT",
                "DOCUMENT BODY",
                "PERSONAL CONVERSATION CONTENT",
            ),
        )
        layout.addWidget(
            _LabelReflowGrid(
                [observed_flow, not_required_flow],
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=560,
                medium_min_width=560,
            )
        )

        layout.addWidget(
            _paragraph(
                "PRIVACY-FIRST is not the same as NO OBSERVATION -- MYELIN "
                "needs evidence to function. The distinction is that the "
                "content above is not required by, and does not reach, the "
                "behavioral evidence model.",
                role="muted",
                size=10.5,
            )
        )

        return frame

    def _build_local_first_section(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("LOCAL-FIRST PROCESSING"))

        layout.addWidget(
            _paragraph(
                "The present MYELIN prototype performs its core behavioral "
                "monitoring and Science Lab processing locally. A remote "
                "MYELIN server is not required for the current workflow."
            )
        )
        layout.addWidget(
            _paragraph(
                "This architecture can reduce unnecessary external "
                "transmission of behavioral research data while keeping "
                "analysis close to the participant's device.",
                role="muted",
            )
        )
        layout.addWidget(
            _paragraph(
                "Local operation does not remove the need for informed "
                "consent, secure storage, transparent study protocols and "
                "appropriate research governance.",
                role="muted",
            )
        )

        platform_row = QHBoxLayout()
        platform_row.setSpacing(8)
        platform_caption = QLabel("CURRENT PROTOTYPE")
        platform_caption.setFont(make_font(8.5, 700, spacing=0.6))
        platform_caption.setProperty("role", "muted")
        platform_row.addWidget(platform_caption)
        platform_value = QLabel("Windows")
        platform_value.setFont(make_font(9.5, 700))
        platform_row.addWidget(platform_value)
        platform_row.addStretch(1)
        layout.addLayout(platform_row)

        return frame

    def _build_research_responsibility(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("RESEARCH RESPONSIBILITY"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        for index, point in enumerate(_RESEARCH_RESPONSIBILITY_POINTS):
            row, col = divmod(index, 2)
            label = QLabel(f"•  {point}")
            label.setWordWrap(True)
            _allow_shrink(label)
            label.setFont(make_font(10, 700, spacing=0.2))
            grid.addWidget(label, row, col)
        layout.addLayout(grid)

        layout.addWidget(
            _paragraph(
                "Any human-participant study using MYELIN would still require "
                "the appropriate consent, ethics and data-governance "
                "procedures.",
                role="muted",
                size=10,
            )
        )

        return frame

    # ------------------------------------------------------------------
    # Mi -- MYELIN Intelligence (Phase 4).  Future Scope / concept only:
    # no model, no inference, no network call, no new import, no live
    # data.  Every sub-section carries its own FUTURE SCOPE / CONCEPT /
    # ILLUSTRATIVE FUTURE EXAMPLE / FUTURE BEHAVIORAL GUIDANCE badge.
    # ------------------------------------------------------------------

    def _build_mi_overview(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        heading = QLabel("Mi — MYELIN INTELLIGENCE")
        heading.setProperty("role", "cyan")
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading.setFont(make_font(14, 800, spacing=0.6))
        header.addWidget(heading, 1)
        header.addWidget(_badge("FUTURE SCOPE"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "MYELIN Intelligence (Mi) is envisioned as a future adaptive "
                "layer that learns from longitudinal MYELIN behavioral "
                "evidence and helps coordinate personalized guidance across "
                "SINE, MINE, COSINE, SECANT and COSECANT while remaining constrained "
                "by approved MYELIN policy."
            )
        )
        layout.addWidget(
            _paragraph(
                "Mi does not exist as running software today. Everything in "
                "this section describes a possible future architecture, not "
                "current MYELIN behavior.",
                role="muted",
                size=10,
            )
        )

        return frame

    def _build_mi_architecture(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("Mi ARCHITECTURE"))

        diagram = QFrame()
        diagram.setObjectName("statBox")
        _allow_shrink(diagram)
        # Capped, not stretched to the card's full width: four short organ
        # names spread across an entire wide card left large dead gaps
        # between them (the Phase 5/6 audit's "Mi Architecture whitespace"
        # finding). A bounded, centered diagram keeps node spacing tight
        # and readable at every card width.
        diagram.setMaximumWidth(480)
        diagram_layout = QVBoxLayout(diagram)
        diagram_layout.setContentsMargins(16, 14, 16, 14)
        diagram_layout.setSpacing(7)
        # No layout-level AlignHCenter -- see _vertical_flow's comment.

        mi_label = QLabel("Mi\nMYELIN INTELLIGENCE")
        mi_label.setProperty("role", "cyan")
        mi_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        mi_label.setFont(make_font(11.5, 800, spacing=0.4))
        diagram_layout.addWidget(mi_label)

        arrow = QLabel("↓")
        arrow.setProperty("role", "muted")
        arrow.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        diagram_layout.addWidget(arrow)

        organ_row = QHBoxLayout()
        organ_row.setSpacing(8)
        for organ in _MI_ARCHITECTURE_ORGANS:
            organ_chip = QFrame()
            organ_chip.setObjectName("card")
            organ_chip_layout = QVBoxLayout(organ_chip)
            organ_chip_layout.setContentsMargins(6, 5, 6, 5)
            organ_label = QLabel(organ)
            organ_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            organ_label.setWordWrap(True)
            _allow_shrink(organ_label)
            organ_label.setFont(make_font(9.5, 700, spacing=0.3))
            organ_chip_layout.addWidget(organ_label)
            organ_row.addWidget(organ_chip, 1)
        diagram_layout.addLayout(organ_row)

        for step in ("↓", "LONGITUDINAL EVIDENCE", "↓", "PERSONALIZED GUIDANCE"):
            label = QLabel(step)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setWordWrap(True)
            _allow_shrink(label)
            if step == "↓":
                label.setProperty("role", "muted")
            else:
                label.setFont(make_font(10.5, 700, spacing=0.3))
            diagram_layout.addWidget(label)

        _add_centered(layout, diagram, 480)

        layout.addWidget(
            _paragraph(
                "Mi is not a sixth organ. SINE, MINE, COSINE, SECANT and COSECANT "
                "retain their individual functions -- Mi would sit above "
                "them as a future adaptive intelligence layer, not replace "
                "any of them.",
                role="muted",
            )
        )

        return frame

    def _build_mi_evidence_authority(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("Mi EVIDENCE AUTHORITY"))

        _add_centered(layout, _vertical_flow("CONCEPT", _MI_EVIDENCE_AUTHORITY_STEPS, max_width=560), 560)

        layout.addWidget(
            _paragraph(
                "Mi would operate on evidence generated by MYELIN; it would "
                "not replace the deterministic evidence system that "
                "establishes what occurred.",
                role="muted",
            )
        )

        return frame

    def _build_mi_future_inputs(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_section_heading("FUTURE Mi INPUTS"), 1)
        header.addWidget(_badge("FUTURE / EVIDENCE-DEPENDENT"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "Possible future inputs, not wired to any live data source "
                "in this phase:",
                role="muted",
                size=10,
            )
        )

        items = []
        for item in _MI_FUTURE_INPUTS:
            label = QLabel(f"•  {item}")
            label.setWordWrap(True)
            _allow_shrink(label)
            label.setFont(make_font(10, 700, spacing=0.2))
            items.append(label)
        layout.addWidget(_LabelReflowGrid(items, wide_columns=4, medium_columns=3, narrow_columns=2))

        return frame

    def _build_mi_adaptation_loop(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("EVIDENCE-GUIDED ADAPTATION"))

        _add_centered(
            layout,
            _vertical_flow(
                "POLICY-CONSTRAINED PERSONALIZATION", _MI_ADAPTATION_LOOP_STEPS, max_width=560
            ),
            560,
        )

        layout.addWidget(
            _paragraph(
                "Adaptation would remain constrained by approved MYELIN "
                "intervention policy.",
                role="muted",
            )
        )

        return frame

    def _build_mi_policy_boundary(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_section_heading("STRICT Mi POLICY BOUNDARY"), 1)
        header.addWidget(_badge("CONCEPT"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "A future Mi -- including any local language model behind "
                "Ask Mi -- must not freely invent:",
                role="muted",
            )
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        for index, item in enumerate(_MI_POLICY_BOUNDARY_ITEMS):
            row, col = divmod(index, 2)
            label = QLabel(f"✕  {item}")
            label.setWordWrap(True)
            _allow_shrink(label)
            label.setFont(make_font(10.5, 400))
            grid.addWidget(label, row, col)
        layout.addLayout(grid)

        return frame

    def _build_mi_illustrative_patterns(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("ILLUSTRATIVE FUTURE PATTERNS"))

        cards = [
            _UseCaseCard(entry["title"], entry["body"], badge="ILLUSTRATIVE FUTURE EXAMPLE")
            for entry in _MI_ILLUSTRATIVE_PATTERNS
        ]
        layout.addWidget(_UseCaseGrid(cards))

        return frame

    def _build_ask_mi(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_section_heading("ASK Mi"), 1)
        header.addWidget(_badge("FUTURE SCOPE"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "Ask Mi is envisioned as a conversational interface through "
                "which users could query their own MYELIN behavioral "
                "history, request explanations and obtain planning support "
                "grounded in approved local evidence."
            )
        )

        layout.addWidget(
            _paragraph("Example future queries -- not functional in this phase:", role="muted", size=10)
        )
        # Compact quote cards in a responsive 2/1-column grid (Phase 6
        # polish) rather than six stacked full-width lines -- still six
        # static, non-functional QLabels, just grouped more efficiently.
        question_cards: list[QWidget] = []
        for question in _ASK_MI_EXAMPLE_QUESTIONS:
            card = QFrame()
            card.setObjectName("statBox")
            _allow_shrink(card)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            row = QLabel(question)
            row.setProperty("role", "muted")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10, 400, italic=True))
            card_layout.addWidget(row)
            question_cards.append(card)
        layout.addWidget(
            _LabelReflowGrid(
                question_cards,
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=520,
                medium_min_width=520,
            )
        )

        return frame

    def _build_ask_mi_distinction(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("ASK Mi IS NOT A GENERIC CHATBOT"))

        generic = QFrame()
        generic.setObjectName("statBox")
        _allow_shrink(generic)
        generic_layout = QVBoxLayout(generic)
        generic_layout.setContentsMargins(14, 12, 14, 12)
        generic_layout.setSpacing(6)
        generic_heading = QLabel("GENERIC CHATBOT")
        generic_heading.setFont(make_font(9.5, 700, spacing=0.3))
        generic_layout.addWidget(generic_heading)
        for item in ("General conversation", "General knowledge", "No MYELIN evidence authority"):
            row = QLabel(f"•  {item}")
            row.setProperty("role", "muted")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            generic_layout.addWidget(row)

        ask_mi = QFrame()
        ask_mi.setObjectName("statBox")
        _allow_shrink(ask_mi)
        ask_mi_layout = QVBoxLayout(ask_mi)
        ask_mi_layout.setContentsMargins(14, 12, 14, 12)
        ask_mi_layout.setSpacing(6)
        ask_mi_heading = QLabel("ASK Mi")
        ask_mi_heading.setProperty("role", "cyan")
        ask_mi_heading.setFont(make_font(9.5, 700, spacing=0.3))
        ask_mi_layout.addWidget(ask_mi_heading)
        for item in ("MYELIN-context questions", "Behavioral history", "Policy-aware guidance", "Evidence-grounded explanations"):
            row = QLabel(f"•  {item}")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            ask_mi_layout.addWidget(row)

        layout.addWidget(
            _LabelReflowGrid(
                [generic, ask_mi],
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=560,
                medium_min_width=560,
            )
        )

        return frame

    def _build_local_llm_concept(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_section_heading("LOCAL LLM CONCEPT"), 1)
        header.addWidget(_badge("CONCEPT"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        _add_centered(layout, _vertical_flow("CONCEPT", _LOCAL_LLM_FLOW_STEPS, max_width=620), 620)

        layout.addWidget(
            _paragraph(
                "Mi's orchestration, policy and the certified MYELIN "
                "evidence it retrieves would be established before the "
                "model runs, and its output would be checked against that "
                "same policy and evidence again before becoming a "
                "response: MYELIN retrieves the facts, and a future "
                "language model would help communicate and reason over "
                "those permitted facts -- it would not independently "
                "decide which facts to believe."
            )
        )
        layout.addWidget(
            _paragraph(
                "A future implementation could use a locally hosted language "
                "model, such as a Llama-family model, where hardware "
                "permits. MYELIN does not currently include or run a "
                "language model.",
                role="muted",
            )
        )

        return frame

    def _build_llm_authority_boundary(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("LLM AUTHORITY BOUNDARY"))

        may = QFrame()
        may.setObjectName("statBox")
        _allow_shrink(may)
        may_layout = QVBoxLayout(may)
        may_layout.setContentsMargins(14, 12, 14, 12)
        may_layout.setSpacing(6)
        may_heading = QLabel("A FUTURE LOCAL MODEL MAY ASSIST WITH")
        may_heading.setProperty("role", "cyan")
        may_heading.setWordWrap(True)
        may_heading.setFont(make_font(9.5, 700, spacing=0.3))
        may_layout.addWidget(may_heading)
        for item in _LLM_MAY_ASSIST_WITH:
            row = QLabel(f"•  {item}")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            may_layout.addWidget(row)

        must_not = QFrame()
        must_not.setObjectName("statBox")
        _allow_shrink(must_not)
        must_not_layout = QVBoxLayout(must_not)
        must_not_layout.setContentsMargins(14, 12, 14, 12)
        must_not_layout.setSpacing(6)
        must_not_heading = QLabel("IT MUST NOT INDEPENDENTLY DECIDE")
        must_not_heading.setWordWrap(True)
        must_not_heading.setFont(make_font(9.5, 700, spacing=0.3))
        must_not_layout.addWidget(must_not_heading)
        for item in _LLM_MUST_NOT_DECIDE:
            row = QLabel(f"✕  {item}")
            row.setProperty("role", "muted")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            must_not_layout.addWidget(row)

        # Side by side at comfortable width, stacked when narrow (same
        # Phase 6 responsiveness fix as the Privacy pipelines).
        layout.addWidget(
            _LabelReflowGrid(
                [may, must_not],
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=560,
                medium_min_width=560,
            )
        )

        layout.addWidget(
            _paragraph(
                "The deterministic MYELIN evidence system remains "
                "authoritative.",
                role="muted",
                size=10,
            )
        )

        return frame

    def _build_local_first_mi(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("LOCAL-FIRST Mi"))

        layout.addWidget(
            _paragraph(
                "A locally hosted model could allow conversational "
                "interaction with MYELIN behavioral history without "
                "requiring the default transfer of that history to a "
                "remote inference service."
            )
        )
        layout.addWidget(
            _paragraph(
                "Local execution alone does not guarantee privacy; model "
                "configuration, storage, consent and research governance "
                "would still require careful control.",
                role="muted",
            )
        )

        return frame

    def _build_late_night_guidance(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        heading = QLabel("WHEN PRODUCTIVITY SHOULD STOP")
        heading.setProperty("role", "cyan")
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading.setFont(make_font(12, 700, spacing=1.0))
        header.addWidget(heading, 1)
        header.addWidget(_badge("FUTURE BEHAVIORAL GUIDANCE"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "MYELIN should not always push the user to keep working. A "
                "future Mi may use behavioral context -- not physiology -- "
                "to recognize that continued productivity nudging may no "
                "longer be appropriate.",
                role="muted",
            )
        )

        concept = QFrame()
        concept.setObjectName("statBox")
        _allow_shrink(concept)
        # Capped width (matches _vertical_flow's Phase 6 fix) and a
        # generous bottom margin: the closing quote is this box's last,
        # tallest-when-wrapped child, and Chief's native screenshot showed
        # it sitting close enough to the box's own bottom edge to read as
        # clipped/colliding with the caption below. A wider bottom margin
        # plus every label below getting wordWrap+_allow_shrink removes
        # that risk regardless of exact font-metrics on the real display.
        concept.setMaximumWidth(560)
        concept_layout = QVBoxLayout(concept)
        concept_layout.setContentsMargins(18, 16, 18, 22)
        concept_layout.setSpacing(6)
        # No layout-level AlignHCenter -- this was the actual root cause of
        # the reported clipped quote (see _vertical_flow's comment): it
        # sized the quote label at its own unconstrained sizeHint() width
        # instead of the box's real width, so heightForWidth was computed
        # against the wrong number and the wrapped second line was cut.

        for index, condition in enumerate(_LATE_NIGHT_CONDITIONS):
            if index:
                plus = QLabel("+")
                plus.setProperty("role", "muted")
                plus.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                concept_layout.addWidget(plus)
            label = QLabel(condition)
            label.setWordWrap(True)
            _allow_shrink(label)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setFont(make_font(10, 700, spacing=0.3))
            concept_layout.addWidget(label)

        arrow = QLabel("↓")
        arrow.setProperty("role", "muted")
        arrow.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        concept_layout.addWidget(arrow)

        pattern = QLabel("Mi IDENTIFIES A RECURRING\nBEHAVIORAL PATTERN")
        pattern.setWordWrap(True)
        _allow_shrink(pattern)
        pattern.setProperty("role", "cyan")
        pattern.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pattern.setFont(make_font(10, 700, spacing=0.3))
        concept_layout.addWidget(pattern)

        arrow2 = QLabel("↓")
        arrow2.setProperty("role", "muted")
        arrow2.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        concept_layout.addWidget(arrow2)

        quote = QLabel("“Consider ending this session and resting.”")
        quote.setWordWrap(True)
        _allow_shrink(quote)
        quote.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        quote.setFont(make_font(11, 700, italic=True))
        concept_layout.addWidget(quote)

        _add_centered(layout, concept, 560)

        layout.addWidget(
            _paragraph(
                "Mi would describe behavior, not physiology: wording such as "
                "repeated late-session drift, slower observed recovery, and "
                "recurring behavioral pattern -- never a claim that a user "
                "is fatigued, that their brain or cognitive system is "
                "exhausted, or that they medically need sleep.",
                role="muted",
                size=10.5,
            )
        )

        return frame

    def _build_user_control(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("USER CONTROL"))

        # Responsive chip grid (Phase 6 polish): 5 across when it fits, 3
        # then 2 as the card narrows -- never shrunk to fit five across.
        chips: list[QWidget] = []
        for option in _USER_CONTROL_OPTIONS:
            chip = QFrame()
            chip.setObjectName("statBox")
            _allow_shrink(chip)
            chip_layout = QVBoxLayout(chip)
            chip_layout.setContentsMargins(10, 9, 10, 9)
            label = QLabel(option)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setWordWrap(True)
            _allow_shrink(label)
            label.setFont(make_font(9.5, 700, spacing=0.2))
            chip_layout.addWidget(label)
            chips.append(chip)
        layout.addWidget(
            _LabelReflowGrid(
                chips,
                wide_columns=5,
                medium_columns=3,
                narrow_columns=2,
                wide_min_width=620,
                medium_min_width=380,
            )
        )

        layout.addWidget(
            _paragraph(
                "The user remains the final decision maker. Mi provides "
                "guidance -- it does not autonomously decide when the user "
                "must sleep or stop working.",
                role="muted",
            )
        )

        return frame

    def _build_sustainable_self_regulation(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapterCentralQuestion")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        eyebrow = QLabel("SUSTAINABLE SELF-REGULATION")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.2))
        layout.addWidget(eyebrow)

        statement = QLabel(
            "The long-term objective of Mi is not to maximize work "
            "duration. It is to support sustainable self-regulation across "
            "focus, distraction, recovery, breaks and rest."
        )
        statement.setWordWrap(True)
        _allow_shrink(statement)
        statement.setFont(make_font(15, 700))
        layout.addWidget(statement)

        return frame

    def _build_mi_research_value(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("Mi RESEARCH VALUE"))

        layout.addWidget(
            _paragraph(
                "If developed and validated, Mi could allow MYELIN to "
                "investigate whether individualized, context-sensitive "
                "intervention policies produce different recovery patterns "
                "from static intervention schedules."
            )
        )
        layout.addWidget(
            _paragraph(
                "This capability does not exist today and has not been "
                "tested.",
                role="muted",
                size=10,
            )
        )

        return frame

    # ------------------------------------------------------------------
    # Phase 5 -- Future Platform, Research Basis & Final Synthesis.
    # Presentation only: no new metric, no raw read, no new package
    # field, no persistence, no analysis, no platform tracking.
    # ------------------------------------------------------------------

    def _build_platform_direction(self) -> QFrame:
        frame, layout = _card()

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_section_heading("PLATFORM DIRECTION"), 1)
        header.addWidget(_badge("FUTURE SCOPE"), 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "The current MYELIN prototype is developed for Windows. "
                "Future work could adapt the behavioral observation layer "
                "to macOS and other desktop environments while preserving "
                "the same organ and evidence architecture.",
                role="muted",
            )
        )

        current = QFrame()
        current.setObjectName("statBox")
        _allow_shrink(current)
        current_layout = QVBoxLayout(current)
        current_layout.setContentsMargins(14, 12, 14, 12)
        current_layout.setSpacing(4)
        current_caption = QLabel("CURRENT PROTOTYPE")
        current_caption.setFont(make_font(8.5, 700, spacing=0.6))
        current_caption.setProperty("role", "muted")
        current_layout.addWidget(current_caption)
        current_value = QLabel("Windows")
        current_value.setFont(make_font(11.5, 700))
        current_layout.addWidget(current_value)

        future = QFrame()
        future.setObjectName("statBox")
        _allow_shrink(future)
        future_layout = QVBoxLayout(future)
        future_layout.setContentsMargins(14, 12, 14, 12)
        future_layout.setSpacing(4)
        future_caption = QLabel("FUTURE PORTABILITY")
        future_caption.setFont(make_font(8.5, 700, spacing=0.6))
        future_caption.setProperty("role", "cyan")
        future_layout.addWidget(future_caption)
        future_value = QLabel("macOS · broader desktop environments")
        future_value.setWordWrap(True)
        _allow_shrink(future_value)
        future_value.setFont(make_font(11.5, 700))
        future_layout.addWidget(future_value)

        layout.addWidget(
            _LabelReflowGrid(
                [current, future],
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=460,
                medium_min_width=460,
            )
        )

        return frame

    # ------------------------------------------------------------------
    # Research Basis extension -- Integrating the Scientific Foundations of
    # MYELIN (Ebbinghaus, JITAI, Weber-Fechner, Gloria Mark). Inserted
    # between the existing Platform Direction and Research Basis blocks per
    # Chief's supplied research dossier. Presentation only: no new metric,
    # no new evidence field, no new timing constant, no new Mi rule, no new
    # intervention rule, no backend behavior. Mi remains future scope; the
    # deterministic MYELIN organ/evidence system remains the current
    # evidence authority, exactly as everywhere else in this file.
    # ------------------------------------------------------------------

    def _build_integration_foundations(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("INTEGRATING THE SCIENTIFIC FOUNDATIONS OF MYELIN"))
        layout.addWidget(_paragraph(_INTEGRATION_INTRO))

        figure = QFrame()
        figure.setObjectName("statBox")
        _allow_shrink(figure)
        figure_layout = QVBoxLayout(figure)
        figure_layout.setContentsMargins(18, 16, 18, 18)
        figure_layout.setSpacing(10)
        # No layout-level AlignHCenter -- see _vertical_flow's comment for
        # why that breaks wrapped-text heightForWidth; every label below
        # centers only its own text via setAlignment.

        figure_tag = QLabel("SCIENTIFIC FOUNDATIONS → MYELIN ARCHITECTURE")
        figure_tag.setProperty("role", "cyan")
        figure_tag.setFont(make_font(8.5, 700, spacing=0.8))
        figure_tag.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        figure_tag.setWordWrap(True)
        _allow_shrink(figure_tag)
        figure_layout.addWidget(figure_tag)

        foundation_cards = [_build_foundation_card(entry) for entry in _FOUNDATIONS]
        figure_layout.addWidget(_UseCaseGrid(foundation_cards))

        arrow1 = QLabel("↓")
        arrow1.setProperty("role", "muted")
        arrow1.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        figure_layout.addWidget(arrow1)

        organs_label = QLabel("MYELIN'S BEHAVIORAL ORGANS")
        organs_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        organs_label.setWordWrap(True)
        _allow_shrink(organs_label)
        organs_label.setFont(make_font(10.5, 700, spacing=0.3))
        figure_layout.addWidget(organs_label)

        organ_row = QHBoxLayout()
        organ_row.setSpacing(8)
        for organ in _MI_ARCHITECTURE_ORGANS:
            organ_chip = QFrame()
            organ_chip.setObjectName("card")
            organ_chip_layout = QVBoxLayout(organ_chip)
            organ_chip_layout.setContentsMargins(6, 5, 6, 5)
            organ_label = QLabel(organ)
            organ_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            organ_label.setWordWrap(True)
            _allow_shrink(organ_label)
            organ_label.setFont(make_font(9.5, 700, spacing=0.3))
            organ_chip_layout.addWidget(organ_label)
            organ_row.addWidget(organ_chip, 1)
        figure_layout.addLayout(organ_row)

        for step in ("↓", "CERTIFIED BEHAVIORAL EVIDENCE", "↓", "Mi (FUTURE SCOPE)", "↓", "POLICY-CONSTRAINED GUIDANCE"):
            label = QLabel(step)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setWordWrap(True)
            _allow_shrink(label)
            if step == "↓":
                label.setProperty("role", "muted")
            elif step == "Mi (FUTURE SCOPE)":
                label.setProperty("role", "cyan")
                label.setFont(make_font(10.5, 800, spacing=0.3))
            else:
                label.setFont(make_font(10.5, 700, spacing=0.3))
            figure_layout.addWidget(label)

        _add_centered(layout, figure, 940)

        layout.addWidget(_paragraph(_INTEGRATION_CAPTION, role="muted", size=9.5))
        layout.addWidget(_paragraph(_INTEGRATION_SYNTHESIS))
        layout.addWidget(_paragraph(_INTEGRATION_TRANSITION, role="muted", size=10.5))

        return frame

    def _build_integration_figure_image(self) -> QFrame:
        """The page-13 systems-flow figure, as an additive card appended
        after the foundation cards above -- ``_build_integration_foundations``
        is untouched by this method; this adds a new card, it does not
        alter or replace the existing one. Vector (inline SVG), not a
        raster asset file -- see ``_INTEGRATION_FIGURE_SVG``'s comment for
        why."""

        frame, layout = _card()
        svg_widget = _SvgFigureWidget(_INTEGRATION_FIGURE_SVG)
        _add_centered(layout, svg_widget, 1080)
        layout.addWidget(_paragraph(_INTEGRATION_FIGURE_CAPTION_V2, role="muted", size=9.5))
        return frame

    def _build_research_basis(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("RESEARCH BASIS"))

        layout.addWidget(
            _paragraph(
                "MYELIN's research direction is informed by established work "
                "on sustained attention, task focus, interruptions, "
                "recovery, adaptive interventions and privacy in behavioral "
                "digital systems."
            )
        )
        layout.addWidget(
            _paragraph(
                "These references provide scientific context for the "
                "questions MYELIN is designed to investigate; they do not "
                "constitute evidence that MYELIN itself is effective.",
                role="muted",
            )
        )

        theme_cards = []
        for entry in _RESEARCH_BASIS_THEMES:
            card = QFrame()
            card.setObjectName("card")
            _allow_shrink(card)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(5)

            header_row = QHBoxLayout()
            header_row.setSpacing(6)
            title_label = QLabel(entry["title"])
            title_label.setWordWrap(True)
            _allow_shrink(title_label)
            title_label.setFont(make_font(10.5, 700, spacing=0.3))
            header_row.addWidget(title_label, 1)
            ref_label = QLabel(entry["ref"])
            ref_label.setProperty("role", "cyan")
            ref_label.setFont(make_font(9.5, 700, mono=True))
            header_row.addWidget(ref_label, 0, Qt.AlignmentFlag.AlignRight)
            card_layout.addLayout(header_row)

            card_layout.addWidget(_paragraph(entry["body"], role="muted", size=10))
            theme_cards.append(card)

        layout.addWidget(_UseCaseGrid(theme_cards))

        references_frame = QFrame()
        references_frame.setObjectName("statBox")
        _allow_shrink(references_frame)
        references_layout = QVBoxLayout(references_frame)
        references_layout.setContentsMargins(18, 16, 18, 16)
        references_layout.setSpacing(11)

        references_heading = QLabel("REFERENCES")
        references_heading.setFont(make_font(9.5, 700, spacing=0.6))
        references_heading.setProperty("role", "muted")
        references_layout.addWidget(references_heading)

        # Hanging-indent presentation (Phase 6 polish): each citation string
        # in _REFERENCES is untouched -- ``partition`` only separates the
        # existing "[n] " marker from the body text at render time, so no
        # author/title/journal/year/DOI/numbering character changes. This
        # replaces one dense flat block with a readable numbered list.
        for citation in _REFERENCES:
            marker, _sep, body = citation.partition(" ")
            row = QHBoxLayout()
            row.setSpacing(8)
            marker_label = QLabel(marker)
            marker_label.setProperty("role", "cyan")
            marker_label.setFont(make_font(9.5, 800, mono=True))
            marker_label.setFixedWidth(26)
            marker_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            row.addWidget(marker_label, 0)
            body_label = QLabel(body)
            body_label.setWordWrap(True)
            _allow_shrink(body_label)
            body_label.setFont(make_font(9.5, 400))
            row.addWidget(body_label, 1)
            references_layout.addLayout(row)

        layout.addWidget(references_frame)

        return frame

    def _build_defensibility(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("SCIENTIFIC MATURITY"))
        layout.addWidget(
            _paragraph(
                "Scientific maturity means defining what is not yet known, "
                "not only what has been built.",
                role="muted",
                size=10.5,
            )
        )

        defensible = QFrame()
        defensible.setObjectName("chapterBoundaryCan")
        _allow_shrink(defensible)
        defensible_layout = QVBoxLayout(defensible)
        defensible_layout.setContentsMargins(14, 12, 14, 12)
        defensible_layout.setSpacing(7)
        defensible_heading = QLabel("CURRENTLY DEFENSIBLE")
        defensible_heading.setObjectName("chapterBoundaryHeadingCan")
        defensible_heading.setFont(make_font(10.5, 700, spacing=0.5))
        defensible_layout.addWidget(defensible_heading)
        for item in _CURRENTLY_DEFENSIBLE_ITEMS:
            row = QLabel(f"✓  {item}")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            defensible_layout.addWidget(row)

        not_yet = QFrame()
        not_yet.setObjectName("chapterBoundaryCannot")
        _allow_shrink(not_yet)
        not_yet_layout = QVBoxLayout(not_yet)
        not_yet_layout.setContentsMargins(14, 12, 14, 12)
        not_yet_layout.setSpacing(7)
        not_yet_heading = QLabel("NOT YET ESTABLISHED")
        not_yet_heading.setObjectName("chapterBoundaryHeadingCannot")
        not_yet_heading.setFont(make_font(10.5, 700, spacing=0.5))
        not_yet_layout.addWidget(not_yet_heading)
        for item in _NOT_YET_ESTABLISHED_ITEMS:
            row = QLabel(f"✕  {item}")
            row.setWordWrap(True)
            _allow_shrink(row)
            row.setFont(make_font(10.5, 400))
            not_yet_layout.addWidget(row)

        layout.addWidget(
            _LabelReflowGrid(
                [defensible, not_yet],
                wide_columns=2,
                medium_columns=2,
                narrow_columns=1,
                wide_min_width=560,
                medium_min_width=560,
            )
        )

        return frame

    def _build_final_synthesis(self) -> QFrame:
        frame, layout = _card()
        layout.addWidget(_section_heading("CONCLUSION"))

        layout.addWidget(
            _paragraph(
                "MYELIN proposes a privacy-oriented framework for studying "
                "digital distraction as a behavioral process rather than "
                "only as accumulated usage time. Its current architecture "
                "separates social, messaging, OTT and break-return "
                "regulation through SINE, MINE, COSINE, SECANT and COSECANT, while "
                "the Science Lab preserves evidence surrounding "
                "intervention, return and recovery where those events can "
                "be certified."
            )
        )
        layout.addWidget(
            _paragraph(
                "Its potential scientific value lies in making the "
                "trajectory from digital drift through intervention and "
                "behavioral return experimentally observable while "
                "maintaining explicit boundaries between measured behavior, "
                "interpretation and future hypotheses.",
                role="muted",
            )
        )
        layout.addWidget(
            _paragraph(
                "Future development through MYELIN Intelligence (Mi) could "
                "extend this framework toward longitudinal, "
                "context-sensitive and policy-constrained guidance, "
                "including situations where the appropriate recommendation "
                "is not greater productivity but a break, session "
                "termination or rest. Mi remains a future concept and would "
                "require implementation, validation and controlled study "
                "before claims of benefit could be made.",
                role="muted",
            )
        )

        return frame

    def _build_final_research_position(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapterCentralQuestion")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        eyebrow = QLabel("FINAL RESEARCH POSITION")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.2))
        layout.addWidget(eyebrow)

        statement = QLabel(
            "MYELIN should be judged not by whether it can generate more "
            "numbers, but by whether the evidence it records can support "
            "reproducible questions about digital distraction, "
            "intervention and recovery."
        )
        statement.setWordWrap(True)
        _allow_shrink(statement)
        statement.setFont(make_font(14, 700))
        layout.addWidget(statement)

        note = _paragraph(
            "The next scientific step is controlled validation: determine "
            "whether MYELIN-assisted regulation produces measurably "
            "different recovery behavior from appropriate comparison "
            "conditions.",
            role="muted",
            size=10.5,
        )
        layout.addWidget(note)

        return frame


__all__ = ["Chapter6ConclusionView"]
