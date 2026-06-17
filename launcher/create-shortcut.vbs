Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
launcherDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(launcherDir)
vbsPath = launcherDir & "\Zoloto-GitHub.vbs"
desktop = shell.SpecialFolders("Desktop")
linkPath = desktop & "\Zoloto GitHub.lnk"
pythonIcon = projectRoot & "\venv\Scripts\python.exe"

If Not fso.FileExists(vbsPath) Then
  WScript.Echo "Zoloto-GitHub.vbs not found"
  WScript.Quit 1
End If

Set sc = shell.CreateShortcut(linkPath)
sc.TargetPath = shell.ExpandEnvironmentStrings("%ComSpec%")
sc.Arguments = "/c wscript.exe //B //Nologo """ & vbsPath & """"
sc.WorkingDirectory = launcherDir
sc.WindowStyle = 7
sc.Description = "Zoloto GitHub - Telegram admin bot"
If fso.FileExists(pythonIcon) Then
  sc.IconLocation = pythonIcon & ",0"
End If
sc.Save

WScript.Echo "Shortcut created on Desktop"
