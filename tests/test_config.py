"""
配置测试
"""
from pathlib import Path

import pytest

from polyxrd.config import AppConfig, get_config


class TestConfig:
    """应用配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = AppConfig()

        assert config.app_name == "PolyXRD"
        assert config.default_wavelength == 1.5406
        assert config.window_width == 1280
        assert config.window_height == 800

    def test_get_config_singleton(self):
        """测试单例模式"""
        config = get_config()
        assert config is not None
        assert isinstance(config, AppConfig)

    def test_export_dir(self):
        """测试导出目录"""
        config = AppConfig()
        export_dir = config.get_export_dir()
        assert isinstance(export_dir, Path)

    def test_cif_db_path(self):
        """测试CIF数据库路径"""
        config = AppConfig()
        cif_path = config.get_cif_db_path()
        assert isinstance(cif_path, Path)
