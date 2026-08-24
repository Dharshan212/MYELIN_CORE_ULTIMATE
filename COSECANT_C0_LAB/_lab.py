"""Shared C0 harness. Read-only against MYELIN2.0_ULTIMATE.

This module builds isolated, fully REAL MYELIN authorities with only two
substitutions:

    * the Windows foreground reader is scripted, and
    * the browser address-bar reader is scripted.

Everything downstream of those two inputs -- browser certification, Resource
Intent, Study, COSECANT, SINE, MIRL, COSINE, Trigger, Blacklist, storage --
is the real production object. That is the point: a C0 test must fail for the
real reason, not because a stub disagreed with production.

Storage is redirected to a throwaway APPDATA so the user's real MYELIN
database is never opened, read, or written by these tests.
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ULTIMATE = Path(r"C:\Users\Dharshan\Downloads\MYELIN_GENALOGY\MYELIN2.0_ULTIMATE")


def _isolate_storage() -> Path:
    """Point APPDATA at a scratch directory BEFORE PERSISTENCE is imported."""

    scratch = Path(tempfile.mkdtemp(prefix="myelin_c0_"))
    os.environ["APPDATA"] = str(scratch)
    os.environ["XDG_DATA_HOME"] = str(scratch)
    return scratch


SCRATCH = _isolate_storage()

if str(ULTIMATE) not in sys.path:
    sys.path.insert(0, str(ULTIMATE))


# ---------------------------------------------------------------------------
# Scripted inputs
# ---------------------------------------------------------------------------


@dataclass
class Surface:
    """One thing the user can have in the foreground.

    CANONICAL PROCESS IDENTITY (corrected in C9-A). ``process_name`` is what
    the production ``WindowsForegroundReader`` emits, and that is
    EXTENSIONLESS -- "chrome", "msedge", "winword". Browser normalises it back
    to executable form for its own adapter lookup; Resource Intent strips
    ".exe" defensively; Trigger compares the canonical Monitor/RI identity
    without stripping anything.

    These fixtures previously carried "chrome.exe", which Trigger's scope
    match can never satisfy, so no lab test could mint an Executive Blacklist
    candidate. Direct browser tests may still legitimately use ".exe" to
    exercise Browser's own normaliser -- this rule is about the MONITOR-side
    foreground identity only.
    """

    process_name: str
    title: str
    url: str = ""
    hwnd: int = 4242
    process_id: int = 9001


LECTURE = Surface(
    process_name="chrome",
    title="Basal Ganglia Direct and Indirect Pathways - YouTube",
    url="https://www.youtube.com/watch?v=BG_LECTURE_001",
)
OTHER_LECTURE = Surface(
    process_name="chrome",
    title="Cerebellum Motor Learning Explained - YouTube",
    url="https://www.youtube.com/watch?v=CEREBELLUM_002",
)
MRBEAST = Surface(
    process_name="chrome",
    title="MrBeast $1,000,000 Challenge Gaming Reaction - YouTube",
    url="https://www.youtube.com/watch?v=MRBEAST_999",
)
SHORTS = Surface(
    process_name="chrome",
    title="Neuroscience Basal Ganglia Dopamine facts #shorts - YouTube",
    url="https://www.youtube.com/shorts/SHORT_777",
)
INSTAGRAM = Surface(
    process_name="chrome",
    title="Instagram",
    url="https://www.instagram.com/reels/REEL_555",
)


class ScriptedForegroundReader:
    """Duck-typed stand-in for WindowsForegroundReader."""

    def __init__(self, surface: Surface) -> None:
        self._surface = surface
        self._sequence = 0
        self.lock = threading.RLock()

    def set_surface(self, surface: Surface) -> None:
        with self.lock:
            self._surface = surface

    def observe(self):
        from CORE_ENGINE.monitor import ForegroundObservation

        with self.lock:
            surface = self._surface
        self._sequence += 1
        return ForegroundObservation(
            sequence=self._sequence,
            hwnd=surface.hwnd,
            process_id=surface.process_id,
            process_name=surface.process_name,
            window_title=surface.title,
            observed_monotonic_ns=time.monotonic_ns(),
            observed_wall_time_utc=datetime.now(timezone.utc).isoformat(),
            idle_seconds=0.0,
        )


def make_browser_reader(foreground: ScriptedForegroundReader):
    """Return a reader that pushes the scripted URL through the REAL classifier.

    Using ``classify_address_value`` rather than a hand-built evidence object
    means the resource_token, marker and evidence kind are produced by exactly
    the production code path, including the session identity secret.
    """

    from CORE_ENGINE.browser import (
        BrowserKind,
        BrowserUrlObservation,
        BrowserUrlReadStatus,
        classify_address_value,
    )

    def reader(*, hwnd, process_id, process_name, diagnostic, identity_secret):
        with foreground.lock:
            url = foreground._surface.url
        if not url:
            return BrowserUrlObservation(
                status=BrowserUrlReadStatus.ADDRESS_VALUE_EMPTY,
                browser=BrowserKind.CHROME,
                browser_label="Chrome",
                process_name=process_name,
                reason="scripted: no address value",
            )
        return BrowserUrlObservation(
            status=BrowserUrlReadStatus.OK,
            browser=BrowserKind.CHROME,
            browser_label="Chrome",
            process_name=process_name,
            evidence=classify_address_value(url, identity_secret=identity_secret),
            read_method="scripted",
            candidate_count=1,
            reason="scripted address value",
        )

    return reader


# ---------------------------------------------------------------------------
# Real services, isolated storage
# ---------------------------------------------------------------------------


def build_services(
    *,
    foreground: ScriptedForegroundReader,
    fast_cosecant: bool,
    blacklist_thresholds=None,
):
    """Mirror CORE_ENGINE.monitor._build_services with scripted browser input.

    ``fast_cosecant`` shortens ONLY the two escalation delays. CosecantPolicy's
    own docstring sanctions this: "only tests should normally shorten them".
    The 3-second confirmation window and the presence gap are left at their
    production values because those are exactly what we are testing.
    """

    from COSECANT_STUDY_MODE.cosecant import CosecantPolicy, CosecantRuntime
    from COSECANT_STUDY_MODE.study import StudyRuntime
    from CORE_ENGINE.blacklist import BlacklistAuthority
    from CORE_ENGINE.browser import BrowserEvidenceAuthority
    from CORE_ENGINE.monitor import MonitorServices
    from CORE_ENGINE.resource_intent import ResourceIntentAuthority
    from CORE_ENGINE.trigger import TriggerAuthority
    from COSINE.cosine import CosineRuntime
    from MIRL.mirl import MirlAuthority
    from PERSISTENCE.storage import EngineStorage
    from SINE.sine import SineAuthority

    storage = EngineStorage()
    intent = ResourceIntentAuthority()
    policy = (
        CosecantPolicy(
            already_over_delay_seconds=2.0,
            final_lock_delay_seconds=1.0,
        )
        if fast_cosecant
        else CosecantPolicy()
    )
    return MonitorServices(
        browser=BrowserEvidenceAuthority(reader=make_browser_reader(foreground)),
        resource_intent=intent,
        blacklist=(
            BlacklistAuthority(thresholds=blacklist_thresholds)
            if blacklist_thresholds is not None
            else BlacklistAuthority()
        ),
        trigger=TriggerAuthority(profile_type="study"),
        sine=SineAuthority(storage=storage),
        cosine=CosineRuntime(event_sink=storage),
        mirl=MirlAuthority(),
        study=StudyRuntime(),
        cosecant=CosecantRuntime(context_authority=intent, policy=policy),
        storage=storage,
    )


class Engine:
    """One real WindowsMonitorCoordinator running in its own thread."""

    def __init__(self, *, surface: Surface, poll_seconds: float = 0.2,
                 fast_cosecant: bool = True, blacklist_thresholds=None) -> None:
        from CORE_ENGINE.monitor import WindowsMonitorCoordinator

        self.foreground = ScriptedForegroundReader(surface)
        self.services = build_services(
            foreground=self.foreground,
            fast_cosecant=fast_cosecant,
            blacklist_thresholds=blacklist_thresholds,
        )
        self.telemetry: queue.Queue = queue.Queue()
        self.commands: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.ready_event = threading.Event()
        self.loop_stopped_event = threading.Event()
        self.cleanup_complete_event = threading.Event()
        self.coordinator = WindowsMonitorCoordinator(
            profile_type="study",
            services=self.services,
            foreground_reader=self.foreground,
            stop_event=self.stop_event,
            pause_event=self.pause_event,
            ready_event=self.ready_event,
            loop_stopped_event=self.loop_stopped_event,
            cleanup_complete_event=self.cleanup_complete_event,
            telemetry_queue=self.telemetry,
            command_queue=self.commands,
            poll_seconds=poll_seconds,
        )
        self._thread = threading.Thread(
            target=self.coordinator.run, name="c0-engine", daemon=True
        )

    def __enter__(self) -> "Engine":
        self._thread.start()
        if not self.ready_event.wait(timeout=30):
            raise RuntimeError("engine did not become ready")
        return self

    def __exit__(self, *exc) -> None:
        self.stop_event.set()
        self._thread.join(timeout=30)

    # -- driving -------------------------------------------------------

    def look_at(self, surface: Surface) -> None:
        self.foreground.set_surface(surface)

    #: Command kinds Monitor fences with an expected-identity group, and the
    #: identity a real Control Station click would carry.  C12-F closed the
    #: identity-free tunnel, so the LAB now sends the REAL PRODUCTION COMMAND
    #: SHAPE: the controller always copies these fields in, so a test that
    #: omitted them was exercising a path no user could reach.
    STUDY_IDENTITY_KINDS = frozenset(
        {"study_prepare", "study_action", "study_break"}
    )

    def _current_study_identity(self) -> dict:
        snapshot = self.services.study.snapshot()
        return {
            "expected_study_block_id": str(getattr(snapshot, "block_id", "") or ""),
            "expected_study_generation": int(getattr(snapshot, "generation", 0) or 0),
        }

    def _current_cosecant_identity(self) -> dict:
        study = self.services.study.snapshot()
        snapshot = self.services.cosecant.snapshot()
        return {
            "expected_break_id": str(getattr(snapshot, "break_id", "") or ""),
            "expected_cosecant_generation": int(
                getattr(snapshot, "generation", 0) or 0
            ),
            "expected_study_block_id": str(
                getattr(snapshot, "study_block_id", None)
                if getattr(snapshot, "study_block_id", None) is not None
                else getattr(study, "block_id", "") or ""
            ),
            "expected_study_generation": int(
                getattr(snapshot, "study_generation", 0) or 0
            ),
        }

    def send(self, kind: str, **payload) -> None:
        """Deliver one command in the shape a real Control Station sends.

        Identity is filled from CURRENT authority unless the caller supplied
        it, so a test that deliberately sends a stale, partial or absent
        identity still gets exactly what it asked for.
        """

        body = dict(payload)
        if kind in self.STUDY_IDENTITY_KINDS or kind == "cosecant_return_intent":
            # A real Control Station can only name an identity it has already
            # been SHOWN, so it cannot press a button for a block the engine
            # has not applied yet.  Let queued commands land first, otherwise
            # this would name the pre-PREPARE generation and be refused.
            self._settle_commands()
        if kind in self.STUDY_IDENTITY_KINDS:
            for key, value in self._current_study_identity().items():
                body.setdefault(key, value)
        elif kind == "cosecant_return_intent":
            for key, value in self._current_cosecant_identity().items():
                body.setdefault(key, value)
        self.commands.put({"kind": kind, "payload": body})

    def _settle_commands(self, timeout: float = 15.0) -> None:
        """Wait until previously queued commands have been applied."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.commands.empty():
            time.sleep(0.02)
        # The coordinator applies a command immediately after dequeuing it;
        # give that handler a moment to publish its new snapshot.
        time.sleep(0.1)

    def send_raw(self, kind: str, **payload) -> None:
        """Deliver one command EXACTLY as given, adding no identity.

        Hostile tests use this to prove an absent identity is refused.
        """

        self.commands.put({"kind": kind, "payload": dict(payload)})

    def cosecant(self):
        return self.services.cosecant.snapshot()

    def study(self):
        return self.services.study.snapshot()

    def intent(self):
        return self.services.resource_intent.live_view()

    def wait_until(self, predicate, *, timeout: float, what: str):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    def drain_telemetry(self) -> list:
        out = []
        while True:
            try:
                out.append(self.telemetry.get_nowait())
            except queue.Empty:
                return out


class QuietMonitor:
    """A real coordinator and real authorities, driven one observation at a time.

    Nothing runs on a thread, so each ``look_at`` is exactly one production
    classification cycle with no concurrent observer mutating Browser or
    Resource Intent state underneath an assertion. Use this when a test needs
    to interrogate a Monitor derivation rather than watch the engine live.
    """

    def __init__(self, surface: Surface, *, fast_cosecant: bool = True) -> None:
        from CORE_ENGINE.monitor import WindowsMonitorCoordinator

        self.reader = ScriptedForegroundReader(surface)
        self.services = build_services(
            foreground=self.reader, fast_cosecant=fast_cosecant
        )
        self.services.browser.start_session()
        self.services.resource_intent.start_session(profile_type="study")
        self.coordinator = WindowsMonitorCoordinator(
            profile_type="study",
            services=self.services,
            foreground_reader=self.reader,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
            ready_event=threading.Event(),
            loop_stopped_event=threading.Event(),
            cleanup_complete_event=threading.Event(),
            telemetry_queue=queue.Queue(),
            command_queue=queue.Queue(),
            poll_seconds=0.2,
        )

    def on_break(
        self,
        *,
        subject: str = "Neuroscience",
        task: str = "basal ganglia",
        block_id: str = "BLOCK-QUIET",
    ) -> None:
        """Put Resource Intent into the same BREAK posture a real break creates."""

        from CORE_ENGINE.resource_intent import StudyContext

        published = self.services.resource_intent.publish_study_context(
            StudyContext(
                block_id=block_id,
                generation=1,
                display_state="BREAK",
                subject=subject,
                task=task,
                protection_active=False,
                planned_break_active=True,
                remaining_seconds=120,
                published_monotonic_ns=time.monotonic_ns(),
            )
        )
        if not published:
            raise AssertionError("the lab could not publish a BREAK study context")

    def look_at(self, surface: Surface):
        """Return one real MonitorContext for ``surface``."""

        self.reader.set_surface(surface)
        return self.coordinator._classify_observation(self.reader.observe())

    def exact(self, context, target) -> bool:
        """Ask Monitor whether this observation proves the exact frozen return."""

        return self.coordinator._exact_return_confirmed(context, target)


@dataclass
class _SineCandidate:
    """The minimal trigger-candidate shape SINE.request_trigger reads.

    SINE only reads uid / session / profile / evidence timing off a candidate,
    so this carries exactly those. Every organ actually under test -- SINE,
    MIRL, Resource Intent, Monitor -- remains the real production object.
    """

    candidate_uid: str
    session_id: int
    profile_type: str
    evidence: object


@dataclass
class _SineEvidence:
    """The trigger evidence SINE reads when founding an episode.

    ``study_context_token`` is what makes the episode a STUDY-mode episode, so
    it is taken from the same real Resource Intent verdict the test observed.
    """

    observed_monotonic_ns: int
    study_context_token: str = ""
    resource_key: str = ""
    process_name: str = ""
    process_id: int = 0
    hwnd: int = 0
    platform_key: str = ""
    dwell_seconds: float = 0.0
    threshold_seconds: float = 0.0


class SineDriver:
    """Drive a real SineAuthority through its stages with no popup UI.

    The lab has no Control Station, so nothing calls ``popup_shown`` for us.
    This performs exactly the factual display reports the presentation layer
    would make, which is the only way an episode can legitimately reach
    Protected Red.
    """

    def __init__(self, *, session_id: int = 1, profile_type: str = "study",
                 policy=None, sine=None) -> None:
        from SINE.sine import SineAuthority, SinePolicy

        fast = policy or SinePolicy(
            # Visible windows stay long so a stage never expires mid-test;
            # only the escalation delays are shortened.
            stage_1_visible_seconds=3600.0,
            stage_2_delay_seconds=0.01,
            stage_2_visible_seconds=3600.0,
            stage_3_delay_seconds=0.01,
            stage_3_visible_seconds=3600.0,
        )
        if sine is None:
            self.sine = SineAuthority(policy=fast)
        else:
            # Adopt the authority the coordinator already owns, so that
            # Monitor's own `sine.protected_red_active()` read -- which
            # _classify_observation pushes into Resource Intent -- reflects
            # this episode instead of a second, unrelated SINE.
            self.sine = sine
            self.sine._policy = fast
        self.session_id = int(session_id)
        self.profile_type = str(profile_type)
        self.sine.start_session(
            session_id=self.session_id, profile_type=self.profile_type
        )
        self._uid = 0
        self._now_ns = time.monotonic_ns()
        # Optional callable receiving every factual SINE event, so a test can
        # feed MIRL exactly what monitor._route_sine_fact would feed it.
        self.fact_sink = None
        self.last_candidate = None
        # Optional callable(candidate, operational_event_id) -> MIRL display
        # token, mirroring monitor's prepare-then-request ordering.
        self.mirl_token_factory = None

    def mirl_token_for(self, candidate, operational_event_id):
        if self.mirl_token_factory is None:
            return None
        return self.mirl_token_factory(candidate, operational_event_id)

    # -- helpers -------------------------------------------------------

    def live(self):
        return self.sine.live_view()

    def observe(self, context) -> None:
        self.sine.observe(context)

    def _show_current(self, at_ns: int) -> bool:
        request_id = str(self.live().popup_request_id or "")
        if not request_id:
            return False
        shown = bool(
            self.sine.popup_shown(request_id=request_id, shown_monotonic_ns=at_ns)
        )
        # Facts queue inside SINE and are released by advance(); MIRL only ever
        # starts an episode from a factual SINE_DISPLAYED, so drain them here.
        self._drain_facts(at_ns)
        return shown

    def _drain_facts(self, at_ns: int) -> None:
        for fact in self.sine.advance(now_monotonic_ns=at_ns) or ():
            if self.fact_sink is not None:
                self.fact_sink(fact)

    # -- episode lifecycle ---------------------------------------------

    def open_episode(self, context) -> None:
        """Accept one trigger against the Study context in ``context``."""

        self.sine.observe(context)
        self._uid += 1
        candidate = _SineCandidate(
            candidate_uid=f"c8-candidate-{self._uid}",
            session_id=self.session_id,
            profile_type=self.profile_type,
            evidence=_SineEvidence(
                observed_monotonic_ns=int(context.foreground.observed_monotonic_ns),
                study_context_token=str(
                    getattr(
                        getattr(context.resource_intent, "verdict", None),
                        "study_context_token",
                        "",
                    )
                    or ""
                ),
                resource_key=str(
                    getattr(
                        getattr(
                            getattr(context.resource_intent, "verdict", None),
                            "resource_identity",
                            None,
                        ),
                        "stable_key",
                        "",
                    )
                    or ""
                ),
                process_name=str(context.foreground.process_name or ""),
                process_id=int(context.foreground.process_id or 0),
                hwnd=int(context.foreground.hwnd or 0),
            ),
        )
        self.last_candidate = candidate
        accepted = self.sine.request_trigger(
            candidate=candidate,
            operational_event_id=self._uid,
            mirl_display_token=self.mirl_token_for(candidate, self._uid),
        )
        if not accepted:
            raise AssertionError("the lab could not open a SINE episode")
        # A display is only valid at or after its own request time, and the
        # request is stamped from SINE's own clock, so read that clock now.
        self._now_ns = time.monotonic_ns()
        if not self._show_current(self._now_ns):
            raise AssertionError("the lab could not display SINE stage 1")

    def escalate_to_protected_red(self, context) -> None:
        """Walk the real stage ladder until SINE-3 sets Protected Red."""

        self.open_episode(context)
        for stage in (2, 3):
            # Stay on the REAL clock. Jumping the escalation into the future
            # would stamp downstream MIRL episodes ahead of every later
            # observation, and MIRL rejects non-monotonic event times.
            time.sleep(0.05)
            self._now_ns = time.monotonic_ns()
            self._drain_facts(self._now_ns)
            if not self._show_current(self._now_ns):
                raise AssertionError(
                    f"the lab could not display SINE stage {stage}"
                )
        if not self.sine.protected_red_active():
            raise AssertionError("the lab did not reach Protected Red")


def freeze_target(
    context,
    *,
    study_context_token: str | None = None,
    platform_key: str | None = None,
    resource_token: str | None = None,
):
    """Freeze a CosecantReturnTarget exactly the way C5 admission freezes one."""

    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    verdict = context.resource_intent.verdict
    identity = verdict.resource_identity
    return CosecantReturnTarget(
        study_context_token=(
            study_context_token
            if study_context_token is not None
            else verdict.study_context_token
        ),
        platform_key=(
            platform_key if platform_key is not None else identity.platform_key
        ),
        resource_token=(
            resource_token
            if resource_token is not None
            else identity.opaque_resource_token
        ),
        observed_monotonic_ns=int(context.foreground.observed_monotonic_ns),
    )


__all__ = [
    "SineDriver",
    "Engine",
    "QuietMonitor",
    "INSTAGRAM",
    "LECTURE",
    "MRBEAST",
    "OTHER_LECTURE",
    "SCRATCH",
    "SHORTS",
    "ScriptedForegroundReader",
    "Surface",
    "ULTIMATE",
    "build_services",
    "freeze_target",
    "make_browser_reader",
]
