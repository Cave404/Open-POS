Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strCurrentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' If virtual environment does not exist yet, launch Start_POS.bat visibly so the user sees setup
If Not fso.FileExists(strCurrentDir & "\venv\Scripts\python.exe") Then
    WshShell.Run "cmd /c """ & strCurrentDir & "\Start_POS.bat""", 1, True
Else
    ' Launch hidden for normal daily retail cashier operation
    intReturn = WshShell.Run("cmd /c """ & strCurrentDir & "\Start_POS.bat""", 0, True)
    If intReturn <> 0 Then
        MsgBox "OpenPOS failed to start properly." & vbCrLf & vbCrLf & _
               "Please launch 'Start_POS.bat' directly to view diagnostic logs.", _
               vbCritical, "OpenPOS Startup Error"
    End If
End If
