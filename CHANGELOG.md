# Changelog

All notable changes to Active Time Tracker.
This project uses [semantic versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

## [1.5.1] — 2026-08-16

### Fixed
- **The v1.5.0 download wouldn't start from a network drive**, failing with
  *"Security validation failure: parent process has different executable!"*.
  The tool that packages the app into a single `.exe` released a new version
  hours before the v1.5.0 build, and it added a startup check that misfires
  when the app is run from a mapped network drive. The packaging tool is now
  pinned to the version that built every release up to 1.4.0. Nothing in the
  app itself was wrong — 1.5.0 ran fine from a local disk.

## [1.5.0] — 2026-08-16

### Added
- **Game controllers and MIDI keyboards keep the timer running.** Windows only
  treats typing and mouse movement as input, so playing on a pad or a MIDI
  keyboard counted as sitting idle and the timer stopped. Both are now watched,
  always — there's nothing to switch on.

  Controller polling is read-only and can't disturb a running game. MIDI needs
  to open your input ports to listen; ports another app already holds are
  skipped, and **Pause tracking** hands them back if your music software needs
  one the app got to first.
- **Backup when you quit**, so closing the app never leaves recent work
  uncaptured.
- **A release can put its own message in the update popup**, for when an update
  is worth explaining. Taken from the release notes (optionally just the part
  between `<!--announce-->` markers); with nothing there the popup reads as
  before.
- **Damaged data files are repaired automatically.** At startup the app checks
  the data file, and if it's damaged it moves the broken copy into a
  `damaged-…` folder, restores your newest healthy backup and tells you what
  happened. Nothing is deleted — the damaged copy is kept in case it holds
  something worth salvaging.

### Fixed
- **Backups now run every 30 minutes, not once a day.** A backup was only taken the
  first time the app ran each day, so everything since that morning had nothing
  to restore from — a day's work could be lost with no copy of it anywhere.
  Today's backup is refreshed on an interval you can set in **Settings →
  Backup** (default every 30 minutes), capping what a problem can cost.
- **A backup can no longer overwrite a good copy with a worse one.** If the live
  database shrinks — reverted or damaged by something outside the app — the next
  scheduled backup would have saved that state over the last good copy and made
  the loss permanent. Shrinking backups are refused and logged instead.
  **Back up now** still saves whatever you have, since that's explicit.

## [1.4.0] — 2026-08-11

### Added
- **Restore from a backup.** **Settings → Restore from backup…** lists your
  backups (or browse for one kept elsewhere) and shows what's inside — how much
  time, which days, how many apps — before you commit. Then either **merge** it
  into your history (keeping the larger record where both have the same day and
  file, so nothing is double-counted) or **replace** everything with it. Your
  current data is snapshotted to a `pre-restore-*.db` first, so a restore can be
  undone.
- An **About** section at the bottom of Settings with the version, author and a
  contact link for feedback.

## [1.3.1] — 2026-08-10

### Changed
- **Hovering any row highlights it**, including files and websites. The gap
  between a short bar and the time on the right made it easy to lose track of
  which row you were reading. The hand cursor still appears only on rows that
  actually expand.

## [1.3.0] — 2026-08-10

### Added
- **Pick a bar colour per app.** Right-click a row → **Bar colour…** and choose
  from a palette, or **Custom…** for an exact shade — so Photoshop can be blue
  and Pyxel Edit red. Choices are saved; **Reset** restores the automatic
  colour. Files follow a dimmed shade of their app's colour.

### Changed
- **The home screen is now a single chart.** The separate applications table is
  gone; every application is one row showing **name · bar · time · percent**.
  Click a row to expand it into the files (or websites) inside it, click again
  to collapse, and right-click any row for the same quick actions as before.
  The list scrolls when it doesn't fit, so nothing is hidden behind a
  "+N more".
- **Each app keeps its own colour.** Colours were assigned by position, so an
  app changed colour whenever the ranking shifted. They're now derived from the
  app's name and stay put from day to day; files use a dimmed shade of their
  app's colour.
- Application names line up in a column of their own, so rows with and without
  an expand arrow start at the same place.

### Fixed
- **The date arrows disappeared when the window was narrowed.** They were the
  first thing dropped when the header ran out of room, even though they're the
  only way to move between days. The header now protects them, and takes less
  space: Settings and App groups are icon buttons (with tooltips — both are
  also on the tray menu), the range presets are labelled *Today / Week / Month
  / Year / Custom*, and the date label drops the year when you're in the
  current one. It now fits the smallest allowed window with room to spare.
- **Start-with-system could silently stop working.** The login entry was only
  checked for existence, never for whether it still pointed at the app — so
  moving, renaming or replacing the program left an entry launching a file that
  no longer existed, and nothing ever repaired it. The entry is now verified on
  every launch and rewritten when it's stale (which also fixes it for anyone
  already affected).
- Filenames containing a hyphen were truncated at the last hyphen —
  `clockwork-workshop.pyxel` was recorded as `workshop.pyxel`. Dashes now only
  separate the app name from the filename when surrounded by spaces.
  (Time logged before this fix keeps the shortened name.)

## [1.2.0] — 2026-08-10

### Added
- **Website tracking for browsers.** Chrome, Edge, Firefox, Brave, Opera and
  Vivaldi now break their time down by site (YouTube, GitHub, Facebook, …)
  instead of being a single lump. Click the browser in the dashboard to see it.

  Site names are read from the page title — window titles never expose the URL —
  so a name can differ from the actual domain, and unusual title formats may
  show an odd label. Turn it off per browser with right-click → *Track files for
  this app*.
- **Automatic backups.** Your database is copied once a day to
  `backups/data-YYYY-MM-DD.db` (newest 7 kept), alongside your settings. In
  **Settings → Backup** you can turn it off, pick the folder, or back up now —
  choose a synced folder (OneDrive, Nextcloud…) to keep copies off this machine,
  where they'd survive a failed drive. New tray item: **Open backups folder**.

### Changed
- **Chart names are shown in full** and wrap onto extra lines instead of being
  cut short. Names now get half the chart width and the bars are about half
  their previous length. When rows don't all fit, a "+N more" marker says how
  many are hidden.

### Fixed
- The taskbar button showed Python's icon when running from source. The app now
  claims its own Windows AppUserModelID and sets a real `.ico`, so the clock
  icon appears in the title bar and taskbar.

### Internal
- Added a **pytest suite** (116 tests) covering title parsing, storage and
  aggregation, the tracker loop, backups, the update check, and the editor
  windows. CI runs it on Windows, macOS and Linux for every push and pull
  request, and release builds are blocked unless it passes.

## [1.1.0] — 2026-08-09

### Added
- **Update checking.** Settings has a new **Updates** section with
  *Automatically check for updates on startup* (on by default) and a
  **Check for updates now** button. When a newer release exists, a popup links
  to the GitHub Releases page. Nothing is downloaded or installed
  automatically — the check only reads public release info.
- **Custom date range.** A **Custom Range** button next to *This Year* opens a
  date picker (with Last 7 / 30 / 90 day presets). ◀ ▶ then pages by that
  range's own length.
- **Resizable trend chart.** Drag the divider above it to change its height;
  it's also taller by default so value labels aren't clipped.
- Note above the per-file chart explaining that files are matched by name.

### Changed
- **Same-named files are no longer merged** when the window title provides
  enough context. The app now records the fullest identity available: a full
  path when the title shows one (Notepad++, Blender, Krita, …), otherwise
  `folder/file` for apps that name their project or workspace (VS Code, Visual
  Studio, Obsidian), otherwise the bare filename. Long paths are shortened on
  folder boundaries in the chart.
- Documentation split: the README is now aimed at everyday users, with
  technical detail moved to [DEVELOPERS.md](DEVELOPERS.md).

### Fixed
- Hyphenated names (`my-file.py`, `Work-Time-Tracker`) are no longer truncated
  when the folder is captured from the window title.
- Trend chart value labels no longer get cut off at the top of the canvas.

### Notes
- Files newly recorded with a folder or path appear as new entries; time logged
  before this release stays under the old bare filename. Nothing is lost.
- Apps that show only a filename in their title (notably Photoshop) still can't
  be told apart — the window title carries nothing to distinguish them.

## [1.0.0] — 2026-08-09

First release.

### Added
- Tray app with a tkinter dashboard that records **active** time per
  application, and per **file** for editors that show the filename in their
  window title.
- Idle detection: the timer pauses after a configurable idle timeout
  (default 10s). Polling only — no keyboard/mouse hooks, no admin rights.
- Review by **Today / This Week / This Month / This Year**, with an app list,
  a bar chart (top apps, or a selected app's files), and a trend chart.
- **App groups** — count several executables as one app.
- **Ignored apps** — never track (and hide) chosen apps.
- Right-click an app to toggle per-file tracking or add it to the ignore list.
- **Settings**: idle timeout, sample interval, start-with-system.
- Cross-platform support: Windows (primary), macOS, and Linux (X11).
- Standalone builds via PyInstaller (`build.bat` / `build.sh`) and automated
  Windows/macOS/Linux release builds through GitHub Actions.
- Local SQLite storage — data never leaves the machine.

[1.5.1]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.5.1
[1.5.0]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.5.0
[1.4.0]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.4.0
[1.3.1]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.3.1
[1.3.0]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.3.0
[1.2.0]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.2.0
[1.1.0]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.1.0
[1.0.0]: https://github.com/Square-Atom/Active-Time-Tracker/releases/tag/v1.0.0
