"""The Tags window: what each tag holds, and a way to take things out of it.

A tag is a named bucket of *items* — a whole app, or one file/site inside an
app. Tagging is non-destructive and applied at read time: the database keeps
its raw per-app/per-file rows, and the dashboard's Tags mode folds them into
tag totals only when displayed. So tags are retroactive and reversible, and an
item can sit in several tags at once (its time counts toward each of them).

Items are *added* by right-clicking a row in the dashboard, which is where you
can see what's worth tagging; this window is for reviewing a tag and removing
what doesn't belong. Every change here is saved straight away.

Saved tags go to config.json `tags`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import config
import dashboard as theme
import storage as storage_mod

DANGER = "#ef5350"   # the X button's hover colour, as in the timeline


def ask_tag_name(parent, title: str, prompt: str, initial: str = "") -> str:
    """Modal one-line prompt for a tag name. '' when cancelled or left empty."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=theme.BG)
    dlg.resizable(False, False)
    dlg.transient(parent)
    result = {"name": ""}

    wrap = tk.Frame(dlg, bg=theme.BG)
    wrap.pack(fill="both", expand=True, padx=18, pady=14)
    tk.Label(wrap, text=prompt, bg=theme.BG, fg=theme.FG,
             font=("Segoe UI", 10)).pack(anchor="w")

    var = tk.StringVar(value=initial)
    entry = tk.Entry(wrap, textvariable=var, width=28, bg=theme.PANEL,
                     fg=theme.FG, insertbackground=theme.FG, borderwidth=0,
                     highlightthickness=1, highlightbackground="#3a3c52",
                     font=("Segoe UI", 10))
    entry.pack(fill="x", pady=(6, 0), ipady=3)

    def ok():
        result["name"] = var.get().strip()
        dlg.destroy()

    btns = tk.Frame(wrap, bg=theme.BG)
    btns.pack(fill="x", pady=(14, 0))
    tk.Button(btns, text="OK", command=ok, bg=theme.ACCENT, fg="#12131c",
              relief="flat", padx=16, pady=4, cursor="hand2",
              font=("Segoe UI Semibold", 10)).pack(side="right")
    tk.Button(btns, text="Cancel", command=dlg.destroy, bg=theme.PANEL,
              fg=theme.FG, relief="flat", padx=14, pady=4,
              cursor="hand2").pack(side="right", padx=(0, 8))

    dlg.bind("<Return>", lambda e: ok())
    dlg.bind("<Escape>", lambda e: dlg.destroy())

    dlg.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    if pw <= 1:                       # parent not mapped yet (or withdrawn)
        px = py = 0
        pw, ph = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
    dlg.geometry(f"+{max(0, px + (pw - dlg.winfo_width()) // 2)}"
                 f"+{max(0, py + (ph - dlg.winfo_height()) // 3)}")

    entry.focus_set()
    entry.select_range(0, "end")
    dlg.grab_set()
    dlg.wait_window()
    return result["name"]


class TagsWindow:
    def __init__(self, root, cfg: config.Config, storage, on_change=None):
        self.root = root
        self.cfg = cfg
        self.storage = storage
        self.on_change = on_change
        self.current: str | None = None      # selected tag name
        # exe -> the display name the database last saw it under.
        self._app_names = dict(storage.known_apps()) if storage else {}

        self.win = tk.Toplevel(root)
        self.win.title("Tags — Active Time Tracker")
        self.win.configure(bg=theme.BG)
        self.win.geometry("720x520")
        self.win.minsize(640, 440)
        self.win.transient(root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._style()
        self._build()
        names = self.cfg.tag_names()
        self._populate_tags(select=names[0] if names else None)
        self.win.grab_set()
        self.win.focus_force()

    def _style(self) -> None:
        s = ttk.Style(self.win)
        s.configure("T.TFrame", background=theme.BG)
        s.configure("TRow.TFrame", background=theme.PANEL)
        s.configure("T.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI", 10))
        s.configure("TRow.TLabel", background=theme.PANEL, foreground=theme.FG,
                    font=("Segoe UI", 10))
        s.configure("TRowMuted.TLabel", background=theme.PANEL,
                    foreground=theme.MUTED, font=("Segoe UI", 9))
        s.configure("THint.TLabel", background=theme.BG, foreground=theme.MUTED,
                    font=("Segoe UI", 8))
        s.configure("TTitle.TLabel", background=theme.BG, foreground=theme.FG,
                    font=("Segoe UI Semibold", 12))
        s.configure("THead.TLabel", background=theme.BG, foreground=theme.ACCENT,
                    font=("Segoe UI Semibold", 11))
        s.configure("TSmall.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(8, 3), borderwidth=0)
        s.map("TSmall.TButton", background=[("active", "#34364a")])
        s.configure("TX.TButton", background=theme.PANEL, foreground=theme.MUTED,
                    padding=(4, 0), borderwidth=0, font=("Segoe UI", 10))
        s.map("TX.TButton", background=[("active", DANGER)],
              foreground=[("active", "#ffffff")])
        s.configure("Close.TButton", background=theme.PANEL, foreground=theme.FG,
                    padding=(16, 6), borderwidth=0)
        s.map("Close.TButton", background=[("active", "#34364a")])

    def _build(self) -> None:
        root = ttk.Frame(self.win, style="T.TFrame")
        root.pack(fill="both", expand=True, padx=16, pady=14)
        root.rowconfigure(2, weight=1)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="Tags", style="TTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(root, text="Group apps, files and websites however you like — "
                             "the dashboard's Tags mode adds up each tag's time. "
                             "Add things by right-clicking them in the dashboard.",
                  style="THint.TLabel", wraplength=660, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Left: the tags themselves
        left = ttk.Frame(root, style="T.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(0, weight=1)
        self.taglist = tk.Listbox(
            left, width=24, activestyle="none", exportselection=False,
            bg=theme.PANEL, fg=theme.FG, highlightthickness=0, borderwidth=0,
            selectbackground=theme.ACCENT, selectforeground="#12131c",
            font=("Segoe UI", 10))
        self.taglist.grid(row=0, column=0, sticky="nsew")
        self.taglist.bind("<<ListboxSelect>>", self._on_tag_select)
        self.taglist.bind("<Double-Button-1>", lambda e: self._rename_tag())

        buttons = ttk.Frame(left, style="T.TFrame")
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="+ New tag", style="TSmall.TButton",
                   command=self._new_tag).pack(side="left")
        ttk.Button(buttons, text="Rename", style="TSmall.TButton",
                   command=self._rename_tag).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Delete", style="TSmall.TButton",
                   command=self._delete_tag).pack(side="left", padx=(6, 0))

        # Right: what's in the selected tag
        right = ttk.Frame(root, style="T.TFrame")
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self.items_title = ttk.Label(right, text="", style="THead.TLabel")
        self.items_title.grid(row=0, column=0, sticky="w", pady=(0, 6))

        wrap = ttk.Frame(right, style="T.TFrame")
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.items_canvas = tk.Canvas(wrap, bg=theme.BG, highlightthickness=0)
        self.items_canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll = ttk.Scrollbar(wrap, orient="vertical",
                                    command=self.items_canvas.yview)
        self.items_canvas.configure(yscrollcommand=self._on_scrolled)
        self.items_inner = ttk.Frame(self.items_canvas, style="T.TFrame")
        self._inner = self.items_canvas.create_window(
            (0, 0), window=self.items_inner, anchor="nw")
        self.items_canvas.bind(
            "<Configure>",
            lambda e: self.items_canvas.itemconfigure(self._inner, width=e.width))
        self.items_inner.bind(
            "<Configure>",
            lambda e: self.items_canvas.configure(
                scrollregion=self.items_canvas.bbox("all")))

        for widget in (self.items_canvas, self.items_inner):
            widget.bind("<MouseWheel>", self._on_wheel)
            widget.bind("<Button-4>", lambda e: self.items_canvas.yview_scroll(-2, "units"))
            widget.bind("<Button-5>", lambda e: self.items_canvas.yview_scroll(2, "units"))

        btns = ttk.Frame(root, style="T.TFrame")
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Close", style="Close.TButton",
                   command=self.close).pack(side="right")

    def _on_wheel(self, event) -> None:
        self.items_canvas.yview_scroll(-2 if event.delta > 0 else 2, "units")

    def _on_scrolled(self, first: str, last: str) -> None:
        """Show the scrollbar only when the items don't all fit."""
        self.scroll.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self.scroll.winfo_ismapped():
            self.scroll.grid(row=0, column=1, sticky="ns")
        elif not needed and self.scroll.winfo_ismapped():
            self.scroll.grid_remove()

    # -- tag list ---------------------------------------------------------

    def _tag_label(self, name: str) -> str:
        return f"{name}  ·  {len(self.cfg.tag_items(name))}"

    def _populate_tags(self, select: str | None) -> None:
        names = self.cfg.tag_names()
        self.taglist.delete(0, "end")
        for name in names:
            self.taglist.insert("end", self._tag_label(name))
        if select in names:
            index = names.index(select)
            self.taglist.selection_clear(0, "end")
            self.taglist.selection_set(index)
            self.taglist.see(index)
            self._load(select)
        else:
            self._load(names[0] if names else None)
            if names:
                self.taglist.selection_set(0)

    def _on_tag_select(self, _e=None) -> None:
        sel = self.taglist.curselection()
        if not sel:
            return
        names = self.cfg.tag_names()
        if sel[0] < len(names):
            self._load(names[sel[0]])

    def _load(self, name: str | None) -> None:
        self.current = name
        if name is None:
            self.items_title.configure(
                text="No tags yet" if not self.cfg.tags else "Select a tag")
        else:
            self.items_title.configure(text=f"In “{name}”")
        self._refresh_items()

    # -- items ------------------------------------------------------------

    def _item_label(self, app: str, file: str | None) -> str:
        app_name = self._app_names.get(app) or config.friendly_name(app)
        return storage_mod.item_label(app_name, file)

    def _refresh_items(self) -> None:
        for child in list(self.items_inner.winfo_children()):
            child.destroy()
        if self.current is None:
            return
        items = self.cfg.tag_items(self.current)
        if not items:
            ttk.Label(self.items_inner,
                      text="Nothing here yet. Right-click an app, file or site "
                           "in the dashboard and pick this tag.",
                      style="THint.TLabel", wraplength=380,
                      justify="left").pack(anchor="w", pady=(4, 0))
            return
        for app, file in items:
            row = ttk.Frame(self.items_inner, style="TRow.TFrame", padding=(10, 5))
            row.pack(fill="x", pady=(0, 3))
            row.columnconfigure(0, weight=1)
            ttk.Label(row, text=self._item_label(app, file), style="TRow.TLabel",
                      anchor="w").grid(row=0, column=0, sticky="ew")
            ttk.Label(row, text="whole app" if file is None else "",
                      style="TRowMuted.TLabel").grid(row=0, column=1, padx=(8, 8))
            ttk.Button(row, text="✕", width=2, style="TX.TButton",
                       command=lambda a=app, f=file: self._remove(a, f)).grid(
                row=0, column=2)
            for widget in (row,):
                widget.bind("<MouseWheel>", self._on_wheel)

    def _remove(self, app: str, file: str | None) -> None:
        if self.current is None:
            return
        self.cfg.set_item_tag(self.current, app, file, False)
        self._save()
        self._populate_tags(select=self.current)

    # -- tag actions ------------------------------------------------------

    def _new_tag(self) -> None:
        name = ask_tag_name(self.win, "New tag", "Name for the new tag:")
        if not name:
            return
        created = self.cfg.create_tag(name)
        self._save()
        self._populate_tags(select=created)

    def _rename_tag(self) -> None:
        if self.current is None:
            return
        old = self.current
        name = ask_tag_name(self.win, "Rename tag", "Tag name:", old)
        if not name or name == old:
            return
        if not self.cfg.rename_tag(old, name):
            messagebox.showinfo("Rename tag", f'There is already a tag called "{name}".',
                                parent=self.win)
            return
        color = self.cfg.app_colors.pop(config.tag_key(old), None)
        if color:
            self.cfg.app_colors[config.tag_key(name)] = color
        self._save()
        self._populate_tags(select=name)

    def _delete_tag(self) -> None:
        if self.current is None:
            return
        name = self.current
        if not messagebox.askyesno(
                "Delete tag",
                f'Delete the tag "{name}"?\n\nNothing is removed from your '
                "history — only the tag itself goes away.", parent=self.win):
            return
        self.cfg.delete_tag(name)
        self.cfg.app_colors.pop(config.tag_key(name), None)
        self._save()
        names = self.cfg.tag_names()
        self._populate_tags(select=names[0] if names else None)

    # -- save / close -----------------------------------------------------

    def _save(self) -> None:
        self.cfg.tags = config.clean_tags(self.cfg.tags)
        self.cfg.save()
        if self.on_change:
            self.on_change()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
