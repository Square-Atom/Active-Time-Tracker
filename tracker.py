"""The background tracking loop.

Every poll interval we check how long the system has been idle. If the user has
been active within the idle timeout, we credit the elapsed time to whatever app
(and file) is currently focused.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time

import backups
import config
import devices
import storage as storage_mod
import sysinfo
from storage import Storage

# How often to ask "is a backup due?". Well under the shortest interval a user
# can set, so the setting is honoured rather than rounded up to this period.
# The check itself costs ~1ms.
_BACKUP_CHECK_SECONDS = 60

# Synthetic identity for this app's own windows (dashboard / settings), so they
# show up as "Active Time Tracker" instead of the host interpreter process.
OWN_APP_KEY = "activetimetracker.exe"
OWN_APP_NAME = "Active Time Tracker"


class Tracker:
    def __init__(self, storage: Storage, cfg: config.Config, watcher=None):
        self.storage = storage
        self.cfg = cfg
        # Optional `notifications.FocusWatcher`. It only hears about time spent
        # in a real app, which is what makes idle time and our own windows
        # leave the focus reminder's clock alone.
        self.watcher = watcher
        self.devices = devices.DeviceActivity()
        self._own_pid = os.getpid()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        # Snapshot of what we're currently crediting, for the tray/status.
        self.current_app_name: str = ""
        self.current_file: str = ""
        self.is_active: bool = False

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.storage.flush()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def set_paused(self, value: bool) -> None:
        if value:
            self._paused.set()
            self.storage.flush()
            self.is_active = False
        else:
            self._paused.clear()

    def toggle_paused(self) -> bool:
        self.set_paused(not self.paused)
        return self.paused

    # -- loop -------------------------------------------------------------

    def _run(self) -> None:
        last = time.monotonic()
        last_wall = time.time()
        last_flush = last
        # Check soon after start, then hourly.
        last_backup_check = last - _BACKUP_CHECK_SECONDS

        while not self._stop.is_set():
            # Read config live so Settings changes take effect without restart.
            poll = max(0.25, float(self.cfg.poll_interval_seconds))
            idle_timeout = float(self.cfg.idle_timeout_seconds)
            flush_every = float(self.cfg.flush_interval_seconds)
            # Cap the credit per tick so a missed schedule / sleep-wake doesn't
            # dump a huge chunk of time onto one app.
            max_credit = poll * 2

            self._stop.wait(poll)
            if self._stop.is_set():
                break

            now = time.monotonic()
            delta = now - last
            last = now
            # The timeline needs wall-clock times. The span ends now and covers
            # the same capped credit, so a sleep/wake gap stays a gap. The two
            # clocks are read one after the other, so a thread preempted
            # between the reads would start a span a little before the last
            # one ended; clamp to it so blocks butt up rather than overlap.
            wall = time.time()
            span_start = max(wall - min(delta, max_credit), last_wall)
            last_wall = wall

            if now - last_flush >= flush_every:
                self.storage.flush()
                last_flush = now
                # Cheap "is a daily backup due?" check, piggybacked on the
                # flush so it needs no timer of its own.
                if now - last_backup_check >= _BACKUP_CHECK_SECONDS:
                    last_backup_check = now
                    backups.maybe_run(self.storage, self.cfg)

            if self._paused.is_set():
                self.is_active = False
                self.devices.release()   # let a DAW have the MIDI ports back
                continue

            # Windows counts only keyboard/mouse as input, so a game pad or a
            # MIDI keyboard would look like idleness. Take whichever source was
            # used most recently.
            self.devices.start()
            idle = min(sysinfo.get_idle_seconds(),
                       self.devices.seconds_since_input())
            if idle > idle_timeout:
                self.is_active = False
                self.current_app_name = ""
                self.current_file = ""
                self.storage.add_span(storage_mod.IDLE, span_start, wall)
                continue

            win = sysinfo.get_foreground_window()
            if win is None or not win.exe or win.exe in self.cfg.ignore_apps:
                # Present, but nothing we name: an ignored app stays anonymous.
                self.is_active = False
                self.storage.add_span(storage_mod.UNTRACKED, span_start, wall)
                continue

            if win.pid == self._own_pid:
                # Our own dashboard/settings window.
                app_key, app_name, file = OWN_APP_KEY, OWN_APP_NAME, ""
            else:
                app_key = win.exe
                app_name = config.friendly_name(win.exe)
                # Read rules live so the file-rules editor applies immediately.
                file = config.parse_file(win.exe, win.title, self.cfg.merged_rules)
            credit = min(delta, max_credit)

            self.storage.add_seconds(
                day=dt.date.today().isoformat(),
                app=app_key,
                app_name=app_name,
                file=file,
                seconds=credit,
            )
            self.storage.add_span(storage_mod.ACTIVE, span_start, wall,
                                  app=app_key, app_name=app_name)
            self.is_active = True
            self.current_app_name = app_name
            self.current_file = file
            if self.watcher is not None and app_key != OWN_APP_KEY:
                self.watcher.tick(app_key, app_name, credit)

        self.devices.close()   # hand MIDI ports back when we stop
        self.storage.flush()
