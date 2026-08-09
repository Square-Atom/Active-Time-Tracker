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
        self.mode = "day"  # 'day' | 'week' | 'month' | 'year'
        self.anchor = dt.date.today()

    def bounds(self) -> tuple[str, str]:
        if self.mode == "day":
            start = end = self.anchor
        elif self.mode == "week":
            start = self.anchor - dt.timedelta(days=self.anchor.weekday())
            end = start + dt.timedelta(days=6)
        elif self.mode == "year":
            start = self.anchor.replace(month=1, day=1)
            end = self.anchor.replace(month=12, day=31)
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
                           ("month", "This Month"), ("year", "This Year")):
            b = ttk.Button(seg, text=text, style="Seg.TButton",
                           command=lambda m=mode: self._set_mode(m))
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

        # --- body: apps | (chart + files) -------------------------------
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        body.columnconfigure(0, weight=3, uniform="col")
        body.columnconfigure(1, weight=4, uniform="col")
        body.rowconfigure(0, weight=1)

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
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self.chart_title = ttk.Label(right, text="TOP APPLICATIONS", style="Muted.TLabel")
        self.chart_title.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.chart = tk.Canvas(right, bg=PANEL, highlightthickness=0, height=200)
        self.chart.grid(row=1, column=0, sticky="nsew")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

        # --- trend (multi-day only) -------------------------------------
        self.trend_frame = ttk.Frame(self.root)
        self.trend_frame.pack(fill="x", padx=16, pady=(0, 14))
        self.trend_title = ttk.Label(self.trend_frame, text="DAILY TREND", style="Muted.TLabel")
        self.trend_title.pack(anchor="w", pady=(0, 4))
        self.trend = tk.Canvas(self.trend_frame, bg=PANEL, highlightthickness=0, height=120)
        self.trend.pack(fill="x")
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

        # trend visibility
        if self.range.is_multiday:
            self.trend_title.configure(
                text="MONTHLY TREND" if self.range.mode == "year" else "DAILY TREND")
            if not self.trend_frame.winfo_ismapped():
                self.trend_frame.pack(fill="x", padx=16, pady=(0, 14))
            self._draw_trend()
        else:
            self.trend_frame.pack_forget()

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

    def _update_chart_for_selection(self) -> None:
        if self.selected_app and self._data_files:
            app_name = next((a["app_name"] for a in self._data_apps
                             if a["app"] == self.selected_app), self.selected_app)
            self.chart_title.configure(text=f"TIME BY FILE · {app_name.upper()}")
            items = [(f["file"] or "(general)", f["seconds"]) for f in self._data_files]
        else:
            self.chart_title.configure(text="TOP APPLICATIONS")
            items = [(a["app_name"], a["seconds"]) for a in self._data_apps]
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
        row_h = min(34, (h - pad) / len(items))
        maxv = max(v for _, v in items) or 1
        label_w = 150
        bar_x0 = pad + label_w
        bar_max = w - bar_x0 - 70
        for i, (label, val) in enumerate(items):
            y = pad + i * row_h + row_h / 2
            color = BAR_COLORS[i % len(BAR_COLORS)]
            text = label if len(label) <= 22 else "…" + label[-21:]
            c.create_text(pad, y, text=text, fill=FG, anchor="w", font=("Segoe UI", 9))
            bw = max(2, bar_max * (val / maxv))
            c.create_rectangle(bar_x0, y - row_h * 0.28, bar_x0 + bw, y + row_h * 0.28,
                               fill=color, outline="")
            c.create_text(bar_x0 + bw + 6, y, text=fmt_duration(val), fill=MUTED,
                          anchor="w", font=("Segoe UI", 9))

    def _trend_bars(self) -> list[tuple[str, float, bool]]:
        """(label, seconds, is_current) buckets: monthly for year, else daily."""
        today = dt.date.today()
        if self.range.mode == "year":
            year = self.range.anchor.year
            sums = [0.0] * 12
            for day, secs in self._data_trend.items():
                d = dt.date.fromisoformat(day)
                if d.year == year:
                    sums[d.month - 1] += secs
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return [(months[m], sums[m],
                     year == today.year and (m + 1) == today.month) for m in range(12)]
        bars = []
        for d in self.range.days():
            v = self._data_trend.get(d.isoformat(), 0.0)
            is_today = d == today
            if self.range.mode == "week":
                lbl = d.strftime("%a")
            else:  # month
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
        pad_top = 10
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
                if bh > 14:
                    c.create_text(cx, base_y - bh - 8, text=fmt_duration(v),
                                  fill=MUTED, font=("Segoe UI", 7))
            if lbl:
                c.create_text(cx, base_y + 11, text=lbl,
                              fill=(ACCENT if is_cur else MUTED), font=("Segoe UI", 8))

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
