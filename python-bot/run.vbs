' ============================================================
' EVA Bot windowless launcher with visible startup diagnostics.
' Dashboard startup errors are logged under data\logs\gui_console.log.
' ============================================================
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = dir

If Not fso.FileExists(dir & "\entry\launcher.py") Then
    MsgBox "EVA Bot project files are incomplete." & vbCrLf & vbCrLf & _
           "Extract the latest project ZIP and merge its papipapi folder into this folder, then try again.", _
           48, "EVA Bot"
    WScript.Quit 1
End If

' 1) Project virtual environment, created by install.bat
py = dir & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(py) Then
    shell.Run """" & py & """ -m entry.launcher", 0, False
    WScript.Quit
End If

' 2) System pythonw
If shell.Run("cmd /c where pythonw >nul 2>&1", 0, True) = 0 Then
    shell.Run "pythonw -m entry.launcher", 0, False
    WScript.Quit
End If

' 3) Python launcher (windowless)
If shell.Run("cmd /c py -3 -c ""import sys"" >nul 2>&1", 0, True) = 0 Then
    shell.Run "py -3w -m entry.launcher", 0, False
    WScript.Quit
End If

MsgBox "Python was not found, so EVA Bot could not start." & vbCrLf & vbCrLf & _
       "Run install.bat from the project folder to install Python dependencies.", _
       48, "EVA Bot"
