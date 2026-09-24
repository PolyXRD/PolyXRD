"""
M19 脚本自动化测试 (Sprint 3)
=============================
"""
import numpy as np

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.scripting import apply_steps, process_files


def _synth_file(tmp_path, name="a.txt"):
    x = np.linspace(20, 60, 401)
    y = np.full_like(x, 30.0)
    for c, a in [(28.44, 800.0), (47.3, 500.0)]:
        y += a * np.exp(-0.5 * ((x - c) / 0.15) ** 2)
    y += 20.0 * np.sin(x * 3.0)  # 高频噪声
    p = tmp_path / name
    p.write_text("".join(f"{v:.3f}\t{intensity:.2f}\n"
                         for v, intensity in zip(x, np.maximum(y, 0))),
                 encoding="utf-8")
    return p


class TestApplySteps:
    def test_smooth_reduces_noise(self):
        x = np.linspace(20, 60, 401)
        y = 500 * np.exp(-0.5 * ((x - 30) / 0.15) ** 2) \
            + 20 * np.sin(x * 3)
        xrd = XRDData(two_theta=x, intensity=np.maximum(y, 0))
        out = apply_steps(xrd, [("smooth", {"window": 11})])
        resid = np.abs(out.intensity - 500 * np.exp(-0.5 * ((x - 30) / 0.15) ** 2))
        assert float(np.mean(resid)) < 15.0

    def test_background_subtracted_floor_zero(self):
        x = np.linspace(10, 80, 701)
        y = 60 + 40 * np.exp(-0.5 * ((x - 40) / 0.2) ** 2)
        xrd = XRDData(two_theta=x, intensity=y)
        out = apply_steps(xrd, [("background", {"method": "snip",
                                                "iterations": 20})])
        assert out.intensity.min() >= 0.0
        # 远离峰处 (10°) 背景≈60 → 减后≈0
        i10 = int(np.argmin(np.abs(x - 10.0)))
        assert abs(out.intensity[i10]) < 5.0

    def test_unknown_step_raises(self):
        xrd = XRDData(two_theta=np.linspace(1, 2, 10),
                      intensity=np.ones(10))
        try:
            apply_steps(xrd, [("foo", {})])
            assert False
        except ValueError:
            pass


class TestProcessFiles:
    def test_batch_summary(self, tmp_path):
        p1 = _synth_file(tmp_path, "a.txt")
        p2 = _synth_file(tmp_path, "b.txt")
        csv_out = tmp_path / "sum.csv"
        res = process_files([p1, p2],
                            steps=[("smooth", {"window": 7}),
                                   ("background", {})],
                            peak_options={"height": 0.2, "distance": 3.0},
                            summary_csv=csv_out)
        assert len(res) == 2
        assert all(r["n_peaks"] >= 2 for r in res)
        assert csv_out.exists()
        lines = csv_out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3               # 表头 + 2 文件
        assert "a.txt" in lines[1]

    def test_missing_file_raises(self, tmp_path):
        try:
            process_files([tmp_path / "nope.txt"])
            assert False
        except FileNotFoundError:
            pass
