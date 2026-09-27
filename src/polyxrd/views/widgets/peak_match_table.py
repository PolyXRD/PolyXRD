"""
峰-归属表 (M21)
===============
底部峰表: 每个实验峰的归属结果。
  - 已匹配行: 归属物相 (相色块 + 名)、Δ2θ、hkl
  - 未解释行: 整行浅红底, 归属列显示 "—未解释—"
行序按 2θ 升序。点行 → peak_row_clicked(two_theta) 信号。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                               QTableWidgetItem, QHeaderView,
                               QAbstractItemView)

from polyxrd.i18n import tr
from polyxrd.services.phase_display import PeakAssignment, phase_color


class PeakMatchTable(QWidget):
    """峰-物相归属表。"""

    peak_row_clicked = Signal(float)   # 点击某行 → 该峰 2θ

    # 表头 (语言相关, 故在构造时求值; "I"/"Δ2θ"/"hkl" 为通用记法, 无需翻译)
    @property
    def COLUMNS(self) -> list:
        return [
            tr("vw.peak_match_table.col_2theta"),
            tr("vw.peak_match_table.col_d"),
            "I",
            tr("vw.peak_match_table.col_phase"),
            "Δ2θ",
            "hkl",
        ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(tr("vw.peak_match_table.title"))
        lay.addWidget(self._title)
        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # S13 标记峰搜索: 允许多选行 → "仅对标记峰再匹配"
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setMinimumHeight(120)
        self._table.cellClicked.connect(self._on_cell_clicked)
        lay.addWidget(self._table)

    def set_assignments(self, assignments) -> None:
        """填充归属表。assignments 顺序可与峰不同, 行按 2θ 升序。"""
        ordered = sorted(assignments, key=lambda a: a.two_theta)
        self._assignments = ordered
        self._table.setRowCount(len(ordered))
        for row, a in enumerate(ordered):
            self._set_row(row, a)
        self._title.setText(tr("vw.peak_match_table.title_count", n=len(ordered)))

    def _set_row(self, row: int, a: PeakAssignment) -> None:
        cols = [
            f"{a.two_theta:.4f}",
            f"{a.d_spacing:.4f}" if a.d_spacing else "",
            f"{a.intensity:.1f}",
        ]
        is_unmatched = a.phase_index is None
        for c, text in enumerate(cols):
            it = QTableWidgetItem(text)
            if is_unmatched:
                it.setBackground(self._light_red())
            self._table.setItem(row, c, it)
        # 归属列 (色块 + 相名)
        if is_unmatched:
            it = QTableWidgetItem(tr("vw.peak_match_table.unexplained"))
            it.setBackground(self._light_red())
            it.setForeground(Qt.GlobalColor.red)
        else:
            it = QTableWidgetItem(f"● {a.phase_name}")
            it.setForeground(self._qcolor(phase_color(a.phase_index)))
        self._table.setItem(row, 3, it)
        # Δ2θ
        it_d = QTableWidgetItem(
            f"{a.delta_2theta:+.4f}" if a.delta_2theta is not None else "")
        it_d.setBackground(self._light_red() if is_unmatched else
                           it_d.background())
        self._table.setItem(row, 4, it_d)
        # hkl
        hkl_s = (f"({a.hkl[0]}{a.hkl[1]}{a.hkl[2]})" if a.hkl else "")
        it_h = QTableWidgetItem(hkl_s)
        it_h.setBackground(self._light_red() if is_unmatched else it_h.background())
        self._table.setItem(row, 5, it_h)

    def _on_cell_clicked(self, row, _col) -> None:
        if row < len(self._assignments):
            self.peak_row_clicked.emit(float(self._assignments[row].two_theta))

    def get_selected_two_thetas(self) -> list[float]:
        """选中行的 2θ 列表 (v2.2 S13 标记峰搜索的标记来源)。

        Returns:
            按 2θ 升序的标记 2θ 列表 (无选中 → 空表)
        """
        rows = sorted(set(i.row() for i in self._table.selectedItems()))
        return [float(self._assignments[r].two_theta)
                for r in rows if r < len(self._assignments)]

    def clear_table(self) -> None:
        self._table.setRowCount(0)
        self._assignments = []
        self._title.setText(tr("vw.peak_match_table.title"))

    def retranslate(self) -> None:
        """切语言时重设表头; 表体按已有归属重画一遍 (「未解释」这类字样在行里)。"""
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        if getattr(self, "_assignments", None):
            self.set_assignments(self._assignments)
        else:
            self._title.setText(tr("vw.peak_match_table.title"))

    # ── 颜色工具 ──────────────────────────────────────────
    @staticmethod
    def _qcolor(hex_color: str):
        from PySide6.QtGui import QColor
        return QColor(hex_color)

    @staticmethod
    def _light_red():
        from PySide6.QtGui import QColor
        return QColor("#FFEBEE")
