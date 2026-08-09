"""Cross-platform system access: foreground window, idle time, single-instance
lock, and "open a folder". Each platform has its own implementation; everything
degrades safely (returns no window / zero idle) if an optional dependency is
missing, so the app still launches.

Platform dependencies for full functionality:
  * Windows: none (uses built-in ctypes / Win32).
  * macOS:   pyobjc  (Quartz + AppKit)  ->  pip install pyobjc
  * Linux:   python-xlib + libXss       ->  pip install python-xlib
             (libXss is usually preinstalled; on Debian/Ubuntu: libxss1)
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass

_PLATFORM = sys.platform
_log = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    exe: str   # basename, lowercased (e.g. "photoshop.exe" / "photoshop")
    pid: int


# ======================================================================
# Windows
# ======================================================================
if _PLATFORM == "win32":
    import winapi  # existing ctypes backend

    def get_idle_seconds() -> float:
        return winapi.get_idle_seconds()

    def get_foreground_window() -> WindowInfo | None:
        w = winapi.get_foreground_window()
        if w is None:
            return None
        return WindowInfo(w.hwnd, w.title, w.exe, w.pid)

    def open_path(path: str) -> None:
        import os
        os.startfile(path)  # noqa: S606 - intended

    def single_instance(app_id: str) -> bool:
        """True if we're the only instance (holds a named mutex for our life)."""
        import ctypes
        global _win_mutex
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _win_mutex = kernel32.CreateMutexW(None, False, f"{app_id}_SingleInstance_Mutex")
        ERROR_ALREADY_EXISTS = 183
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


# ======================================================================
# macOS
# ======================================================================
elif _PLATFORM == "darwin":

    def get_idle_seconds() -> float:
        try:
            from Quartz import (
                CGEventSourceSecondsSinceLastEventType,
                kCGEventSourceStateHIDSystemState,
            )
            k_any = 0xFFFFFFFF  # kCGAnyInputEventType
            return float(CGEventSourceSecondsSinceLastEventType(
                kCGEventSourceStateHIDSystemState, k_any))
        except Exception:
            _log.warning("idle detection unavailable (install pyobjc)", exc_info=True)
            return 0.0

    def _mac_window_title(pid: int) -> str:
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGWindowListExcludeDesktopElements,
                kCGNullWindowID,
            )
            opts = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
            for w in CGWindowListCopyWindowInfo(opts, kCGNullWindowID) or []:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer", 1) == 0:
                    name = w.get("kCGWindowName") or ""
                    if name:
                        return str(name)
        except Exception:
            pass  # window titles need Screen Recording permission; ok to skip
        return ""

    def get_foreground_window() -> WindowInfo | None:
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return None
            pid = int(app.processIdentifier())
            url = app.executableURL()
            name = url.lastPathComponent() if url else (app.localizedName() or "")
            return WindowInfo(0, _mac_window_title(pid), (name or "").lower(), pid)
        except Exception:
            _log.warning("foreground detection unavailable (install pyobjc)",
                         exc_info=True)
            return None

    def open_path(path: str) -> None:
        subprocess.Popen(["open", path])

    def single_instance(app_id: str) -> bool:
        return _posix_single_instance(app_id)


# ======================================================================
# Linux / other X11
# ======================================================================
else:

    def get_idle_seconds() -> float:
        try:
            import ctypes
            global _xss, _xss_display, _XScreenSaverInfo
            if "_xss" not in globals() or _xss is None:
                _x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
                _xss = ctypes.cdll.LoadLibrary("libXss.so.1")

                class XScreenSaverInfo(ctypes.Structure):
                    _fields_ = [
                        ("window", ctypes.c_ulong),
                        ("state", ctypes.c_int),
                        ("kind", ctypes.c_int),
                        ("since", ctypes.c_ulong),
                        ("idle", ctypes.c_ulong),
                        ("event_mask", ctypes.c_ulong),
                    ]

                _XScreenSaverInfo = XScreenSaverInfo
                _x11.XOpenDisplay.restype = ctypes.c_void_p
                _x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
                _x11.XDefaultRootWindow.restype = ctypes.c_ulong
                _xss.XScreenSaverAllocInfo.restype = ctypes.c_void_p
                _xss.XScreenSaverQueryInfo.argtypes = [
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
                globals()["_x11lib"] = _x11
                _xss_display = _x11.XOpenDisplay(None)
                globals()["_xss_root"] = _x11.XDefaultRootWindow(_xss_display)
                globals()["_xss_info"] = _xss.XScreenSaverAllocInfo()
            _xss.XScreenSaverQueryInfo(_xss_display, _xss_root, _xss_info)
            info = _XScreenSaverInfo.from_address(_xss_info)
            return info.idle / 1000.0
        except Exception:
            _log.warning("idle detection unavailable (need libXss)", exc_info=True)
            return 0.0

    def _linux_exe_for_pid(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
                return fh.read().strip().lower()
        except OSError:
            return ""

    def get_foreground_window() -> WindowInfo | None:
        try:
            from Xlib import X, display
            global _xdisplay
            if "_xdisplay" not in globals() or _xdisplay is None:
                _xdisplay = display.Display()
            root = _xdisplay.screen().root
            net_active = _xdisplay.intern_atom("_NET_ACTIVE_WINDOW")
            prop = root.get_full_property(net_active, X.AnyPropertyType)
            if not prop or not prop.value:
                return None
            win = _xdisplay.create_resource_object("window", prop.value[0])
            title = ""
            for atom_name in ("_NET_WM_NAME", "WM_NAME"):
                atom = _xdisplay.intern_atom(atom_name)
                p = win.get_full_property(atom, X.AnyPropertyType)
                if p and p.value:
                    title = p.value.decode("utf-8", "replace") if isinstance(
                        p.value, bytes) else str(p.value)
                    if title:
                        break
            pid = 0
            pidp = win.get_full_property(_xdisplay.intern_atom("_NET_WM_PID"),
                                         X.AnyPropertyType)
            if pidp and pidp.value:
                pid = int(pidp.value[0])
            exe = _linux_exe_for_pid(pid) if pid else ""
            if not exe:
                cls = win.get_wm_class()
                exe = (cls[0] if cls else "").lower()
            return WindowInfo(int(prop.value[0]), title, exe, pid)
        except Exception:
            _log.warning("foreground detection unavailable (need python-xlib)",
                         exc_info=True)
            return None

    def open_path(path: str) -> None:
        subprocess.Popen(["xdg-open", path])

    def single_instance(app_id: str) -> bool:
        return _posix_single_instance(app_id)


# ----------------------------------------------------------------------
# Shared POSIX single-instance lock (macOS + Linux)
# ----------------------------------------------------------------------
def _posix_single_instance(app_id: str) -> bool:
    import fcntl
    import os
    import tempfile
    global _posix_lock_fd
    path = os.path.join(tempfile.gettempdir(), f"{app_id}.lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    _posix_lock_fd = fd  # keep the fd (and lock) alive for the process lifetime
    return True
