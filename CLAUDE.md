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
   foreground window. Game-pad and MIDI activity (`devices.py`) counts too —
   Windows' idle timer only sees keyboard and mouse.
2. If idle ≤ `idle_timeout` (default 10s), the elapsed time is credited to the
   focused app, and to its open file (parsed from the window title).
3. Time is buffered in memory and flushed to SQLite every ~15s.

Credit per tick is capped so sleep/wake gaps can't dump a huge chunk onto one app.

## Module map

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point: tray icon (pystray), single-instance guard, wiring, tk mainloop |
| `tracker.py` | Background poll loop; credits active seconds; reads config live |
| `sysinfo.py` | **Cross-platform** foreground-window, idle-time, single-instance, open-folder, global hotkey (dispatches by `sys.platform`) |
| `devices.py` | Game-pad (XInput) and MIDI activity — input Windows doesn't count as input |
| `winapi.py` | Windows ctypes backend (used by `sysinfo` on win32 only) |
| `autostart.py` | Launch-at-login: Windows registry / macOS LaunchAgent / Linux .desktop |
| `storage.py` | SQLite; buffered writes; read-time aggregation (app/file/day, tags, ignore) |
| `config.py` | Paths, defaults, friendly names, file-parsing rules, merge/track helpers |
| `dashboard.py` | tkinter dashboard: ranges, app/tag list, chart, trend; theme constants live here |
| `timeline.py` | Day view timeline strip (focus blocks, idle/off, notes) and the note editor |
| `hotkeys.py` | "New note" hotkey: text form (`Ctrl+Alt+N`), key capture, registration via `sysinfo` |
| `notifications.py` | Focus reminders: the timing (`FocusWatcher`) and the click-to-add-a-note popup (`Toast`) |
| `settings.py` | Tabbed Settings window (General, Ignored apps, Backup, Timeline, Notifications, About) |
| `ignoreapps.py` | Ignored-apps manager window |
| `tags.py` | Tags window (what each tag holds) + the shared tag-name prompt |
| `recordedit.py` | "Edit record" window: move a record's time to another name (duration parsing) |
| `appicon.py` | Clock icon shared by tray, window, and the built .exe |
| `backups.py` | Daily rotating backups (location, rotation, scheduling) |
| `restore.py` | "Restore from backup" window (merge / replace, with undo) |
| `updater.py` | GitHub release check (stdlib urllib, off-thread, never raises) |
| `updatedialog.py` | "Update available" / check-result popups; links to Releases |
| `buildwin.py` | Build-time: Windows app via Nuitka (folder + zip, version resource from `APP_VERSION`) |

`dashboard.py` holds the color constants (`BG`, `PANEL`, `FG`, `MUTED`, `ACCENT`);
`settings.py`, `tags.py`, and `ignoreapps.py` import them as `theme`.

## Data & config

Stored per-user (not in the repo):
- Windows `%APPDATA%\ActiveTimeTracker\`, macOS `~/Library/Application Support/ActiveTimeTracker/`, Linux `~/.config/ActiveTimeTracker/`
- `data.db` (SQLite), `config.json`, `app.log`

`config.py` auto-migrates the pre-rename `WorkTimeTracker` folder on first launch.

**SQLite schema** — one table `activity(day, app, app_name, file, seconds)` keyed
by `(day, app, file)`; `file=''` means app-level. Raw per-exe rows are always
stored; **tags and ignores are applied at read time** in `storage.py`
(non-destructive, retroactive, reversible).

**Timeline** — table `timeline(day, start, end, state, app, app_name)`, epoch
seconds, one row per uninterrupted block (`state` = `active` / `idle` /
`untracked`; ignored apps are recorded as `untracked`). The tracker calls
`Storage.add_span` each tick; contiguous ticks extend the open block, which is
written on flush and then updated in place. Gaps between blocks are "no record".
Blocks never cross midnight. The ignore list is applied at read time in
`timeline.build_blocks`.

**Notes** — table `notes(ts, text)`, `ts` = local `"YYYY-MM-DD HH:MM:SS"`. Both
tables are carried by backups and restores.

**Focus reminders** — off by default (`notify_enabled`). The tracker feeds
`notifications.FocusWatcher.tick` only the seconds it credits to a real app, so
idle time and our own windows neither advance the clock nor reset it; a
different app resets it. The first reminder comes after `notify_first_minutes`
and then every `notify_repeat_minutes`, each interval measured from the
reminder before it. The popup is ours, not a tray balloon: pystray's Windows
backend reports clicks on the icon, not on a balloon, and the click is the
point — it opens the note window centred on screen (`ask_note(center=True)`).

**Hotkey** — `RegisterHotKey` on its own message-loop thread (`winapi.GlobalHotkey`),
not a keyboard hook. Windows only; elsewhere `sysinfo.register_hotkey` returns None.

**Edit record** — right-click a file row → **Edit record…** re-files some of
its time, in the range on screen, under another file name of the same app
(`Storage.move_time`), merging into that name's rows day by day, latest days
first. Unlike tags and ignores this *does* rewrite `activity` rows: it's a
one-off correction, not a rule, so later time still lands where the tracker
puts it. **Copy record's name** (every row) pre-fills the target.

**File detection** — `config.parse_file` reads the window title using per-app
rules in `DEFAULT_FILE_RULES` (+ user overrides in `config.json` `file_rules`):
- `["app"]` = app-level only, `["auto"]` = force generic detection, absent = built-in/generic, or a custom regex list with a `(?P<file>…)` group.
- Users toggle this by right-clicking an app in the dashboard ("Track files").

**Tags** — `config.tags` = list of `{name, items[]}`, where an item is
`{"app": exe}` (the whole app) or `{"app": exe, "file": name}` (one file/site
inside it; `file=""` is the app's untitled time). The chart key is
`tag::<name>`, and the folding happens in `storage.fold_tags` — an item may
sit in several tags, so tag totals overlap by design, but a row is only
counted once within one tag. Tags with no time in the range are left out, and
untagged time isn't reported at all (that's the Apps view's job), so the tag
rows don't add up to the grand total in either direction.
`config.load()` carries a <= 1.6 `merges` list over into tags.

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
- Windows: `build.bat` (Nuitka, needs MSVC) → `dist\ActiveTimeTracker\` + `dist\ActiveTimeTracker-windows.zip`
- macOS/Linux: `./build.sh` (PyInstaller) → `dist/ActiveTimeTracker(.app)`
- Requires `requirements-build.txt`. Neither packager cross-compiles — build on the target OS.

## Notes / gotchas

- Only Windows is verified here; macOS/Linux backends are implemented but should
  be tested on real machines (macOS needs Screen Recording permission for per-file
  window titles; Linux needs X11, not Wayland).
- `build/`, `dist/`, `app.ico`, and `*.spec` are generated and git-ignored.
- **Windows is built with Nuitka, not PyInstaller.** Every PyInstaller variant was
  flagged as a trojan (see DEVELOPERS.md → "Antivirus false positives"). Nuitka
  doesn't set `sys.frozen` (check `__compiled__` too), and its `sys.executable`
  is a nonexistent `python.exe`, so use `autostart._app_executable()`.
- Tests live in `tests/` (pytest): `python -m pytest`. `tests/conftest.py`
  sandboxes the data dir *before* importing project modules, since `config`
  resolves it at import time. Never hard-code today's date (use the `today`
  fixture) and never hit the network. CI gates releases on the suite.
