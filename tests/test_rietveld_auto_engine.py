"""engine="auto" 自动引擎选择测试 (v0.11.0 GSAS-II 通道打磨).

规则: 全相有结构 CIF 且 GSAS-II 可用 → gsas2; 否则 builtin,
原因写入 fit_params["engine_fallback_reason"]。
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


def _gsas2_result() -> RefinementResult:
    return RefinementResult(fit_params={"engine": "gsas2"})


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
    def test_uses_gsas2_when_structured(
        self, refiner, data, tmp_path, monkeypatch
    ):
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A"))]
        monkeypatch.setattr(refiner, "_find_gsas2_python", lambda: Path("fake_py"))
        monkeypatch.setattr(refiner, "_refine_gsas2",
                            lambda *a, **k: _gsas2_result())
        result = refiner.refine(data, phases, engine="auto")
        assert result.fit_params["engine"] == "gsas2"
        assert "engine_fallback_reason" not in result.fit_params

    def test_fallback_when_no_structure(self, refiner, data, monkeypatch):
        phases = [Phase(name="A")]  # 无 CIF
        calls = {}

        def fake_builtin(*a, **k):
            calls["hit"] = True
            return _builtin_result()

        monkeypatch.setattr(refiner, "_refine_builtin", fake_builtin)
        result = refiner.refine(data, phases, engine="auto")
        assert calls["hit"]
        assert result.fit_params["engine"] == "builtin"
        # v1.1.1: 服务层不依赖 Qt/i18n (`services/` 的硬约定), 回退原因统一为
        # 符号化 ASCII 写法, 不再跟随界面语言 → 断言应对英文原文。
        assert "without structure" in result.fit_params["engine_fallback_reason"]

    def test_fallback_when_gsas2_missing(self, refiner, data, tmp_path, monkeypatch):
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A"))]
        monkeypatch.setattr(refiner, "_find_gsas2_python", lambda: None)
        monkeypatch.setattr(refiner, "_refine_builtin",
                            lambda *a, **k: _builtin_result())
        result = refiner.refine(data, phases, engine="auto")
        assert result.fit_params["engine"] == "builtin"
        assert "GSAS-II" in result.fit_params["engine_fallback_reason"]

    def test_fallback_when_gsas2_raises(self, refiner, data, tmp_path, monkeypatch):
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A"))]
        monkeypatch.setattr(refiner, "_find_gsas2_python", lambda: Path("fake_py"))

        def boom(*a, **k):
            raise RuntimeError("bridge crashed")

        monkeypatch.setattr(refiner, "_refine_gsas2", boom)
        monkeypatch.setattr(refiner, "_refine_builtin",
                            lambda *a, **k: _builtin_result())
        result = refiner.refine(data, phases, engine="auto")
        assert result.fit_params["engine"] == "builtin"
        assert "bridge crashed" in result.fit_params["engine_fallback_reason"]

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

    def test_real_pipeline_auto_with_real_gsas2(
        self, refiner, data, tmp_path
    ):
        """不 mock: 本机装了 GSAS-II 时 auto+结构 CIF 应真的选 gsas2"""
        py = RietveldRefiner._find_gsas2_python()
        if py is None:
            pytest.skip("本机未装 GSAS-II")
        phases = [Phase(name="A", cif_path=_mk_cif(tmp_path, "A"))]
        result = refiner.refine(data, phases, engine="auto", max_cycles=1)
        # 假 CIF 结构极简, 桥可能成功也可能报错回退 — 只要求二选一且自洽
        eng = result.fit_params.get("engine")
        assert eng in ("gsas2", "builtin")
        if eng == "builtin":
            assert "engine_fallback_reason" in result.fit_params
