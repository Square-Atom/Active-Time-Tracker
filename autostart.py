"""Register/unregister the app to launch at login — cross-platform.

  * Windows: HKCU ...\\Run registry value
  * macOS:   ~/Library/LaunchAgents/<id>.plist
  * Linux:   ~/.config/autostart/<id>.desktop
"""

from __future__ import annotations

import os
import sys

APP_ID = "ActiveTimeTracker"
_OLD_WIN_VALUE = "WorkTimeTracker"  # pre-rename registry value to clean up

_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_args() -> list[str]:
    """Argv that starts the tracker minimized to the tray."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]
    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    exe = sys.executable
    if sys.platform == "win32":
        pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(pythonw):
            exe = pythonw
    return [exe, main_py, "--minimized"]


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


# ---------------------------------------------------------------- Windows
def _win_command() -> str:
    return " ".join(_quote(a) for a in _launch_args())


def _win_set(enabled: bool) -> None:
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _win_command())
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def _win_is_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return False
    try:
        winreg.QueryValueEx(key, APP_ID)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)


def _win_cleanup_legacy() -> None:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE)
    except FileNotFoundError:
        return
    try:
        winreg.DeleteValue(key, _OLD_WIN_VALUE)
    except FileNotFoundError:
        pass
    finally:
        winreg.CloseKey(key)


# ---------------------------------------------------------------- macOS
def _mac_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/com.{APP_ID.lower()}.plist")


def _mac_set(enabled: bool) -> None:
    path = _mac_plist_path()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    args = "".join(f"\n        <string>{a}</string>" for a in _launch_args())
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.{APP_ID.lower()}</string>
    <key>ProgramArguments</key>
    <array>{args}
    </array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(plist)


def _mac_is_enabled() -> bool:
    return os.path.exists(_mac_plist_path())


# ---------------------------------------------------------------- Linux
def _linux_desktop_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "autostart", f"{APP_ID.lower()}.desktop")


def _linux_set(enabled: bool) -> None:
    path = _linux_desktop_path()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exec_line = " ".join(_quote(a) for a in _launch_args())
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Active Time Tracker\n"
        f"Exec={exec_line}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _linux_is_enabled() -> bool:
    return os.path.exists(_linux_desktop_path())


# ---------------------------------------------------------------- dispatch
def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        _win_set(enabled)
    elif sys.platform == "darwin":
        _mac_set(enabled)
    else:
        _linux_set(enabled)


def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_is_enabled()
    if sys.platform == "darwin":
        return _mac_is_enabled()
    return _linux_is_enabled()


def cleanup_legacy() -> None:
    """Remove any autostart entry left over from the pre-rename name."""
    if sys.platform == "win32":
        _win_cleanup_legacy()
