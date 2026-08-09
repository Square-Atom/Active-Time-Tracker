#!/usr/bin/env bash
# ----------------------------------------------------------------------
# Build a standalone app on macOS or Linux (no Python needed to RUN it).
#
# Output:
#   Linux -> dist/ActiveTimeTracker            (single binary)
#   macOS -> dist/ActiveTimeTracker.app        (app bundle) + dist/ActiveTimeTracker
#
# One-time setup on the build machine:
#   python3 -m pip install -r requirements-build.txt
# (macOS also needs pyobjc; Linux needs python-xlib + libXss — both are pulled
#  in by requirements-build.txt via platform markers, except the system libXss
#  package on Debian/Ubuntu: sudo apt install libxss1)
# ----------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

echo "Installing build dependencies..."
python3 -m pip install -r requirements-build.txt

echo "Building executable (this can take a minute)..."
python3 -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name "ActiveTimeTracker" main.py

echo
echo "Done. See the dist/ folder."
