"""
PolyXRD - Install missing packages and start the application.
Usage: d:\\TEMP\\PolyXRD\\venv\\Scripts\\python.exe d:\\TEMP\\PolyXRD\\start_polyxrd.py
"""
import sys
import subprocess

VENV_PIP = r"d:\TEMP\PolyXRD\venv\Scripts\pip.exe"
VENV_PYTHON = r"d:\TEMP\PolyXRD\venv\Scripts\python.exe"

MISSING_PACKAGES = [
    "platformdirs>=3.0.0",
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "powerxrd",
]


def check_package(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def install_package(pkg):
    print(f"  Installing {pkg} ...")
    result = subprocess.run(
        [VENV_PIP, "install", pkg],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  [OK] {pkg}")
    else:
        print(f"  [WARN] {pkg} install failed:")
        print(f"    {result.stderr[-500:] if result.stderr else 'no error output'}")
    return result.returncode == 0


def main():
    print("=" * 50)
    print("  PolyXRD - Environment Check & Launch")
    print("=" * 50)
    print()

    # Check and install missing packages
    check_map = {
        "platformdirs": "platformdirs",
        "pytest": "pytest",
        "powerxrd": "powerxrd",
    }

    missing = []
    for import_name, install_name in check_map.items():
        if not check_package(import_name):
            missing.append(install_name)

    if missing:
        print(f"[Info] Installing {len(missing)} missing package(s)...")
        for pkg in MISSING_PACKAGES:
            pkg_name = pkg.split(">=")[0].split("==")[0].strip()
            if not check_package(pkg_name.replace("-", "_")):
                install_package(pkg)
        print()
    else:
        print("[Info] All packages already installed.")
        print()

    # Final verification
    print("Verifying installation...")
    all_packages = {
        "numpy": "numpy",
        "scipy": "scipy",
        "PySide6": "PySide6",
        "matplotlib": "matplotlib",
        "pandas": "pandas",
        "pymatgen": "pymatgen",
        "lmfit": "lmfit",
        "pyqtgraph": "pyqtgraph",
        "PIL": "Pillow",
        "spglib": "spglib",
        "plotly": "plotly",
        "platformdirs": "platformdirs",
    }

    all_ok = True
    for import_name, display_name in all_packages.items():
        if check_package(import_name):
            print(f"  [OK] {display_name}")
        else:
            print(f"  [MISSING] {display_name}")
            all_ok = False

    # Optional packages
    for opt in ["powerxrd", "GSASIIscriptable"]:
        if check_package(opt):
            print(f"  [OK] {opt} (optional)")
        else:
            print(f"  [OPTIONAL] {opt} not installed")

    # Check polyxrd
    sys.path.insert(0, r"d:\TEMP\PolyXRD\src")
    if check_package("polyxrd"):
        print(f"  [OK] polyxrd")
    else:
        print(f"  [ERROR] polyxrd not importable")
        all_ok = False

    if not all_ok:
        print("\n[WARN] Some required packages are missing. App may not work correctly.")
        print("  Try running: d:\\TEMP\\PolyXRD\\venv\\Scripts\\pip.exe install platformdirs powerxrd")
        print()

    print()
    print("=" * 50)
    print("  Starting PolyXRD...")
    print("=" * 50)
    print()

    # Launch the application
    sys.path.insert(0, r"d:\TEMP\PolyXRD\src")
    from polyxrd.main import main as app_main
    app_main()


if __name__ == "__main__":
    main()
