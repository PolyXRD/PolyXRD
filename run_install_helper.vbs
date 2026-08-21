Set objShell = CreateObject("WScript.Shell")
strPython = "c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe"
strScript = "c:\Users\Administrator\Desktop\WorkSpace\Trae\PolyXRD\install_helper.py"
objShell.Run Chr(34) & strPython & Chr(34) & " " & Chr(34) & strScript & Chr(34), 1, True