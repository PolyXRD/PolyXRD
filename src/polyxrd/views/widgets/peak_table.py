"""
峰列表控件
==========
显示检测到的峰列表。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QToolBar,
    QAbstractItemView,
)

from polyxrd.i18n import tr
from polyxrd.models.peak import Peak


class PeakTable(QWidget):
    """峰列表表格控件

    Features:
    - 显示峰的2θ、d-spacing、强度、FWHM、hkl等信息
    - 支持排序、筛选
    - 支持选择单个或多个峰
    - 支持编辑峰的hkl和物相
    - 支持删除峰
    - 支持导出CSV

    Signals:
        peak_selected: 选中峰
        peak_deleted: 峰被删除
    """

    peak_selected = Signal(object)
    peak_deleted = Signal(object)

    # 表头 (语言相关, 故在构造时求值; "hkl" 为通用记法, 无需翻译)
    @property
    def COLUMNS(self) -> list:
        return [
            tr("vw.peak_table.col_id"),
            tr("vw.peak_table.col_2theta"),
            tr("vw.peak_table.col_d"),
            tr("vw.peak_table.col_intensity"),
            tr("vw.peak_table.col_fwhm"),
            "hkl",
            tr("vw.peak_table.col_phase"),
        ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._peaks: list[Peak] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏 (留引用: 切语言时按当前语言重设文案)
        self._toolbar = QToolBar()
        self._act_del_selected = self._toolbar.addAction(
            tr("vw.peak_table.act_del_selected"), self._on_delete_selected)
        self._act_clear = self._toolbar.addAction(
            tr("vw.peak_table.act_clear"), self._on_clear)
        self._act_export_csv = self._toolbar.addAction(
            tr("vw.peak_table.act_export_csv"), self._on_export_csv)
        layout.addWidget(self._toolbar)

        # 表格
        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._table.setSortingEnabled(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellChanged.connect(self._on_cell_changed)

        # M20 v2: 右键菜单 (复制 / 删除 / 清空 / 导出)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self._table)

    def retranslate(self) -> None:
        """切语言时重设表头与工具栏文案 (不动已加载的峰数据)。"""
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._act_del_selected.setText(tr("vw.peak_table.act_del_selected"))
        self._act_clear.setText(tr("vw.peak_table.act_clear"))
        self._act_export_csv.setText(tr("vw.peak_table.act_export_csv"))

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def set_peaks(self, peaks) -> None:
        """设置峰列表 (接受 PeakList 或 list[Peak])"""
        if hasattr(peaks, "peaks"):
            peaks = peaks.peaks
        self._peaks = list(peaks)
        self._reload_table()

    def add_peak(self, peak: Peak) -> None:
        """添加单个峰"""
        self._peaks.append(peak)
        self._reload_table()

    def get_selected_peaks(self) -> list[Peak]:
        """获取选中的峰"""
        selected_rows = set()
        for item in self._table.selectedItems():
            selected_rows.add(item.row())

        return [self._peaks[row] for row in selected_rows if row < len(self._peaks)]

    def get_all_peaks(self) -> list[Peak]:
        """获取所有峰"""
        return self._peaks.copy()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _reload_table(self) -> None:
        """重新加载表格

        排序必须在填充期间关闭: sortingEnabled 下逐格 setItem 会触发
        实时重排, 导致后续 setItem 落错行 / 丢格 (显示错乱, 复制/读取
        亦错)。填充完再恢复排序。
        """
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._peaks))

        for row, peak in enumerate(self._peaks):
            self._set_table_item(row, 0, str(row + 1))
            self._set_table_item(row, 1, f"{peak.two_theta:.4f}")
            self._set_table_item(row, 2, f"{peak.d_spacing:.4f}")
            self._set_table_item(row, 3, f"{peak.intensity:.1f}")
            self._set_table_item(row, 4, f"{peak.fwhm:.4f}")
            self._set_table_item(row, 5, peak.hkl_str)
            self._set_table_item(row, 6, peak.phase)

        self._table.setSortingEnabled(True)

    def _set_table_item(self, row: int, col: int, text: str) -> None:
        """设置单元格内容"""
        item = QTableWidgetItem(text)
        if col == 0:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, col, item)

    def _on_selection_changed(self) -> None:
        """选中变更"""
        selected = self.get_selected_peaks()
        if selected:
            self.peak_selected.emit(selected[0])

    def _on_cell_changed(self, row: int, col: int) -> None:
        """单元格内容变更"""
        if row >= len(self._peaks):
            return

        item = self._table.item(row, col)
        if item is None:
            return

        text = item.text()
        peak = self._peaks[row]

        # 更新峰属性
        try:
            if col == 5:  # hkl
                hkl = self._parse_hkl(text)
                if hkl:
                    peak.hkl = hkl
            elif col == 6:  # phase
                peak.phase = text
        except Exception:
            pass

    def _on_delete_selected(self) -> None:
        """删除选中峰"""
        selected_rows = sorted(set(
            item.row() for item in self._table.selectedItems()
        ), reverse=True)

        for row in selected_rows:
            if row < len(self._peaks):
                self.peak_deleted.emit(self._peaks[row])
                del self._peaks[row]

        self._reload_table()

    # ------------------------------------------------------------------
    # 右键菜单 (M20 v2)
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        """峰表右键菜单: 复制选中行 / 删除 / 清空 / 导出CSV。"""
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        has_sel = bool(self._table.selectedItems())
        act_copy = menu.addAction(tr("vw.peak_table.act_copy_row"))
        act_copy.setEnabled(has_sel)
        act_del = menu.addAction(tr("vw.peak_table.act_del_selected"))
        act_del.setEnabled(has_sel)
        menu.addSeparator()
        menu.addAction(tr("vw.peak_table.act_clear"), self._on_clear)
        menu.addSeparator()
        menu.addAction(tr("vw.peak_table.act_export_csv"), self._on_export_csv)

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is act_del:
            self._on_delete_selected()
        elif chosen is act_copy:
            self._copy_selected_to_clipboard()

    def _copy_selected_to_clipboard(self) -> None:
        """把选中行以 TSV 复制到剪贴板 (可直接粘贴到 Excel)。"""
        from PySide6.QtGui import QGuiApplication

        rows = sorted(set(item.row() for item in self._table.selectedItems()))
        lines = ["\t".join(self.COLUMNS)]
        for row in rows:
            cells = []
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                cells.append(item.text() if item is not None else "")
            lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _on_clear(self) -> None:
        """清空所有峰"""
        self._peaks.clear()
        self._reload_table()

    def _on_export_csv(self) -> None:
        """导出CSV"""
        from PySide6.QtWidgets import QFileDialog
        import csv

        path, _ = QFileDialog.getSaveFileName(
            self, tr("vw.peak_table.dlg_export_peaks_caption"), "peaks.csv",
            tr("vw.peak_table.dlg_export_peaks_filter")
        )
        if path:
            # v1.1.1: 表头随界面语言本地化 (中文/日文), 因此必须带 BOM 写入,
            # 否则 Excel / WPS 按系统 ANSI 代码页解释会全是乱码。
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(self.COLUMNS)
                for row, peak in enumerate(self._peaks):
                    writer.writerow([
                        row + 1,
                        f"{peak.two_theta:.4f}",
                        f"{peak.d_spacing:.4f}",
                        f"{peak.intensity:.1f}",
                        f"{peak.fwhm:.4f}",
                        peak.hkl_str,
                        peak.phase,
                    ])

    @staticmethod
    def _parse_hkl(text: str) -> Optional[tuple[int, int, int]]:
        """解析hkl字符串 (如 '111', '(1,0,0)')"""
        text = text.strip().replace("(", "").replace(")", "")
        if "," in text:
            parts = text.split(",")
            if len(parts) == 3:
                return tuple(int(p.strip()) for p in parts)
        elif len(text) == 3 and text.isdigit():
            return (int(text[0]), int(text[1]), int(text[2]))
        return None
