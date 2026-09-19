"""Chapter structure and static content for the MYELIN Science Lab.

Pure data.  No Qt, no database, no engine, no report logic belongs here --
``lab.py`` reads these records to build the chapter drawer and the Coming
Soon / Reserved pages.  Chapter 1's own card-by-card prose stays inside its
builder methods in ``lab.py`` (moved verbatim from the pre-extraction
``ScienceLabPage``); it is interleaved with widget construction closely
enough that lifting it into pure data here would be a rewrite, not a move,
and Phase B is extraction only.
"""

from __future__ import annotations

from typing import Final

#: Frozen chapter numbering (Chapter 1 dummy-UI spec section 4).  Chapter 4
#: is intentionally reserved for future SenseHub / MYELIN Edge evidence --
#: the gap must never be renumbered away.
CHAPTER_DEFINITIONS: Final = (
    {"key": "chapter_1", "number": "01", "title": "Chapter 1", "subtitle": "Purpose & Introduction", "state": "normal"},
    {"key": "chapter_2", "number": "02", "title": "Chapter 2", "subtitle": "Parts of MYELIN", "state": "normal"},
    {"key": "chapter_3", "number": "03", "title": "Chapter 3", "subtitle": "Data Analysis", "state": "normal"},
    {"key": "chapter_4", "number": "04", "title": "Chapter 4", "subtitle": "Reserved for SenseHub / MYELIN Edge", "state": "reserved"},
    {"key": "chapter_5", "number": "05", "title": "Chapter 5", "subtitle": "Results & Discussion", "state": "normal"},
    {"key": "chapter_6", "number": "06", "title": "Chapter 6", "subtitle": "Conclusion & Future Scope", "state": "normal"},
)

#: Coming Soon page copy for chapter 6.  Chapter 2 has its own real page
#: (SCIENCE_LAB.schematics.ChapterTwoOrganViewer); Chapter 3 has its own
#: real page (SCIENCE_LAB.chapter3_view.Chapter3TimelineView); Chapter 5
#: has its own real page (SCIENCE_LAB.chapter5_view.Chapter5ResultsView).
COMING_SOON_CONTENT: Final = {
    "chapter_6": {
        "chapter_label": "CHAPTER 6",
        "title": "CONCLUSION & FUTURE SCOPE",
        "body_text": "This chapter will summarise the findings and describe future directions for MYELIN.",
        "secondary_text": "",
    },
}

#: Reserved page copy for Chapter 4.
RESERVED_CHAPTER_CONTENT: Final = {
    "chapter_label": "CHAPTER 4",
    "title": "SENSEHUB / MYELIN EDGE",
    "body_text": "This chapter is reserved for future hardware and physiological evidence.",
    "note_text": "No physiological data is simulated in the current Science Lab version.",
}

#: Chapter 2's own organ selector (Chapter 2 Phase 1: four-organ selector +
#: SINE living schematic).  Pure data -- no Qt object belongs here.
#: ``state`` is "ready" (a real schematic exists) or "coming_soon"
#: (selectable placeholder pane).  Order is frozen: SINE, MINE, COSINE,
#: COSECANT.
CHAPTER_TWO_ORGANS: Final = (
    {
        "key": "sine",
        "title": "SINE",
        "subtitle": "Soft Intervention Nudge Escalation",
        "state": "ready",
    },
    {
        "key": "mine",
        "title": "MINE",
        "subtitle": "Messaging Intervention Nudge Escalation",
        "state": "ready",
    },
    {
        "key": "cosine",
        "title": "COSINE",
        "subtitle": "OTT / streaming intervention",
        "state": "ready",
    },
    {
        "key": "cosecant",
        "title": "COSECANT",
        "subtitle": "Study-break return regulation",
        "state": "ready",
    },
)


#: SINE facts verified directly against SINE/sine.py and SINE/popup.py
#: (Chapter 2 Phase 1 forensic audit) -- presentation copy only, never
#: imported from the SINE runtime itself.
SINE_STAGE_FACTS: Final = {
    "sine_1": {
        "label": "SINE 1",
        "accent": "#3DDCFF",
        "headline": "Cognitive Drift Detected",
        "message": "The current resource reached its intervention threshold.",
        "buttons": ("I'M BACK", "NEED A BREAK"),
        "display_seconds": 45,
    },
    "sine_2": {
        "label": "SINE 2",
        "accent": "#F5A623",
        "headline": "Still Here?",
        "message": (
            "You stepped away for a moment, but the loop pulled you back. "
            "Your focus window is still open."
        ),
        "buttons": ("I'M BACK NOW",),
        "display_seconds": 60,
    },
    "sine_3": {
        "label": "SINE 3 · PROTECTED",
        "accent": "#FF4D6D",
        "headline": "Long Drift Detected",
        "message": "NO BUTTONS · AWAITING VERIFIED FOCUS RETURN",
        "buttons": (),
        "display_seconds": 600,
    },
    "break_gate": {
        "label": "WELCOME BACK",
        "accent": "#39D98A",
        "headline": "Welcome back.",
        "message": "Not a SINE stage. Confirms return after a Normal Break.",
        "buttons": ("I'M BACK",),
        "display_seconds": None,
    },
}

#: Baseline escalation windows (SinePolicy in SINE/sine.py).  F is MYELIN's
#: approved session personalization factor, supplied upstream; SINE does
#: not compute it.  Shown as labels only -- Chapter 2 never recalculates it.
SINE_TIMING_FACTS: Final = {
    "stage_1_to_2_baseline": "10:00",
    "stage_2_to_3_baseline": "13:15",
    "f_tooltip": (
        "F is MYELIN's approved session personalization factor. SINE "
        "consumes the value supplied by the upstream behavioural timing "
        "model. If no valid learned factor exists, F = 1.0."
    ),
}

#: MINE facts verified directly against MINE/mine.py and MINE/popup.py
#: (Chapter 2 Phase 2 forensic audit) -- presentation copy only, never
#: imported from the MINE runtime itself.  MINE-1's two branches share one
#: card (the runtime turns the same window into a duration-entry view
#: rather than opening a second popup); MINE-2 has two headline variants
#: and never has buttons.
MINE_STAGE_FACTS: Final = {
    "mine_1": {
        "label": "MINE-1",
        "accent": "#F5A623",
        "headline": "IT SEEMS YOU HAVE STARTED USING A MESSAGING APP",
        "message": "BUT YOU HAVE IMPORTANT WORK — RETURN IF THIS IS NOT IMPORTANT.",
        "buttons": ("I WILL COME BACK", "IT'S IMPORTANT"),
    },
    "mine_1_duration": {
        "label": "IT'S IMPORTANT",
        "accent": "#F5A623",
        "headline": "HOW MANY WHOLE MINUTES DO YOU NEED?",
        "message": "ENTER ANY VALUE FROM 5 THROUGH 30.",
        "buttons": ("SET IMPORTANT TIME",),
    },
    "mine_2a": {
        "label": "MINE-2A",
        "accent": "#FF4D6D",
        "headline": "YOU SAID YOU WOULD COME BACK",
        "message": "YOUR IMPORTANT WORK IS WAITING.",
        "buttons": (),
    },
    "mine_2b": {
        "label": "MINE-2B",
        "accent": "#FF4D6D",
        "headline": "YOUR IMPORTANT MESSAGING TIME IS OVER",
        "message": "IT IS TIME TO RETURN.",
        "buttons": (),
    },
}

#: MinePolicy timing constants (MINE/mine.py) -- frozen, display-only.
MINE_TIMING_FACTS: Final = {
    "initial_gate": "10:00",
    "return_intent_window": "13:15",
    "continuous_total": "23:15",
    "important_minutes_min": 5,
    "important_minutes_max": 30,
    "final_callback_hide_seconds": 3,
    "return_verification_seconds": 10,
    "closure_confirmation_seconds": 60,
}

#: Branch/boundary facts (MINE/mine.py) that Chapter 2 must teach
#: correctly: MINE owns its own recovery sequence (never MIRL); neutral
#: detours pause the post-MINE-1 clock rather than resetting it; Study Mode
#: outranks MINE; Global Pause freezes MINE's effective clock.
MINE_BRANCH_FACTS: Final = {
    "neutral_pause_note": "Pauses. Does not reset.",
    "platform_switch_note": "Messaging platform switches remain inside the same MINE episode.",
    "early_return_note": "Returning early can begin recovery before MINE-2.",
    "recovery_owner_note": "MINE owns its own return-confirmation sequence. Recovery is not MIRL.",
    "relapse_note": "A relapse during recovery restores the same MINE-2 callback -- it does not create a new one.",
    "study_preemption_note": "Study Mode has higher authority and can preempt MINE.",
    "global_pause_note": "Global Pause freezes MINE's effective clock.",
}

#: The exactly-eight platform families COSINE currently supports
#: (PLATFORM_LABELS in COSINE/cosine.py, Chapter 2 Phase 3 forensic
#: audit).  YouTube is deliberately absent -- it is not in the current
#: platform map.
COSINE_PLATFORM_FACTS: Final = (
    "Netflix",
    "Prime Video",
    "JioHotstar",
    "Disney+",
    "Hulu",
    "HBO Max",
    "Apple TV+",
    "Paramount+",
)

#: CosinePolicy timing constants (COSINE/cosine.py) -- frozen, display-only.
COSINE_TIMING_FACTS: Final = {
    "initial_gate": "5:00",
    "return_intent_window": "5:00",
    "break_minutes_min": 10,
    "break_minutes_max": 200,
    "final_callback_hide_seconds": 3,
    "return_verification_seconds": 10,
    "closure_confirmation_seconds": 60,
}

#: COSINE popup facts verified directly against COSINE/popup.py (Chapter 2
#: Phase 3 forensic audit) -- presentation copy only, never imported from
#: the COSINE runtime itself.  The current architecture is NOT the older
#: 23:15 / "10 MORE MIN" / "FINISH MY SHOW" concept -- those names survive
#: only as legacy compatibility enum values in cosine.py and must not be
#: shown here.
COSINE_POPUP_FACTS: Final = {
    "intention": {
        "label": "INTENTION",
        "accent": "#38BDF8",
        "headline": "IT SEEMS YOU ARE INTERESTED TO WATCH THIS SHOW",
        "message": "",
        "buttons": ("SORRY, I'LL COME BACK", "YEAH, I WANT SOME BREAK"),
    },
    "set_a_limit": {
        "label": "SET A LIMIT",
        "accent": "#38BDF8",
        "headline": "IT SEEMS YOU'D LIKE TO KEEP WATCHING.",
        "message": "LET'S SET A LIMIT.\nI'LL CALL YOU BACK WHEN YOUR BREAK IS OVER.",
        "context": "TRY TO KEEP IT TO ONE EPISODE.",
        "buttons": ("START WATCHING",),
    },
    "break_length": {
        "label": "BREAK LENGTH",
        "accent": "#38BDF8",
        "headline": "HOW LONG WOULD YOU LIKE YOUR BREAK TO BE?",
        "message": "",
        "buttons": ("SET TIME",),
    },
    "break_set": {
        "label": "BREAK SET",
        "accent": "#38BDF8",
        "headline": "ENJOY THE SHOW",
        "message": "I'LL CALL YOU BACK IN",
        "buttons": ("YAY",),
    },
    "final_callback": {
        "label": "FOCUS",
        "accent": "#FF4D6D",
        "headline": "HOPE YOU ENJOYED THE SHOW.",
        "message": "NOW IT'S TIME TO FOCUS.",
        "buttons": (),
    },
}

#: Branch/boundary facts (COSINE/cosine.py) that Chapter 2 must teach
#: correctly: COSINE owns its own recovery sequence; the 3-second hide is
#: a milestone inside the 10-second return verification, not a stacked
#: extra interval; continued OTT after a return intention converts to a
#: duration limit rather than the legacy "10 MORE MIN" popup; platform
#: hops continue the same episode; Study Mode outranks COSINE; Global
#: Pause freezes COSINE's effective clock.
COSINE_BRANCH_FACTS: Final = {
    "return_intent_note": "An intention only -- not verified recovery. A new 5:00 window starts after acceptance.",
    "failed_return_note": "Continued OTT through the new window converts to a break-duration limit, not a legacy \"10 MORE MIN\" popup.",
    "yay_note": "Deadline already exists -- YAY acknowledges the break; it does not extend it.",
    "no_timeout_note": "There is no acknowledgement timeout of any kind.",
    "hide_milestone_note": "The 3-second hide is a milestone inside the 10-second return verification, not an extra interval before it.",
    "hopper_note": "Supported OTT platform switches remain inside the same COSINE episode.",
    "relapse_note": "An OTT relapse during recovery restores the same final callback -- it does not create a new one.",
    "study_preemption_note": "Study Mode has higher authority and can preempt COSINE.",
    "global_pause_note": "Global Pause freezes COSINE's effective clock.",
}

#: CosecantPolicy timing constants (COSECANT_STUDY_MODE/cosecant.py) --
#: frozen, display-only.  The internal 2.2s maximum-presence-gap safety
#: margin is deliberately omitted here (Chapter 2 Phase 4 forensic audit,
#: spec section 30): it is implementation machinery, not a user-facing
#: rule.  The user-facing rule is "3 continuous seconds".
COSECANT_TIMING_FACTS: Final = {
    "already_over_delay": "5:00",
    "final_lock_delay": "1:00",
    "return_confirmation_seconds": 3,
    "break_minimum_seconds": 60,
    "break_maximum_hours": 24,
}

#: COSECANT popup facts verified directly against
#: COSECANT_STUDY_MODE/view.py (Chapter 2 Phase 4 forensic audit) --
#: presentation copy only, never imported from the COSECANT runtime
#: itself.  ``buttons`` is empty for final_lock: the real
#: ContinuityPopup hides its RETURN TO STUDY button whenever
#: ``snapshot.final_locked`` is true (FINAL_LOCK itself, and any
#: RETURN_CONFIRMING that originated from FINAL_LOCK) -- this is a
#: locked invariant, not a presentation choice.
COSECANT_POPUP_FACTS: Final = {
    "break_complete": {
        "label": "BREAK COMPLETE",
        "accent": "#39D98A",
        "headline": "BREAK COMPLETE",
        "message": "Your planned break has ended. Return to your registered Study task.",
        "status": "APPROVED BREAK COMPLETE · RETURN INTENT AVAILABLE",
        "buttons": ("RETURN TO STUDY",),
    },
    "break_already_over": {
        "label": "BREAK ALREADY OVER",
        "accent": "#F5A623",
        "headline": "BREAK ALREADY OVER",
        "message": "Your planned break has been over for five minutes. Return to your registered Study task.",
        "status": "APPROVED BREAK OVERDUE · RETURN INTENT AVAILABLE",
        "buttons": ("RETURN TO STUDY",),
    },
    "final_lock": {
        "label": "FINAL LOCK",
        "accent": "#FF4D6D",
        "headline": "COME BACK PLEASE",
        "message": (
            "Open the exact registered Study resource. This protected notice "
            "closes only after observed return."
        ),
        "status": "FINAL RETURN LOCK · WAITING FOR EXACT RESOURCE",
        "buttons": (),
    },
    "return_confirming": {
        "label": "RETURN DETECTED",
        "accent": "#38BDF8",
        "headline": "RETURN DETECTED",
        "message": "Keep the exact registered Study resource present while COSECANT verifies the return.",
        "status": "FACTUAL RETURN DETECTED · VERIFYING CONTINUITY",
        "buttons": (),
    },
}

#: Branch/boundary facts (COSECANT_STUDY_MODE/cosecant.py,
#: CORE_ENGINE/monitor.py) that Chapter 2 must teach correctly: a button
#: press is intent only, never return evidence; only the exact registered
#: Study resource -- never generic focus -- can release the lock;
#: confirmation requires three CONTINUOUS seconds and breaks on any
#: uncertain/stale/mismatched evidence; the break cannot be admitted until
#: an exact return target is frozen, and Study pauses only after that
#: admission succeeds; COSECANT itself never resumes Study.
COSECANT_BRANCH_FACTS: Final = {
    "exact_target_note": "The exact Study resource is frozen as the return target before the break is admitted.",
    "admission_note": "A break request is parked until the next real Monitor observation confirms the exact return target. Study pauses only after admission succeeds.",
    "button_intent_note": "RETURN TO STUDY records intent only. It is never return evidence and never resumes Study.",
    "exact_resource_note": "Generic focus is not enough. Only the exact registered Study resource can release the lock.",
    "continuity_note": "Return confirmation requires three CONTINUOUS seconds -- not two sightings separated by a gap.",
    "loss_note": "Uncertain, stale, or mismatched evidence does not count and breaks confirmation.",
    "early_return_note": "Return can be verified from Break Complete or Break Already Over -- Final Lock is an escalation, not a mandatory stage.",
    "resume_boundary_note": "COSECANT confirms return; it does not resume Study itself. Monitor/coordinator resumes Study once confirmation completes.",
}
