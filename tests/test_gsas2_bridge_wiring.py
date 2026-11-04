"""GSAS-II 桥接线守护（P1-9①③④，v5.2）。

桥是子进程脚本（GSAS-II 自带 Python 跑），本文件**不真跑** GSAS-II，钉三件事：

1. **超时自适应**（①）：未显式给 ``gsas2_timeout`` 时按相数
   ``max(300, 120·n)``（5-1/5-2 实测 300 s 必超时 → 整条回退）；
   显式给 ≤0 = 不限时；
2. **PO / 样品位移透传**（③）：服务层把 ``_po_direction``/``_po_r``
   （RefineOptions.preferred_orientation 的 M14 前处理产物）与
   ``gsas2_sample_displace`` 写进 request.json，桥侧的
   ``_apply_pref_ori`` / ``_apply_sample_displace`` 能把它落到
   GSAS-II 的 HAP ``Pref.Ori.`` / Sample ``DisplaceX`` 上；
3. **GOF/Nobs/Nvar 回传**（④）：桥 main() 此前硬编码 ``"GOF": None``，
   诊断表整列恒 0。现在 ``_read_rvals`` 从 Controls 取真值，位置兼容
   ``Controls['Rvals']`` 与 ``Controls['data']['Rvals']`` 两代。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import gsas2_bridge as bridge  # noqa: E402
from polyxrd.models.phase import LatticeParams, Phase  # noqa: E402
from polyxrd.models.xrd_data import XRDData  # noqa: E402
from polyxrd.services.rietveld_refiner import RietveldRefiner  # noqa: E402


# ──────────────────────────────────────────────────────────────
# 桥侧纯函数（不需要 GSAS-II）
# ──────────────────────────────────────────────────────────────
class TestBridgeAppliers:
    def test_apply_sample_displace_sets_value_and_flag(self):
        hist = types.SimpleNamespace(data={"Sample Parameters": {
            "DisplaceX": [0.0, False]}})
        bridge._apply_sample_displace(
            hist, {"sample_displace": -120.5})
        dx = hist.data["Sample Parameters"]["DisplaceX"]
        assert dx == [-120.5, True]

    def test_apply_sample_displace_noop_without_key(self):
        hist = types.SimpleNamespace(data={"Sample Parameters": {
            "DisplaceX": [0.0, False]}})
        bridge._apply_sample_displace(hist, {})
        assert hist.data["Sample Parameters"]["DisplaceX"] == [0.0, False]
        # 非法值也静默跳过
        bridge._apply_sample_displace(hist, {"sample_displace": "x"})
        bridge._apply_sample_displace(hist, {"sample_displace": float("nan")})
        assert hist.data["Sample Parameters"]["DisplaceX"] == [0.0, False]

    @staticmethod
    def _fake_gpx(n_phases=2):
        phases = []
        for i in range(n_phases):
            phases.append(types.SimpleNamespace(data={
                "Histograms": {
                    "PWDR": {"Pref.Ori.": ["MD", 1.0, False, [0, 0, 1]]},
                },
                "name": f"ph{i}",
            }))
        return types.SimpleNamespace(phases=lambda: phases)

    def test_apply_pref_ori_sets_md_axis_and_r(self):
        gpx = self._fake_gpx()
        bridge._apply_pref_ori(gpx, {"pref_ori": {"hkl": [0, 0, 1],
                                                  "r": 0.8}})
        for ph in gpx.phases():
            p = ph.data["Histograms"]["PWDR"]["Pref.Ori."]
            assert p[0] == "MD"
            assert p[1] == pytest.approx(0.8)
            assert p[2] is True
            assert p[3] == [0, 0, 1]

    def test_apply_pref_ori_skips_r_one_or_missing(self):
        gpx = self._fake_gpx()
        bridge._apply_pref_ori(gpx, {"pref_ori": {"hkl": [1, 0, 0], "r": 1.0}})
        bridge._apply_pref_ori(gpx, {})
        p = gpx.phases()[0].data["Histograms"]["PWDR"]["Pref.Ori."]
        assert p == ["MD", 1.0, False, [0, 0, 1]]  # 原样未动

    def test_read_rvals_covariance_tree_is_canonical(self):
        """GSASIIstrMain 把 covData 存进 Covariance['data']（端到端实证位置）。"""
        gpx = types.SimpleNamespace(data={"Covariance": {"data": {
            "Rvals": {"GOF": 3.1, "Nobs": 5000, "Nvar": 15}}}})
        rv = bridge._read_rvals(gpx)
        assert rv["GOF"] == pytest.approx(3.1)
        assert rv["Nobs"] == 5000

    def test_read_rvals_controls_legacy_locations(self):
        gpx = types.SimpleNamespace(data={"Controls": {
            "Rvals": {"GOF": 2.42, "Nobs": 4000, "Nvar": 12}}})
        assert bridge._read_rvals(gpx)["GOF"] == pytest.approx(2.42)

    def test_read_rvals_data_nested_location(self):
        gpx = types.SimpleNamespace(data={"Controls": {"data": {
            "Rvals": {"GOF": 1.9, "Nobs": 2000, "Nvar": 8}}}})
        assert bridge._read_rvals(gpx)["Nobs"] == 2000

    def test_read_rvals_missing_returns_empty(self):
        assert bridge._read_rvals(types.SimpleNamespace(data={})) == {}


# ──────────────────────────────────────────────────────────────
# 服务层接线（假 subprocess.run，不真调 GSAS-II）
# ──────────────────────────────────────────────────────────────
def _two_phase_data():
    tt = np.linspace(15.0, 60.0, 300)
    yy = 100.0 * np.exp(-((tt - 29.4) ** 2) / 0.02) + 30.0
    return XRDData(two_theta=tt, intensity=yy, wavelength=1.54056)


def _phases(n=2):
    return [Phase(name=f"P{i}", formula="AB", space_group="P 1",
                  lattice=LatticeParams(a=4.9, b=4.9, c=5.4))
            for i in range(n)]


class TestTimeoutAdaptive:
    @staticmethod
    def _run_capture(monkeypatch, captured, rc=1):
        """替换 subprocess.run：记录 timeout 与 request.json，返回假失败。"""

        def fake_run(cmd, **kw):
            captured["timeout"] = kw.get("timeout")
            with open(cmd[2], "r", encoding="utf-8") as f:
                captured["req"] = json.load(f)
            return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)

    def test_default_scales_with_phase_count(self, monkeypatch):
        captured: dict = {}
        self._run_capture(monkeypatch, captured)
        r = RietveldRefiner()
        r._refine_gsas2(_two_phase_data(), _phases(5), "quick", 10)
        assert captured["timeout"] == pytest.approx(600.0)  # 120·5

    def test_two_phases_still_gets_floor_300(self, monkeypatch):
        captured: dict = {}
        self._run_capture(monkeypatch, captured)
        RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10)
        assert captured["timeout"] == pytest.approx(300.0)

    def test_explicit_value_wins(self, monkeypatch):
        captured: dict = {}
        self._run_capture(monkeypatch, captured)
        RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(5), "quick", 10, gsas2_timeout=900.0)
        assert captured["timeout"] == pytest.approx(900.0)

    def test_explicit_zero_means_no_limit(self, monkeypatch):
        captured: dict = {}
        self._run_capture(monkeypatch, captured)
        RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10, gsas2_timeout=0)
        assert captured["timeout"] is None


class TestRequestWiring:
    def test_po_and_displace_land_in_request(self, monkeypatch):
        captured: dict = {}
        TestTimeoutAdaptive._run_capture(monkeypatch, captured)
        RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10,
            _po_direction=(0, 0, 1), _po_r=0.8, gsas2_sample_displace=-75.0)
        req = captured["req"]
        assert req["pref_ori"] == {"hkl": [0, 0, 1], "r": 0.8}
        assert req["sample_displace"] == pytest.approx(-75.0)

    def test_no_po_by_default(self, monkeypatch):
        captured: dict = {}
        TestTimeoutAdaptive._run_capture(monkeypatch, captured)
        RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10)
        assert "pref_ori" not in captured["req"]
        assert "sample_displace" not in captured["req"]

    def test_r_one_is_not_sent(self, monkeypatch):
        """r=1 = 无择优，别让桥白白打开 PO 精修标志。"""
        captured: dict = {}
        TestTimeoutAdaptive._run_capture(monkeypatch, captured)
        RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10,
            _po_direction=(0, 0, 1), _po_r=1.0)
        assert "pref_ori" not in captured["req"]


class TestGofPassthrough:
    def test_result_carries_nobs_nvar_and_gof(self, monkeypatch):
        """桥返回真 GOF/Nobs/Nvar 时，服务层照收并反推可解读的 Rexp。"""
        out = {
            "ok": True, "wR": 20.0, "GOF": 2.5, "Nobs": 4000, "Nvar": 10,
            "n_cycles": 6,
            "phases": [{"name": "P0", "lattice": None},
                       {"name": "P1", "lattice": None}],
            "phase_fractions": [60.0, 40.0],
            "ycalc": list(np.linspace(1.0, 30.0, 300)), "gpx": "x.gpx",
        }

        def fake_run(cmd, **kw):
            with open(cmd[3], "w", encoding="utf-8") as f:
                json.dump(out, f)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr(RietveldRefiner, "_find_gsas2_python",
                            staticmethod(lambda: Path("fake_py")))
        res = RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10)
        assert res.GOF == pytest.approx(2.5)
        assert res.fit_params["gsas2_nobs"] == 4000
        assert res.fit_params["gsas2_nvar"] == 10
        assert res.metrics_valid is True
        assert res.Rexp == pytest.approx(20.0 / 2.5)

    def test_legacy_bridge_without_gof_still_works(self, monkeypatch):
        """旧桥输出（无 GOF 键）不炸：GOF=0 + metrics_no_rexp 诊断（原语义）。"""
        out = {
            "ok": True, "wR": 20.0, "n_cycles": 6,
            "phases": [{"name": "P0", "lattice": None},
                       {"name": "P1", "lattice": None}],
            "phase_fractions": [60.0, 40.0],
            "ycalc": list(np.linspace(1, 30, 300)), "gpx": "x.gpx",
        }

        def fake_run(cmd, **kw):
            with open(cmd[3], "w", encoding="utf-8") as f:
                json.dump(out, f)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr(RietveldRefiner, "_find_gsas2_python",
                            staticmethod(lambda: Path("fake_py")))
        res = RietveldRefiner()._refine_gsas2(
            _two_phase_data(), _phases(2), "quick", 10)
        assert res.GOF == 0.0
        assert res.metrics_valid is False
        assert any(d["code"] == "diag.metrics_no_rexp" for d in res.diagnostics)
