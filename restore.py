"""Load tracked time back from a backup file.

Restoring overwrites history that can't be recreated, so this window is built
to be slow and obvious: it summarises the chosen file before doing anything,
makes you confirm, and snapshots the current data first so a mistake is
undoable.

Two ways to apply a backup:
  * **Merge**   — keeps whichever side recorded more per day/app/file. The safe
                  default: recovers missing history without discarding today.
  * **Replace** — throws away what's here. For when the current data is wrong.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import backups
import config
import dashboard as theme
import storage as storage_mod


def _fmt_span(info: dict) -> str:
    if not info["rows"]:
        return "empty — no tracked time"
    days = f"{info['days']} day" + ("s" if info["days"] != 1 else "")
    span = info["first_day"] if info["first_day"] == info["last_day"] \
        else f"{info['first_day']} → {info['last_day']}"
    return (f"{theme.fmt_duration(info['seconds'])} across {days} "
            f"({span}), {info['apps']} apps")


class RestoreWindow:
    def __init__(self, root, cfg: config.Config, storage, on_change=None):
        self.root = root
        self.cfg = cfg
        self.storage = storage
        self.on_change = on_change
        self.selected: str | None = None

        self.win = tk.Toplevel(root)
        self.win.title("Restore from backup — Active Time Tracker")
        self.win.configure(bg=theme.BG)
        self.win.geometry("620x480")
        self.win.minsize(560, 420)
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._style()
        self._build()
        self._populate()
        self.win.grab_set()
        self.win.focus_force()

    def _style(self) -> None:
        s = ttk.Style(self.win)
        s.configure("R.TFrame", background=theme.BG)
        s.configure("R.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI", 10))
        s.configure("RHint.TLabel", background=theme.BG, foreground=theme.MUTED,
                    font=("Segoe UI", 8))
        s.configure("RTitle.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI Semibold", 13))
        s.configure("RInfo.TLabel", background=theme.PANEL, foreground=theme.FG,
                    font=("Segoe UI", 9))
        s.configure("RSmall.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(10, 3), borderwidth=0)
        s.map("RSmall.TButton", background=[("active", "#34364a")])
        s.configure("RGo.TButton", background=theme.ACCENT, foreground="#12131c",
                    font=("Segoe UI Semibold", 10), padding=(14, 5), borderwidth=0)
        s.map("RGo.TButton", background=[("active", theme.ACCENT)])
        s.configure("RWarn.TButton", background="#7a3b3b", foreground=theme.FG,
                    padding=(14, 5), borderwidth=0)
        s.map("RWarn.TButton", background=[("active", "#8f4545")])

    def _build(self) -> None:
        frm = ttk.Frame(self.win, style="R.TFrame")
        frm.pack(fill="both", expand=True, padx=18, pady=16)
        frm.rowconfigure(3, weight=1)
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="Restore from backup", style="RTitle.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(frm, text="Pick a backup to load your tracked time from. "
                            "Your current data is snapshotted first, so this "
                            "can be undone.",
                  style="RHint.TLabel", wraplength=560, justify="left").grid(
            row=1, column=0, sticky="w", pady=(2, 10))

        ttk.Label(frm, text="BACKUPS FOUND", style="RHint.TLabel").grid(
            row=2, column=0, sticky="w")

        listwrap = ttk.Frame(frm, style="R.TFrame")
        listwrap.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        listwrap.rowconfigure(0, weight=1)
        listwrap.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            listwrap, activestyle="none", exportselection=False,
            bg=theme.PANEL, fg=theme.FG, highlightthickness=1,
            highlightbackground="#3a3c52", borderwidth=0,
            selectbackground=theme.ACCENT, selectforeground="#12131c",
            font=("Segoe UI", 10))
        self.listbox.grid(row=0, column=0, sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", self._on_pick)
        sb = ttk.Scrollbar(listwrap, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)

        row = ttk.Frame(frm, style="R.TFrame")
        row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(row, text="Browse…", style="RSmall.TButton",
                   command=self._browse).pack(side="left")
        ttk.Button(row, text="Open backups folder", style="RSmall.TButton",
                   command=self._open_folder).pack(side="left", padx=(6, 0))

        self.info = ttk.Label(frm, text="Select a backup to see what's in it.",
                              style="RInfo.TLabel", wraplength=560,
                              justify="left", padding=10)
        self.info.grid(row=5, column=0, sticky="ew", pady=(12, 0))

        btns = ttk.Frame(frm, style="R.TFrame")
        btns.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(btns, text="Close", style="RSmall.TButton",
                   command=self.close).pack(side="right")
        self.replace_btn = ttk.Button(btns, text="Replace my data",
                                      style="RWarn.TButton", state="disabled",
                                      command=lambda: self._apply(storage_mod.REPLACE))
        self.replace_btn.pack(side="right", padx=(8, 8))
        self.merge_btn = ttk.Button(btns, text="Merge into my data",
                                    style="RGo.TButton", state="disabled",
                                    command=lambda: self._apply(storage_mod.MERGE))
        self.merge_btn.pack(side="right")

    # -- choosing ---------------------------------------------------------

    def _populate(self) -> None:
        self.paths: list[str] = []
        self.listbox.delete(0, "end")
        for stamp, path in backups.list_backups(self.cfg):
            size = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
            self.listbox.insert("end", f"{stamp}      {size:,.0f} KB")
            self.paths.append(path)
        if not self.paths:
            self.listbox.insert("end", "  (no backups in the backup folder)")
            self.listbox.configure(state="disabled")

    def _on_pick(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.paths):
            self._select(self.paths[sel[0]])

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win, title="Choose a backup",
            initialdir=backups.backup_dir(self.cfg),
            filetypes=[("Tracker backup", "*.db"), ("All files", "*.*")])
        if path:
            self.listbox.selection_clear(0, "end")
            self._select(path)

    def _select(self, path: str) -> None:
        try:
            info = storage_mod.describe_backup(path)
        except storage_mod.BadBackup as exc:
            self.selected = None
            self.info.configure(text=f"⚠ {exc}")
            self._enable(False)
            return
        self.selected = path
        self.info.configure(
            text=f"{os.path.basename(path)}\n{_fmt_span(info)}")
        self._enable(bool(info["rows"]))

    def _enable(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        self.merge_btn.configure(state=state)
        self.replace_btn.configure(state=state)

    def _open_folder(self) -> None:
        import sysinfo
        path = backups.backup_dir(self.cfg)
        try:
            os.makedirs(path, exist_ok=True)
            sysinfo.open_path(path)
        except OSError:
            messagebox.showwarning("Backups", f"Couldn't open:\n{path}",
                                   parent=self.win)

    # -- applying ---------------------------------------------------------

    def _apply(self, mode: str) -> None:
        if not self.selected:
            return
        name = os.path.basename(self.selected)
        if mode == storage_mod.REPLACE:
            ok = messagebox.askyesno(
                "Replace all tracked time?",
                f"This deletes everything currently recorded and keeps only "
                f"what's in {name}.\n\nA snapshot of your current data is saved "
                f"to the backups folder first, so you can undo this.\n\nContinue?",
                icon="warning", default="no", parent=self.win)
        else:
            ok = messagebox.askyesno(
                "Merge this backup?",
                f"Time from {name} will be added to your history. Where both "
                f"have a record for the same day and file, the larger one is "
                f"kept.\n\nContinue?",
                default="yes", parent=self.win)
        if not ok:
            return

        snapshot = backups.safety_copy(self.storage, self.cfg)
        try:
            rows = self.storage.restore_from(self.selected, mode)
        except Exception as exc:
            messagebox.showerror("Restore failed", str(exc), parent=self.win)
            return

        if self.on_change:
            self.on_change()
        undo = (f"\n\nYour previous data was saved as:\n{os.path.basename(snapshot)}"
                if snapshot else "")
        messagebox.showinfo(
            "Restore complete",
            f"{'Replaced' if mode == storage_mod.REPLACE else 'Merged'} from "
            f"{name}.\nYou now have {rows:,} records.{undo}", parent=self.win)
        self._populate()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
