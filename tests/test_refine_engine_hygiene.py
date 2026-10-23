"""精修引擎卫生回归 (2026-10 代码审查 / task-4)。

锁定四个「真缺陷」修复，每条都在修复前被实证复现：

1. ``RietveldRefiner._refine_maud`` 泄漏临时工作目录 —— ``MaudEngine.refine`` 的
   ``keep_workdir`` 只被记进 fit_params, 引擎自身**从不** rmtree (grep 全文无
   rmtree), 于是每次 MAUD 精修 (含失败回退) 都在 CWD 留下一个
   ``maud_engine_*`` / ``polyxrd_maud_*`` 目录 (仓库根实测 3 个)。
2. GSAS-II 子进程桥的 ``returncode``/``stderr`` 被丢弃 —— 桥崩 (LAPACK/DLL/导入失败)
   时只剩一句 "produced no output.json", 现场诊断全丢, fallback reason 也不含退出码。
3. powerxrd 分支异常时**静默**回退内置引擎 (不写 engine_requested / reason),
   GUI 只看到 engine=builtin; 且 Rexp/GOF 用单位权算出却被标为 metrics_valid=True。
4. 精修模板管理器: 非 UTF-8 模板文件会让 ``__init__`` 崩; ``get_user_templates``
   返回内部列表 (可被外部改坏); ``delete_user_template`` 恒返回 True;
   模板名含路径分隔符时写到目录外。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from polyxrd.models.phase import LatticeParams, Phase
from polyxrd.models.xrd_data import XRDData
from polyxrd.services.rietveld_refiner import RietveldRefiner

WAV = 1.5406


def _small_data(n=240, lo=20.0, hi=60.0) -> XRDData:
    tt = np.linspace(lo, hi, n)
    y = np.full_like(tt, 20.0)
    for c, a, s in [(28.44, 500.0, 0.12), (47.30, 300.0, 0.14)]:
        y += a * np.exp(-0.5 * ((tt - c) / s) ** 2)
    return XRDData(two_theta=tt, intensity=np.maximum(y, 0.0), wavelength=WAV)


def _si_phase() -> Phase:
    return Phase(
        name="Si", formula="Si", space_group="Fd-3m",
        lattice=LatticeParams(a=5.431, b=5.431, c=5.431,
                              alpha=90.0, beta=90.0, gamma=90.0),
        weight_fraction=100.0,
        reference_peaks=[((1, 1, 1), 28.44, 500.0), ((2, 2, 0), 47.30, 300.0)],
    )


# --------------------------------------------------------------------------- #
# 1. MAUD 临时目录所有权
# --------------------------------------------------------------------------- #
class _FakeMaudEngine:
    """替代 MaudEngine: 记录收到的 work_dir, 成功走正常返回 / 失败抛错。"""

    instances: list["_FakeMaudEngine"] = []
    raise_error = False

    def __init__(self, maud_root=None):
        self.work_dir = None
        self.maud_root = maud_root
        _FakeMaudEngine.instances.append(self)

    def refine(self, data, phases, *, iterations=0, wizard_index=None,
               timeout_s=0.0, keep_workdir=False, on_progress=None,
               cod_root=None, work_dir=None, **kwargs):
        self.work_dir = Path(work_dir) if work_dir else None
        if self.work_dir is not None:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            (self.work_dir / "input.xye").write_text("x y e\n", encoding="utf-8")
        if _FakeMaudEngine.raise_error:
            from polyxrd.services.refinement_engines import MaudEngineError

            raise MaudEngineError("MAUD 超时 (test)")
        return SimpleNamespace(wR=12.5, num_cycles=7)


@pytest.fixture()
def fake_maud(monkeypatch):
    import polyxrd.services.refinement_engines as engines

    _FakeMaudEngine.instances = []
    _FakeMaudEngine.raise_error = False
    monkeypatch.setattr(engines, "MaudEngine", _FakeMaudEngine)
    monkeypatch.setattr(RietveldRefiner, "_maud_needs_first_run",
                        staticmethod(lambda *a, **k: False))
    monkeypatch.setattr(RietveldRefiner, "_maud_mark_first_run_done",
                        staticmethod(lambda: None))
    yield _FakeMaudEngine
    # 清理 keep_workdir=True 留下的目录 (测试自身不留垃圾)
    for inst in _FakeMaudEngine.instances:
        if inst.work_dir is not None and inst.work_dir.exists():
            import shutil

            shutil.rmtree(inst.work_dir, ignore_errors=True)


class TestMaudWorkdirCleanup:

    def test_success_cleans_workdir(self, fake_maud, tmp_path):
        ref = RietveldRefiner()
        res = ref._refine_maud(_small_data(), [_si_phase()], "sequential", 1)
        assert res.wR == pytest.approx(12.5)
        wd = fake_maud.instances[-1].work_dir
        assert wd is not None and not wd.exists(), (
            f"MAUD 成功后仍残留工作目录: {wd}")

    def test_failure_also_cleans_workdir_and_falls_back(self, fake_maud):
        fake_maud.raise_error = True
        ref = RietveldRefiner()
        res = ref._refine_maud(
            _small_data(), [_si_phase()], "sequential", 1,
            n_starts=1, max_nfev_per_start=20, detect_ka2=False,
        )
        # 失败 → 回退内置引擎 (engine=builtin), 但临时目录必须被回收
        assert res is not None
        wd = fake_maud.instances[-1].work_dir
        assert wd is not None and not wd.exists(), (
            f"MAUD 失败后残留工作目录: {wd}")

    def test_keep_workdir_true_preserves_dir(self, fake_maud):
        ref = RietveldRefiner()
        ref._refine_maud(_small_data(), [_si_phase()], "sequential", 1,
                         maud_keep_workdir=True)
        # keep=True 时由引擎自己 mkdtemp (本 fake 不建目录), 这里只断言
        # 调用方**没有**替它建/删目录, 即 work_dir 传 None。
        assert fake_maud.instances[-1].work_dir is None


# --------------------------------------------------------------------------- #
# 2. GSAS-II 桥: 退出码 / stderr 不再丢弃
# --------------------------------------------------------------------------- #
class TestGsas2BridgeDiagnostics:

    def _run(self, monkeypatch, stderr_text, returncode):
        bridge = (Path(__file__).resolve().parents[1]
                  / "scripts" / "gsas2_bridge.py")
        assert bridge.exists(), "gsas2_bridge.py 应随仓库分发"

        monkeypatch.setattr(RietveldRefiner, "_find_gsas2_python",
                            staticmethod(lambda: Path(sys.executable)))
        monkeypatch.setattr(RietveldRefiner, "_gsas2_env",
                            staticmethod(lambda py: dict()))

        def fake_run(cmd, **kwargs):
            # 模拟"桥崩且没写出 output.json"
            return subprocess.CompletedProcess(
                args=cmd, returncode=returncode, stdout="",
                stderr=stderr_text)

        monkeypatch.setattr(subprocess, "run", fake_run)
        logs: list[str] = []
        ref = RietveldRefiner()
        res = ref._refine_gsas2(
            _small_data(), [_si_phase()], "sequential", 1,
            log_cb=logs.append, n_starts=1, max_nfev_per_start=20,
            detect_ka2=False,
        )
        return res, logs

    def test_returncode_and_stderr_in_fallback_reason(self, monkeypatch):
        res, logs = self._run(monkeypatch, "ImportError: LAPACK dll missing", 3)
        reason = res.fit_params.get("engine_fallback_reason", "")
        assert "exit=3" in reason, reason
        assert "LAPACK" in reason, reason
        assert res.fit_params.get("engine") == "builtin"
        assert res.fit_params.get("engine_requested") == "gsas2"
        joined = "\n".join(logs)
        assert "exit=3" in joined and "LAPACK" in joined, joined

    def test_clean_failure_without_stderr_still_reports_exit(self, monkeypatch):
        res, _ = self._run(monkeypatch, "", 1)
        reason = res.fit_params.get("engine_fallback_reason", "")
        assert "exit=1" in reason, reason


# --------------------------------------------------------------------------- #
# 3. powerxrd: 失败不静默 + 统计口径不冒充有效
# --------------------------------------------------------------------------- #
class TestPowerxrdHonesty:

    def _cubic_data(self) -> XRDData:
        # 立方 Si 单相: 通过 powerxrd 的 (单相 + 立方) 前置门
        return _small_data()

    def test_failure_records_requested_engine(self, monkeypatch):
        import powerxrd.model as pxr_model

        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("powerxrd 内部崩溃")

        monkeypatch.setattr(pxr_model, "PhaseModel", _Boom)
        res = RietveldRefiner()._refine_powerxrd(
            self._cubic_data(), [_si_phase()], "sequential", 1,
            n_starts=1, max_nfev_per_start=20, detect_ka2=False,
        )
        assert res.fit_params.get("engine") == "builtin"
        assert res.fit_params.get("engine_requested") == "powerxrd"
        assert "powerxrd" in res.fit_params.get("engine_fallback_reason", "")

    def test_unit_weight_metrics_not_marked_valid(self):
        """powerxrd 成功路径: Rexp/GOF 无统计权 → metrics_valid 必须为 False。"""
        try:
            import powerxrd  # noqa: F401
        except ImportError:  # pragma: no cover - 环境缺库时跳过
            pytest.skip("powerxrd 未安装")
        ref = RietveldRefiner()
        res = ref.refine(self._cubic_data(), [_si_phase()],
                         engine="powerxrd", max_cycles=2, detect_ka2=False)
        if res.fit_params.get("engine") != "powerxrd":
            pytest.skip(f"powerxrd 未真正生效: {res.fit_params.get('engine_fallback_reason')}")
        assert res.metrics_valid is False
        codes = {d.get("code") for d in res.diagnostics}
        assert "diag.metrics_no_weights" in codes


# --------------------------------------------------------------------------- #
# 5. d-spacing 标量结算: 换成 math 后必须与三斜通式逐位一致 (性能项)
# --------------------------------------------------------------------------- #
class TestDSpacingFormula:

    @staticmethod
    def _ref(a, b, c, al, be, ga, h, k, l):
        """独立实现的 1/d² 三斜通式 (不调用被测函数)。"""
        import math

        ar, br, gr = map(math.radians, (al, be, ga))
        ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
        sa, sb, sg = math.sin(ar), math.sin(br), math.sin(gr)
        inv = ((h * h * sa * sa) / (a * a) + (k * k * sb * sb) / (b * b)
               + (l * l * sg * sg) / (c * c)
               + (2 * k * l * (cb * cg - ca)) / (b * c)
               + (2 * h * l * (ca * cg - cb)) / (a * c)
               + (2 * h * k * (ca * cb - cg)) / (a * b))
        nrm = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
        inv = inv / nrm if nrm > 1e-12 else inv
        return 1.0 / math.sqrt(inv) if inv > 0 else 0.0

    def test_hexagonal_known_angles(self):
        # 注释里记录过的实测值: ZnO a=3.2498, c=5.2066 的 (100)/(101)
        a, c = 3.2498, 5.2066
        d100 = RietveldRefiner._calc_d_spacing_from_hkl(
            a, a, c, 90.0, 90.0, 120.0, 1, 0, 0)
        tth100 = 2 * np.degrees(np.arcsin(WAV / (2 * d100)))
        assert tth100 == pytest.approx(31.767, abs=0.01), tth100
        d101 = RietveldRefiner._calc_d_spacing_from_hkl(
            a, a, c, 90.0, 90.0, 120.0, 1, 0, 1)
        tth101 = 2 * np.degrees(np.arcsin(WAV / (2 * d101)))
        assert tth101 == pytest.approx(36.252, abs=0.01), tth101

    def test_random_triclinic_matches_closed_form(self):
        rng = np.random.default_rng(20261023)
        for _ in range(500):
            a, b, c = rng.uniform(3.0, 12.0, 3)
            al, be, ga = rng.uniform(60.0, 120.0, 3)
            h, k, l = (int(v) for v in rng.integers(-4, 5, 3))
            got = RietveldRefiner._calc_d_spacing_from_hkl(
                float(a), float(b), float(c), float(al), float(be),
                float(ga), h, k, l)
            want = self._ref(a, b, c, al, be, ga, h, k, l)
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)

# --------------------------------------------------------------------------- #
# 6. WPSM: 求解器收敛状态不再被丢弃
# --------------------------------------------------------------------------- #
class TestWpsmSolverStatus:

    def test_solver_status_recorded(self):
        from polyxrd.services.wpsm import WpsmConfig, fit_candidate

        x = np.linspace(20.0, 60.0, 400)
        y = np.full_like(x, 20.0)
        peaks = []
        for c, a in [(28.44, 500.0), (47.30, 300.0)]:
            y += a * np.exp(-0.5 * ((x - c) / 0.12) ** 2)
            peaks.append(((1, 1, 1), c, a))
        fit = fit_candidate(x, np.maximum(y, 0.0), peaks,
                            cfg=WpsmConfig(caglioti=False), key="k1")
        assert fit.ok, fit.reason
        assert isinstance(fit.extra.get("solver_success"), bool)
        assert fit.extra["solver_status"] in (-1, 0, 1, 2, 3, 4)
        assert fit.extra["solver_nfev"] >= 1
        assert 0.0 < fit.fom <= 1.0


# --------------------------------------------------------------------------- #
# 4. 精修模板管理器健壮性
# --------------------------------------------------------------------------- #
class TestRefinementTemplatesRobustness:

    @pytest.fixture()
    def manager(self, monkeypatch, tmp_path):
        import polyxrd.services.refinement_templates as rt

        class _Cfg:
            cif_db_path = tmp_path / "PolyXRD" / "cif.db"

        monkeypatch.setattr(rt, "get_config", lambda: _Cfg())
        mgr = rt.RefinementTemplateManager()
        yield mgr, tmp_path / "PolyXRD" / "refinement_templates"

    def test_non_utf8_template_file_does_not_crash_init(self, manager):
        mgr, tdir = manager
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "bad.json").write_bytes(b"\xff\xfe\x00not-utf8")
        # 重新构造: 坏文件应被跳过, 而不是让管理器炸掉
        import polyxrd.services.refinement_templates as rt

        mgr2 = rt.RefinementTemplateManager()
        assert mgr2.get_user_templates() == []

    def test_get_user_templates_returns_copy(self, manager):
        mgr, tdir = manager
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "t.json").write_text(
            json.dumps({"name": "t", "engine": "builtin"}), encoding="utf-8")
        import polyxrd.services.refinement_templates as rt

        mgr2 = rt.RefinementTemplateManager()
        got = mgr2.get_user_templates()
        got.clear()
        assert len(mgr2.get_user_templates()) == 1, "外部不应改坏管理器内部状态"

    def test_delete_missing_template_returns_false(self, manager):
        mgr, _tdir = manager
        assert mgr.delete_user_template("不存在的模板") is False

    def test_save_template_name_cannot_escape_dir(self, manager):
        mgr, tdir = manager
        tdir.mkdir(parents=True, exist_ok=True)
        evil = rt_template_name = "..\\..\\evil"
        t = mgr.create_from_config({}, name=evil)
        mgr.save_template(t)
        # 文件必须落在 templates 目录内 (名字被清洗), 不得写到上级
        outside = (tdir.parent.parent / "evil.json")
        assert not outside.exists(), f"模板名逃逸目录: {outside}"
        saved = list(tdir.glob("*.json"))
        assert saved and saved[0].parent == tdir
        # 用同一名字仍能取回 (save/load 用同一映射)
        loaded = mgr.load_template(evil)
        assert loaded is not None and loaded.name == evil
        assert mgr.delete_user_template(evil) is True
