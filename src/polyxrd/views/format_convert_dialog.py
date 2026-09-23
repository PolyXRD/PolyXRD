"""
谱图格式转换对话框
==================
挂在「文件 → 打开」下面的格式转换入口: 把受支持的谱图文件另存为另一种扩展名。

只做**一件事** —— 读源文件、按目标格式写出; 是否把结果载入主界面由调用方决定。
真正的读写实现都在 ``services.pattern_convert``, 这里只负责交互。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from polyxrd.i18n import tr
from polyxrd.services.data_io import DataFormatError
from polyxrd.services.pattern_convert import (
    TARGET_EXTS,
    TARGET_FORMATS,
    convert_pattern_file,
    load_pattern,
)


def _row(*widgets: QWidget) -> QWidget:
    """把若干控件打包成一行 (QFormLayout.addRow 需要 widget 而不是 layout)。"""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    for i, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if i == 0 else 0)
    return box


class FormatConvertDialog(QDialog):
    """谱图文件格式转换。

    Args:
        parent: 父窗口
        source: 预填的源文件 (通常传当前数据的源文件路径)

    Attributes:
        result_path: 转换成功后写出的文件路径 (取消/失败时为 None)
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        source: Optional[Union[str, Path]] = None,
    ) -> None:
        super().__init__(parent)
        self.result_path: Optional[Path] = None
        self.setWindowTitle(tr("convert.title"))
        self.setMinimumWidth(620)
        self._build_ui()
        if source:
            self._source.setText(str(source))
        self._on_source_changed()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        hint = QLabel(tr("convert.hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._source = QLineEdit()
        self._source.setPlaceholderText(tr("convert.source_placeholder"))
        self._source.editingFinished.connect(self._on_source_changed)
        btn_src = QPushButton(tr("convert.browse"))
        btn_src.clicked.connect(self._on_browse_source)
        form.addRow(tr("convert.source"), _row(self._source, btn_src))

        self._format = QComboBox()
        for key, ext in TARGET_FORMATS:
            self._format.addItem(f"{tr('convert.fmt.' + key)}  (*{ext})", key)
        self._format.currentIndexChanged.connect(self._sync_output)
        form.addRow(tr("convert.target"), self._format)

        self._output = QLineEdit()
        self._output.setPlaceholderText(tr("convert.output_placeholder"))
        btn_dst = QPushButton(tr("convert.browse"))
        btn_dst.clicked.connect(self._on_browse_output)
        form.addRow(tr("convert.output"), _row(self._output, btn_dst))

        root.addLayout(form)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        root.addWidget(self._info)

        buttons = QDialogButtonBox()
        self._run_btn = buttons.addButton(
            tr("convert.run"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(
            tr("common.cancel"), QDialogButtonBox.ButtonRole.RejectRole
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def _current_format(self) -> str:
        return str(self._format.currentData() or "xy")

    def _on_source_changed(self) -> None:
        self._sync_output()
        self._preview()

    def _sync_output(self) -> None:
        """源文件/目标格式一变就跟着改输出路径。

        只换扩展名, 保留用户在源文件(或自己挑过的输出路径)上的目录与主名 ——
        这样"选好去处再改格式"不会把用户填的目录冲掉。
        """
        ext = TARGET_EXTS.get(self._current_format(), "")
        if not ext:
            return
        current = self._output.text().strip()
        src = self._source.text().strip()
        raw = current or src
        # ⚠️ 必须判 `raw` 而不是判 `str(Path(raw))`: `Path("")` 是 `Path(".")`,
        # 它的 str() 是 "." (真值!) 而 `Path(".").with_suffix(".xy")` 会抛
        # `ValueError: WindowsPath('.') has an empty name` —— 旧的写法让
        # "未加载数据时打开格式转换对话框" 直接崩在构造阶段 (source=None 时
        # 源/目标都为空)。这里两处都空就只能放弃自动填输出路径。
        if not raw:
            return
        self._output.setText(str(Path(raw).with_suffix(ext)))

    def _preview(self) -> None:
        """源文件可用时先读一遍, 把点数与 2θ 范围显示出来 (读不动就说明原因)。"""
        src = self._source.text().strip()
        if not src or not Path(src).exists():
            self._info.setText("")
            return
        try:
            data = load_pattern(src)
        except Exception as exc:  # noqa: BLE001 - 预览失败不影响继续选格式
            self._info.setText(tr("convert.preview_failed", error=str(exc)))
            return
        self._info.setText(
            tr(
                "convert.preview",
                n=len(data),
                x0=f"{float(data.two_theta[0]):.3f}",
                x1=f"{float(data.two_theta[-1]):.3f}",
            )
        )

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _start_dir(self) -> str:
        src = self._source.text().strip()
        if src:
            parent = Path(src).parent
            if parent.exists():
                return str(parent)
        return str(Path.home())

    def _on_browse_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("convert.choose_source"),
            self._start_dir(),
            tr("dialog.file_filter"),
        )
        if path:
            self._source.setText(path)
            self._on_source_changed()

    def _on_browse_output(self) -> None:
        key = self._current_format()
        ext = TARGET_EXTS.get(key, "")
        current = self._output.text().strip() or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("convert.choose_output"),
            current,
            f"{tr('convert.fmt.' + key)} (*{ext})",
        )
        if path:
            self._output.setText(path)

    def _on_accept(self) -> None:
        src = self._source.text().strip()
        dst = self._output.text().strip()
        if not src:
            QMessageBox.warning(
                self, tr("dialog.warning"), tr("convert.need_source")
            )
            return
        if not Path(src).exists():
            QMessageBox.warning(
                self, tr("dialog.warning"), tr("convert.source_missing", path=src)
            )
            return
        if not dst:
            QMessageBox.warning(
                self, tr("dialog.warning"), tr("convert.need_output")
            )
            return

        key = self._current_format()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.result_path = convert_pattern_file(src, dst, key)
        except (DataFormatError, OSError, ValueError) as exc:
            QMessageBox.critical(
                self, tr("dialog.error"), tr("convert.failed", error=str(exc))
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        QMessageBox.information(
            self,
            tr("dialog.info"),
            tr("convert.done", path=str(self.result_path)),
        )
        self.accept()
