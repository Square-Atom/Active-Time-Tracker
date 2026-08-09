"""Settings window.

A small, extensible dialog for adjusting tracker behaviour. Today it exposes the
idle timeout, the sample interval, and the start-with-Windows toggle. Add new
rows in `_build` (and read them in `_save`) to grow it over time.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import autostart
import config
import dashboard as theme  # reuse the dashboard's colour constants


class SettingsWindow:
    def __init__(self, root: tk.Tk, cfg: config.Config, tracker, on_change=None,
                 storage=None, open_ignore=None):
        self.root = root
        self.cfg = cfg
        self.tracker = tracker
        self.on_change = on_change
        self.storage = storage
        self.open_ignore_cb = open_ignore

        self.win = tk.Toplevel(root)
        self.win.title("Settings — Active Time Tracker")
        self.win.configure(bg=theme.BG)
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._style()
        self._build()
        self._center()
        self.win.grab_set()
        self.win.focus_force()

    # -- styling ----------------------------------------------------------

    def _style(self) -> None:
        style = ttk.Style(self.win)
        style.configure("S.TFrame", background=theme.BG)
        style.configure("S.TLabel", background=theme.BG, foreground=theme.FG,
                        font=("Segoe UI", 10))
        style.configure("SHint.TLabel", background=theme.BG, foreground=theme.MUTED,
                        font=("Segoe UI", 8))
        style.configure("STitle.TLabel", background=theme.BG, foreground=theme.FG,
                        font=("Segoe UI Semibold", 14))
        style.configure("SSection.TLabel", background=theme.BG, foreground=theme.MUTED,
                        font=("Segoe UI", 8))
        style.configure("S.TEntry", fieldbackground=theme.PANEL, foreground=theme.FG,
                        insertcolor=theme.FG, borderwidth=1)
        style.configure("S.TSpinbox", fieldbackground=theme.PANEL, foreground=theme.FG,
                        insertcolor=theme.FG, arrowsize=13, borderwidth=1)
        style.map("S.TSpinbox", fieldbackground=[("readonly", theme.PANEL)])
        style.configure("S.TCheckbutton", background=theme.BG, foreground=theme.FG,
                        font=("Segoe UI", 10), focuscolor=theme.BG)
        style.map("S.TCheckbutton", background=[("active", theme.BG)])
        style.configure("Save.TButton", background=theme.ACCENT, foreground="#12131c",
                        font=("Segoe UI Semibold", 10), padding=(16, 6), borderwidth=0)
        style.map("Save.TButton", background=[("active", theme.ACCENT)])
        style.configure("Cancel.TButton", background=theme.PANEL, foreground=theme.FG,
                        padding=(16, 6), borderwidth=0)
        style.map("Cancel.TButton", background=[("active", "#34364a")])
        style.configure("SSmall.TButton", background=theme.PANEL, foreground=theme.FG,
                        padding=(10, 3), borderwidth=0)
        style.map("SSmall.TButton", background=[("active", "#34364a")])
        style.configure("S.TCombobox", fieldbackground=theme.PANEL, background=theme.PANEL,
                        foreground=theme.FG, arrowsize=13)
        style.map("S.TCombobox", fieldbackground=[("readonly", theme.PANEL)],
                  foreground=[("readonly", theme.FG)])

    # -- layout -----------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 20}
        frm = ttk.Frame(self.win, style="S.TFrame")
        frm.pack(fill="both", expand=True, pady=16)

        ttk.Label(frm, text="Settings", style="STitle.TLabel").pack(anchor="w", **pad)
        ttk.Label(frm, text="Changes apply immediately.", style="SHint.TLabel").pack(
            anchor="w", pady=(0, 10), **pad)

        ttk.Label(frm, text="TRACKING", style="SSection.TLabel").pack(anchor="w", **pad)

        # Idle timeout
        self.idle_var = tk.StringVar(value=str(_clean_num(self.cfg.idle_timeout_seconds)))
        self._num_row(frm, "Stop timer after idle for", self.idle_var,
                      "seconds",
                      "How long with no keyboard/mouse input before the timer pauses.",
                      from_=2, to=3600, increment=1)

        # Sample interval
        self.poll_var = tk.StringVar(value=str(_clean_num(self.cfg.poll_interval_seconds)))
        self._num_row(frm, "Sample the active window every", self.poll_var,
                      "seconds",
                      "How often focus is checked. Smaller = finer, but slightly more CPU.",
                      from_=0.25, to=10, increment=0.25)

        ttk.Separator(frm).pack(fill="x", pady=12, **pad)
        ttk.Label(frm, text="STARTUP", style="SSection.TLabel").pack(anchor="w", **pad)

        self.autostart_var = tk.BooleanVar(value=self.cfg.autostart)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(4, 0), **pad)
        ttk.Checkbutton(row, text="Start with Windows", variable=self.autostart_var,
                        style="S.TCheckbutton", takefocus=False).pack(anchor="w")
        ttk.Label(frm, text="Launch minimized to the tray when you log in.",
                  style="SHint.TLabel").pack(anchor="w", **pad)

        ttk.Separator(frm).pack(fill="x", pady=12, **pad)
        ttk.Label(frm, text="IGNORED APPS", style="SSection.TLabel").pack(anchor="w", **pad)
        ttk.Label(frm, text="Apps that are never tracked (e.g. games, launchers).",
                  style="SHint.TLabel").pack(anchor="w", **pad)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(6, 0), **pad)
        ttk.Button(row, text="Manage ignored apps…", style="SSmall.TButton",
                   command=self._open_ignore).pack(side="left")

        # Buttons
        btns = ttk.Frame(frm, style="S.TFrame")
        btns.pack(fill="x", pady=(18, 0), **pad)
        ttk.Button(btns, text="Save", style="Save.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btns, text="Cancel", style="Cancel.TButton",
                   command=self.close).pack(side="right", padx=(0, 8))

    def _open_ignore(self) -> None:
        if self.open_ignore_cb:
            self.open_ignore_cb()

    def _num_row(self, parent, label, var, unit, hint, *, from_, to, increment) -> None:
        pad = {"padx": 20}
        row = ttk.Frame(parent, style="S.TFrame")
        row.pack(fill="x", pady=(8, 0), **pad)
        ttk.Label(row, text=label, style="S.TLabel").pack(side="left")
        ttk.Label(row, text=unit, style="SHint.TLabel").pack(side="right")
        ttk.Spinbox(row, textvariable=var, from_=from_, to=to, increment=increment,
                    width=7, style="S.TSpinbox", justify="right").pack(
            side="right", padx=(8, 6))
        ttk.Label(parent, text=hint, style="SHint.TLabel").pack(anchor="w", **pad)

    def _center(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        if rw <= 1:  # root hidden; fall back to screen centre
            rx, ry = 0, 0
            rw, rh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 3
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    # -- save / close -----------------------------------------------------

    def _save(self) -> None:
        try:
            idle = float(self.idle_var.get())
            poll = float(self.poll_var.get())
        except ValueError:
            messagebox.showerror("Invalid value",
                                 "Please enter numbers for the time fields.",
                                 parent=self.win)
            return
        idle = _clamp(idle, 2, 3600)
        poll = _clamp(poll, 0.25, 10)

        self.cfg.idle_timeout_seconds = idle
        self.cfg.poll_interval_seconds = poll

        autostart_changed = self.autostart_var.get() != self.cfg.autostart
        if autostart_changed:
            try:
                autostart.set_enabled(self.autostart_var.get())
                self.cfg.autostart = self.autostart_var.get()
            except OSError:
                messagebox.showwarning(
                    "Autostart", "Couldn't update the Windows startup entry.",
                    parent=self.win)

        self.cfg.save()  # tracker reads cfg live, so this takes effect at once
        if self.on_change:
            self.on_change()
        self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _clean_num(v) -> float | int:
    """Show whole numbers without a trailing .0."""
    f = float(v)
    return int(f) if f == int(f) else f
