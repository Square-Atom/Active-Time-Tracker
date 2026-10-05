"""Cross-platform system access: foreground window, idle time, single-instance
lock, "open a folder", the desktop work area, a global hotkey (Windows
only for now), and the folder a file manager is showing. Each platform has its own implementation; everything
degrades safely (returns no window / zero idle) if an optional dependency is
missing, so the app still launches.

Platform dependencies for full functionality:
  * Windows: none (uses built-in ctypes / Win32). pywin32 is optional and
             gives File Explorer's full folder path (see winapi.explorer_folder).
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

    def file_manager_folder(win: WindowInfo) -> str | None:
        """See the shared docstring at the bottom of this module."""
        if win.exe != "explorer.exe":
            return None
        return winapi.explorer_folder(win.hwnd, win.title)

    def work_area() -> tuple[int, int, int, int] | None:
        return winapi.work_area()

    def single_instance(app_id: str) -> bool:
        """True if we're the only instance (holds a named mutex for our life)."""
        import ctypes
        global _win_mutex
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _win_mutex = kernel32.CreateMutexW(None, False, f"{app_id}_SingleInstance_Mutex")
        ERROR_ALREADY_EXISTS = 183
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    HOTKEYS_SUPPORTED = True

    _WIN_NAMED_KEYS = {
        "Space": 0x20, "PageUp": 0x21, "PageDown": 0x22, "End": 0x23,
        "Home": 0x24, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
        "Insert": 0x2D, "Delete": 0x2E,
    }
    _WIN_MODIFIERS = {"Alt": 0x1, "Ctrl": 0x2, "Shift": 0x4, "Win": 0x8}

    def register_hotkey(modifiers, key: str, callback):
        """Call `callback` (on a background thread) whenever the combination
        is pressed anywhere. Returns a handle with `stop()`, or None if the
        combination can't be registered (e.g. another app owns it)."""
        if len(key) == 1 and key.isalnum():
            vk = ord(key.upper())
        elif key[:1] == "F" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
            vk = 0x6F + int(key[1:])
        else:
            vk = _WIN_NAMED_KEYS.get(key)
        if vk is None:
            return None
        mods = 0
        for m in modifiers:
            mods |= _WIN_MODIFIERS.get(m, 0)
        handle = winapi.GlobalHotkey(mods, vk, callback)
        return handle if handle.start() else None


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

    # Finder answers AppleScript, which gives the front window's real path (its
    # title, when we can read it at all, is only the folder's name). The
    # script runs in `osascript` rather than in-process because NSAppleScript
    # wants the main thread and we poll from the tracker's thread.
    # The first run makes macOS ask "Active Time Tracker wants to control
    # Finder"; until that's allowed every run fails, so after a failure we wait
    # a while before trying again rather than spawning osascript every second.
    _FINDER_SCRIPT = """
    tell application "Finder"
        if (count of Finder windows) is 0 then return ""
        try
            return POSIX path of (target of front Finder window as alias)
        on error
            -- Recents, AirDrop, search results ... have a name but no path.
            return name of front Finder window
        end try
    end tell
    """
    _FINDER_RETRY_SECONDS = 60.0
    _finder_retry_at = 0.0

    def file_manager_folder(win: WindowInfo) -> str | None:
        """See the shared docstring at the bottom of this module."""
        global _finder_retry_at
        import time
        if win.exe != "finder" or time.monotonic() < _finder_retry_at:
            return None
        try:
            out = subprocess.run(["osascript", "-e", _FINDER_SCRIPT],
                                 capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            out = None
        if out is None or out.returncode != 0:
            _finder_retry_at = time.monotonic() + _FINDER_RETRY_SECONDS
            return None
        path = out.stdout.strip()
        # "/Users/hau/Documents/" -> "/Users/hau/Documents" (keep a bare "/").
        return path.rstrip("/") or path

    def work_area() -> tuple[int, int, int, int] | None:
        return None       # callers fall back to the full screen

    def single_instance(app_id: str) -> bool:
        return _posix_single_instance(app_id)

    HOTKEYS_SUPPORTED = False

    def register_hotkey(modifiers, key: str, callback):
        return None   # not implemented here yet; the setting just does nothing


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

    def file_manager_folder(win: WindowInfo) -> str | None:
        """See the shared docstring at the bottom of this module.

        Linux file managers (Nautilus, Dolphin, Thunar, Nemo, ...) offer no
        way to ask which folder a given window shows, so it's always the
        window title (`config.parse_folder`)."""
        return None

    def work_area() -> tuple[int, int, int, int] | None:
        return None       # callers fall back to the full screen

    def single_instance(app_id: str) -> bool:
        return _posix_single_instance(app_id)

    HOTKEYS_SUPPORTED = False

    def register_hotkey(modifiers, key: str, callback):
        return None   # not implemented here yet; the setting just does nothing


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


# `file_manager_folder(win)`, defined per platform above:
#   Ask the OS which folder the focused file manager window is showing.
#   Returns a full path (or a name for virtual folders like "This PC"); ''
#   when the window is the file manager's but not a folder view (the Windows
#   desktop or taskbar); None when we can't ask, in which case the caller reads
#   the folder from the window title instead (`config.parse_folder`).
