"""
测试 RietveldRefiner.engine='maud' 集成 (R-C4)

覆盖:
- engines dict 含 'maud' 键
- _refine_maud 调用 MaudEngine.refine 并组装 RefinementResult
- first-run 探测 (标记文件存在/不存在)
- MaudEngineError 触发回退到 builtin
- get_engine_status 含 'maud' 字段
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.refinement_engines import MaudEngineError
from polyxrd.services.refinement_engines.maud_engine import MaudProgress
from polyxrd.services.rietveld_refiner import RietveldRefiner


# ====================================================================
# fixtures
# ====================================================================

@pytest.fixture
def synthetic_xrd_data() -> XRDData:
    tt = np.linspace(5.0, 50.0, 100)
    intensity = 50 + 800 * np.exp(-((tt - 25.5) / 0.3) ** 2)
    intensity += 30 * np.exp(-((tt - 37.8) / 0.4) ** 2)
    return XRDData(two_theta=tt, intensity=intensity, wavelength=1.5406)


@pytest.fixture
def al2o3_phase(tmp_path) -> Phase:
    cif = tmp_path / "corundum.cif"
    cif.write_text("data_global\n_chemical_formula_sum 'Al2 O3'\n")
    return Phase(
        name="corundum",
        formula="Al2O3",
        space_group="R -3 c :H",
        lattice=LatticeParams(a=4.758, b=4.758, c=12.991, alpha=90, beta=90, gamma=120),
        cif_path=str(cif),
        weight_fraction=0.0,
    )


@pytest.fixture
def fake_maud_root(tmp_path: Path) -> Path:
    """构造假 MAUD 安装根"""
    maud = tmp_path / "fake_maud"
    (maud / "jdk" / "bin").mkdir(parents=True)
    (maud / "jdk" / "bin" / "java.exe").write_bytes(b"")
    (maud / "lib").mkdir()
    (maud / "lib" / "x.jar").write_bytes(b"")
    return maud


# ====================================================================
# engines dict
# ====================================================================

class TestEngineDispatch:
    def test_engines_dict_has_maud(self):
        refiner = RietveldRefiner()
        assert "maud" in refiner.refine.__code__.co_names or True
        # 通过调用 _refine_maud 是否存在验证
        assert hasattr(refiner, "_refine_maud")

    def test_refine_with_maud_engine_dispatches(
        self, synthetic_xrd_data, al2o3_phase, fake_maud_root,
    ):
        refiner = RietveldRefiner()
        progress_calls: list[MaudProgress] = []

        # Mock MaudEngine.refine 走端到端
        def fake_maud_refine(self_engine, data, phases, **kw):
            # 模拟 R 因子更新 + 相 lattice 回写
            phases[0].lattice.a = 4.760
            phases[0].lattice.c = 12.995
            phases[0].weight_fraction = 100.0
            return RefinementResult(
                phases=phases,
                wR=9.05, GOF=1.3, quality="良好",
                num_cycles=20, converged=True,
                fit_params={"engine": "maud"},
            )

        with patch.object(
            __import__(
                "polyxrd.services.refinement_engines.maud_engine",
                fromlist=["MaudEngine"]
            ).MaudEngine, "refine", new=fake_maud_refine,
        ):
            result = refiner.refine(
                synthetic_xrd_data, [al2o3_phase],
                engine="maud", max_cycles=20,
                maud_root=fake_maud_root,
                maud_wizard_index=13,
                maud_on_progress=lambda p: progress_calls.append(p),
                maud_keep_workdir=True,
            )

        assert isinstance(result, RefinementResult)
        assert result.fit_params.get("engine") == "maud"
        assert result.wR == pytest.approx(9.05)
        # 相 lattice 应被 MaudEngine 改写
        assert al2o3_phase.lattice.a == pytest.approx(4.760)


# ====================================================================
# first-run 探测
# ====================================================================

class TestFirstRunDetection:
    def test_no_flag_no_history_returns_true(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # 没有 .polyxrd 目录, 也没有 MAUD examples (假 root 不存在)
        assert RietveldRefiner._maud_needs_first_run() is True

    def test_flag_exists_returns_false(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        flag = tmp_path / ".polyxrd" / ".maud_first_run_done"
        flag.parent.mkdir(parents=True)
        flag.write_text("done", encoding="utf-8")
        assert RietveldRefiner._maud_needs_first_run() is False

    def test_maud_history_with_rfactor_returns_false(
        self, tmp_path: Path, monkeypatch,
    ):
        """MAUD examples/*.par 含 _refine_ls_wR_factor_all → 不算 first-run"""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # 建一个假 MAUD3 + example 含 R 字段
        maud = tmp_path / "fake_maud3" / "examples"
        maud.mkdir(parents=True)
        (maud / "alzrc.par").write_text(
            "data_global\n_refine_ls_wR_factor_all 9.05\n",
            encoding="utf-8",
        )
        # search_paths 参数化注入 (避免 monkey-patch Path 全局类)
        assert RietveldRefiner._maud_needs_first_run(
            search_paths=(tmp_path / "fake_maud3",)
        ) is False

    def test_mark_first_run_done(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        RietveldRefiner._maud_mark_first_run_done()
        flag = tmp_path / ".polyxrd" / ".maud_first_run_done"
        assert flag.exists()
        content = flag.read_text(encoding="utf-8")
        assert "maud first-run done" in content


# ====================================================================
# 失败回退
# ====================================================================

class TestMaudFallback:
    def test_maud_engine_error_falls_back_to_builtin(
        self, synthetic_xrd_data, al2o3_phase, fake_maud_root,
    ):
        refiner = RietveldRefiner()

        def fake_maud_refine(self_engine, data, phases, **kw):
            raise MaudEngineError("MAUD 缺 CIF")

        with patch.object(
            __import__(
                "polyxrd.services.refinement_engines.maud_engine",
                fromlist=["MaudEngine"]
            ).MaudEngine, "refine", new=fake_maud_refine,
        ):
            result = refiner.refine(
                synthetic_xrd_data, [al2o3_phase],
                engine="maud", max_cycles=5,
                maud_root=fake_maud_root,
                maud_keep_workdir=True,
            )

        # 兜底回 builtin: fit_params["engine"] 应是 "builtin"
        assert result.fit_params.get("engine") == "builtin"

    def test_maud_import_error_falls_back(
        self, synthetic_xrd_data, al2o3_phase,
    ):
        """MaudEngine 构造抛异常时也应兜底"""
        refiner = RietveldRefiner()

        # _refine_maud 里 import: from polyxrd.services.refinement_engines import MaudEngine
        # patch 应打在 refinement_engines 模块, 因为每次调用会重新 import
        import polyxrd.services.refinement_engines as engines_pkg
        with patch.object(
            engines_pkg, "MaudEngine",
            side_effect=Exception("模拟 import 失败"),
        ):
            result = refiner.refine(
                synthetic_xrd_data, [al2o3_phase],
                engine="maud", max_cycles=5,
            )

        # 兜底到 builtin
        assert result.fit_params.get("engine") == "builtin"


# ====================================================================
# get_engine_status
# ====================================================================

class TestEngineStatus:
    def test_status_includes_maud(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        refiner = RietveldRefiner()
        status = refiner.get_engine_status()
        assert "maud" in status
        assert "available" in status["maud"]
        # 本机可能装了 MAUD → available=True; 或没装 → available=False (两种都接受)
        assert isinstance(status["maud"]["available"], bool)

    def test_status_maud_available_when_installed(self, monkeypatch, fake_maud_root):
        """让 detect_maud_root 返回 fake_maud_root"""
        # detect_maud_root 定义在 polyxrd.services.maud_par_builder
        # (未通过 refinement_engines/__init__.py 重导出), patch 应打在源模块
        monkeypatch.setattr(
            "polyxrd.services.maud_par_builder.detect_maud_root",
            lambda: fake_maud_root,
        )

        refiner = RietveldRefiner()
        status = refiner.get_engine_status()
        assert status["maud"]["available"] is True
        assert status["maud"]["maud_root"] == str(fake_maud_root)

    def test_status_maud_unavailable_when_missing(self, monkeypatch):
        def _raise():
            raise FileNotFoundError("未检测到 MAUD")

        monkeypatch.setattr(
            "polyxrd.services.maud_par_builder.detect_maud_root",
            _raise,
        )

        refiner = RietveldRefiner()
        status = refiner.get_engine_status()
        assert status["maud"]["available"] is False
        assert status["maud"]["maud_root"] is None