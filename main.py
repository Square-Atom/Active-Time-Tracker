"""Active Time Tracker — entry point.

Wires together the tracker loop, SQLite storage, tkinter dashboard, and a
system-tray icon. Runs the tk mainloop on the main thread; the tray icon runs
detached in its own thread; the tracker polls in a daemon thread.

Usage:
    python main.py              # start and show the dashboard
    python main.py --minimized  # start hidden in the tray (used for autostart)
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import tkinter as tk

import pystray
from PIL import ImageTk

import appicon
import autostart
import backups
import config
import sysinfo
import updatedialog
import updater
from appicon import make_clock_image
from dashboard import Dashboard
from ignoreapps import IgnoreWindow
from merges import MergesWindow
from settings import SettingsWindow
from storage import Storage
from tracker import Tracker

APP_ID = "ActiveTimeTracker"
APP_TITLE = "Active Time Tracker"

logging.basicConfig(
    filename=os.path.join(config.APP_DIR, "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _claim_taskbar_identity() -> None:
    """Stop Windows filing our window under pythonw.exe.

    The taskbar groups by AppUserModelID; without our own, the button inherits
    the host interpreter's identity and its icon. Must run before any window is
    created.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"PixelmancerStudio.{APP_ID}")
    except Exception:
        logging.debug("Could not set AppUserModelID", exc_info=True)


def _set_window_icon(root) -> None:
    """Give the window (and taskbar button) our clock icon.

    Windows needs a real .ico via `iconbitmap`; `iconphoto` alone doesn't reach
    the taskbar.
    """
    ico = appicon.ensure_ico()
    if ico:
        try:
            root.iconbitmap(default=ico)
            return
        except tk.TclError:
            logging.debug("iconbitmap failed; falling back to iconphoto", exc_info=True)
    # Non-Windows (or no .ico): a Tk photo image still sets the window icon.
    root._app_icon = ImageTk.PhotoImage(appicon.make_clock_image(64))
    root.iconphoto(True, root._app_icon)


def main() -> None:
    if not sysinfo.single_instance(APP_ID):
        logging.info("Another instance is already running; exiting.")
        return

    start_hidden = "--minimized" in sys.argv
    _claim_taskbar_identity()  # before any window exists

    cfg = config.load()
    storage = Storage()
    tracker = Tracker(storage, cfg)

    # Keep the login-item entry in sync with the saved preference.
    try:
        autostart.cleanup_legacy()
        if cfg.autostart != autostart.is_enabled():
            autostart.set_enabled(cfg.autostart)
    except OSError:
        logging.exception("Failed to sync autostart setting")

    root = tk.Tk()
    _set_window_icon(root)  # same clock as the tray, incl. the taskbar button
    dashboard = Dashboard(root, storage, tracker)
    root.protocol("WM_DELETE_WINDOW", dashboard.hide)  # X hides to tray

    tracker.start()

    # --- settings / groups windows (single instance each) -----------------
    settings_holder: dict[str, SettingsWindow | None] = {"win": None}
    merges_holder: dict[str, MergesWindow | None] = {"win": None}
    ignore_holder: dict[str, IgnoreWindow | None] = {"win": None}

    def on_settings_changed():
        try:
            icon.update_menu()  # refresh the autostart checkmark
        except Exception:
            pass
        # If the dashboard is visible, reflect any changes right away.
        if dashboard._visible:
            root.after(0, dashboard.refresh)

    def open_ignore():
        existing = ignore_holder["win"]
        if existing is not None and existing.win.winfo_exists():
            existing.win.lift()
            existing.win.focus_force()
            return
        ignore_holder["win"] = IgnoreWindow(
            root, cfg, storage, on_change=on_settings_changed)

    def open_settings():
        existing = settings_holder["win"]
        if existing is not None and existing.win.winfo_exists():
            existing.win.lift()
            existing.win.focus_force()
            return
        settings_holder["win"] = SettingsWindow(
            root, cfg, tracker, on_change=on_settings_changed, storage=storage,
            open_ignore=open_ignore)

    def open_merges():
        existing = merges_holder["win"]
        if existing is not None and existing.win.winfo_exists():
            existing.win.lift()
            existing.win.focus_force()
            return
        merges_holder["win"] = MergesWindow(
            root, cfg, storage, on_change=on_settings_changed)

    dashboard.open_settings_cb = open_settings
    dashboard.open_merges_cb = open_merges

    # --- tray icon ---------------------------------------------------------
    def do_show(icon=None, item=None):
        root.after(0, dashboard.show)

    def do_settings(icon, item):
        root.after(0, open_settings)

    def do_merges(icon, item):
        root.after(0, open_merges)

    def do_ignore(icon, item):
        root.after(0, open_ignore)

    def do_toggle_pause(icon, item):
        tracker.toggle_paused()
        icon.update_menu()

    def do_toggle_autostart(icon, item):
        new_value = not cfg.autostart
        try:
            autostart.set_enabled(new_value)
            cfg.autostart = new_value
            cfg.save()
        except OSError:
            logging.exception("Failed to change autostart setting")
        icon.update_menu()

    def do_open_folder(icon, item):
        sysinfo.open_path(config.APP_DIR)

    def do_open_backups(icon, item):
        path = backups.backup_dir(cfg)
        try:
            os.makedirs(path, exist_ok=True)
            sysinfo.open_path(path)
        except OSError:
            logging.exception("Could not open the backups folder")

    def do_quit(icon, item):
        try:
            tracker.stop()
            storage.close()
        finally:
            icon.visible = False
            icon.stop()
            root.after(0, root.destroy)

    menu = pystray.Menu(
        pystray.MenuItem("Open dashboard", do_show, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause tracking", do_toggle_pause,
                         checked=lambda item: tracker.paused),
        pystray.MenuItem("Start with Windows", do_toggle_autostart,
                         checked=lambda item: cfg.autostart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings…", do_settings),
        pystray.MenuItem("App groups…", do_merges),
        pystray.MenuItem("Ignored apps…", do_ignore),
        pystray.MenuItem("Open data folder", do_open_folder),
        pystray.MenuItem("Open backups folder", do_open_backups),
        pystray.MenuItem("Quit", do_quit),
    )
    icon = pystray.Icon(APP_ID, make_clock_image(64), APP_TITLE, menu)
    icon.run_detached()

    if not start_hidden:
        dashboard.show()
    else:
        root.withdraw()

    # Optional startup update check: runs in the background and only speaks up
    # when there's actually a newer release.
    if cfg.check_updates_on_startup:
        def on_startup_check(result):
            if result.has_update:
                root.after(0, lambda: updatedialog.show_update(root, result))

        root.after(3000, lambda: updater.check_async(on_startup_check))

    try:
        root.mainloop()
    finally:
        tracker.stop()
        storage.close()
        try:
            icon.stop()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal error")
        raise
