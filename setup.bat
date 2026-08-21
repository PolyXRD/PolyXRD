@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   PolyXRD Environment Setup
echo ========================================
echo.

REM Check if Python exists
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found. Please install Python 3.11+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [Info] Python version:
python --version
echo.

REM Create virtual environment
if not exist "venv" (
    echo [Info] Creating virtual environment...
    python -m venv venv
) else (
    echo [Info] Virtual environment already exists
)

REM Activate and setup
call venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip

REM Install core dependencies
echo.
echo [Info] Installing core dependencies...
pip install numpy scipy matplotlib PySide6 pandas Pillow platformdirs lmfit

REM Install optional packages (ignore failures)
echo.
echo [Info] Installing optional packages...
pip install pymatgen
pip install powerxrd
pip install GSAS-II
pip install pyqtgraph
pip install pyinstaller
pip install pytest pytest-cov

REM Install project
echo.
echo [Info] Installing project...
pip install -e .

REM Verify installation
echo.
echo ========================================
echo   Verify Installation
echo ========================================
python -c "import numpy; print(f'numpy: {numpy.__version__}')"
python -c "import scipy; print(f'scipy: {scipy.__version__}')"
python -c "import PySide6; print(f'PySide6: {PySide6.__version__}')"
python -c "import matplotlib; print(f'matplotlib: {matplotlib.__version__}')"
python -c "import pymatgen; print(f'pymatgen: {pymatgen.__version__}')" 2>nul || echo pymatgen: not installed
python -c "import lmfit; print(f'lmfit: {lmfit.__version__}')" 2>nul || echo lmfit: not installed
python -c "import polyxrd; print(f'polyxrd: {polyxrd.__version__}')" 2>nul || echo polyxrd: not installed

echo.
echo ========================================
echo   Setup Complete!
echo   Run: venv\Scripts\python -m polyxrd.main
echo ========================================
pause
