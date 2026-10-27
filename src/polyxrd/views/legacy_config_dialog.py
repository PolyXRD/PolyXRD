"""
旧库配置迁移提示（v4.3.0 P4.3）
==============================

v4.2.0 删掉旧 COD sqlite 运行时后，配置文件里的旧键会留成"幽灵"（见
``services/legacy_config``）。本对话框只在**启动后检测到残留时弹一次**，
把"发现了什么 / 点一下会发生什么"讲清楚，然后给两个选择：

* **清理旧配置** —— 删掉旧键与失效挂载项（**不删库文件**），若某个旧路径
  其实是一份 polyDB 目录则顺手挂回来；
* **稍后再说** —— 一个版本内不再提示（记住位写回 ``user_db_paths.json``）。

刻意不做成多步向导：残留项通常 1–3 条，一次性摆清楚比翻页更快，也更容易
被截图给同事看。真正的"迁移"动作（把哪些库重新挂上）由用户在「数据库管理」
里决定，这里只清账。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from polyxrd.i18n import tr
from polyxrd.services.legacy_config import LegacyReport, describe


class LegacyConfigDialog(QDialog):
    """列出残留配置并提供"清理 / 稍后"。

    用 :meth:`ask` 而不是直接构造：调用方关心的是"用户选了哪个 + 要不要
    顺手挂回 polyDB"，不是控件本身。
    """

    #: ``ask()`` 的返回值 —— 用户点了「清理旧配置」。
    ACTION_CLEANUP = "cleanup"
    #: ``ask()`` 的返回值 —— 用户点了「稍后再说」。
    ACTION_LATER = "later"

    def __init__(self, report: LegacyReport,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("legacy_config.title"))
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)

        intro = QLabel(tr("legacy_config.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setPlainText("\n".join(describe(report)))
        self._details.setMinimumHeight(120)
        # 长路径用等宽字体更好读；不改全局样式，只挂在本控件上
        self._details.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self._details)

        existed = report.existing
        if existed:
            note = tr("legacy_config.files_note", count=len(existed),
                      mb=report.total_mb)
        else:
            note = tr("legacy_config.files_note_none")
        lbl_note = QLabel(note)
        lbl_note.setWordWrap(True)
        lbl_note.setStyleSheet("color: #666;")
        layout.addWidget(lbl_note)

        self._chk_remount = QCheckBox(tr("legacy_config.remount"))
        self._chk_remount.setChecked(True)
        # 独立记一份"有没有可救回的项"——对话框 accept 后自身已隐藏,
        # 用 isVisibleTo() 判断会误判为 False。
        self._has_recoverable = bool(report.recoverable)
        self._chk_remount.setVisible(self._has_recoverable)
        layout.addWidget(self._chk_remount)

        buttons = QDialogButtonBox()
        self._btn_clean = buttons.addButton(
            tr("legacy_config.btn_cleanup"),
            QDialogButtonBox.ButtonRole.AcceptRole)
        self._btn_clean.setToolTip(tr("legacy_config.btn_cleanup_tip"))
        btn_later = buttons.addButton(
            tr("legacy_config.btn_later"),
            QDialogButtonBox.ButtonRole.RejectRole)
        btn_later.setToolTip(tr("legacy_config.btn_later_tip"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setWindowModality(Qt.WindowModality.WindowModal)

    @property
    def remount_polydb(self) -> bool:
        """是否顺手把"其实是 polyDB"的旧路径挂回来（无可救回项时恒 False）。"""
        return bool(self._has_recoverable and self._chk_remount.isChecked())

    @classmethod
    def ask(cls, report: LegacyReport, parent: Optional[QWidget] = None,
            ) -> tuple[str, bool]:
        """弹出对话框，返回 ``(动作, 是否顺手挂回 polyDB)``。"""
        dlg = cls(report, parent)
        try:
            accepted = dlg.exec() == QDialog.DialogCode.Accepted
            return ((cls.ACTION_CLEANUP if accepted else cls.ACTION_LATER),
                    dlg.remount_polydb if accepted else False)
        finally:
            dlg.deleteLater()
