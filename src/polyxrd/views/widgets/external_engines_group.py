"""外部精修程序配置/启动区 (v0.15 M25-2)
==========================================

挂入精修页右栏 ``_ext_group`` 容器 (M24-4)。每个外部引擎一行::

    [状态灯] 名称 [路径 QLineEdit] [浏览…] [检测] [启动]

- 路径改动即校验并持久化 (``~/.polyxrd/external_tools.json``);
- 状态灯: 绿=路径可用 (用户配置或自动探测), 红=配置了但不可用,
  灰=未配置;
- 「检测」= 重新自动探测并回填;
- 「启动」= FullProf 走批处理精修 (信号交精修页执行), GSAS-II/MAUD
  为 GUI 拉起 (Popen, 非阻塞, "导出+拉起" 降级语义)。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from polyxrd.config import get_config
from polyxrd.i18n import tr
from polyxrd.services.external_tools import (
    ALL_SPECS,
    FULLPROF_SPEC,
    GSAS2_SPEC,
    MAUD_SPEC,
    ToolSpec,
    resolve_tool,
)

_LIGHT_OK = "color: #2ecc71; font-size: 15px;"
_LIGHT_BAD = "color: #e74c3c; font-size: 15px;"
_LIGHT_OFF = "color: #888; font-size: 15px;"


class ExternalEnginesGroup(QGroupBox):
    """三引擎配置/启动面板。"""

    # (fp_exe_path) — FullProf 批处理精修请求, 由精修页在忙碌闸门内执行
    fullprof_requested = Signal(str)
    # 日志行 → 精修日志区
    log_message = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(tr("vw.external_engines_group.title"), parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._rows: dict[str, dict] = {}
        for spec in ALL_SPECS:
            row = self._build_row(spec)
            self._rows[spec.key] = row
            layout.addLayout(row["layout"])

        self._context_provider: Optional[Callable] = None
        self.refresh_status()

    # ── 上下文注入 ────────────────────────────────────────────
    def set_context_provider(self, provider: Callable) -> None:
        """注入 ``() -> (XRDData|None, selected_phases)`` 提供者。"""
        self._context_provider = provider

    # ── 行构建 ────────────────────────────────────────────────
    def _build_row(self, spec: ToolSpec) -> dict:
        row = QHBoxLayout()

        light = QLabel("●")
        light.setStyleSheet(_LIGHT_OFF)
        light.setToolTip(
            tr("vw.external_engines_group.status_tip", title=spec.title)
        )
        row.addWidget(light)

        title = QLabel(spec.title)
        title.setFixedWidth(64)
        row.addWidget(title)

        edit = QLineEdit()
        edit.setPlaceholderText(tr("vw.external_engines_group.placeholder"))
        edit.editingFinished.connect(
            lambda s=spec, e=edit: self._on_path_edited(s, e)
        )
        row.addWidget(edit, stretch=1)

        btn_browse = QPushButton(tr("vw.external_engines_group.browse"))
        btn_browse.clicked.connect(lambda _=False, s=spec, e=edit: self._on_browse(s, e))
        row.addWidget(btn_browse)

        btn_detect = QPushButton(tr("vw.external_engines_group.detect"))
        btn_detect.setToolTip(tr("vw.external_engines_group.detect_tip"))
        btn_detect.clicked.connect(lambda _=False, s=spec: self._on_detect(s))
        row.addWidget(btn_detect)

        btn_run = QPushButton(
            tr("vw.external_engines_group.start_refine")
            if spec is FULLPROF_SPEC
            else tr("vw.external_engines_group.launch_gui")
        )
        btn_run.setToolTip(
            tr("vw.external_engines_group.run_tip", title=spec.title)
        )
        btn_run.clicked.connect(lambda _=False, s=spec: self._on_launch(s))
        row.addWidget(btn_run)

        return {"layout": row, "light": light, "edit": edit,
                "browse": btn_browse, "detect": btn_detect, "run": btn_run,
                "spec": spec}

    # ── 状态 ──────────────────────────────────────────────────
    def refresh_status(self) -> None:
        """重读配置并刷新每行状态灯/路径显示。"""
        for key, row in self._rows.items():
            spec: ToolSpec = row["spec"]
            path, source = resolve_tool(spec)
            edit = row["edit"]
            if source == "user":
                edit.setText(str(path))
            elif source == "auto" and not edit.text().strip():
                edit.setPlaceholderText(
                    tr("vw.external_engines_group.detected_placeholder", path=path)
                )
            if path is not None and spec.validate(path):
                light_style, tip = _LIGHT_OK, tr("vw.external_engines_group.status_ok")
            elif get_config().get_external_tool_path(spec.key):
                light_style, tip = _LIGHT_BAD, tr("vw.external_engines_group.status_bad")
            else:
                light_style, tip = _LIGHT_OFF, tr("vw.external_engines_group.status_off")
            row["light"].setStyleSheet(light_style)
            row["light"].setToolTip(
                tr("vw.external_engines_group.light_tip", title=spec.title, tip=tip)
            )

    # ── 槽 ────────────────────────────────────────────────────
    def retranslate(self) -> None:
        """切语言时重设分组标题 / 每行按钮与提示 (引擎名本身是专有名词, 不翻)。"""
        self.setTitle(tr("vw.external_engines_group.title"))
        for row in self._rows.values():
            spec: ToolSpec = row["spec"]
            row["edit"].setPlaceholderText(
                tr("vw.external_engines_group.placeholder"))
            row["browse"].setText(tr("vw.external_engines_group.browse"))
            row["detect"].setText(tr("vw.external_engines_group.detect"))
            row["detect"].setToolTip(tr("vw.external_engines_group.detect_tip"))
            row["run"].setText(
                tr("vw.external_engines_group.start_refine")
                if spec is FULLPROF_SPEC
                else tr("vw.external_engines_group.launch_gui")
            )
            row["run"].setToolTip(
                tr("vw.external_engines_group.run_tip", title=spec.title))
        # 状态灯提示里有本地化的"可用/不可用"字样 → 重跑一次状态刷新
        self.refresh_status()

    def _on_path_edited(self, spec: ToolSpec, edit: QLineEdit) -> None:
        text = edit.text().strip()
        if text:
            get_config().set_external_tool_path(spec.key, text)
        self.refresh_status()

    def _on_browse(self, spec: ToolSpec, edit: QLineEdit) -> None:
        start = edit.text().strip() or str(get_config().get_external_tool_path(spec.key) or "")
        path, _ = QFileDialog.getOpenFileName(
            self, tr("vw.external_engines_group.select_exe", title=spec.title), start,
            tr("vw.external_engines_group.exe_filter")
        )
        if path:
            edit.setText(path)
            get_config().set_external_tool_path(spec.key, path)
            self.refresh_status()

    def _on_detect(self, spec: ToolSpec) -> None:
        auto = spec.detect_fn() if spec.detect_fn else None
        if auto is not None:
            get_config().set_external_tool_path(spec.key, str(auto))
            self.log_message.emit(
                tr("vw.external_engines_group.log_detected", title=spec.title, path=auto)
            )
        else:
            self.log_message.emit(
                tr("vw.external_engines_group.log_not_detected", title=spec.title)
            )
        self.refresh_status()

    def _on_launch(self, spec: ToolSpec) -> None:
        path, _src = resolve_tool(spec)
        if path is None:
            self.log_message.emit(
                tr("vw.external_engines_group.log_unavailable", title=spec.title))
            return

        data, phases = None, []
        if self._context_provider is not None:
            try:
                data, phases = self._context_provider()
            except Exception:  # noqa: BLE001
                data, phases = None, []
        if data is None:
            self.log_message.emit(tr("vw.external_engines_group.log_need_data"))
            return
        if not phases:
            self.log_message.emit(tr("vw.external_engines_group.log_need_phases"))
            return

        try:
            if spec is FULLPROF_SPEC:
                # 批处理精修: 交精修页在忙碌闸门内执行 (M25-6)
                self.fullprof_requested.emit(str(path))
            elif spec is GSAS2_SPEC:
                from polyxrd.services.fullprof.runner import new_run_dir
                from polyxrd.services.launchers.gsas2_launcher import launch_gui

                wd = new_run_dir("gsas2")
                self.log_message.emit(
                    tr("vw.external_engines_group.log_gsas2_wd", wd=wd)
                )
                launch_gui(data, phases, wd, on_log=self.log_message.emit)
            elif spec is MAUD_SPEC:
                from polyxrd.services.fullprof.runner import new_run_dir
                from polyxrd.services.launchers.maud_launcher import launch_gui

                wd = new_run_dir("maud")
                self.log_message.emit(
                    tr("vw.external_engines_group.log_maud_wd", wd=wd)
                )
                launch_gui(data, phases, wd, custom=str(path) if path else None,
                           on_log=self.log_message.emit)
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(
                tr("vw.external_engines_group.log_launch_failed",
                   title=spec.title, exc=exc)
            )
