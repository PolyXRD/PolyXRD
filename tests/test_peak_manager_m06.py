"""
M06 峰管理测试 (Sprint 1)
=========================
覆盖: 增/删/改峰(不可变式), 区域排除掩码, 残差峰, 相对强度重标定。
"""
import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase
from polyxrd.services.peak_manager import PeakManager


def _plist(tt_list):
    return PeakList(peaks=[Peak(two_theta=t, intensity=100.0 * (i + 1))
                           for i, t in enumerate(tt_list)])


class TestPeakManagerM06:

    def test_add_keeps_sorted_and_immutable(self):
        pl = _plist([47.3, 28.44])
        out = PeakManager.add_peak(pl, 36.5, intensity=88.0)
        assert len(out) == 3
        assert [p.two_theta for p in out] == sorted(p.two_theta for p in out)
        assert len(pl) == 2, "原列表不应被修改 (不可变式)"

    def test_delete_by_index_and_theta(self):
        pl = _plist([28.44, 36.5, 47.3])
        by_idx = PeakManager.delete_peak(pl, index=0)
        assert len(by_idx) == 2 and by_idx.peaks[0].two_theta == 36.5
        by_tt = PeakManager.delete_peak(pl, two_theta=36.6)  # 就近删除
        assert len(by_tt) == 2
        assert all(abs(p.two_theta - 36.5) > 1e-6 for p in by_tt)

    def test_edit_peak(self):
        pl = _plist([28.44, 47.3])
        out = PeakManager.edit_peak(pl, 0, two_theta=25.0, intensity=999.0)
        assert out.peaks[0].two_theta == 25.0
        assert out.peaks[0].intensity == 999.0
        assert len(pl) == 2 and pl.peaks[0].two_theta == 28.44

    def test_exclude_regions_mask(self):
        tt = np.linspace(10, 60, 501)
        mask = PeakManager.exclude_regions_mask(tt, [(20, 25), (40, 45)])
        assert mask[0] and mask[-1]          # 区间外保留
        assert not mask[np.argmin(abs(tt - 22))]
        assert not mask[np.argmin(abs(tt - 42))]
        # 相交区间自动合并为一段
        mask2 = PeakManager.exclude_regions_mask(tt, [(20, 30), (25, 35)])
        assert not mask2[np.argmin(abs(tt - 32))]  # 25-30 交叠带也排除
        # 非法区间 (lo>=hi) 忽略
        mask3 = PeakManager.exclude_regions_mask(tt, [(50, 40)])
        assert mask3.all()

    def test_filter_peaks_by_mask(self):
        pl = _plist([21.0, 30.0, 50.0])
        tt = np.linspace(10, 60, 501)
        mask = PeakManager.exclude_regions_mask(tt, [(20, 25)])
        out = PeakManager.filter_peaks_by_mask(pl, mask, tt)
        assert [p.two_theta for p in out] == [30.0, 50.0], \
            "20-25° 区间内的峰应被滤除"

    def test_residual_peaks(self):
        obs = _plist([25.0, 28.44, 33.0, 47.3, 56.0])
        phase_a = Phase(name="A", reference_peaks=[
            ((1, 0, 0), 28.44, 100.0), ((1, 1, 0), 47.3, 60.0)])
        phase_b = Phase(name="B", reference_peaks=[
            ((1, 0, 1), 33.0, 90.0)])
        residual = PeakManager.compute_residual_peaks(obs, [phase_a, phase_b], tolerance=0.15)
        got = sorted(p.two_theta for p in residual)
        assert got == [25.0, 56.0], f"残差峰应为 25/56 两峰, 实际 {got}"

    def test_residual_respects_regions(self):
        obs = _plist([25.0, 28.44])
        phase_a = Phase(name="A", reference_peaks=[((1, 0, 0), 28.44, 100.0)])
        # 25° 位于排除带 → 不算残差
        residual = PeakManager.compute_residual_peaks(
            obs, [phase_a], tolerance=0.15, regions=[(24, 26)])
        assert len(residual) == 0

    def test_rescale_relative_intensities(self):
        pl = _plist([28.44, 47.3])  # 强度 100, 200
        out = PeakManager.rescale_relative_intensities(pl)
        assert out.peaks[1].intensity == 100.0
        assert abs(out.peaks[0].intensity - 50.0) < 1e-6
        assert pl.peaks[1].intensity == 200.0, "原列表不变"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
