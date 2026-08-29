@echo off
REM PolyXRD post-install actions (runs after 7z SFX extract)
REM Usage: setup_actions.bat "<install_dir>"
setlocal enabledelayedexpansion
set "INST=%~1"
if "%INST%"=="" set "INST=%~dp0"

REM Ensure we work from inside install dir
cd /d "%INST%" || goto :eof

set "APP_EXE=%INST%\PolyXRD.exe"
if not exist "%APP_EXE%" (
  echo ERR: PolyXRD.exe not found at %APP_EXE%
  exit /b 1
)

REM --- Start Menu ---
set "SM=%AppData%\Microsoft\Windows\Start Menu\Programs\PolyXRD"
if not exist "%SM%" mkdir "%SM%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SM%\PolyXRD.lnk');" ^
  "$s.TargetPath='%APP_EXE%';" ^
  "$s.WorkingDirectory='%INST%';" ^
  "$s.WindowStyle=7;$s.Save()"

REM --- Desktop shortcut (CurrentUser) ---
for /f "delims=" %%d in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESK=%%d"
if "%DESK%"=="" set "DESK=%USERPROFILE%\Desktop"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESK%\PolyXRD.lnk');" ^
  "$s.TargetPath='%APP_EXE%';" ^
  "$s.WorkingDirectory='%INST%';" ^
  "$s.WindowStyle=7;$s.Save()"

REM --- Uninstall entry: create unins.bat and register in CurrentUser registry (no admin required) ---
set "UNINSTALL=%INST%\uninstall.bat"
(
echo @echo off
echo echo Removing PolyXRD shortcuts...
echo del /q "%%AppData%%\Microsoft\Windows\Start Menu\Programs\PolyXRD\PolyXRD.lnk" ^>nul 2^>^&1
echo rmdir /q "%%AppData%%\Microsoft\Windows\Start Menu\Programs\PolyXRD" ^>nul 2^>^&1
echo for /f "delims=" %%%%d in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"'^) do set "DESK=%%%%d"
echo if "%%DESK%%"=="" set "DESK=%%USERPROFILE%%\Desktop"
echo del /q "%%DESK%%\PolyXRD.lnk" ^>nul 2^>^&1
echo echo Removing uninstaller registry entry...
echo reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PolyXRD" /f ^>nul 2^>^&1
echo echo.
echo echo PolyXRD uninstall shortcuts completed. You may now delete the folder: %%~dp0
echo pause
) > "%UNINSTALL%"

REM Write DisplayName/DisplayVersion info under CurrentUser so Add/Remove shows it
set "REG=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PolyXRD"
reg add "%REG%" /v DisplayName    /t REG_SZ /d "PolyXRD 0.9.0" /f >nul
reg add "%REG%" /v DisplayVersion /t REG_SZ /d "0.9.0"         /f >nul
reg add "%REG%" /v Publisher      /t REG_SZ /d "PolyXRD Team"  /f >nul
reg add "%REG%" /v Contact        /t REG_SZ /d "sshztx@outlook.com" /f >nul
reg add "%REG%" /v URLInfoAbout   /t REG_SZ /d "https://github.com/PolyXRD/PolyXRD" /f >nul
reg add "%REG%" /v InstallLocation /t REG_SZ /d "%INST%"       /f >nul
reg add "%REG%" /v UninstallString /t REG_SZ /d "\"%UNINSTALL%\"" /f >nul
reg add "%REG%" /v NoModify       /t REG_DWORD /d 1 /f >nul
reg add "%REG%" /v NoRepair       /t REG_DWORD /d 1 /f >nul
REM Estimated size KB: sum folder -> /1024
for /f "usebackq tokens=* delims=" %%k in (`powershell -NoProfile -Command "[math]::Round((Get-ChildItem -Recurse -File '%INST%'|Measure-Object Length -Sum).Sum/1024,0)"`) do set "SKB=%%k"
if defined SKB reg add "%REG%" /v EstimatedSize /t REG_DWORD /d %SKB% /f >nul

endlocal
exit /b 0
