"""用户数据库管理对话框 (v2.6.0)
================================
用户把自己收集的 CIF 文件 (多选或整个文件夹) 导入一个本地库, 库里存的是
与「COD 无机物库」**同构**的表: d-I 峰表 / 预截断强峰列 / 原子坐标 / CIF 全文。

因此导入后的条目可以直接:
  · 在物相检索的「用户数据库」源里被 Hanawalt d-I 预筛命中;
  · 勾选后直接进内置 Rietveld / Le Bail 精修 (晶胞 + 原子坐标随 Phase 一起走);
  · 导出成 ``.sqlite`` 分发给同事, 对方「导入 sqlite」即可挂载使用。

本对话框只管这一组动作: 导入 (文件/文件夹) / 查看 / 删除 / 导出 / 清空。
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from polyxrd.i18n import tr
from polyxrd.services import user_db


class UserDatabaseDialog(QDialog):
    """用户自建 CIF 库: 导入 / 列表 / 删除 / 导出。"""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("user_db.title"))
        self.setMinimumSize(880, 560)
        self._entries: list[dict] = []
        self._build()
        self._refresh()

    # ── 构建 ──────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        intro = QLabel(tr("user_db.intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet("color: palette(mid);")
        root.addWidget(intro)

        self._stats = QLabel("—")
        self._stats.setWordWrap(True)
        self._stats.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._stats)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_files = QPushButton(tr("user_db.btn_import_files"))
        self._btn_files.clicked.connect(self._on_import_files)
        self._btn_folder = QPushButton(tr("user_db.btn_import_folder"))
        self._btn_folder.clicked.connect(self._on_import_folder)
        self._btn_export = QPushButton(tr("user_db.btn_export"))
        self._btn_export.clicked.connect(self._on_export)
        self._btn_delete = QPushButton(tr("user_db.btn_delete"))
        self._btn_delete.clicked.connect(self._on_delete_selected)
        self._btn_clear = QPushButton(tr("user_db.btn_clear"))
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_refresh = QPushButton(tr("user_db.btn_refresh"))
        self._btn_refresh.clicked.connect(self._refresh)
        for b in (self._btn_files, self._btn_folder, self._btn_export,
                  self._btn_delete, self._btn_clear, self._btn_refresh):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            tr("user_db.col_id"), tr("user_db.col_formula"),
            tr("user_db.col_sg"), tr("user_db.col_cell"),
            tr("user_db.col_peaks"), tr("user_db.col_source"),
        ])
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        head = self._table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, stretch=1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        btns = QDialogButtonBox()
        close_btn = btns.addButton(tr("common.close"),
                                   QDialogButtonBox.ButtonRole.AcceptRole)
        close_btn.clicked.connect(self.accept)
        root.addWidget(btns)

    # ── 刷新 ──────────────────────────────────────────────
    def _refresh(self) -> None:
        st = user_db.user_stats()
        if not st["exists"]:
            self._stats.setText(tr("user_db.stats_none", path=st["path"]))
        else:
            self._stats.setText(
                tr("user_db.stats", rows=st["rows"], size=st["size_mb"],
                   path=st["path"]))

        entries = user_db.list_entries()
        self._entries = entries
        self._table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            cell = ""
            try:
                cell = (f"{float(e['cell_a']):.4f} / {float(e['cell_b']):.4f} / "
                        f"{float(e['cell_c']):.4f}")
            except (TypeError, ValueError):
                cell = ""
            vals = [
                e.get("display_id") or "",
                e.get("formula") or "",
                e.get("space_group") or "",
                cell,
                str(e.get("n_peaks") or 0),
                e.get("source_file") or "",
            ]
            for c, v in enumerate(vals):
                self._table.setItem(r, c, QTableWidgetItem(str(v)))

        has = bool(entries)
        for b in (self._btn_export, self._btn_delete, self._btn_clear):
            b.setEnabled(has)
        if not has:
            self._status.setText(tr("user_db.list_empty"))

    # ── 导入 ──────────────────────────────────────────────
    def _on_import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("user_db.import_files_title"),
            str(Path.home()), tr("user_db.file_filter"))
        if paths:
            self._import(paths, tr("user_db.import_files_title"))

    def _on_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, tr("user_db.import_folder_title"), str(Path.home()))
        if folder:
            self._import_folder(folder)

    def _import_folder(self, folder: str) -> None:
        """导入文件夹 (不递归; 子目录请多选或分次导入)。"""
        cifs = sorted(
            [p for p in Path(folder).glob("*.cif")],
            key=lambda p: p.name.lower())
        if not cifs:
            QMessageBox.information(
                self, tr("user_db.import_folder_title"),
                tr("user_db.folder_empty", folder=folder))
            return
        self._import([str(p) for p in cifs], tr("user_db.import_folder_title"))

    def _import(self, paths: list[str], title: str) -> None:
        total = len(paths)
        # 逐文件解析 + 模拟 XRD 峰表是长任务 (几百个 CIF 分钟级), 必须有
        # 进度反馈; 但**不给取消** —— 服务层按批 commit, 中途打断会留下
        # 半批条目, 与其给一个假取消按钮不如老实显示进度。
        dlg = QProgressDialog(tr("user_db.importing"), "", 0, total, self)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.setValue(0)

        def on_progress(done: int, all_: int, name: str) -> None:
            dlg.setMaximum(all_)
            dlg.setValue(done)
            dlg.setLabelText(tr("user_db.importing_name", name=name,
                                done=done + 1, total=all_))
            QApplication.processEvents()

        try:
            report = user_db.import_cif_files(paths, progress=on_progress)
        except Exception as e:  # noqa: BLE001 - 导入失败要如实告诉用户
            dlg.close()
            QMessageBox.critical(self, tr("user_db.import_failed"),
                                 str(e))
            return
        dlg.setValue(total)
        dlg.close()

        self._refresh()
        self.changed.emit()
        msg = tr("user_db.import_done_body",
                 ok=len(report.imported),
                 dup=len(report.skipped_dup),
                 fail=len(report.failed))
        if report.failed:
            detail = "\n".join(f"· {n}: {why}" for n, why in report.failed[:8])
            if len(report.failed) > 8:
                detail += "\n…"
            msg += "\n\n" + tr("user_db.import_failed_list") + "\n" + detail
        self._status.setText(tr("user_db.last_import",
                                ok=len(report.imported),
                                dup=len(report.skipped_dup),
                                fail=len(report.failed)))

        box = QMessageBox(self)
        box.setWindowTitle(tr("user_db.import_done"))
        box.setText(msg)
        box.setIcon(QMessageBox.Icon.Information
                    if not report.failed else QMessageBox.Icon.Warning)
        box.exec()

    # ── 导出 / 删除 / 清空 ────────────────────────────────
    def _on_export(self) -> None:
        default = str(Path.home() / "user_phases.sqlite")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("user_db.export_title"), default,
            tr("user_db.sqlite_filter"))
        if not path:
            return
        self._export(path)

    def _export(self, path: str) -> None:
        try:
            dest = user_db.export_user_db(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("user_db.export_failed"), str(e))
            return
        try:
            size = os.path.getsize(dest) / 1e6
        except OSError:
            size = 0.0
        QMessageBox.information(
            self, tr("user_db.export_ok"),
            tr("user_db.export_ok_body", path=str(dest), size=f"{size:.1f}"))

    def _selected_ids(self) -> list[int]:
        by_display = {e.get("display_id"): int(e["cod_id"]) for e in self._entries}
        ids = []
        for idx in self._table.selectionModel().selectedRows():
            item = self._table.item(idx.row(), 0)
            if item is None:
                continue
            uid = by_display.get(item.text())
            if uid is not None:
                ids.append(uid)
        return ids

    def _on_delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, tr("user_db.btn_delete"),
                                    tr("user_db.select_none"))
            return
        if QMessageBox.question(
            self, tr("user_db.btn_delete"),
            tr("user_db.delete_confirm", n=len(ids)),
        ) != QMessageBox.StandardButton.Yes:
            return
        n = user_db.remove_entries(ids)
        self._refresh()
        self.changed.emit()
        self._status.setText(tr("user_db.delete_done", n=n))

    def _on_clear(self) -> None:
        if QMessageBox.question(
            self, tr("user_db.btn_clear"), tr("user_db.clear_confirm"),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            user_db.clear_user_db()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("user_db.btn_clear"), str(e))
            return
        self._refresh()
        self.changed.emit()
        self._status.setText(tr("user_db.clear_done"))
