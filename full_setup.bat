@echo off
chcp 65001 >nul
echo ========================================
echo   PolyXRD - Full Setup Script
echo   (Bypasses PowerShell Execution Policy)
echo ========================================
echo.

echo [Step 1] Setting PowerShell Execution Policy to RemoteSigned...
reg add "HKCU\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell" /v ExecutionPolicy /t REG_SZ /d RemoteSigned /f
if %errorlevel% equ 0 (
    echo   [OK] Execution policy set successfully.
) else (
    echo   [WARN] Failed to set execution policy, continuing anyway...
)

echo.
echo [Step 2] Installing Python dependencies...
echo.

c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import subprocess, sys; result = subprocess.run([r'c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\pip.exe', 'install', '-r', r'c:\Users\Administrator\Desktop\WorkSpace\Trae\PolyXRD\requirements.txt'], capture_output=True, text=True); print(result.stdout); print(result.stderr); sys.exit(result.returncode if result.returncode else 0)"

if %errorlevel% equ 0 (
    echo.
    echo   [OK] Dependencies installed successfully!
) else (
    echo.
    echo   [FAIL] Dependency installation failed with error code %errorlevel%.
    echo   Check the output above for details.
    pause
    exit /b 1
)

echo.
echo [Step 3] Verifying installation...
echo.

c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import numpy; print(f'  numpy: {numpy.__version__}')" 2>nul || echo "  numpy: NOT INSTALLED"
c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import scipy; print(f'  scipy: {scipy.__version__}')" 2>nul || echo "  scipy: NOT INSTALLED"
c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import PySide6; print(f'  PySide6: {PySide6.__version__}')" 2>nul || echo "  PySide6: NOT INSTALLED"
c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import matplotlib; print(f'  matplotlib: {matplotlib.__version__}')" 2>nul || echo "  matplotlib: NOT INSTALLED"
c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import pandas; print(f'  pandas: {pandas.__version__}')" 2>nul || echo "  pandas: NOT INSTALLED"
c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe -c "import lmfit; print(f'  lmfit: {lmfit.__version__}')" 2>nul || echo "  lmfit: NOT INSTALLED"

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
pause