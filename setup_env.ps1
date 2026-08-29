# PolyXRD Environment Setup Script
# Run this script from PowerShell (preferably PowerShell 7):
#   cd d:\TEMP\PolyXRD
#   .\setup_env.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PolyXRD Environment Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- Step 0: Determine Python path ----
$VenvPython = ".\venv\Scripts\python.exe"
$TraePython = "$env:APPDATA\TRAE SOLO CN\ModularData\ai-agent\vm\tools\python\python.exe"
$SystemPython = "python"

$PythonExe = $null

# Try venv first
if (Test-Path $VenvPython) {
    Write-Host "[1/7] Testing existing venv Python..." -ForegroundColor Yellow
    try {
        $result = & $VenvPython --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] venv Python is working: $result" -ForegroundColor Green
            $PythonExe = $VenvPython
            $PipExe = ".\venv\Scripts\pip.exe"
        } else {
            Write-Host "  [WARN] venv Python failed, will try alternatives" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [WARN] venv Python not usable: $_" -ForegroundColor Yellow
    }
}

# Try TRAE built-in Python
if (-not $PythonExe -and (Test-Path $TraePython)) {
    Write-Host "[1/7] Testing TRAE built-in Python..." -ForegroundColor Yellow
    try {
        $result = & $TraePython --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] TRAE Python found: $result" -ForegroundColor Green
            $PythonExe = $TraePython
        }
    } catch {
        Write-Host "  [WARN] TRAE Python not usable: $_" -ForegroundColor Yellow
    }
}

# Try system Python
if (-not $PythonExe) {
    Write-Host "[1/7] Trying system Python..." -ForegroundColor Yellow
    try {
        $result = & $SystemPython --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] System Python found: $result" -ForegroundColor Green
            $PythonExe = $SystemPython
        }
    } catch {
        Write-Host "  [ERROR] No Python found!" -ForegroundColor Red
        Write-Host "  Please install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Red
        Write-Host "  Make sure to check 'Add to PATH' during installation." -ForegroundColor Red
        exit 1
    }
}

if (-not $PythonExe) {
    Write-Host "[ERROR] No usable Python found!" -ForegroundColor Red
    exit 1
}

Write-Host "  Using Python: $PythonExe" -ForegroundColor Green
Write-Host ""

# ---- Step 2: Recreate venv if using non-venv Python ----
if ($PythonExe -ne $VenvPython) {
    Write-Host "[2/7] Creating new virtual environment..." -ForegroundColor Yellow
    if (Test-Path "venv") {
        Write-Host "  Removing old venv..." -ForegroundColor DarkGray
        Remove-Item -Recurse -Force "venv" -ErrorAction SilentlyContinue
    }
    & $PythonExe -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] venv creation failed!" -ForegroundColor Red
        exit 1
    }
    $PythonExe = ".\venv\Scripts\python.exe"
    $PipExe = ".\venv\Scripts\pip.exe"
    Write-Host "  [OK] New venv created" -ForegroundColor Green
} else {
    Write-Host "[2/7] Using existing venv" -ForegroundColor Green
}
Write-Host ""

# ---- Step 3: Upgrade pip ----
Write-Host "[3/7] Upgrading pip..." -ForegroundColor Yellow
& $PythonExe -m pip install --upgrade pip 2>&1 | Out-Host
Write-Host "  [OK] pip upgraded" -ForegroundColor Green
Write-Host ""

# ---- Step 4: Install core dependencies ----
Write-Host "[4/7] Installing core dependencies..." -ForegroundColor Yellow

$coreDeps = @(
    "numpy>=1.24",
    "scipy>=1.10",
    "matplotlib>=3.7",
    "pandas>=2.0.0",
    "Pillow>=9.0.0",
    "platformdirs>=3.0.0"
)

foreach ($dep in $coreDeps) {
    Write-Host "  Installing $dep ..." -ForegroundColor DarkGray
    & $PipExe install $dep 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    [WARN] $dep installation had issues" -ForegroundColor Yellow
    }
}
Write-Host "  [OK] Core dependencies installed" -ForegroundColor Green
Write-Host ""

# ---- Step 5: Install GUI and scientific dependencies ----
Write-Host "[5/7] Installing GUI and scientific dependencies..." -ForegroundColor Yellow

$sciDeps = @(
    "PySide6>=6.5",
    "pymatgen>=2024.1.1",
    "lmfit>=1.3",
    "pyqtgraph>=0.13.0",
    "spglib>=2.0",
    "plotly>=5.0"
)

foreach ($dep in $sciDeps) {
    Write-Host "  Installing $dep ..." -ForegroundColor DarkGray
    & $PipExe install $dep 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    [WARN] $dep installation had issues" -ForegroundColor Yellow
    }
}

# powerxrd (optional but needed)
Write-Host "  Installing powerxrd ..." -ForegroundColor DarkGray
& $PipExe install "powerxrd>=1.0" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    [WARN] powerxrd installation failed (may need manual install)" -ForegroundColor Yellow
}

# GSAS-II (optional)
Write-Host "  Installing GSAS-II (optional)..." -ForegroundColor DarkGray
& $PipExe install "GSAS-II" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    [INFO] GSAS-II not available via pip (optional - app has built-in engine)" -ForegroundColor DarkGray
}

Write-Host "  [OK] Scientific dependencies installed" -ForegroundColor Green
Write-Host ""

# ---- Step 6: Install dev tools ----
Write-Host "[6/7] Installing development tools..." -ForegroundColor Yellow
& $PipExe install "pyinstaller>=6.0" "pytest>=7.0" "pytest-cov>=4.0" 2>&1 | Out-Null
Write-Host "  [OK] Dev tools installed" -ForegroundColor Green
Write-Host ""

# ---- Step 6.5: Install PolyXRD in development mode ----
Write-Host "[6.5/7] Installing PolyXRD (development mode)..." -ForegroundColor Yellow
& $PipExe install -e . 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [WARN] pip install -e . had issues, trying alternative..." -ForegroundColor Yellow
    & $PipExe install -e . --no-build-isolation 2>&1 | Out-Host
}
Write-Host ""

# ---- Step 7: Verify installation ----
Write-Host "[7/7] Verifying installation..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$packages = @(
    "numpy", "scipy", "PySide6", "matplotlib", "pandas",
    "pymatgen", "lmfit", "pyqtgraph", "PIL",
    "platformdirs", "spglib", "plotly",
    "powerxrd", "pytest", "PyInstaller"
)

$allOk = $true
foreach ($pkg in $packages) {
    $result = & $PythonExe -c "import $pkg; print(getattr($pkg, '__version__', 'OK'))" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $pkg`: $result" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $pkg" -ForegroundColor Red
        $allOk = $false
    }
}

# Check GSAS-II separately (optional)
$result = & $PythonExe -c "import GSASII; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] GSAS-II: $result" -ForegroundColor Green
} else {
    Write-Host "  [OPTIONAL] GSAS-II: not installed (app has built-in engine)" -ForegroundColor DarkGray
}

# Check polyxrd
$result = & $PythonExe -c "import polyxrd; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] polyxrd: $result" -ForegroundColor Green
} else {
    Write-Host "  [WARN] polyxrd: not importable (try: set PYTHONPATH=src)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "  Setup Complete! All required packages installed." -ForegroundColor Green
} else {
    Write-Host "  Setup partially complete. Some packages missing." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  To run the application:" -ForegroundColor White
Write-Host "    .\venv\Scripts\python.exe -m polyxrd.main" -ForegroundColor White
Write-Host ""
Write-Host "  To run tests:" -ForegroundColor White
Write-Host "    .\venv\Scripts\python.exe -m pytest tests/ -v" -ForegroundColor White
Write-Host ""
Write-Host "  To build EXE:" -ForegroundColor White
Write-Host "    .\venv\Scripts\python.exe -m PyInstaller PolyXRD.spec --noconfirm --clean" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
