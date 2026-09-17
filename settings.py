"""Settings window.

A tabbed dialog for adjusting tracker behaviour: General (tracking, startup,
updates), Ignored apps, Backup, Timeline and About. Add rows in the matching
`_build_*` method (and read them in `_save`) to grow it over time.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import autostart
import backups
import config
import dashboard as theme  # reuse the dashboard's colour constants
import hotkeys
import sysinfo
import updatedialog
import updater

AUTHOR_EMAIL = "contact@pixelmancer.studio"


class SettingsWindow:
    def __init__(self, root: tk.Tk, cfg: config.Config, tracker, on_change=None,
                 storage=None, open_ignore=None, open_restore=None,
                 apply_hotkey=None):
        self.root = root
        self.cfg = cfg
        self.tracker = tracker
        self.on_change = on_change
        self.storage = storage
        self.open_ignore_cb = open_ignore
        self.open_restore_cb = open_restore
        # apply_hotkey(spec) -> bool: registers the note hotkey ("" = none).
        self.apply_hotkey_cb = apply_hotkey

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
        # The clam theme outlines tabs and the page in near-white; tone the
        # outlines down to the panel colours.
        edges = {"bordercolor": "#3a3c52", "lightcolor": theme.BG,
                 "darkcolor": theme.BG}
        style.configure("S.TNotebook", background=theme.BG, **edges)
        style.configure("S.TNotebook.Tab", background=theme.PANEL,
                        foreground=theme.MUTED, padding=(12, 5),
                        font=("Segoe UI", 9), focuscolor=theme.BG, **edges)
        style.map("S.TNotebook.Tab",
                  background=[("selected", theme.BG), ("active", "#2d2e40")],
                  foreground=[("selected", theme.FG)])

    # -- layout -----------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 20}
        outer = ttk.Frame(self.win, style="S.TFrame")
        outer.pack(fill="both", expand=True, pady=16)

        ttk.Label(outer, text="Settings", style="STitle.TLabel").pack(anchor="w", **pad)
        ttk.Label(outer, text="Changes apply immediately.", style="SHint.TLabel").pack(
            anchor="w", pady=(0, 10), **pad)

        self.tabs = ttk.Notebook(outer, style="S.TNotebook", takefocus=False)
        self.tabs.pack(fill="both", expand=True, **pad)

        def tab(title):
            page = ttk.Frame(self.tabs, style="S.TFrame", padding=(0, 12, 0, 4))
            self.tabs.add(page, text=title)
            return page

        self._build_general(tab("General"))
        self._build_ignored(tab("Ignored apps"))
        self._build_backup(tab("Backup"))
        self._build_timeline(tab("Timeline"))
        self._build_about(tab("About"))

        # Buttons
        btns = ttk.Frame(outer, style="S.TFrame")
        btns.pack(fill="x", pady=(14, 0), **pad)
        ttk.Button(btns, text="Save", style="Save.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btns, text="Cancel", style="Cancel.TButton",
                   command=self.close).pack(side="right", padx=(0, 8))

    def _build_general(self, frm) -> None:
        pad = {"padx": 20}
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

        ttk.Label(frm, text="Game controllers and MIDI keyboards count as input "
                            "too, so the timer keeps running while you play.",
                  style="SHint.TLabel", wraplength=430, justify="left").pack(
            anchor="w", pady=(10, 0), **pad)

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
        ttk.Label(frm, text="UPDATES", style="SSection.TLabel").pack(anchor="w", **pad)

        self.check_updates_var = tk.BooleanVar(value=self.cfg.check_updates_on_startup)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(4, 0), **pad)
        ttk.Checkbutton(row, text="Automatically check for updates on startup",
                        variable=self.check_updates_var, style="S.TCheckbutton",
                        takefocus=False).pack(anchor="w")
        ttk.Label(frm, text=f"You're running version {config.APP_VERSION}. "
                            "Updates are downloaded manually from GitHub.",
                  style="SHint.TLabel").pack(anchor="w", **pad)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(6, 0), **pad)
        self.update_btn = ttk.Button(row, text="Check for updates now",
                                     style="SSmall.TButton", command=self._check_updates)
        self.update_btn.pack(side="left")
        self.update_status = ttk.Label(row, text="", style="SHint.TLabel")
        self.update_status.pack(side="left", padx=(10, 0))

    def _build_ignored(self, frm) -> None:
        pad = {"padx": 20}
        ttk.Label(frm, text="IGNORED APPS", style="SSection.TLabel").pack(anchor="w", **pad)
        ttk.Label(frm, text="Apps that are never tracked (e.g. games, launchers).",
                  style="SHint.TLabel").pack(anchor="w", **pad)
        ttk.Label(frm, text="Their time isn't counted, and the timeline shows it "
                            "as \"Not tracked\" without naming the app.",
                  style="SHint.TLabel", wraplength=430, justify="left").pack(
            anchor="w", **pad)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(8, 0), **pad)
        ttk.Button(row, text="Manage ignored apps…", style="SSmall.TButton",
                   command=self._open_ignore).pack(side="left")

    def _build_backup(self, frm) -> None:
        pad = {"padx": 20}
        ttk.Label(frm, text="BACKUP", style="SSection.TLabel").pack(anchor="w", **pad)

        self.backup_var = tk.BooleanVar(value=self.cfg.backup_enabled)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(4, 0), **pad)
        ttk.Checkbutton(row, text="Back up my data", variable=self.backup_var,
                        style="S.TCheckbutton", takefocus=False).pack(anchor="w")

        self.backup_every_var = tk.StringVar(
            value=str(int(self.cfg.backup_interval_minutes)))
        self._num_row(frm, "Back up every", self.backup_every_var, "minutes",
                      f"Also on exit. Keeps the {self.cfg.backup_keep} most recent "
                      "days; a backup takes a few hundredths of a second.",
                      from_=1, to=1440, increment=5)
        ttk.Label(frm, text="Choose a synced folder (OneDrive, Google Drive…) to "
                            "keep the copies off this machine.",
                  style="SHint.TLabel", wraplength=430, justify="left").pack(
            anchor="w", **pad)

        self.backup_path_var = tk.StringVar(value=backups.backup_dir(self.cfg))
        ttk.Label(frm, textvariable=self.backup_path_var, style="SHint.TLabel",
                  wraplength=430, justify="left").pack(anchor="w", pady=(4, 0), **pad)

        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(6, 0), **pad)
        ttk.Button(row, text="Change folder…", style="SSmall.TButton",
                   command=self._choose_backup_dir).pack(side="left")
        ttk.Button(row, text="Open folder", style="SSmall.TButton",
                   command=self._open_backup_dir).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Back up now", style="SSmall.TButton",
                   command=self._backup_now).pack(side="left", padx=(6, 0))
        self.backup_status = ttk.Label(row, text="", style="SHint.TLabel")
        self.backup_status.pack(side="left", padx=(10, 0))

        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(6, 0), **pad)
        ttk.Button(row, text="Restore from backup…", style="SSmall.TButton",
                   command=self._open_restore).pack(side="left")

    def _build_timeline(self, frm) -> None:
        pad = {"padx": 20}
        ttk.Label(frm, text="TIMELINE", style="SSection.TLabel").pack(anchor="w", **pad)

        self.timeline_var = tk.BooleanVar(value=self.cfg.timeline_enabled)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(4, 0), **pad)
        ttk.Checkbutton(row, text="Show the timeline in the Day view",
                        variable=self.timeline_var, style="S.TCheckbutton",
                        takefocus=False).pack(anchor="w")
        ttk.Label(frm, text="Which app had focus through the day, with idle time "
                            "and notes. Click a note to edit or delete it; "
                            "double-click the bar to add one at that time.",
                  style="SHint.TLabel", wraplength=430, justify="left").pack(
            anchor="w", **pad)

        ttk.Separator(frm).pack(fill="x", pady=12, **pad)
        ttk.Label(frm, text="NOTES", style="SSection.TLabel").pack(anchor="w", **pad)

        self.hotkey_var = tk.StringVar(value=self.cfg.note_hotkey)
        row = ttk.Frame(frm, style="S.TFrame")
        row.pack(fill="x", pady=(8, 0), **pad)
        ttk.Label(row, text="New note hotkey", style="S.TLabel").pack(side="left")
        self.hotkey_entry = HotkeyEntry(row, self.hotkey_var)
        self.hotkey_entry.pack(side="left", padx=(8, 6))
        ttk.Button(row, text="Clear", style="SSmall.TButton",
                   command=lambda: self.hotkey_var.set("")).pack(side="left")
        if sysinfo.HOTKEYS_SUPPORTED:
            hint = ("Click the box and press a combination, e.g. Ctrl+Alt+N. "
                    "It works anywhere, even with the dashboard closed. "
                    "Leave it empty for no hotkey.")
        else:
            hint = "Global hotkeys are only available on Windows for now."
        ttk.Label(frm, text=hint, style="SHint.TLabel", wraplength=430,
                  justify="left").pack(anchor="w", **pad)

    def _build_about(self, frm) -> None:
        pad = {"padx": 20}
        ttk.Label(frm, text="ABOUT", style="SSection.TLabel").pack(anchor="w", **pad)
        ttk.Label(frm, text=f"Active Time Tracker {config.APP_VERSION} — "
                            "created by Hau Tran, Pixelmancer Studio.",
                  style="SHint.TLabel").pack(anchor="w", pady=(4, 0), **pad)

        contact = ttk.Frame(frm, style="S.TFrame")
        contact.pack(fill="x", pady=(2, 0), **pad)
        ttk.Label(contact, text="Feedback and bug reports are welcome:",
                  style="SHint.TLabel").pack(side="left")
        email = tk.Label(contact, text=AUTHOR_EMAIL, bg=theme.BG, fg=theme.ACCENT,
                         font=("Segoe UI", 8, "underline"), cursor="hand2")
        email.pack(side="left", padx=(4, 0))
        email.bind("<Button-1>", lambda e: self._mail_author())

    def _open_ignore(self) -> None:
        if self.open_ignore_cb:
            self.open_ignore_cb()

    # -- backup -----------------------------------------------------------

    def _pending_cfg(self) -> config.Config:
        """A view of the config with the not-yet-saved backup folder applied."""
        chosen = self.backup_path_var.get().strip()
        default = os.path.join(config.APP_DIR, "backups")
        self.cfg.backup_dir = "" if chosen in ("", default) else chosen
        return self.cfg

    def _choose_backup_dir(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self.win, title="Choose a backup folder",
            initialdir=self.backup_path_var.get() or config.APP_DIR)
        if chosen:
            self.backup_path_var.set(os.path.normpath(chosen))

    def _open_backup_dir(self) -> None:
        path = self.backup_path_var.get()
        try:
            os.makedirs(path, exist_ok=True)
            sysinfo.open_path(path)
        except OSError:
            messagebox.showwarning("Backup", f"Couldn't open:\n{path}",
                                   parent=self.win)

    def _mail_author(self) -> None:
        """Open the user's mail client — never fail loudly over a footer link."""
        import webbrowser
        try:
            webbrowser.open(f"mailto:{AUTHOR_EMAIL}")
        except Exception:
            messagebox.showinfo("Contact", AUTHOR_EMAIL, parent=self.win)

    def _open_restore(self) -> None:
        if self.open_restore_cb:
            self.open_restore_cb()

    def _backup_now(self) -> None:
        self.backup_status.configure(text="Backing up…")
        self.win.update_idletasks()
        # force: the user asked for this explicitly, so don't second-guess it
        # with the shrink check the automatic runs use.
        path = (backups.run(self.storage, self._pending_cfg(), force=True)
                if self.storage else None)
        self.backup_status.configure(
            text=f"Saved {os.path.basename(path)}" if path else "Backup failed")

    def _check_updates(self) -> None:
        self.update_btn.configure(state="disabled")
        self.update_status.configure(text="Checking…")

        def done(result):
            # Called on the worker thread — hop back to the UI thread.
            self.win.after(0, lambda: self._show_update_result(result))

        updater.check_async(done)

    def _show_update_result(self, result) -> None:
        if not self.win.winfo_exists():
            return
        self.update_btn.configure(state="normal")
        self.update_status.configure(text="")
        updatedialog.show_result(self.win, result)

    def _num_row(self, parent, label, var, unit, hint, *, from_, to, increment) -> None:
        """A "<label> [value] <unit>" row.

        Everything sits together on the left so the row reads as one phrase —
        pushing the box to the far right left a gap wide enough that the number
        stopped looking connected to its label.
        """
        pad = {"padx": 20}
        row = ttk.Frame(parent, style="S.TFrame")
        row.pack(fill="x", pady=(8, 0), **pad)
        ttk.Label(row, text=label, style="S.TLabel").pack(side="left")
        ttk.Spinbox(row, textvariable=var, from_=from_, to=to, increment=increment,
                    width=6, style="S.TSpinbox", justify="right").pack(
            side="left", padx=(8, 6))
        ttk.Label(row, text=unit, style="SHint.TLabel").pack(side="left")
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

        # The hotkey first: if another app owns it, stay open to pick another.
        timeline_on = bool(self.timeline_var.get())
        hotkey = hotkeys.normalize(self.hotkey_var.get())
        wanted = hotkey if timeline_on else ""
        current = self.cfg.note_hotkey if self.cfg.timeline_enabled else ""
        if wanted != current and self.apply_hotkey_cb is not None:
            if not self.apply_hotkey_cb(wanted):
                self.tabs.select(3)
                messagebox.showwarning(
                    "Hotkey unavailable",
                    f"{hotkey} is already used by Windows or another app. "
                    "Please choose a different combination.",
                    parent=self.win)
                return
        self.cfg.timeline_enabled = timeline_on
        self.cfg.note_hotkey = hotkey

        self.cfg.idle_timeout_seconds = idle
        self.cfg.poll_interval_seconds = poll
        self.cfg.check_updates_on_startup = bool(self.check_updates_var.get())
        self.cfg.backup_enabled = bool(self.backup_var.get())
        try:
            self.cfg.backup_interval_minutes = int(
                _clamp(float(self.backup_every_var.get()), 1, 1440))
        except ValueError:
            pass                      # keep the previous value on nonsense input
        self._pending_cfg()  # normalises backup_dir ("" when it's the default)

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


class HotkeyEntry(tk.Entry):
    """A box that records the key combination pressed while it has focus.

    Typing doesn't insert text: modifiers build up as they're held, and the
    first ordinary key completes the combination. Backspace or Delete on its
    own clears it; Escape (or leaving the box) keeps the previous value.
    """

    PROMPT = "Press keys…"

    def __init__(self, parent, var: tk.StringVar):
        self.var = var
        self._shown = tk.StringVar(value=var.get())
        super().__init__(parent, textvariable=self._shown, width=18,
                         bg=theme.PANEL, fg=theme.FG, readonlybackground=theme.PANEL,
                         insertbackground=theme.PANEL, borderwidth=0,
                         highlightthickness=1, highlightbackground="#3a3c52",
                         highlightcolor=theme.ACCENT, font=("Segoe UI", 10),
                         justify="center", cursor="hand2")
        self.configure(state="readonly")
        self._held: set[str] = set()
        var.trace_add("write", lambda *a: self._shown.set(var.get()))
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<KeyPress>", self._on_key)
        self.bind("<KeyRelease>", self._on_release)
        self.bind("<Button-1>", lambda e: self.focus_set())

    def _preview(self) -> None:
        mods = [m for m in hotkeys.MODIFIERS if m in self._held]
        self._shown.set("+".join(mods) + "+…" if mods else self.PROMPT)

    def _on_focus_in(self, _event=None) -> None:
        self._held.clear()
        self._preview()

    def _on_focus_out(self, _event=None) -> None:
        self._held.clear()
        self._shown.set(self.var.get())

    def _finish(self) -> str:
        self._held.clear()
        self.master.focus_set()        # leaving the box shows the result
        return "break"

    def _on_key(self, event):
        mod = hotkeys.modifier_for_keysym(event.keysym)
        if mod:
            self._held.add(mod)
            self._preview()
            return "break"
        if event.keysym == "Tab":
            return None                # keep keyboard navigation working
        if not self._held and event.keysym == "Escape":
            return self._finish()
        if not self._held and event.keysym in ("BackSpace", "Delete"):
            self.var.set("")
            return self._finish()
        key = hotkeys.key_from_tk(event.keysym, event.keycode)
        spec = hotkeys.normalize(hotkeys.format_spec(self._held, key)) if key else ""
        if spec:
            self.var.set(spec)
            return self._finish()
        return "break"                 # not a usable combination; keep waiting

    def _on_release(self, event):
        mod = hotkeys.modifier_for_keysym(event.keysym)
        if mod:
            self._held.discard(mod)
            self._preview()
        return "break"
