"""
数据预处理测试
"""
import numpy as np
import pytest

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.data_preprocessor import DataPreprocessor


class TestDataPreprocessor:
    """数据预处理测试"""

    def _create_test_data(self):
        """创建测试数据"""
        np.random.seed(42)
        two_theta = np.linspace(5, 80, 500)
        intensity = np.zeros_like(two_theta)

        # 添加峰
        for center, amp, sigma in [(28.44, 800, 0.15), (47.30, 600, 0.20)]:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)

        # 添加背景
        background = 50 + 10 * two_theta
        intensity += background

        # 添加噪声
        intensity += np.random.normal(0, 5, len(two_theta))
        intensity = np.maximum(intensity, 0)

        return XRDData(two_theta=two_theta, intensity=intensity)

    def test_snip_background(self):
        """测试SNIP背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="snip")
        assert result.method == "snip"
        assert len(result.background) == len(data.intensity)
        assert len(result.corrected.intensity) == len(data.intensity)

        # 校正后强度应小于原始强度
        assert np.max(result.corrected.intensity) <= np.max(data.intensity)

    def test_als_background(self):
        """测试ALS背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="als")
        assert result.method == "als"

    def test_polyfit_background(self):
        """测试多项式拟合背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="polyfit", degree=4)
        assert result.method == "polyfit"

    def test_median_background(self):
        """测试中值滤波背景扣除"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        result = preprocessor.subtract_background(data, method="median")
        assert result.method == "median"

    def test_savgol_smooth(self):
        """测试Savitzky-Golay平滑"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="savgol", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_gaussian_smooth(self):
        """测试高斯平滑"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="gaussian", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_moving_average_smooth(self):
        """测试移动平均"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="moving", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_median_smooth(self):
        """测试中值平滑"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        smoothed = preprocessor.smooth(data, method="median", window=11)
        assert len(smoothed.intensity) == len(data.intensity)

    def test_invalid_method_raises(self):
        """测试无效方法"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        with pytest.raises(ValueError):
            preprocessor.subtract_background(data, method="invalid_method")

    def test_ka2_strip(self):
        """测试Kα2剥离"""
        data = self._create_test_data()
        preprocessor = DataPreprocessor()

        corrected = preprocessor.strip_ka_alpha2(data)
        assert len(corrected.intensity) == len(data.intensity)


# ─────────────────────────────────────────────────────────────────
# v3.0.1 回归: SNIP / 高斯平滑 / 方法名归一 / Kα2 剥离方向与波长
# ─────────────────────────────────────────────────────────────────

def _flat_bg_with_peak(center=30.0, amp=800.0, bg=100.0, fwhm_sigma=0.08,
                       n=7001):
    tt = np.linspace(20, 45, n)
    y = bg + amp * np.exp(-0.5 * ((tt - center) / fwhm_sigma) ** 2)
    return XRDData(two_theta=tt, intensity=y), int(np.argmin(np.abs(tt - center)))


class TestSnipAndSmoothRegression:
    """P0-2 / P0-3 回归。

    旧实现: SNIP 把"半窗 w"写成了"数值阈值"，峰几乎被整体当背景扣掉
    （实测峰心背景估成 898、扣后峰高仅 17.5 / 真值 800）；高斯平滑核未
    归一（常数谱 100 → 459.21，放大 4.59 倍）。
    """

    def test_snip_recovers_peak_height(self):
        data, i_peak = _flat_bg_with_peak()
        res = DataPreprocessor().subtract_background(data, method="snip")
        # 峰心背景估计必须贴近真实平背景 (100)，不能跟着峰一起抬升
        assert res.background[i_peak] == pytest.approx(100.0, abs=10.0)
        # 扣背景后峰高必须基本保留（旧实现只剩 2.2%）
        assert res.corrected.intensity[i_peak] >= 0.9 * 800.0

    def test_snip_flat_background_not_distorted(self):
        tt = np.linspace(20, 45, 2001)
        data = XRDData(two_theta=tt, intensity=np.full_like(tt, 250.0))
        res = DataPreprocessor().subtract_background(data, method="snip")
        assert np.allclose(res.background, 250.0, rtol=1e-3)
        assert np.allclose(res.corrected.intensity, 0.0, atol=1.0)

    @pytest.mark.parametrize("window", [5, 11, 21, 51])
    def test_gaussian_smooth_conserves_amplitude(self, window):
        tt = np.linspace(20, 45, 2001)
        data = XRDData(two_theta=tt, intensity=np.full_like(tt, 100.0))
        out = DataPreprocessor().smooth(data, method="gaussian", window=window)
        # 核必须归一: 常数谱平滑后仍是常数（旧实现放大 4.59 倍）
        assert np.allclose(out.intensity, 100.0, rtol=1e-6)

    def test_gaussian_smooth_uses_window_not_spectrum_length(self):
        # 同一窗口在不同长度谱上必须给出等价结果（旧实现用 len(intensity)
        # 当核长，谱越长核越宽 → 结果随采样点数漂移）
        a = DataPreprocessor().smooth(
            XRDData(two_theta=np.linspace(20, 45, 501),
                    intensity=np.full_like(np.linspace(20, 45, 501), 60.0)),
            method="gaussian", window=11)
        b = DataPreprocessor().smooth(
            XRDData(two_theta=np.linspace(20, 45, 5001),
                    intensity=np.full_like(np.linspace(20, 45, 5001), 60.0)),
            method="gaussian", window=11)
        assert a.intensity[250] == pytest.approx(60.0, rel=1e-6)
        assert b.intensity[2500] == pytest.approx(60.0, rel=1e-6)


class TestMethodNameNormalization:
    """P0-1 服务层侧回归: 方法名大小写/空白/译文都能落到 key。

    界面侧还有单独一层（下拉框 userData 存 key），见 main_window 的
    ``_BG_COMBO_ITEMS`` / ``_combo_value``。
    """

    @pytest.mark.parametrize("alias,expected",
                             [("snip", "snip"), (" SNIP ", "snip"),
                              ("Snip", "snip"), ("als", "als"),
                              ("Polyfit", "polyfit")])
    def test_background_alias_accepted(self, alias, expected):
        data, _ = _flat_bg_with_peak()
        res = DataPreprocessor().subtract_background(data, method=alias)
        assert res.method == expected

    @pytest.mark.parametrize("alias,expected",
                             [("gaussian", "gaussian"), (" Gaussian ", "gaussian"),
                              ("Moving", "moving"), ("Savgol", "savgol")])
    def test_smooth_alias_accepted(self, alias, expected):
        data, _ = _flat_bg_with_peak()
        out = DataPreprocessor().smooth(data, method=alias, window=11)
        assert out.metadata.get("smooth_method") == expected

    def test_error_message_lists_options(self):
        data, _ = _flat_bg_with_peak()
        with pytest.raises(ValueError) as ei:
            DataPreprocessor().subtract_background(data, method="nope")
        assert "snip" in str(ei.value)

    def test_none_method_falls_back(self):
        # None / "" → 回落默认值，不应抛错
        data, _ = _flat_bg_with_peak()
        DataPreprocessor().subtract_background(data, method=None)


class TestKa2StripRegression:
    """P0-5 回归: 剥离方向 + 输出波长。

    实测口径: 固定 d=3.1355 Å (Si 111)、峰宽 0.004° 的合成双线。
    旧实现把 d 当"α1 峰的 d"再**正算** α2 位置（查 x+Δ），方向相反 ——
    卫星峰 520 只降到 824/1020 量级，主峰肩部被削出 −27.5%·Imax 的负坑
    （自带 1% 自检会直接判定"不是双线"而放弃剥离）。
    """

    D_TRUE = 3.1355

    @staticmethod
    def _doublet(lam1, ratio=0.5, amp=1000.0, bg=20.0, w=0.004):
        lam2 = lam1 * 1.00249
        p1 = 2.0 * np.degrees(np.arcsin(lam1 / (2 * TestKa2StripRegression.D_TRUE)))
        p2 = 2.0 * np.degrees(np.arcsin(lam2 / (2 * TestKa2StripRegression.D_TRUE)))
        tt = np.linspace(p1 - 3, p2 + 3, 20001)
        g = lambda c, a: a * np.exp(-0.5 * ((tt - c) / w) ** 2)  # noqa: E731
        return XRDData(two_theta=tt, intensity=g(p1, amp) + g(p2, ratio * amp) + bg,
                       wavelength=lam1), \
            int(np.argmin(np.abs(tt - p1))), int(np.argmin(np.abs(tt - p2)))

    @pytest.mark.parametrize("lam1", [1.5406, 1.78897, 1.93604, 0.7093])
    def test_satellite_removed_main_peak_kept(self, lam1):
        data, i_main, i_sat = self._doublet(lam1)
        out = DataPreprocessor().strip_ka_alpha2(data)
        assert out.metadata.get("ka2_stripped") is True
        # 卫星峰 (520+20) 应降到背景量级
        assert out.intensity[i_sat] <= 40.0
        # 主峰基本守恒 (允许 3% 因双线重叠损失)
        assert out.intensity[i_main] >= 0.97 * 1020.0
        # 不应出现负强度
        assert out.intensity.min() >= 0.0

    def test_output_wavelength_follows_input(self):
        """结果必须保留输入波长，不能被写死成 Cu。"""
        for lam1 in (1.78897, 1.93604, 0.7093):
            data, _, _ = self._doublet(lam1)
            out = DataPreprocessor().strip_ka_alpha2(data)
            assert out.wavelength == pytest.approx(lam1)
            assert out.metadata["ka2_alpha1"] == pytest.approx(lam1)

    def test_skip_when_ratio_mismatch(self):
        """伴线过弱 (非 0.5 双线模型) → 不剥离、原样返回并标记。"""
        data, _, _ = self._doublet(1.5406, ratio=0.02)
        out = DataPreprocessor().strip_ka_alpha2(data, ratio=0.5)
        assert out.metadata.get("ka2_stripped") is False
        assert "ka2_skipped" in out.metadata
        assert np.allclose(out.intensity, data.intensity)

    def test_skip_can_be_disabled(self):
        data, _, _ = self._doublet(1.5406, ratio=0.02)
        out = DataPreprocessor().strip_ka_alpha2(
            data, ratio=0.5, skip_on_mismatch=False)
        assert out.metadata.get("ka2_stripped") is True
        assert out.intensity.min() >= 0.0   # 仍被 np.maximum(raw, 0) 夹住
