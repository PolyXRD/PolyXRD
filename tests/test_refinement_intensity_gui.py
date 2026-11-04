# -*- coding: utf-8 -*-
"""精修向导的系统性强度误差控件（v5.2，offscreen Qt）。

验收口径
--------
1. **默认全关**：开向导不改任何行为，`refine()` 收到的仍是"未启用"。
2. **控件 → 配置 → 引擎**：勾选/填半径要真的写进 ``_refinement_config["params"]``，
   键名与 ``refine()`` 的 kwargs 一致（``roughness_model`` / ``refine_roughness``
   / ``microabsorption`` / ``grain_radius_um``）。
3. **未勾微吸收时半径必须是 0**：否则引擎会拿一个"没打算用"的半径去算 τ。
4. **clamped 必须看得见**：`_update_microabsorption_note` 在
   ``fit_params["microabsorption_clamped"]`` 为真时显示醒目告警，而不是照常报 wt%
   —— τ 不进拟合向量，Rwp 反映不出半径给错了（基准报告 §22.6 / §22.8）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from polyxrd.i18n import tr
from polyxrd.models.refinement import RefinementResult


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def wizard(qapp):
    from polyxrd.views.refinement_wizard import RefinementWizard

    w = RefinementWizard()
    yield w
    w.close()
    w.deleteLater()


def _params(wizard) -> dict:
    return dict(wizard._refinement_config.get("params") or {})


class TestIntensityControls:
    def test_default_is_off(self, wizard):
        p = _params(wizard)
        assert p["roughness_model"] == "none"
        assert p["refine_roughness"] is False
        assert p["microabsorption"] is False
        assert p["grain_radius_um"] == 0.0

    def test_roughness_toggle_writes_params(self, wizard):
        wizard._chk_roughness.setChecked(True)
        p = _params(wizard)
        assert p["roughness_model"] == "sidey"
        # 幅度精修是二级开关：勾了模型才有意义
        assert wizard._chk_roughness_refine.isEnabled()
        wizard._chk_roughness_refine.setChecked(True)
        assert _params(wizard)["refine_roughness"] is True

        wizard._chk_roughness.setChecked(False)
        p = _params(wizard)
        assert p["roughness_model"] == "none"
        assert p["refine_roughness"] is False
        assert not wizard._chk_roughness_refine.isEnabled()

    def test_microabsorption_needs_radius(self, wizard):
        assert not wizard._spin_grain_radius.isEnabled()
        wizard._chk_microabsorption.setChecked(True)
        assert wizard._spin_grain_radius.isEnabled()
        wizard._spin_grain_radius.setValue(12.5)
        p = _params(wizard)
        assert p["microabsorption"] is True
        assert p["grain_radius_um"] == pytest.approx(12.5)

        # 取消勾选 → 半径归 0（"没打算用"的半径不能漏给引擎）
        wizard._chk_microabsorption.setChecked(False)
        p = _params(wizard)
        assert p["microabsorption"] is False
        assert p["grain_radius_um"] == 0.0

    def test_radius_is_clamped_to_widget_range(self, wizard):
        wizard._chk_microabsorption.setChecked(True)
        wizard._spin_grain_radius.setValue(1e6)
        assert _params(wizard)["grain_radius_um"] <= 200.0

    def test_template_params_do_not_clobber_other_keys(self, wizard):
        """``params`` 里模板带来的其它键不能被控件同步冲掉。"""
        wizard._refinement_config["params"] = {"quick_scan": True}
        wizard._chk_microabsorption.setChecked(True)
        p = _params(wizard)
        assert p["quick_scan"] is True
        assert p["microabsorption"] is True

    def test_load_params_roundtrip(self, wizard):
        wizard._load_intensity_params({
            "roughness_model": "sidey", "refine_roughness": True,
            "microabsorption": True, "grain_radius_um": 4.0,
        })
        assert wizard._chk_roughness.isChecked()
        assert wizard._chk_roughness_refine.isChecked()
        assert wizard._chk_microabsorption.isChecked()
        p = _params(wizard)
        assert p["roughness_model"] == "sidey"
        assert p["grain_radius_um"] == pytest.approx(4.0)

        wizard._load_intensity_params({})
        p = _params(wizard)
        assert p["roughness_model"] == "none"
        assert p["microabsorption"] is False


class TestClampedWarning:
    def _result(self, **fit_params) -> RefinementResult:
        return RefinementResult(wR=12.0, GOF=1.2, fit_params=dict(fit_params))

    def test_clamped_shows_warning(self, wizard):
        wizard._update_microabsorption_note(self._result(
            microabsorption_tau=[2.036, 0.496], microabsorption_mu_bar=603.0,
            microabsorption_clamped=True, grain_radius_um=25.0))
        assert wizard._label_microabsorption.text() == tr("intensity_note.clamped")
        assert "c0392b" in wizard._label_microabsorption.styleSheet()

    def test_applied_reports_tau_range(self, wizard):
        wizard._update_microabsorption_note(self._result(
            microabsorption_tau=[0.99, 1.248], microabsorption_mu_bar=272.3,
            microabsorption_clamped=False, grain_radius_um=10.0))
        text = wizard._label_microabsorption.text()
        assert "272" in text and "1.25" in text
        assert wizard._label_microabsorption.styleSheet() == ""

    def test_disabled_says_not_enabled(self, wizard):
        wizard._update_microabsorption_note(self._result())
        assert wizard._label_microabsorption.text() == tr("intensity_note.off")

    def test_roughness_only_reports_s(self, wizard):
        wizard._update_microabsorption_note(self._result(
            roughness_model="sidey", roughness_s=0.123))
        assert "0.123" in wizard._label_microabsorption.text()


# ----------------------------------------------------------------------
# 主精修页 (refinement_view) —— 与向导共用同一组开关与同一份文案
# ----------------------------------------------------------------------


@pytest.fixture()
def refine_view(qapp):
    from polyxrd.viewmodels.main_vm import MainViewModel
    from polyxrd.views.refinement_view import RefinementView

    v = RefinementView(MainViewModel())
    yield v
    v.close()
    v.deleteLater()


class TestMainPageControls:
    """主精修页直接点"开始精修"时也必须能拿到这两个开关。"""

    def test_default_is_off(self, refine_view):
        p = refine_view._intensity_params()
        assert p == {
            "roughness_model": "none",
            "refine_roughness": False,
            "microabsorption": False,
            "grain_radius_um": 0.0,
        }

    def test_reachable_in_wizard_style(self, refine_view):
        """默认就勾着"按向导方式" —— 这几个控件若被一起置灰, 功能等于没做。"""
        assert refine_view._chk_wizard.isChecked() is True
        assert refine_view._chk_roughness.isEnabled() is True
        assert refine_view._chk_microabsorption.isEnabled() is True

    def test_toggle_writes_kwargs(self, refine_view):
        refine_view._chk_roughness.setChecked(True)
        assert refine_view._chk_roughness_refine.isEnabled() is True
        refine_view._chk_roughness_refine.setChecked(True)
        p = refine_view._intensity_params()
        assert p["roughness_model"] == "sidey"
        assert p["refine_roughness"] is True

        refine_view._chk_microabsorption.setChecked(True)
        assert refine_view._spin_grain_radius.isEnabled() is True
        refine_view._spin_grain_radius.setValue(8.0)
        assert refine_view._intensity_params()["grain_radius_um"] == pytest.approx(8.0)

        refine_view._chk_microabsorption.setChecked(False)
        assert refine_view._intensity_params()["grain_radius_um"] == 0.0
        assert not refine_view._spin_grain_radius.isEnabled()

    def test_radius_is_clamped_to_widget_range(self, refine_view):
        refine_view._chk_microabsorption.setChecked(True)
        refine_view._spin_grain_radius.setValue(1e6)
        assert refine_view._intensity_params()["grain_radius_um"] <= 200.0

    def test_refine_forwards_intensity_kwargs(self, refine_view, monkeypatch):
        """``_on_refine`` 组装的 kwargs 必须真的带上四个键 (向导档也一样)。"""
        seen: dict = {}

        def _fake_refine_structure(**kwargs):
            seen.update(kwargs)

        monkeypatch.setattr(
            refine_view._vm, "refine_structure", _fake_refine_structure
        )
        refine_view._chk_microabsorption.setChecked(True)
        refine_view._spin_grain_radius.setValue(15.0)
        refine_view._on_refine()  # 默认向导档
        assert seen["microabsorption"] is True
        assert seen["grain_radius_um"] == pytest.approx(15.0)
        assert seen["roughness_model"] == "none"


class TestMainPageClampedAlert:
    def _view(self, refine_view):
        return refine_view

    def _result(self, **fit_params) -> RefinementResult:
        return RefinementResult(wR=12.0, GOF=1.2, fit_params=dict(fit_params))

    def test_clamped_turns_alert_red(self, refine_view):
        refine_view._on_refinement_completed(self._result(
            microabsorption_tau=[2.036, 0.496], microabsorption_mu_bar=603.0,
            microabsorption_clamped=True, grain_radius_um=25.0))
        assert refine_view._label_microabsorption.text() == tr("intensity_note.clamped")
        assert "c0392b" in refine_view._label_microabsorption.styleSheet()
        # 提示条必须从"琥珀提示"切到"红色告警", 且告警里出现这条 finding
        assert "#fdecea" in refine_view._label_alert.styleSheet()
        assert refine_view._label_alert.isVisible() or refine_view._label_alert.text()

    def test_applied_reports_tau_range(self, refine_view):
        refine_view._on_refinement_completed(self._result(
            microabsorption_tau=[0.99, 1.248], microabsorption_mu_bar=272.3,
            microabsorption_clamped=False, grain_radius_um=10.0))
        text = refine_view._label_microabsorption.text()
        assert "272" in text and "1.25" in text
        assert refine_view._label_microabsorption.styleSheet() == ""
        # 表内 → 提示条退回普通琥珀色
        assert "#fff4d6" in refine_view._label_alert.styleSheet()

    def test_disabled_says_not_enabled(self, refine_view):
        refine_view._on_refinement_completed(self._result())
        assert refine_view._label_microabsorption.text() == tr("intensity_note.off")

