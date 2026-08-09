"""Dedicated window for managing the ignored-apps list.

Ignored apps are never tracked and are hidden from the dashboard reports. This
lives in its own window (rather than a cramped section of Settings) so the list
has room to grow. Saved to config.json `ignore_apps`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import config
import dashboard as theme


class IgnoreWindow:
    def __init__(self, root, cfg: config.Config, storage, on_change=None):
        self.root = root
        self.cfg = cfg
        self.storage = storage
        self.on_change = on_change
        self.ignored = list(cfg.ignore_apps)  # working copy

        self.win = tk.Toplevel(root)
        self.win.title("Ignored apps — Active Time Tracker")
        self.win.configure(bg=theme.BG)
        self.win.geometry("440x560")
        self.win.minsize(380, 420)
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._style()
        self._build()
        self._refresh()
        self.win.grab_set()
        self.win.focus_force()

    def _style(self) -> None:
        s = ttk.Style(self.win)
        s.configure("I.TFrame", background=theme.BG)
        s.configure("I.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI", 10))
        s.configure("IHint.TLabel", background=theme.BG, foreground=theme.MUTED,
                    font=("Segoe UI", 8))
        s.configure("ITitle.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI Semibold", 14))
        s.configure("Save.TButton", background=theme.ACCENT, foreground="#12131c",
                    font=("Segoe UI Semibold", 10), padding=(16, 6), borderwidth=0)
        s.map("Save.TButton", background=[("active", theme.ACCENT)])
        s.configure("Cancel.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(16, 6), borderwidth=0)
        s.map("Cancel.TButton", background=[("active", "#34364a")])
        s.configure("ISmall.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(10, 3), borderwidth=0)
        s.map("ISmall.TButton", background=[("active", "#34364a")])
        s.configure("I.TCombobox", fieldbackground=theme.PANEL, background=theme.PANEL,
                    foreground=theme.FG, arrowsize=13)
        s.map("I.TCombobox", fieldbackground=[("readonly", theme.PANEL)])

    def _build(self) -> None:
        frm = ttk.Frame(self.win, style="I.TFrame")
        frm.pack(fill="both", expand=True, padx=18, pady=16)
        frm.rowconfigure(3, weight=1)
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="Ignored apps", style="ITitle.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(frm, text="These apps are never tracked and are hidden from reports.",
                  style="IHint.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 10))

        # Add row
        add = ttk.Frame(frm, style="I.TFrame")
        add.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        add.columnconfigure(0, weight=1)
        self._label_to_exe: dict[str, str] = {}
        self.combo = ttk.Combobox(add, style="I.TCombobox", height=14)
        self.combo.grid(row=0, column=0, sticky="ew")
        self.combo.bind("<Return>", lambda e: self._add())
        ttk.Button(add, text="Add", style="ISmall.TButton",
                   command=self._add).grid(row=0, column=1, padx=(6, 0))

        # List
        listwrap = ttk.Frame(frm, style="I.TFrame")
        listwrap.grid(row=3, column=0, sticky="nsew")
        listwrap.rowconfigure(0, weight=1)
        listwrap.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            listwrap, activestyle="none", exportselection=False,
            bg=theme.PANEL, fg=theme.FG, highlightthickness=1,
            highlightbackground="#3a3c52", borderwidth=0,
            selectbackground=theme.ACCENT, selectforeground="#12131c",
            font=("Segoe UI", 10))
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(listwrap, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)

        ttk.Button(frm, text="Remove selected", style="ISmall.TButton",
                   command=self._remove).grid(row=4, column=0, sticky="w", pady=(8, 0))

        # Buttons
        btns = ttk.Frame(frm, style="I.TFrame")
        btns.grid(row=5, column=0, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Save", style="Save.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btns, text="Cancel", style="Cancel.TButton",
                   command=self.close).pack(side="right", padx=(0, 8))

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        for exe in self.ignored:
            self.listbox.insert("end", f"{config.friendly_name(exe)}  ({exe})")
        self._label_to_exe = {}
        values = []
        known = self.storage.known_apps() if self.storage else []
        for exe, _name in known:
            if exe in self.ignored or exe == "worktimetracker.exe":
                continue
            label = f"{config.friendly_name(exe)}  ({exe})"
            self._label_to_exe[label] = exe
            values.append(label)
        self.combo["values"] = values
        self.combo.set("")

    def _add(self) -> None:
        text = self.combo.get().strip()
        if not text:
            return
        if text in self._label_to_exe:
            exe = self._label_to_exe[text]
        elif "(" in text and text.endswith(")"):
            exe = text[text.rfind("(") + 1:-1].strip().lower()
        else:
            exe = text.lower()
        if exe and exe not in self.ignored:
            self.ignored.append(exe)
        self._refresh()

    def _remove(self) -> None:
        sel = self.listbox.curselection()
        if sel:
            del self.ignored[sel[0]]
            self._refresh()

    def _save(self) -> None:
        self.cfg.ignore_apps = [a.strip().lower() for a in self.ignored if a.strip()]
        self.cfg.save()
        if self.on_change:
            self.on_change()
        self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
