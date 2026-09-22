"""
报告视图
========
分析报告的预览和导出界面。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QTextEdit,
    QComboBox,
    QFileDialog,
    QLabel,
)

from polyxrd.i18n import tr
from polyxrd.viewmodels.main_vm import MainViewModel


class ReportView(QWidget):
    """报告预览和导出视图"""

    def __init__(self, vm: MainViewModel) -> None:
        super().__init__()
        self._vm = vm
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # 工具栏
        toolbar = QHBoxLayout()

        self._btn_preview = QPushButton(tr("vw.report_view.btn_preview"))
        self._btn_preview.clicked.connect(self._on_preview)
        toolbar.addWidget(self._btn_preview)

        toolbar.addWidget(QLabel(tr("vw.report_view.label_export_format")))
        self._format_combo = QComboBox()
        self._format_combo.addItems(["json", "txt", "csv", "all"])
        toolbar.addWidget(self._format_combo)

        self._btn_export = QPushButton(tr("vw.report_view.btn_export"))
        self._btn_export.clicked.connect(self._on_export)
        toolbar.addWidget(self._btn_export)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # 报告预览区
        report_group = QGroupBox(tr("vw.report_view.group_preview"))
        report_layout = QVBoxLayout()

        self._report_text = QTextEdit()
        self._report_text.setReadOnly(True)
        self._report_text.setFontFamily("Courier")
        report_layout.addWidget(self._report_text)

        report_group.setLayout(report_layout)
        main_layout.addWidget(report_group)

    def _setup_connections(self) -> None:
        self._vm.refinement_completed.connect(self._on_refinement_completed)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_preview(self) -> None:
        """生成报告预览"""
        result = self._vm.refinement_result
        if result is None:
            self._report_text.setPlainText(tr("vw.report_view.no_result"))
            return

        self._report_text.setPlainText(result.summary())

    def _on_export(self) -> None:
        """导出报告"""
        result = self._vm.refinement_result
        if result is None:
            return

        export_dir = QFileDialog.getExistingDirectory(self, tr("vw.report_view.export_dir_title"))
        if export_dir:
            self._vm.export_result(export_dir, format=self._format_combo.currentText())

    def _on_refinement_completed(self, result) -> None:
        """精修完成时自动更新报告"""
        self._on_preview()
