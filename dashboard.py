"""The tkinter dashboard window.

Shows focus time for a selected range (Today / This Week / This Month), broken
down by application, with a per-file breakdown for the selected app, a bar chart,
and a daily-trend chart for multi-day ranges. Charts are hand-drawn on a Canvas
to keep dependencies minimal.
"""

from __future__ import annotations

import calendar
import datetime as dt
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

    def label(self) -> str:
        today = dt.date.today()
        if self.mode == "day":
            if self.anchor == today:
                return "Today"
            if self.anchor == today - dt.timedelta(days=1):
                return "Yesterday"
            return self.anchor.strftime("%a, %b %d, %Y")
        if self.mode == "week":
            s, e = self.bounds()
            sd = dt.date.fromisoformat(s)
            ed = dt.date.fromisoformat(e)
            return f"{sd.strftime('%b %d')} – {ed.strftime('%b %d, %Y')}"
        if self.mode == "year":
            return self.anchor.strftime("%Y")
        if self.mode == "custom":
            s, e = self.bounds()
            sd = dt.date.fromisoformat(s)
            ed = dt.date.fromisoformat(e)
            if sd == ed:
                return sd.strftime("%b %d, %Y")
            return f"{sd.strftime('%b %d, %Y')} – {ed.strftime('%b %d, %Y')}"
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
        self.selected_app: str | None = None
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
        style.configure("Active.Seg.TButton", background=ACCENT, foreground="#12131c")
        style.map("Active.Seg.TButton", background=[("active", ACCENT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=FG, borderwidth=0, rowheight=26)
        style.configure("Treeview.Heading", background="#33344a", foreground=MUTED,
                        borderwidth=0, font=("Segoe UI", 9))
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#12131c")])

        # --- header -----------------------------------------------------
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(14, 6))

        seg = ttk.Frame(header)
        seg.pack(side="left")
        self.seg_buttons = {}
        for mode, text in (("day", "Today"), ("week", "This Week"),
                           ("month", "This Month"), ("year", "This Year"),
                           ("custom", "Custom Range")):
            cmd = self._open_custom_range if mode == "custom" \
                else (lambda m=mode: self._set_mode(m))
            b = ttk.Button(seg, text=text, style="Seg.TButton", command=cmd)
            b.pack(side="left", padx=(0, 6))
            self.seg_buttons[mode] = b

        ttk.Button(header, text="⚙ Settings", command=self._open_settings).pack(
            side="right", padx=(8, 0))
        ttk.Button(header, text="🔀 Groups", command=self._open_merges).pack(
            side="right", padx=(8, 0))

        nav = ttk.Frame(header)
        nav.pack(side="right")
        ttk.Button(nav, text="◀", width=3, command=lambda: self._nav(-1)).pack(side="left")
        self.range_label = ttk.Label(nav, text="", style="H.TLabel", width=24, anchor="center")
        self.range_label.pack(side="left", padx=8)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._nav(1)).pack(side="left")

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

        # body: apps | (chart)
        body = ttk.Frame(self.main_paned)
        body.columnconfigure(0, weight=3, uniform="col")
        body.columnconfigure(1, weight=4, uniform="col")
        body.rowconfigure(0, weight=1)
        self.main_paned.add(body, weight=4)

        # Apps
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(left, text="APPLICATIONS", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.app_tree = ttk.Treeview(left, columns=("time", "pct"), show="tree headings",
                                     selectmode="browse")
        self.app_tree.heading("#0", text="App")
        self.app_tree.heading("time", text="Time")
        self.app_tree.heading("pct", text="%")
        self.app_tree.column("#0", width=180, anchor="w")
        self.app_tree.column("time", width=90, anchor="e")
        self.app_tree.column("pct", width=50, anchor="e")
        self.app_tree.pack(fill="both", expand=True)
        self.app_tree.bind("<<TreeviewSelect>>", self._on_app_select)
        self.app_tree.bind("<Button-1>", self._on_app_left_click)
        self.app_tree.bind("<Button-3>", self._on_app_right_click)

        # Right column
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self.chart_title = ttk.Label(right, text="TOP APPLICATIONS", style="Muted.TLabel")
        self.chart_title.grid(row=0, column=0, sticky="w", pady=(0, 4))
        # Shown only in the per-file view: files are identified from the window
        # title, so same-named files can share a row.
        self.chart_note = ttk.Label(
            right,
            text="ⓘ Files are matched by name — same-named files may share a row "
                 "unless the app shows their folder.",
            style="Note.TLabel", wraplength=420, justify="left")
        self.chart = tk.Canvas(right, bg=PANEL, highlightthickness=0, height=200)
        self.chart.grid(row=2, column=0, sticky="nsew")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

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
        self._data_files: list[dict] = []
        self._data_trend: dict[str, float] = {}
        self._grand = 0.0

    # -- events -----------------------------------------------------------

    def _set_mode(self, mode: str) -> None:
        self.range.set_mode(mode)
        self.selected_app = None
        self.refresh()

    def _nav(self, direction: int) -> None:
        self.range.shift(direction)
        self.selected_app = None
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
        self.selected_app = None
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

    def _on_app_select(self, _event=None) -> None:
        sel = self.app_tree.selection()
        self.selected_app = sel[0] if sel else None
        self._load_files()
        self._update_chart_for_selection()

    def _on_app_left_click(self, event):
        # Clicking the already-selected app deselects it (back to top apps).
        row = self.app_tree.identify_row(event.y)
        if row and row == self.selected_app:
            self.app_tree.selection_remove(row)
            self.selected_app = None
            self._load_files()
            self._update_chart_for_selection()
            return "break"
        return None

    # -- right-click context menu ----------------------------------------

    def _members_of(self, key: str) -> list[str]:
        return getattr(self, "_app_members", {}).get(key, [key])

    def _on_app_right_click(self, event) -> None:
        cfg = self.tracker.cfg if self.tracker else None
        if cfg is None:
            return
        row = self.app_tree.identify_row(event.y)
        if not row:
            return
        self.app_tree.selection_set(row)
        self.selected_app = row
        self._load_files()
        self._update_chart_for_selection()

        members = [m for m in self._members_of(row) if not m.startswith(config.MERGE_PREFIX)]
        name = self.app_tree.item(row, "text")
        tracks = bool(members) and all(cfg.tracks_files(m) for m in members)

        menu = tk.Menu(self.root, tearoff=0, bg="#f6f6fa", fg="#1e1f2b",
                       activebackground=ACCENT, activeforeground="#12131c",
                       borderwidth=0, relief="flat")
        self._ctx_track_var = tk.BooleanVar(value=tracks)
        menu.add_checkbutton(label="Track files for this app",
                             variable=self._ctx_track_var,
                             command=lambda: self._ctx_toggle_track(members))
        menu.add_separator()
        menu.add_command(label=f'Add "{name}" to ignore list',
                         command=lambda: self._ctx_ignore(members))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
        self.selected_app = None
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

        # apps tree
        prev = self.selected_app
        self.app_tree.delete(*self.app_tree.get_children())
        for a in self._data_apps:
            pct = (a["seconds"] / self._grand * 100) if self._grand else 0
            self.app_tree.insert("", "end", iid=a["app"], text=a["app_name"],
                                 values=(fmt_duration(a["seconds"]), f"{pct:.0f}%"))
        # keep selection if still present
        if prev and self.app_tree.exists(prev):
            self.app_tree.selection_set(prev)
            self.selected_app = prev
        else:
            self.selected_app = None

        self._load_files()
        self._update_chart_for_selection()

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
        # Per-file data feeds the chart when an app is selected (the separate
        # file table was removed as it duplicated the chart).
        if not self.selected_app:
            self._data_files = []
            return
        start, end = self.range.bounds()
        members = getattr(self, "_app_members", {}).get(self.selected_app, [self.selected_app])
        self._data_files = self.storage.totals_by_file(start, end, members)

    _NOTE_FILES = ("ⓘ Files are matched by name — same-named files may share a row "
                   "unless the app shows their folder.")
    _NOTE_SITES = ("ⓘ Sites are read from the page title, so a name may differ "
                   "from the actual website.")

    def _chart_note_text(self) -> str:
        cfg = self.tracker.cfg if self.tracker else None
        if cfg and self.selected_app:
            members = [m for m in self._members_of(self.selected_app)
                       if not m.startswith(config.MERGE_PREFIX)]
            if members and all(cfg.merged_rules.get(m) == ["site"] for m in members):
                return self._NOTE_SITES
        return self._NOTE_FILES

    def _update_chart_for_selection(self) -> None:
        showing_files = bool(self.selected_app and self._data_files)
        if showing_files:
            app_name = next((a["app_name"] for a in self._data_apps
                             if a["app"] == self.selected_app), self.selected_app)
            self.chart_title.configure(text=f"TIME BY FILE · {app_name.upper()}")
            items = [(f["file"] or "(general)", f["seconds"]) for f in self._data_files]
        else:
            self.chart_title.configure(text="TOP APPLICATIONS")
            items = [(a["app_name"], a["seconds"]) for a in self._data_apps]
        # Caveat text depends on what the rows actually are.
        if showing_files:
            self.chart_note.configure(text=self._chart_note_text())
            self.chart_note.grid(row=1, column=0, sticky="w", pady=(0, 4))
        else:
            self.chart_note.grid_remove()
        self._chart_items = items[:10]
        self._draw_chart()

    # -- canvas drawing ---------------------------------------------------

    def _draw_chart(self) -> None:
        c = self.chart
        c.delete("all")
        items = getattr(self, "_chart_items", [])
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1 or h <= 1:
            return
        if not items:
            c.create_text(w // 2, h // 2, text="No activity in this range",
                          fill=MUTED, font=("Segoe UI", 10))
            return
        pad = 12
        value_w = 68           # right-hand column for the duration
        gap = 12
        # Names get half the canvas; the bar track takes what's left, which is
        # roughly half its old length. Long names wrap instead of being cut.
        label_w = max(120, (w - 2 * pad) * 0.5)
        bar_x0 = pad + label_w + gap
        bar_right = w - pad - value_w
        bar_max = max(16, bar_right - bar_x0)
        maxv = max(v for _, v in items) or 1

        font = ("Segoe UI", 9)
        min_row, vpad = 24, 10
        y = pad
        for i, (label, val) in enumerate(items):
            # Measure the wrapped label first so the row can grow to fit it.
            # Wrap a little narrower than the column: Tk overshoots slightly
            # when it has to break a long unbroken token (a path, say).
            text_id = c.create_text(pad, y, text=label, fill=FG, anchor="nw",
                                    width=max(40, label_w - 10), font=font)
            x0, y0, x1, y1 = c.bbox(text_id)
            row_h = max(min_row, (y1 - y0) + vpad)
            if y + row_h > h - 2 and i > 0:
                # Out of room — drop this row and say how many were hidden.
                c.delete(text_id)
                left = len(items) - i
                c.create_text(pad, min(y + 6, h - 12), anchor="nw",
                              text=f"+{left} more", fill=MUTED, font=("Segoe UI", 8))
                break
            # Centre the label vertically within its row.
            c.move(text_id, 0, (row_h - (y1 - y0)) / 2)
            mid = y + row_h / 2
            bw = max(2, bar_max * (val / maxv))
            bar_h = min(14, row_h * 0.5)
            c.create_rectangle(bar_x0, mid - bar_h / 2, bar_x0 + bw, mid + bar_h / 2,
                               fill=BAR_COLORS[i % len(BAR_COLORS)], outline="")
            c.create_text(w - pad, mid, text=fmt_duration(val), fill=MUTED,
                          anchor="e", font=font)
            y += row_h

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
