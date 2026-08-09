' Double-click to launch Active Time Tracker silently (no console window).
' It starts minimized to the system tray and begins tracking.
Set sh = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir
sh.Run "pythonw """ & scriptDir & "\main.py"" --minimized", 0, False
