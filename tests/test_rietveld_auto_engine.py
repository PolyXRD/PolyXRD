"""engine="auto" 自动引擎选择测试。

v5.0.1 起口径变更（原实现: 全相有结构 CIF 且 GSAS-II 可用 → gsas2）：
`auto` 一律走 v5 精修引擎（refinement），失败由它自己回退 builtin。
依据是 13 试样三引擎对拍: refinement 在 11/13 个试样上 Rwp 最低且快 1~2 个
量级; gsas2 既依赖外部安装、又只在个别试样上更好（详见
``docs/基准报告-精修-v5.0.0.md`` 与 ``scripts/bench_engines_v500.py``）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from polyxrd.models.phase import Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner


@pytest.fixture
def data() -> XRDData:
    tt = np.linspace(20.0, 60.0, 200)
    return XRDData(two_theta=tt, intensity=np.abs(np.sin(tt)) * 100 + 10)


@pytest.fixture
def refiner() -> RietveldRefiner:
    return RietveldRefiner()


def _mk_cif(tmp_path: Path, name: str) -> str:
    p = tmp_path / f"{name}.cif"
    p.write_text("data_global\n_cell_length_a 3.25\n")
    return str(p)


def _v5_result() -> RefinementResult:
    return RefinementResult(fit_params={"engine": "refinement"})


def _builtin_result() -> RefinementResult:
    return RefinementResult(fit_params={"engine": "builtin"})


class TestPhasesHaveStructure:
    def test_all_cif_exist(self, tmp_path: Path):
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A")),
                  Phase(name="B", cif_path=_mk_cif(tmp_path, "B"))]
        assert RietveldRefiner._phases_have_structure(phases) is True

    def test_missing_cif_file(self):
        phases = [Phase(name="A", cif_path=r"Z:\nope\missing.cif")]
        assert RietveldRefiner._phases_have_structure(phases) is False

    def test_no_cif_at_all(self):
        assert RietveldRefiner._phases_have_structure([Phase(name="A")]) is False

    def test_empty_phases(self):
        assert RietveldRefiner._phases_have_structure([]) is False


class TestAutoEngine:
    def test_auto_uses_v5(self, refiner, data, monkeypatch):
        """有/无结构 CIF 都走 refinement —— auto 不再以 CIF 为门槛。"""
        phases = [Phase(name="A")]  # 无 CIF
        calls = {}

        def fake_v5(*a, **k):
            calls["hit"] = True
            return _v5_result()

        monkeypatch.setattr(refiner, "_refine_v5", fake_v5)
        result = refiner.refine(data, phases, engine="auto")
        assert calls["hit"], "auto 必须调用 v5 引擎"
        assert result.fit_params["engine"] == "refinement"
        assert result.fit_params["engine_auto_selected"] == "refinement"
        # 正常路径不该被记成"回退"
        assert "engine_fallback_reason" not in result.fit_params
        assert not [d for d in result.diagnostics
                    if d.get("code") == "diag.engine_fallback"]

    def test_auto_does_not_touch_gsas2(self, refiner, data, tmp_path, monkeypatch):
        """即便全相有 CIF 且 GSAS-II 在位, auto 也不再选 gsas2。"""
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A"))]
        monkeypatch.setattr(refiner, "_find_gsas2_python", lambda: Path("fake_py"))

        def boom(*a, **k):
            raise AssertionError("auto 不应调用 gsas2")

        monkeypatch.setattr(refiner, "_refine_gsas2", boom)
        monkeypatch.setattr(refiner, "_refine_v5", lambda *a, **k: _v5_result())
        result = refiner.refine(data, phases, engine="auto")
        assert result.fit_params["engine"] == "refinement"

    def test_v5_failure_falls_back_to_builtin(self, refiner, data, monkeypatch):
        """v5 内部回退 builtin 时, requested/used 不一致要留下回退记录。"""
        def fake_v5(*a, **k):
            res = _builtin_result()
            res.fit_params["engine_fallback_reason"] = "no structure for A"
            return res

        monkeypatch.setattr(refiner, "_refine_v5", fake_v5)
        result = refiner.refine(data, [Phase(name="A")], engine="auto")
        assert result.fit_params["engine"] == "builtin"
        assert "no structure" in result.fit_params["engine_fallback_reason"]
        assert [d for d in result.diagnostics
                if d.get("code") == "diag.engine_fallback"]

    def test_auto_engine_exception_falls_back(self, refiner, data, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("v5 crashed")

        monkeypatch.setattr(refiner, "_refine_v5", boom)
        monkeypatch.setattr(refiner, "_refine_builtin",
                            lambda *a, **k: _builtin_result())
        result = refiner.refine(data, [Phase(name="A")], engine="auto")
        assert result.fit_params["engine"] == "builtin"
        assert "v5 crashed" in result.fit_params["engine_fallback_reason"]

    def test_generic_fallback_annotates_reason(self, refiner, data, monkeypatch):
        """非 auto 引擎失败回退 builtin 时也应记录 requested/reason"""
        def boom(*a, **k):
            raise ValueError("boom")

        monkeypatch.setattr(refiner, "_refine_gsas2", boom)
        monkeypatch.setattr(refiner, "_refine_builtin",
                            lambda *a, **k: _builtin_result())
        result = refiner.refine(data, [Phase(name="A")], engine="gsas2")
        assert result.fit_params["engine_requested"] == "gsas2"
        assert "boom" in result.fit_params["engine_fallback_reason"]

    def test_real_pipeline_auto_end_to_end(self, refiner, data, tmp_path):
        """不 mock: auto 在极小样本上要么 refinement 要么 builtin, 且自洽。"""
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A"))]
        result = refiner.refine(data, phases, engine="auto", max_cycles=1)
        eng = result.fit_params.get("engine")
        assert eng in ("refinement", "builtin")
        if eng == "builtin":
            assert "engine_fallback_reason" in result.fit_params
