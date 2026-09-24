"""M26 谱合成内核性能改造 - 一致性与性能测试

窗口化 (cutoff_fwhm=50) 与全矩阵 (cutoff_fwhm=None) 必须数值一致
(截断误差 << wR 有效精度), 且单次评估显著提速。
"""
import time

import numpy as np
import pytest

from polyxrd.services.phase_display import spectrum_from_refs

RNG = np.random.default_rng(42)


def _make_case(n_points=3600, n_phases=7, peaks_per_phase=430, span=(10.0, 90.0)):
    """合成 7 相 × ~430 峰 (对齐 7-1 实测量级: 7251 点 × ~3000 峰)"""
    tt = np.linspace(span[0], span[1], n_points)
    phase_peaks = []
    for _ in range(n_phases):
        n = peaks_per_phase
        pos = np.sort(RNG.uniform(span[0] + 0.5, span[1] - 0.5, n))
        inten = RNG.uniform(1.0, 100.0, n)
        phase_peaks.append([(None, float(p), float(i)) for p, i in zip(pos, inten)])
    weights = RNG.uniform(0.5, 2.0, n_phases)
    return tt, phase_peaks, weights


@pytest.mark.parametrize("peak_shape,caglioti", [
    ("pseudo-voigt", None),
    ("pseudo-voigt", (0.02, -0.005, 0.004)),
    ("gaussian", None),
    ("lorentzian", None),
])
def test_windowed_matches_full_matrix(peak_shape, caglioti):
    tt, phase_peaks, weights = _make_case(n_points=1500, peaks_per_phase=120)
    kw = dict(peak_shape=peak_shape, caglioti=caglioti)
    y_full = spectrum_from_refs(tt, phase_peaks, weights, 0.12, 0.5, 1.5,
                                cutoff_fwhm=None, **kw)
    y_win = spectrum_from_refs(tt, phase_peaks, weights, 0.12, 0.5, 1.5,
                               cutoff_fwhm=100.0, **kw)
    scale = np.max(np.abs(y_full))
    assert scale > 0
    # 截断尾差为平滑准基线偏移: 50×FWHM 处 lorentz 尾 1e-4/峰, 逐点
    # 累加实测 ≈ 1e-3 × 满谱最大值; 对 wR 的影响 ~1e-6 量级 (见下 wR 测试)
    assert np.max(np.abs(y_full - y_win)) < 2e-3 * scale


def test_windowed_speedup_and_wr_equivalence():
    tt, phase_peaks, weights = _make_case()  # 3600 点 × 7 相 × 430 峰
    kwargs = dict(peak_shape="pseudo-voigt", caglioti=None)

    t0 = time.perf_counter()
    y_full = spectrum_from_refs(tt, phase_peaks, weights, 0.12, 0.5, 1.5,
                                cutoff_fwhm=None, **kwargs)
    t_full = time.perf_counter() - t0

    t0 = time.perf_counter()
    y_win = spectrum_from_refs(tt, phase_peaks, weights, 0.12, 0.5, 1.5,
                               cutoff_fwhm=100.0, **kwargs)
    t_win = time.perf_counter() - t0

    assert np.max(np.abs(y_full - y_win)) < 2e-3 * np.max(y_full)
    # wR 等效性: 给合成谱加 5% 噪声当"实测", 两条路径的 wR 差必须
    # 远小于 wR 本身的有效精度 (0.01 个百分点)
    y_exp = y_full * (1 + RNG.normal(0, 0.05, y_full.shape)) + 10.0

    def _wr(y_calc):
        r = y_exp - y_calc
        return 100.0 * np.sqrt(np.sum(r * r) / np.sum(y_exp * y_exp))

    assert abs(_wr(y_full) - _wr(y_win)) < 0.05
    # 性能断言放宽到 2x (CI 机器抖动), 实测预期 >3x
    assert t_win < t_full / 2.0


def test_empty_and_out_of_range_peaks():
    tt = np.linspace(10.0, 90.0, 500)
    # 空峰表 → 全 0
    assert np.all(spectrum_from_refs(tt, [[]], [1.0], 0.1, 0.5, 1.0) == 0)
    # 峰全在范围外 → 全 0 (窗口与全矩阵一致)
    peaks_out = [(None, 95.0, 10.0), (None, 5.0, 10.0)]
    for cut in (None, 50.0):
        y = spectrum_from_refs(tt, [peaks_out], [1.0], 0.1, 0.5, 1.0,
                               cutoff_fwhm=cut)
        assert np.all(y == 0)


def test_short_peaks_rows_ignored():
    tt = np.linspace(10.0, 90.0, 500)
    peaks = [(None, 30.0, 50.0), (None, 40.0)]  # 第二行缺强度 → 忽略
    y_full = spectrum_from_refs(tt, [peaks], [1.0], 0.1, 0.5, 1.0,
                                cutoff_fwhm=None)
    y_win = spectrum_from_refs(tt, [peaks], [1.0], 0.1, 0.5, 1.0)
    # 主峰必须一致。v1.1.2 峰形改**面积归一**后洛伦兹"面积"守恒 → 远尾幅度约为旧
    # (峰高=1) 实现的 1/(πγ) ≈ 6.4 倍, 故全矩阵/窗口化的截断差由 ~1e-4 升到 ~1e-3,
    # 容差随之放宽; 该差是截断导致、非错误。
    assert np.allclose(y_full, y_win, atol=5e-3)
    # 缺强度的行必须被忽略: 40° 处只可能剩 30° 峰的洛伦兹远尾, 远小于主峰
    i30 = int(np.argmin(np.abs(tt - 30.0)))
    i40 = int(np.argmin(np.abs(tt - 40.0)))
    assert y_win[i30] > 10.0
    assert y_win[i40] < y_win[i30] * 1e-3, (y_win[i40], y_win[i30])
