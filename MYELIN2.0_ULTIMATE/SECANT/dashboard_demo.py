"""DUMMY_UI_ONLY / NOT_REAL_EVIDENCE / ASTRA_WIRING_PENDING.

Literal presentation specimens for the SECANT + COSECANT dashboard.
This module has no persistence, runtime, clock, or physiology imports.
"""

OVERVIEW_METRICS = (
    ("CAPTURED EPISODES", "38", "Total distraction episodes"),
    ("VERIFIED RETURNS", "33", "Successful return verifications"),
    ("INTERRUPTED RECOVERIES", "7", "Recoveries interrupted"),
    ("STUDY RESOURCES", "12", "Total study-aligned resources"),
    ("DIRECT STUDY JUMPS", "9", "Directly observed Study → Study transitions"),
    ("TOTAL STUDY TIME", "2h 14m", "Across study resources"),
)
DISTRACTION_METRICS = OVERVIEW_METRICS[:3] + (("DISTRACTION SOURCES", "12", "Unique recorded sources"),)
STUDY_METRICS = OVERVIEW_METRICS[3:] + (("CONFIRMED UNCERTAIN RESOURCES", "4", "Later confirmed study-aligned"),)
COSECANT_METRICS = (
    ("RECORDED BREAKS", "25", "Break starts recorded"),
    ("COMPLETED ALLOWANCES", "21", "Selected allowances completed"),
    ("CONFIRMED RETURNS", "18", "Returns confirmed"),
    ("CANCELLED BREAKS", "3", "Break cancellations recorded"),
)

RECENT_EPISODE = (
    ("Episode ID", "SEC-27092026-01"),
    ("Distraction Source", "Instagram"),
    ("Stage Reached", "SECANT-2"),
    ("Closure", "Return verified"),
    ("Recorded At", "26 Sep 2026 · 21:14:22"),
    ("Current study material", "Neural Engineering Lecture 04"),
)
LANDING_STATUS = ("●  EPISODE", "No active SECANT episode", "INACTIVE", "red")
LANDING_RECENT_BADGES = ("CLOSED", "VERIFIED")
LANDING_BEHAVIOUR = (
    "Instagram", "instagram", "Stage reached: SECANT-2",
    "Return verified · Neural Engineering Lecture 04",
)
STUDY_SNAPSHOT = (
    ("Primary resource", "Neural Engineering Lecture 04"),
    ("Later resource", "Operating Systems — Process Scheduling"),
    ("Confirmed uncertain resources", "4"),
    ("Observed study path", "Study-aligned only"),
    ("Distraction videos", "Excluded"),
)
LATEST_SECANT_EVENTS = (
    ("1", "21:14:22", "Distraction detected", "Instagram", "Observed"),
    ("2", "21:16:08", "SECANT-1 displayed", "Instagram", "Observed"),
    ("3", "21:20:12", "Return intent recorded", "Chrome", "Derived"),
    ("4", "21:22:40", "Return verification started", "Chrome", "Observed"),
    ("5", "21:26:24", "Return verification completed", "Study resource", "Derived"),
)
OVERVIEW_INSIGHTS = (
    ("Most recent return verified", "Episode SEC-27092026-01 ended with a recorded verification."),
    ("YouTube interruption appears in history", "A YouTube distraction is present in the demo episodes."),
    ("Study jump chain contains 5 resources", "The demo chain includes five study-aligned resources."),
    ("Uncertain resources stay separate", "Unmatched resources are excluded from the study jump chain."),
)
EPISODES = (
    ("1", "SEC-27092026-01", "Instagram", "SECANT-2", "Return verified", "26 Sep 2026 · 21:14:22"),
    ("2", "SEC-26092026-05", "WhatsApp", "SECANT-1", "Closed", "26 Sep 2026 · 20:45:11"),
    ("3", "SEC-26092026-04", "YouTube", "SECANT-3", "Interrupted", "26 Sep 2026 · 19:58:40"),
    ("4", "SEC-26092026-03", "Facebook", "SECANT-2", "Return verified", "26 Sep 2026 · 18:51:03"),
    ("5", "SEC-26092026-02", "Instagram", "SECANT-1", "Closed", "26 Sep 2026 · 17:32:16"),
)
DISTRACTION_HISTORY = (
    ("1", "Instagram", "26 Sep 2026 · 21:14:22", "SECANT-2", "21:16:08", "Yes", "Returned after intent"),
    ("2", "WhatsApp", "26 Sep 2026 · 20:43:11", "SECANT-1", "20:47:25", "Yes", "Closed normally"),
    ("3", "YouTube", "26 Sep 2026 · 19:58:40", "SECANT-3", "20:01:12", "No", "Interrupted (OTT)"),
    ("4", "Facebook", "26 Sep 2026 · 18:51:03", "SECANT-2", "18:53:40", "Yes", "Returned after intent"),
    ("5", "Telegram", "26 Sep 2026 · 17:02:17", "SECANT-1", "17:05:33", "Yes", "Return verified"),
    ("6", "Chrome", "26 Sep 2026 · 15:26:09", "SECANT-2", "15:32:18", "No", "Session stopped"),
)
DISTRACTION_ATTRIBUTES = (
    ("Distraction Source", "Instagram"), ("Return Intent", "Recorded · 21:20:12"),
    ("Return Verified", "Confirmed · 21:28:24"), ("Stage Reached", "SECANT-2"),
    ("Closure", "Session complete · 21:28:36"), ("Outcome scope", "Behavioural only"),
    ("Recovery Interruption", "External trigger · 21:24:32"),
    ("Recorded At", "26 Sep 2026 · 21:14:22"),
)
STUDY_HISTORY = (
    ("1", "Neural Engineering Lecture 04", "18m 24s", "20:14:08", "20:32:50", "Primary resource"),
    ("2", "Operating Systems — Process Scheduling", "12m 11s", "20:33:14", "20:45:25", "Later resource"),
    ("3", "DBMS Lecture Slides", "09m 58s", "20:46:02", "20:56:00", "Confirmed study-aligned"),
    ("4", "Computer Networks — Notes", "15m 07s", "20:56:31", "21:11:38", "Confirmed study-aligned"),
    ("5", "Signals and Systems — Revision Video", "07m 49s", "21:12:02", "21:19:51", "Later resource"),
)
STUDY_EVIDENCE = (
    ("1", "Neural Engineering Lecture 04", "STUDY ALIGNED", "100%", "None", "PRIMARY"),
    ("2", "Operating Systems Notes", "STUDY ALIGNED", "78%", "None", "LATER"),
    ("3", "Machine Learning Textbook", "DISTRACTION", "50%", "None", "Not qualified"),
    ("4", "DBMS Lecture Slides", "UNCERTAIN", "72%", "Confirmed", "LATER"),
    ("5", "Computer Networks — Video", "UNCERTAIN", "65%", "None", "Not qualified"),
    ("6", "Signals and Systems Revision", "STUDY ALIGNED", "81%", "None", "LATER"),
)
EVIDENCE_ATTRIBUTES = (
    ("Resource", "DBMS Lecture Slides"), ("Initial Classification", "UNCERTAIN"),
    ("Initial Confidence", "72%"), ("User Confirmation", "Confirmed"),
    ("Effective Classification", "STUDY ALIGNED"),
    ("Effective Confidence", "Not recorded"), ("Qualification", "LATER"),
    ("Evidence scope", "Behavioural only"),
)

# Each flow node is (category, title, detail, timestamp, tone, gap-to-next).
SECANT_FLOW = (
    ("DISTRACTION", "Instagram", "Distraction detected", "21:14:22", "neutral", "1m 46s"),
    ("SECANT-1", "Intervention", "Displayed", "21:16:08", "blue", "4m 04s"),
    ("RETURN INTENT", "User indication", "Recorded", "21:20:12", "green", "2m 28s"),
    ("RETURN PROCESS", "Verification", "Started", "21:22:40", "green", "1m 52s"),
    ("INTERRUPTED", "External trigger", "Recorded", "21:24:32", "yellow", "1m 56s"),
    ("SECANT-2", "Re-orientation", "Displayed", "21:26:28", "amber", "1m 56s"),
    ("RETURN VERIFIED", "Study resource", "Confirmation recorded", "21:28:24", "green", "12s"),
    ("EPISODE CLOSED", "Session complete", "Closure recorded", "21:28:36", "neutral", ""),
)
STUDY_FLOW = (
    # Connector captions are curated facts between these Study nodes, not elapsed-time calculations.
    ("PRIMARY RESOURCE", "Neural Engineering Lecture 04", "Study-aligned", "20:14:08–20:32:50", "green", "Direct observed change"),
    ("LATER RESOURCE", "Operating Systems — Process Scheduling", "Study-aligned", "20:33:14–20:45:25", "blue", "Direct observed change"),
    ("LATER RESOURCE", "DBMS Lecture Slides", "Initially uncertain · later confirmed", "20:46:02–20:56:00", "teal", "Evidence gap"),
    ("STUDY-ALIGNED", "Computer Networks — Notes", "Study-aligned", "20:56:31–21:11:38", "teal", "Interruption recorded"),
    ("LATER RESOURCE", "Signals and Systems — Revision Video", "Study-aligned", "21:12:02–21:19:51", "blue", ""),
)
CONFIRMATION_FLOW = (
    ("PRIMARY RESOURCE", "Neural Engineering Lecture 04", "Accepted", "20:14:08", "green", "31s"),
    ("LATER RESOURCE", "Operating Systems — Process Scheduling", "Accepted", "20:33:14", "blue", "44s"),
    ("UNCERTAIN RESOURCE", "DBMS Lecture Slides", "Awaited confirmation", "20:46:02", "amber", "User confirmed"),
    ("STUDY-ALIGNED", "DBMS Lecture Slides", "Confirmation recorded", "20:56:31", "green", "28s"),
    ("UNCERTAIN RESOURCE", "Computer Networks — Video", "Not matched", "21:12:02", "amber", "Not matched"),
    ("EXCLUDED", "Not in study chain", "Evidence not carried forward", "21:19:51", "red", ""),
)
COSECANT_BREAK = (
    ("BREAK ID", "COSEC-27092026-01"),
    ("LAST RECORDED STATE", "Return Confirmation Started"),
    ("BREAK TYPE", "User-requested break"), ("SELECTED ALLOWANCE", "10 min"),
    ("RETURN TARGET", "Operating Systems Notes"), ("OUTCOME", "In progress"),
)
RECENT_BREAK = (
    ("Break ID", "COSEC-26092026-01"), ("Selected Allowance", "5 min"),
    ("Return Target", "Title not recorded · browser resource"),
    ("Return Confirmation", "Confirmed · 22:04:18"),
    ("Outcome", "Returned"), ("Recorded At", "26 Sep 2026 · 21:57:02"),
)
BREAK_HISTORY = (
    ("Break ID", "COSEC-25092026-01"),
    ("Break Type", "User-requested break"),
    ("Selected Allowance", "15 min"),
    ("Return Target", "Signals and Systems Notes"),
    ("Allowance Status", "Cancelled"),
    ("Return Status", "None"),
    ("Outcome", "Break Cancelled"),
)
COSECANT_EVENTS = (
    ("Return Selected", "User action", "22:02:20"),
    ("Return Confirmation Started", "Recorded", "22:03:50"),
    ("Return Confirmation Interrupted", "Recorded", "22:04:00"),
    ("Final Return Reminder", "State", "22:04:08"),
    ("Return Confirmed", "Recorded", "22:04:18"),
)
RETURN_HISTORY = (
    # The target is known; this specimen's return projection cannot be validated by the reader.
    ("Operating Systems Notes", "Unavailable", "Unavailable", "Unavailable"),
    ("Title not recorded", "22:04:18", "Confirmed", "Returned"),
    ("DBMS Lecture Slides", "None", "Interrupted", "In progress"),
    ("Signals and Systems Notes", "None", "None", "Break Cancelled"),
    ("Neural Engineering Lecture 04", "09:41:00", "Confirmed", "Returned"),
)
COSECANT_FLOW = (
    ("BREAK", "Started", "5 min selected", "21:57:02", "purple", "5m 00s"),
    ("BREAK ALLOWANCE", "Complete", "5 min selected", "22:02:02", "yellow", "18s"),
    ("RETURN", "Selected", "Title not recorded", "22:02:20", "green", "1m 30s"),
    ("RETURN CONFIRMATION", "Started", "Target evidence", "22:03:50", "green", "10s"),
    ("RETURN CONFIRMATION", "Interrupted", "Evidence lost", "22:04:00", "yellow", "8s"),
    ("FINAL RETURN", "Reminder", "State recorded", "22:04:08", "yellow", "10s"),
    ("RETURN", "Confirmed", "Return evidence", "22:04:18", "green", ""),
)


# DUMMY_HISTORY_ONLY
# STATIC_DATE_FILTER_ONLY
# NOT_REAL_EVIDENCE
# ASTRA_WIRING_PENDING
# Literal specimens for the contextual archive browsers; no persistence.
DEMO_SECANT_EPISODE_ARCHIVE = (
    {
        "episode_id": "SEC-26092026-05", "display_episode_id": "SEC-26092026-05", "source": "Instagram",
        "started": "26 Sep 2026 · 18:12:05", "stage": "SECANT-1",
        "outcome": "Return verified", "return_intent": "Recorded · 18:13:08",
        "verification": "Confirmed · 18:15:02", "interruption": "None recorded",
        "closure": "Returned after intent · 18:15:11",
        "study_resource": "Neural Engineering Lecture 03",
        "events": (
            ("1", "18:12:05", "Distraction detected", "Instagram", "Observed"),
            ("2", "18:12:17", "SECANT-1 displayed", "Instagram", "Observed"),
            ("3", "18:13:08", "Return intent recorded", "User", "Derived"),
            ("4", "18:13:26", "Return verification started", "Study resource", "Observed"),
            ("5", "18:15:02", "Return verified", "Study resource", "Derived"),
            ("6", "18:15:11", "Episode closed", "SECANT", "Derived"),
        ),
        "map_nodes": (
            ("DISTRACTION", "Instagram", "Detected", "18:12:05", "neutral", "12s"),
            ("SECANT-1", "Attention shift", "Displayed", "18:12:17", "blue", "51s"),
            ("RETURN INTENT", "User signal", "Recorded", "18:13:08", "green", "18s"),
            ("RETURN PROCESS", "Study resource", "Verification started", "18:13:26", "green", "1m 36s"),
            ("RETURN VERIFIED", "Study resumed", "Confirmed", "18:15:02", "green", "9s"),
            ("EPISODE CLOSED", "Returned after intent", "Return verified", "18:15:11", "green", ""),
        ),
    },
    {
        "episode_id": "SEC-26092026-04", "display_episode_id": "SEC-26092026-04", "source": "YouTube",
        "started": "26 Sep 2026 · 19:58:40", "stage": "SECANT-2",
        "outcome": "Return verified", "return_intent": "Recorded · 20:01:12",
        "verification": "Confirmed · 20:08:24",
        "interruption": "OTT trigger · 20:04:00",
        "closure": "Returned after interruption · 20:08:36",
        "study_resource": "Operating Systems Notes",
        "events": (
            ("1", "19:58:40", "Distraction detected", "YouTube", "Observed"),
            ("2", "19:59:22", "SECANT-1 displayed", "YouTube", "Observed"),
            ("3", "20:01:12", "Return intent recorded", "User", "Derived"),
            ("4", "20:01:47", "Return verification started", "Study resource", "Observed"),
            ("5", "20:04:00", "Recovery interrupted", "OTT trigger", "Observed"),
            ("6", "20:04:58", "SECANT-2 displayed", "SECANT", "Observed"),
            ("7", "20:08:24", "Return verified", "Study resource", "Derived"),
            ("8", "20:08:36", "Episode closed", "SECANT", "Derived"),
        ),
        "map_nodes": (
            ("DISTRACTION", "YouTube", "Detected", "19:58:40", "neutral", "42s"),
            ("SECANT-1", "Attention shift", "Displayed", "19:59:22", "blue", "1m 50s"),
            ("RETURN INTENT", "User signal", "Recorded", "20:01:12", "green", "35s"),
            ("RETURN PROCESS", "Study resource", "Verification started", "20:01:47", "green", "2m 13s"),
            ("INTERRUPTED", "OTT trigger", "Recorded", "20:04:00", "yellow", "58s"),
            ("SECANT-2", "Re-orientation", "Displayed", "20:04:58", "amber", "3m 26s"),
            ("RETURN VERIFIED", "Study resumed", "Confirmed", "20:08:24", "green", "12s"),
            ("EPISODE CLOSED", "Returned", "Return verified", "20:08:36", "green", ""),
        ),
    },
    {
        "episode_id": "SEC-25092026-02", "display_episode_id": "SEC-25092026-02", "source": "WhatsApp",
        "started": "25 Sep 2026 · 20:43:11", "stage": "SECANT-3",
        "outcome": "Return verified", "return_intent": "Recorded · 20:45:06",
        "verification": "Confirmed · 20:55:21",
        "interruption": "Recovery interrupted · 20:48:04",
        "closure": "Returned after SECANT-3 · 20:55:30",
        "study_resource": "DBMS Lecture Slides",
        "events": (
            ("1", "20:43:11", "Distraction detected", "WhatsApp", "Observed"),
            ("2", "20:43:39", "SECANT-1 displayed", "WhatsApp", "Observed"),
            ("3", "20:44:32", "SECANT-2 displayed", "SECANT", "Observed"),
            ("4", "20:45:06", "Return intent recorded", "User", "Derived"),
            ("5", "20:47:25", "Recovery attempt started", "Study resource", "Observed"),
            ("6", "20:48:04", "Recovery interrupted", "WhatsApp", "Observed"),
            ("7", "20:50:10", "SECANT-3 displayed", "SECANT", "Observed"),
            ("8", "20:55:21", "Return verified", "Study resource", "Derived"),
            ("9", "20:55:30", "Episode closed", "SECANT", "Derived"),
        ),
        "map_nodes": (
            ("DISTRACTION", "WhatsApp", "Detected", "20:43:11", "neutral", "28s"),
            ("SECANT-1", "Attention shift", "Displayed", "20:43:39", "blue", "53s"),
            ("SECANT-2", "Re-orientation", "Displayed", "20:44:32", "amber", "34s"),
            ("RETURN INTENT", "User signal", "Recorded", "20:45:06", "green", "2m 19s"),
            ("RECOVERY ATTEMPT", "DBMS slides", "Started", "20:47:25", "green", "39s"),
            ("INTERRUPTED", "WhatsApp", "Recorded", "20:48:04", "yellow", "2m 06s"),
            ("SECANT-3", "Final re-orientation", "Displayed", "20:50:10", "red", "5m 11s"),
            ("RETURN VERIFIED", "Study resumed", "Confirmed", "20:55:21", "green", "9s"),
            ("EPISODE CLOSED", "Returned", "Return verified", "20:55:30", "green", ""),
        ),
    },
    {
        "episode_id": "SEC-24092026-01", "display_episode_id": "SEC-24092026-01", "source": "Facebook",
        "started": "24 Sep 2026 · 18:51:03", "stage": "SECANT-1",
        "outcome": "Session stopped", "return_intent": "Recorded · 18:53:40",
        "verification": "Not recorded", "interruption": "None recorded",
        "closure": "Session stopped · 18:54:30",
        "study_resource": "None confirmed",
        "events": (
            ("1", "18:51:03", "Distraction detected", "Facebook", "Observed"),
            ("2", "18:51:26", "SECANT-1 displayed", "Facebook", "Observed"),
            ("3", "18:53:40", "Return intent recorded", "User", "Derived"),
            ("4", "18:54:24", "Session stopped", "User", "Observed"),
            ("5", "18:54:30", "Episode closed", "SECANT", "Derived"),
        ),
        "map_nodes": (
            ("DISTRACTION", "Facebook", "Detected", "18:51:03", "neutral", "23s"),
            ("SECANT-1", "Attention shift", "Displayed", "18:51:26", "blue", "2m 14s"),
            ("RETURN INTENT", "User signal", "Recorded", "18:53:40", "green", "44s"),
            ("SESSION STOPPED", "User action", "Recorded", "18:54:24", "yellow", "6s"),
            ("EPISODE CLOSED", "No verification", "Session stopped", "18:54:30", "neutral", ""),
        ),
    },
)

DEMO_STUDY_SESSION_ARCHIVE = (
    # Each jump_nodes connector caption is a supplied fixture fact, never inferred from timestamps.
    {
        "demo_key": "demo_study_001", "date": "27 Sep 2026",
        "title": "Neural Engineering", "duration": "58m", "direct_study_jumps": "2",
        "started": "20:14:08", "ended": "21:12:08",
        "primary": "Neural Engineering Lecture 04",
        "resources": (
            ("1", "Neural Engineering Lecture 04", "18m 24s", "20:14:08", "20:32:50", "Primary resource"),
            ("2", "Operating Systems — Process Scheduling", "12m 11s", "20:33:14", "20:45:25", "Later resource"),
            ("3", "DBMS Lecture Slides", "09m 58s", "20:46:02", "20:56:00", "Initially uncertain → confirmed"),
            ("4", "Computer Networks — Notes", "15m 07s", "20:56:31", "21:11:38", "Study-aligned"),
            ("5", "Computer Networks — Video", "Single observation", "21:11:38", "21:11:38", "Uncertain · excluded"),
        ),
        "evidence": (
            ("1", "Neural Engineering Lecture 04", "Study-aligned", "Primary", "Matched"),
            ("2", "Operating Systems — Process Scheduling", "Study-aligned", "Later", "Matched"),
            ("3", "DBMS Lecture Slides", "Uncertain", "Confirmed study-aligned", "User confirmed"),
            ("4", "Computer Networks — Notes", "Study-aligned", "Confirmed", "Matched"),
            ("5", "Computer Networks — Video", "Uncertain", "Excluded", "Not matched"),
        ),
        "events": (
            ("1", "20:14:08", "Session started", "Observed"),
            ("2", "20:33:14", "Study resource changed", "Observed"),
            ("3", "20:46:02", "Uncertain resource opened", "Observed"),
            ("4", "20:56:00", "DBMS resource confirmed", "User action"),
            ("5", "20:56:31", "Study resource changed", "Observed"),
            ("6", "21:12:08", "Session ended", "Observed"),
        ),
        "jump_nodes": (
            ("PRIMARY RESOURCE", "Neural Engineering Lecture 04", "Study-aligned", "20:14:08", "green", "Direct observed change"),
            ("LATER RESOURCE", "Operating Systems — Process Scheduling", "Study-aligned", "20:33:14", "blue", "Evidence gap"),
            ("LATER RESOURCE", "DBMS Lecture Slides", "Initially uncertain · later confirmed", "20:46:02", "teal", "Direct observed change"),
            ("STUDY-ALIGNED", "Computer Networks — Notes", "Confirmed", "20:56:31", "teal", ""),
        ),
    },
    {
        "demo_key": "demo_study_002", "date": "26 Sep 2026",
        "title": "Signals and Systems", "duration": "46m", "direct_study_jumps": "1",
        "started": "16:00:00", "ended": "16:46:00",
        "primary": "Signals and Systems Revision",
        "resources": (
            ("1", "Signals and Systems Revision", "19m 18s", "16:00:00", "16:19:18", "Primary resource"),
            ("2", "Fourier Transform Notes", "13m 07s", "16:19:42", "16:32:49", "Initially uncertain → confirmed"),
            ("3", "Control Systems Lecture", "12m 40s", "16:33:20", "16:46:00", "Later resource"),
        ),
        "evidence": (
            ("1", "Signals and Systems Revision", "Study-aligned", "Primary", "Matched"),
            ("2", "Fourier Transform Notes", "Uncertain", "Confirmed study-aligned", "User confirmed"),
            ("3", "Control Systems Lecture", "Study-aligned", "Later", "Matched"),
        ),
        "events": (
            ("1", "16:00:00", "Session started", "Observed"),
            ("2", "16:19:42", "Fourier notes opened", "Observed"),
            ("3", "16:32:49", "Fourier notes confirmed", "User action"),
            ("4", "16:33:20", "Control Systems lecture opened", "Observed"),
            ("5", "16:46:00", "Session ended", "Observed"),
        ),
        "jump_nodes": (
            ("PRIMARY RESOURCE", "Signals and Systems Revision", "Study-aligned", "16:00:00", "green", "Direct observed change"),
            ("LATER RESOURCE", "Fourier Transform Notes", "Initially uncertain · later confirmed", "16:19:42", "teal", "Interruption recorded"),
            ("LATER RESOURCE", "Control Systems Lecture", "Study-aligned", "16:33:20", "blue", ""),
        ),
    },
    {
        "demo_key": "demo_study_003", "date": "25 Sep 2026",
        "title": "Biomedical Instrumentation", "duration": "1h 07m", "direct_study_jumps": "1",
        "started": "14:00:00", "ended": "15:07:00",
        "primary": "Biomedical Instrumentation",
        "resources": (
            ("1", "Biomedical Instrumentation", "24m 11s", "14:00:00", "14:24:11", "Primary resource"),
            ("2", "ECG Signal Processing", "21m 30s", "14:24:50", "14:46:20", "Later resource"),
            ("3", "BioAmp EXG Notes", "20m 05s", "14:46:55", "15:07:00", "Initially uncertain → confirmed"),
        ),
        "evidence": (
            ("1", "Biomedical Instrumentation", "Study-aligned", "Primary", "Matched"),
            ("2", "ECG Signal Processing", "Study-aligned", "Later", "Matched"),
            ("3", "BioAmp EXG Notes", "Uncertain", "Confirmed study-aligned", "User confirmed"),
        ),
        "events": (
            ("1", "14:00:00", "Session started", "Observed"),
            ("2", "14:24:50", "ECG resource opened", "Observed"),
            ("3", "14:46:55", "Uncertain notes opened", "Observed"),
            ("4", "15:06:42", "BioAmp notes confirmed", "User action"),
            ("5", "15:07:00", "Session ended", "Observed"),
        ),
        "jump_nodes": (
            ("PRIMARY RESOURCE", "Biomedical Instrumentation", "Study-aligned", "14:00:00", "green", "Evidence gap"),
            ("LATER RESOURCE", "ECG Signal Processing", "Study-aligned", "14:24:50", "blue", "Direct observed change"),
            ("LATER RESOURCE", "BioAmp EXG Notes", "Initially uncertain · later confirmed", "14:46:55", "teal", ""),
        ),
    },
    {
        "demo_key": "demo_study_004", "date": "24 Sep 2026",
        "title": "Machine Learning", "duration": "1h 24m", "direct_study_jumps": "2",
        "started": "17:00:00", "ended": "18:24:00",
        "primary": "Machine Learning Lecture",
        "resources": (
            ("1", "Machine Learning Lecture", "31m 20s", "17:00:00", "17:31:20", "Primary resource"),
            ("2", "Python Notebook", "25m 30s", "17:32:04", "17:57:34", "Later resource"),
            ("3", "Classification Notes", "24m 46s", "17:58:25", "18:23:11", "Study-aligned"),
            ("4", "Suggested Video", "Not recorded", "18:23:11", "Not recorded", "Uncertain · excluded"),
        ),
        "evidence": (
            ("1", "Machine Learning Lecture", "Study-aligned", "Primary", "Matched"),
            ("2", "Python Notebook", "Study-aligned", "Later", "Matched"),
            ("3", "Classification Notes", "Study-aligned", "Confirmed", "Matched"),
            ("4", "Suggested Video", "Uncertain", "Excluded", "Not matched"),
        ),
        "events": (
            ("1", "17:00:00", "Session started", "Observed"),
            ("2", "17:32:04", "Notebook opened", "Observed"),
            ("3", "17:58:25", "Classification notes opened", "Observed"),
            ("4", "18:23:11", "Unmatched video opened", "Observed"),
            ("5", "18:24:00", "Session ended", "Observed"),
        ),
        "jump_nodes": (
            ("PRIMARY RESOURCE", "Machine Learning Lecture", "Study-aligned", "17:00:00", "green", "Direct observed change"),
            ("LATER RESOURCE", "Python Notebook", "Study-aligned", "17:32:04", "blue", "Direct observed change"),
            ("STUDY-ALIGNED", "Classification Notes", "Confirmed", "17:58:25", "teal", ""),
        ),
    },
)
