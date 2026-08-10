"""The tkinter dashboard window.

Shows focus time for a selected range (Today / This Week / This Month), broken
down by application, with a per-file breakdown for the selected app, a bar chart,
and a daily-trend chart for multi-day ranges. Charts are hand-drawn on a Canvas
to keep dependencies minimal.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import tkinter as tk
from tkinter import ttk

import config
from storage import Storage

# --- theme ---------------------------------------------------------------
BG = "#1e1f2b"
PANEL = "#272838"
FG = "#e8e8f0"
MUTED = "#9a9ab0"
ACCENT = "#7c9cff"
BAR_COLORS = [
    "#7c9cff", "#7ce0c3", "#ffcb6b", "#ff8b94", "#c792ea",
    "#82d8ff", "#f78c6c", "#a6e22e", "#ff9de2", "#8fd6a9",
]
ROW_HOVER = "#383a58"   # readable against PANEL without shouting
MARKER_W = 16    # expander column, so names line up whether or not one is shown
FILE_INDENT = 18

# Offered when picking a bar colour by hand — a wider spread than BAR_COLORS so
# there's a sensible blue/red/orange for apps with a known brand colour.
PICKER_COLORS = [
    "#7c9cff", "#4d7cff", "#82d8ff", "#7ce0c3",
    "#8fd6a9", "#a6e22e", "#ffcb6b", "#f7a05c",
    "#f78c6c", "#ff7043", "#ff8b94", "#ef5350",
    "#ff9de2", "#c792ea", "#9a8cff", "#9a9ab0",
]


def color_for(key: str) -> str:
    """A stable colour for an app or file.

    Derived from the name, not its position in the list, so an app keeps the
    same colour as its ranking moves around and between days. `hash()` is
    randomised per process, hence md5.
    """
    digest = hashlib.md5(key.encode("utf-8", "replace")).digest()
    return BAR_COLORS[digest[0] % len(BAR_COLORS)]


def _blend(color: str, other: str, amount: float) -> str:
    """Mix `color` toward `other` (0.0 = unchanged, 1.0 = fully `other`)."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    mixed = [round(x + (y - x) * amount) for x, y in zip(a, b)]
    return "#%02x%02x%02x" % tuple(mixed)


class Tooltip:
    """A small hover label — icon-only buttons need to say what they do."""

    def __init__(self, widget, text: str, delay: int = 450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self._tip or not self.widget.winfo_viewable():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        tk.Label(self._tip, text=self.text, bg="#f6f6fa", fg="#1e1f2b",
                 font=("Segoe UI", 8), padx=6, pady=2).pack()
        self._tip.update_idletasks()
        self._tip.wm_geometry(f"+{x - self._tip.winfo_width() // 2}+{y}")

    def _hide(self, _event=None):
        self._cancel()
        if self._tip:
            self._tip.destroy()
            self._tip = None


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


class RangeState:
    """Tracks the selected date range and supports prev/next navigation."""

    def __init__(self):
        self.mode = "day"  # 'day' | 'week' | 'month' | 'year' | 'custom'
        self.anchor = dt.date.today()
        self.custom_start: dt.date | None = None
        self.custom_end: dt.date | None = None

    def bounds(self) -> tuple[str, str]:
        if self.mode == "day":
            start = end = self.anchor
        elif self.mode == "week":
            start = self.anchor - dt.timedelta(days=self.anchor.weekday())
            end = start + dt.timedelta(days=6)
        elif self.mode == "year":
            start = self.anchor.replace(month=1, day=1)
            end = self.anchor.replace(month=12, day=31)
        elif self.mode == "custom":
            start = self.custom_start or dt.date.today()
            end = self.custom_end or start
        else:  # month
            start = self.anchor.replace(day=1)
            last = calendar.monthrange(self.anchor.year, self.anchor.month)[1]
            end = self.anchor.replace(day=last)
        return start.isoformat(), end.isoformat()

    def days(self) -> list[dt.date]:
        s, e = self.bounds()
        start = dt.date.fromisoformat(s)
        end = dt.date.fromisoformat(e)
        out = []
        d = start
        while d <= end:
            out.append(d)
            d += dt.timedelta(days=1)
        return out

    @property
    def is_multiday(self) -> bool:
        if self.mode == "custom":
            return self.custom_start != self.custom_end
        return self.mode in ("week", "month", "year")

    @staticmethod
    def _day_label(d: dt.date) -> str:
        """'Aug 10', or 'Aug 10, 2025' outside the current year.

        The year is redundant most of the time, and dropping it keeps the
        header narrow enough for the navigation arrows to survive a small
        window.
        """
        if d.year == dt.date.today().year:
            return d.strftime("%b %d")
        return d.strftime("%b %d, %Y")

    def label(self) -> str:
        today = dt.date.today()
        if self.mode == "day":
            if self.anchor == today:
                return "Today"
            if self.anchor == today - dt.timedelta(days=1):
                return "Yesterday"
            if self.anchor.year == today.year:
                return self.anchor.strftime("%a, %b %d")
            return self.anchor.strftime("%a, %b %d, %Y")
        if self.mode == "year":
            return self.anchor.strftime("%Y")
        if self.mode in ("week", "custom"):
            s, e = self.bounds()
            sd = dt.date.fromisoformat(s)
            ed = dt.date.fromisoformat(e)
            if sd == ed:
                return self._day_label(sd)
            return f"{self._day_label(sd)} – {self._day_label(ed)}"
        return self.anchor.strftime("%B %Y")

    def shift(self, direction: int) -> None:
        if self.mode == "day":
            self.anchor += dt.timedelta(days=direction)
        elif self.mode == "week":
            self.anchor += dt.timedelta(weeks=direction)
        elif self.mode == "year":
            year = self.anchor.year + direction
            day = min(self.anchor.day, calendar.monthrange(year, self.anchor.month)[1])
            self.anchor = self.anchor.replace(year=year, day=day)
        elif self.mode == "custom":
            if self.custom_start and self.custom_end:
                span = (self.custom_end - self.custom_start) + dt.timedelta(days=1)
                self.custom_start += span * direction
                self.custom_end += span * direction
        else:
            month = self.anchor.month - 1 + direction
            year = self.anchor.year + month // 12
            month = month % 12 + 1
            day = min(self.anchor.day, calendar.monthrange(year, month)[1])
            self.anchor = dt.date(year, month, day)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.anchor = dt.date.today()


class Dashboard:
    def __init__(self, root: tk.Tk, storage: Storage, tracker=None,
                 open_settings=None, open_merges=None):
        self.root = root
        self.storage = storage
        self.tracker = tracker
        self.open_settings_cb = open_settings
        self.open_merges_cb = open_merges
        self.range = RangeState()
        self.expanded: set[str] = set()   # app keys whose files are shown
        self._refresh_job = None
        self._visible = False
        self._trend_height = 190  # default trend pane height (drag-adjustable)
        self._build()

    def _open_settings(self) -> None:
        if self.open_settings_cb:
            self.open_settings_cb()

    def _open_merges(self) -> None:
        if self.open_merges_cb:
            self.open_merges_cb()

    # -- UI construction --------------------------------------------------

    def _build(self) -> None:
        self.root.title("Active Time Tracker")
        self.root.configure(bg=BG)
        self.root.geometry("980x640")
        self.root.minsize(820, 520)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Note.TLabel", background=BG, foreground=MUTED,
                        font=("Segoe UI", 8))
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Total.TLabel", background=BG, foreground=ACCENT,
                        font=("Segoe UI Semibold", 22))
        style.configure("H.TLabel", background=BG, foreground=FG,
                        font=("Segoe UI Semibold", 11))
        style.configure("TButton", background=PANEL, foreground=FG, borderwidth=0,
                        focuscolor=PANEL, padding=(10, 4))
        style.map("TButton", background=[("active", "#34364a")])
        style.configure("Seg.TButton", padding=(14, 5))
        style.configure("Icon.TButton", padding=(4, 4), font=("Segoe UI", 11),
                        anchor="center")
        style.configure("Active.Seg.TButton", background=ACCENT, foreground="#12131c")
        style.map("Active.Seg.TButton", background=[("active", ACCENT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=FG, borderwidth=0, rowheight=26)
        style.configure("Treeview.Heading", background="#33344a", foreground=MUTED,
                        borderwidth=0, font=("Segoe UI", 9))
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#12131c")])

        # --- header -----------------------------------------------------
        # Laid out with grid, not pack: the range arrows are the only way to
        # move between days, so they must never be the thing that gets pushed
        # off when the window narrows. Only the preset column absorbs the
        # squeeze; everything else keeps its natural width.
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(14, 6))
        header.columnconfigure(0, weight=1)

        seg = ttk.Frame(header)
        seg.grid(row=0, column=0, sticky="w")
        self.seg_buttons = {}
        for mode, text in (("day", "Today"), ("week", "Week"),
                           ("month", "Month"), ("year", "Year"),
                           ("custom", "Custom")):
            cmd = self._open_custom_range if mode == "custom" \
                else (lambda m=mode: self._set_mode(m))
            # ttk gives buttons a generous default minimum width, which the
            # short labels don't need — size them to their text instead.
            b = ttk.Button(seg, text=text, style="Seg.TButton", command=cmd,
                           width=len(text) + 1)
            b.pack(side="left", padx=(0, 6))
            self.seg_buttons[mode] = b

        nav = ttk.Frame(header)
        nav.grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Button(nav, text="◀", width=3, command=lambda: self._nav(-1)).pack(side="left")
        # Fixed width so the arrows don't shuffle as the label text changes;
        # 16 fits the longest form ("Aug 01 – Aug 10").
        self.range_label = ttk.Label(nav, text="", style="H.TLabel", width=16,
                                     anchor="center")
        self.range_label.pack(side="left", padx=6)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._nav(1)).pack(side="left")

        # Icon-only: both windows are also on the tray menu, so the labels were
        # costing header width for little gain.
        actions = ttk.Frame(header)
        actions.grid(row=0, column=2, sticky="e", padx=(10, 0))
        # Plain geometric glyphs, not emoji: emoji fall back to a boxed
        # placeholder in the UI font on Windows.
        groups_btn = ttk.Button(actions, text="⧉", width=3, style="Icon.TButton",
                                command=self._open_merges)
        groups_btn.pack(side="left", padx=(0, 4))
        settings_btn = ttk.Button(actions, text="⚙", width=3, style="Icon.TButton",
                                  command=self._open_settings)
        settings_btn.pack(side="left")
        Tooltip(groups_btn, "App groups")
        Tooltip(settings_btn, "Settings")

        totalrow = ttk.Frame(self.root)
        totalrow.pack(fill="x", padx=16, pady=(0, 8))
        self.total_label = ttk.Label(totalrow, text="0s", style="Total.TLabel")
        self.total_label.pack(side="left")
        self.status_label = ttk.Label(totalrow, text="", style="Muted.TLabel")
        self.status_label.pack(side="right", pady=(10, 0))

        # --- body + trend live in a vertical paned window so the trend
        #     height is drag-adjustable via the divider ---------------------
        style.configure("TPanedwindow", background=BG)
        style.configure("Sash", sashthickness=7, gripcount=12)
        self.main_paned = ttk.PanedWindow(self.root, orient="vertical")
        self.main_paned.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.main_paned.bind("<ButtonRelease-1>", lambda e: self._remember_trend_height())

        # body: one full-width chart — every application is a clickable row that
        # expands to show its files.
        body = ttk.Frame(self.main_paned)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        self.main_paned.add(body, weight=4)

        self.chart_title = ttk.Label(body, text="APPLICATIONS", style="Muted.TLabel")
        self.chart_title.grid(row=0, column=0, sticky="w", pady=(0, 4))
        # Only meaningful once a row is expanded: files/sites come from window
        # titles, so same-named entries can share a row.
        self.chart_note = ttk.Label(body, text="", style="Note.TLabel",
                                    wraplength=620, justify="left")

        chart_wrap = ttk.Frame(body)
        chart_wrap.grid(row=2, column=0, sticky="nsew")
        chart_wrap.rowconfigure(0, weight=1)
        chart_wrap.columnconfigure(0, weight=1)
        self.chart = tk.Canvas(chart_wrap, bg=PANEL, highlightthickness=0, height=200)
        self.chart.grid(row=0, column=0, sticky="nsew")
        self.chart_scroll = ttk.Scrollbar(chart_wrap, orient="vertical",
                                          command=self.chart.yview)
        self.chart.configure(yscrollcommand=self._on_chart_scrolled)
        self.chart.bind("<Configure>", lambda e: self._draw_chart())
        self.chart.bind("<Button-1>", self._on_chart_click)
        self.chart.bind("<Button-3>", self._on_chart_right_click)
        self.chart.bind("<Motion>", self._on_chart_motion)
        self.chart.bind("<Leave>", lambda e: self._set_hover(None))
        # Mouse wheel: Windows/macOS send <MouseWheel>, X11 sends Button-4/5.
        self.chart.bind("<MouseWheel>",
                        lambda e: self._scroll_chart(-1 if e.delta > 0 else 1))
        self.chart.bind("<Button-4>", lambda e: self._scroll_chart(-1))
        self.chart.bind("<Button-5>", lambda e: self._scroll_chart(1))

        # --- trend (multi-day only; added to the paned window in refresh) ---
        self.trend_frame = ttk.Frame(self.main_paned)
        self.trend_title = ttk.Label(self.trend_frame, text="DAILY TREND", style="Muted.TLabel")
        self.trend_title.pack(anchor="w", pady=(0, 4))
        # A small requested height lets the sash shrink it; the default size is
        # set via the sash position in _apply_trend_height().
        self.trend = tk.Canvas(self.trend_frame, bg=PANEL, highlightthickness=0, height=60)
        self.trend.pack(fill="both", expand=True)
        self.trend.bind("<Configure>", lambda e: self._draw_trend())

        self._data_apps: list[dict] = []
        self._data_files: dict[str, list[dict]] = {}   # app key -> its files
        self._data_trend: dict[str, float] = {}
        self._grand = 0.0
        self._rows: list[dict] = []                    # drawn rows, for hit tests
        self._hover: str | None = None

    # -- events -----------------------------------------------------------

    def _set_mode(self, mode: str) -> None:
        self.range.set_mode(mode)
        self.refresh()   # expanded rows persist; refresh drops any that vanish

    def _nav(self, direction: int) -> None:
        self.range.shift(direction)
        self.refresh()

    def _open_custom_range(self) -> None:
        if self.range.custom_start and self.range.custom_end:
            s0, e0 = self.range.custom_start, self.range.custom_end
        else:
            e0 = dt.date.today()
            s0 = e0 - dt.timedelta(days=6)
        result = self._ask_custom_range(s0, e0)
        if result is None:
            return  # cancelled — leave the current view unchanged
        start, end = result
        self.range.mode = "custom"
        self.range.custom_start = start
        self.range.custom_end = end
        self.refresh()

    def _ask_custom_range(self, s0: dt.date, e0: dt.date):
        """Modal date-range picker. Returns (start, end) dates or None."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Custom range")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        result = {"val": None}

        wrap = tk.Frame(dlg, bg=BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=16)
        tk.Label(wrap, text="Show statistics for a date range",
                 bg=BG, fg=FG, font=("Segoe UI Semibold", 12)).grid(
            row=0, column=0, columnspan=2, sticky="w")

        from_var = tk.StringVar(value=s0.isoformat())
        to_var = tk.StringVar(value=e0.isoformat())

        def _entry(row, label, var):
            tk.Label(wrap, text=label, bg=BG, fg=FG, font=("Segoe UI", 10)).grid(
                row=row, column=0, sticky="w", pady=(12 if row == 1 else 6, 0))
            e = tk.Entry(wrap, textvariable=var, width=14, bg=PANEL, fg=FG,
                         insertbackground=FG, borderwidth=0, highlightthickness=1,
                         highlightbackground="#3a3c52", font=("Consolas", 11),
                         justify="center")
            e.grid(row=row, column=1, sticky="e", pady=(12 if row == 1 else 6, 0))
            return e

        first = _entry(1, "From", from_var)
        _entry(2, "To", to_var)
        tk.Label(wrap, text="Format: YYYY-MM-DD", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).grid(row=3, column=0, columnspan=2,
                                            sticky="w", pady=(4, 0))

        presets = tk.Frame(wrap, bg=BG)
        presets.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

        def set_last(days):
            today = dt.date.today()
            from_var.set((today - dt.timedelta(days=days - 1)).isoformat())
            to_var.set(today.isoformat())

        for text, days in (("Last 7 days", 7), ("Last 30 days", 30), ("Last 90 days", 90)):
            b = tk.Label(presets, text=text, bg=PANEL, fg=FG, font=("Segoe UI", 8),
                         padx=8, pady=3, cursor="hand2")
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, d=days: set_last(d))

        err = tk.Label(wrap, text="", bg=BG, fg="#ff8b94", font=("Segoe UI", 8))
        err.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def ok():
            try:
                s = dt.date.fromisoformat(from_var.get().strip())
                e = dt.date.fromisoformat(to_var.get().strip())
            except ValueError:
                err.configure(text="Please enter valid dates as YYYY-MM-DD.")
                return
            if s > e:
                s, e = e, s
            result["val"] = (s, e)
            dlg.destroy()

        btns = tk.Frame(wrap, bg=BG)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        tk.Button(btns, text="Cancel", command=dlg.destroy, bg=PANEL, fg=FG,
                  relief="flat", padx=14, pady=4, cursor="hand2").pack(side="right", padx=(0, 8))
        tk.Button(btns, text="Show", command=ok, bg=ACCENT, fg="#12131c",
                  relief="flat", padx=16, pady=4, cursor="hand2",
                  font=("Segoe UI Semibold", 10)).pack(side="right")

        dlg.bind("<Return>", lambda e: ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        if rw <= 1:
            rx = ry = 0
            rw, rh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        x = rx + (rw - dlg.winfo_width()) // 2
        y = ry + (rh - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

        first.focus_set()
        first.select_range(0, "end")
        dlg.grab_set()
        dlg.wait_window()
        return result["val"]

    # -- chart interaction ------------------------------------------------

    def _row_at(self, event) -> dict | None:
        """The drawn row under the pointer (the canvas scrolls, so convert)."""
        y = self.chart.canvasy(event.y)
        for row in self._rows:
            if row["y0"] <= y < row["y1"]:
                return row
        return None

    def _on_chart_click(self, event):
        row = self._row_at(event)
        if not row or row["kind"] != "app":
            return None
        if not row["has_files"]:
            return None                     # nothing to expand
        key = row["key"]
        if key in self.expanded:
            self.expanded.discard(key)
        else:
            self.expanded.add(key)
        self.refresh()
        return "break"

    def _on_chart_motion(self, event) -> None:
        # Highlight whatever is under the pointer — a wide gap between a long
        # name and its time is hard to track by eye otherwise. Only expandable
        # rows get the hand cursor, since only those do something when clicked.
        row = self._row_at(event)
        self._set_hover(row["key"] if row else None,
                        clickable=bool(row and row["kind"] == "app"
                                       and row["has_files"]))

    def _set_hover(self, key, clickable: bool = False) -> None:
        if key != self._hover:
            self._hover = key
            self._draw_chart()
        cursor = "hand2" if clickable else ""
        if self.chart.cget("cursor") != cursor:
            self.chart.configure(cursor=cursor)

    def _scroll_chart(self, direction: int) -> None:
        self.chart.yview_scroll(direction * 2, "units")

    def _on_chart_scrolled(self, first: str, last: str) -> None:
        """Show the scrollbar only when the rows don't all fit."""
        self.chart_scroll.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self.chart_scroll.winfo_ismapped():
            self.chart_scroll.grid(row=0, column=1, sticky="ns")
        elif not needed and self.chart_scroll.winfo_ismapped():
            self.chart_scroll.grid_remove()

    # -- right-click context menu ----------------------------------------

    def _members_of(self, key: str) -> list[str]:
        return getattr(self, "_app_members", {}).get(key, [key])

    def _on_chart_right_click(self, event) -> None:
        cfg = self.tracker.cfg if self.tracker else None
        if cfg is None:
            return
        row = self._row_at(event)
        if not row:
            return
        # Right-clicking a file acts on the app it belongs to.
        key = row["key"] if row["kind"] == "app" else row["app"]
        name = next((r["label"] for r in self._rows
                     if r["kind"] == "app" and r["key"] == key), key)

        members = [m for m in self._members_of(key) if not m.startswith(config.MERGE_PREFIX)]
        tracks = bool(members) and all(cfg.tracks_files(m) for m in members)

        menu = tk.Menu(self.root, tearoff=0, bg="#f6f6fa", fg="#1e1f2b",
                       activebackground=ACCENT, activeforeground="#12131c",
                       borderwidth=0, relief="flat")
        self._ctx_track_var = tk.BooleanVar(value=tracks)
        menu.add_checkbutton(label="Track files for this app",
                             variable=self._ctx_track_var,
                             command=lambda: self._ctx_toggle_track(members))
        menu.add_command(label="Bar colour…",
                         command=lambda: self._open_color_picker(key, name,
                                                                 event.x_root,
                                                                 event.y_root))
        menu.add_separator()
        menu.add_command(label=f'Add "{name}" to ignore list',
                         command=lambda: self._ctx_ignore(members))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # -- bar colour -------------------------------------------------------

    def _set_app_color(self, key: str, color: str | None) -> None:
        """Store (or clear, when `color` is None) a hand-picked bar colour."""
        cfg = self.tracker.cfg
        if color:
            cfg.app_colors[key] = color
        else:
            cfg.app_colors.pop(key, None)
        cfg.save()
        self.refresh()

    def _open_color_picker(self, key: str, name: str, x: int, y: int) -> None:
        """A small swatch grid — lighter than a full colour dialog for the
        common case, with the system picker behind 'Custom…' for exact shades."""
        current = self._color_for(key)
        win = tk.Toplevel(self.root)
        win.title(f"Bar colour — {name}")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)

        wrap = tk.Frame(win, bg=BG)
        wrap.pack(padx=14, pady=12)
        tk.Label(wrap, text=name, bg=BG, fg=FG,
                 font=("Segoe UI Semibold", 10)).grid(
            row=0, column=0, columnspan=8, sticky="w", pady=(0, 8))

        def choose(color):
            win.destroy()
            self._set_app_color(key, color)

        for i, color in enumerate(PICKER_COLORS):
            selected = color.lower() == current.lower()
            cell = tk.Frame(wrap, bg=ACCENT if selected else BG,
                            padx=2, pady=2)
            cell.grid(row=1 + i // 8, column=i % 8, padx=3, pady=3)
            sw = tk.Frame(cell, bg=color, width=26, height=22, cursor="hand2")
            sw.pack()
            sw.bind("<Button-1>", lambda e, c=color: choose(c))

        def custom():
            from tkinter import colorchooser
            picked = colorchooser.askcolor(color=current, parent=win,
                                           title=f"Bar colour — {name}")[1]
            if picked:
                choose(picked)

        btns = tk.Frame(wrap, bg=BG)
        btns.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        tk.Button(btns, text="Custom…", command=custom, bg=PANEL, fg=FG,
                  relief="flat", padx=10, pady=3, cursor="hand2").pack(side="left")
        tk.Button(btns, text="Reset", command=lambda: choose(None), bg=PANEL,
                  fg=FG, relief="flat", padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=(6, 0))
        tk.Button(btns, text="Cancel", command=win.destroy, bg=PANEL, fg=FG,
                  relief="flat", padx=10, pady=3,
                  cursor="hand2").pack(side="right")

        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        win.geometry(f"+{max(0, x - 40)}+{max(0, y - 20)}")
        win.grab_set()
        win.focus_force()

    def _ctx_toggle_track(self, members: list[str]) -> None:
        cfg = self.tracker.cfg
        track = self._ctx_track_var.get()
        for m in members:
            cfg.set_track_files(m, track)
        cfg.save()
        self.refresh()

    def _ctx_ignore(self, members: list[str]) -> None:
        cfg = self.tracker.cfg
        for m in members:
            if m and m not in cfg.ignore_apps:
                cfg.ignore_apps.append(m)
        cfg.save()
        self.refresh()

    # -- data + rendering -------------------------------------------------

    def refresh(self) -> None:
        start, end = self.range.bounds()
        cfg = self.tracker.cfg if self.tracker else None
        merge_map = cfg.merge_map() if cfg else None
        group_members = cfg.group_members() if cfg else {}
        ignore = set(cfg.ignore_apps) if cfg else set()
        self._data_apps = self.storage.totals_by_app(start, end, merge_map, ignore)
        # display_key -> member exes (for the per-file breakdown of a group)
        self._app_members = {
            a["app"]: group_members.get(a["app"], [a["app"]]) for a in self._data_apps
        }
        self._grand = sum(a["seconds"] for a in self._data_apps)
        self._data_trend = self.storage.totals_by_day(start, end) if self.range.is_multiday else {}

        # segment button styling
        for mode, b in self.seg_buttons.items():
            b.configure(style="Active.Seg.TButton" if mode == self.range.mode else "Seg.TButton")
        self.range_label.configure(text=self.range.label())
        self.total_label.configure(text=fmt_duration(self._grand))

        # Forget expansions for apps that no longer appear in this range.
        present = {a["app"] for a in self._data_apps}
        self.expanded &= present
        self._load_files()
        self._update_note()
        self._draw_chart()

        # trend visibility (as a resizable bottom pane)
        panes = self.main_paned.panes()
        if self.range.is_multiday:
            self.trend_title.configure(
                text="MONTHLY TREND" if self._trend_is_monthly() else "DAILY TREND")
            if str(self.trend_frame) not in panes:
                self.main_paned.add(self.trend_frame, weight=1)
                self.root.after(10, self._apply_trend_height)
            self._draw_trend()
        else:
            if str(self.trend_frame) in panes:
                self._remember_trend_height()
                self.main_paned.forget(self.trend_frame)

        self._update_status()

    def _load_files(self) -> None:
        """Fetch per-file rows for the expanded apps only (lazy, not for all)."""
        start, end = self.range.bounds()
        self._data_files = {}
        for key in self.expanded:
            members = self._members_of(key)
            self._data_files[key] = self.storage.totals_by_file(start, end, members)

    def _has_files(self, app: dict) -> bool:
        """Whether this app is worth expanding.

        Cheap guess from the config rather than a query per app: an app-level
        rule can never produce file rows. Apps that do track files but happen to
        have only unnamed time expand to a single "(no file)" row, which is
        honest rather than a dead click.
        """
        cfg = self.tracker.cfg if self.tracker else None
        if cfg is None:
            return False
        members = [m for m in self._members_of(app["app"])
                   if not m.startswith(config.MERGE_PREFIX)]
        return any(cfg.tracks_files(m) for m in members)

    _NOTE_FILES = ("ⓘ Files are matched by name — same-named files may share a row "
                   "unless the app shows their folder.")
    _NOTE_SITES = ("ⓘ Sites are read from the page title, so a name may differ "
                   "from the actual website.")

    def _update_note(self) -> None:
        """Explain the naming caveat, but only while a row is expanded."""
        cfg = self.tracker.cfg if self.tracker else None
        if not (cfg and self.expanded):
            self.chart_note.grid_remove()
            return
        site_only = True
        for key in self.expanded:
            members = [m for m in self._members_of(key)
                       if not m.startswith(config.MERGE_PREFIX)]
            if not (members and all(cfg.merged_rules.get(m) == ["site"] for m in members)):
                site_only = False
                break
        self.chart_note.configure(
            text=self._NOTE_SITES if site_only else self._NOTE_FILES)
        self.chart_note.grid(row=1, column=0, sticky="w", pady=(0, 4))

    # -- canvas drawing ---------------------------------------------------

    def _color_for(self, key: str) -> str:
        """A hand-picked colour if the user chose one, else the stable default."""
        cfg = self.tracker.cfg if self.tracker else None
        if cfg:
            chosen = cfg.app_colors.get(key)
            if chosen:
                return chosen
        return color_for(key)

    def _chart_rows(self) -> list[dict]:
        """Flatten apps (and the files of expanded ones) into drawable rows."""
        rows: list[dict] = []
        for app in self._data_apps:
            key = app["app"]
            rows.append({
                "kind": "app", "key": key, "label": app["app_name"],
                "seconds": app["seconds"],
                "pct": (app["seconds"] / self._grand * 100) if self._grand else 0,
                "color": self._color_for(key),
                "has_files": self._has_files(app),
                "expanded": key in self.expanded,
            })
            if key not in self.expanded:
                continue
            files = self._data_files.get(key, [])
            total = app["seconds"] or 1
            for f in files:
                rows.append({
                    "kind": "file", "app": key, "key": f"{key}\x00{f['file']}",
                    "label": f["file"] or "(no file)",
                    "seconds": f["seconds"],
                    "pct": f["seconds"] / total * 100,
                    # Dimmed shade of the parent's colour keeps the grouping
                    # obvious without adding a second palette.
                    "color": _blend(self._color_for(key), PANEL, 0.45),
                    "has_files": False, "expanded": False,
                })
        return rows

    def _draw_chart(self) -> None:
        c = self.chart
        c.delete("all")
        self._rows = []
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            return
        rows = self._chart_rows()
        if not rows:
            c.create_text(w // 2, h // 2, text="No activity in this range",
                          fill=MUTED, font=("Segoe UI", 10))
            c.configure(scrollregion=(0, 0, w, h))
            return

        pad = 12
        pct_w, time_w, gap = 46, 74, 12
        name_w = max(130, (w - 2 * pad - pct_w - time_w - gap) * 0.42)
        bar_x0 = pad + name_w + gap
        bar_right = w - pad - pct_w - time_w
        bar_max = max(16, bar_right - bar_x0 - gap)
        maxv = max((r["seconds"] for r in rows if r["kind"] == "app"), default=0) or 1

        font = ("Segoe UI", 9)
        min_row, vpad = 26, 10
        y = pad
        for row in rows:
            is_file = row["kind"] == "file"
            # The expander gets its own column so every name starts at the same
            # x, whether or not the row can be expanded.
            indent = FILE_INDENT if is_file else 0
            name_x = pad + MARKER_W + indent
            # Measure the wrapped name first so the row can grow to fit it.
            # Wrap a little narrower than the column: Tk overshoots slightly
            # when breaking a long unbroken token (a path, say).
            text_id = c.create_text(
                name_x, y, text=row["label"], anchor="nw",
                fill=MUTED if is_file else FG,
                width=max(40, name_w - MARKER_W - indent - 10), font=font)
            x0, y0, x1, y1 = c.bbox(text_id)
            row_h = max(min_row, (y1 - y0) + vpad)

            if self._hover == row.get("key"):
                c.create_rectangle(2, y, w - 2, y + row_h, fill=ROW_HOVER, outline="")
                c.tag_raise(text_id)   # the band is drawn after the name
            c.move(text_id, 0, (row_h - (y1 - y0)) / 2)   # centre in the row

            mid = y + row_h / 2
            if row["has_files"]:
                c.create_text(pad + 3, mid, text="▾" if row["expanded"] else "▸",
                              fill=MUTED, anchor="w", font=font)
            bw = max(2, bar_max * (row["seconds"] / maxv))
            bar_h = min(13, row_h * 0.46)
            c.create_rectangle(bar_x0, mid - bar_h / 2, bar_x0 + bw, mid + bar_h / 2,
                               fill=row["color"], outline="")
            c.create_text(w - pad - pct_w, mid, text=fmt_duration(row["seconds"]),
                          fill=FG if not is_file else MUTED, anchor="e", font=font)
            c.create_text(w - pad, mid, text=f"{row['pct']:.0f}%",
                          fill=MUTED, anchor="e", font=font)

            row["y0"], row["y1"] = y, y + row_h
            self._rows.append(row)
            y += row_h

        c.configure(scrollregion=(0, 0, w, max(y + pad, h)))

    _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def _trend_is_monthly(self) -> bool:
        """Bucket by month for the year view and for long custom ranges."""
        if self.range.mode == "year":
            return True
        if self.range.mode == "custom":
            return len(self.range.days()) > 62
        return False

    def _trend_bars(self) -> list[tuple[str, float, bool]]:
        """(label, seconds, is_current) buckets: monthly or daily per range."""
        today = dt.date.today()
        days = self.range.days()
        if self._trend_is_monthly():
            buckets: dict[tuple[int, int], float] = {}
            order: list[tuple[int, int]] = []
            for d in days:
                key = (d.year, d.month)
                if key not in buckets:
                    buckets[key] = 0.0
                    order.append(key)
                buckets[key] += self._data_trend.get(d.isoformat(), 0.0)
            multi_year = len({y for y, _ in order}) > 1
            out = []
            for (y, m) in order:
                lbl = f"{self._MONTHS[m - 1]}'{y % 100:02d}" if multi_year else self._MONTHS[m - 1]
                out.append((lbl, buckets[(y, m)], y == today.year and m == today.month))
            return out
        bars = []
        for d in days:
            v = self._data_trend.get(d.isoformat(), 0.0)
            is_today = d == today
            if self.range.mode == "week":
                lbl = d.strftime("%a")
            else:  # month / short custom: sparse day-number labels
                lbl = str(d.day) if (d.day == 1 or d.day % 5 == 0 or is_today) else ""
            bars.append((lbl, v, is_today))
        return bars

    def _draw_trend(self) -> None:
        c = self.trend
        c.delete("all")
        bars = self._trend_bars()
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1 or not bars:
            return
        maxv = max((v for _, v, _ in bars), default=0) or 1
        pad_x = 10
        pad_bottom = 22
        pad_top = 20  # room for the value label above the tallest bar
        n = len(bars)
        slot = (w - 2 * pad_x) / n
        bar_w = min(slot * 0.6, 46)
        base_y = h - pad_bottom
        for i, (lbl, v, is_cur) in enumerate(bars):
            cx = pad_x + slot * (i + 0.5)
            bh = (base_y - pad_top) * (v / maxv) if v else 0
            x0 = cx - bar_w / 2
            x1 = cx + bar_w / 2
            color = ACCENT if is_cur else "#4a4c66"
            if v:
                c.create_rectangle(x0, base_y - bh, x1, base_y, fill=color, outline="")
                if bh > 12:
                    ty = max(9, base_y - bh - 8)  # keep the label inside the canvas
                    c.create_text(cx, ty, text=fmt_duration(v),
                                  fill=MUTED, font=("Segoe UI", 8))
            if lbl:
                c.create_text(cx, base_y + 11, text=lbl,
                              fill=(ACCENT if is_cur else MUTED), font=("Segoe UI", 8))

    def _apply_trend_height(self) -> None:
        """Position the sash so the trend pane gets its remembered height."""
        try:
            total = self.main_paned.winfo_height()
            if total <= 1:
                self.root.after(30, self._apply_trend_height)
                return
            pos = max(140, total - self._trend_height)
            self.main_paned.sashpos(0, pos)
        except tk.TclError:
            pass

    def _remember_trend_height(self) -> None:
        """Remember the current trend pane height so it survives view switches."""
        try:
            h = self.trend_frame.winfo_height()
            if h > 40:
                self._trend_height = h
        except tk.TclError:
            pass

    # -- status + lifecycle ----------------------------------------------

    def _update_status(self) -> None:
        if not self.tracker:
            self.status_label.configure(text="")
            return
        if self.tracker.paused:
            self.status_label.configure(text="⏸  Tracking paused")
        elif self.tracker.is_active:
            what = self.tracker.current_app_name
            if self.tracker.current_file:
                what += f" · {self.tracker.current_file}"
            self.status_label.configure(text=f"● Tracking  {what}")
        else:
            self.status_label.configure(text="○ Idle")

    def show(self) -> None:
        self._visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.refresh()
        self._schedule_refresh()

    def hide(self) -> None:
        self._visible = False
        if self._refresh_job:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None
        self.root.withdraw()

    def _schedule_refresh(self) -> None:
        if not self._visible:
            return
        # Light-touch refresh so the current day's numbers tick up live.
        if self.range.mode == "day" and self.range.anchor == dt.date.today():
            self.refresh()
        else:
            self._update_status()
        self._refresh_job = self.root.after(4000, self._schedule_refresh)
