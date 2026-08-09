# Active Time Tracker

A lightweight app that tracks how much **active** time you spend in each
program — and, for editors like Photoshop, Pyxel Edit, Aseprite, VS Code, etc.,
how much time you spend on each **file**. It runs quietly in the system tray and
lets you review your time by day, week, month, or year.

Primary platform is **Windows**; it also runs on **macOS** and **Linux** (X11)
from source or a self-built app — see [Cross-platform notes](#cross-platform-notes).

## Download (no Python needed)

**Windows:** grab **`ActiveTimeTracker.exe`** from the [Releases](../../releases)
page and double-click it — that's the whole app in one file, nothing to install.

* On first launch Windows SmartScreen may warn "unknown publisher" (normal for
  unsigned apps): click **More info → Run anyway**.
* It starts in the system tray (clock icon) and begins tracking. It also
  registers itself to start with Windows; turn that off in Settings anytime.
* Your data lives in `%APPDATA%\ActiveTimeTracker\` — it stays on your machine.

**macOS / Linux:** build it from source (see below) — a one-file app with no
Python needed to run the result.

## How it works

* Every second it checks which window has focus and how long since your last
  keyboard/mouse input.
* If you've been active within the **idle timeout (default 10s)**, that second is
  credited to the focused app (and its open file).
* After 10 seconds of no input, the timer pauses automatically until you're active again.
* The open file is read from the window's title bar (per-app rules — see below).
* Everything is stored locally in SQLite. Nothing leaves your machine.

It uses **polling only** — no global keyboard/mouse hooks, no admin rights — so
it won't trip antivirus and stays cheap on CPU.

## Running from source

For developers, or if you'd rather not use the packaged app.

* Python 3.13+ (tested on 3.14)
* Install dependencies (platform-specific extras are selected automatically):

```bash
python -m pip install -r requirements.txt
```

* **Show the dashboard:** on Windows double-click `run.bat`, or:

```bash
python main.py          # (use pythonw on Windows for no console window)
```

* **Start hidden in the tray** (what autostart uses):

```bash
python main.py --minimized
```

* **Windows silent launcher:** double-click `Start Active Time Tracker.vbs`.

## Building a standalone app

Produces a single file that runs with no Python installed.

```bash
python -m pip install -r requirements-build.txt
```

* **Windows:** run **`build.bat`** → `dist\ActiveTimeTracker.exe`
* **macOS / Linux:** run **`./build.sh`** →
  * Linux: `dist/ActiveTimeTracker` (single binary)
  * macOS: `dist/ActiveTimeTracker.app`

Share that one file/bundle — no Python required to run it. Upload it to your
GitHub repo's **Releases** so others can download it. (Build on the same OS you're
targeting — PyInstaller is not a cross-compiler.)

## Cross-platform notes

The core is OS-specific (focus window, idle time, autostart, single-instance) and
lives behind small backends in `sysinfo.py` / `autostart.py`:

| | Windows | macOS | Linux (X11) |
|---|---|---|---|
| Focus + idle | built-in (Win32) | `pyobjc` (Quartz/AppKit) | `python-xlib` + `libXss` |
| Autostart | Registry Run key | LaunchAgent plist | `~/.config/autostart` |

* **Windows** is the primary, fully-tested platform.
* **macOS:** `requirements.txt` installs `pyobjc`. Reading the open **file name**
  from a window needs Screen Recording permission; without it, time still counts
  at the app level. Note tray + window interaction is less battle-tested on macOS.
* **Linux:** needs X11 (Wayland's security model blocks active-window queries).
  Install the system lib if missing — Debian/Ubuntu: `sudo apt install libxss1`.

### Tray menu
Right-click the tray clock icon:
* **Open dashboard** (also opens on double-click)
* **Pause / resume tracking**
* **Start with Windows** — toggles launch-at-login (on by default)
* **Settings…** — idle timeout, sample interval
* **App groups…** — count several exes as one app
* **Ignored apps…** — manage the never-tracked list
* **Open data folder**
* **Quit**

### Right-click an app (in the dashboard)
Right-click any app in the **Applications** list for quick actions:
* **Track files for this app** — toggle whether this app is split by file or just
  counted at the app level. Works on any app (even browsers).
* **Add "…" to ignore list** — stop tracking it and hide it from reports.

Right-clicking a merged group applies the action to all its members.

### Settings
Open from the tray menu or the **⚙ Settings** button in the dashboard:
* **Stop timer after idle for** — the idle timeout (default 10s).
* **Sample the active window every** — how often focus is checked (default 1s).
* **Start with Windows** — same as the tray toggle.
* **Manage ignored apps…** — opens the Ignored apps window (below).

Changes apply immediately, no restart needed.

### Ignored apps
Open from the tray menu, or from **Settings → Manage ignored apps…**. Add apps
that should never be tracked (e.g. games, launchers) — pick from a dropdown of
apps you've used or type an exe name — and remove them anytime. Ignored apps are
hidden from the dashboard reports. (You can also right-click an app in the
dashboard to add it here quickly.)

### App groups
Open from the tray menu or the **🔀 Groups** button in the dashboard. Create a
group, give it a name, and add the executables that should be counted as one app
— e.g. **Godot** = `godot.exe` + `godot_console.exe`, or a browser plus its
helper processes.

Grouping is **non-destructive**: the raw per-exe data is kept and groups are folded
together only when shown, so it's **retroactive** (past data folds in too) and can
be changed or removed anytime. A group's file breakdown combines files across all
its members.

Closing the dashboard window (the ✕) just hides it back to the tray; use **Quit**
to actually stop tracking.

## The dashboard

* **Today / This Week / This Month** buttons, with ◀ ▶ to move between periods.
* Left: time per **application**. Click an app to drill into its **per-file**
  breakdown in the chart; click it again to go back to the top-apps view.
* Right: a bar chart — top apps, or the selected app's files.
* Bottom: a **trend** chart — daily for week/month, monthly for the year view.
* Today's view updates live every few seconds.

## Data & settings location

* Windows: `%APPDATA%\ActiveTimeTracker\`
* macOS: `~/Library/Application Support/ActiveTimeTracker/`
* Linux: `~/.config/ActiveTimeTracker/`

Contains:
* `data.db` — your tracked time (SQLite)
* `config.json` — settings
* `app.log` — error log

(Upgrading from the old "Work Time Tracker"? Your data folder is migrated
automatically on first launch.)

## Configuration (`config.json`)

```json
{
  "idle_timeout_seconds": 10,
  "poll_interval_seconds": 1.0,
  "flush_interval_seconds": 15,
  "autostart": true,
  "ignore_apps": ["lockapp.exe"],
  "file_rules": {},
  "merges": []
}
```

### File tracking per app

File detection reads the window title. Built-in rules cover Photoshop, Pyxel Edit,
Aseprite, Krita, Clip Studio, Blender, After Effects, Illustrator, VS Code,
Visual Studio, Sublime, Notepad(++), Obsidian, Word/Excel/PowerPoint. Browsers
and Explorer default to app-level only.

**Easiest:** right-click an app in the dashboard and toggle **Track files for this
app** (see above).

Under the hood this writes `file_rules`, keyed by the **exe name** (lowercase):
* `["app"]` — never split by file (app-level only).
* `["auto"]` — force generic detection ("first name.ext in the title"), even for
  apps that default to app-level.
* omit an app — use its built-in rule, or generic if it has none.

Advanced users can also hand-write a custom regex list here (first pattern with a
named `(?P<file>…)` group wins), e.g.
`"mytool.exe": ["(?P<file>[^\\\\/:*?\"<>|]+\\.myext)"]`.

## Notes & limitations

* The app labels its own windows as **"Active Time Tracker"** (not the host
  interpreter process).
* **Photoshop / tabbed apps:** modern versions sometimes show only the app name
  in the main window title (the filename lives on a document tab). When the title
  doesn't contain the filename, time is still counted at the app level.
* Time is credited in ~1-second steps, capped per tick so sleep/wake gaps don't
  over-count.
