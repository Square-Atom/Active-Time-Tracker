"""Build the Windows app with Nuitka: dist/ActiveTimeTracker/ plus a zip of it.

Windows builds use Nuitka rather than PyInstaller because antivirus engines
flagged every PyInstaller variant as a trojan. v1.5.1 hit Microsoft
`Wacatac.B!ml`, Kaspersky and others. A PyInstaller exe is a launcher with a
compressed Python archive appended, a layout malware uses heavily. A locally
compiled bootloader and a one-folder build were both still flagged. Nuitka
compiles the code to C and links an ordinary executable, which scanned clean.
See DEVELOPERS.md → "Antivirus false positives".

Needs Visual Studio's C++ build tools. Run: `python buildwin.py`
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

NAME = "ActiveTimeTracker"
PRODUCT = "Active Time Tracker"
COMPANY = "Pixelmancer Studio"
DESCRIPTION = "Active Time Tracker - tracks active time per app and file"
DIST = os.path.join(HERE, "dist")
ZIP_BASENAME = f"{NAME}-windows"


def app_version(config_path: str) -> str:
    """`APP_VERSION` read from config.py's source.

    Importing `config` would create (and possibly migrate) the per-user data
    folder, which a build step has no business doing.
    """
    with open(config_path, encoding="utf-8") as fh:
        match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
    if not match:
        raise ValueError(f"APP_VERSION not found in {config_path}")
    return match.group(1)


def file_version(version: str) -> str:
    """"1.5.1" -> "1.5.1.0". Windows wants exactly four numbers."""
    parts = [str(int(p)) for p in version.split(".")[:4]]
    return ".".join(parts + ["0"] * (4 - len(parts)))


def nuitka_args(version: str, year: int, python: str = sys.executable) -> list[str]:
    return [
        python, "-m", "nuitka",
        "--standalone",
        "--msvc=latest",
        "--assume-yes-for-downloads",       # dependency walker, on a fresh machine
        "--enable-plugin=tk-inter",
        # pystray picks its backend at runtime, out of Nuitka's sight.
        "--include-module=pystray._win32",
        "--windows-console-mode=disable",
        "--windows-icon-from-ico=app.ico",
        # appicon.ensure_ico() looks for it beside the modules.
        "--include-data-files=app.ico=app.ico",
        # The version resource (Properties → Details). An exe without one is
        # another trait antivirus models weigh against unsigned programs.
        f"--company-name={COMPANY}",
        f"--product-name={PRODUCT}",
        f"--file-description={DESCRIPTION}",
        f"--file-version={file_version(version)}",
        f"--product-version={file_version(version)}",
        f"--copyright=Copyright (c) {year} {COMPANY}. MIT License.",
        f"--output-filename={NAME}.exe",
        f"--output-folder-name={NAME}",
        f"--output-dir={DIST}",
        "--remove-output",
        "main.py",
    ]


def main() -> int:
    import datetime

    import appicon

    os.chdir(HERE)
    version = app_version(os.path.join(HERE, "config.py"))
    appicon.save_ico(os.path.join(HERE, "app.ico"))

    folder = os.path.join(DIST, NAME)
    built = folder + ".dist"                    # Nuitka always appends .dist
    for stale in (folder, built):               # no leftovers from an old build
        shutil.rmtree(stale, ignore_errors=True)
    print(f"Building {PRODUCT} {version} with Nuitka (this takes a few minutes)...")
    result = subprocess.run(nuitka_args(version, datetime.date.today().year))
    if result.returncode != 0:
        return result.returncode
    os.rename(built, folder)

    # Zip with the folder at the top, so unzipping gives one tidy folder.
    zip_path = shutil.make_archive(os.path.join(DIST, ZIP_BASENAME), "zip",
                                   root_dir=DIST, base_dir=NAME)
    print(f"Built {os.path.join(folder, NAME + '.exe')}\nZipped {zip_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
