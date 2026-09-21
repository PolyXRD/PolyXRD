"""批量精修对话框 (v0.11.0 GSAS-II 通道打磨)。

对文件夹内全部衍射数据文件, 用同一组物相 (当前已选相的深拷贝) 顺序精修,
汇总 Rwp / Rexp / Rb / GOF / wt% 到表格, 可导出 CSV。引擎默认 auto
(全相有结构 CIF 且装了 GSAS-II 时自动走真 Rietveld)。
"""
from __future__ import annotations

import copy
import csv
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from polyxrd.i18n import tr

DATA_PATTERNS = ("*.txt", "*.dat", "*.xye", "*.xy", "*.csv")


class BatchRefinementWorker(QThread):
    """逐文件精修工作线程 (每个文件用物相的独立深拷贝)."""

    file_done = Signal(str, dict)      # 文件名, 结果行
    file_failed = Signal(str, str)     # 文件名, 错误
    progress = Signal(int, int)        # 完成/总数
    all_done = Signal()

    def __init__(
        self,
        files: list[Path],
        phases: list,
        engine: str = "auto",
        max_cycles: int = 20,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._files = files
        self._phases = phases
        self._engine = engine
        self._max_cycles = max_cycles
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from polyxrd.services.data_loader import DataLoader
        from polyxrd.services.rietveld_refiner import RietveldRefiner

        loader = DataLoader()
        refiner = RietveldRefiner()
        total = len(self._files)
        for i, f in enumerate(self._files):
            if self._cancelled:
                break
            try:
                data = loader.load(f)
                # 每个文件从干净物相出发 (refine 会回写 lattice/wt)
                result = refiner.refine(
                    data,
                    copy.deepcopy(self._phases),
                    engine=self._engine,
                    max_cycles=self._max_cycles,
                )
                row = {
                    "Rwp": result.Rwp,
                    "Rexp": getattr(result, "Rexp", 0.0),
                    "Rb": getattr(result, "Rb", 0.0),
                    "GOF": result.GOF,
                    "engine": result.fit_params.get("engine", "?"),
                    "note": result.fit_params.get("engine_fallback_reason", ""),
                    "phases": [
                        (p.name, round(p.weight_fraction, 2))
                        for p in result.phases
                    ],
                }
                self.file_done.emit(f.name, row)
            except Exception as e:  # 单文件失败不影响批次
                self.file_failed.emit(f.name, str(e))
            self.progress.emit(i + 1, total)
        self.all_done.emit()


class BatchRefinementDialog(QDialog):
    """批量精修对话框"""

    def __init__(self, phases: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("batch_refine.title"))
        self.setMinimumSize(720, 480)
        self._phases = phases
        self._worker: BatchRefinementWorker | None = None
        self._rows: list[dict] = []
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(tr("batch_refine.intro"))
        info.setWordWrap(True)
        layout.addWidget(info)

        # 文件夹行
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr("batch_refine.folder")))
        self._folder_edit = QComboBox()
        self._folder_edit.setEditable(True)
        folder_row.addWidget(self._folder_edit, 1)
        btn_browse = QPushButton(tr("batch_refine.browse"))
        btn_browse.clicked.connect(self._on_browse)
        folder_row.addWidget(btn_browse)
        btn_scan = QPushButton(tr("batch_refine.scan"))
        btn_scan.clicked.connect(self._on_scan)
        folder_row.addWidget(btn_scan)
        layout.addLayout(folder_row)

        # 参数行
        param_row = QHBoxLayout()
        param_row.addWidget(QLabel(tr("batch_refine.engine")))
        self._engine_combo = QComboBox()
        self._engine_combo.addItems(["auto", "gsas2", "maud", "builtin", "powerxrd"])
        param_row.addWidget(self._engine_combo)
        param_row.addWidget(QLabel(tr("batch_refine.cycles")))
        self._cycles_spin = QSpinBox()
        self._cycles_spin.setRange(1, 200)
        self._cycles_spin.setValue(20)
        param_row.addWidget(self._cycles_spin)
        self._run_btn = QPushButton(tr("batch_refine.run"))
        self._run_btn.clicked.connect(self._on_run)
        param_row.addWidget(self._run_btn)
        self._cancel_btn = QPushButton(tr("batch_refine.cancel"))
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        param_row.addWidget(self._cancel_btn)
        param_row.addStretch(1)
        layout.addLayout(param_row)

        self._progress = QProgressBar()
        layout.addWidget(self._progress)

        # 结果表
        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        # 底部按钮
        bottom = QHBoxLayout()
        self._status = QLabel("")
        bottom.addWidget(self._status, 1)
        btn_csv = QPushButton(tr("batch_refine.export_csv"))
        btn_csv.clicked.connect(self._on_export_csv)
        bottom.addWidget(btn_csv)
        btn_close = QPushButton(tr("batch_refine.close"))
        btn_close.clicked.connect(self.reject)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    # ── 交互 ──────────────────────────────────────────────────────
    def _on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("batch_refine.folder"))
        if d:
            self._folder_edit.setCurrentText(d)

    def _on_scan(self) -> None:
        folder = Path(self._folder_edit.currentText().strip())
        if not folder.is_dir():
            QMessageBox.warning(
                self, tr("batch_refine.title"), tr("batch_refine.no_folder")
            )
            return
        files = sorted(
            p for pat in DATA_PATTERNS for p in folder.glob(pat)
        )
        self._status.setText(
            tr("batch_refine.found", n=len(files), folder=str(folder))
        )
        self._scan_count = len(files)

    def _on_run(self) -> None:
        if not self._phases:
            QMessageBox.warning(
                self, tr("batch_refine.title"), tr("batch_refine.no_phases")
            )
            return
        folder = Path(self._folder_edit.currentText().strip())
        if not folder.is_dir():
            QMessageBox.warning(
                self, tr("batch_refine.title"), tr("batch_refine.no_folder")
            )
            return
        files = sorted(
            p for pat in DATA_PATTERNS for p in folder.glob(pat)
        )
        if not files:
            QMessageBox.warning(
                self, tr("batch_refine.title"), tr("batch_refine.no_files")
            )
            return

        self._rows = []
        self._table.clear()
        self._table.setRowCount(0)
        self._progress.setRange(0, len(files))
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._worker = BatchRefinementWorker(
            files,
            self._phases,
            engine=self._engine_combo.currentText(),
            max_cycles=self._cycles_spin.value(),
        )
        self._worker.file_done.connect(self._on_file_done)
        self._worker.file_failed.connect(self._on_file_failed)
        self._worker.progress.connect(self._on_progress)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _on_file_done(self, name: str, row: dict) -> None:
        row["file"] = name
        row["error"] = ""
        self._rows.append(row)
        self._append_table_row(row)

    def _on_file_failed(self, name: str, err: str) -> None:
        row = {"file": name, "error": err, "Rwp": None, "Rexp": None,
               "Rb": None, "GOF": None,
               "engine": "-", "note": "", "phases": []}
        self._rows.append(row)
        self._append_table_row(row)

    def _on_progress(self, done: int, total: int) -> None:
        self._progress.setValue(done)
        self._status.setText(f"{done} / {total}")

    def _on_all_done(self) -> None:
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        ok = sum(1 for r in self._rows if not r.get("error"))
        self._status.setText(
            tr("batch_refine.done", ok=ok, total=len(self._rows))
        )

    # ── 表格 / 导出 ───────────────────────────────────────────────
    def _append_table_row(self, row: dict) -> None:
        phase_names: list[str] = []
        for name, _ in row.get("phases", []):
            if name not in phase_names:
                phase_names.append(name)
        # 列结构: 文件 | Rwp | Rexp | Rb | GOF | 引擎 | 各相 wt% ... | 备注
        headers = self._current_headers(phase_names)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        r = self._table.rowCount()
        self._table.insertRow(r)

        def setitem(c: int, text: str) -> None:
            self._table.setItem(r, c, QTableWidgetItem(text))

        c = 0
        setitem(c, row.get("file", "")); c += 1
        setitem(c, f"{row['Rwp']:.2f}" if row.get("Rwp") is not None else "-"); c += 1
        setitem(c, f"{row['Rexp']:.2f}" if row.get("Rexp") is not None else "-"); c += 1
        setitem(c, f"{row['Rb']:.2f}" if row.get("Rb") is not None else "-"); c += 1
        setitem(c, f"{row['GOF']:.3f}" if row.get("GOF") is not None else "-"); c += 1
        setitem(c, str(row.get("engine", "-"))); c += 1
        wt_map = dict(row.get("phases", []))
        for pn in phase_names:
            wt = wt_map.get(pn)
            setitem(c, f"{wt:.2f}" if wt is not None else "-"); c += 1
        note = row.get("note", "")
        if row.get("error"):
            note = f"{tr('batch_refine.error')}: {row['error']}"
        setitem(c, note)
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )

    def _current_headers(self, phase_names: list[str]) -> list[str]:
        headers = [
            tr("batch_refine.col_file"),
            "Rwp%",
            "Rexp%",
            "Rb%",
            "GOF",
            tr("batch_refine.col_engine"),
        ]
        headers += [f"{pn} wt%" for pn in phase_names]
        headers.append(tr("batch_refine.col_note"))
        return headers

    def _on_export_csv(self) -> None:
        if not self._rows:
            QMessageBox.information(
                self, tr("batch_refine.title"), tr("batch_refine.nothing_to_export")
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("batch_refine.export_csv"), "batch_refine.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        # 列: 文件, Rwp, Rexp, Rb, GOF, 引擎, 各相 wt%, 备注/错误
        all_phase_names: list[str] = []
        for row in self._rows:
            for name, _ in row.get("phases", []):
                if name not in all_phase_names:
                    all_phase_names.append(name)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                ["file", "Rwp_percent", "Rexp_percent", "Rb_percent", "GOF", "engine"]
                + [f"{n}_wt_percent" for n in all_phase_names]
                + ["note"]
            )
            for row in self._rows:
                wt_map = dict(row.get("phases", []))
                w.writerow(
                    [
                        row.get("file", ""),
                        row.get("Rwp"),
                        row.get("Rexp"),
                        row.get("Rb"),
                        row.get("GOF"),
                        row.get("engine", ""),
                        *[wt_map.get(n, "") for n in all_phase_names],
                        row.get("note") or row.get("error") or "",
                    ]
                )
        self._status.setText(tr("batch_refine.exported", path=path))

    # 停止线程再关
    def reject(self) -> None:  # noqa: D102
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().reject()
