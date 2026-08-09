@echo off
REM ----------------------------------------------------------------------
REM Build a standalone Windows executable (no Python needed to RUN it).
REM Output: dist\ActiveTimeTracker.exe   (a single, shareable .exe)
REM
REM One-time setup on the build machine:
REM     py -m pip install -r requirements-build.txt
REM ----------------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo Generating icon...
py -3.14 appicon.py 2>nul || py appicon.py

echo Building executable (this can take a minute)...
py -3.14 -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "ActiveTimeTracker" --icon app.ico main.py 2>nul ^
 || py -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "ActiveTimeTracker" --icon app.ico main.py

echo.
echo Done. Your app is at:  dist\ActiveTimeTracker.exe
echo Share that single file - your friend just double-clicks it.
endlocal
