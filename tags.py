"""The Tags window: what each tag holds, and a way to take things out of it.

A tag is a named bucket of *items* — a whole app, or one file/site inside an
app. Tagging is non-destructive and applied at read time: the database keeps
its raw per-app/per-file rows, and the dashboard's Tags mode folds them into
tag totals only when displayed. So tags are retroactive and reversible, and an
item can sit in several tags at once (its time counts toward each of them).

Items are *added* by right-clicking a row in the dashboard, which is where you
can see what's worth tagging; this window is for reviewing a tag and removing
what doesn't belong. Every change here is saved straight away.

Tags can also be filed under a *group*, one group per tag: drag a tag by the
grip before its name onto a group to put it there, and back out among the
loose tags to take it out. The dashboard's Tags mode then lists the group,
with its total, and its tags inside it.

Saved tags go to config.json `tags`, the groups' names to `tag_groups`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import config
import dashboard as theme
import storage as storage_mod

DANGER = "#ef5350"   # the X button's hover colour, as in the timeline
ROW_H = 24           # one line of the tag list
GRIP_W = 16          # the drag grip's column, before a tag's name
GROUP_INDENT = 14    # how far a group's tags sit in from its name


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
        self.current: str | None = None        # selected tag name …
        self.current_group: str | None = None  # … or the selected group's
        self._rows: list[dict] = []            # the list as drawn, for hit tests
        self._drag: str | None = None          # tag being dragged by its grip
        self._drop: str | None = None          # group it's over ('' = none)
        self._ghost: tuple[float, float] | None = None
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
        self._populate_tags(select=None)
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
        s.configure("TSort.TButton", background=theme.BG, foreground=theme.MUTED,
                    padding=(6, 2), borderwidth=0, font=("Segoe UI", 8))
        s.map("TSort.TButton", background=[("active", "#34364a")])
        s.configure("TSortOn.TButton", background=theme.PANEL,
                    foreground=theme.FG, padding=(6, 2), borderwidth=0,
                    font=("Segoe UI Semibold", 8))
        s.map("TSortOn.TButton", background=[("active", theme.PANEL)])
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
                             "Add things by right-clicking them in the dashboard. "
                             "Drag a tag by its grip onto a group to file it "
                             "there, or back out to take it out.",
                  style="THint.TLabel", wraplength=660, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # Left: the groups, each with its tags, then the tags in no group.
        # Drawn by hand — a Listbox has no grip to drag a row by.
        left = ttk.Frame(root, style="T.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(0, weight=1)
        self.taglist = tk.Canvas(left, width=210, bg=theme.PANEL,
                                 highlightthickness=0, borderwidth=0)
        self.taglist.grid(row=0, column=0, sticky="nsew")
        self.taglist.bind("<Configure>", lambda e: self._draw_tags())
        self.taglist.bind("<Button-1>", self._press)
        self.taglist.bind("<B1-Motion>", self._drag_motion)
        self.taglist.bind("<ButtonRelease-1>", self._release)
        self.taglist.bind("<Double-Button-1>", lambda e: self._rename())
        self.taglist.bind("<Motion>", self._hover)
        self.taglist.bind("<MouseWheel>", lambda e: self.taglist.yview_scroll(
            -2 if e.delta > 0 else 2, "units"))
        self.taglist.bind("<Button-4>", lambda e: self.taglist.yview_scroll(-2, "units"))
        self.taglist.bind("<Button-5>", lambda e: self.taglist.yview_scroll(2, "units"))

        # Sort first, then what you can do to the selected tag.
        sorts = ttk.Frame(left, style="T.TFrame")
        sorts.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(sorts, text="Sort", style="THint.TLabel").pack(side="left",
                                                                 padx=(2, 6))
        self.sort_buttons = {}
        for sort, text in ((config.BY_RECENT, "Recent"), (config.BY_NAME, "A–Z")):
            b = ttk.Button(sorts, text=text, style="TSort.TButton",
                           width=len(text) + 1,
                           command=lambda s=sort: self._set_sort(s))
            b.pack(side="left", padx=(0, 4))
            self.sort_buttons[sort] = b
        self._style_sorts()

        adds = ttk.Frame(left, style="T.TFrame")
        adds.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(adds, text="+ New tag", style="TSmall.TButton",
                   command=self._new_tag).pack(side="left")
        ttk.Button(adds, text="+ New group", style="TSmall.TButton",
                   command=self._new_group).pack(side="left", padx=(6, 0))

        # Rename and Delete act on whichever is selected, tag or group.
        buttons = ttk.Frame(left, style="T.TFrame")
        buttons.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(buttons, text="Rename", style="TSmall.TButton",
                   command=self._rename).pack(side="left")
        ttk.Button(buttons, text="Delete", style="TSmall.TButton",
                   command=self._delete).pack(side="left", padx=(6, 0))

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

    def _style_sorts(self) -> None:
        for sort, button in self.sort_buttons.items():
            button.configure(style="TSortOn.TButton" if sort == self.cfg.tag_sort
                             else "TSort.TButton")

    def _set_sort(self, sort: str) -> None:
        """Reorder the list — and remember it, since it's a habit, not a mood."""
        if sort == self.cfg.tag_sort:
            return
        self.cfg.tag_sort = sort
        self._style_sorts()
        self._save()
        self._populate_tags(select=self.current, group=self.current_group)

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

    def _layout(self) -> list[dict]:
        """The list's rows, top to bottom: each group, then the loose tags.

        Every row says which group it belongs to ('' for none), which is also
        where a tag dropped on it ends up.
        """
        cfg = self.cfg

        def tags_of(group: str) -> list[dict]:
            return [{"kind": "tag", "name": name, "group": group,
                     "label": self._tag_label(name)}
                    for name in cfg.group_tags(group)]

        rows: list[dict] = []
        for group in sorted(cfg.tag_groups, key=str.casefold):
            inside = tags_of(group)
            rows.append({"kind": "group", "name": group, "group": group,
                         "label": f"{group}  ·  {len(inside)}"})
            rows += inside or [{"kind": "hint", "name": "", "group": group,
                                "label": "Drag a tag here"}]
        rows += tags_of("")
        if self._drag is not None and cfg.tag_group(self._drag):
            # Somewhere to aim for even when every tag is in a group.
            rows.append({"kind": "hint", "name": "", "group": "",
                         "label": "Drop here to take it out of the group"})
        return rows

    def _is_selected(self, row: dict) -> bool:
        if row["kind"] == "tag":
            return row["name"] == self.current
        return row["kind"] == "group" and row["name"] == self.current_group

    @staticmethod
    def _name_x(row: dict) -> int:
        """Where a row's text starts; a tag's grip takes up the space before."""
        if row["kind"] == "group":
            return 8
        indent = GROUP_INDENT if row["group"] else 0
        return 8 + indent + (GRIP_W if row["kind"] == "tag" else 0)

    def _draw_tags(self) -> None:
        c = self.taglist
        c.delete("all")
        w = max(c.winfo_width(), c.winfo_reqwidth())
        rows = self._layout()
        y = 0
        for row in rows:
            row["y0"], row["y1"] = y, y + ROW_H
            mid = y + ROW_H / 2
            selected = self._is_selected(row)
            if selected:
                c.create_rectangle(0, y, w, y + ROW_H, fill=theme.ACCENT, outline="")
            fg = "#12131c" if selected else theme.FG
            x = self._name_x(row)
            if row["kind"] == "group":
                c.create_text(x, mid, text=row["label"], anchor="w", fill=fg,
                              font=("Segoe UI Semibold", 10))
            elif row["kind"] == "hint":
                c.create_text(x, mid, text=row["label"], anchor="w",
                              fill=theme.MUTED, font=("Segoe UI", 8))
            else:
                lifted = row["name"] == self._drag
                self._draw_grip(x - GRIP_W, mid, fg if selected else theme.MUTED)
                c.create_text(x, mid, text=row["label"], anchor="w",
                              fill=theme.MUTED if lifted and not selected else fg,
                              font=("Segoe UI", 10))
            y += ROW_H
        self._rows = rows

        if self._drag is not None and self._drop is not None:
            # Outline everything a drop here would join: the group and its
            # tags, or the loose tags.
            block = [r for r in rows if r["group"] == self._drop]
            if block:
                c.create_rectangle(1, block[0]["y0"] + 1, w - 2, block[-1]["y1"] - 1,
                                   outline=theme.ACCENT)
            if self._ghost:
                label = c.create_text(self._ghost[0] + 12, self._ghost[1] + 16,
                                      text=self._drag, anchor="w", fill=theme.FG,
                                      font=("Segoe UI", 10))
                x0, y0, x1, y1 = c.bbox(label)
                c.tag_lower(c.create_rectangle(
                    x0 - 6, y0 - 3, x1 + 6, y1 + 3, fill="#34364a",
                    outline=theme.ACCENT), label)
        c.configure(scrollregion=(0, 0, w, max(y, c.winfo_height())))

    def _draw_grip(self, x: float, mid: float, color: str) -> None:
        """Six dots, two across — drawn, so it doesn't hang on a font's glyph."""
        for dx in (2, 7):
            for dy in (-5, 0, 5):
                self.taglist.create_rectangle(x + dx, mid + dy - 1, x + dx + 2,
                                              mid + dy + 1, fill=color, outline="")

    def _row_at(self, event) -> dict | None:
        y = self.taglist.canvasy(event.y)
        for row in self._rows:
            if row["y0"] <= y < row["y1"]:
                return row
        return None

    def _on_grip(self, row: dict | None, event) -> bool:
        return bool(row and row["kind"] == "tag"
                    and self.taglist.canvasx(event.x) < self._name_x(row))

    def _hover(self, event) -> None:
        cursor = "fleur" if self._on_grip(self._row_at(event), event) else ""
        if self._drag is None and self.taglist.cget("cursor") != cursor:
            self.taglist.configure(cursor=cursor)

    def _press(self, event) -> None:
        row = self._row_at(event)
        if not row or row["kind"] == "hint":
            return
        if self._on_grip(row, event):
            self._drag = row["name"]
        if row["kind"] == "group":
            self._load(None, row["name"])
        else:
            self._load(row["name"])

    def _drag_motion(self, event) -> None:
        if self._drag is None:
            return
        c = self.taglist
        if event.y < 0 or event.y > c.winfo_height():   # past an edge: scroll
            c.yview_scroll(-1 if event.y < 0 else 1, "units")
        row = self._row_at(event)
        # Below the last row is the loose tags' end of the list.
        self._drop = row["group"] if row else ""
        self._ghost = (c.canvasx(event.x), c.canvasy(event.y))
        self._draw_tags()

    def _release(self, _event=None) -> None:
        name, target = self._drag, self._drop
        self._drag = self._drop = self._ghost = None
        if name is None:
            return
        if target is not None and target != self.cfg.tag_group(name):
            self.cfg.set_tag_group(name, target)
            self._save()
        self._populate_tags(select=name)

    def _populate_tags(self, select: str | None, group: str | None = None) -> None:
        """Redraw the list with `group` selected, else `select`, else the first tag."""
        names = self.cfg.tag_order()
        if group is not None and group in self.cfg.tag_groups:
            self._load(None, group)
        elif select in names:
            self._load(select)
        else:
            self._load(names[0] if names else None)
        self._see_selection()

    def _see_selection(self) -> None:
        c = self.taglist
        height = c.winfo_height()
        row = next((r for r in self._rows if self._is_selected(r)), None)
        if row is None or height <= 1:
            return
        top = c.canvasy(0)
        if row["y0"] < top or row["y1"] > top + height:
            total = max(self._rows[-1]["y1"], height)
            c.yview_moveto(max(0, row["y1"] - height) / total)

    def _load(self, name: str | None, group: str | None = None) -> None:
        self.current = name
        self.current_group = group
        if group is not None:
            self.items_title.configure(text=f"In the group “{group}”")
        elif name is None:
            self.items_title.configure(
                text="No tags yet" if not self.cfg.tags else "Select a tag")
        else:
            self.items_title.configure(text=f"In “{name}”")
        self._refresh_items()
        self._draw_tags()

    # -- items ------------------------------------------------------------

    def _item_label(self, app: str, file: str | None) -> str:
        app_name = self._app_names.get(app) or config.friendly_name(app)
        return storage_mod.item_label(app_name, file)

    def _refresh_items(self) -> None:
        for child in list(self.items_inner.winfo_children()):
            child.destroy()
        if self.current_group is not None:
            tags = self.cfg.group_tags(self.current_group)
            if not tags:
                self._items_hint("No tags in this group yet. Drag one onto it "
                                 "by the grip before its name.")
            for name in tags:
                self._item_row(name, "tag",
                               lambda n=name: self._ungroup(n))
            return
        if self.current is None:
            return
        items = self.cfg.tag_items(self.current)
        if not items:
            self._items_hint("Nothing here yet. Right-click an app, file or site "
                             "in the dashboard and pick this tag.")
            return
        for app, file in items:
            self._item_row(self._item_label(app, file),
                           "whole app" if file is None else "",
                           lambda a=app, f=file: self._remove(a, f))

    def _items_hint(self, text: str) -> None:
        ttk.Label(self.items_inner, text=text, style="THint.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))

    def _item_row(self, text: str, note: str, remove) -> None:
        """One line of the right-hand list, with an ✕ that calls `remove`."""
        row = ttk.Frame(self.items_inner, style="TRow.TFrame", padding=(10, 5))
        row.pack(fill="x", pady=(0, 3))
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text=text, style="TRow.TLabel",
                  anchor="w").grid(row=0, column=0, sticky="ew")
        ttk.Label(row, text=note,
                  style="TRowMuted.TLabel").grid(row=0, column=1, padx=(8, 8))
        ttk.Button(row, text="✕", width=2, style="TX.TButton",
                   command=remove).grid(row=0, column=2)
        row.bind("<MouseWheel>", self._on_wheel)

    def _remove(self, app: str, file: str | None) -> None:
        if self.current is None:
            return
        self.cfg.set_item_tag(self.current, app, file, False)
        self._save()
        self._populate_tags(select=self.current)

    def _ungroup(self, name: str) -> None:
        """Take a tag out of the group on show; the tag itself is untouched."""
        self.cfg.set_tag_group(name, None)
        self._save()
        self._populate_tags(select=None, group=self.current_group)

    # -- tag actions ------------------------------------------------------

    def _new_tag(self) -> None:
        name = ask_tag_name(self.win, "New tag", "Name for the new tag:")
        if not name:
            return
        created = self.cfg.create_tag(name)
        self._save()
        self._populate_tags(select=created)

    def _rename(self) -> None:
        if self.current_group is not None:
            self._rename_group()
        else:
            self._rename_tag()

    def _delete(self) -> None:
        if self.current_group is not None:
            self._delete_group()
        else:
            self._delete_tag()

    def _move_color(self, old_key: str, new_key: str | None) -> None:
        """A hand-picked colour is keyed by name, so it follows a rename."""
        color = self.cfg.app_colors.pop(old_key, None)
        if color and new_key:
            self.cfg.app_colors[new_key] = color

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
        self._move_color(config.tag_key(old), config.tag_key(name))
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
        self._move_color(config.tag_key(name), None)
        self._save()
        self._populate_tags(select=None)

    # -- group actions ----------------------------------------------------

    def _new_group(self) -> None:
        name = ask_tag_name(self.win, "New group", "Name for the new group:")
        if not name:
            return
        created = self.cfg.create_group(name)
        self._save()
        self._populate_tags(select=None, group=created)

    def _rename_group(self) -> None:
        old = self.current_group
        if old is None:
            return
        name = ask_tag_name(self.win, "Rename group", "Group name:", old)
        if not name or name == old:
            return
        if not self.cfg.rename_group(old, name):
            messagebox.showinfo("Rename group",
                                f'There is already a group called "{name}".',
                                parent=self.win)
            return
        self._move_color(config.group_key(old), config.group_key(name))
        self._save()
        self._populate_tags(select=None, group=name)

    def _delete_group(self) -> None:
        name = self.current_group
        if name is None:
            return
        if not messagebox.askyesno(
                "Delete group",
                f'Delete the group "{name}"?\n\nIts tags are kept — they just '
                "stop being grouped.", parent=self.win):
            return
        self.cfg.delete_group(name)
        self._move_color(config.group_key(name), None)
        self._save()
        self._populate_tags(select=None)

    # -- save / close -----------------------------------------------------

    def _save(self) -> None:
        self.cfg.tags = config.clean_tags(self.cfg.tags)
        self.cfg.tag_groups = config.clean_groups(self.cfg.tag_groups,
                                                  self.cfg.tags)
        self.cfg.save()
        if self.on_change:
            self.on_change()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
