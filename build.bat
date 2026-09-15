@echo off
REM ----------------------------------------------------------------------
REM Build the standalone Windows app (no Python needed to RUN it).
REM Output: dist\ActiveTimeTracker\ActiveTimeTracker.exe   (the app folder)
REM         dist\ActiveTimeTracker-windows.zip             (that folder, zipped)
REM
REM Uses Nuitka, not PyInstaller - see buildwin.py for why. Needs Visual
REM Studio's C++ build tools.
REM
REM One-time setup on the build machine:
REM     py -m pip install -r requirements-build.txt
REM ----------------------------------------------------------------------
setlocal
cd /d "%~dp0"

py -3.14 buildwin.py 2>nul || py buildwin.py || goto :failed

echo.
echo Done. Share dist\ActiveTimeTracker-windows.zip - your friend unzips it
echo and double-clicks ActiveTimeTracker.exe inside.
endlocal
exit /b 0

:failed
echo.
echo Build failed: see the messages above.
endlocal
exit /b 1
