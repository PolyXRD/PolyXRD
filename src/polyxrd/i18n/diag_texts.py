"""
结构化诊断渲染 (v2.1-B)
========================
服务层 (rietveld_refiner 等) 只产出 ``{code, params}`` 结构化诊断条目,
**不产出任何界面文案** —— 文案统一在此用 ``tr()`` 按当前界面语言渲染。

诊断键约定 (三语言翻译文件中的 ``diag`` 段):
    diag.engine_fallback          引擎回退 {requested} → {used} (原因: {reason})
    diag.ka2_detected             Kα2 双线未剥离 {center:.2f}/{delta:.3f}/{ratio:.0f}
    diag.metrics_no_weights       未使用统计权重 → Rexp/GOF 不可解读
    diag.metrics_no_rexp          GSAS-II 未回传 Rexp/GOF
    diag.metrics_no_ycalc         GSAS-II 未回传计算谱
    diag.dw_correlated            残差逐点强相关 {dw:.2f}
    diag.high_angle_residual      高角区残差偏大 {high:.1f} vs {low:.1f}
    diag.low_angle_residual       低角区残差偏大 {low:.1f} vs {high:.1f}
    diag.residual_large           整体残差偏大 {r:.1f} (DW={dw:.2f})
"""
from __future__ import annotations

from typing import Any

from polyxrd.i18n.i18n_manager import tr

# 指标口径类诊断码 —— metric_note 的结构化来源
METRIC_NOTE_CODES = (
    "diag.metrics_no_weights",
    "diag.metrics_no_rexp",
    "diag.metrics_no_ycalc",
)


def _entries_of(result: Any) -> list[dict]:
    """从结果对象取结构化诊断条目 (缺字段/旧对象 → 空列表)。"""
    raw = getattr(result, "diagnostics", None) or []
    return [d for d in raw if isinstance(d, dict) and d.get("code")]


def render_entry(entry: dict) -> str:
    """渲染单条结构化诊断; 未知码回退为码名本身 (不抛异常)。"""
    code = str(entry.get("code", ""))
    params = entry.get("params") or {}
    try:
        return tr(code, **params)
    except Exception:  # noqa: BLE001 - 渲染失败不该打断结果展示
        return code


def render_diagnostics(result: Any) -> list[str]:
    """把结果里的结构化诊断渲染成本地化文案列表 (供结果区/执行日志展示)。"""
    return [render_entry(d) for d in _entries_of(result)]


def metric_note_text(result: Any) -> str:
    """指标口径提示:
    旧结果 (项目文件回读) 直接用已存的 ``metric_note`` 文本;
    新结果从结构化诊断里的指标类码渲染 —— 保证随界面语言切换。
    """
    note = getattr(result, "metric_note", "") or ""
    if note:
        return note
    for d in _entries_of(result):
        if d["code"] in METRIC_NOTE_CODES:
            return render_entry(d)
    return ""
