"""
PolyXRD 自动打包脚本
==================
检查环境、安装依赖、运行测试、打包为独立可执行文件。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class Colors:
    """终端颜色输出"""
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


def print_header(msg: str) -> None:
    print(f"\n{Colors.HEADER}{'=' * 50}{Colors.ENDC}")
    print(f"{Colors.HEADER}{msg}{Colors.ENDC}")
    print(f"{Colors.HEADER}{'=' * 50}{Colors.ENDC}\n")


def print_ok(msg: str) -> None:
    print(f"{Colors.OKGREEN}[OK]{Colors.ENDC} {msg}")


def print_warn(msg: str) -> None:
    print(f"{Colors.WARNING}[WARN]{Colors.ENDC} {msg}")


def print_error(msg: str) -> None:
    print(f"{Colors.FAIL}[ERROR]{Colors.ENDC} {msg}")


def print_info(msg: str) -> None:
    print(f"{Colors.OKBLUE}[INFO]{Colors.ENDC} {msg}")


def run_cmd(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """运行命令"""
    print_info(f"执行: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=False,
        text=True,
    )
    if result.returncode != 0:
        if check:
            print_error(f"命令失败 (退出码: {result.returncode})")
        else:
            print_warn(f"命令返回非零退出码: {result.returncode}")
    return result


def main() -> int:
    project_dir = Path(__file__).parent.resolve()
    os.chdir(project_dir)

    print_header("PolyXRD 自动打包脚本")
    print(f"项目目录: {project_dir}")

    # ------------------------------------------------------------------
    # Step 1: 检查 Python 环境
    # ------------------------------------------------------------------
    print_header("Step 1: 检查 Python 环境")

    print_info(f"Python 版本: {sys.version}")
    if sys.version_info < (3, 10):
        print_error("需要 Python 3.10+ 版本")
        return 1
    print_ok("Python 版本符合要求")

    # ------------------------------------------------------------------
    # Step 2: 创建虚拟环境 (如果不存在)
    # ------------------------------------------------------------------
    print_header("Step 2: 检查/创建虚拟环境")

    venv_dir = project_dir / "venv"
    venv_python = venv_dir / "Scripts" / "python.exe"

    if not venv_python.exists():
        print_info("创建虚拟环境 (使用 virtualenv)...")
        result = run_cmd([sys.executable, "-m", "virtualenv", "venv"], cwd=project_dir)
        if not venv_python.exists():
            # 尝试使用 venv 模块
            print_info("尝试使用 venv 模块...")
            result = run_cmd([sys.executable, "-c", "import venv; venv.EnvBuilder().create('venv')"], cwd=project_dir)
            if not venv_python.exists():
                print_error("虚拟环境创建失败")
                return 1
        print_ok("虚拟环境创建成功")
    else:
        print_ok("虚拟环境已存在")

    # ------------------------------------------------------------------
    # Step 3: 安装依赖
    # ------------------------------------------------------------------
    print_header("Step 3: 安装项目依赖")

    # 先升级 pip
    run_cmd([str(venv_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    # 安装项目和依赖
    requirements_file = project_dir / "requirements.txt"
    if requirements_file.exists():
        print_info("安装 requirements.txt 中的依赖...")
        run_cmd([str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"], cwd=project_dir)
    else:
        print_warn("requirements.txt 不存在，手动安装核心依赖...")
        deps = [
            "numpy>=1.24",
            "scipy>=1.10",
            "pandas>=2.0",
            "matplotlib>=3.7",
            "PySide6>=6.5",
            "pymatgen>=2024.1.26",
            "lmfit>=1.3",
        ]
        for dep in deps:
            run_cmd([str(venv_python), "-m", "pip", "install", dep])

    # 安装项目本身 (editable mode)
    pyproject_file = project_dir / "pyproject.toml"
    if pyproject_file.exists():
        run_cmd([str(venv_python), "-m", "pip", "install", "-e", "."], cwd=project_dir)
    else:
        print_warn("pyproject.toml 不存在")

    # 安装 PyInstaller
    run_cmd([str(venv_python), "-m", "pip", "install", "pyinstaller>=6.0"])

    print_ok("依赖安装完成")

    # ------------------------------------------------------------------
    # Step 4: 运行单元测试
    # ------------------------------------------------------------------
    print_header("Step 4: 运行单元测试")

    tests_dir = project_dir / "tests"
    if tests_dir.exists():
        result = run_cmd(
            [str(venv_python), "-m", "pytest", "tests/", "-v", "--tb=short"],
            cwd=project_dir,
            check=False,
        )
        if result.returncode == 0:
            print_ok("所有测试通过！")
        else:
            print_warn("部分测试失败，但继续打包流程...")
    else:
        print_warn("tests 目录不存在，跳过测试")

    # ------------------------------------------------------------------
    # Step 5: 生成测试数据
    # ------------------------------------------------------------------
    print_header("Step 5: 生成测试数据")

    test_data_dir = project_dir / "test_data"
    test_data_dir.mkdir(exist_ok=True)

    generator = project_dir / "generate_test_data.py"
    if generator.exists():
        run_cmd([str(venv_python), str(generator)], cwd=project_dir, check=False)
    else:
        print_warn("测试数据生成器不存在")

    # ------------------------------------------------------------------
    # Step 6: 清理旧的构建
    # ------------------------------------------------------------------
    print_header("Step 6: 清理旧的构建产物")

    for dir_name in ["build", "dist"]:
        dir_path = project_dir / dir_name
        if dir_path.exists():
            shutil.rmtree(dir_path, ignore_errors=True)
            print_info(f"已删除: {dir_name}/")

    spec_file = project_dir / "PolyXRD.spec"
    if spec_file.exists():
        spec_file.unlink()
        print_info("已删除: PolyXRD.spec")

    # ------------------------------------------------------------------
    # Step 7: PyInstaller 打包
    # ------------------------------------------------------------------
    print_header("Step 7: PyInstaller 打包")

    pyinstaller_cmd = [
        str(venv_python),
        "-m", "PyInstaller",
        "--name", "PolyXRD",
        "--windowed",
        "--noconfirm",
        "--collect-all", "PySide6",
        "--collect-all", "matplotlib",
        "--collect-all", "pymatgen",
        "--collect-all", "lmfit",
        "--collect-all", "scipy",
        "--collect-all", "numpy",
        "--collect-all", "pandas",
        "--hidden-import", "polyxrd",
        "--hidden-import", "polyxrd.i18n",
        "--hidden-import", "polyxrd.i18n.translations.zh_CN",
        "--hidden-import", "polyxrd.i18n.translations.en_US",
        "--add-data", "src/polyxrd/i18n;polyxrd/i18n",
        "src/polyxrd/main.py",
    ]

    result = run_cmd(pyinstaller_cmd, cwd=project_dir, check=False)

    if result.returncode != 0:
        print_error("PyInstaller 打包失败！")
        print_error("请检查上方输出日志")
        return 1

    # ------------------------------------------------------------------
    # Step 8: 验证打包结果
    # ------------------------------------------------------------------
    print_header("Step 8: 验证打包结果")

    exe_path = project_dir / "dist" / "PolyXRD" / "PolyXRD.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print_ok(f"可执行文件已生成: {exe_path}")
        print_ok(f"文件大小: {size_mb:.1f} MB")

        # 列出 dist 目录内容
        dist_dir = project_dir / "dist" / "PolyXRD"
        file_count = len(list(dist_dir.rglob("*")))
        print_info(f"打包文件总数: {file_count}")
    else:
        print_error("未找到生成的可执行文件！")
        print_error(f"请检查 dist/PolyXRD/ 目录")
        return 1

    # ------------------------------------------------------------------
    # 完成
    # ------------------------------------------------------------------
    print_header("🎉 PolyXRD 打包完成！")
    print(f"""
  输出目录: {project_dir / 'dist' / 'PolyXRD'}
  可执行文件: {exe_path}

  使用说明:
  1. 将 dist/PolyXRD 整个文件夹复制到目标电脑
  2. 双击 PolyXRD.exe 即可运行
  3. 无需安装 Python 或其他依赖

  如需单文件安装包，可使用 Inno Setup 或类似工具将 dist/PolyXRD 目录打包为安装程序。
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
