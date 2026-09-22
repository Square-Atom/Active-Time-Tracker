"""The "Edit record" window: move some of a record's time under another name.

Most useful for "(no file)" — an editor's window title has no file name until
the document is first saved, so that time lands on the app's untitled row.
Right-click the saved file, **Copy record's name**, then right-click
"(no file)" and **Edit record…**: the name is filled in, and the time moves
across, merging with the file's own.

The edit is a one-off correction to the days on screen (`Storage.move_time`);
nothing is remembered for the past or the future.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

import dashboard as theme

NO_FILE = "(no file)"   # how an app's untitled record reads everywhere

_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*([hms])")


def parse_duration(text: str) -> float | None:
    """Seconds from "1h 20m", "45m", "90s", "1:20:00", "20:00" or "20" (minutes).

    None when the text isn't a duration.
    """
    text = text.strip().lower()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3 or not all(p.strip().isdigit() for p in parts):
            return None
        total = 0.0
        for part in parts:
            total = total * 60 + int(part)
        # "20:00" is minutes:seconds, "1:20:00" hours:minutes:seconds.
        return total
    try:
        return float(text) * 60
    except ValueError:
        pass
    found = _UNIT.findall(text)
    if not found or _UNIT.sub("", text).strip():
        return None
    scale = {"h": 3600, "m": 60, "s": 1}
    return sum(float(n) * scale[u] for n, u in found)


def fmt_exact(seconds: float) -> str:
    """H:MM:SS — exact to the second, and read back by `parse_duration`."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}"


def file_from_label(text: str) -> str:
    """What the user typed as a name → the stored file ('' for no file)."""
    text = text.strip()
    return "" if text == NO_FILE else text


def ask_edit(parent, app_name: str, file: str, available: float,
             range_label: str, choices: list[str], initial: str = ""):
    """Modal "Edit record" dialog.

    `choices` are the app's other record names, offered in the drop-down.
    Returns (seconds, new_file) or None when cancelled.
    """
    dlg = tk.Toplevel(parent)
    dlg.title("Edit record")
    dlg.configure(bg=theme.BG)
    dlg.resizable(False, False)
    dlg.transient(parent)
    result = {"val": None}

    wrap = tk.Frame(dlg, bg=theme.BG)
    wrap.pack(fill="both", expand=True, padx=18, pady=14)
    tk.Label(wrap, text=f"{file or NO_FILE}  ·  {app_name}", bg=theme.BG,
             fg=theme.FG, font=("Segoe UI Semibold", 11), wraplength=380,
             justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
    tk.Label(wrap, text=f"{theme.fmt_duration(available)} recorded  ·  "
                        f"{range_label}", bg=theme.BG, fg=theme.MUTED,
             font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=3,
                                        sticky="w", pady=(2, 0))

    entry_opts = dict(bg=theme.PANEL, fg=theme.FG, insertbackground=theme.FG,
                      borderwidth=0, highlightthickness=1,
                      highlightbackground="#3a3c52", font=("Segoe UI", 10))

    tk.Label(wrap, text="Time to move", bg=theme.BG, fg=theme.FG,
             font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w",
                                         pady=(14, 0))
    amount = tk.StringVar(value=fmt_exact(available))
    amount_row = tk.Frame(wrap, bg=theme.BG)
    amount_row.grid(row=2, column=1, columnspan=2, sticky="w", padx=(10, 0),
                    pady=(14, 0))
    amount_entry = tk.Entry(amount_row, textvariable=amount, width=12,
                            **entry_opts)
    amount_entry.pack(side="left", ipady=3)
    all_btn = tk.Label(amount_row, text="All", bg=theme.PANEL, fg=theme.FG,
                       font=("Segoe UI", 8), padx=8, pady=3, cursor="hand2")
    all_btn.pack(side="left", padx=(6, 0))
    all_btn.bind("<Button-1>", lambda e: amount.set(fmt_exact(available)))
    tk.Label(wrap, text="e.g. 1:20:00, 1h 20m, 45m", bg=theme.BG,
             fg=theme.MUTED, font=("Segoe UI", 8)).grid(
        row=3, column=1, columnspan=2, sticky="w", padx=(10, 0))

    tk.Label(wrap, text="Rename to", bg=theme.BG, fg=theme.FG,
             font=("Segoe UI", 10)).grid(row=4, column=0, sticky="w",
                                         pady=(10, 0))
    target = tk.StringVar(value=initial)
    combo = ttk.Combobox(wrap, textvariable=target, values=choices, width=34,
                         font=("Segoe UI", 10))
    combo.grid(row=4, column=1, columnspan=2, sticky="we", padx=(10, 0),
               pady=(10, 0))

    hint = tk.Label(wrap, text="", bg=theme.BG, fg=theme.MUTED,
                    font=("Segoe UI", 8))
    hint.grid(row=5, column=1, columnspan=2, sticky="w", padx=(10, 0))
    known = {file_from_label(c) for c in choices}

    def update_hint(*_):
        name = file_from_label(target.get())
        if not target.get().strip():
            hint.configure(text="")
        elif name == file:
            hint.configure(text="That's this record's own name.")
        elif name in known:
            hint.configure(text="Existing record — the time is added to it.")
        else:
            hint.configure(text="New name — a record is created for it.")

    target.trace_add("write", update_hint)
    update_hint()

    err = tk.Label(wrap, text="", bg=theme.BG, fg="#ff8b94",
                   font=("Segoe UI", 8))
    err.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def ok():
        seconds = parse_duration(amount.get())
        if seconds is None or seconds <= 0:
            err.configure(text="Enter how much time to move, e.g. 1:20:00.")
            return
        if seconds > available + 0.5:
            err.configure(text=f"There's only {fmt_exact(available)} to move.")
            return
        if not target.get().strip():
            err.configure(text="Enter the name to move the time to.")
            return
        name = file_from_label(target.get())
        if name == file:
            err.configure(text="Pick a different name from this record's own.")
            return
        result["val"] = (min(seconds, available), name)
        dlg.destroy()

    btns = tk.Frame(wrap, bg=theme.BG)
    btns.grid(row=7, column=0, columnspan=3, sticky="e", pady=(12, 0))
    tk.Button(btns, text="Move", command=ok, bg=theme.ACCENT, fg="#12131c",
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

    # With a name already filled in, the amount is what's left to decide.
    first = amount_entry if initial else combo
    first.focus_set()
    if first is amount_entry:
        amount_entry.select_range(0, "end")
    dlg.grab_set()
    dlg.wait_window()
    return result["val"]
