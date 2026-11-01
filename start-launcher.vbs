' No-console launcher: double-click this instead of start-launcher.bat.
' Runs the launcher with pythonw (no console window at all, not even
' a brief flash like the .bat gives while it checks PyQt). If PyQt
' ever breaks, use start-launcher.bat instead — that one checks and
' reinstalls PyQt, at the cost of a brief console window.
Dim fso, dir, shell
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = dir
shell.Run "pythonw """ & dir & "\cml-launcher-gui.py""", 0, False
