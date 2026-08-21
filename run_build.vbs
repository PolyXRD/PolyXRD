Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 获取脚本所在目录
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 切换到项目目录
shell.CurrentDirectory = scriptDir

' 检查Python是否存在
pythonExe = ""
If fso.FileExists(scriptDir & "\venv\Scripts\python.exe") Then
    pythonExe = scriptDir & "\venv\Scripts\python.exe"
ElseIf fso.FileExists(scriptDir & "\auto_build.py") Then
    ' 使用系统Python
    pythonExe = "python"
End If

If pythonExe = "" Then
    MsgBox "未找到 Python 或 auto_build.py！", vbCritical, "错误"
    WScript.Quit 1
End If

' 运行 auto_build.py
returnCode = shell.Run("""" & pythonExe & """ auto_build.py""", 1, True)

If returnCode = 0 Then
    MsgBox "PolyXRD 打包完成！" & vbCrLf & vbCrLf & "输出目录: dist\PolyXRD\" & vbCrLf & "可执行文件: dist\PolyXRD\PolyXRD.exe", vbInformation, "完成"
Else
    MsgBox "打包过程已结束 (退出码: " & returnCode & ")" & vbCrLf & vbCrLf & "请查看命令行窗口的详细输出。", vbInformation, "提示"
End If
