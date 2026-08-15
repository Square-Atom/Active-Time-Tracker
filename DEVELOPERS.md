# Developer & advanced guide

Technical details for Active Time Tracker. For everyday use, see the
[README](README.md). For a codebase map and conventions, see [CLAUDE.md](CLAUDE.md).
Release history lives in [CHANGELOG.md](CHANGELOG.md).

## Running from source

* Python 3.13+ (developed on 3.14)
* Install dependencies (platform-specific extras are selected automatically via
  environment markers):

```bash
python -m pip install -r requirements.txt
```

Run it:

```bash
python main.py              # show the dashboard (use pythonw on Windows: no console)
python main.py --minimized  # start hidden in the tray (what autostart uses)
```

Windows convenience launchers: `run.bat` (shows the dashboard) and
`Start Active Time Tracker.vbs` (silent, no console window).

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

`tests/conftest.py` redirects the per-user data directory to a temp sandbox
**before** any project module is imported — `config` resolves and creates that
directory at import time, so tests can never touch (or migrate) your real data.
GUI tests skip themselves when no display is available.

Two rules worth keeping:

* **Never hard-code today's date.** Use the `today` fixture. Tests that assumed
  a fixed date silently broke at midnight.
* **Never hit the network.** `test_updater.py` mocks `urllib`; a rate-limited
  runner shouldn't turn into a red build.

CI runs the suite on Windows, macOS, and Linux for every push and pull request,
and the release build has `needs: test` — a failing suite blocks publishing.

## Building a standalone app

Produces a single file that runs with no Python installed.

```bash
python -m pip install -r requirements-build.txt
```

* **Windows:** run `build.bat` → `dist\ActiveTimeTracker.exe`
* **macOS / Linux:** run `./build.sh` →
  * Linux: `dist/ActiveTimeTracker` (single binary)
  * macOS: `dist/ActiveTimeTracker.app`

Build on the OS you're targeting — PyInstaller is not a cross-compiler.

## Automated releases (GitHub Actions)

You don't have to build by hand. [`.github/workflows/release.yml`](.github/workflows/release.yml)
builds Windows, macOS, and Linux binaries in the cloud and attaches them to a
GitHub Release.

**Release checklist:**

1. Bump `APP_VERSION` in `config.py` to the new version (no `v` prefix).
2. Promote the *Unreleased* section in [CHANGELOG.md](CHANGELOG.md) to the new
   version with today's date, and add its link at the bottom.
3. Commit both, then run the tests (`python -m pytest`) — CI runs them on push
   too, and the build won't publish if they fail.
4. Tag and push (substituting the real version):

```bash
git tag -a vX.Y.Z -m "Active Time Tracker vX.Y.Z"
git push origin main --follow-tags
```

Step 1 matters: the update check compares the GitHub tag against `APP_VERSION`,
so a stale constant tells every user an update is available.

The workflow runs on the tag and produces `ActiveTimeTracker-windows.exe`,
`ActiveTimeTracker-macos.zip`, and `ActiveTimeTracker-linux`, uploading them to
the Release for that tag. You can also trigger a test build from the repo's
**Actions** tab (binaries appear as downloadable *artifacts*). Builds are
unsigned, so first-launch OS warnings apply.

## How tracking works

Polling only — **no global keyboard/mouse hooks**, no admin rights:

1. Every `poll_interval` (default 1s) it reads system idle time and the
   foreground window.
2. If idle ≤ `idle_timeout` (default 10s), the elapsed time is credited to the
   focused app, and to its open file (parsed from the window title).
3. Time is buffered in memory and flushed to SQLite every ~15s (and on
   pause/quit). Credit per tick is capped so sleep/wake gaps can't over-count.

## Controller and MIDI activity (`devices.py`)

`GetLastInputInfo` only reports keyboard and mouse, so a game pad or MIDI
keyboard reads as idleness. `devices.DeviceActivity` watches both and the
tracker takes `min(system_idle, device_idle)`. Windows-only; elsewhere it
reports `NEVER`, which leaves the existing behaviour untouched.

**Controllers** — XInput polled through ctypes, no dependency. Polling is
read-only and never exclusive, so it can't disturb a running game. Two details
matter:

* Sticks drift and triggers jitter, so raw values change constantly even when
  nobody is holding the pad — and `dwPacketNumber` increments with them. State
  is quantised (`_AXIS_STEP`, `_TRIGGER_STEP`) so only a real nudge counts.
* Querying an empty XInput slot is slow, so all four slots are only rescanned
  every few seconds; connected pads are polled every tick.

**MIDI** — `midiInOpen` per input port via winmm. Two hazards:

* **Realtime chatter.** Status bytes `0xF8`–`0xFF` are clock, active sensing and
  friends, which many keyboards emit several times a second regardless of
  whether anyone is playing. Counting those would mean never going idle, so
  `is_musical_message()` filters them. (An Oxygen Pro 49 stays silent when idle,
  but plenty of gear doesn't.)
* **Port exclusivity.** Many Windows MIDI ports are single-client, so holding
  one open could stop a DAW using the keyboard — and since the app autostarts,
  it would usually get there first. Ports already in use are skipped
  (`MMSYSERR_ALLOCATED`) rather than fought over, each port opens independently
  so one refusal doesn't lose the rest, and ports are released when the tracker
  stops or the setting is turned off. The setting exists so a user with a
  single-client device can opt out.

The ctypes callback object is kept on the watcher: let it be collected and the
next MIDI message crashes the process.

## Cross-platform notes

OS-specific access (focus window, idle time, autostart, single-instance) lives
behind small backends in `sysinfo.py` / `autostart.py`:

| | Windows | macOS | Linux (X11) |
|---|---|---|---|
| Focus + idle | built-in (Win32) | `pyobjc` (Quartz/AppKit) | `python-xlib` + `libXss` |
| Autostart | Registry Run key | LaunchAgent plist | `~/.config/autostart` |

`autostart.ensure(enabled)` runs at startup and is the only thing `main` should
call: it verifies the login item both *exists* and still points at the running
executable, rewriting it when stale. Checking existence alone isn't enough —
moving or renaming the program otherwise leaves an entry that launches nothing
and never self-heals.

* **Windows** is the primary, fully-tested platform.
* **macOS:** `requirements.txt` installs `pyobjc`. Reading the open **file name**
  from a window needs Screen Recording permission; without it, time still counts
  at the app level. Tray + window interaction is less battle-tested here.
* **Linux:** needs X11 (Wayland blocks active-window queries). Install the system
  lib if missing — Debian/Ubuntu: `sudo apt install libxss1`.

## Data files

Stored in the per-user data folder (see the README for the path per OS):

* `data.db` — tracked time (SQLite). One table `activity(day, app, app_name,
  file, seconds)`, keyed by `(day, app, file)`; `file=''` means app-level. Raw
  per-exe rows are always stored — **app groups and ignores are applied at read
  time**, so they're retroactive and reversible.
* `config.json` — settings (below).
* `app.log` — error log.
* `backups/` — dated copies (see below).

### Backups

Backups are checked cheaply on the tracker's existing flush cycle, keeping the
newest `backup_keep` (default 7) days as `backups/data-YYYY-MM-DD.db` plus the
matching `config-*.json`. Today's file is **rewritten every
`backup_interval_hours`** (default 1). Backing up only once a day left
everything since that morning unprotected — a real incident lost a day's work
because the only backup predated it.

Two consequences of refreshing through the day:

* **`run()` refuses to replace today's backup with one holding less history**
  (`_lost_history`). If the live database is reverted or damaged, the next
  scheduled backup would otherwise bake that in and destroy the last good copy —
  which would have turned a recoverable incident into permanent loss. The
  refusal is logged. `force=True` skips it for the manual "Back up now", where
  the user has explicitly asked to save the current state.
* `_BACKUP_CHECK_SECONDS` (5 min) must stay well under the shortest sensible
  interval, or the interval gets rounded up to the check period.

`Storage.backup_to()` uses **SQLite's backup API**, not a file copy. This matters:
in WAL mode most recent commits live in the `-wal` sidecar, so copying `data.db`
would miss them and could catch a half-written state. The backup runs against
the live connection, produces one self-contained file, and is followed by a
`wal_checkpoint(TRUNCATE)` to stop the WAL growing unbounded. Writes go to a
`.part` file and are then renamed, so an interrupted run can't leave a truncated
file looking like a good backup. Failures are logged and swallowed — a backup
must never take the tracker down.

Set `backup_dir` to a synced folder (OneDrive, Google Drive, Dropbox…) for off-machine
safety; a copy on the same disk won't survive a drive failure.

### Restoring

`Storage.restore_from(path, mode)` copies rows from an **ATTACHed** database
rather than swapping files, so the live connection — and the tracker writing
through it — keep working. (`ATTACH` can't run inside a transaction, hence the
explicit `commit()` first.)

* `REPLACE` — `DELETE` then insert.
* `MERGE` — upsert taking `MAX(existing, incoming)` per `(day, app, file)`.
  Deliberately not a sum: a backup normally overlaps the current data, so
  adding them would double-count every shared day.

`storage.describe_backup()` opens the file **read-only** and raises `BadBackup`
for anything that isn't one of our databases; the UI calls it before offering
any action, and `restore_from` calls it again before touching anything.
`backups.safety_copy()` writes a `pre-restore-<timestamp>.db` first — named
apart from the dated backups so it neither displaces today's nor disappears in
rotation, since it's the only undo for a mistaken restore.

Upgrading from the old "Work Time Tracker"? The data folder is migrated
automatically on first launch.

## Configuration (`config.json`)

```json
{
  "idle_timeout_seconds": 10,
  "poll_interval_seconds": 1.0,
  "flush_interval_seconds": 15,
  "autostart": true,
  "ignore_apps": ["lockapp.exe"],
  "file_rules": {},
  "merges": [],
  "check_updates_on_startup": true,
  "backup_enabled": true,
  "backup_dir": "",
  "backup_keep": 7,
  "app_colors": {}
}
```

`app_colors` maps an app key (or `merge::<group>`) to a `#rrggbb` bar colour,
set from the dashboard's right-click menu. Anything not listed gets a stable
colour derived from its name — `dashboard.color_for()` hashes the name with md5
rather than `hash()`, which is randomised per process and would change the
palette on every restart.

Most of this is editable from the app's UI (Settings, Ignored apps, App groups,
and the right-click menu). Direct editing is for advanced tweaks.

### File-tracking rules

File detection reads the window title. Built-in rules cover Photoshop, Pyxel
Edit, Aseprite, Krita, Clip Studio, Blender, After Effects, Illustrator, VS Code,
Visual Studio, Sublime, Notepad(++), Obsidian, and Word/Excel/PowerPoint.
Browsers and Explorer default to app-level only.

**Same-named files.** `parse_file` records the fullest identity the title
offers, so two `design.psd` files in different folders don't merge:

1. a **full path**, when the title shows a rooted one (`path_ext_rule` /
   `GENERIC_PATH_RE`) — e.g. Notepad++, Blender, Krita;
2. otherwise **`folder/file`**, when the app names its project/workspace via a
   `(?P<folder>…)` group — e.g. VS Code, Visual Studio, Obsidian;
3. otherwise the **bare filename**.

Apps whose titles show only a filename (Photoshop is the notable one) can't be
disambiguated from the window title at all — those still merge. Separating them
would need an app-specific integration (e.g. a Photoshop script reporting the
active document path).

Right-clicking an app in the dashboard → **Track files for this app** writes
`file_rules`, keyed by the **exe name** (lowercase):

* `["app"]` — never split by file (app-level only).
* `["auto"]` — force generic detection ("first name.ext in the title"), even for
  apps that default to app-level.
* `["site"]` — treat the title as a browser page title and record the **website**
  (see below). The default for Chrome/Edge/Firefox/Brave/Opera/Vivaldi.
* omit an app — use its built-in rule, or generic if it has none.

### Website tracking (`["site"]`)

Window titles never contain the URL — only the page title (`"Facebook - Google
Chrome"`). `config.parse_site` therefore works heuristically:

1. Strip the browser's own suffix. Edge is special-cased because it inserts a
   zero-width space in "Microsoft​ Edge" and may add a profile segment
   (`"Page - Personal - Microsoft Edge"`); that allowance must **not** be applied
   to other browsers or it swallows the real site in `"… - YouTube - Chrome"`.
   Also strips `"and N more pages"` and leading unread counters like `"(3) "`.
2. Split the page title on the usual separators (`-`, `|`, `·`, `/`, `:`, …).
3. If any segment matches `KNOWN_SITES`, use its canonical name — this handles
   sites that put their name *first* (`"GitHub - user/repo: …"`). Segments
   starting with `r/` map to Reddit.
4. Otherwise use the **last** segment, which is where site names conventionally
   live (`"Video title - YouTube"`). Truncated at 40 chars.

Getting real domains would need UI Automation to read the address bar: Windows-
only, an extra dependency, and it forces Chrome's accessibility tree on (raising
Chrome's own CPU/memory). That trade-off was rejected in favour of this.

Advanced users can hand-write a custom regex list (first pattern with a named
`(?P<file>…)` group wins), e.g.
`"mytool.exe": ["(?P<file>[^\\\\/:*?\"<>|]+\\.myext)"]`.

### App groups (`merges`)

A list of `{ "name": ..., "members": ["a.exe", "b.exe"] }`. Members are counted
as one app in reports. Applied at read time (non-destructive).

## Update checking

`updater.py` asks the GitHub API for the latest release of
`Square-Atom/Active-Time-Tracker` and compares its tag with
`config.APP_VERSION`. It uses only stdlib `urllib`, runs off the UI thread
(`check_async`), and never raises — failures come back as an `error` result.
`updatedialog.py` renders the popup, which just links to the Releases page; the
app never downloads or installs anything.

Triggered from Settings (button + "check on startup" toggle, stored as
`check_updates_on_startup`). The startup check runs 3s after launch and stays
silent unless a newer version exists.

**When releasing, bump `config.APP_VERSION` to match the git tag** — the
comparison is tag-vs-constant, so a stale constant makes the app think an update
is always available.

## Notes & limitations

* The app labels its own windows as **"Active Time Tracker"** (not the host
  interpreter process), detected by PID.
* **Photoshop / tabbed apps:** modern versions sometimes show only the app name
  in the main window title (the filename lives on a document tab). When the title
  has no filename, time is still counted at the app level. When it shows only a
  bare filename, two same-named files in different folders are counted together
  (see [File-tracking rules](#file-tracking-rules)).
* Time is credited in ~1-second steps, capped per tick so sleep/wake gaps don't
  over-count.
