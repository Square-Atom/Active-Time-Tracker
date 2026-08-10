# CLAUDE.md

Guidance for working in this repository.

## What this is

**Active Time Tracker** — a lightweight desktop app that tracks how much *active*
time you spend in each application, and (for editors) in each open file. It runs
in the system tray with a tkinter dashboard for reviewing time by day / week /
month / year.

Primary platform is **Windows** (fully tested); it also targets **macOS** and
**Linux (X11)** through platform backends.

## How tracking works

Polling only — **no global keyboard/mouse hooks** (avoids antivirus/admin issues):

1. Every `poll_interval` (default 1s) the tracker checks system idle time and the
   foreground window.
2. If idle ≤ `idle_timeout` (default 10s), the elapsed time is credited to the
   focused app, and to its open file (parsed from the window title).
3. Time is buffered in memory and flushed to SQLite every ~15s.

Credit per tick is capped so sleep/wake gaps can't dump a huge chunk onto one app.

## Module map

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point: tray icon (pystray), single-instance guard, wiring, tk mainloop |
| `tracker.py` | Background poll loop; credits active seconds; reads config live |
| `sysinfo.py` | **Cross-platform** foreground-window, idle-time, single-instance, open-folder (dispatches by `sys.platform`) |
| `winapi.py` | Windows ctypes backend (used by `sysinfo` on win32 only) |
| `autostart.py` | Launch-at-login: Windows registry / macOS LaunchAgent / Linux .desktop |
| `storage.py` | SQLite; buffered writes; read-time aggregation (app/file/day, merges, ignore) |
| `config.py` | Paths, defaults, friendly names, file-parsing rules, merge/track helpers |
| `dashboard.py` | tkinter dashboard: ranges, app list, chart, trend; theme constants live here |
| `settings.py` | Settings window (idle, sample interval, autostart, → ignored apps) |
| `ignoreapps.py` | Ignored-apps manager window |
| `merges.py` | "App groups" window (merge several exes into one) |
| `appicon.py` | Clock icon shared by tray, window, and the built .exe |
| `backups.py` | Daily rotating backups (location, rotation, scheduling) |
| `updater.py` | GitHub release check (stdlib urllib, off-thread, never raises) |
| `updatedialog.py` | "Update available" / check-result popups; links to Releases |

`dashboard.py` holds the color constants (`BG`, `PANEL`, `FG`, `MUTED`, `ACCENT`);
`settings.py`, `merges.py`, and `ignoreapps.py` import them as `theme`.

## Data & config

Stored per-user (not in the repo):
- Windows `%APPDATA%\ActiveTimeTracker\`, macOS `~/Library/Application Support/ActiveTimeTracker/`, Linux `~/.config/ActiveTimeTracker/`
- `data.db` (SQLite), `config.json`, `app.log`

`config.py` auto-migrates the pre-rename `WorkTimeTracker` folder on first launch.

**SQLite schema** — one table `activity(day, app, app_name, file, seconds)` keyed
by `(day, app, file)`; `file=''` means app-level. Raw per-exe rows are always
stored; **merges and ignores are applied at read time** in `storage.py`
(non-destructive, retroactive, reversible).

**File detection** — `config.parse_file` reads the window title using per-app
rules in `DEFAULT_FILE_RULES` (+ user overrides in `config.json` `file_rules`):
- `["app"]` = app-level only, `["auto"]` = force generic detection, absent = built-in/generic, or a custom regex list with a `(?P<file>…)` group.
- Users toggle this by right-clicking an app in the dashboard ("Track files").

**Merges** — `config.merges` = list of `{name, members[]}`; group key is
`merge::<name>`.

## Conventions

- Config is read **live** in the tracker loop, so settings changes apply without
  a restart. Editor windows call an `on_change` callback after saving.
- The app's own windows are attributed to `activetimetracker.exe` /
  "Active Time Tracker" (detected by PID in `tracker.py`).
- Anything OS-specific must go through `sysinfo.py` / `autostart.py`, with lazy
  imports so the module stays importable on every platform and degrades safely
  (returns "no window" / zero idle) when an optional dep is missing.
- `config.APP_VERSION` must match the release git tag — the update check
  compares the two.

## Running & building

```bash
python -m pip install -r requirements.txt        # runtime deps (platform markers)
python main.py                                    # run from source (pythonw on Windows)
python main.py --minimized                        # start hidden in tray
```

Build a standalone app (no Python needed to run the result):
- Windows: `build.bat` → `dist\ActiveTimeTracker.exe`
- macOS/Linux: `./build.sh` → `dist/ActiveTimeTracker(.app)`
- Requires `requirements-build.txt` (adds PyInstaller). PyInstaller is not a
  cross-compiler — build on the target OS.

## Notes / gotchas

- Only Windows is verified here; macOS/Linux backends are implemented but should
  be tested on real machines (macOS needs Screen Recording permission for per-file
  window titles; Linux needs X11, not Wayland).
- `build/`, `dist/`, `app.ico`, and `*.spec` are generated and git-ignored.
- Tests live in `tests/` (pytest): `python -m pytest`. `tests/conftest.py`
  sandboxes the data dir *before* importing project modules, since `config`
  resolves it at import time. Never hard-code today's date (use the `today`
  fixture) and never hit the network. CI gates releases on the suite.
