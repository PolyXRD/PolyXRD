"""
数据加载器测试
"""
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from polyxrd.services.data_loader import DataLoader, save_xy


class TestDataLoader:
    """数据加载器测试"""

    def test_load_xy_file(self):
        """测试加载XY格式文件"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xy", delete=False
        ) as f:
            for two_theta in np.linspace(5, 80, 100):
                intensity = 100 * np.sin(np.radians(two_theta)) + 50
                f.write(f"{two_theta:.6f}\t{intensity:.4f}\n")
            temp_path = f.name

        try:
            loader = DataLoader()
            data = loader.load(temp_path)

            assert len(data) == 100
            assert data.wavelength == 1.5406
            assert data.two_theta[0] == pytest.approx(5.0, rel=0.01)
        finally:
            os.unlink(temp_path)

    def test_load_csv_file(self):
        """测试加载CSV格式文件"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("2theta,intensity\n")
            for two_theta in np.linspace(5, 80, 50):
                intensity = np.random.rand() * 1000
                f.write(f"{two_theta:.4f},{intensity:.2f}\n")
            temp_path = f.name

        try:
            loader = DataLoader()
            data = loader.load(temp_path)

            assert len(data) == 50
            assert data.metadata["format"] == "csv"
        finally:
            os.unlink(temp_path)

    def test_load_with_custom_wavelength(self):
        """测试自定义波长"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xy", delete=False
        ) as f:
            for two_theta in np.linspace(5, 80, 30):
                intensity = np.random.rand() * 1000
                f.write(f"{two_theta:.6f}\t{intensity:.4f}\n")
            temp_path = f.name

        try:
            loader = DataLoader()
            data = loader.load(temp_path, wavelength=1.7902)  # Mo Kα

            assert data.wavelength == 1.7902
        finally:
            os.unlink(temp_path)

    def test_file_not_found(self):
        """测试文件不存在"""
        loader = DataLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("/nonexistent/file.xy")

    def test_save_xy(self):
        """测试保存XY格式"""
        from polyxrd.models.xrd_data import XRDData

        two_theta = np.linspace(5, 80, 50)
        intensity = np.random.rand(50) * 1000
        data = XRDData(two_theta=two_theta, intensity=intensity)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xy", delete=False
        ) as f:
            temp_path = f.name

        try:
            save_xy(data, temp_path, fmt="xy")

            # 重新加载验证
            loader = DataLoader()
            loaded = loader.load(temp_path)

            assert len(loaded) == len(data)
            np.testing.assert_array_almost_equal(
                loaded.two_theta, data.two_theta, decimal=4
            )
        finally:
            os.unlink(temp_path)

    def test_save_csv(self):
        """测试保存CSV格式"""
        from polyxrd.models.xrd_data import XRDData

        two_theta = np.linspace(5, 80, 30)
        intensity = np.random.rand(30) * 1000
        data = XRDData(two_theta=two_theta, intensity=intensity)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            temp_path = f.name

        try:
            save_xy(data, temp_path, fmt="csv")

            assert os.path.exists(temp_path)
        finally:
            os.unlink(temp_path)
