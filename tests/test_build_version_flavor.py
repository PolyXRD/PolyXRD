"""VERSION.txt 的 flavor 文案（P2-6）。

背景：``write_version`` 曾硬编码 ``PolyXRD v{ver} Release``，internal 变体
（发给评估方的便携包）里的 VERSION.txt 也自称 "Release"，与实际构建变体
矛盾 —— 用户排障时容易把内部评估版当正式版。v4.5.0 发布时发现，因"不在
发版前改已验证产物"而未动。现在按 ``POLYXRD_FLAVOR``（build.bat 第 35 行
已设）/ 显式参数写正确文案。

注意：门禁 ``verify_release.ps1 -CheckDistVersion`` 只比对版本号，不会因为
文案错而失败 —— 所以这条只能靠单元测试守。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_build_post():
    spec = importlib.util.spec_from_file_location(
        "_bp_flavor", ROOT / "scripts" / "_build_post.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    m = _load_build_post()
    monkeypatch.setattr(m, "DIST", str(tmp_path / "dist"))
    # installer_output 副本也要隔离（否则会往仓库里写文件）
    monkeypatch.setattr(m.os.path, "isdir",
                        lambda p: False if p == "installer_output"
                        else __import__("os").path.isdir(p))
    monkeypatch.delenv("POLYXRD_FLAVOR", raising=False)
    return m


def _first_line(dist: Path) -> str:
    return (dist / "VERSION.txt").read_text(encoding="utf-8").splitlines()[0]


class TestFlavorLabel:
    def test_release_says_release(self, mod, tmp_path):
        assert mod.write_version("5.2.0", "release") == 0
        assert _first_line(tmp_path / "dist") == "PolyXRD v5.2.0 Release"

    def test_internal_says_internal_evaluation(self, mod, tmp_path):
        assert mod.write_version("5.2.0", "internal") == 0
        line = _first_line(tmp_path / "dist")
        assert line == "PolyXRD v5.2.0 Internal Evaluation"
        assert "Release" not in line

    def test_env_var_is_picked_up(self, mod, tmp_path, monkeypatch):
        """build.bat 只传版本号，flavor 靠环境变量 —— 这条是实际构建路径。"""
        monkeypatch.setenv("POLYXRD_FLAVOR", "internal")
        mod.write_version("5.2.0")
        assert "Internal Evaluation" in _first_line(tmp_path / "dist")

    def test_explicit_arg_beats_env(self, mod, tmp_path, monkeypatch):
        monkeypatch.setenv("POLYXRD_FLAVOR", "internal")
        mod.write_version("5.2.0", "release")
        assert _first_line(tmp_path / "dist").endswith("Release")

    def test_unknown_flavor_is_not_silently_release(self, mod, tmp_path):
        """未知值不得回落成 "Release"（那正是本 bug 的形态）。"""
        mod.write_version("5.2.0", "beta3")
        line = _first_line(tmp_path / "dist")
        assert "BETA3" in line
        assert "Release" not in line

    def test_flavor_field_present(self, mod, tmp_path):
        """显式 Flavor 行便于排障时一眼看出变体。"""
        mod.write_version("5.2.0", "internal")
        text = (tmp_path / "dist" / "VERSION.txt").read_text(encoding="utf-8")
        assert "Version    : 5.2.0" in text
        assert "Flavor     : internal" in text


class TestCommandLine:
    def test_main_version_with_flavor_arg(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["_build_post.py", "version", "5.2.0", "internal"])
        assert mod.main() == 0
        assert "Internal Evaluation" in _first_line(tmp_path / "dist")

    def test_main_version_without_flavor_uses_env(self, mod, tmp_path,
                                                 monkeypatch):
        monkeypatch.setenv("POLYXRD_FLAVOR", "internal")
        monkeypatch.setattr(sys, "argv", ["_build_post.py", "version", "5.2.0"])
        assert mod.main() == 0
        assert "Internal Evaluation" in _first_line(tmp_path / "dist")

    def test_main_version_requires_ver(self, mod, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["_build_post.py", "version"])
        assert mod.main() == 2
