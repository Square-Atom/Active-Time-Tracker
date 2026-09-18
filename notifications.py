"""Focus reminders: "you've been in this one a while — want to note it?"

Two halves, kept apart so the timing can be tested without a display:
`FocusWatcher` decides when a reminder is due, `Toast` is the little window
that says so.

The toast is ours rather than a tray balloon because the whole point is the
click: pystray's Windows backend reports clicks on the *icon*, not on a
balloon, so a native notification would have nothing to act on. Drawing it
ourselves also keeps it in the app's own colours on every platform.

Time only accumulates while the user is genuinely in one app. Idling, or
looking at Active Time Tracker itself, neither advances the clock nor resets
it — so stepping away to write the note the reminder asked for doesn't start
you over.
"""

from __future__ import annotations

import tkinter as tk

MIN_MINUTES = 1
MAX_MINUTES = 24 * 60
DEFAULT_FIRST = 5
DEFAULT_REPEAT = 15


def _seconds(value, fallback: int) -> float:
    """A minutes setting as seconds, clamped and proof against nonsense."""
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        minutes = fallback
    return max(MIN_MINUTES, min(MAX_MINUTES, minutes)) * 60


class FocusWatcher:
    """Counts uninterrupted time in one app and says when a reminder is due.

    The tracker feeds it only the seconds it credits to a real app, so the
    "don't count idle time or our own windows" rule needs no special case
    here: those ticks simply never arrive.
    """

    def __init__(self, cfg, notify):
        self.cfg = cfg
        self.notify = notify          # notify(app_name, minutes)
        self.app: str | None = None
        self.seconds = 0.0
        self.fired = 0                # reminders given for this stretch
        self.anchor = 0.0             # focus seconds at the last reminder

    def reset(self) -> None:
        self.app = None
        self.seconds = 0.0
        self.fired = 0
        self.anchor = 0.0

    def tick(self, app_key: str, app_name: str, seconds: float) -> None:
        if app_key != self.app:
            self.reset()
            self.app = app_key
        self.seconds += max(0.0, seconds)
        if not getattr(self.cfg, "notify_enabled", False):
            return
        if self.seconds >= self._due_at():
            self.fired += 1
            # Measured from the reminder just given, not from a fixed grid, so
            # switching reminders on (or shortening them) part way through a
            # stretch gives one reminder now and the next a full interval
            # later — never a backlog, never a short gap.
            self.anchor = self.seconds
            self.notify(app_name, int(round(self.seconds / 60)))

    def _due_at(self) -> float:
        """Focus seconds at which the next reminder falls due.

        Read from the config every time, so a change in Settings applies to
        the stretch already under way.
        """
        if self.fired:
            step = _seconds(getattr(self.cfg, "notify_repeat_minutes",
                                    DEFAULT_REPEAT), DEFAULT_REPEAT)
        else:
            step = _seconds(getattr(self.cfg, "notify_first_minutes",
                                    DEFAULT_FIRST), DEFAULT_FIRST)
        return self.anchor + step


def _tree(widget) -> list:
    """A widget and everything inside it."""
    found = [widget]
    for child in widget.winfo_children():
        found.extend(_tree(child))
    return found


def message(app_name: str, minutes: int) -> str:
    unit = "minute" if minutes == 1 else "minutes"
    return f"You have been focusing on {app_name} for {minutes} {unit}."


class Toast:
    """A click-to-act popup in the corner of the screen.

    One window, reused: a second reminder replaces the first rather than
    stacking up a column of them.
    """

    WIDTH = 320
    MARGIN = 18
    LIFETIME_MS = 12000
    PROMPT = "Click to add a note."

    def __init__(self, root, theme: dict, on_click=None):
        self.root = root
        self.theme = theme
        self.on_click = on_click
        self.win: tk.Toplevel | None = None
        self.text = ""
        self._after = None

    # -- showing ----------------------------------------------------------

    def show(self, app_name: str, minutes: int) -> None:
        self.text = message(app_name, minutes)
        try:
            self._build()
        except tk.TclError:
            self.win = None          # no display, or shutting down

    def _build(self) -> None:
        self.hide()
        win = self.win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)          # no title bar, and no focus stolen
        win.configure(bg=self.theme["accent"])
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass

        body = tk.Frame(win, bg=self.theme["panel"])
        # The accent shows as a stripe down the left edge.
        body.pack(fill="both", expand=True, padx=(4, 0))

        head = tk.Frame(body, bg=self.theme["panel"])
        head.pack(fill="x", padx=12, pady=(9, 0))
        tk.Label(head, text="Active Time Tracker", bg=self.theme["panel"],
                 fg=self.theme["muted"], font=("Segoe UI", 8)).pack(side="left")
        close = tk.Label(head, text="✕", bg=self.theme["panel"],
                         fg=self.theme["muted"], font=("Segoe UI", 8),
                         cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", self._dismiss)

        tk.Label(body, text=self.text, bg=self.theme["panel"],
                 fg=self.theme["fg"], font=("Segoe UI", 10),
                 wraplength=self.WIDTH - 40, justify="left").pack(
            anchor="w", padx=12, pady=(4, 0))
        tk.Label(body, text=self.PROMPT, bg=self.theme["panel"],
                 fg=self.theme["accent"], font=("Segoe UI Semibold", 9)).pack(
            anchor="w", padx=12, pady=(2, 10))

        # The whole thing is the button — anywhere but the ✕.
        for widget in _tree(win):
            if widget is close:
                continue
            widget.bind("<Button-1>", self._clicked)
            try:
                widget.configure(cursor="hand2")
            except tk.TclError:
                pass

        self._place(win)
        win.deiconify()
        self._after = win.after(self.LIFETIME_MS, self.hide)

    def _place(self, win) -> None:
        """Bottom-right of the desktop, clear of the taskbar."""
        win.update_idletasks()
        w = max(self.WIDTH, win.winfo_reqwidth())
        h = win.winfo_reqheight()
        area = self._work_area(win)
        x = area[2] - w - self.MARGIN
        y = area[3] - h - self.MARGIN
        win.geometry(f"{w}x{h}+{max(0, int(x))}+{max(0, int(y))}")

    def _work_area(self, win) -> tuple[int, int, int, int]:
        import sysinfo
        area = sysinfo.work_area()
        if area:
            return area
        # No platform answer: guess a taskbar's worth of room at the bottom.
        return (0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - 48)

    # -- dismissing -------------------------------------------------------

    def _clicked(self, _event=None) -> None:
        self.hide()
        if self.on_click:
            self.on_click()

    def _dismiss(self, _event=None) -> str:
        self.hide()
        return "break"                      # the ✕ isn't "click to add a note"

    def hide(self, _event=None) -> None:
        win, self.win = self.win, None
        if self._after and win is not None:
            try:
                win.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
