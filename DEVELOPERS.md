# Developer & advanced guide

Technical details for Active Time Tracker. For everyday use, see the
[README](README.md). For a codebase map and conventions, see [CLAUDE.md](CLAUDE.md).

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
GitHub Release. To cut a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

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

## Cross-platform notes

OS-specific access (focus window, idle time, autostart, single-instance) lives
behind small backends in `sysinfo.py` / `autostart.py`:

| | Windows | macOS | Linux (X11) |
|---|---|---|---|
| Focus + idle | built-in (Win32) | `pyobjc` (Quartz/AppKit) | `python-xlib` + `libXss` |
| Autostart | Registry Run key | LaunchAgent plist | `~/.config/autostart` |

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
  "merges": []
}
```

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
* omit an app — use its built-in rule, or generic if it has none.

Advanced users can hand-write a custom regex list (first pattern with a named
`(?P<file>…)` group wins), e.g.
`"mytool.exe": ["(?P<file>[^\\\\/:*?\"<>|]+\\.myext)"]`.

### App groups (`merges`)

A list of `{ "name": ..., "members": ["a.exe", "b.exe"] }`. Members are counted
as one app in reports. Applied at read time (non-destructive).

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
