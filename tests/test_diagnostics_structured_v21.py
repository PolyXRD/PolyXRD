"""v2.1-B: 服务层诊断结构化 + i18n 补齐 (回归测试)
==================================================
验收口径 (docs/后续计划与已知问题-v2.1.md):
  - 服务层只产出 {code, params} 结构化诊断, 不再生成中文文案;
  - 三语言翻译文件各有 diag.* 键组, en/ja 下渲染结果无中文残留;
  - 诊断随项目文件/模型序列化往返不丢。
"""
from __future__ import annotations

import re

from polyxrd.i18n.diag_texts import (
    METRIC_NOTE_CODES,
    metric_note_text,
    render_diagnostics,
    render_entry,
)
from polyxrd.i18n.i18n_manager import I18nManager
from polyxrd.models.refinement import RefinementResult

# CJK 统一表意文字 + 假名 (残留扫描口径)
_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

ALL_CODES = [
    ("diag.engine_fallback", {"requested": "gsas2", "used": "builtin",
                              "reason": "RuntimeError: boom"}),
    ("diag.ka2_detected", {"center": 36.25, "delta": 0.093, "ratio": 42.0}),
    ("diag.metrics_no_weights", {}),
    ("diag.metrics_no_rexp", {}),
    ("diag.metrics_no_ycalc", {}),
    ("diag.dw_correlated", {"dw": 0.72}),
    ("diag.high_angle_residual", {"high": 21.3, "low": 4.1}),
    ("diag.low_angle_residual", {"low": 18.2, "high": 5.0}),
    ("diag.residual_large", {"r": 12.6, "dw": 1.31}),
    ("diag.weight_basis_relative", {"phases": "LiNiO2, ZnO"}),
]


def test_all_diag_codes_rendered_cjk_free_in_en_and_ja():
    """en 下渲染无 CJK 残留; ja 下与 zh 渲染不同 (证明键存在、未回退中文)。"""
    mgr = I18nManager()
    _orig = mgr.current_language
    try:
        zh_texts = {}
        mgr.set_language("zh_CN")
        for code, params in ALL_CODES:
            zh_texts[code] = render_entry({"code": code, "params": params})
            assert zh_texts[code] != code, code          # zh 键必须存在
        for lang in ("en_US", "ja_JP"):
            mgr.set_language(lang)
            for code, params in ALL_CODES:
                text = render_entry({"code": code, "params": params})
                assert text != code, (lang, code)        # 键必须存在
                assert text != zh_texts[code], (lang, code, text)
                if lang == "en_US":
                    assert not _CJK.search(text), (lang, code, text)
    finally:
        mgr.set_language(_orig)


def test_render_diagnostics_and_metric_note():
    """render_diagnostics / metric_note_text 走结构化条目。"""
    result = RefinementResult(
        metrics_valid=False,
        diagnostics=[
            {"code": "diag.engine_fallback",
             "params": {"requested": "gsas2", "used": "builtin",
                        "reason": "boom"}},
            {"code": "diag.metrics_no_weights", "params": {}},
        ],
    )
    texts = render_diagnostics(result)
    assert len(texts) == 2
    assert all(t for t in texts)
    note = metric_note_text(result)
    assert note
    assert note in texts


def test_metric_note_falls_back_to_stored_text_for_old_projects():
    """旧项目文件回读: metric_note 已存文本优先 (兼容历史中文文案)。"""
    result = RefinementResult(
        metric_note="旧版中文提示",
        diagnostics=[{"code": "diag.metrics_no_weights", "params": {}}],
    )
    assert metric_note_text(result) == "旧版中文提示"


def test_metric_note_codes_registry():
    """指标类诊断码注册表与翻译键一致。"""
    for code in METRIC_NOTE_CODES:
        assert code.startswith("diag.metrics_")


def test_roundtrip_preserves_diagnostics():
    """to_dict/from_dict 往返保留结构化诊断; 非法条目被过滤。"""
    rr = RefinementResult(
        diagnostics=[
            {"code": "diag.ka2_detected",
             "params": {"center": 36.25, "delta": 0.093, "ratio": 42.0}},
            {"code": "diag.dw_correlated", "params": {"dw": 0.72}},
        ],
        warnings=["legacy text kept"],
    )
    d = rr.to_dict()
    rr2 = RefinementResult.from_dict(d)
    assert rr2.diagnostics == rr.diagnostics
    assert rr2.warnings == ["legacy text kept"]
    # 非法条目 (无 code / 非 dict) 在 from_dict 侧被丢弃
    bad = RefinementResult.from_dict({
        "diagnostics": [{"params": {}}, "junk", {"code": "diag.dw_correlated",
                                                 "params": {"dw": 1.0}}],
    })
    assert [x["code"] for x in bad.diagnostics] == ["diag.dw_correlated"]
