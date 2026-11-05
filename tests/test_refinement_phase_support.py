# -*- coding: utf-8 -*-
"""P2-10：份额有没有谱线支撑（``PHASE_UNSUPPORTED``）的守护测试。

背景（2026-11-05，``test_xrd/WO3`` 实测）：两相 Rietveld 把 W20O58 分到
15.6 wt%、Rwp 还降了 3.0 pp，但它最强判别线 24.66°（该相 I/Imax 0.67）在两条
谱上都是主峰 24.34° 的单调衰减尾巴。机理是大胞相自带独立峰宽参数，把样品展宽
造成的失配整块摊平 —— 份额、Rwp、各相 σ 三者都看不出这件事。

本文件锁两件事：
1. ``observed_peaks`` 用 prominence 而不是"绝对局部极大"，否则陡降峰尾上的
   噪声起伏会被当成峰；
2. ``_phase_support`` 只在"该相有唯一强线且一条都没出现"时才报，被其它相遮盖、
   含量过低的相要沉默 —— 误报比漏报更伤，用户会开始无视所有诊断。
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from polyxrd.refinement.report import (
    UNSUPPORTED_OBS_TOL,
    Finding,
    observed_peaks,
    prioritise,
)
from polyxrd.services.rietveld_refiner import _finding_log_lines, _v5_diagnostics

RNG = np.random.default_rng(20261105)

#: 主相「WO3」的强线（Cu Kα 2θ）与相对强度
MAIN_TT = np.array([23.11, 23.58, 24.35, 26.59, 28.61, 33.25, 34.09, 41.42])
MAIN_I = np.array([1.00, 0.55, 0.92, 0.30, 0.80, 0.45, 0.62, 0.25])

#: 「W20O58」：只有 24.66 / 24.01 / 22.75 三条是主相没有的
SUB_TT = np.array([23.52, 24.01, 24.66, 22.75, 32.77, 47.67])
SUB_I = np.array([1.00, 0.41, 0.67, 0.40, 0.27, 0.20])


def _pattern(x, centers, amps=None, width=0.12, bg=60.0, noise=2.0, shift=0.0):
    """在 ``centers`` 上铺高斯峰（``amps`` 缺省按 Imax 比例），加背景与噪声。"""
    y = np.full(x.shape, float(bg))
    if amps is None:
        amps = np.full(len(centers), 4000.0)
    for c, a in zip(centers, amps):
        y = y + a * np.exp(-0.5 * ((x - (c + shift)) / width) ** 2)
    return y + RNG.normal(0.0, noise, x.size)


def _quant(fracs, labels):
    from polyxrd.refinement.quantitative import QuantResult

    n = len(fracs)
    return QuantResult(labels=tuple(labels), fractions=tuple(fracs),
                       scales=(1.0,) * n, factor=(1.0,) * n, z=(1,) * n,
                       mass_per_cell=(1.0,) * n, volume=(1.0,) * n,
                       detectable=(True,) * n)


def _audit(x, y, phase_peaks, quant=None, calc_centers=None):
    from polyxrd.refinement.report import audit

    findings = audit(x, y, y, np.ones_like(x), quant=quant,
                     calc_centers=calc_centers, phase_peaks=phase_peaks)
    return {f.code: f for f in findings}


class TestObservedPeaks:
    """峰表判据：prominence 而不是绝对局部极大。"""

    def test_gaussian_peak_is_found(self):
        x = np.linspace(20.0, 30.0, 501)
        y = _pattern(x, [24.66], amps=np.array([3000.0]))
        found = [t for t, _ in observed_peaks(x, y)]
        assert min(abs(t - 24.66) for t in found) <= 0.05

    def test_steep_tail_noise_is_not_a_peak(self):
        """24.34° 主峰的衰减段：局部极大但**突出度≈0**，不能算峰。

        这正是第一版判据踩的坑 —— data1 的
        ``24.64:978 > 24.66:896 > 24.68:812`` 被"绝对局部极大"判成峰。
        这里把那个局部极大**构造出来**（在主峰尾巴上加一个 26 counts 的小包），
        保证测的不是随机噪声：局部极大一定成立，突出度一定为 0。
        """
        x = np.linspace(20.0, 30.0, 501)
        y = _pattern(x, [24.34], amps=np.array([4700.0]), width=0.10, noise=0.0)
        i = int(np.argmin(np.abs(x - 24.66)))
        y[i] += 26.0                       # 制造 24.64 < 24.66 > 24.68
        assert y[i] > y[i - 1] and y[i] > y[i + 1]
        found = [t for t, _ in observed_peaks(x, y)]
        assert not [t for t in found if abs(t - 24.66) <= 0.20]
        # 主峰本身仍必须被检到（否则说明判据把真峰也一起吃了）
        assert min(abs(t - 24.34) for t in found) <= 0.05

    def test_degenerate_inputs_return_empty(self):
        assert observed_peaks([], []) == []
        x = np.linspace(20.0, 21.0, 5)
        assert observed_peaks(x, np.ones(5)) == []
        x = np.linspace(20.0, 30.0, 200)
        assert observed_peaks(x, np.zeros_like(x)) == []

    def test_flat_pattern_has_no_peaks(self):
        x = np.linspace(20.0, 30.0, 400)
        assert observed_peaks(x, np.full_like(x, 100.0)) == []


class TestPhaseUnsupported:
    """``PHASE_UNSUPPORTED`` 的触发与沉默条件。"""

    def _setup(self, extra_centers=(), sub_frac=0.156, sub_tt=SUB_TT,
               sub_i=SUB_I, shift=0.0):
        x = np.linspace(20.0, 60.0, 2001)
        centers = np.concatenate([MAIN_TT, np.asarray(extra_centers, float)])
        amps = np.concatenate([4000.0 * MAIN_I,
                               4000.0 * np.ones(len(extra_centers)) * 0.6])
        y = _pattern(x, centers, amps, shift=shift)
        pp = [("WO3", MAIN_TT, MAIN_I), ("W20O58", np.asarray(sub_tt, float),
                                         np.asarray(sub_i, float))]
        q = _quant((1.0 - sub_frac, sub_frac), ("WO3", "W20O58"))
        return x, y, pp, q

    def test_warns_when_unique_strong_lines_absent(self):
        """WO3 实测的复刻：15.6 % 的 W20O58，24.66° 处只是主峰尾巴。"""
        x, y, pp, q = self._setup()
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_UNSUPPORTED" in f
        item = f["PHASE_UNSUPPORTED"]
        assert item.severity == "warn"
        assert item.evidence["phase"] == "W20O58"
        assert item.evidence["fraction"] == pytest.approx(0.156, abs=1e-9)
        # 最强唯一线应指向 24.66°，且不会被误报成主相
        assert item.evidence["strongest_2theta"] == pytest.approx(24.66, abs=0.05)
        assert item.evidence["n_unique_strong"] >= 1.0

    def test_silent_when_line_is_present(self):
        """把 24.66° 的真峰补进谱里 → 该相有支撑，不该再指控它。"""
        x, y, pp, q = self._setup(extra_centers=[24.66])
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_UNSUPPORTED" not in f

    def test_all_strong_lines_covered_reports_unverifiable(self):
        """强线全被别的相**更强的线**压住 → 不是"沉默"，而是"份额不可独立验证"。

        这条是端到端验收逼出来的：W20O58 的 5 条强线
        （23.55/24.39/24.36/34.16/23.05）全在 WO3 的 0.30° 以内（最小 0.03°），
        加权强度又被主相压约 5 倍，第一版直接 ``continue`` → 15.63 wt% 静默通过。
        """
        x = np.linspace(20.0, 60.0, 2001)
        y = _pattern(x, MAIN_TT, 4000.0 * MAIN_I)
        # 该相的强线全压在**主相最强**的三条线上，加权后被压 5 倍
        close = np.array([23.11, 23.58, 24.35]) + 0.05
        pp = [("WO3", MAIN_TT, MAIN_I), ("Covered", close, np.ones(close.size))]
        q = _quant((0.85, 0.15), ("WO3", "Covered"))
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_FRACTION_UNVERIFIABLE" in f
        item = f["PHASE_FRACTION_UNVERIFIABLE"]
        # 只许指控被压住的那一相，**主相自己不能中招**（第一版就撞了这个）
        assert item.evidence["phase"] == "Covered"
        assert item.evidence["min_gap"] <= 0.30
        # 不是"无支撑"那支 —— 两种证据要区分得清
        assert "PHASE_UNSUPPORTED" not in f

    def test_single_phase_never_reports_unverifiable(self):
        """单相没有"别的相"可比，绝不该报"全部重合"。"""
        x = np.linspace(20.0, 60.0, 2001)
        y = _pattern(x, MAIN_TT, 4000.0 * MAIN_I)
        pp = [("WO3", MAIN_TT, MAIN_I)]
        q = _quant((1.0,), ("WO3",))
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_FRACTION_UNVERIFIABLE" not in f
        assert "PHASE_UNSUPPORTED" not in f

    def test_trace_phase_is_not_blamed(self):
        """0.5 % 的相本来就只能报检出限，另有 PHASE_NOT_DETECTED/WEAK_PHASE 管。"""
        x, y, pp, q = self._setup(sub_frac=0.005)
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_UNSUPPORTED" not in f

    def test_without_phase_tables_no_finding(self):
        """没给各相反射表就不判 —— 单相问题不存在，也不能凭空的定罪。"""
        x, y, _pp, q = self._setup()
        f = _audit(x, y, None, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_UNSUPPORTED" not in f

    def test_silent_on_flat_pattern(self):
        """全平谱：峰表为空时不能把每个相都判成"无支撑"（那是峰表坏了）。"""
        x = np.linspace(20.0, 60.0, 2001)
        y = np.full_like(x, 120.0)
        pp = [("WO3", MAIN_TT, MAIN_I), ("W20O58", SUB_TT, SUB_I)]
        q = _quant((0.844, 0.156), ("WO3", "W20O58"))
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_UNSUPPORTED" not in f

    def test_zero_shift_is_compensated(self):
        """模型反射表是 Bragg 位置（不含仪器零点）；整体零点 +0.20° 时，
        仍在 24.86° 出现的真峰必须被认成 24.66° 那条线，而不是被判无支撑。"""
        x, y, pp, q = self._setup(extra_centers=[24.66], shift=0.20)
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert "PHASE_UNSUPPORTED" not in f

    def test_evidence_carries_zero_shift(self):
        x, y, pp, q = self._setup(shift=0.0)
        f = _audit(x, y, pp, quant=q, calc_centers=MAIN_TT)
        assert abs(f["PHASE_UNSUPPORTED"].evidence["zero_shift"]) < 0.05

    def test_obs_tol_is_documented_threshold(self):
        """常量本身要被用到（防止以后改判据时忘记同步容差语义）。"""
        assert 0.0 < UNSUPPORTED_OBS_TOL <= 0.35


# ── 界面只收 4 条：谁该露头 ─────────────────────────────────────────────
class TestPrioritise:
    """``prioritise``：同级内高价值码优先，别让无关 warn 把结论挤出去。

    起因（2026-11-05 实测四相拟合）：``audit`` 的排序键是
    ``(severity, code)``，全是 warn 时**纯按字母**，于是
    AT_BOUND / BACKGROUND_TREND / HIGH_CORRELATION 三条"改了也看不出"
    的提示占满前三，把 PHASE_FRACTION_UNVERIFIABLE（这份 wt% 到底能不
    能用）挤到第 4；再多一条 NEGATIVE_CALC 就静默丢了。
    """

    @staticmethod
    def _f(code, severity="warn", **ev):
        return Finding(code=code, severity=severity, message=code,
                       evidence=dict(ev))

    def test_high_value_beats_alphabetical(self):
        findings = [
            self._f("AT_BOUND"), self._f("BACKGROUND_TREND"),
            self._f("HIGH_CORRELATION"), self._f("NEGATIVE_CALC"),
            self._f("PHASE_FRACTION_UNVERIFIABLE"),
        ]
        got = [f.code for f in prioritise(findings, limit=4)]
        # 高价值两条（AT_BOUND / PHASE_FRACTION_UNVERIFIABLE）提到最前，
        # 且保持各自在传入序列里的先后（稳定排序）。
        assert got[:2] == ["AT_BOUND", "PHASE_FRACTION_UNVERIFIABLE"]
        assert "NEGATIVE_CALC" not in got       # 字母最靠前的那条让位

    def test_error_outranks_warn(self):
        findings = [self._f("PHASE_FRACTION_UNVERIFIABLE"),
                    self._f("RANK_DEFICIENT", "error")]
        assert [f.code for f in prioritise(findings, limit=1)] == [
            "RANK_DEFICIENT"]

    def test_info_never_reaches_ui(self):
        assert prioritise([self._f("AT_BOUND", "info")], limit=4) == []

    def test_same_weight_keeps_input_order(self):
        """同级同权重时用稳定排序，不因 sort 打乱（否则界面顺序随机跳动）。"""
        findings = [self._f(f"ZZ_{i}") for i in range(6)]
        assert [f.code for f in prioritise(findings, limit=2)] == [
            "ZZ_0", "ZZ_1"]


class TestServiceDiagnostics:
    """服务层 ``_v5_diagnostics``：``diagnostics`` 少而准，``v5_findings`` 不丢。"""

    @staticmethod
    def _report(*codes):
        return SimpleNamespace(findings=[
            Finding(code=c, severity="warn", message=c, evidence={"x": 1.0})
            for c in codes])

    def test_full_findings_preserved(self):
        rep = self._report("AT_BOUND", "PHASE_NOT_DETECTED")
        diag, full = _v5_diagnostics(rep)
        assert [d["code"] for d in full] == ["AT_BOUND", "PHASE_NOT_DETECTED"]
        assert len(diag) == 2

    def test_codes_carry_diag_prefix(self):
        """``render_diagnostics`` 按 ``tr(code)`` 查表，前缀少了界面就显码名。"""
        diag, _ = _v5_diagnostics(self._report("PHASE_UNSUPPORTED"))
        assert diag[0]["code"] == "diag.refinement.phase_unsupported"

    def test_noise_warns_do_not_crowd_out(self):
        rep = self._report("AT_BOUND", "BACKGROUND_TREND", "HIGH_CORRELATION",
                           "NEGATIVE_CALC", "PHASE_FRACTION_UNVERIFIABLE")
        diag, _ = _v5_diagnostics(rep)
        codes = [d["code"] for d in diag]
        assert len(codes) == 4                 # 仍然只收 4 条，不刷屏
        assert "diag.refinement.phase_fraction_unverifiable" in codes
        # 纯按字母的话 NEGATIVE_CALC 会挤进来、把"份额不可信"顶掉
        assert "diag.refinement.negative_calc" not in codes

    def test_string_evidence_does_not_kill_group(self):
        """``SCALE_CORRELATED`` 带相名（字符串）；旧代码一律 float() 会整组崩。"""
        f = Finding(code="SCALE_CORRELATED", severity="warn", message="m",
                    evidence={"phase": "WO3", "rho": -1.0})
        diag, _ = _v5_diagnostics(SimpleNamespace(findings=[f]))
        assert diag[0]["params"] == {"phase": "WO3", "rho": -1.0}

    def test_dropped_findings_reach_the_log(self):
        """P2-11：``diagnostics`` 只挂 4 条，剩下的一度**哪都看不到** ——
        ``fit_params["v5_findings"]`` 全仓库没有消费者，界面只读 diagnostics。
        现在全量进执行日志；这条锁住"被截掉的那条也在日志里且码名对得上"。"""
        rep = self._report("AT_BOUND", "BACKGROUND_TREND", "HIGH_CORRELATION",
                           "NEGATIVE_CALC", "PHASE_FRACTION_UNVERIFIABLE")
        diag, full = _v5_diagnostics(rep)
        lines = _finding_log_lines(full)
        assert len(lines) == 5                     # 全量，不是 4
        assert any("NEGATIVE_CALC" in ln for ln in lines)
        shown = {d["code"].rsplit(".", 1)[-1].upper() for d in diag}
        assert shown <= {ln.split()[2] for ln in lines}   # 界面码都能在日志里找到

    def test_log_line_is_technical_not_prose(self):
        """服务层日志不依赖 i18n：只写码名 + 数值，中文 message 不许混进去。"""
        f = Finding(code="AT_BOUND", severity="warn", message="参数撞界了",
                    evidence={"n_at_bound": 2, "note": "abc"})
        (line,) = _finding_log_lines([{**f.as_dict()}])
        assert "参数撞界了" not in line
        assert "n_at_bound=2" in line and "note=abc" in line
