import subprocess
import sys
import os

PYTHON_EXE = r"c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\python.exe"
PIP_EXE = r"c:\Users\Administrator\.workbuddy\binaries\python\envs\polyxrd\Scripts\pip.exe"
REQUIREMENTS = r"c:\Users\Administrator\Desktop\WorkSpace\Trae\PolyXRD\requirements.txt"

def modify_registry():
    try:
        import winreg
        key_path = r"Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell"
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "ExecutionPolicy", 0, winreg.REG_SZ, "RemoteSigned")
        winreg.CloseKey(key)
        print("[OK] Registry modified successfully: ExecutionPolicy = RemoteSigned")
        return True
    except Exception as e:
        print(f"[FAIL] Registry modification failed: {e}")
        return False

def install_deps():
    print(f"\n[INFO] Installing dependencies from: {REQUIREMENTS}")
    print(f"[INFO] Using pip: {PIP_EXE}")
    
    if not os.path.exists(PIP_EXE):
        print(f"[ERROR] pip.exe not found at: {PIP_EXE}")
        return False
    
    if not os.path.exists(REQUIREMENTS):
        print(f"[ERROR] requirements.txt not found at: {REQUIREMENTS}")
        return False
    
    try:
        result = subprocess.run(
            [PIP_EXE, "install", "-r", REQUIREMENTS],
            capture_output=True,
            text=True,
            timeout=600
        )
        print(result.stdout)
        if result.stderr:
            print("[WARN] Stderr output:")
            print(result.stderr)
        
        if result.returncode == 0:
            print("\n[OK] Dependencies installed successfully!")
            return True
        else:
            print(f"\n[FAIL] pip exited with code: {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        print("[FAIL] Installation timed out (10 min limit)")
        return False
    except Exception as e:
        print(f"[FAIL] Installation error: {e}")
        return False

def verify_installation():
    print("\n" + "=" * 50)
    print("Verifying installation...")
    modules = ["numpy", "scipy", "PySide6", "matplotlib", "pandas", "Pillow", "lmfit"]
    for mod in modules:
        try:
            result = subprocess.run(
                [PYTHON_EXE, "-c", f"import {mod}; print({mod}.__version__)"],
                capture_output=True, text=True, timeout=10
            )
            version = result.stdout.strip()
            print(f"  [OK] {mod}: {version}")
        except Exception:
            print(f"  [WARN] {mod}: not importable")
    
    try:
        result = subprocess.run(
            [PYTHON_EXE, "-c", "import pymatgen; print(pymatgen.__version__)"],
            capture_output=True, text=True, timeout=10
        )
        print(f"  [OK] pymatgen: {result.stdout.strip()}")
    except Exception:
        print(f"  [WARN] pymatgen: not importable (may need separate install)")

def main():
    print("=" * 50)
    print("PolyXRD - Dependency Installer")
    print("=" * 50)
    
    print("\n[Step 1] Modifying registry for PowerShell execution policy...")
    reg_ok = modify_registry()
    
    print("\n[Step 2] Installing dependencies...")
    install_ok = install_deps()
    
    if install_ok:
        verify_installation()
    
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Registry modification: {'OK' if reg_ok else 'FAILED'}")
    print(f"  Dependency installation: {'OK' if install_ok else 'FAILED'}")
    print("=" * 50)
    
    return 0 if (reg_ok and install_ok) else 1

if __name__ == "__main__":
    sys.exit(main())