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

    def test_load_rigaku_rint_raw(self):
        """Rigaku RINT-2000 二进制 (.raw, 魔数 FI\\x00\\x00) 解析。

        合成一个最小合法文件: 定长 3162 字节头 (2962 处写轴参数) + 末尾 float32 强度。
        """
        import struct

        start, end, step = 10.0, 12.0, 0.02
        n = int(round((end - start) / step))  # 100
        hdr = bytearray(3162)
        hdr[0:4] = b"FI\x00\x00"
        struct.pack_into("<f", hdr, 2962, start)
        struct.pack_into("<f", hdr, 2966, end)
        struct.pack_into("<f", hdr, 2970, step)
        intensity = np.arange(n, dtype="<f4").astype(float)
        intensity[50] = 9999.0  # 一个峰
        raw = bytes(hdr) + np.asarray(intensity, dtype="<f4").tobytes()

        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
            f.write(raw)
            path = f.name
        try:
            data = DataLoader().load(path)
            assert len(data.two_theta) == n
            assert data.two_theta[0] == pytest.approx(start, abs=1e-3)
            assert data.two_theta[-1] == pytest.approx(start + step * (n - 1), abs=1e-3)
            assert float(data.intensity.max()) == pytest.approx(9999.0)
            assert data.metadata.get("rigaku_raw") is True
            assert data.metadata.get("format") == "raw"
        finally:
            os.unlink(path)

    def test_load_rigaku_rint_raw_real(self):
        """真实 Rigaku RINT 文件 (csuHJW 教学集) 交叉验证: 铜 fcc 峰精确命中。"""
        real = (
            r"D:/Project/XRD/XRData/csuHJW/Data007：铜衍射谱系列.raw"
        )
        if not os.path.exists(real):
            pytest.skip("真实 Rigaku RINT 样本不在本地, 跳过")
        data = DataLoader().load(real)
        # 铜 fcc: 111@43.3 应为最强峰 (全局最大)
        idx_max = int(np.argmax(data.intensity))
        assert data.two_theta[idx_max] == pytest.approx(43.3, abs=0.1)
        # 期望峰位集合 (111/200/220/311/222) 应显著高出本底 (绝对阈值, 不依赖相对强度比)
        peaks_2th = [43.3, 50.4, 74.1, 89.9, 95.1]
        for p in peaks_2th:
            i = int(round((p - data.two_theta[0]) / (data.two_theta[1] - data.two_theta[0])))
            assert data.intensity[i] > 300.0
