@echo off
REM Launch Active Time Tracker (shows the dashboard). Closes the console immediately.
REM Prefer the pyw launcher: a bare "pythonw" can resolve to another app's
REM bundled Python (e.g. Inkscape's) that lacks our dependencies.
where pyw >nul 2>nul && (start "" pyw "%~dp0main.py") || (start "" pythonw "%~dp0main.py")
