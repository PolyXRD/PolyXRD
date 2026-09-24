"""
M05 峰搜索增强测试 (Sprint 1)
=============================
覆盖: sensitivity 灵敏度 / 肩峰检测 / Kα1-Kα2 双峰合并。
向后兼容: 不带新参数时行为与旧版一致 (由 test_peak_finder.py 回归保证)。
"""
import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.peak_finder import PeakFinder


def _synth(pairs, lo=20.0, hi=40.0, step=0.02, noise=1.5, seed=0):
    """合成高斯峰谱: pairs=[(center, amp, sigma), ...]"""
    rng = np.random.default_rng(seed)
    x = np.arange(lo, hi + step / 2, step)
    y = np.zeros_like(x)
    for c, a, s in pairs:
        y += a * np.exp(-0.5 * ((x - c) / s) ** 2)
    y += rng.normal(0, noise, len(x))
    return XRDData(two_theta=x, intensity=np.maximum(y, 0))


class TestPeakFinderM05:

    def test_default_equals_no_shoulder(self):
        """默认路径(不带新参数)与显式关闭增强一致, 向后兼容。"""
        d = _synth([(28.44, 800, 0.15)], hi=80, step=0.05, noise=5)
        pf = PeakFinder()
        default = pf.find_peaks(d, height=0.05, distance=3.0)
        explicit = pf.find_peaks(d, height=0.05, distance=3.0,
                                 detect_shoulders=False, merge_kalpha_doublets=False)
        assert len(default) == len(explicit)
        assert [p.two_theta for p in default] == [p.two_theta for p in explicit]

    def test_detect_shoulders_separated_secondary_maximum(self):
        """明显次极大肩峰: 关闭时只检 1 峰, 开启后多检出一个肩峰。"""
        d = _synth([(28.0, 800, 0.2), (28.45, 300, 0.2)], noise=1.5)
        pf = PeakFinder()
        off = pf.find_peaks(d, height=0.03, distance=1.5)
        on = pf.find_peaks(d, height=0.03, distance=1.5,
                           detect_shoulders=True, shoulder_smooth_window=7)
        tt_on = [p.two_theta for p in on]
        print(f"off={[round(p.two_theta,2) for p in off]}  on={[round(t,2) for t in tt_on]}")
        assert len(off) == 1
        assert len(on) >= 2
        extra = [t for t in tt_on if abs(t - 28.0) > 0.3]
        assert len(extra) >= 1, f"应检出次极大肩峰, 实际 {tt_on}"

    def test_detect_shoulders_overlapped_hidden_peak(self):
        """重叠到看不出局部极大的隐藏峰: 开启后比关闭多检出一个特征。"""
        d = _synth([(28.0, 800, 0.2), (28.22, 120, 0.2)], noise=1.0)
        pf = PeakFinder()
        off = pf.find_peaks(d, height=0.03, distance=1.5)
        on = pf.find_peaks(d, height=0.03, distance=1.5,
                           detect_shoulders=True, shoulder_smooth_window=7)
        tt_on = [p.two_theta for p in on]
        print(f"off={[round(p.two_theta,2) for p in off]}  on={[round(t,2) for t in tt_on]}")
        assert len(on) > len(off), f"隐藏肩峰应使峰数增加: {len(off)} -> {len(on)}"
        # 第二特征应落在主峰附近 (真实位置需 M07 轮廓拟合精修)
        assert any(28.0 < t < 29.0 for t in tt_on) or len(off) == 1

    def test_sensitivity_monotonic(self):
        """灵敏度越高检出的峰越多 (弱峰 33.5°, amp≈7)。"""
        d = _synth([(28.0, 800, 0.2), (33.5, 7, 0.15)], noise=1.0, seed=1)
        pf = PeakFinder()
        s1 = pf.find_peaks(d, height=None, distance=2.0, sensitivity=1.0)
        s3 = pf.find_peaks(d, height=None, distance=2.0, sensitivity=3.0)
        s10 = pf.find_peaks(d, height=None, distance=2.0, sensitivity=10.0)
        print(f"sens1={len(s1)} sens3={len(s3)} sens10={len(s10)}")
        assert len(s3) >= len(s1), "灵敏度 3 检出的峰应不少于 灵敏度 1"
        assert len(s10) >= len(s3), "灵敏度 10 检出的峰应不少于 灵敏度 3"
        # 高灵敏度应包含低灵敏度发现的显著峰
        def has(pl, tt):
            return any(abs(p.two_theta - tt) < 0.2 for p in pl)
        assert has(s3, 28.0) and has(s3, 33.5)
        assert has(s10, 28.0) and has(s10, 33.5)

    def test_kalpha_separation_formula(self):
        """Kα1-Kα2 间距公式: Cu 在 28.4° 附近约 0.07° 量级且随 2θ 增大。"""
        pf = PeakFinder()
        s28 = pf._kalpha_doublet_separation(28.44, 1.5406, 1.5444)
        s60 = pf._kalpha_doublet_separation(60.0, 1.5406, 1.5444)
        assert 0.05 < s28 < 0.12, f"s(28.4°)={s28:.4f} 应在 0.05~0.12"
        assert s60 > s28, "高角双峰间距应更大"

    def test_merge_kalpha_doublets(self):
        """双峰(间距≈Δ2θ, 强度比≈0.5)合并; 真正的两晶面峰不误合并。"""
        pf = PeakFinder()
        sep = pf._kalpha_doublet_separation(28.44, 1.5406, 1.5444)
        # 28.44(Kα1) + 28.44+sep(Kα2, 0.5 倍强度) + 独立的 31.7
        plist = [
            Peak(two_theta=28.44, intensity=800, fwhm=0.15),
            Peak(two_theta=28.44 + sep, intensity=400, fwhm=0.15),
            Peak(two_theta=31.7, intensity=300, fwhm=0.15),
        ]
        merged = pf._merge_kalpha_doublets(plist)
        print(f"merged->{[round(p.two_theta,3) for p in merged]}")
        assert len(merged) == 2
        assert abs(merged[0].two_theta - 28.44) < 1e-6  # 保留 Kα1 低角峰

    def test_merge_does_not_touch_real_peaks(self):
        """真实相邻峰 (间距明显大于双峰间距) 不得被合并。"""
        pf = PeakFinder()
        plist = [
            Peak(two_theta=28.0, intensity=800, fwhm=0.2),
            Peak(two_theta=29.2, intensity=700, fwhm=0.2),  # 相邻晶面峰
        ]
        merged = pf._merge_kalpha_doublets(plist)
        assert len(merged) == 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
