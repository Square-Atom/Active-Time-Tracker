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

* **Pick a period** — Today, This Week, This Month, This Year, or a **Custom
  Range**. Use ◀ ▶ to step to the previous/next period.
* **See your apps** — the left list shows time per app. **Click an app** to break
  it down by file in the chart; click it again to go back.
* **Browsers break down by website** — click Chrome, Edge or Firefox to see
  which sites your time went to (read from the page title, so the name may not
  exactly match the domain).
* **Trend chart** at the bottom shows your activity over time — drag the divider
  above it to make it taller or shorter.

### Right-click an app
* **Track files for this app** — turn per-file tracking on or off for that app.
  (Works when the app shows the file name in its title bar.)
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
and the check only reads the public release info.

See [CHANGELOG.md](CHANGELOG.md) for what's new in each version.

## How it works (in short)

It checks which window you're using and whether you've typed or moved the mouse
recently. If you've been active in the last **10 seconds**, that time counts
toward the current app (and its open file). After 10 seconds of no input, the
timer pauses on its own. It only notices *which* window is focused — no
keylogging — and nothing ever leaves your computer.

## Your data

Everything is stored locally in a folder you can back up or delete:

* **Windows:** `%APPDATA%\ActiveTimeTracker\`
* **macOS:** `~/Library/Application Support/ActiveTimeTracker/`
* **Linux:** `~/.config/ActiveTimeTracker/`

### Backups

The app copies your data once a day into a `backups` folder there, keeping the
last 7 days. Find it via the tray menu → **Open backups folder**.

In **Settings → Backup** you can turn this off, back up on demand, or point it
at a different folder. Worth doing: choosing a synced folder (OneDrive,
Nextcloud, Dropbox…) means your history survives even if the drive dies — a
backup sitting on the same disk won't.

To restore: quit the app, copy a `data-YYYY-MM-DD.db` over `data.db` (delete any
`data.db-wal` / `data.db-shm` next to it), then start the app again.

## For developers

Running from source, building the apps yourself, the automatic release build,
cross-platform details, and advanced configuration all live in
**[DEVELOPERS.md](DEVELOPERS.md)**.

Licensed under the [MIT License](LICENSE).
