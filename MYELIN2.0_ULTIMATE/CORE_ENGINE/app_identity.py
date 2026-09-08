"""Exact window-level app identity for the two locally proven Store web apps.

This is a passive helper of WindowsForegroundReader, not a second monitor.
No title, URL, profile, command line, cache, or timing policy is consulted.
The shared Edge PID is insufficient: the AUMID must belong to this HWND.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


# Independently observed on foreground windows and matched to Store app
# registrations on 2026-09-02. Exact IDs only; no publisher/name substrings.
_APP_PLATFORMS = MappingProxyType({
    "AmazonVideo.PrimeVideo_pwbj9vvecjh7j!PWA": "prime_video",
    "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App": "netflix",
})


@dataclass(frozen=True, slots=True)
class ForegroundAppIdentity:
    application_id: str
    process_name: str
    process_id: int
    hwnd: int
    observed_monotonic_ns: int

    @property
    def platform_key(self) -> str:
        return _APP_PLATFORMS.get(self.application_id, "")

    def matches(self, *, process_name: str, process_id: int, hwnd: int,
                observed_monotonic_ns: int) -> bool:
        return bool(
            self.platform_key
            and self.process_name == process_name == "msedge.exe"
            and self.process_id == process_id > 0
            and self.hwnd == hwnd > 0
            and self.observed_monotonic_ns == observed_monotonic_ns > 0
        )


def read_foreground_app_identity(*, hwnd: int, process_id: int,
                                process_name: str, observed_monotonic_ns: int
                                ) -> ForegroundAppIdentity | None:
    """Read only the exact current Edge window's explicit Windows AUMID.

    Failure, unknown IDs, and any foreground/PID change fail closed. There
    is no previous-evidence hold. Unknown AUMIDs (which may contain browser
    profile names) never escape this function. All COM access is read-only.
    """
    process = process_name.casefold()
    if process not in {"msedge", "msedge.exe"}:
        return None
    if hwnd <= 0 or process_id <= 0 or observed_monotonic_ns <= 0:
        return None
    initialized = False
    try:
        import pythoncom
        import win32gui
        import win32process
        from win32com.propsys import propsys, pscon

        def same_window() -> bool:
            return bool(
                win32gui.GetForegroundWindow() == hwnd
                and win32process.GetWindowThreadProcessId(hwnd)[1] == process_id
                and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"
            )

        if not same_window():
            return None
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            initialized = True
        except pythoncom.com_error as error:
            # An already-initialized MTA is valid; do not uninitialize it.
            if error.hresult != -2147417850:  # RPC_E_CHANGED_MODE
                return None
        store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
        application_id = store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
        if not isinstance(application_id, str) or application_id not in _APP_PLATFORMS:
            return None
        if not same_window():
            return None
        return ForegroundAppIdentity(application_id, "msedge.exe", process_id,
                                     hwnd, observed_monotonic_ns)
    except Exception:
        # Missing Windows support, an exited window, or a denied read cannot
        # grant app identity and must not disable normal browser monitoring.
        return None
    finally:
        if initialized:
            pythoncom.CoUninitialize()
