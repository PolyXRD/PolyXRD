"""外挂数据库管理对话框 (0.10.0)
================================
0.10.0 起发布包不再内置数据库。用户单独下载数据库后在这里导入:
  文件 → 校验 (是不是对的库、有多少相、列齐不齐) → 持久化路径。
导入后立即清缓存并通知主窗口刷新数据源下拉, 无需重启。

设计取舍: 校验失败时**不静默失败也不只弹一句"格式错误"**, 而是尽量告诉
用户"这个文件其实是 PDF2 库 / 缺了 peaks_d 列", 并且如果它确实是另一类
合法库, 直接问"要不要导入到对应槽位"。外挂库这事最容易踩的坑就是
拿错文件, 而拿错文件原本是不会报错的 (COD 无机物库与 PDF2 库表名同为
`phases`, 拿混了只会静默检索不到东西)。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from polyxrd.i18n import tr
from polyxrd.services import db_import
from polyxrd.services.db_import import DB_KINDS, inspect_db_file

_FILE_FILTER = "SQLite 数据库 (*.sqlite *.sqlite3 *.db);;所有文件 (*)"


class DatabaseManagerDialog(QDialog):
    """外挂数据库管理: 查看 / 导入 / 清除三个库槽位。"""

    databases_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("db_manager.title"))
        self.setMinimumWidth(760)
        self._rows: dict[str, dict] = {}
        self._build()
        self._refresh()

    # ── 构建 ──────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(tr("db_manager.intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet("color: palette(mid);")
        root.addWidget(intro)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        root.addLayout(grid)

        for i, kind in enumerate(DB_KINDS):
            self._build_row(grid, i, kind)

        root.addStretch(1)

        btns = QDialogButtonBox()
        self._btn_recheck = btns.addButton(
            tr("db_manager.recheck"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_recheck.clicked.connect(self._refresh)
        close_btn = btns.addButton(
            tr("common.close"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        close_btn.clicked.connect(self.accept)
        root.addWidget(btns)

    def _build_row(self, grid: QGridLayout, row: int, kind) -> None:
        name = QLabel(f"<b>{tr(kind.label_key)}</b>")
        name.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        status = QLabel("—")
        status.setWordWrap(True)
        status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        path_lbl = QLabel("—")
        path_lbl.setStyleSheet("color: palette(mid);")
        path_lbl.setWordWrap(True)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(status)
        info.addWidget(path_lbl)
        pkg_lbl = QLabel("—")
        pkg_lbl.setStyleSheet("color: palette(mid);")
        pkg_lbl.setWordWrap(True)
        pkg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.addWidget(pkg_lbl)

        # 授权/合规提示 (目前只有 PDF2-2004 需要): 该库是 ICDD 的商业数据库,
        # 我们只做格式转换与离线索引、不附带任何授权, 所以把"请确认正版授权"
        # 直接摆在导入按钮旁边 —— 用户是在这里点的「导入…」, 提示放这里才有用。
        notice_key = getattr(kind, "notice_key", "")
        if notice_key:
            notice = QLabel(tr(notice_key))
            notice.setWordWrap(True)
            notice.setStyleSheet("color: #b9770e;")
            notice.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            info.addWidget(notice)

        info_w = QWidget()
        info_w.setLayout(info)

        btn_import = QPushButton(tr("db_manager.import"))
        btn_import.clicked.connect(lambda _=False, k=kind.key: self._on_import(k))
        btn_clear = QPushButton(tr("db_manager.clear"))
        btn_clear.clicked.connect(lambda _=False, k=kind.key: self._on_clear(k))
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addWidget(btn_import)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)
        btn_w = QWidget()
        btn_w.setLayout(btn_row)

        grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(info_w, row, 1)
        grid.addWidget(btn_w, row, 2, Qt.AlignmentFlag.AlignTop)
        self._rows[kind.key] = {
            "status": status, "path": path_lbl, "clear": btn_clear,
            "pkg": pkg_lbl,
        }

    # ── 刷新 ──────────────────────────────────────────────
    def _refresh(self) -> None:
        for st in db_import.slot_states():
            row = self._rows.get(st["kind"])
            if row is None:
                continue
            row["clear"].setEnabled(st["imported"])
            row["path"].setText(st["path"] or "—")
            # 三个库各自独立打包下载 —— 把"这个槽位该下哪个包"写死在行里,
            # 否则用户面对三个槽位只能靠文件名猜。
            row["pkg"].setText(
                tr("db_manager.pkg_hint",
                   pkg=st["pkg_name"], file=st["pkg_filename"])
            )
            if not st["exists"]:
                row["status"].setText(f"<span style='color:#c0392b'>"
                                      f"{tr('db_manager.status_missing')}</span>")
                row["path"].setText(tr("db_manager.no_path"))
                continue
            if st["ok"]:
                extra = ""
                if st["has_top_peaks"]:
                    extra = " · " + tr("db_manager.has_top_peaks")
                src = (tr("db_manager.src_imported") if st["imported"]
                       else tr("db_manager.src_default"))
                row["status"].setText(
                    f"<span style='color:#1e8449'>{tr('db_manager.status_ok')}"
                    f"</span> · {st['rows']:,} · {st['size_mb']} MB"
                    f" · {src}{extra}"
                )
            else:
                reason = st["error"] or "unknown"
                if st["hint"]:
                    reason += f" ({st['hint']})"
                row["status"].setText(
                    f"<span style='color:#c0392b'>{tr('db_manager.status_bad')}"
                    f"</span> · {reason}"
                )

    # ── 交互 ──────────────────────────────────────────────
    def _on_import(self, expect_kind: str) -> None:
        start = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, tr("db_manager.import_title"), start, _FILE_FILTER
        )
        if not path:
            return
        self._import_path(expect_kind, path)

    def _import_path(self, expect_kind: str, path: str) -> bool:
        """对给定路径执行导入 (校验 → 类型确认 → 落盘 → 刷新 → 发信号)。

        与选文件解耦, 便于测试: 单测直接喂路径, 不必驱动 QFileDialog。

        Returns:
            是否真的完成了导入 (用户取消/校验失败/落盘失败都返回 False)。
        """
        ins = inspect_db_file(path)

        if not ins.ok:
            detail = ins.error + (f"\n{ins.hint}" if ins.hint else "")
            QMessageBox.warning(
                self, tr("db_manager.import_failed"),
                tr("db_manager.import_failed_body", path=path, detail=detail),
            )
            return False

        if ins.kind != expect_kind:
            other = db_import.KIND_BY_KEY[ins.kind]
            ans = QMessageBox.question(
                self, tr("db_manager.kind_mismatch"),
                tr("db_manager.kind_mismatch_body",
                   path=path, got=tr(other.label_key),
                   want=tr(db_import.KIND_BY_KEY[expect_kind].label_key)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return False
            expect_kind = ins.kind

        try:
            db_import.apply_import(ins)
        except Exception as e:  # noqa: BLE001 - 落盘失败要如实告诉用户
            QMessageBox.critical(
                self, tr("db_manager.import_failed"),
                tr("db_manager.save_failed_body", error=str(e)),
            )
            return False

        db_import.reload_caches()
        self._refresh()
        self.databases_changed.emit()
        extra = ("\n" + tr("db_manager.has_top_peaks")
                 if ins.has_top_peaks else "")
        QMessageBox.information(
            self, tr("db_manager.import_ok"),
            tr("db_manager.import_ok_body",
               rows=f"{ins.rows:,}", path=path) + extra,
        )
        return True

    def _on_clear(self, kind_key: str) -> None:
        if QMessageBox.question(
            self, tr("db_manager.clear"),
            tr("db_manager.clear_confirm",
               name=tr(db_import.KIND_BY_KEY[kind_key].label_key)),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            db_import.clear_import(kind_key)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("db_manager.clear"),
                                 str(e))
            return
        db_import.reload_caches()
        self._refresh()
        self.databases_changed.emit()
