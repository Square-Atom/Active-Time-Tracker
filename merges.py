"""Editor for merging several apps into one entry in reports.

Merging is non-destructive and applied at read time: the database keeps the raw
per-exe rows, and a group (e.g. "Godot" = godot.exe + godot_console.exe) is folded
together only when displayed. So merges are retroactive and fully reversible.

Saved groups go to config.json `merges`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import config
import dashboard as theme

IGNORED_KEYS = {"worktimetracker.exe"}


class MergesWindow:
    def __init__(self, root, cfg: config.Config, storage, on_change=None):
        self.root = root
        self.cfg = cfg
        self.storage = storage
        self.on_change = on_change
        # Deep-ish working copy.
        self.groups: list[dict] = [
            {"name": g.get("name", ""), "members": list(g.get("members", []))}
            for g in cfg.merges
        ]
        self.current: int | None = None

        self.win = tk.Toplevel(root)
        self.win.title("App groups — Active Time Tracker")
        self.win.configure(bg=theme.BG)
        self.win.geometry("720x520")
        self.win.minsize(640, 440)
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._style()
        self._build()
        self._populate_groups(select=0 if self.groups else None)
        self.win.grab_set()
        self.win.focus_force()

    def _style(self) -> None:
        s = ttk.Style(self.win)
        s.configure("M.TFrame", background=theme.BG)
        s.configure("M.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI", 10))
        s.configure("MHint.TLabel", background=theme.BG, foreground=theme.MUTED,
                    font=("Segoe UI", 8))
        s.configure("MTitle.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI Semibold", 12))
        s.configure("MHead.TLabel", background=theme.BG, foreground=theme.ACCENT,
                    font=("Segoe UI Semibold", 11))
        s.configure("Save.TButton", background=theme.ACCENT, foreground="#12131c",
                    font=("Segoe UI Semibold", 10), padding=(16, 6), borderwidth=0)
        s.map("Save.TButton", background=[("active", theme.ACCENT)])
        s.configure("Cancel.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(16, 6), borderwidth=0)
        s.map("Cancel.TButton", background=[("active", "#34364a")])
        s.configure("MSmall.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(8, 3), borderwidth=0)
        s.map("MSmall.TButton", background=[("active", "#34364a")])
        s.configure("M.TCombobox", fieldbackground=theme.PANEL, background=theme.PANEL,
                    foreground=theme.FG, arrowsize=13)
        s.map("M.TCombobox", fieldbackground=[("readonly", theme.PANEL)])

    def _build(self) -> None:
        root = ttk.Frame(self.win, style="M.TFrame")
        root.pack(fill="both", expand=True, padx=16, pady=14)
        root.rowconfigure(2, weight=1)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="App groups", style="MTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(root, text="Count several executables as one app in reports "
                             "(e.g. Godot + its console).",
                  style="MHint.TLabel").grid(row=1, column=0, columnspan=2,
                                             sticky="w", pady=(0, 10))

        # Left: group list
        left = ttk.Frame(root, style="M.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(0, weight=1)
        self.grouplist = tk.Listbox(
            left, width=22, activestyle="none", exportselection=False,
            bg=theme.PANEL, fg=theme.FG, highlightthickness=0, borderwidth=0,
            selectbackground=theme.ACCENT, selectforeground="#12131c",
            font=("Segoe UI", 10))
        self.grouplist.grid(row=0, column=0, sticky="nsew")
        self.grouplist.bind("<<ListboxSelect>>", self._on_group_select)
        gb = ttk.Frame(left, style="M.TFrame")
        gb.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(gb, text="+ New group", style="MSmall.TButton",
                   command=self._new_group).pack(side="left")
        ttk.Button(gb, text="Delete", style="MSmall.TButton",
                   command=self._delete_group).pack(side="left", padx=(6, 0))

        # Right: editor
        right = ttk.Frame(root, style="M.TFrame")
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(4, weight=1)

        ttk.Label(right, text="Group name", style="MHead.TLabel").grid(
            row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *a: self._on_name_change())
        self.name_entry = tk.Entry(right, textvariable=self.name_var, bg=theme.PANEL,
                                   fg=theme.FG, insertbackground=theme.FG, borderwidth=0,
                                   highlightthickness=1, highlightbackground="#3a3c52",
                                   font=("Segoe UI", 10))
        self.name_entry.grid(row=1, column=0, sticky="ew", pady=(3, 10))

        ttk.Label(right, text="Members", style="M.TLabel").grid(row=2, column=0, sticky="w")
        add = ttk.Frame(right, style="M.TFrame")
        add.grid(row=3, column=0, sticky="ew", pady=(3, 4))
        add.columnconfigure(0, weight=1)
        self._label_to_exe: dict[str, str] = {}
        self.member_combo = ttk.Combobox(add, style="M.TCombobox", height=12)
        self.member_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(add, text="Add", style="MSmall.TButton",
                   command=self._add_member).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(add, text="Remove", style="MSmall.TButton",
                   command=self._remove_member).grid(row=0, column=2, padx=(6, 0))

        self.memberlist = tk.Listbox(
            right, activestyle="none", exportselection=False,
            bg=theme.PANEL, fg=theme.FG, highlightthickness=1,
            highlightbackground="#3a3c52", borderwidth=0,
            selectbackground=theme.ACCENT, selectforeground="#12131c",
            font=("Segoe UI", 10))
        self.memberlist.grid(row=4, column=0, sticky="nsew")

        # Buttons
        btns = ttk.Frame(root, style="M.TFrame")
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Save", style="Save.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(btns, text="Cancel", style="Cancel.TButton",
                   command=self.close).pack(side="right", padx=(0, 8))

    # -- group list -------------------------------------------------------

    def _group_label(self, g: dict) -> str:
        name = (g.get("name") or "").strip() or "(unnamed)"
        return f"{name}  ·  {len(g.get('members', []))}"

    def _populate_groups(self, select: int | None) -> None:
        self.grouplist.delete(0, "end")
        for g in self.groups:
            self.grouplist.insert("end", self._group_label(g))
        if select is not None and 0 <= select < len(self.groups):
            self.grouplist.selection_clear(0, "end")
            self.grouplist.selection_set(select)
            self._load(select)
        else:
            self.current = None
            self._load(None)

    def _refresh_current_group_label(self) -> None:
        if self.current is None:
            return
        sel = self.grouplist.curselection()
        self.grouplist.delete(self.current)
        self.grouplist.insert(self.current, self._group_label(self.groups[self.current]))
        if sel:
            self.grouplist.selection_set(self.current)

    # -- selection + editing ---------------------------------------------

    def _on_group_select(self, _e=None) -> None:
        sel = self.grouplist.curselection()
        if not sel or sel[0] == self.current:
            return
        self._commit_name()
        self._load(sel[0])

    def _load(self, index: int | None) -> None:
        self.current = index
        enabled = index is not None
        state = "normal" if enabled else "disabled"
        self.name_entry.configure(state=state)
        self.member_combo.configure(state="readonly" if enabled else "disabled")
        if not enabled:
            self.name_var.set("")
            self.memberlist.delete(0, "end")
            self.member_combo.set("")
            return
        g = self.groups[index]
        self.name_var.set(g.get("name", ""))
        self._refresh_members()

    def _on_name_change(self) -> None:
        if self.current is None:
            return
        self.groups[self.current]["name"] = self.name_var.get()
        self._refresh_current_group_label()

    def _commit_name(self) -> None:
        if self.current is not None:
            self.groups[self.current]["name"] = self.name_var.get()

    def _refresh_members(self) -> None:
        if self.current is None:
            return
        members = self.groups[self.current]["members"]
        self.memberlist.delete(0, "end")
        for exe in members:
            self.memberlist.insert("end", f"{config.friendly_name(exe)}  ({exe})")
        # dropdown: known apps not already in this group
        self._label_to_exe = {}
        values = []
        for exe, _name in self.storage.known_apps():
            if exe in IGNORED_KEYS or exe in members:
                continue
            label = f"{config.friendly_name(exe)}  ({exe})"
            self._label_to_exe[label] = exe
            values.append(label)
        self.member_combo["values"] = values
        self.member_combo.set("")

    def _add_member(self) -> None:
        if self.current is None:
            return
        text = self.member_combo.get().strip()
        if not text:
            return
        if text in self._label_to_exe:
            exe = self._label_to_exe[text]
        elif "(" in text and text.endswith(")"):
            exe = text[text.rfind("(") + 1:-1].strip().lower()
        else:
            exe = text.lower()
        members = self.groups[self.current]["members"]
        if exe and exe not in members:
            members.append(exe)
        self._refresh_members()
        self._refresh_current_group_label()

    def _remove_member(self) -> None:
        if self.current is None:
            return
        sel = self.memberlist.curselection()
        if sel:
            del self.groups[self.current]["members"][sel[0]]
            self._refresh_members()
            self._refresh_current_group_label()

    def _new_group(self) -> None:
        self._commit_name()
        self.groups.append({"name": "New group", "members": []})
        self._populate_groups(select=len(self.groups) - 1)

    def _delete_group(self) -> None:
        if self.current is None:
            return
        del self.groups[self.current]
        self._populate_groups(select=(0 if self.groups else None))

    # -- save / close -----------------------------------------------------

    def _save(self) -> None:
        self._commit_name()
        cleaned = []
        for g in self.groups:
            members = [m.strip().lower() for m in g.get("members", []) if m.strip()]
            if not members:
                continue  # drop empty groups
            cleaned.append({"name": (g.get("name") or "Merged").strip() or "Merged",
                            "members": members})
        self.cfg.merges = cleaned
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
