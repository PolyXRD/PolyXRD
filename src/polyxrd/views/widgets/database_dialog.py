r"""外挂数据库管理对话框 —— 列表式多库挂载 (v4.0.0 重设计)
==========================================================

旧版是**按类型一个槽位**: COD 无机物库 / COD 全库索引 / PDF2 / XinMatch 格式库
各占一行, 每类只能挂一份。v4.0.0 起改成**一张表**: 一行 = 一个已挂载的数据库,
想挂几份挂几份 (同一类型也可以挂多份, 例如"内置盘常驻的 polyDB 全库" +
"移动硬盘上的无机子集"), 选中某行点「设为当前」, 物相检索就用那一份。

界面结构
--------
    ┌ 说明 ───────────────────────────────────────────────┐
    │ 挂载数据库文件…  挂载文件夹…  卸载  设为当前  重新检测  用户库管理… │
    ├ 表格 (名称/类型/相数/大小/状态/位置) ────────────────────┤
    │ ● COD 无机物库 (polyDB)  polyDB  77,500  89.9 MB  已挂载  D:\... │
    │   COD 全库索引           COD    1,959,421 30.2 GB 已挂载  D:\... │
    ├ 详情 (路径 / 下载包 / 授权提示) ────────────────────────┤
    │ 当前物相检索使用：COD 无机物库 (polyDB)              [关闭] │
    └──────────────────────────────────────────────────┘

设计取舍
--------
1. **「设为当前」是一个显式动作, 不是"选中即切换"**。选中行会立刻改变详情区,
   但真正换数据源要按按钮 (或双击行) —— 表格里点一下就换库、下一张谱跑出
   另一套结果的体验太危险。
2. **卸载内置库 = 清对应配置槽位**(与旧「取消挂载」等价), 卸载用户自加项 =
   从挂载表里删掉。两者都不删库文件本身。
3. **授权提示跟着选中行走**(PDF2-2004 是 ICDD 商业库)。提示必须出现在用户
   挂载它的地方, 藏在许可协议里等于没提示。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from polyxrd.i18n import tr
from polyxrd.services import db_import, db_mounts, user_db

#: kind key → DBKind; 保留给"下载包提示"用 (DB_KINDS 的顺序即优先级, 这里按 key 查)
DB_KINDS_BY_KEY = db_import.KIND_BY_KEY

_ROW_ID = Qt.ItemDataRole.UserRole

#: 表格列顺序 (与 ``_HEADER_KEYS`` 一一对应)
_COL_ACTIVE, _COL_NAME, _COL_TYPE, _COL_ROWS, _COL_SIZE, _COL_STATUS, _COL_PATH = range(7)

_HEADER_KEYS = (
    "db_manager.col_active",
    "db_manager.col_name",
    "db_manager.col_type",
    "db_manager.col_rows",
    "db_manager.col_size",
    "db_manager.col_status",
    "db_manager.col_path",
)

#: 库类型 → 显示名 i18n 键 (polyDB 的显示名带变体信息, 由 mount.label_key 覆盖)
_GREEN = "#1e8449"
_RED = "#c0392b"
_AMBER = "#b9770e"
_MUTED = "#7f8c8d"


class DatabaseManagerDialog(QDialog):
    """外挂数据库管理: 列表式挂载 / 卸载 / 选当前库。"""

    databases_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("db_manager.title"))
        self.setMinimumSize(920, 560)
        self._rows: list[dict] = []
        self._build()
        self.reload()

    # ── 构建 ──────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(tr("db_manager.list_intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet("color: palette(mid);")
        root.addWidget(intro)

        root.addLayout(self._build_toolbar())
        root.addWidget(self._build_table(), stretch=1)
        root.addWidget(self._build_detail())

        foot = QHBoxLayout()
        self._current_lbl = QLabel("—")
        self._current_lbl.setWordWrap(True)
        foot.addWidget(self._current_lbl, stretch=1)
        btns = QDialogButtonBox()
        self._btn_recheck = btns.addButton(
            tr("db_manager.recheck"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_recheck.clicked.connect(self.reload)
        close_btn = btns.addButton(
            tr("common.close"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        close_btn.clicked.connect(self.accept)
        foot.addWidget(btns)
        root.addLayout(foot)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._btn_mount_file = QPushButton(tr("db_manager.btn_mount_file"))
        self._btn_mount_file.clicked.connect(self._on_mount_file)
        self._btn_mount_dir = QPushButton(tr("db_manager.btn_mount_dir"))
        self._btn_mount_dir.clicked.connect(self._on_mount_dir)

        self._btn_set_active = QPushButton(tr("db_manager.btn_set_active"))
        self._btn_set_active.clicked.connect(self._on_set_active)
        self._btn_unmount = QPushButton(tr("db_manager.btn_unmount"))
        self._btn_unmount.clicked.connect(self._on_unmount)
        self._btn_user = QPushButton(tr("db_manager.btn_user_manage"))
        self._btn_user.clicked.connect(self._on_open_user_db)

        for b in (self._btn_mount_file, self._btn_mount_dir):
            b.setStyleSheet(
                "QPushButton { background-color: #1565c0; color: white;"
                " padding: 4px 12px; }"
                "QPushButton:hover { background-color: #0d47a1; }")
        self._btn_set_active.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white;"
            " padding: 4px 12px; }"
            "QPushButton:hover { background-color: #1b5e20; }")

        row.addWidget(self._btn_mount_file)
        row.addWidget(self._btn_mount_dir)
        row.addSpacing(12)
        row.addWidget(self._btn_set_active)
        row.addWidget(self._btn_unmount)
        row.addSpacing(12)
        row.addWidget(self._btn_user)
        row.addStretch(1)
        return row

    def _build_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_HEADER_KEYS))
        t.setHorizontalHeaderLabels([tr(k) for k in _HEADER_KEYS])
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        # 单行 + 右侧省略: 一行一库, 行高必须整齐 (长路径靠 tooltip 看全)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.TextElideMode.ElideRight)
        t.verticalHeader().setDefaultSectionSize(26)
        t.itemSelectionChanged.connect(self._on_selection_changed)
        t.itemDoubleClicked.connect(lambda _it: self._on_set_active())
        head = t.horizontalHeader()
        head.setStretchLastSection(True)
        for col, width in ((_COL_ACTIVE, 72), (_COL_NAME, 300), (_COL_TYPE, 96),
                           (_COL_ROWS, 96), (_COL_SIZE, 92), (_COL_STATUS, 120)):
            t.setColumnWidth(col, width)
        head.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Interactive)
        self._table = t
        return t

    def _build_detail(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(box)
        lay.setSpacing(3)

        self._detail_name = QLabel("—")
        self._detail_name.setStyleSheet("font-weight: bold;")
        lay.addWidget(self._detail_name)

        self._detail_path = QLabel("—")
        self._detail_path.setWordWrap(True)
        self._detail_path.setStyleSheet("color: palette(mid);")
        self._detail_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._detail_path)

        self._detail_pkg = QLabel("")
        self._detail_pkg.setWordWrap(True)
        self._detail_pkg.setStyleSheet("color: palette(mid);")
        self._detail_pkg.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._detail_pkg)

        self._detail_notice = QLabel("")
        self._detail_notice.setWordWrap(True)
        self._detail_notice.setStyleSheet(f"color: {_AMBER};")
        self._detail_notice.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._detail_notice.hide()
        lay.addWidget(self._detail_notice)
        return box

    # ── 刷新 ──────────────────────────────────────────────
    def reload(self) -> None:
        """重新探测全部挂载项并重画表格 (保留当前选中行)。"""
        keep = self._selected_id()
        db_mounts.clear_probe_cache()
        self._rows = db_mounts.probe_all()
        self._fill_table(keep)
        self._update_footer()

    #: 兼容旧名 (外部曾用它做"导入后刷新")
    _refresh = reload

    def _fill_table(self, keep_id: str = "") -> None:
        active = db_mounts.active_id()
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            is_active = row["id"] == active and row["ok"]
            cells = [
                tr("db_manager.active_mark") if is_active else "",
                self._display_name(row),
                self._type_label(row),
                f"{row['rows']:,}" if row["ok"] else "—",
                f"{row['size_mb']} MB" if row["size_mb"] else "—",
                self._status_text(row),
                row["path"] or "—",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(_ROW_ID, row["id"])
                if c == _COL_ACTIVE and is_active:
                    item.setForeground(QColor(_GREEN))
                if c == _COL_STATUS:
                    item.setForeground(QColor(
                        _GREEN if row["ok"] else
                        (_RED if row["exists"] else _AMBER)))
                if c == _COL_PATH:
                    item.setForeground(QColor(_MUTED))
                    item.setToolTip(row["path"] or "")
                if c == _COL_NAME and item.text():
                    item.setToolTip(self._name_tooltip(row))
                if not row["ok"]:
                    item.setToolTip(tr("db_manager.row_disabled_tip"))
                self._table.setItem(r, c, item)
        self._table.blockSignals(False)
        # 恢复选中
        target = -1
        for r, row in enumerate(self._rows):
            if row["id"] == keep_id:
                target = r
                break
        if target < 0 and self._rows:
            target = 0
        if target >= 0:
            self._table.selectRow(target)
        self._on_selection_changed()

    def _update_footer(self) -> None:
        m = db_mounts.active_mount()
        if m is not None and m.exists:
            self._current_lbl.setText(
                f"<span style='color:{_GREEN}'>"
                f"{tr('db_manager.current_source', name=self._display_name_of(m.id))}"
                f"</span>")
        else:
            self._current_lbl.setText(tr("db_manager.current_source_none"))

    # ── 行 → 文案 ─────────────────────────────────────────
    def _display_name(self, row: dict) -> str:
        """行名称: 内置项用类型名; 同类型挂了多份时补"是哪一份"(文件/目录名)。

        只有一份时补名字是噪音 (类型列已经说清是什么库); 有两份以上时不补
        名字就分不清哪行是哪份库了 —— 而"选哪份库"正是这张表的全部意义。
        """
        key = row.get("label_key") or ""
        base = tr(key) if key else (row.get("label") or row["id"])
        same = [r for r in self._rows if r.get("kind") == row.get("kind")]
        if len(same) > 1 and row.get("path"):
            return f"{base} · {Path(row['path']).name}"
        return base

    def _name_tooltip(self, row: dict) -> str:
        """名称列的完整信息 (列宽不够时被省略, 悬停可看全)。"""
        name = self._display_name(row)
        path = row.get("path") or tr("db_manager.no_path")
        return f"{name}\n{path}"

    def _display_name_of(self, mount_id: str) -> str:
        for row in self._rows:
            if row["id"] == mount_id:
                return self._display_name(row)
        return mount_id

    @staticmethod
    def _type_label(row: dict) -> str:
        """类型列: 讲清"这是哪种库", 而不重复行名称里的变体信息。"""
        kind = row["kind"]
        if kind == "polydb":
            return tr("db_mounts.type.polydb")
        key = db_mounts.KIND_LABEL_KEY.get(kind, "")
        return tr(key) if key else kind

    @staticmethod
    def _status_text(row: dict) -> str:
        if row["ok"]:
            return tr("db_manager.status_ok")
        if not row["path"]:
            return tr("db_manager.status_unmounted")
        if not row["exists"]:
            return tr("db_manager.status_missing")
        detail = row.get("error") or "unknown"
        if row.get("hint"):
            detail += f" ({row['hint']})"
        return f"{tr('db_manager.status_bad')} · {detail}"

    # ── 选中 → 详情 ───────────────────────────────────────
    def _selected_id(self) -> str:
        it = self._table.currentItem() if hasattr(self, "_table") else None
        return str(it.data(_ROW_ID)) if it is not None else ""

    def _current_row(self) -> dict | None:
        mid = self._selected_id()
        for row in self._rows:
            if row["id"] == mid:
                return row
        return None

    def _on_selection_changed(self) -> None:
        row = self._current_row()
        if row is None:
            self._detail_name.setText("—")
            self._detail_path.setText("—")
            self._detail_pkg.setText("")
            self._detail_notice.hide()
            self._btn_set_active.setEnabled(False)
            self._btn_unmount.setEnabled(False)
            return
        self._detail_name.setText(self._display_name(row))
        self._detail_path.setText(row["path"] or tr("db_manager.no_path"))
        self._detail_pkg.setText(self._pkg_hint(row))
        notice = self._notice_of(row)
        self._detail_notice.setText(notice)
        self._detail_notice.setVisible(bool(notice))
        self._btn_set_active.setEnabled(
            bool(row["ok"]) and db_mounts.active_id() != row["id"])
        # 用户自建库的位置由 user_db 自己管, 这里不给"卸载"
        self._btn_unmount.setEnabled(
            row["kind"] != "user" and (bool(row["path"]) or not row["builtin"]))

    def _pkg_hint(self, row: dict) -> str:
        spec = DB_KINDS_BY_KEY.get(row["kind"])
        if spec is None:
            # polyDB 库包统一由独立仓库 PolyXRD-DataBase 发布（v4.1.1 政策：
            # 主仓库 Release 只发程序、不上传数据库）；默认库已内置, 这里给的是
            # “扩展库去哪下”的指引, 不再编造主仓库附件名。
            if row["kind"] == "polydb":
                return tr(
                    "db_mounts.pkg_polydb_repo",
                    url="https://github.com/PolyXRD/PolyXRD-DataBase/releases")
            return tr("db_mounts.pkg_free")
        version = _app_version()
        pkg = db_import.release_package_name(spec.key, version)
        fname = db_import.PKG_FILENAME.get(spec.key, "")
        if pkg:
            return tr("db_manager.pkg_hint", pkg=pkg, file=fname)
        return tr("db_manager.pkg_hint_local", file=fname)

    @staticmethod
    def _notice_of(row: dict) -> str:
        spec = DB_KINDS_BY_KEY.get(row["kind"])
        key = getattr(spec, "notice_key", "") if spec else ""
        return tr(key) if key else ""

    # ── 交互 ──────────────────────────────────────────────
    def _on_mount_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("db_manager.mount_title_file"), str(Path.home()),
            tr("db_manager.mount_filter"))
        if path:
            self.mount_path(path)

    def _on_mount_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr("db_manager.mount_title_dir"), str(Path.home()))
        if path:
            self.mount_path(path)

    def mount_path(self, path: str) -> bool:
        """挂载一个路径下所有合格的库 (sqlite 各类 + polyDB 目录)。

        与选文件对话框解耦, 便于单测直接喂路径; 返回是否至少挂上一个。
        """
        try:
            mounted = db_mounts.mount_any(path)
        except Exception as e:  # noqa: BLE001 - 失败原因要如实展示
            QMessageBox.warning(
                self, tr("db_manager.mount_failed"),
                tr("db_manager.mount_failed_body", path=path, error=str(e)))
            return False
        db_import.reload_caches()
        self.reload()
        self.databases_changed.emit()
        lines: list[str] = []
        for m in mounted:
            n = _probe_rows(m)
            tail = f"{n:,}" if n else tr("db_manager.status_unmounted")
            lines.append(f"· {self._name_of_mount(m)} — {tail}")
        QMessageBox.information(
            self, tr("db_manager.mount_ok"),
            tr("db_manager.mount_ok_body", n=len(mounted),
               detail="\n".join(lines)))
        return True

    def _name_of_mount(self, m: db_mounts.Mount) -> str:
        if m.label_key:
            return tr(m.label_key)
        return m.display_name()

    def _on_set_active(self) -> None:
        row = self._current_row()
        if row is None:
            return
        if not row["ok"]:
            QMessageBox.warning(
                self, tr("db_manager.btn_set_active"),
                tr("db_manager.set_active_unavailable",
                   name=self._display_name(row)))
            return
        db_mounts.set_active(row["id"])
        self._fill_table(row["id"])
        self._update_footer()
        self.databases_changed.emit()

    def _on_unmount(self) -> None:
        row = self._current_row()
        if row is None:
            return
        name = self._display_name(row)
        if QMessageBox.question(
            self, tr("db_manager.btn_unmount"),
            tr("db_manager.unmount_confirm", name=name),
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            db_mounts.remove_mount(row["id"])
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("db_manager.btn_unmount"), str(e))
            return
        db_import.reload_caches()
        self.reload()
        self.databases_changed.emit()

    def _on_open_user_db(self) -> None:
        from polyxrd.views.widgets.user_db_dialog import UserDatabaseDialog

        dlg = UserDatabaseDialog(self)
        dlg.changed.connect(self.reload)
        dlg.changed.connect(self.databases_changed.emit)
        dlg.exec()
        self.reload()


def _app_version() -> str:
    try:
        from polyxrd.config import get_config

        return get_config().app_version
    except Exception:  # noqa: BLE001
        return ""


def _probe_rows(m: db_mounts.Mount) -> int:
    res = db_mounts.probe(m)
    return int(res.get("rows") or 0) if res.get("ok") else 0


def user_db_summary() -> dict:
    """用户自建库概况 (给外部/测试用; 库里没有条目时 rows=0)。"""
    try:
        return user_db.user_stats()
    except Exception:  # noqa: BLE001
        return {"rows": 0, "path": "", "exists": False, "size_mb": 0}
