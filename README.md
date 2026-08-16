# Active Time Tracker

Ever wonder where your time actually goes? Active Time Tracker quietly records how
much **active** time you spend in each app — and, for creative and coding tools,
in each **file** — so you can review it by day, week, month, or year.

It lives in your system tray, barely uses any resources, and keeps all your data
on your own computer.

## Download & install

Grab the file for your system from the [**Releases**](../../releases) page and
open it — there's nothing to install.

| Your system | Download | Open it |
|---|---|---|
| **Windows** | `ActiveTimeTracker-windows.exe` | Double-click it. |
| **macOS** | `ActiveTimeTracker-macos.zip` | Unzip, then open `ActiveTimeTracker.app`. |
| **Linux** (X11) | `ActiveTimeTracker-linux` | Make it executable, then run it. |

The app isn't code-signed, so your system may warn you the first time:

* **Windows:** SmartScreen "unknown publisher" → **More info → Run anyway**.
* **macOS:** right-click the app → **Open** (just the first time).
* **Linux:** if it won't start, install `libxss1` (`sudo apt install libxss1`).

Once open, it shows up as a **clock icon** in your tray and starts tracking. It
also launches automatically when you log in — you can turn that off in Settings.

## Using it

Click the tray icon to open the dashboard.

* **Pick a period** — Today, Week, Month, Year, or a **Custom** range. Use ◀ ▶
  to step to the previous/next period.
* **See your apps** — one row each, showing name, bar, time and share of the
  day. **Click a row** to expand it into the files you worked on; click again to
  collapse. Each app keeps its own colour, so it looks the same day to day.
* **Browsers break down by website** — click Chrome, Edge or Firefox to see
  which sites your time went to (read from the page title, so the name may not
  exactly match the domain).
* **Trend chart** at the bottom shows your activity over time — drag the divider
  above it to make it taller or shorter.

### Right-click an app
* **Track files for this app** — turn per-file tracking on or off for that app.
  (Works when the app shows the file name in its title bar.)
* **Bar colour…** — pick a colour for that app, so Photoshop can be blue and
  Pyxel Edit red. Your choice is saved; **Reset** goes back to the automatic one.
* **Add to ignore list** — stop tracking it and hide it from your stats.

### Tray menu (right-click the clock icon)
* **Open dashboard** · **Pause / resume tracking**
* **Settings** — idle timeout, how often it checks, start-with-system, updates
* **App groups** — count several programs as one (e.g. a game and its launcher)
* **Ignored apps** — manage what's never tracked
* **Open data folder** · **Quit**

Closing the dashboard window just hides it back to the tray — use **Quit** to
actually stop tracking.

## Staying up to date

The app can check GitHub for a newer release. In **Settings** you'll find
**Automatically check for updates on startup** (on by default) and a
**Check for updates now** button.

If a new version exists, a popup links you to the Releases page — you download
and replace the app yourself. Nothing is downloaded or installed automatically,
and the check only reads the public release info. An important release may
include a short note in that popup explaining why it's worth installing.

See [CHANGELOG.md](CHANGELOG.md) for what's new in each version.

## How it works (in short)

It checks which window you're using and whether you've typed or moved the mouse
recently. If you've been active in the last **10 seconds**, that time counts
toward the current app (and its open file). After 10 seconds of no input, the
timer pauses on its own. It only notices *which* window is focused — no
keylogging — and nothing ever leaves your computer.

**Game controllers and MIDI keyboards count too.** Windows treats only typing
and mouse movement as "input", so playing a game on a pad or a part on a MIDI
keyboard used to look like sitting idle. Both are watched as well, so the timer
keeps running.

Listening to a MIDI keyboard means opening its port. If another program is
already using it, the app leaves it alone — but if the app got there first and
your music software can't reach the keyboard, use **Pause tracking** on the tray
menu and it hands the ports straight back.

## Your data

Everything is stored locally in a folder you can back up or delete:

* **Windows:** `%APPDATA%\ActiveTimeTracker\`
* **macOS:** `~/Library/Application Support/ActiveTimeTracker/`
* **Linux:** `~/.config/ActiveTimeTracker/`

### Backups

The app copies your data into a `backups` folder there, keeping the last 7 days.
Today's copy is **refreshed every 30 minutes** and again when you quit, so if
something goes wrong you lose at most half an hour rather than everything since
the morning. Open the folder from the tray menu → **Open backups folder**, and
change how often it's written in **Settings → Backup**.

If the live database ever shrinks — reverted by another program, say — the
automatic backup **refuses to overwrite** the good copy with the smaller one and
notes it in the log, so a bad day can't erase your history. (**Back up now**
saves whatever you currently have, by your explicit request.)

In **Settings → Backup** you can turn this off, back up on demand, or point it
at a different folder. Worth doing: choosing a synced folder (OneDrive,
Google Drive, Dropbox…) means your history survives even if the drive dies — a
backup sitting on the same disk won't.

### Restoring

**Settings → Restore from backup…** lists your backups (or **Browse…** for one
kept elsewhere). Pick one and it shows what's inside — how much time, which
days, how many apps — before you commit to anything. Then choose:

* **Merge into my data** — adds the backup's history to what you have. Where
  both recorded the same day and file, the larger is kept, so nothing is
  double-counted. Use this to recover history you've lost.
* **Replace my data** — throws away everything currently recorded and keeps
  only the backup. Use this if your current data is wrong.

Either way your current data is snapshotted to a `pre-restore-*.db` file first,
so a restore can be undone.

> **Use this window rather than copying files by hand.** Copying a backup over
> `data.db` in Explorer leaves the `data.db-wal` file beside it belonging to the
> *old* database, and the two get blended into something that returns different
> answers on every read. The restore window can't get this wrong.

If the data file is ever damaged anyway, the app notices at startup, moves the
damaged copy into a `damaged-…` folder, restores your newest healthy backup and
tells you what it did.

## For developers

Running from source, building the apps yourself, the automatic release build,
cross-platform details, and advanced configuration all live in
**[DEVELOPERS.md](DEVELOPERS.md)**.

Licensed under the [MIT License](LICENSE).
