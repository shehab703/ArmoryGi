Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = appDir & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
    MsgBox "venv not found. Run install_offline.bat or setup.bat first.", vbExclamation, "ArmoryGIS Pro"
    WScript.Quit 1
End If
sh.CurrentDirectory = appDir
sh.Run """" & pyw & """ main.py", 0, False
