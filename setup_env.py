#!/usr/bin/env python3
"""
PolyXRD 环境设置脚本
====================
自动检测 Python 环境、创建虚拟环境、安装依赖、验证安装。
"""

import os
import sys
import subprocess
import venv
from pathlib import Path


def check_python_version():
    """检查 Python 版本"""
    version = sys.version_info
    print(f"[信息] 当前 Python 版本: {version.major}.{version.minor}.{version.micro}")
    if version < (3, 11):
        print("[警告] 建议使用 Python 3.11+，当前版本可能不兼容")
        return False
    return True


def create_virtual_env(project_dir: Path):
    """创建虚拟环境"""
    venv_dir = project_dir / "venv"
    if venv_dir.exists() and (venv_dir / "Scripts" / "python.exe").exists():
        print(f"[信息] 虚拟环境已存在: {venv_dir}")
        return venv_dir
    
    print(f"[信息] 创建虚拟环境: {venv_dir}")
    venv.create(str(venv_dir), with_pip=True, clear=False)
    print("[完成] 虚拟环境创建成功")
    return venv_dir


def get_venv_python(venv_dir: Path) -> str:
    """获取虚拟环境中的 Python 路径"""
    if sys.platform == "win32":
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")


def get_venv_pip(venv_dir: Path) -> str:
    """获取虚拟环境中的 pip 路径"""
    if sys.platform == "win32":
        return str(venv_dir / "Scripts" / "pip.exe")
    return str(venv_dir / "bin" / "pip")


def run_command(cmd: list, cwd: Path = None):
    """运行命令"""
    print(f"[执行] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(f"[警告] {result.stderr.strip()}")
    if result.returncode != 0:
        print(f"[错误] 命令执行失败 (返回码: {result.returncode})")
        return False
    return True


def upgrade_pip(venv_dir: Path):
    """升级 pip"""
    print("[信息] 升级 pip...")
    pip_path = get_venv_pip(venv_dir)
    python_path = get_venv_python(venv_dir)
    return run_command([python_path, "-m", "pip", "install", "--upgrade", "pip"])


def install_dependencies(venv_dir: Path, project_dir: Path):
    """安装项目依赖"""
    python_path = get_venv_python(venv_dir)
    pip_path = get_venv_pip(venv_dir)
    
    # 先安装核心依赖
    print("[信息] 安装核心依赖...")
    core_reqs = [
        "numpy>=1.24",
        "scipy>=1.10",
        "matplotlib>=3.7",
        "pandas>=2.0.0",
        "Pillow>=9.0.0",
        "platformdirs>=3.0.0",
    ]
    for req in core_reqs:
        run_command([pip_path, "install", req])
    
    # 安装 PySide6 (GUI)
    print("[信息] 安装 PySide6 (GUI框架)...")
    run_command([pip_path, "install", "PySide6>=6.5"])
    
    # 安装科学计算依赖
    print("[信息] 安装科学计算依赖...")
    science_reqs = [
        "pymatgen>=2024.1.1",
        "lmfit>=1.3",
        "powerxrd>=1.0",
    ]
    for req in science_reqs:
        print(f"[信息] 尝试安装 {req}...")
        success = run_command([pip_path, "install", req])
        if not success:
            print(f"[警告] {req} 安装失败，将使用内置替代方案")
    
    # 安装 GSAS-II (可选，用于 Rietveld 精修)
    print("[信息] 尝试安装 GSAS-II...")
    gsas2_success = run_command([pip_path, "install", "GSAS-II>=5.0"])
    if not gsas2_success:
        print("[警告] GSAS-II 安装失败。")
        print("  GSAS-II 需要从源安装: https://gsas-ii.readthedocs.io/")
        print("  软件将使用内置的简化 Rietveld 引擎作为替代")
    
    # 安装 pyqtgraph (可选)
    print("[信息] 安装 pyqtgraph...")
    run_command([pip_path, "install", "pyqtgraph>=0.13.0"])
    
    # 安装项目本身 (开发模式)
    print("[信息] 安装 PolyXRD (开发模式)...")
    run_command([pip_path, "install", "-e", str(project_dir)])
    
    # 安装测试依赖
    print("[信息] 安装测试依赖...")
    run_command([pip_path, "install", "pytest>=7.0", "pytest-cov>=4.0"])


def verify_installation(venv_dir: Path, project_dir: Path):
    """验证安装"""
    python_path = get_venv_python(venv_dir)
    
    print("\n" + "=" * 50)
    print("  验证安装")
    print("=" * 50)
    
    # 验证核心模块
    modules_to_check = [
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("matplotlib", "matplotlib"),
        ("pandas", "pandas"),
        ("PySide6", "PySide6"),
        ("pymatgen", "pymatgen"),
        ("lmfit", "lmfit"),
    ]
    
    all_ok = True
    for module_name, import_name in modules_to_check:
        code = f"import {import_name}; print({module_name}.__version__ if hasattr({import_name}, '__version__') else 'OK')"
        result = subprocess.run(
            [python_path, "-c", code],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"  [OK] {module_name}: {version}")
        else:
            print(f"  [失败] {module_name}: {result.stderr.strip()}")
            all_ok = False
    
    # 验证项目模块
    print("\n  [信息] 验证 PolyXRD 模块...")
    sys.path.insert(0, str(project_dir / "src"))
    code = "from polyxrd.models.xrd_data import XRDData; print('PolyXRD 核心模块: OK')"
    result = subprocess.run(
        [python_path, "-c", code],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(project_dir / "src")}
    )
    if result.returncode == 0:
        print(f"  [OK] {result.stdout.strip()}")
    else:
        print(f"  [警告] {result.stderr.strip()}")
        all_ok = False
    
    # 验证可选模块
    optional_modules = [
        ("powerxrd", "powerxrd"),
        ("GSAS-II", "GSASII"),
        ("pyqtgraph", "pyqtgraph"),
    ]
    for module_name, import_name in optional_modules:
        code = f"import {import_name}"
        result = subprocess.run(
            [python_path, "-c", code],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"  [OK] {module_name}: 已安装")
        else:
            print(f"  [--] {module_name}: 未安装 (可选)")
    
    return all_ok


def main():
    """主函数"""
    print("=" * 50)
    print("  PolyXRD 环境设置")
    print("=" * 50)
    print()
    
    # 获取项目目录
    project_dir = Path(__file__).parent.resolve()
    print(f"[信息] 项目目录: {project_dir}")
    
    # 检查 Python 版本
    if not check_python_version():
        input("按 Enter 键继续...")
    
    # 创建虚拟环境
    venv_dir = create_virtual_env(project_dir)
    
    # 升级 pip
    if not upgrade_pip(venv_dir):
        print("[警告] pip 升级失败，继续安装...")
    
    # 安装依赖
    install_dependencies(venv_dir, project_dir)
    
    # 验证安装
    success = verify_installation(venv_dir, project_dir)
    
    print("\n" + "=" * 50)
    if success:
        print("  环境设置完成！")
    else:
        print("  环境设置部分完成（某些可选依赖未安装）")
    
    print("\n  运行应用:")
    print(f"    {get_venv_python(venv_dir)} -m polyxrd.main")
    print(f"\n  运行测试:")
    print(f"    {get_venv_python(venv_dir)} -m pytest tests/ -v")
    print("=" * 50)


if __name__ == "__main__":
    main()
