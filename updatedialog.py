"""The 'a new version is available' popup.

Deliberately minimal: it shows what's new and opens the GitHub Releases page in
the user's browser. The app never downloads or installs anything itself.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser

import config
import dashboard as theme
import updater


def show_update(parent, result: updater.UpdateResult) -> None:
    """Popup announcing a newer release.

    A release can carry its own message (see `updater.announcement`), which is
    shown in place of the standard wording — the point being to say something
    that matters when an update matters. The version line stays either way, so
    the reader always knows what they're being offered.
    """
    body = (f"You're running {config.APP_VERSION}.\n"
            f"Version {result.latest} is available on GitHub.")
    _dialog(
        parent,
        title="Update available",
        heading="A new version is available",
        body=body,
        note=result.notes,
        url=result.url,
        primary="Open download page",
        secondary="Later",
    )


def show_result(parent, result: updater.UpdateResult) -> None:
    """Feedback for a manual check — including the 'nothing new' cases."""
    if result.has_update:
        show_update(parent, result)
        return
    if result.status == "current":
        heading, body = ("You're up to date",
                         f"Version {config.APP_VERSION} is the latest release.")
    elif result.status == "none":
        heading, body = ("No releases yet",
                         result.message or "No published releases were found.")
    else:
        heading, body = ("Couldn't check for updates",
                         result.message or "Something went wrong.")
    _dialog(parent, title="Check for updates", heading=heading, body=body,
            url=updater.RELEASES_PAGE, primary=None, secondary="OK")


def _dialog(parent, *, title, heading, body, url, primary, secondary,
            note: str = "") -> None:
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=theme.BG)
    win.resizable(False, False)
    win.transient(parent)

    wrap = tk.Frame(win, bg=theme.BG)
    wrap.pack(fill="both", expand=True, padx=22, pady=18)

    tk.Label(wrap, text=heading, bg=theme.BG, fg=theme.FG,
             font=("Segoe UI Semibold", 13)).pack(anchor="w")
    tk.Label(wrap, text=body, bg=theme.BG, fg=theme.MUTED, justify="left",
             font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))

    if note:
        # The release's own words, set apart so they read as a message rather
        # than more of the app's chrome. Plain text — never rendered as markup.
        panel = tk.Frame(wrap, bg=theme.PANEL)
        panel.pack(anchor="w", fill="x", pady=(10, 0))
        tk.Label(panel, text=note, bg=theme.PANEL, fg=theme.FG, justify="left",
                 font=("Segoe UI", 9), wraplength=360, padx=10, pady=8).pack(
            anchor="w")

    link = tk.Label(wrap, text=url, bg=theme.BG, fg=theme.ACCENT,
                    font=("Segoe UI", 8, "underline"), cursor="hand2",
                    wraplength=360, justify="left")
    link.pack(anchor="w", pady=(10, 0))
    link.bind("<Button-1>", lambda e: webbrowser.open(url))

    btns = tk.Frame(wrap, bg=theme.BG)
    btns.pack(anchor="e", pady=(16, 0))

    def open_page():
        webbrowser.open(url)
        win.destroy()

    tk.Button(btns, text=secondary, command=win.destroy, bg=theme.PANEL,
              fg=theme.FG, relief="flat", padx=14, pady=4,
              cursor="hand2").pack(side="right", padx=(8, 0))
    if primary:
        tk.Button(btns, text=primary, command=open_page, bg=theme.ACCENT,
                  fg="#12131c", relief="flat", padx=16, pady=4, cursor="hand2",
                  font=("Segoe UI Semibold", 10)).pack(side="right")

    win.bind("<Escape>", lambda e: win.destroy())
    win.update_idletasks()
    rx, ry = parent.winfo_rootx(), parent.winfo_rooty()
    rw, rh = parent.winfo_width(), parent.winfo_height()
    if rw <= 1:  # parent hidden (started in tray) — centre on screen
        rx = ry = 0
        rw, rh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = rx + (rw - win.winfo_width()) // 2
    y = ry + (rh - win.winfo_height()) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.lift()
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))
    win.focus_force()
