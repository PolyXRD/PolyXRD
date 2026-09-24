"""
M08 仪器校正测试 (Sprint 1)
===========================
覆盖: 零点偏移校正/样品位移偏移/直方图误差估计/内标校正。
符号约定: error = obs - true; 校正 = 观测减 error (数据前校正)。
"""
import numpy as np

from polyxrd.models.peak import Peak
from polyxrd.models.phase import Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.calibration import Calibration


def _xrd(lo=20.0, hi=80.0, step=0.05):
    tt = np.arange(lo, hi + step / 2, step)
    return XRDData(two_theta=tt, intensity=np.linspace(10, 100, len(tt)))


class TestCalibrationM08:

    def test_zero_point_shift_axis(self):
        xrd = _xrd()
        dz = 0.05
        out = Calibration.zero_point_shift(xrd, dz)
        assert abs(out.two_theta[0] - (xrd.two_theta[0] - dz)) < 1e-12
        assert np.allclose(out.intensity, xrd.intensity)

    def test_zero_point_offset_scalar_and_array(self):
        assert abs(float(Calibration.zero_point_offset(30.0, 0.05)) - 0.05) < 1e-12
        arr = Calibration.zero_point_offset(np.array([10.0, 20.0]), 0.05)
        assert np.allclose(arr, [0.05, 0.05])

    def test_specimen_offset_sign_and_magnitude(self):
        # BB 平板, s>0 (样品下移): 误差为负, 峰移向低角
        off = float(Calibration.specimen_displacement_offset(28.44, 0.5, 240.0))
        assert -0.35 < off < -0.1, f"reflection offset 应在 -0.35~-0.1, 实际 {off:.4f}"
        # 位移越大误差越大 (绝对值)
        off_big = float(Calibration.specimen_displacement_offset(28.44, 1.0, 240.0))
        assert abs(off_big) > abs(off)

    def test_specimen_shift_reverts_synthetic_error(self):
        # 构造带位移误差的谱: tt_obs = tt_true + offset(tt_true)
        tt_true = np.linspace(20, 80, 1201)
        err = Calibration.specimen_displacement_offset(tt_true, 0.4, 240.0)
        sim = XRDData(two_theta=tt_true + err,
                      intensity=np.sin(tt_true) + 2.0)
        corr = Calibration.specimen_displacement_shift(sim, 0.4, 240.0)
        resid = np.abs(corr.two_theta - tt_true)
        assert float(np.max(resid)) < 0.02, \
            f"位移误差校正后应回到真值, 最大残差 {float(np.max(resid)):.4f}°"

    def test_estimate_from_histogram_zero_shift(self):
        # 无误差 → dz ≈ 0
        refs = [28.44, 47.30, 56.11]
        dz = Calibration.estimate_from_histogram(refs, refs)
        assert abs(dz) < 0.02, f"无误差时 dz 应≈0, 实际 {dz}"

    def test_estimate_from_histogram_positive_shift(self):
        # 观测整体偏高 +0.05 → dz ≈ +0.05
        refs = [28.44, 47.30, 56.11]
        obs = [t + 0.05 for t in refs]
        dz = Calibration.estimate_from_histogram(obs, refs)
        assert abs(dz - 0.05) < 0.03, f"应恢复 +0.05 偏移, 实际 {dz}"

    def test_estimate_accepts_peak_and_phase_objects(self):
        refs = [28.44, 47.30, 56.11]
        phase = Phase(name="Si", reference_peaks=[
            ((1, 1, 1), 28.44, 100.0), ((2, 2, 0), 47.30, 60.0),
            ((3, 1, 1), 56.11, 35.0)])
        obs_peaks = [Peak(two_theta=t + 0.08, intensity=100) for t in refs]
        dz_phase = Calibration.estimate_from_histogram(
            [p.two_theta for p in obs_peaks], [phase])
        dz_peak = Calibration.estimate_from_histogram(obs_peaks, refs)
        assert abs(dz_phase - 0.08) < 0.03, f"phase 输入 dz={dz_phase}"
        assert abs(dz_peak - 0.08) < 0.03, f"peak 输入 dz={dz_peak}"

    def test_calibrate_to_internal_standard(self):
        phase = Phase(name="Std", reference_peaks=[
            ((1, 1, 1), 28.44, 100.0), ((2, 2, 0), 47.30, 60.0),
            ((3, 1, 1), 56.11, 35.0)])
        obs = [t + 0.1 for t in [28.44, 47.30, 56.11]]
        dz = Calibration.calibrate_to_internal_standard(obs, phase)
        assert abs(dz - 0.1) < 0.04, f"内标校正应≈0.1, 实际 {dz}"

    def test_end_to_end_recover_peak(self):
        # 谱整体 +0.05 → 估计 dz → 零点校正 → 主峰回到真值
        tt = np.linspace(20, 60, 801)
        y = 800 * np.exp(-0.5 * ((tt - 28.44) / 0.1) ** 2) + 5.0
        biased = XRDData(two_theta=tt + 0.05, intensity=y)
        refs = [28.44, 47.30, 56.11]
        # 用峰检测取得观测峰
        from polyxrd.services.peak_finder import PeakFinder
        obs = PeakFinder().find_peaks(biased, height=0.02, distance=3.0)
        obs_tt = [p.two_theta for p in obs]
        dz = Calibration.estimate_from_histogram(obs_tt, refs)
        corr = Calibration.zero_point_shift(biased, dz)
        from polyxrd.services.peak_finder import PeakFinder as PF2
        obs2 = PF2().find_peaks(corr, height=0.02, distance=3.0)
        best = min(obs2.peaks, key=lambda p: abs(p.two_theta - 28.44))
        assert abs(best.two_theta - 28.44) < 0.05, \
            f"校正后主峰应≈28.44, 实际 {best.two_theta:.3f} (dz={dz:.3f})"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
