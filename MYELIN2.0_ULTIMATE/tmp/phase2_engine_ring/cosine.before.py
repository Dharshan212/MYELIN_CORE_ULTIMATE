"""Single NEW COSINE backend authority. No UI, Windows reads, SQL, or timezone projection."""
from __future__ import annotations

import hashlib, json, math, secrets, threading, time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final, Protocol
from CORE_ENGINE.app_identity import ForegroundAppIdentity

COSINE_SCHEMA_VERSION: Final = "myelin-cosine-v3-parent-session"
INITIAL_GATE_SECONDS: Final = 5 * 60
RETURN_INTENT_WINDOW_SECONDS: Final = 5 * 60
BREAK_MINUTES_MIN: Final = 10
BREAK_MINUTES_MAX: Final = 200
RETURN_VERIFICATION_SECONDS: Final = 10
CLOSURE_CONFIRMATION_SECONDS: Final = 60
FINAL_CALLBACK_HIDE_SECONDS: Final = 3
MAX_CONTENT_TITLE: Final = 300
_NS: Final = 1_000_000_000

PLATFORM_LABELS: Final = {
    "netflix": "Netflix", "prime_video": "Prime Video", "jiohotstar": "JioHotstar",
    "disney_plus": "Disney+", "hulu": "Hulu", "hbo_max": "HBO Max",
    "apple_tv_plus": "Apple TV+", "paramount_plus": "Paramount+",
}
PLATFORM_KEYS: Final = frozenset(PLATFORM_LABELS)
_HOST_PLATFORM: Final = {
    "netflix.com": "netflix", "primevideo.com": "prime_video",
    "jiohotstar.com": "jiohotstar", "hotstar.com": "jiohotstar",
    "disneyplus.com": "disney_plus", "hulu.com": "hulu", "max.com": "hbo_max",
    "hbomax.com": "hbo_max", "tv.apple.com": "apple_tv_plus",
    "paramountplus.com": "paramount_plus",
}
_PROCESS_PLATFORM: Final = {
    "netflix.exe": "netflix", "primevideo.exe": "prime_video",
    "amazonprimevideo.exe": "prime_video", "jiohotstar.exe": "jiohotstar",
    "hotstar.exe": "jiohotstar", "disneyplus.exe": "disney_plus",
    "hulu.exe": "hulu", "hbomax.exe": "hbo_max", "max.exe": "hbo_max",
    "appletv.exe": "apple_tv_plus", "paramountplus.exe": "paramount_plus",
}
_BROWSERS: Final = frozenset({"chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "opera_gx.exe"})

class CosinePhase(str, Enum):
    IDLE="IDLE"; OBSERVING_OTT="OBSERVING_OTT"; INTENT_GATE_PENDING="INTENT_GATE_PENDING"
    INTENT_GATE_ACTIVE="INTENT_GATE_ACTIVE"; RETURN_INTENT_OBSERVING="RETURN_INTENT_OBSERVING"
    DURATION_ENTRY="DURATION_ENTRY"; BREAK_COMMIT_PENDING="BREAK_COMMIT_PENDING"; BREAK_ACTIVE="BREAK_ACTIVE"
    RETURN_VERIFYING="RETURN_VERIFYING"; CLOSURE_CONFIRMING="CLOSURE_CONFIRMING"
    FINAL_CALLBACK_PENDING="FINAL_CALLBACK_PENDING"; FINAL_CALLBACK_ACTIVE="FINAL_CALLBACK_ACTIVE"
    FINAL_CALLBACK_HIDDEN_VERIFYING="FINAL_CALLBACK_HIDDEN_VERIFYING"; CLOSED="CLOSED"; SHUTDOWN="SHUTDOWN"
    # Phase-1H-old import aliases only.
    QUALIFYING="OBSERVING_OTT"; CHECKIN_PENDING="INTENT_GATE_PENDING"; ACTIVE="INTENT_GATE_ACTIVE"; RETURN_PENDING="RETURN_VERIFYING"

class CheckinMode(str, Enum):  # deprecated import compatibility only
    INITIAL="INITIAL"; TEN_MORE_MIN="TEN_MORE_MIN"; FINISH_MY_SHOW="FINISH_MY_SHOW"; CONTINUED_WATCHING="CONTINUED_WATCHING"

class CosineChoice(str, Enum):
    RETURN_INTENTION="RETURN_INTENTION"; INTENTIONAL_BREAK="INTENTIONAL_BREAK"; ACKNOWLEDGE="ACKNOWLEDGE"
    TEN_MORE_MIN="TEN_MORE_MIN"; FINISH_MY_SHOW="FINISH_MY_SHOW"; YAY="YAY"; IM_TIRED="IM_TIRED"

class CommandKind(str, Enum):
    INTENT_GATE_DISPLAYED="INTENT_GATE_DISPLAYED"; INTENT_ACTION="INTENT_ACTION"; DURATION_SUBMITTED="DURATION_SUBMITTED"
    BREAK_ACK_DISPLAYED="BREAK_ACK_DISPLAYED"; BREAK_ACKNOWLEDGED="BREAK_ACKNOWLEDGED"; FINAL_CALLBACK_DISPLAYED="FINAL_CALLBACK_DISPLAYED"
    CHECKIN_DISPLAYED="CHECKIN_DISPLAYED"; CHECKIN_ACTION="CHECKIN_ACTION"; CHECKIN_EXPIRED="CHECKIN_EXPIRED"
    WELCOME_DISPLAYED="WELCOME_DISPLAYED"; WELCOME_ACTION="WELCOME_ACTION"; WELCOME_EXPIRED="WELCOME_EXPIRED"

class ClosureReason(str, Enum):
    RETURNED_TO_FOCUS="RETURNED_TO_FOCUS"
    STUDY_MODE_ACTIVATED="STUDY_MODE_ACTIVATED"
    STOPPED="STOPPED"; EMERGENCY="EMERGENCY"; SYSTEM_LOCK="SYSTEM_LOCK"; SYSTEM_SLEEP="SYSTEM_SLEEP"
    NOT_ENOUGH_INFORMATION="NOT_ENOUGH_INFORMATION"

class ClosureOutcome(str, Enum):
    RETURNED_AFTER_INTENT="RETURNED_AFTER_INTENT"; EARLY_RETURN="EARLY_RETURN"
    RETURNED_AFTER_CALLBACK="RETURNED_AFTER_CALLBACK"; STUDY_PREEMPTION="STUDY_PREEMPTION"
    EMERGENCY="EMERGENCY"; INCOMPLETE="INCOMPLETE"

class EffectKind(str, Enum):
    SHOW_INTENT_GATE="SHOW_INTENT_GATE"; CLOSE_INTENT_GATE="CLOSE_INTENT_GATE"
    SHOW_DURATION_ENTRY="SHOW_DURATION_ENTRY"; CLOSE_DURATION_ENTRY="CLOSE_DURATION_ENTRY"
    SHOW_BREAK_ACK="SHOW_BREAK_ACK"; CLOSE_BREAK_ACK="CLOSE_BREAK_ACK"
    SHOW_FINAL_CALLBACK="SHOW_FINAL_CALLBACK"; HIDE_FINAL_CALLBACK="HIDE_FINAL_CALLBACK"
    RESTORE_FINAL_CALLBACK="RESTORE_FINAL_CALLBACK"; CLOSE_PRESENTATION="CLOSE_PRESENTATION"
    SHOW_CHECKIN="SHOW_CHECKIN"; CLOSE_CHECKIN="CLOSE_CHECKIN"; SHOW_WELCOME="SHOW_WELCOME"
    CLOSE_WELCOME="CLOSE_WELCOME"; REQUEST_NORMAL_STOP="REQUEST_NORMAL_STOP"

class EvidenceSource(str, Enum): CERTIFIED_HOST="CERTIFIED_HOST"; NATIVE_PROCESS="NATIVE_PROCESS"; WINDOWS_APP="WINDOWS_APP"
class EventClass(str, Enum): OBSERVED="OBSERVED"; DERIVED="DERIVED"; USER_ACTION="USER_ACTION"; PRESENTATION="PRESENTATION"
class _Kind(str, Enum): OTT="OTT"; FOCUS="FOCUS"; UNKNOWN="UNKNOWN"
class _Origin(str, Enum): NONE="NONE"; RETURN_INTENT="RETURN_INTENT"; EARLY_BREAK="EARLY_BREAK"; FINAL_CALLBACK="FINAL_CALLBACK"

@dataclass(frozen=True, slots=True)
class CosinePolicy:
    initial_gate_seconds: float=INITIAL_GATE_SECONDS
    return_intent_window_seconds: float=RETURN_INTENT_WINDOW_SECONDS
    break_minimum_minutes: int=BREAK_MINUTES_MIN; break_maximum_minutes: int=BREAK_MINUTES_MAX
    return_verification_seconds: float=RETURN_VERIFICATION_SECONDS
    closure_confirmation_seconds: float=CLOSURE_CONFIRMATION_SECONDS
    final_callback_hide_seconds: float=FINAL_CALLBACK_HIDE_SECONDS
    def __post_init__(self):
        expected=(INITIAL_GATE_SECONDS,RETURN_INTENT_WINDOW_SECONDS,BREAK_MINUTES_MIN,BREAK_MINUTES_MAX,RETURN_VERIFICATION_SECONDS,CLOSURE_CONFIRMATION_SECONDS,FINAL_CALLBACK_HIDE_SECONDS)
        actual=(self.initial_gate_seconds,self.return_intent_window_seconds,self.break_minimum_minutes,self.break_maximum_minutes,self.return_verification_seconds,self.closure_confirmation_seconds,self.final_callback_hide_seconds)
        if any(not math.isfinite(float(v)) or float(v)!=float(e) for v,e in zip(actual,expected)): raise ValueError("COSINE timing ledger is frozen")
    @property
    def initial_checkin_seconds(self): return self.initial_gate_seconds
    @property
    def popup_response_seconds(self): return self.return_intent_window_seconds
    @property
    def return_confirmation_seconds(self): return self.return_verification_seconds+self.closure_confirmation_seconds

@dataclass(frozen=True, slots=True)
class CertifiedPlatformEvidence:
    platform_key:str; source:EvidenceSource; process_name:str; process_id:int; hwnd:int; certified_host:str
    evidence_token:str; observed_monotonic_ns:int; content_title:str=""
    def __post_init__(self):
        if self.platform_key not in PLATFORM_KEYS or not isinstance(self.source,EvidenceSource): raise ValueError("invalid platform evidence")
        if not self.process_name or self.process_id<=0 or self.hwnd<=0 or self.observed_monotonic_ns<=0 or not self.evidence_token: raise ValueError("platform evidence requires exact foreground identity")
        if self.source is EvidenceSource.CERTIFIED_HOST and not self.certified_host: raise ValueError("certified host required")

@dataclass(frozen=True, slots=True)
class CosineObservation:
    platform:CertifiedPlatformEvidence|None; focus_confirmed:bool; sine_popup_displayed:bool
    observed_monotonic_ns:int; observation_sequence:int=0; supported_interval_ns:int=0
    def __post_init__(self):
        if self.observed_monotonic_ns<=0: raise ValueError("positive monotonic time required")
        if self.platform and self.platform.observed_monotonic_ns!=self.observed_monotonic_ns: raise ValueError("sample times differ")
        if type(self.focus_confirmed) is not bool or type(self.sine_popup_displayed) is not bool: raise TypeError("flags must be bool")
        if self.observation_sequence<0 or self.supported_interval_ns<0 or (self.platform is not None and self.focus_confirmed): raise ValueError("invalid observation")

@dataclass(frozen=True, slots=True)
class CosineCommand:
    kind:CommandKind; generation:int; request_id:str; choice:CosineChoice|None=None
    occurred_monotonic_ns:int=0; duration_minutes:int|None=None
    def __post_init__(self):
        if not isinstance(self.kind,CommandKind) or self.generation<0 or not self.request_id or self.occurred_monotonic_ns<=0: raise ValueError("invalid command")

@dataclass(frozen=True, slots=True)
class CosineEvent:
    event_id:str; session_id:int; cosine_session_id:str; sequence:int; event_name:str; event_class:EventClass
    occurred_at_utc:str; monotonic_ns:int; generation:int; platform_key:str; content_title:str
    request_id:str; evidence_token:str; payload_json:str; schema_version:str=COSINE_SCHEMA_VERSION

@dataclass(frozen=True, slots=True)
class CosineEffect:
    kind:EffectKind; generation:int; request_id:str; platform_key:str=""; content_title:str=""; message:str=""
    # Phase-1H presentation metadata only.  Appended at the end so existing
    # positional construction stays valid.  These fields never take part in
    # state, timing, evidence, pause, return, closure or persistence.
    presentation_variant:str=""; duration_minutes:int|None=None; source_hwnd:int=0

@dataclass(frozen=True, slots=True)
class PlatformSnapshot:
    platform_key:str; foreground_seconds:float; mode:CheckinMode; content_title:str; content_history:tuple[str,...]

@dataclass(frozen=True, slots=True)
class CosineSnapshot:
    phase:CosinePhase; generation:int; session_id:int|None; cosine_session_id:str; current_platform_key:str; current_platform_label:str
    current_content_title:str; foreground_ott_seconds:float; current_platform_seconds:float; qualification_seconds:float
    checkin_request_id:str; checkin_displayed:bool; checkin_response_remaining_seconds:float
    return_confirmation_remaining_seconds:float; return_focus_continuous:bool; welcome_request_id:str
    welcome_pending:bool; closure_reason:str; durable_health:bool; durable_detail:str; platforms:tuple[PlatformSnapshot,...]
    available:bool; hopper_count:int; initial_gate_remaining_seconds:float; return_intent_remaining_seconds:float
    chosen_break_minutes:int|None; break_start_effective_ns:int; break_deadline_effective_ns:int; break_remaining_seconds:float
    final_callback_request_id:str; final_callback_visible:bool; return_verification_state:str
    return_verification_remaining_seconds:float; closure_confirmation_remaining_seconds:float
    global_paused:bool; closure_outcome:str; data_quality:str
    schema_version:str=COSINE_SCHEMA_VERSION

@dataclass(frozen=True, slots=True)
class CosineMonitorStatus:
    """Narrow Mom-facing status with no sibling or handover policy."""
    factual_episode:bool; source_eligible:bool; held:bool; termination_pending:bool
    episode_key:tuple[int,str]|None; phase:CosinePhase

@dataclass(frozen=True, slots=True)
class CommandResult: accepted:bool; close_popup:bool; message:str; snapshot:CosineSnapshot
class CosineEventSink(Protocol):
    def append_cosine_events(self,events:tuple[CosineEvent,...])->bool: ...
@dataclass(slots=True)
class _PlatformState: platform_key:str; foreground_ns:int=0; content_title:str=""; content_history:tuple[str,...]=()
@dataclass(slots=True)
class _Request: request_id:str; requested_ns:int; displayed_ns:int=0; visible:bool=False

def certify_platform_evidence(*,process_name:object,process_id:int,hwnd:int,observed_monotonic_ns:int,browser_authoritative:bool=False,certified_host:object="",window_title:object="",app_identity:ForegroundAppIdentity|None=None):
    process=_process_name(process_name); host=_host_name(certified_host); source=None; platform=_PROCESS_PLATFORM.get(process)
    if platform: source=EvidenceSource.NATIVE_PROCESS; host=""
    elif isinstance(app_identity,ForegroundAppIdentity) and app_identity.matches(process_name=process,process_id=process_id,hwnd=hwnd,observed_monotonic_ns=observed_monotonic_ns):
        platform=app_identity.platform_key; source=EvidenceSource.WINDOWS_APP; host=""
    elif process in _BROWSERS and browser_authoritative and host:
        platform=next((key for domain,key in _HOST_PLATFORM.items() if host==domain or host.endswith(f".{domain}")),None)
        if platform: source=EvidenceSource.CERTIFIED_HOST
    if not platform or source is None: return None
    try: pid=int(process_id); window=int(hwnd); observed=int(observed_monotonic_ns)
    except (TypeError,ValueError): return None
    if pid<=0 or window<=0 or observed<=0: return None
    identity=app_identity.application_id if source is EvidenceSource.WINDOWS_APP else host
    token=hashlib.sha256(f"{source.value}|{platform}|{process}|{pid}|{window}|{identity}".encode()).hexdigest()[:32]
    return CertifiedPlatformEvidence(platform,source,process,pid,window,host,token,observed,_supporting_title(window_title,platform))

class CosineRuntime:
    """Thread-safe owner of one NEW COSINE episode."""
    def __init__(self,*,event_sink:CosineEventSink,policy:CosinePolicy=CosinePolicy(),wall_clock_utc:Callable[[],datetime]|None=None):
        if event_sink is None: raise ValueError("durable event sink required")
        self._sink=event_sink; self._policy=policy; self._wall=wall_clock_utc or (lambda:datetime.now(timezone.utc)); self._lock=threading.RLock()
        self._phase=CosinePhase.IDLE; self._generation=0; self._parent_session_id=None; self._session_id=""; self._event_sequence=0
        self._platforms={}; self._current_platform=""; self._last_evidence_token=""; self._hopper_count=0
        self._initial_ns=0; self._intent_window_ns=0
        self._intent=None; self._duration=None; self._duration_variant=""; self._ack=None; self._final=None
        self._chosen_minutes=None; self._break_start=0; self._break_deadline=0
        self._origin=_Origin.NONE; self._candidate=False; self._verify_ns=0; self._closure_ns=0
        self._last_obs_ns=0; self._last_obs_seq=0; self._last_kind=_Kind.UNKNOWN; self._last_platform=""
        self._paused=False; self._pause_started=0; self._paused_total=0
        self._pending_pause_events=[]
        self._study_suppressed=False
        # Phase 2C Mom artery only: no sibling identity, target, or 120-second timer.
        self._monitor_held=False; self._monitor_hold_started_effective=0
        self._monitor_restore_request_id=""; self._monitor_restore_was_visible=False
        self._monitor_termination_pending=False
        self._closure_reason=""; self._closure_outcome=""; self._quality="NO_EVIDENCE"
        self._durable_health=True; self._durable_detail=""; self._effects=[]

    def snapshot(self,*,now_ns:int|None=None)->CosineSnapshot:
        with self._lock:
            raw=_now_ns(now_ns); effective=self._effective(raw); current=self._platforms.get(self._current_platform)
            total=sum(p.foreground_ns for p in self._platforms.values())
            initial=max(0.0,self._policy.initial_gate_seconds-self._initial_ns/_NS)
            intent=max(0.0,self._policy.return_intent_window_seconds-self._intent_window_ns/_NS) if self._phase is CosinePhase.RETURN_INTENT_OBSERVING else 0.0
            remain=max(0.0,(self._break_deadline-effective)/_NS) if self._break_deadline and self._phase not in {CosinePhase.CLOSED,CosinePhase.SHUTDOWN} else 0.0
            verify=max(0.0,self._policy.return_verification_seconds-self._verify_ns/_NS) if self._candidate and self._phase is not CosinePhase.CLOSURE_CONFIRMING else 0.0
            close=max(0.0,self._policy.closure_confirmation_seconds-self._closure_ns/_NS) if self._phase is CosinePhase.CLOSURE_CONFIRMING else 0.0
            return CosineSnapshot(
                self._phase,self._generation,self._parent_session_id,self._session_id,self._current_platform,PLATFORM_LABELS.get(self._current_platform,""),
                current.content_title if current else "",total/_NS,current.foreground_ns/_NS if current else 0.0,self._initial_ns/_NS,
                self._intent.request_id if self._intent else "",bool(self._intent and self._intent.displayed_ns),intent,verify+close,
                self._candidate,"",False,self._closure_reason,self._durable_health,self._durable_detail,
                tuple(PlatformSnapshot(p.platform_key,p.foreground_ns/_NS,CheckinMode.INITIAL,p.content_title,p.content_history) for p in self._platforms.values()),
                self._phase is not CosinePhase.SHUTDOWN,self._hopper_count,initial,intent,self._chosen_minutes,self._break_start,self._break_deadline,remain,
                self._final.request_id if self._final else "",bool(self._final and self._final.visible),
                "CLOSURE_CONFIRMING" if self._phase is CosinePhase.CLOSURE_CONFIRMING else "RETURN_VERIFYING" if self._candidate else "INACTIVE",
                verify,close,self._paused,self._closure_outcome,"PAUSED" if self._paused else self._quality)

    def bind_parent_session(self,session_id:int)->bool:
        """Bind the exact durable Monitor session before any COSINE event."""
        if isinstance(session_id,bool) or not isinstance(session_id,int) or session_id<=0:
            raise ValueError("COSINE parent session_id must be a positive integer")
        with self._lock:
            if self._parent_session_id is None:
                if self._event_sequence or self._session_id:
                    raise RuntimeError("COSINE parent session cannot be bound after event emission begins")
                self._parent_session_id=session_id
                return True
            if self._parent_session_id==session_id: return True
            raise RuntimeError("COSINE parent session is immutable for one Monitor runtime")

    def observe(self,observation:CosineObservation)->tuple[CosineEffect,...]:
        with self._lock:
            if self._phase is CosinePhase.SHUTDOWN or self._paused or self._monitor_held: return ()
            now=observation.observed_monotonic_ns
            if self._last_obs_ns and now<self._last_obs_ns:
                self._gap(now,"REGRESSED_MONOTONIC_TIME"); return self.drain_effects()
            kind=_Kind.OTT if observation.platform else _Kind.FOCUS if observation.focus_confirmed else _Kind.UNKNOWN
            elapsed=self._supported_interval(observation,kind)
            if elapsed: self._credit(elapsed,kind)
            if self._phase in {CosinePhase.IDLE,CosinePhase.CLOSED}:
                if observation.platform: self._start(observation.platform,now)
            elif observation.platform: self._observe_ott(observation.platform,now)
            elif observation.focus_confirmed: self._observe_focus(now)
            else: self._observe_unknown(now)
            self._thresholds(now); self._remember(observation,kind)
            return self.drain_effects()

    def advance(self,*,now_ns:int|None=None)->tuple[CosineEffect,...]:
        with self._lock:
            now=_now_ns(now_ns)
            if self._phase is CosinePhase.SHUTDOWN or self._paused: return ()
            if self._monitor_held:
                if self._monitor_termination_pending: self._attempt_monitor_termination(now)
                return self.drain_effects()
            if self._deadline_reached(now):
                if self._phase is CosinePhase.BREAK_ACTIVE: self._request_final(now)
                elif self._origin is _Origin.EARLY_BREAK and self._phase in {CosinePhase.RETURN_VERIFYING,CosinePhase.CLOSURE_CONFIRMING}:
                    self._interrupt(now,"BREAK_DEADLINE_REACHED"); self._request_final(now)
            return self.drain_effects()

    def set_global_paused(self,paused:bool,now_ns:int|None=None)->bool:
        with self._lock:
            now=_now_ns(now_ns); requested=bool(paused)
            if requested!=self._paused:
                # Global Pause is an external scientific fact. Freeze/resume
                # first even when its audit event cannot yet be persisted.
                if requested: self._paused=True; self._pause_started=now
                else:
                    if self._pause_started and now>self._pause_started: self._paused_total+=now-self._pause_started
                    self._paused=False; self._pause_started=0
                self._break_continuity()
                if self._session_id and self._phase not in {CosinePhase.CLOSED,CosinePhase.SHUTDOWN}:
                    self._pending_pause_events.append(("GLOBAL_PAUSE_ENTERED" if requested else "GLOBAL_PAUSE_EXITED",now))
            return self._flush_pause_events()

    def submit_command(self,command:CosineCommand)->CommandResult:
        with self._lock:
            if command.generation!=self._generation: return self._reject("COSINE generation changed")
            if self._monitor_held: return self._reject("Monitor temporarily owns this episode")
            # M3.  Study outranks COSINE.  Once suppression is latched no
            # specialist command may be accepted, even while the durable
            # STUDY_MODE_ACTIVATED close is still being retried -- otherwise an
            # old intention/duration button could still act inside Study.
            if self._study_suppressed: return self._reject("Study owns this moment")
            if command.kind is CommandKind.INTENT_GATE_DISPLAYED: return self._display_intent(command)
            if command.kind is CommandKind.INTENT_ACTION: return self._intent_action(command)
            if command.kind is CommandKind.DURATION_SUBMITTED: return self._submit_duration(command)
            if command.kind in {CommandKind.BREAK_ACK_DISPLAYED,CommandKind.BREAK_ACKNOWLEDGED}: return self._break_ack(command)
            if command.kind is CommandKind.FINAL_CALLBACK_DISPLAYED: return self._display_final(command)
            return self._reject("Legacy or invalid COSINE command is not authoritative")

    def monitor_status(self,*,now_ns:int|None=None)->CosineMonitorStatus:
        del now_ns
        with self._lock:
            factual_phases={CosinePhase.INTENT_GATE_ACTIVE,CosinePhase.RETURN_INTENT_OBSERVING,CosinePhase.DURATION_ENTRY,CosinePhase.BREAK_COMMIT_PENDING,CosinePhase.BREAK_ACTIVE,CosinePhase.RETURN_VERIFYING,CosinePhase.CLOSURE_CONFIRMING,CosinePhase.FINAL_CALLBACK_PENDING,CosinePhase.FINAL_CALLBACK_ACTIVE,CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING}
            eligible_phases={CosinePhase.INTENT_GATE_ACTIVE,CosinePhase.RETURN_INTENT_OBSERVING,CosinePhase.DURATION_ENTRY,CosinePhase.BREAK_COMMIT_PENDING,CosinePhase.BREAK_ACTIVE,CosinePhase.FINAL_CALLBACK_PENDING,CosinePhase.FINAL_CALLBACK_ACTIVE}
            factual=bool(self._session_id and self._phase in factual_phases)
            eligible=bool(factual and self._phase in eligible_phases and not self._study_suppressed and not self._monitor_termination_pending)
            key=(self._generation,self._session_id) if factual else None
            return CosineMonitorStatus(factual,eligible,self._monitor_held,self._monitor_termination_pending,key,self._phase)

    def monitor_hold(self,*,episode_key:object,now_ns:int)->bool:
        with self._lock:
            status=self.monitor_status(now_ns=now_ns)
            if not status.source_eligible or status.episode_key!=episode_key: return False
            if self._monitor_held: return True
            now=_now_ns(now_ns); self._monitor_held=True; self._monitor_hold_started_effective=self._effective(now)
            request=self._current_presentation_request(); self._monitor_restore_request_id=request.request_id if request else ""
            self._monitor_restore_was_visible=bool(request and request.visible)
            if request:
                request.visible=False
                self._effects.append(CosineEffect(EffectKind.CLOSE_PRESENTATION,self._generation,request.request_id,self._current_platform,message="Monitor temporarily withdrew this presentation"))
            self._break_continuity(); return True

    def monitor_resume(self,*,episode_key:object,now_ns:int)->bool:
        with self._lock:
            status=self.monitor_status(now_ns=now_ns)
            if not self._monitor_held or self._monitor_termination_pending or status.episode_key!=episode_key: return False
            now=_now_ns(now_ns); held=max(0,self._effective(now)-self._monitor_hold_started_effective)
            if self._break_start: self._break_start+=held
            if self._break_deadline: self._break_deadline+=held
            request=self._current_presentation_request()
            if request and request.request_id==self._monitor_restore_request_id:
                effect=self._presentation_restore_effect(request,self._monitor_restore_was_visible)
                if effect is not None:
                    request.visible=self._monitor_restore_was_visible
                    self._effects.append(effect)
            self._clear_monitor_control(); self._break_continuity(); return True

    def monitor_terminate(self,*,episode_key:object,now_ns:int)->bool:
        with self._lock:
            status=self.monitor_status(now_ns=now_ns)
            if not self._monitor_held or status.episode_key!=episode_key: return False
            self._monitor_termination_pending=True
            self._attempt_monitor_termination(_now_ns(now_ns))
            return self._phase is CosinePhase.CLOSED

    def _attempt_monitor_termination(self,now:int)->None:
        if not self._monitor_termination_pending: return
        self.close(ClosureReason.STOPPED,now_ns=now)
        if self._phase is CosinePhase.CLOSED: self._clear_monitor_control()

    def _clear_monitor_control(self)->None:
        self._monitor_held=False; self._monitor_hold_started_effective=0
        self._monitor_restore_request_id=""; self._monitor_restore_was_visible=False
        self._monitor_termination_pending=False

    def preempt_for_study(self, *, now_ns:int|None=None)->tuple[CosineEffect,...]:
        """Immediately end the current COSINE episode when Dad/Study takes ownership.

        Study is a stronger owner, not a sibling.  Specialist authority is
        withdrawn before durable closure is attempted, so an old COSINE action
        can never remain usable inside Study if persistence is temporarily
        unavailable.  A failed close is retried by calling this method again;
        no timer, handover, saved remainder or old-episode restoration is used.
        """
        with self._lock:
            if self._phase in {CosinePhase.IDLE,CosinePhase.CLOSED,CosinePhase.SHUTDOWN}: return ()
            now=_now_ns(now_ns)
            if not self._study_suppressed:
                self._study_suppressed=True
                request=self._current_presentation_request()
                if request and request.visible:
                    request.visible=False
                    self._effects.append(CosineEffect(EffectKind.CLOSE_PRESENTATION,self._generation,request.request_id))
            return self.close(ClosureReason.STUDY_MODE_ACTIVATED,now_ns=now)

    def close(self,reason:ClosureReason,*,now_ns:int|None=None)->tuple[CosineEffect,...]:
        with self._lock:
            if not isinstance(reason,ClosureReason): raise TypeError("reason must be ClosureReason")
            if self._phase in {CosinePhase.IDLE,CosinePhase.CLOSED,CosinePhase.SHUTDOWN}: return ()
            now=_now_ns(now_ns); outcome=self._external_outcome(reason)
            if not self._flush_pause_events(): return self.drain_effects()
            if not self._commit("COSINE_SESSION_CLOSED",EventClass.DERIVED,now,platform=self._current_platform,payload=self._closure_payload(reason.value,outcome.value)):
                self._quality="EVIDENCE_GAP"; self._break_continuity(); return self.drain_effects()
            self._closure_reason=reason.value; self._closure_outcome=outcome.value; self._phase=CosinePhase.CLOSED
            self._clear_recovery(); self._close_presentations(); self._clear_monitor_control(); self._break_continuity(); return self.drain_effects()

    def shutdown(self,*,now_ns:int|None=None)->bool:
        with self._lock:
            if self._phase is CosinePhase.SHUTDOWN: return True
            now=_now_ns(now_ns)
            if self._session_id and self._phase is not CosinePhase.CLOSED:
                self.close(ClosureReason.STOPPED,now_ns=now)
                if self._phase is not CosinePhase.CLOSED: return False
            self._phase=CosinePhase.SHUTDOWN; return True

    def drain_effects(self):
        effects=tuple(self._effects); self._effects.clear(); return effects

    def _start(self,e:CertifiedPlatformEvidence,now:int):
        if self._parent_session_id is None:
            self._durable_health=False; self._durable_detail="COSINE parent session is not durably bound"
            return
        sid=secrets.token_hex(16); gen=self._generation+1
        events=(self._event("COSINE_SESSION_STARTED",EventClass.OBSERVED,now,platform=e.platform_key,content=e.content_title,evidence_token=e.evidence_token,payload={"evidence_source":e.source.value},session_id=sid,generation=gen,sequence=1),
                self._event("OTT_PLATFORM_ENTERED",EventClass.OBSERVED,now,platform=e.platform_key,content=e.content_title,evidence_token=e.evidence_token,session_id=sid,generation=gen,sequence=2))
        if not self._write(events): return
        self._reset_episode(); self._generation=gen; self._session_id=sid; self._event_sequence=2; self._phase=CosinePhase.OBSERVING_OTT
        self._current_platform=e.platform_key; self._platforms[e.platform_key]=_PlatformState(e.platform_key); self._last_evidence_token=e.evidence_token; self._quality="OBSERVED"; self._content(e,now)

    def _observe_ott(self,e:CertifiedPlatformEvidence,now:int):
        if e.platform_key!=self._current_platform:
            old=self._current_platform
            if not self._commit("HOPPER_TRANSITION",EventClass.OBSERVED,now,platform=e.platform_key,content=e.content_title,evidence_token=e.evidence_token,payload={"from_platform":old,"to_platform":e.platform_key}): return
            self._current_platform=e.platform_key; self._platform(e.platform_key); self._hopper_count+=1
        self._last_evidence_token=e.evidence_token; self._content(e,now)
        if self._phase in {CosinePhase.RETURN_VERIFYING,CosinePhase.CLOSURE_CONFIRMING,CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING} or (self._phase is CosinePhase.FINAL_CALLBACK_ACTIVE and self._candidate): self._relapse(now)

    def _observe_focus(self,now:int):
        if self._phase is CosinePhase.RETURN_INTENT_OBSERVING: self._start_recovery(_Origin.RETURN_INTENT,now)
        elif self._phase is CosinePhase.BREAK_ACTIVE:
            self._request_final(now) if self._deadline_reached(now) else self._start_recovery(_Origin.EARLY_BREAK,now)
        elif self._phase is CosinePhase.FINAL_CALLBACK_ACTIVE and not self._candidate: self._start_recovery(_Origin.FINAL_CALLBACK,now)
        elif self._phase is CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING and not self._candidate: self._start_recovery(_Origin.FINAL_CALLBACK,now)

    def _observe_unknown(self,now:int):
        if self._phase is CosinePhase.RETURN_VERIFYING: self._interrupt(now,"FOCUS_NOT_CONFIRMED")
        elif self._phase is CosinePhase.CLOSURE_CONFIRMING:
            self._interrupt_final_silent(now) if self._origin is _Origin.FINAL_CALLBACK else self._interrupt(now,"FOCUS_NOT_CONFIRMED")
        elif self._phase is CosinePhase.FINAL_CALLBACK_ACTIVE and self._candidate: self._interrupt_final_visible(now)
        elif self._phase is CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING: self._interrupt_final_silent(now)

    def _thresholds(self,now:int):
        if self._phase is CosinePhase.OBSERVING_OTT and self._initial_ns>=_to_ns(self._policy.initial_gate_seconds): self._request_intent(now)
        elif self._phase is CosinePhase.RETURN_INTENT_OBSERVING and self._intent_window_ns>=_to_ns(self._policy.return_intent_window_seconds): self._failed_return(now)
        if not self._candidate: return
        if self._origin is _Origin.FINAL_CALLBACK and self._phase is CosinePhase.FINAL_CALLBACK_ACTIVE and self._verify_ns>=_to_ns(self._policy.final_callback_hide_seconds): self._hide_final(now)
        if self._phase in {CosinePhase.RETURN_VERIFYING,CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING} and self._verify_ns>=_to_ns(self._policy.return_verification_seconds): self._verified(now)
        if self._phase is CosinePhase.CLOSURE_CONFIRMING and self._closure_ns>=_to_ns(self._policy.closure_confirmation_seconds): self._confirm(now)

    def _start_recovery(self,origin:_Origin,now:int):
        if not self._commit("RETURN_CANDIDATE_STARTED",EventClass.OBSERVED,now,payload={"branch":origin.value}): return
        self._origin=origin; self._candidate=True; self._verify_ns=0; self._closure_ns=0
        if origin is not _Origin.FINAL_CALLBACK: self._phase=CosinePhase.RETURN_VERIFYING

    def _verified(self,now:int):
        if not self._commit_many((("RETURN_VERIFICATION_COMPLETED",EventClass.DERIVED,{"branch":self._origin.value}),("CLOSURE_CONFIRMATION_STARTED",EventClass.DERIVED,{"branch":self._origin.value})),now): return
        self._phase=CosinePhase.CLOSURE_CONFIRMING; self._closure_ns=0

    def _confirm(self,now:int):
        outcome={_Origin.RETURN_INTENT:ClosureOutcome.RETURNED_AFTER_INTENT,_Origin.EARLY_BREAK:ClosureOutcome.EARLY_RETURN,_Origin.FINAL_CALLBACK:ClosureOutcome.RETURNED_AFTER_CALLBACK}.get(self._origin)
        if outcome is None: return
        if not self._flush_pause_events(): return
        if not self._commit_many((("RETURN_CONFIRMED",EventClass.DERIVED,{"closure_outcome":outcome.value}),("COSINE_SESSION_CLOSED",EventClass.DERIVED,self._closure_payload("RETURN_CONFIRMED",outcome.value))),now): return
        self._closure_reason="RETURN_CONFIRMED"; self._closure_outcome=outcome.value; self._phase=CosinePhase.CLOSED
        self._close_presentations(); self._clear_recovery(); self._clear_monitor_control(); self._break_continuity()

    def _relapse(self,now:int):
        if self._origin is _Origin.FINAL_CALLBACK:
            hidden=self._phase in {CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING,CosinePhase.CLOSURE_CONFIRMING}
            event="CLOSURE_CONFIRMATION_INTERRUPTED" if self._phase is CosinePhase.CLOSURE_CONFIRMING else "RETURN_VERIFICATION_INTERRUPTED"
            specs=[(event,EventClass.OBSERVED,{"reason":"OTT_RELAPSE","branch":self._origin.value})]
            if hidden: specs.append(("FINAL_CALLBACK_RESTORED_AFTER_RELAPSE",EventClass.DERIVED,{"request_id":self._final.request_id if self._final else ""}))
            if not self._commit_many(tuple(specs),now): return
            self._phase=CosinePhase.FINAL_CALLBACK_ACTIVE
            if self._final:
                self._final.visible=True
                if hidden: self._effects.append(CosineEffect(EffectKind.RESTORE_FINAL_CALLBACK,self._generation,self._final.request_id,self._current_platform,message="Restore same logical final callback"))
            self._clear_recovery(); return
        self._interrupt(now,"OTT_RELAPSE")

    def _interrupt(self,now:int,reason:str):
        origin=self._origin
        if origin is _Origin.NONE: return
        event="CLOSURE_CONFIRMATION_INTERRUPTED" if self._phase is CosinePhase.CLOSURE_CONFIRMING else "RETURN_VERIFICATION_INTERRUPTED"
        if not self._commit(event,EventClass.OBSERVED,now,payload={"reason":reason,"branch":origin.value}): return
        self._clear_recovery()
        if origin is _Origin.RETURN_INTENT: self._phase=CosinePhase.RETURN_INTENT_OBSERVING
        elif origin is _Origin.EARLY_BREAK: self._phase=CosinePhase.BREAK_ACTIVE
        else: self._phase=CosinePhase.FINAL_CALLBACK_ACTIVE

    def _interrupt_final_visible(self,now:int):
        if self._commit("RETURN_VERIFICATION_INTERRUPTED",EventClass.OBSERVED,now,payload={"reason":"FOCUS_NOT_CONFIRMED","branch":_Origin.FINAL_CALLBACK.value}): self._clear_recovery()

    def _interrupt_final_silent(self,now:int):
        event="CLOSURE_CONFIRMATION_INTERRUPTED" if self._phase is CosinePhase.CLOSURE_CONFIRMING else "RETURN_VERIFICATION_INTERRUPTED"
        if not self._commit(event,EventClass.OBSERVED,now,payload={"reason":"FOCUS_NOT_CONFIRMED","branch":_Origin.FINAL_CALLBACK.value}): return
        self._phase=CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING; self._origin=_Origin.FINAL_CALLBACK
        self._candidate=False; self._verify_ns=0; self._closure_ns=0

    def _request_intent(self,now:int):
        if self._intent: return
        rid=self._rid("intent")
        if not self._commit_many((("INTENT_GATE_ELIGIBLE",EventClass.DERIVED,{}),("INTENT_GATE_REQUESTED",EventClass.DERIVED,{"request_id":rid})),now,request_id=rid): return
        self._intent=_Request(rid,now); self._phase=CosinePhase.INTENT_GATE_PENDING
        self._effects.append(CosineEffect(EffectKind.SHOW_INTENT_GATE,self._generation,rid,self._current_platform,self._current_content(),"COSINE intention gate"))

    def _display_intent(self,c:CosineCommand):
        r=self._intent
        if self._phase is not CosinePhase.INTENT_GATE_PENDING or not r or c.request_id!=r.request_id: return self._reject("Intention gate request is no longer current")
        if r.displayed_ns: return CommandResult(True,False,"Intention gate already displayed",self.snapshot(now_ns=c.occurred_monotonic_ns))
        if not self._commit("INTENT_GATE_DISPLAYED",EventClass.PRESENTATION,c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Display acknowledgement was not durably accepted")
        r.displayed_ns=c.occurred_monotonic_ns; r.visible=True; self._phase=CosinePhase.INTENT_GATE_ACTIVE
        return CommandResult(True,False,"Intention gate display accepted",self.snapshot(now_ns=c.occurred_monotonic_ns))

    def _intent_action(self,c:CosineCommand):
        r=self._intent
        if self._phase is not CosinePhase.INTENT_GATE_ACTIVE or not r or c.request_id!=r.request_id or not r.displayed_ns: return self._reject("Displayed intention gate is not current")
        if c.choice is CosineChoice.RETURN_INTENTION:
            if not self._commit_many((("RETURN_INTENT_RECORDED",EventClass.USER_ACTION,{"choice":c.choice.value}),("RETURN_INTENT_WINDOW_STARTED",EventClass.DERIVED,{})),c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Return intention was not durably accepted")
            self._intent_window_ns=0; self._phase=CosinePhase.RETURN_INTENT_OBSERVING; r.visible=False
            self._break_continuity()
            self._effects.append(CosineEffect(EffectKind.CLOSE_INTENT_GATE,self._generation,r.request_id))
            return CommandResult(True,True,"Return intention recorded",self.snapshot(now_ns=c.occurred_monotonic_ns))
        if c.choice is CosineChoice.INTENTIONAL_BREAK:
            did=self._rid("duration")
            if not self._commit_many((("BREAK_INTENT_RECORDED",EventClass.USER_ACTION,{"choice":c.choice.value}),("DURATION_REQUESTED",EventClass.DERIVED,{"request_id":did,"branch":"DIRECT_BREAK"})),c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Break intention was not durably accepted")
            self._duration=_Request(did,c.occurred_monotonic_ns); self._duration_variant="DIRECT_BREAK"; self._phase=CosinePhase.DURATION_ENTRY; r.visible=False
            effects=[CosineEffect(EffectKind.CLOSE_INTENT_GATE,self._generation,r.request_id)]
            effects.append(CosineEffect(EffectKind.SHOW_DURATION_ENTRY,self._generation,did,self._current_platform,message="Choose 10 to 200 minutes",presentation_variant="DIRECT_BREAK"))
            self._effects.extend(effects)
            return CommandResult(True,True,"Break intention recorded; duration required",self.snapshot(now_ns=c.occurred_monotonic_ns))
        return self._reject("Intention action is invalid")

    def _failed_return(self,now:int):
        if self._duration: return
        rid=self._rid("duration")
        if not self._commit_many((("RETURN_INTENT_CONVERTED_TO_BREAK",EventClass.DERIVED,{"observed_ott_seconds":self._intent_window_ns/_NS}),("DURATION_REQUESTED",EventClass.DERIVED,{"request_id":rid,"branch":"FAILED_RETURN_INTENTION"})),now,request_id=rid): return
        self._duration=_Request(rid,now); self._duration_variant="FAILED_RETURN_INTENTION"; self._phase=CosinePhase.DURATION_ENTRY
        self._effects.append(CosineEffect(EffectKind.SHOW_DURATION_ENTRY,self._generation,rid,self._current_platform,message="Choose 10 to 200 minutes",presentation_variant="FAILED_RETURN_INTENTION"))

    def _submit_duration(self,c:CosineCommand):
        r=self._duration; minutes=c.duration_minutes
        if self._phase is not CosinePhase.DURATION_ENTRY or not r or c.request_id!=r.request_id: return self._reject("Duration request is no longer current")
        if isinstance(minutes,bool) or not isinstance(minutes,int) or not self._policy.break_minimum_minutes<=minutes<=self._policy.break_maximum_minutes: return self._reject("Break duration must be an integer from 10 through 200")
        start=self._effective(c.occurred_monotonic_ns); deadline=start+_to_ns(minutes*60); aid=self._rid("break-ack")
        specs=(("BREAK_DURATION_COMMITTED",EventClass.USER_ACTION,{"duration_minutes":minutes}),("BREAK_STARTED",EventClass.DERIVED,{"duration_minutes":minutes,"break_start_effective_ns":start,"break_deadline_effective_ns":deadline}),("BREAK_ACK_REQUESTED",EventClass.DERIVED,{"request_id":aid}))
        if not self._commit_many(specs,c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Break duration was not durably accepted")
        self._phase=CosinePhase.BREAK_COMMIT_PENDING; self._chosen_minutes=minutes; self._break_start=start; self._break_deadline=deadline
        self._ack=_Request(aid,c.occurred_monotonic_ns); self._phase=CosinePhase.BREAK_ACTIVE
        effects=[CosineEffect(EffectKind.CLOSE_DURATION_ENTRY,self._generation,r.request_id)]
        effects.append(CosineEffect(EffectKind.SHOW_BREAK_ACK,self._generation,aid,self._current_platform,message="Intentional break accepted",duration_minutes=self._chosen_minutes))
        self._effects.extend(effects)
        return CommandResult(True,True,"Break duration committed",self.snapshot(now_ns=c.occurred_monotonic_ns))

    def _break_ack(self,c:CosineCommand):
        r=self._ack
        if not r or c.request_id!=r.request_id: return self._reject("Break acknowledgement is no longer current")
        if c.kind is CommandKind.BREAK_ACK_DISPLAYED:
            if r.displayed_ns: return CommandResult(True,False,"Break acknowledgement already displayed",self.snapshot(now_ns=c.occurred_monotonic_ns))
            if not self._commit("BREAK_ACK_DISPLAYED",EventClass.PRESENTATION,c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Break acknowledgement display was not durable")
            r.displayed_ns=c.occurred_monotonic_ns; r.visible=True
            return CommandResult(True,False,"Break acknowledgement displayed",self.snapshot(now_ns=c.occurred_monotonic_ns))
        if not r.displayed_ns: return self._reject("Break acknowledgement was not factually displayed")
        if c.choice not in {None,CosineChoice.ACKNOWLEDGE}: return self._reject("Break acknowledgement action is invalid")
        if not self._commit("BREAK_ACKNOWLEDGED",EventClass.USER_ACTION,c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Break acknowledgement was not durable")
        r.visible=False; self._effects.append(CosineEffect(EffectKind.CLOSE_BREAK_ACK,self._generation,r.request_id))
        return CommandResult(True,True,"Break acknowledged; deadline unchanged",self.snapshot(now_ns=c.occurred_monotonic_ns))

    def _request_final(self,now:int):
        if self._final: return
        rid=self._rid("final")
        if not self._commit_many((("BREAK_DEADLINE_REACHED",EventClass.DERIVED,{}),("FINAL_CALLBACK_REQUESTED",EventClass.DERIVED,{"request_id":rid})),now,request_id=rid): return
        self._clear_recovery(); self._final=_Request(rid,now); self._phase=CosinePhase.FINAL_CALLBACK_PENDING
        self._effects.append(CosineEffect(EffectKind.SHOW_FINAL_CALLBACK,self._generation,rid,self._current_platform,message="Hope you enjoyed the show. Now it's time to focus."))

    def _display_final(self,c:CosineCommand):
        r=self._final
        if self._phase is not CosinePhase.FINAL_CALLBACK_PENDING or not r or c.request_id!=r.request_id: return self._reject("Final callback request is no longer current")
        if not self._commit("FINAL_CALLBACK_DISPLAYED",EventClass.PRESENTATION,c.occurred_monotonic_ns,request_id=r.request_id): return self._reject("Final callback display was not durable")
        r.displayed_ns=c.occurred_monotonic_ns; r.visible=True; self._phase=CosinePhase.FINAL_CALLBACK_ACTIVE
        return CommandResult(True,False,"Final callback display accepted",self.snapshot(now_ns=c.occurred_monotonic_ns))

    def _hide_final(self,now:int):
        r=self._final
        if not r or not r.visible or not self._commit("FINAL_CALLBACK_HIDDEN_FOR_FOCUS",EventClass.DERIVED,now,request_id=r.request_id): return
        r.visible=False; self._phase=CosinePhase.FINAL_CALLBACK_HIDDEN_VERIFYING
        self._effects.append(CosineEffect(EffectKind.HIDE_FINAL_CALLBACK,self._generation,r.request_id,self._current_platform,message="Hide callback; recovery continues"))

    def _supported_interval(self,o:CosineObservation,kind:_Kind):
        if not self._last_obs_ns: return 0
        if o.observation_sequence<=0 or self._last_obs_seq<=0 or o.observation_sequence!=self._last_obs_seq+1:
            self._gap(o.observed_monotonic_ns,"NON_ADJACENT_OBSERVATION_SEQUENCE"); return 0
        if kind is not self._last_kind or kind not in {_Kind.OTT,_Kind.FOCUS}: return 0
        # Timestamp distance is never evidence by itself. Monitor supplies a
        # conservative duration supported by its existing polling cadence.
        return min(max(0,o.observed_monotonic_ns-self._last_obs_ns),o.supported_interval_ns)

    def _flush_pause_events(self):
        while self._pending_pause_events:
            name,occurred_ns=self._pending_pause_events[0]
            if not self._commit(name,EventClass.OBSERVED,occurred_ns): return False
            self._pending_pause_events.pop(0)
        return True

    def _credit(self,elapsed:int,kind:_Kind):
        if kind is _Kind.OTT:
            if self._last_platform and self._session_id: self._platform(self._last_platform).foreground_ns+=elapsed
            if self._phase is CosinePhase.OBSERVING_OTT: self._initial_ns+=elapsed
            elif self._phase is CosinePhase.RETURN_INTENT_OBSERVING: self._intent_window_ns+=elapsed
        elif kind is _Kind.FOCUS and self._candidate:
            if self._phase is CosinePhase.CLOSURE_CONFIRMING: self._closure_ns+=elapsed
            else: self._verify_ns+=elapsed

    def _remember(self,o:CosineObservation,kind:_Kind):
        self._last_obs_ns=o.observed_monotonic_ns; self._last_obs_seq=o.observation_sequence; self._last_kind=kind
        self._last_platform=o.platform.platform_key if o.platform else ""
        if kind is not _Kind.UNKNOWN: self._quality="OBSERVED"

    def _gap(self,now:int,reason:str):
        self._quality="EVIDENCE_GAP"
        if self._session_id and self._phase not in {CosinePhase.CLOSED,CosinePhase.SHUTDOWN}: self._commit("EVIDENCE_GAP",EventClass.OBSERVED,now,payload={"reason":reason})

    def _effective(self,raw:int):
        paused=self._paused_total+(raw-self._pause_started if self._paused and self._pause_started and raw>self._pause_started else 0)
        return raw-paused
    def _deadline_reached(self,raw:int): return bool(self._break_deadline and self._effective(raw)>=self._break_deadline)
    def _break_continuity(self): self._last_obs_ns=0; self._last_obs_seq=0; self._last_kind=_Kind.UNKNOWN; self._last_platform=""

    def _content(self,e:CertifiedPlatformEvidence,now:int):
        if not e.content_title: return
        p=self._platform(e.platform_key)
        if p.content_title.casefold()==e.content_title.casefold(): return
        if not self._commit("CONTENT_OBSERVED",EventClass.OBSERVED,now,platform=e.platform_key,content=e.content_title,evidence_token=e.evidence_token): return
        p.content_title=e.content_title; p.content_history=(*p.content_history,e.content_title)[-100:]
    def _platform(self,key:str):
        if key not in self._platforms: self._platforms[key]=_PlatformState(key)
        return self._platforms[key]
    def _current_content(self): return self._platforms[self._current_platform].content_title if self._current_platform in self._platforms else ""

    def _commit_many(self,specs:tuple[tuple[str,EventClass,Mapping[str,object]],...],now:int,*,request_id:str=""):
        events=tuple(self._event(name,kind,now,request_id=request_id,payload=payload,sequence=self._event_sequence+1+i) for i,(name,kind,payload) in enumerate(specs))
        if not self._write(events): return False
        self._event_sequence+=len(events); return True
    def _commit(self,name:str,kind:EventClass,now:int,*,platform:str="",content:str="",request_id:str="",evidence_token:str="",payload:Mapping[str,object]|None=None):
        e=self._event(name,kind,now,platform=platform,content=content,request_id=request_id,evidence_token=evidence_token,payload=payload,sequence=self._event_sequence+1)
        if not self._write((e,)): return False
        self._event_sequence+=1; return True
    def _event(self,name:str,kind:EventClass,now:int,*,platform:str="",content:str="",request_id:str="",evidence_token:str="",payload:Mapping[str,object]|None=None,session_id:str|None=None,generation:int|None=None,sequence:int|None=None):
        wall=self._wall()
        if wall.tzinfo is None or wall.utcoffset() is None: raise RuntimeError("COSINE wall clock must be timezone-aware")
        if self._parent_session_id is None: raise RuntimeError("COSINE parent session is not durably bound")
        return CosineEvent(secrets.token_hex(16),self._parent_session_id,self._session_id if session_id is None else session_id,self._event_sequence+1 if sequence is None else sequence,name,kind,wall.astimezone(timezone.utc).isoformat(timespec="microseconds"),now,self._generation if generation is None else generation,platform,_bounded(content),request_id,evidence_token,json.dumps(dict(payload or {}),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False))
    def _write(self,events):
        try: accepted=bool(self._sink.append_cosine_events(events)); detail="durable event sink rejected transition"
        except Exception as exc: accepted=False; detail=str(exc)
        self._durable_health=accepted; self._durable_detail="" if accepted else " ".join(detail.split())[:240]
        return accepted

    def _closure_payload(self,reason:str,outcome:str):
        seconds={k:round(v.foreground_ns/_NS,6) for k,v in self._platforms.items()}
        return {"closure_reason":reason,"closure_outcome":outcome,"foreground_ott_seconds":round(sum(seconds.values()),6),"platform_seconds":seconds,"hopper_count":self._hopper_count,"chosen_break_minutes":self._chosen_minutes}
    @staticmethod
    def _external_outcome(reason):
        if reason is ClosureReason.STUDY_MODE_ACTIVATED: return ClosureOutcome.STUDY_PREEMPTION
        if reason is ClosureReason.EMERGENCY: return ClosureOutcome.EMERGENCY
        return ClosureOutcome.INCOMPLETE
    def _close_presentations(self):
        for r in (self._intent,self._duration,self._ack,self._final):
            if r:
                self._effects.append(CosineEffect(EffectKind.CLOSE_PRESENTATION,self._generation,r.request_id))
                r.visible=False
        # Unchanged behaviour: a terminal close already cleared Study
        # inhibition through the shared helper before Phase 1 split the two
        # latches apart.  Keep that exact semantics here at the call site.
        self._study_suppressed=False
    def _current_presentation_request(self):
        if self._phase in {CosinePhase.INTENT_GATE_PENDING,CosinePhase.INTENT_GATE_ACTIVE}: return self._intent
        if self._phase is CosinePhase.DURATION_ENTRY: return self._duration
        if self._phase in {CosinePhase.BREAK_COMMIT_PENDING,CosinePhase.BREAK_ACTIVE} and self._ack and (self._ack.visible or not self._ack.displayed_ns): return self._ack
        if self._phase in {CosinePhase.FINAL_CALLBACK_PENDING,CosinePhase.FINAL_CALLBACK_ACTIVE}: return self._final
        return None
    def _presentation_restore_effect(self,request,was_visible):
        if request is self._intent: return CosineEffect(EffectKind.SHOW_INTENT_GATE,self._generation,request.request_id,self._current_platform,self._current_content(),"COSINE intention gate")
        if request is self._duration: return CosineEffect(EffectKind.SHOW_DURATION_ENTRY,self._generation,request.request_id,self._current_platform,message="Choose 10 to 200 minutes",presentation_variant=self._duration_variant)
        if request is self._ack: return CosineEffect(EffectKind.SHOW_BREAK_ACK,self._generation,request.request_id,self._current_platform,message="Intentional break accepted",duration_minutes=self._chosen_minutes)
        if request is self._final:
            kind=EffectKind.RESTORE_FINAL_CALLBACK if was_visible else EffectKind.SHOW_FINAL_CALLBACK
            return CosineEffect(kind,self._generation,request.request_id,self._current_platform,message="Hope you enjoyed the show. Now it's time to focus.")
        return None
    def _clear_recovery(self): self._origin=_Origin.NONE; self._candidate=False; self._verify_ns=0; self._closure_ns=0
    def _rid(self,purpose): return f"cosine-{purpose}-{self._generation}-{secrets.token_hex(6)}"
    def _reset_episode(self):
        self._event_sequence=0; self._platforms={}; self._current_platform=""; self._last_evidence_token=""; self._hopper_count=0
        self._initial_ns=0; self._intent_window_ns=0; self._intent=None; self._duration=None; self._duration_variant=""; self._ack=None; self._final=None
        self._chosen_minutes=None; self._break_start=0; self._break_deadline=0; self._clear_recovery()
        self._closure_reason=""; self._closure_outcome=""; self._quality="NO_EVIDENCE"; self._clear_monitor_control(); self._break_continuity()
        # M3.  A fresh episode is a safe transition, so Study inhibition from
        # the previous episode must not leak into it.
        self._study_suppressed=False
    def _reject(self,message): return CommandResult(False,False,message,self.snapshot())

def _process_name(value):
    text=str(value or "").strip().casefold().replace("\\","/").rsplit("/",1)[-1]
    return text if text.endswith(".exe") else f"{text}.exe" if text else ""
def _host_name(value):
    host=str(value or "").strip().casefold().strip(".")
    return "" if "://" in host else host if host and all(c.isalnum() or c in ".-" for c in host) else ""
def _supporting_title(value,platform):
    title=" ".join(str(value or "").split()).strip(" -|"); lowered=title.casefold()
    for suffix in (PLATFORM_LABELS.get(platform,""),"Google Chrome","Microsoft Edge","Mozilla Firefox"):
        marker=f" - {suffix}".casefold()
        if suffix and lowered.endswith(marker): title=title[:-len(marker)].strip(" -|"); lowered=title.casefold()
    return "" if not title or lowered in {"home","browse","who's watching",PLATFORM_LABELS.get(platform,"").casefold()} else _bounded(title)
def _bounded(value): return " ".join(str(value or "").split())[:MAX_CONTENT_TITLE]
def _now_ns(value):
    current=time.monotonic_ns() if value is None else int(value)
    if current<=0: raise ValueError("positive monotonic time required")
    return current
def _to_ns(value): return int(float(value)*_NS)

__all__=["BREAK_MINUTES_MAX","BREAK_MINUTES_MIN","CLOSURE_CONFIRMATION_SECONDS","COSINE_SCHEMA_VERSION","CheckinMode","ClosureOutcome","ClosureReason","CommandKind","CommandResult","CosineChoice","CosineCommand","CosineEffect","CosineEvent","CosineEventSink","CosineObservation","CosinePhase","CosinePolicy","CosineRuntime","CosineSnapshot","CertifiedPlatformEvidence","EffectKind","EventClass","EvidenceSource","FINAL_CALLBACK_HIDE_SECONDS","INITIAL_GATE_SECONDS","PLATFORM_KEYS","PLATFORM_LABELS","PlatformSnapshot","RETURN_INTENT_WINDOW_SECONDS","RETURN_VERIFICATION_SECONDS","certify_platform_evidence"]
