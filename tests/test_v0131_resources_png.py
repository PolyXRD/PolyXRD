"""v0.13.1 启动图/窗口图标 PNG 优先 (不加载 imageformats 插件) 的契约测试。

背景 (2026-09-17 启动崩溃排查): 打包版/源码模式在真实显示环境下,
``window.show()`` 阶段原生崩溃 (abort / access violation)。分层定位结论:

- QApplication + MainWindow + show (不碰任何图片)      -> 3/3 干净
- 叠加 QIcon('app-icon.ico')   (加载 qico.dll 插件)     -> 1/3 干净
- 叠加 QPixmap('splash-screen.jpg') (加载 qjpeg.dll)    -> 1/3 干净
- v0.11.0 源码/安装包同样代码 -> 干净 (回归自 v0.12/v0.13 引入)

Qt6 的 PNG 解码器**内建**于 Qt6Gui, 取 PNG 不加载任何 imageformats 插件
(实测: none=0 个插件, png=0, jpg=2 个 qjpeg, ico=2 个 qico)。故运行时的
窗口图标与启动画面一律优先走 PNG; .ico 仅留给 exe 资源 / 安装器 (不经过
Qt 运行时)。本测试守住"解析顺序必须 PNG 优先"这一契约。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polyxrd.utils import resources


@pytest.fixture()
def fake_resources(tmp_path, monkeypatch):
    """把 get_resource_path 指到临时目录, 返回该目录。"""

    def _fake(relative_path: str) -> Path:
        return tmp_path / "polyxrd" / "resources" / relative_path

    monkeypatch.setattr(resources, "get_resource_path", _fake)
    return tmp_path / "polyxrd" / "resources"


def _touch(base: Path, name: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    p = base / name
    p.write_bytes(b"x")
    return p


class TestAppIconPrefersPng:
    def test_prefers_png_when_both_exist(self, fake_resources):
        _touch(fake_resources, "app-icon.png")
        _touch(fake_resources, "app-icon.ico")
        assert resources.get_app_icon_path().endswith("app-icon.png")

    def test_falls_back_to_ico(self, fake_resources):
        _touch(fake_resources, "app-icon.ico")
        assert resources.get_app_icon_path().endswith("app-icon.ico")

    def test_empty_when_nothing_exists(self, fake_resources):
        assert resources.get_app_icon_path() == ""


class TestSplashPrefersPng:
    def test_prefers_png_when_both_exist(self, fake_resources):
        _touch(fake_resources, "splash-screen.png")
        _touch(fake_resources, "splash-screen.jpg")
        assert resources.get_splash_screen_path().endswith("splash-screen.png")

    def test_falls_back_to_jpg(self, fake_resources):
        _touch(fake_resources, "splash-screen.jpg")
        assert resources.get_splash_screen_path().endswith("splash-screen.jpg")

    def test_empty_when_nothing_exists(self, fake_resources):
        assert resources.get_splash_screen_path() == ""


class TestShippedAssets:
    """仓库里实际随包的资源必须满足启动路径的假设。"""

    def test_splash_png_exists_and_pre_scaled(self):
        """启动图 PNG 必须存在, 且已按 480x270 预缩放 (启动期免重采样)。"""
        p = resources.get_resource_path("splash-screen.png")
        assert p.exists(), f"缺少 {p}"
        from PIL import Image

        with Image.open(p) as im:
            assert im.size == (480, 270)

    def test_app_icon_png_exists(self):
        p = resources.get_resource_path("app-icon.png")
        assert p.exists(), f"缺少 {p}"

    def test_splash_jpg_still_shipped_as_fallback(self):
        p = resources.get_resource_path("splash-screen.jpg")
        assert p.exists(), f"缺少 {p}"

    def test_ico_still_shipped_for_installer(self):
        """ico 仍要存在: PolyXRD.spec 的 icon= 与 Setup.iss 的 SetupIconFile 用它。"""
        p = resources.get_resource_path("app-icon.ico")
        assert p.exists(), f"缺少 {p}"
