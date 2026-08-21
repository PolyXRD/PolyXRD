"""
元素过滤对话框
==============
弹出式元素周期表过滤对话框。
用户选择元素后，通过 accepted 信号返回过滤条件。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QDialogButtonBox,
)

from polyxrd.views.widgets.element_periodic_table import ElementPeriodicTable


class ElementFilterDialog(QDialog):
    """元素过滤对话框
    
    Signals:
        filter_changed: 过滤条件变更
    """
    
    filter_changed = Signal(dict)
    
    def __init__(self, parent=None, initial_filter: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("元素过滤 - 三态选择")
        self.setMinimumSize(900, 600)
        self.resize(1000, 650)
        
        self._table = ElementPeriodicTable()
        
        if initial_filter:
            self._table.set_selection(
                must=initial_filter.get("must", []),
                maybe=initial_filter.get("maybe", []),
                exclude=initial_filter.get("exclude", []),
            )
        
        self._table.selection_changed.connect(self._on_selection_changed)
        
        layout = QVBoxLayout(self)
        layout.addWidget(self._table, stretch=1)
        
        # 图例
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(self._make_legend_item("必须", "#4caf50"))
        legend_layout.addWidget(self._make_legend_item("可能", "#ffc107"))
        legend_layout.addWidget(self._make_legend_item("不含", "#f44336"))
        legend_layout.addStretch()
        layout.addLayout(legend_layout)
        
        # 当前选择摘要
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet(
            "QLabel { font-size: 12px; padding: 8px; "
            "background-color: #f5f5f5; border-radius: 4px; }"
        )
        layout.addWidget(self._summary_label)
        self._update_summary()
        
        # 按钮
        btn_layout = QHBoxLayout()
        
        self._btn_clear = QPushButton("清空选择")
        self._btn_clear.clicked.connect(self._on_clear)
        btn_layout.addWidget(self._btn_clear)
        
        btn_layout.addStretch()
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        btn_layout.addWidget(button_box)
        
        layout.addLayout(btn_layout)
    
    def _make_legend_item(self, text: str, color: str) -> QLabel:
        """创建图例项"""
        label = QLabel(f"  {text}")
        label.setStyleSheet(
            f"QLabel {{ background-color: {color}; color: white; "
            f"padding: 4px 12px; border-radius: 4px; font-size: 12px; }}"
        )
        return label
    
    def _on_selection_changed(self, must, maybe, exclude) -> None:
        self._update_summary()
        self.filter_changed.emit(self.get_filter_dict())
    
    def _update_summary(self) -> None:
        must, maybe, exclude = self._table.get_selection()
        parts = []
        if must:
            parts.append(f"<b>必须:</b> {', '.join(must)}")
        if maybe:
            parts.append(f"<b>可能:</b> {', '.join(maybe)}")
        if exclude:
            parts.append(f"<b>不含:</b> {', '.join(exclude)}")
        
        if parts:
            self._summary_label.setText("当前过滤: " + " | ".join(parts))
        else:
            self._summary_label.setText("当前过滤: 未选择任何元素 (将使用全库搜索)")
    
    def _on_clear(self) -> None:
        self._table.reset()
    
    def get_filter_dict(self) -> dict:
        """获取过滤条件"""
        return self._table.get_filter_dict()
    
    def get_selection(self) -> tuple:
        """获取选择状态"""
        return self._table.get_selection()