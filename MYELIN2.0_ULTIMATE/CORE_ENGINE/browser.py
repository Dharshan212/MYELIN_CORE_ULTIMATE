"""Certified, privacy-safe browser evidence for the MYELIN Core Engine.

This module has one narrow responsibility: turn the browser address bar from
the *already observed foreground window* into certified, reduced evidence.

Authority order
---------------
1. The foreground process must be a supported browser.
2. UI Automation must attach to the exact foreground HWND.
3. The attached window must belong to the observed process ID.
4. A visible address-bar control must be identified by browser-chrome metadata.
5. Only that selected control may expose a value.
6. The URL host and path decide the evidence.

The window title is deliberately absent from this authority.  A title can help
another layer display context, but it can never certify a host, URL, route or
study resource.

Privacy boundary
----------------
The raw address never leaves the local reader function.  Public observations
contain only a platform, a route marker and a redacted address.  Query text,
fragments, account names and content IDs are never returned or logged here.
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final
from urllib.parse import parse_qs, unquote, urlsplit


class BrowserKind(str, Enum):
    """Supported Chromium browser families."""

    CHROME = "chrome"
    EDGE = "edge"
    BRAVE = "brave"
    VIVALDI = "vivaldi"
    OPERA = "opera"
    OPERA_GX = "opera_gx"


class BrowserUrlReadStatus(str, Enum):
    """Factual result of one bounded address-bar read."""

    OK = "ok"
    INVALID_WINDOW = "invalid_window"
    NOT_SUPPORTED_BROWSER = "not_supported_browser"
    DEPENDENCY_MISSING = "dependency_missing"
    WINDOW_NOT_FOUND = "window_not_found"
    WINDOW_IDENTITY_MISMATCH = "window_identity_mismatch"
    ADDRESS_BAR_NOT_FOUND = "address_bar_not_found"
    ADDRESS_VALUE_EMPTY = "address_value_empty"
    ADDRESS_VALUE_INVALID = "address_value_invalid"
    ACCESS_DENIED = "access_denied"
    READER_ERROR = "reader_error"


class UrlEvidenceKind(str, Enum):
    """Privacy-safe facts that can be proved from a URL route."""

    CONFIRMED_SHORT_FEED = "confirmed_short_feed"
    CONFIRMED_SELECTED_VIDEO = "confirmed_selected_video"
    CONFIRMED_SOCIAL_FEED = "confirmed_social_feed"
    CONFIRMED_STATIC_ENTRY = "confirmed_static_entry"
    CONFIRMED_PRODUCTIVE_PAGE = "confirmed_productive_page"
    CONFIRMED_MESSAGING_PAGE = "confirmed_messaging_page"
    NOT_CONFIRMED = "not_confirmed"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    INVALID_ADDRESS = "invalid_address"
    URL_UNAVAILABLE = "url_unavailable"


class EvidenceConfidence(str, Enum):
    HIGH = "high"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class BrowserAdapterSpec:
    """Trusted process and address-bar metadata for one browser family."""

    browser: BrowserKind
    display_name: str
    process_names: tuple[str, ...]
    automation_id_hints: tuple[str, ...]
    accessible_name_hints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UrlSurfaceEvidence:
    """Reduced URL evidence; a raw browser address cannot be stored here."""

    kind: UrlEvidenceKind
    platform_key: str
    platform_label: str
    marker: str
    redacted_address: str
    confidence: EvidenceConfidence
    reason: str
    resource_token: str = ""
    certified_host: str = ""

    @property
    def is_strong(self) -> bool:
        return self.kind in _STRONG_EVIDENCE_KINDS


@dataclass(frozen=True, slots=True)
class BrowserUrlObservation:
    """One sanitised result from the exact-window UIA reader."""

    status: BrowserUrlReadStatus
    browser: BrowserKind | None = None
    browser_label: str = ""
    process_name: str = ""
    evidence: UrlSurfaceEvidence | None = None
    read_method: str = ""
    candidate_count: int = 0
    reason: str = ""
    diagnostic_candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BrowserEvidenceSnapshot:
    """Certified browser fact delivered to the rest of the Core Engine.

    ``authoritative`` can remain true briefly while a previous strong result is
    held across a transient UIA failure.  That hold is valid only for the same
    process and HWND and is bounded by :class:`EvidenceStabilityPolicy`.
    """

    observation_sequence: int
    hwnd: int
    process_id: int
    process_name: str
    browser: BrowserKind | None
    browser_label: str
    supported_browser: bool
    read_attempted: bool
    status: BrowserUrlReadStatus
    evidence: UrlSurfaceEvidence | None
    holding_previous_strong_evidence: bool = False
    consecutive_weak_samples: int = 0
    reader_disabled_for_session: bool = False
    reason: str = ""

    @property
    def authoritative(self) -> bool:
        """True only when strong evidence belongs to this certified scope."""

        return bool(
            self.supported_browser
            and self.hwnd > 0
            and self.process_id > 0
            and self.evidence is not None
            and self.evidence.is_strong
            and (
                self.status is BrowserUrlReadStatus.OK
                or self.holding_previous_strong_evidence
            )
        )

    @property
    def host_authoritative(self) -> bool:
        """True only for a host read from this exact foreground browser sample."""

        return bool(
            self.supported_browser
            and self.hwnd > 0
            and self.process_id > 0
            and self.status is BrowserUrlReadStatus.OK
            and self.evidence is not None
            and bool(self.evidence.certified_host)
        )

    @property
    def platform_key(self) -> str:
        return self.evidence.platform_key if self.evidence is not None else ""

    @property
    def redacted_address(self) -> str:
        return self.evidence.redacted_address if self.evidence is not None else ""

    @property
    def certified_host(self) -> str:
        """Return the reduced host proven by the exact address-bar read."""

        return self.evidence.certified_host if self.evidence is not None else ""


@dataclass(frozen=True, slots=True)
class AddressBarCandidate:
    """Structural UIA metadata collected before any control value is read."""

    index: int
    automation_id: str
    accessible_name: str
    in_browser_top_band: bool
    visible: bool


@dataclass(frozen=True, slots=True)
class EvidenceStabilityPolicy:
    """Short grace period for temporary address-bar/UIA read failures."""

    release_after_weak_samples: int = 3
    maximum_hold_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.release_after_weak_samples < 1:
            raise ValueError("release_after_weak_samples must be at least 1")
        if not math.isfinite(float(self.maximum_hold_seconds)):
            raise ValueError("maximum_hold_seconds must be finite")
        if self.maximum_hold_seconds < 0:
            raise ValueError("maximum_hold_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class _StableEvidenceView:
    evidence: UrlSurfaceEvidence | None
    holding_previous_strong_evidence: bool
    consecutive_weak_samples: int
    reason: str


_COMMON_AUTO_ID_HINTS: Final = (
    "omnibox",
    "address",
    "urlbar",
    "url bar",
    "location",
)
_COMMON_NAME_HINTS: Final = (
    "address and search bar",
    "address bar",
    "search or enter web address",
    "search google or type a url",
    "search or type web address",
    "location bar",
    "omnibox",
)

BROWSER_ADAPTERS: Final = (
    BrowserAdapterSpec(BrowserKind.CHROME, "Chrome", ("chrome.exe",), _COMMON_AUTO_ID_HINTS, _COMMON_NAME_HINTS),
    BrowserAdapterSpec(BrowserKind.EDGE, "Edge", ("msedge.exe",), _COMMON_AUTO_ID_HINTS, _COMMON_NAME_HINTS),
    BrowserAdapterSpec(BrowserKind.BRAVE, "Brave", ("brave.exe",), _COMMON_AUTO_ID_HINTS, _COMMON_NAME_HINTS),
    BrowserAdapterSpec(BrowserKind.VIVALDI, "Vivaldi", ("vivaldi.exe",), _COMMON_AUTO_ID_HINTS, _COMMON_NAME_HINTS),
    BrowserAdapterSpec(BrowserKind.OPERA, "Opera", ("opera.exe",), _COMMON_AUTO_ID_HINTS, _COMMON_NAME_HINTS),
    BrowserAdapterSpec(BrowserKind.OPERA_GX, "Opera GX", ("opera_gx.exe",), _COMMON_AUTO_ID_HINTS, _COMMON_NAME_HINTS),
)

_STRONG_EVIDENCE_KINDS: Final = frozenset(
    {
        UrlEvidenceKind.CONFIRMED_SHORT_FEED,
        UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO,
        UrlEvidenceKind.CONFIRMED_SOCIAL_FEED,
        UrlEvidenceKind.CONFIRMED_STATIC_ENTRY,
        UrlEvidenceKind.CONFIRMED_PRODUCTIVE_PAGE,
        UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE,
    }
)
_SCHEME_RE: Final = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_HOSTISH_RE: Final = re.compile(
    r"^(?:localhost(?::\d+)?|(?:[a-z0-9-]+\.)+[a-z]{2,})(?:[/:?#]|$)",
    re.IGNORECASE,
)
_INTERNAL_PREFIXES: Final = (
    "about:",
    "chrome://",
    "edge://",
    "brave://",
    "vivaldi://",
    "opera://",
)


def normalise_process_name(value: object) -> str:
    """Normalise only the executable name; never infer it from a title."""

    text = str(value or "").strip().casefold()
    if not text:
        return ""
    return text if text.endswith(".exe") else f"{text}.exe"


def adapter_for_process(process_name: object) -> BrowserAdapterSpec | None:
    normalised = normalise_process_name(process_name)
    return next(
        (
            adapter
            for adapter in BROWSER_ADAPTERS
            if normalised in adapter.process_names
        ),
        None,
    )


def _normalise_space(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _host_matches(host: str, domain: str) -> bool:
    """Accept the exact domain or a subdomain, never an evil suffix."""

    clean_host = host.casefold().strip(".")
    clean_domain = domain.casefold().strip(".")
    return clean_host == clean_domain or clean_host.endswith(f".{clean_domain}")


def _prepare_for_split(address_value: object) -> str:
    text = _normalise_space(address_value)
    if not text:
        return ""
    lowered = text.casefold()
    if _SCHEME_RE.match(text) or lowered.startswith(("about:", "file://")):
        return text
    if _HOSTISH_RE.match(text):
        return f"https://{text}"
    return text


def _path_segments(path: str) -> tuple[str, ...]:
    return tuple(unquote(part).casefold() for part in path.split("/") if part)


def _certified_host_from_address(address_value: object) -> str:
    """Return only the parsed hostname; never return the raw address."""

    prepared = _prepare_for_split(address_value)
    if not prepared or prepared.casefold().startswith(_INTERNAL_PREFIXES):
        return ""
    try:
        return (urlsplit(prepared).hostname or "").casefold().strip(".")
    except (TypeError, ValueError):
        return ""


def _redacted(platform_label: str, marker: str = "") -> str:
    base = {
        "Instagram": "instagram.com",
        "Facebook": "facebook.com",
        "YouTube": "youtube.com",
        "Snapchat": "snapchat.com",
        "TikTok": "tiktok.com",
        "Twitch": "twitch.tv",
        "LinkedIn": "linkedin.com",
        "X": "x.com",
    }.get(platform_label, platform_label.casefold() or "unknown")
    return f"{base}/{marker}/[redacted]" if marker else base


def _evidence(
    kind: UrlEvidenceKind,
    platform_key: str,
    platform_label: str,
    marker: str,
    confidence: EvidenceConfidence,
    reason: str,
    resource_token: str = "",
) -> UrlSurfaceEvidence:
    if platform_label:
        redacted_address = _redacted(platform_label, marker)
    elif kind is UrlEvidenceKind.UNSUPPORTED_PLATFORM:
        redacted_address = "unsupported-host"
    else:
        redacted_address = ""
    return UrlSurfaceEvidence(
        kind=kind,
        platform_key=platform_key,
        platform_label=platform_label,
        marker=marker,
        redacted_address=redacted_address,
        confidence=confidence,
        reason=reason,
        resource_token=resource_token,
    )


def _opaque_resource_token(
    *,
    identity_secret: bytes | None,
    platform: str,
    marker: str,
    content_identity: str,
) -> str:
    """Create a session-only exact identity without exposing the content ID."""

    if not identity_secret or not content_identity:
        return ""
    payload = f"{platform}\x1f{marker}\x1f{content_identity}".encode("utf-8")
    return hashlib.blake2b(
        payload,
        key=identity_secret,
        digest_size=16,
        person=b"MYELIN-URL-ID",
    ).hexdigest()


def classify_address_value(
    address_value: object,
    *,
    identity_secret: bytes | None = None,
) -> UrlSurfaceEvidence:
    """Reduce one address into host/path evidence without returning the URL."""

    prepared = _prepare_for_split(address_value)
    if not prepared:
        return _evidence(UrlEvidenceKind.URL_UNAVAILABLE, "", "", "", EvidenceConfidence.NONE, "The address-bar value was empty.")

    if prepared.casefold().startswith(_INTERNAL_PREFIXES):
        return UrlSurfaceEvidence(
            kind=UrlEvidenceKind.CONFIRMED_STATIC_ENTRY,
            platform_key="browser",
            platform_label="Browser",
            marker="internal",
            redacted_address="browser://internal",
            confidence=EvidenceConfidence.HIGH,
            reason="A browser-internal page was observed.",
        )

    try:
        parsed = urlsplit(prepared)
        host = (parsed.hostname or "").casefold().strip(".")
    except (TypeError, ValueError):
        host = ""
        parsed = None
    if not host or parsed is None:
        return _evidence(UrlEvidenceKind.INVALID_ADDRESS, "", "", "", EvidenceConfidence.NONE, "No valid web host was exposed by the address bar.")

    parts = _path_segments(parsed.path)
    first = parts[0] if parts else ""

    # INSTRUCTION: URL host and path are the only classifiers below.
    if _host_matches(host, "instagram.com"):
        if first == "direct":
            return _evidence(UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE, "instagram", "Instagram", first, EvidenceConfidence.HIGH, "An Instagram messaging route was observed.")
        if first in {"reel", "reels"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "instagram", "Instagram", first, EvidenceConfidence.HIGH, "An Instagram reel route was observed.")
        if first in {"accounts", "developer"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_STATIC_ENTRY, "instagram", "Instagram", first, EvidenceConfidence.HIGH, "An Instagram account or entry route was observed.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "instagram", "Instagram", "", EvidenceConfidence.NONE, "No recognised Instagram route was proved.")

    if _host_matches(host, "facebook.com"):
        if first in {"messages", "messaging"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE, "facebook", "Facebook", first, EvidenceConfidence.HIGH, "A Facebook messaging route was observed.")
        if first in {"reel", "reels"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "facebook", "Facebook", first, EvidenceConfidence.HIGH, "A Facebook reel route was observed.")
        if first in {"watch", "videos"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO, "facebook", "Facebook", first, EvidenceConfidence.HIGH, "A selected Facebook video route was observed.")
        if first in {"login", "recover", "reg"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_STATIC_ENTRY, "facebook", "Facebook", first, EvidenceConfidence.HIGH, "A Facebook entry route was observed.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "facebook", "Facebook", "", EvidenceConfidence.NONE, "No recognised Facebook route was proved.")

    if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
        if first == "shorts":
            return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "youtube", "YouTube", first, EvidenceConfidence.HIGH, "YouTube Shorts was proved by the URL path.")
        if first in {"watch", "live", "embed"} or _host_matches(host, "youtu.be"):
            marker = first if first in {"watch", "live", "embed"} else "watch"
            if _host_matches(host, "youtu.be"):
                content_identity = first
            elif marker == "watch":
                content_identity = str(
                    (parse_qs(parsed.query).get("v") or [""])[0]
                )
            else:
                content_identity = parts[1] if len(parts) > 1 else ""
            return _evidence(
                UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO,
                "youtube",
                "YouTube",
                marker,
                EvidenceConfidence.HIGH,
                "A selected YouTube video route was observed.",
                resource_token=_opaque_resource_token(
                    identity_secret=identity_secret,
                    platform="youtube",
                    marker=marker,
                    content_identity=content_identity,
                ),
            )
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "youtube", "YouTube", "", EvidenceConfidence.NONE, "The YouTube URL did not prove a selected video or Shorts route.")

    if _host_matches(host, "snapchat.com"):
        if first == "spotlight":
            return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "snapchat", "Snapchat", first, EvidenceConfidence.HIGH, "Snapchat Spotlight was proved by the URL path.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "snapchat", "Snapchat", "", EvidenceConfidence.NONE, "No recognised Snapchat route was proved.")

    if _host_matches(host, "tiktok.com"):
        if "video" in parts:
            return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "tiktok", "TikTok", "video", EvidenceConfidence.HIGH, "A direct TikTok video route was observed.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "tiktok", "TikTok", "", EvidenceConfidence.NONE, "No direct TikTok video route was proved.")

    if _host_matches(host, "clips.twitch.tv"):
        return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "twitch", "Twitch", "clips", EvidenceConfidence.HIGH, "The dedicated Twitch Clips host was observed.")

    if _host_matches(host, "twitch.tv"):
        if first in {"clip", "clips"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_SHORT_FEED, "twitch", "Twitch", first, EvidenceConfidence.HIGH, "A Twitch clips route was observed.")
        if first == "videos":
            return _evidence(UrlEvidenceKind.CONFIRMED_SELECTED_VIDEO, "twitch", "Twitch", first, EvidenceConfidence.HIGH, "A Twitch VOD route was observed.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "twitch", "Twitch", "", EvidenceConfidence.NONE, "The Twitch URL did not prove live, VOD or Clips state.")

    if _host_matches(host, "linkedin.com"):
        if first == "messaging":
            return _evidence(UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE, "linkedin", "LinkedIn", first, EvidenceConfidence.HIGH, "The LinkedIn messaging route was observed.")
        if first == "feed":
            return _evidence(UrlEvidenceKind.CONFIRMED_SOCIAL_FEED, "linkedin", "LinkedIn", first, EvidenceConfidence.HIGH, "The LinkedIn feed route was observed.")
        if first in {"jobs", "learning"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_PRODUCTIVE_PAGE, "linkedin", "LinkedIn", first, EvidenceConfidence.HIGH, "A productive LinkedIn route was observed.")
        if first in {"login", "checkpoint"}:
            return _evidence(UrlEvidenceKind.CONFIRMED_STATIC_ENTRY, "linkedin", "LinkedIn", first, EvidenceConfidence.HIGH, "A LinkedIn entry route was observed.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "linkedin", "LinkedIn", "", EvidenceConfidence.NONE, "The LinkedIn URL did not prove a managed route.")

    if _host_matches(host, "x.com") or _host_matches(host, "twitter.com"):
        if first == "messages":
            return _evidence(UrlEvidenceKind.CONFIRMED_MESSAGING_PAGE, "x", "X", first, EvidenceConfidence.HIGH, "The X messaging route was observed.")
        if first == "home":
            return _evidence(UrlEvidenceKind.CONFIRMED_SOCIAL_FEED, "x", "X", first, EvidenceConfidence.HIGH, "The X home feed route was observed.")
        if parts[:3] in (("i", "flow", "login"), ("i", "flow", "signup")):
            return _evidence(UrlEvidenceKind.CONFIRMED_STATIC_ENTRY, "x", "X", "login", EvidenceConfidence.HIGH, "An X entry route was observed.")
        return _evidence(UrlEvidenceKind.NOT_CONFIRMED, "x", "X", "", EvidenceConfidence.NONE, "The X URL did not prove a managed route.")

    return _evidence(UrlEvidenceKind.UNSUPPORTED_PLATFORM, "", "", "", EvidenceConfidence.NONE, "The certified host is not managed by MYELIN.")


def _looks_like_address(value: object) -> bool:
    text = _normalise_space(value)
    if not text or any(character in text for character in ("\n", "\r", "\t")):
        return False
    lowered = text.casefold()
    if lowered.startswith((*_INTERNAL_PREFIXES, "http://", "https://", "file://")):
        return True
    first_token = lowered.split("/", 1)[0].split("?", 1)[0]
    return "." in first_token and " " not in first_token


def _candidate_score(candidate: AddressBarCandidate, adapter: BrowserAdapterSpec) -> tuple[int, str]:
    auto_id = candidate.automation_id.casefold()
    accessible_name = candidate.accessible_name.casefold()
    auto_match = any(hint in auto_id for hint in adapter.automation_id_hints)
    name_match = any(hint in accessible_name for hint in adapter.accessible_name_hints)
    if not candidate.visible:
        return -1000, "invisible control rejected"
    if not (auto_match or name_match):
        return -500, "no address-bar identity"
    if not candidate.in_browser_top_band:
        return -250, "address identity outside browser chrome"
    score = 30 + (120 if auto_match else 0) + (90 if name_match else 0)
    return score, "trusted metadata in the browser top band"


def choose_address_bar_candidate(
    candidates: Iterable[AddressBarCandidate],
    adapter: BrowserAdapterSpec,
) -> tuple[AddressBarCandidate | None, str]:
    """Select by structural metadata only; do not inspect Edit values."""

    ranked = [
        (*_candidate_score(candidate, adapter), -candidate.index, candidate)
        for candidate in candidates
    ]
    if not ranked:
        return None, "No UIA Edit controls were exposed."
    ranked.sort(key=lambda item: (item[0], item[2]), reverse=True)
    score, reason, _, selected = ranked[0]
    if score < 100:
        return None, "No Edit control had certified address-bar metadata."
    return selected, f"score={score}; {reason}"


def _control_metadata(control: Any, index: int, top_limit: int) -> AddressBarCandidate:
    """INSTRUCTION: collect metadata only. Never read a value in this step."""

    try:
        info = control.element_info
        automation_id = _normalise_space(getattr(info, "automation_id", ""))
        accessible_name = _normalise_space(getattr(info, "name", ""))
    except Exception:
        automation_id = ""
        accessible_name = ""
    try:
        in_top_band = int(control.rectangle().top) <= int(top_limit)
    except Exception:
        in_top_band = False
    try:
        visible = bool(control.is_visible())
    except Exception:
        visible = False
    return AddressBarCandidate(index, automation_id, accessible_name, in_top_band, visible)


def _selected_control_value(control: Any) -> str:
    """Read only the candidate already certified as the address bar."""

    try:
        getter = getattr(control, "get_value", None)
        if callable(getter):
            value = _normalise_space(getter())
            if value:
                return value
    except Exception:
        pass
    try:
        return _normalise_space(control.window_text())
    except Exception:
        return ""


def _safe_uia_process_id(window: Any) -> int:
    try:
        return int(getattr(window.element_info, "process_id", 0) or 0)
    except Exception:
        return 0


def read_browser_url_evidence(
    *,
    hwnd: int,
    process_id: int,
    process_name: object,
    diagnostic: bool = False,
    identity_secret: bytes | None = None,
) -> BrowserUrlObservation:
    """Read one exact browser HWND and immediately reduce its address."""

    normalised_process = normalise_process_name(process_name)
    adapter = adapter_for_process(normalised_process)
    if adapter is None:
        return BrowserUrlObservation(BrowserUrlReadStatus.NOT_SUPPORTED_BROWSER, process_name=normalised_process, reason="The foreground process is not a supported browser.")
    try:
        numeric_hwnd = int(hwnd)
        expected_process_id = int(process_id)
    except (TypeError, ValueError):
        numeric_hwnd = expected_process_id = 0
    if numeric_hwnd <= 0 or expected_process_id <= 0:
        return BrowserUrlObservation(BrowserUrlReadStatus.INVALID_WINDOW, adapter.browser, adapter.display_name, normalised_process, reason="A valid HWND and process ID were not supplied.")

    try:
        from pywinauto import Desktop
    except Exception:
        return BrowserUrlObservation(BrowserUrlReadStatus.DEPENDENCY_MISSING, adapter.browser, adapter.display_name, normalised_process, reason="Windows UI Automation support is unavailable.")

    try:
        window = Desktop(backend="uia").window(handle=numeric_hwnd).wrapper_object()
    except Exception as error:
        error_name = type(error).__name__.casefold()
        status = BrowserUrlReadStatus.ACCESS_DENIED if "access" in error_name or "permission" in error_name else BrowserUrlReadStatus.WINDOW_NOT_FOUND
        return BrowserUrlObservation(status, adapter.browser, adapter.display_name, normalised_process, reason="The exact foreground browser window could not be attached through UIA.")

    # INSTRUCTION: reject a recycled or mismatched HWND before reading controls.
    attached_process_id = _safe_uia_process_id(window)
    try:
        attached_hwnd = int(getattr(window, "handle", 0) or 0)
    except Exception:
        attached_hwnd = 0
    if attached_hwnd != numeric_hwnd or attached_process_id != expected_process_id:
        return BrowserUrlObservation(BrowserUrlReadStatus.WINDOW_IDENTITY_MISMATCH, adapter.browser, adapter.display_name, normalised_process, reason="UIA window identity did not match the observed HWND and process ID.")

    try:
        rectangle = window.rectangle()
        top_limit = int(rectangle.top) + max(180, int(max(1, int(rectangle.height())) * 0.22))
        edit_controls = tuple(window.descendants(control_type="Edit"))[:64]
    except Exception:
        return BrowserUrlObservation(BrowserUrlReadStatus.READER_ERROR, adapter.browser, adapter.display_name, normalised_process, reason="UIA could not inspect the browser chrome safely.")

    candidates = tuple(
        _control_metadata(control, index, top_limit)
        for index, control in enumerate(edit_controls)
    )
    selected, selection_reason = choose_address_bar_candidate(candidates, adapter)
    diagnostics: tuple[str, ...] = ()
    if diagnostic:
        diagnostics = tuple(
            f"candidate={item.index}; top_band={item.in_browser_top_band}; visible={item.visible}; value_read=False"
            for item in candidates
        )
    if selected is None:
        return BrowserUrlObservation(BrowserUrlReadStatus.ADDRESS_BAR_NOT_FOUND, adapter.browser, adapter.display_name, normalised_process, candidate_count=len(candidates), reason=selection_reason, diagnostic_candidates=diagnostics)

    address_value = _selected_control_value(edit_controls[selected.index])
    if not address_value:
        return BrowserUrlObservation(BrowserUrlReadStatus.ADDRESS_VALUE_EMPTY, adapter.browser, adapter.display_name, normalised_process, candidate_count=len(candidates), reason="The certified address bar exposed no value.", diagnostic_candidates=diagnostics)
    if not _looks_like_address(address_value):
        return BrowserUrlObservation(BrowserUrlReadStatus.ADDRESS_VALUE_INVALID, adapter.browser, adapter.display_name, normalised_process, candidate_count=len(candidates), reason="The certified address bar did not expose an address-shaped value.", diagnostic_candidates=diagnostics)

    # INSTRUCTION: reduce immediately. Do not attach address_value to any result.
    evidence = classify_address_value(
        address_value,
        identity_secret=identity_secret,
    )
    certified_host = _certified_host_from_address(address_value)
    if certified_host:
        evidence = replace(evidence, certified_host=certified_host)
    if evidence.kind is UrlEvidenceKind.INVALID_ADDRESS:
        return BrowserUrlObservation(BrowserUrlReadStatus.ADDRESS_VALUE_INVALID, adapter.browser, adapter.display_name, normalised_process, candidate_count=len(candidates), reason="The certified address could not be parsed safely.", diagnostic_candidates=diagnostics)
    return BrowserUrlObservation(
        status=BrowserUrlReadStatus.OK,
        browser=adapter.browser,
        browser_label=adapter.display_name,
        process_name=normalised_process,
        evidence=evidence,
        read_method="uia_exact_hwnd_selected_address_bar_only",
        candidate_count=len(candidates),
        reason=selection_reason,
        diagnostic_candidates=diagnostics,
    )


class _EvidenceStabiliser:
    """Deterministic continuity for one already-certified browser window."""

    def __init__(self, policy: EvidenceStabilityPolicy) -> None:
        self._policy = policy
        self._current: UrlSurfaceEvidence | None = None
        self._last_time: float | None = None
        self._weak_samples = 0
        self._first_weak_time: float | None = None

    def reset(self) -> None:
        self._current = None
        self._last_time = None
        self._clear_weak_run()

    def observe(self, evidence: UrlSurfaceEvidence, observed_at: float) -> _StableEvidenceView:
        now = self._validate_time(observed_at)
        current = self._current
        if current is None:
            return self._replace(evidence, "The first reduced URL evidence was accepted.")
        if self._same_identity(current, evidence):
            self._clear_weak_run()
            return _StableEvidenceView(current, False, 0, "The stable URL evidence was observed again.")
        if current.platform_key != evidence.platform_key:
            return self._replace(evidence, "The certified host changed, so previous evidence was released.")
        if evidence.is_strong:
            return self._replace(evidence, "New strong evidence from the same host was accepted.")
        if current.is_strong:
            return self._handle_weak(evidence, now)
        return self._replace(evidence, "Weak evidence changed without a protected strong state.")

    def unavailable(self, observed_at: float) -> _StableEvidenceView:
        now = self._validate_time(observed_at)
        if self._current is None:
            return _StableEvidenceView(None, False, 0, "No URL evidence was available.")
        if self._current.is_strong:
            return self._handle_weak(None, now)
        self._current = None
        self._clear_weak_run()
        return _StableEvidenceView(None, False, 0, "Unavailable input cleared weak evidence.")

    def _handle_weak(self, replacement: UrlSurfaceEvidence | None, now: float) -> _StableEvidenceView:
        self._weak_samples += 1
        if self._first_weak_time is None:
            self._first_weak_time = now
        expired = now - self._first_weak_time >= self._policy.maximum_hold_seconds
        counted = self._weak_samples >= self._policy.release_after_weak_samples
        if not (expired or counted):
            return _StableEvidenceView(self._current, True, self._weak_samples, "A transient weak read is holding the previous strong evidence.")
        return self._replace(replacement, "Repeated or aged weak evidence released the previous strong state.")

    def _replace(self, evidence: UrlSurfaceEvidence | None, reason: str) -> _StableEvidenceView:
        self._current = evidence
        self._clear_weak_run()
        return _StableEvidenceView(evidence, False, 0, reason)

    def _validate_time(self, observed_at: float) -> float:
        now = float(observed_at)
        if not math.isfinite(now):
            raise ValueError("observed time must be finite")
        if self._last_time is not None and now < self._last_time:
            raise ValueError("observed time must be monotonic")
        self._last_time = now
        return now

    def _clear_weak_run(self) -> None:
        self._weak_samples = 0
        self._first_weak_time = None

    @staticmethod
    def _same_identity(left: UrlSurfaceEvidence, right: UrlSurfaceEvidence) -> bool:
        # The exact resource token is part of identity.  Without it two
        # different YouTube videos both reduce to
        # selected_video/youtube/watch, so the second one was treated as "the
        # stable evidence observed again" and the FIRST video's token was kept
        # for the rest of the session.  Routes that carry no exact token
        # compare "" == "" and keep their previous behaviour; a token
        # appearing or disappearing is correctly a different identity.
        return (
            left.kind is right.kind
            and left.platform_key == right.platform_key
            and left.marker == right.marker
            and left.resource_token == right.resource_token
        )


BrowserReader = Callable[..., BrowserUrlObservation]


class BrowserEvidenceAuthority:
    """One session-scoped browser authority used by ``monitor.py``."""

    def __init__(
        self,
        *,
        policy: EvidenceStabilityPolicy | None = None,
        reader: BrowserReader = read_browser_url_evidence,
        diagnostic: bool = False,
    ) -> None:
        self._reader = reader
        self._diagnostic = bool(diagnostic)
        self._stabiliser = _EvidenceStabiliser(policy or EvidenceStabilityPolicy())
        self._scope: tuple[str, int, int] | None = None
        self._reader_disabled = False
        self._reader_disable_status = BrowserUrlReadStatus.DEPENDENCY_MISSING
        self._identity_secret = secrets.token_bytes(32)
        self._started = False
        self._closed = False

    def start_session(self) -> None:
        """Start clean; a previous browser identity may never cross sessions."""

        self._stabiliser.reset()
        self._scope = None
        self._reader_disabled = False
        self._reader_disable_status = BrowserUrlReadStatus.DEPENDENCY_MISSING
        self._identity_secret = secrets.token_bytes(32)
        self._started = True
        self._closed = False

    def observe(self, foreground: object) -> BrowserEvidenceSnapshot:
        if not self._started or self._closed:
            raise RuntimeError("Browser evidence session is not active")

        sequence = int(getattr(foreground, "sequence", 0) or 0)
        hwnd = int(getattr(foreground, "hwnd", 0) or 0)
        process_id = int(getattr(foreground, "process_id", 0) or 0)
        process_name = normalise_process_name(getattr(foreground, "process_name", ""))
        observed_ns = int(getattr(foreground, "observed_monotonic_ns", 0) or 0)
        observed_at = observed_ns / 1_000_000_000
        adapter = adapter_for_process(process_name)

        # INSTRUCTION: unsupported processes clear browser continuity at once.
        if adapter is None:
            self._reset_scope()
            return BrowserEvidenceSnapshot(
                sequence, hwnd, process_id, process_name, None, "", False,
                False, BrowserUrlReadStatus.NOT_SUPPORTED_BROWSER, None,
                reader_disabled_for_session=self._reader_disabled,
                reason="The foreground process is not a supported browser.",
            )

        scope = (process_name, hwnd, process_id)
        if scope != self._scope:
            self._stabiliser.reset()
            self._scope = scope

        if hwnd <= 0 or process_id <= 0 or observed_ns <= 0:
            self._stabiliser.reset()
            return self._snapshot(sequence, hwnd, process_id, process_name, adapter, False, BrowserUrlReadStatus.INVALID_WINDOW, None, False, 0, "The foreground browser observation was incomplete.")

        if self._reader_disabled:
            stable = self._stabiliser.unavailable(observed_at)
            return self._snapshot(
                sequence,
                hwnd,
                process_id,
                process_name,
                adapter,
                False,
                self._reader_disable_status,
                stable.evidence,
                stable.holding_previous_strong_evidence,
                stable.consecutive_weak_samples,
                stable.reason,
            )

        observation = self._reader(
            hwnd=hwnd,
            process_id=process_id,
            process_name=process_name,
            diagnostic=self._diagnostic,
            identity_secret=self._identity_secret,
        )
        if observation.status in {
            BrowserUrlReadStatus.DEPENDENCY_MISSING,
            BrowserUrlReadStatus.ACCESS_DENIED,
        }:
            self._reader_disabled = True
            self._reader_disable_status = observation.status

        if observation.status is BrowserUrlReadStatus.OK and observation.evidence is not None:
            stable = self._stabiliser.observe(observation.evidence, observed_at)
        elif observation.status in {
            BrowserUrlReadStatus.DEPENDENCY_MISSING,
            BrowserUrlReadStatus.ACCESS_DENIED,
            BrowserUrlReadStatus.WINDOW_NOT_FOUND,
            BrowserUrlReadStatus.ADDRESS_BAR_NOT_FOUND,
            BrowserUrlReadStatus.ADDRESS_VALUE_EMPTY,
            BrowserUrlReadStatus.READER_ERROR,
        }:
            stable = self._stabiliser.unavailable(observed_at)
        else:
            # Identity mismatch and invalid address fail closed.
            self._stabiliser.reset()
            stable = _StableEvidenceView(None, False, 0, "Unsafe or non-transient browser evidence was rejected.")

        reason = stable.reason if stable.holding_previous_strong_evidence else (observation.reason or stable.reason)
        return self._snapshot(
            sequence, hwnd, process_id, process_name, adapter, True,
            observation.status, stable.evidence,
            stable.holding_previous_strong_evidence,
            stable.consecutive_weak_samples,
            reason,
        )

    def shutdown(self) -> None:
        self._reset_scope()
        self._started = False
        self._closed = True

    def _reset_scope(self) -> None:
        self._stabiliser.reset()
        self._scope = None

    def _snapshot(
        self,
        sequence: int,
        hwnd: int,
        process_id: int,
        process_name: str,
        adapter: BrowserAdapterSpec,
        read_attempted: bool,
        status: BrowserUrlReadStatus,
        evidence: UrlSurfaceEvidence | None,
        holding: bool,
        weak_samples: int,
        reason: str,
    ) -> BrowserEvidenceSnapshot:
        return BrowserEvidenceSnapshot(
            observation_sequence=sequence,
            hwnd=hwnd,
            process_id=process_id,
            process_name=process_name,
            browser=adapter.browser,
            browser_label=adapter.display_name,
            supported_browser=True,
            read_attempted=read_attempted,
            status=status,
            evidence=evidence,
            holding_previous_strong_evidence=holding,
            consecutive_weak_samples=weak_samples,
            reader_disabled_for_session=self._reader_disabled,
            reason=reason,
        )


__all__ = (
    "AddressBarCandidate",
    "BROWSER_ADAPTERS",
    "BrowserAdapterSpec",
    "BrowserEvidenceAuthority",
    "BrowserEvidenceSnapshot",
    "BrowserKind",
    "BrowserUrlObservation",
    "BrowserUrlReadStatus",
    "EvidenceConfidence",
    "EvidenceStabilityPolicy",
    "UrlEvidenceKind",
    "UrlSurfaceEvidence",
    "adapter_for_process",
    "choose_address_bar_candidate",
    "classify_address_value",
    "normalise_process_name",
    "read_browser_url_evidence",
)
