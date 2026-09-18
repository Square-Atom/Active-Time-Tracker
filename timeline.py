"""Day view timeline: what had focus when, with notes pinned to moments.

The bar runs from the first recorded moment of the day to now (or, for a past
day, to the last recorded moment). Each block is one uninterrupted stretch of
the same app, split from its neighbours by a thin dark line. Idle time is a
dark block; time with no record at all (computer off, app closed, tracking
paused) is left black.

The ignore list is applied here, at read time, exactly as the app list
applies it — an ignored app's blocks read as "Not tracked".
"""

from __future__ import annotations

import datetime as dt
import math
import tkinter as tk
from tkinter import messagebox, ttk

import storage as storage_mod
from storage import NOTE_TS_FORMAT

OFF = "#08080c"          # no record — the bar's own background
IDLE_COLOR = "#3a3c55"
UNTRACKED_COLOR = "#2f3044"
NOTE_PAPER = "#f6f6fa"
NOTE_FOLD = "#b4b4c8"
BUBBLE_BG = "#f6f6fa"
BUBBLE_FG = "#1e1f2b"
DANGER = "#ef5350"

# Canvas geometry (pixels).
NOTE_ROW = 26            # note icons sit above the bar
BAR_H = 26
AXIS_H = 18
PAD_X = 8
SEPARATOR_MIN_PX = 4     # thinner blocks get no divider, or it'd all go black
MIN_SPAN = 10 * 60       # never zoom in further than ten minutes
TICK_STEPS_MIN = (5, 10, 15, 30, 60, 120, 180, 240, 360, 720)
TICK_MIN_PX = 64
NOTE_HIT_PX = 7


def build_blocks(segments, ignore=()) -> list[dict]:
    """Turn stored segments into display blocks.

    Applies the ignore list, then joins blocks that touch and share a key (the
    same app either side of a moment we stopped naming).
    """
    ignore = set(ignore)
    blocks: list[dict] = []
    for seg in segments:
        if seg["state"] == storage_mod.ACTIVE and seg["app"] not in ignore:
            key, name, kind = seg["app"], seg["app_name"], "app"
        elif seg["state"] == storage_mod.IDLE:
            key, name, kind = "\x00idle", "Idle", "idle"
        else:
            key, name, kind = "\x00untracked", "Not tracked", "untracked"
        prev = blocks[-1] if blocks else None
        if (prev and prev["key"] == key
                and seg["start"] - prev["end"] <= storage_mod.SEGMENT_JOIN_SECONDS):
            prev["end"] = max(prev["end"], seg["end"])
            continue
        blocks.append({"key": key, "name": name, "kind": kind,
                       "start": seg["start"], "end": seg["end"]})
    return blocks


def view_bounds(blocks, note_times, is_today: bool, now: float):
    """(start, end) epoch seconds to draw, or None when there's nothing."""
    starts = [b["start"] for b in blocks] + list(note_times)
    if not starts:
        return None
    start = min(starts)
    if is_today:
        end = max([now] + list(note_times))
    else:
        end = max([b["end"] for b in blocks] + list(note_times))
    if end - start < MIN_SPAN:
        end = start + MIN_SPAN
    return start, end


def tick_step_minutes(span: float, width: float) -> int:
    """The finest tick interval that leaves room for its labels."""
    for step in TICK_STEPS_MIN:
        if width and step * 60 / span * width >= TICK_MIN_PX:
            return step
    return TICK_STEPS_MIN[-1]


def note_epoch(ts: str) -> float:
    return dt.datetime.strptime(ts, NOTE_TS_FORMAT).timestamp()


def _clock(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch).strftime("%H:%M")


def _duration(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


class Bubble:
    """A small floating label placed above a point on screen."""

    def __init__(self, parent):
        self.parent = parent
        self.win: tk.Toplevel | None = None
        self.text = None

    def show(self, text: str, x_root: int, y_root: int) -> None:
        """Show `text` with its bottom edge centred just above (x, y)."""
        if self.win is None:
            self.win = tk.Toplevel(self.parent)
            self.win.wm_overrideredirect(True)
            try:
                self.win.attributes("-topmost", True)
            except tk.TclError:
                pass
            self.label = tk.Label(self.win, bg=BUBBLE_BG, fg=BUBBLE_FG,
                                  font=("Segoe UI", 9), padx=8, pady=4,
                                  justify="left", wraplength=280)
            self.label.pack()
        if text != self.text:
            self.text = text
            self.label.configure(text=text)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        x = min(max(0, x_root - w // 2), max(0, screen_w - w))
        self.win.wm_geometry(f"+{x}+{max(0, y_root - h - 4)}")

    def hide(self) -> None:
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.text = None


def _draw_pencil(c: tk.Canvas, color: str) -> None:
    c.create_line(8, 18, 17, 9, fill=color, width=4, capstyle="butt")
    c.create_polygon(5, 21, 6.2, 16.8, 9.2, 19.8, fill=color, outline="")
    c.create_line(16.2, 7.2, 19.8, 10.8, fill=color, width=2)


def _draw_trash(c: tk.Canvas, color: str) -> None:
    c.create_line(6, 8, 20, 8, fill=color, width=2)
    c.create_rectangle(10.5, 5, 15.5, 8, outline=color, width=1.5)
    c.create_polygon(7.5, 10, 18.5, 10, 17.5, 21, 8.5, 21,
                     fill="", outline=color, width=1.5)
    for x in (11, 13, 15):
        c.create_line(x, 12.5, x, 18.5, fill=color, width=1.2)


class NoteActions:
    """The little edit / delete pop-up shown when a note icon is clicked."""

    def __init__(self, parent, on_edit, on_delete, bg: str, fg: str, hover: str):
        self.win = tk.Toplevel(parent)
        self.win.wm_overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = tk.Frame(self.win, bg=bg, padx=3, pady=3,
                         highlightthickness=1, highlightbackground="#4a4c66")
        frame.pack()
        self.buttons = {}
        for name, draw, color, action in (
                ("edit", _draw_pencil, fg, on_edit),
                ("delete", _draw_trash, DANGER, on_delete)):
            btn = tk.Canvas(frame, width=26, height=26, bg=bg,
                            highlightthickness=0, cursor="hand2")
            btn.pack(side="left", padx=1)
            draw(btn, color)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=hover))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=bg))
            btn.bind("<Button-1>", lambda e, a=action: a())
            self.buttons[name] = btn
        self.win.bind("<Escape>", lambda e: self.close())

    def place_above(self, x_root: int, y_root: int) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        self.win.wm_geometry(f"+{max(0, x_root - w // 2)}+{max(0, y_root - h - 2)}")

    def close(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def ask_note(parent, day: dt.date, when: dt.datetime | None = None,
             text: str = "", colors=None) -> tuple[str, str] | None:
    """Modal note editor. Returns (timestamp key, text), or None if cancelled.

    `when` defaults to the current time on `day`. The time can be changed;
    the date is the day the note belongs to.
    """
    bg, panel, fg, muted, accent = colors or ("#1e1f2b", "#272838", "#e8e8f0",
                                              "#9a9ab0", "#7c9cff")
    editing = when is not None
    if when is None:
        when = dt.datetime.combine(day, dt.datetime.now().time().replace(microsecond=0))

    dlg = tk.Toplevel(parent)
    dlg.title("Edit note" if editing else "New note")
    dlg.configure(bg=bg)
    dlg.resizable(False, False)
    # A hidden parent (opened by the hotkey from the tray) would hide a
    # transient dialog along with it.
    if parent.winfo_viewable():
        dlg.transient(parent)
    result = {"val": None}

    wrap = tk.Frame(dlg, bg=bg)
    wrap.pack(fill="both", expand=True, padx=18, pady=14)
    tk.Label(wrap, text="Edit note" if editing else "New note", bg=bg, fg=fg,
             font=("Segoe UI Semibold", 12)).grid(row=0, column=0, sticky="w")
    tk.Label(wrap, text=day.strftime("%A, %b %d, %Y"), bg=bg, fg=muted,
             font=("Segoe UI", 9)).grid(row=0, column=1, sticky="e")

    time_row = tk.Frame(wrap, bg=bg)
    time_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 6))
    tk.Label(time_row, text="Time", bg=bg, fg=fg,
             font=("Segoe UI", 10)).pack(side="left")
    initial_hm = when.strftime("%H:%M")
    time_var = tk.StringVar(value=initial_hm)
    time_entry = tk.Entry(time_row, textvariable=time_var, width=6, bg=panel,
                          fg=fg, insertbackground=fg, borderwidth=0,
                          highlightthickness=1, highlightbackground="#3a3c52",
                          font=("Consolas", 11), justify="center")
    time_entry.pack(side="left", padx=(8, 6))
    tk.Label(time_row, text="HH:MM", bg=bg, fg=muted,
             font=("Segoe UI", 8)).pack(side="left")

    body = tk.Text(wrap, width=42, height=6, wrap="word", bg=panel, fg=fg,
                   insertbackground=fg, borderwidth=0, highlightthickness=1,
                   highlightbackground="#3a3c52", highlightcolor=accent,
                   font=("Segoe UI", 10), padx=6, pady=4, undo=True)
    body.grid(row=2, column=0, columnspan=2, sticky="nsew")
    body.insert("1.0", text)

    err = tk.Label(wrap, text="", bg=bg, fg="#ff8b94", font=("Segoe UI", 8))
    err.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def ok(_event=None):
        content = body.get("1.0", "end").strip()
        if not content:
            err.configure(text="Write something first.")
            return "break"
        raw = time_var.get().strip()
        try:
            hm = dt.datetime.strptime(raw, "%H:%M").time()
        except ValueError:
            err.configure(text="Enter the time as HH:MM, e.g. 14:30.")
            return "break"
        # An untouched time keeps its seconds, so notes made a moment apart
        # stay in order.
        chosen = when if raw == initial_hm else dt.datetime.combine(day, hm)
        result["val"] = (chosen.strftime(NOTE_TS_FORMAT), content)
        dlg.destroy()
        return "break"

    btns = tk.Frame(wrap, bg=bg)
    btns.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    tk.Label(btns, text="Ctrl+Enter to save", bg=bg, fg=muted,
             font=("Segoe UI", 8)).pack(side="left")
    tk.Button(btns, text="Save", command=ok, bg=accent, fg="#12131c",
              relief="flat", padx=16, pady=4, cursor="hand2",
              font=("Segoe UI Semibold", 10)).pack(side="right")
    tk.Button(btns, text="Cancel", command=dlg.destroy, bg=panel, fg=fg,
              relief="flat", padx=14, pady=4,
              cursor="hand2").pack(side="right", padx=(0, 8))

    dlg.bind("<Control-Return>", ok)
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    time_entry.bind("<Return>", ok)

    dlg.update_idletasks()
    if parent.winfo_viewable():
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    else:
        px = py = 0
        pw, ph = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
    x = px + (pw - dlg.winfo_reqwidth()) // 2
    y = py + (ph - dlg.winfo_reqheight()) // 3
    dlg.geometry(f"+{max(0, x)}+{max(0, y)}")

    # Brought up by a global hotkey, the dialog has to push to the front.
    dlg.lift()
    try:
        dlg.attributes("-topmost", True)
        dlg.after(300, lambda: dlg.winfo_exists() and dlg.attributes("-topmost", False))
    except tk.TclError:
        pass
    dlg.focus_force()
    body.focus_set()
    body.mark_set("insert", "end")
    dlg.grab_set()
    dlg.wait_window()
    return result["val"]


class TimelineView(ttk.Frame):
    """The timeline strip under the Day view, with its "New note" button."""

    def __init__(self, parent, storage, theme: dict, color_for, on_change=None):
        super().__init__(parent)
        self.storage = storage
        self.theme = theme
        self.color_for = color_for
        self.on_change = on_change
        self.day = dt.date.today()
        self.ignore: set = set()
        self.blocks: list[dict] = []
        self.notes: dict[str, str] = {}
        self.bounds = None
        self._note_hits: list[tuple[float, str]] = []   # (x, ts)
        self._bubble = Bubble(self)
        self._bubble_for = None
        self._actions: NoteActions | None = None
        self._actions_ts: str | None = None

        ttk.Label(self, text="TIMELINE", style="Muted.TLabel").pack(
            anchor="w", pady=(0, 4))
        row = ttk.Frame(self)
        row.pack(fill="x")
        self.new_btn = ttk.Button(row, text="New\nnote", style="Note.TButton",
                                  width=6, command=self.new_note)
        self.new_btn.pack(side="left", fill="y", padx=(0, 10))

        height = NOTE_ROW + BAR_H + AXIS_H
        self.canvas = tk.Canvas(row, height=height, bg=theme["panel"],
                                highlightthickness=0)
        self.canvas.pack(side="left", fill="x", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._clear_hover())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)

        self._top = top = self.winfo_toplevel()
        top.bind("<Button-1>", self._on_outside_click, add="+")
        top.bind("<Unmap>", self._on_top_unmap, add="+")
        top.bind("<Configure>", self._on_top_configure, add="+")
        self.bind("<Unmap>", lambda e: self.close_popups())

    # -- data -------------------------------------------------------------

    def load(self, day: dt.date, ignore=()) -> None:
        self.day = day
        self.ignore = set(ignore)
        segments = self.storage.timeline_for_day(day.isoformat())
        self.blocks = build_blocks(segments, self.ignore)
        self.notes = self.storage.notes_for_day(day.isoformat())
        if self._actions and self._actions_ts not in self.notes:
            self.close_popups()
        self.redraw()

    # -- geometry ---------------------------------------------------------

    def _x_for(self, epoch: float) -> float:
        start, end = self.bounds
        width = self.canvas.winfo_width() - 2 * PAD_X
        return PAD_X + (epoch - start) / (end - start) * width

    def _time_at(self, x: float) -> float:
        start, end = self.bounds
        width = self.canvas.winfo_width() - 2 * PAD_X
        frac = min(1.0, max(0.0, (x - PAD_X) / width))
        return start + frac * (end - start)

    # -- drawing ----------------------------------------------------------

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        self._note_hits = []
        w = c.winfo_width()
        if w <= 2 * PAD_X + 10:
            return
        is_today = self.day == dt.date.today()
        note_times = [note_epoch(ts) for ts in self.notes]
        self.bounds = view_bounds(self.blocks, note_times, is_today,
                                  dt.datetime.now().timestamp())
        bar_y0, bar_y1 = NOTE_ROW, NOTE_ROW + BAR_H
        c.create_rectangle(PAD_X, bar_y0, w - PAD_X, bar_y1, fill=OFF, outline="")
        if self.bounds is None:
            msg = ("Nothing recorded yet today" if is_today
                   else "No timeline recorded for this day")
            c.create_text(w // 2, (bar_y0 + bar_y1) // 2, text=msg,
                          fill=self.theme["muted"], font=("Segoe UI", 9))
            return

        # Blocks, then dividers where two drawn blocks meet.
        spans = []
        for b in self.blocks:
            x0, x1 = self._x_for(b["start"]), self._x_for(b["end"])
            if b["kind"] == "app":
                color = self.color_for(b["key"])
            elif b["kind"] == "idle":
                color = IDLE_COLOR
            else:
                color = UNTRACKED_COLOR
            c.create_rectangle(x0, bar_y0, max(x1, x0 + 1), bar_y1,
                               fill=color, outline="")
            spans.append((x0, x1, b))
        for (a0, a1, a), (b0, b1, b) in zip(spans, spans[1:]):
            touching = b["start"] - a["end"] <= storage_mod.SEGMENT_JOIN_SECONDS
            if touching and a1 - a0 >= SEPARATOR_MIN_PX and b1 - b0 >= SEPARATOR_MIN_PX:
                x = round(b0)
                c.create_line(x, bar_y0, x, bar_y1, fill=OFF, width=1)

        self._draw_axis(bar_y1)
        self._draw_notes()

    def _draw_axis(self, y: float) -> None:
        c = self.canvas
        start, end = self.bounds
        width = c.winfo_width() - 2 * PAD_X
        step = tick_step_minutes(end - start, width) * 60
        midnight = dt.datetime.combine(self.day, dt.time()).timestamp()
        t = midnight + math.ceil((start - midnight) / step) * step
        muted = self.theme["muted"]
        while t <= end:
            x = self._x_for(t)
            c.create_line(x, y, x, y + 3, fill=muted)
            c.create_text(x, y + 4, text=_clock(t), anchor="n", fill=muted,
                          font=("Segoe UI", 8))
            t += step

    def _draw_notes(self) -> None:
        c = self.canvas
        fg = self.theme["fg"]
        for ts in self.notes:
            cx = round(self._x_for(note_epoch(ts)))
            top = 3
            # A page with a folded corner, and a pointer down to the bar.
            c.create_polygon(cx - 6, top, cx + 2, top, cx + 6, top + 4,
                             cx + 6, top + 15, cx - 6, top + 15,
                             fill=NOTE_PAPER, outline="")
            c.create_polygon(cx + 2, top, cx + 2, top + 4, cx + 6, top + 4,
                             fill=NOTE_FOLD, outline="")
            for dy in (7, 10):
                c.create_line(cx - 3, top + dy, cx + 3, top + dy, fill=NOTE_FOLD)
            c.create_polygon(cx - 4, top + 17, cx + 4, top + 17, cx, NOTE_ROW - 2,
                             fill=fg, outline="")
            self._note_hits.append((cx, ts))

    # -- interaction ------------------------------------------------------

    def _note_at(self, x: float, y: float) -> str | None:
        if y > NOTE_ROW or not self._note_hits:
            return None
        x_best, ts = min(self._note_hits, key=lambda h: abs(h[0] - x))
        return ts if abs(x_best - x) <= NOTE_HIT_PX else None

    def _block_at(self, x: float, y: float):
        if not self.bounds or not (NOTE_ROW <= y <= NOTE_ROW + BAR_H):
            return None
        t = self._time_at(x)
        for b in self.blocks:
            if b["start"] <= t <= b["end"]:
                return b
        return "off"

    def _on_motion(self, event) -> None:
        c = self.canvas
        ts = self._note_at(event.x, event.y)
        c.configure(cursor="hand2" if ts else "")
        if ts:
            if self._actions is None:
                x_root = c.winfo_rootx() + round(self._x_for(note_epoch(ts)))
                self._show_bubble(("note", ts), self.notes[ts], x_root,
                                  c.winfo_rooty())
            return
        block = self._block_at(event.x, event.y)
        if block is None:
            self._clear_hover()
            return
        if block == "off":
            text = f"Not recorded · {_clock(self._time_at(event.x))}"
            key = ("off", round(event.x))
        else:
            text = (f"{block['name']}\n{_clock(block['start'])} – "
                    f"{_clock(block['end'])}  ·  "
                    f"{_duration(block['end'] - block['start'])}")
            key = ("block", block["start"])
        self._show_bubble(key, text, c.winfo_rootx() + event.x,
                          c.winfo_rooty() + NOTE_ROW - 2)

    def _show_bubble(self, key, text, x_root, y_root) -> None:
        self._bubble_for = key
        self._bubble.show(text, x_root, y_root)

    def _clear_hover(self) -> None:
        self._bubble_for = None
        self._bubble.hide()
        self.canvas.configure(cursor="")

    def _on_click(self, event):
        ts = self._note_at(event.x, event.y)
        if not ts:
            self.close_popups()
            return None
        self._open_actions(ts)
        return "break"

    def _on_double_click(self, event):
        if self._note_at(event.x, event.y) or not self.bounds:
            return None
        if not (NOTE_ROW <= event.y <= NOTE_ROW + BAR_H):
            return None
        at = dt.datetime.fromtimestamp(self._time_at(event.x)).replace(microsecond=0)
        if at.date() != self.day:
            return None
        self._clear_hover()
        self._edit(None, "", when=at)
        return "break"

    def _open_actions(self, ts: str) -> None:
        self.close_popups()
        self._bubble.hide()
        self._actions_ts = ts
        self._actions = NoteActions(
            self, on_edit=lambda: self._edit_existing(ts),
            on_delete=lambda: self._delete(ts),
            bg=self.theme["panel"], fg=self.theme["fg"],
            hover=self.theme["hover"])
        c = self.canvas
        self._actions.place_above(c.winfo_rootx() + round(self._x_for(note_epoch(ts))),
                                  c.winfo_rooty())

    def close_popups(self) -> None:
        if self._actions is not None:
            self._actions.close()
            self._actions = None
        self._clear_hover()

    def _on_outside_click(self, event) -> None:
        if self._actions is not None and event.widget is not self.canvas:
            self.close_popups()

    def _on_top_unmap(self, event) -> None:
        if event.widget is self._top:
            self.close_popups()

    def _on_top_configure(self, event) -> None:
        # The pop-ups are separate windows; don't leave them behind on a move.
        if self._actions is not None and event.widget is self._top:
            self.close_popups()

    # -- notes ------------------------------------------------------------

    def new_note(self) -> None:
        self.close_popups()
        self._edit(None, "")

    def _edit_existing(self, ts: str) -> None:
        text = self.notes.get(ts, "")
        self.close_popups()
        self._edit(ts, text, when=dt.datetime.strptime(ts, NOTE_TS_FORMAT))

    def _edit(self, old_ts, text, when=None) -> None:
        result = ask_note(self.winfo_toplevel(), self.day, when, text,
                          colors=(self.theme["bg"], self.theme["panel"],
                                  self.theme["fg"], self.theme["muted"],
                                  self.theme["accent"]))
        if result is None:
            return
        ts, content = result
        if old_ts == ts and self.notes.get(ts) == content:
            return
        self.storage.save_note(ts, content, replaces=old_ts)
        self._changed()

    def _delete(self, ts: str) -> None:
        text = self.notes.get(ts, "")
        self.close_popups()
        preview = text if len(text) <= 80 else text[:79] + "…"
        if not messagebox.askyesno(
                "Delete note", f"Delete this note?\n\n{preview}",
                parent=self.winfo_toplevel()):
            return
        self.storage.delete_note(ts)
        self._changed()

    def _changed(self) -> None:
        self.load(self.day, self.ignore)
        if self.on_change:
            self.on_change()
