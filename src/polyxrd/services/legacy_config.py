"""
旧库配置检测与一次性清理（v4.3.0 P4.3）
=======================================

v4.2.0 删掉旧 COD sqlite 运行时后，**配置文件里仍留着指向那些已不存在的库的
键**——程序本身照常跑（所有读取方都已删除），但用户会在这几处看到"幽灵"：

* ``~/.polyxrd/user_db_paths.json`` 里的 ``cod_db_path`` /
  ``cod_index_db_path`` / ``cod_svn_path``（v4.1.x 及更早写入）；
* ``~/.polyxrd/db_mounts.json`` 的 ``mounts[]`` 里 ``kind`` 是已删除引擎
  （``cod_inorganics`` / ``cod_index`` / ``xinmatch`` …）的条目 ——
  ``db_mounts._custom_mounts()`` 会把它们**静默丢弃**，于是"我明明加过库，
  怎么列表里没有"；
* 同一文件里的 ``active`` 指向上述已被丢弃的条目 id。

本模块只做三件事，且**全部可逆、不碰任何库文件**：

1. :func:`scan` —— 只读盘点，返回带路径/大小/是否存在的报告；
2. :func:`cleanup` —— 按报告删键/删条目（旧路径本身**不删文件**）；
3. :func:`dismiss` / :func:`is_dismissed` —— "稍后再说"的记住位。

设计取舍
--------
* **只清配置、绝不删库文件**：v4.1.x 的默认无机物库是 ``cod_data/`` 下的一个
  2 GB 级 sqlite 文件，仍可能被用户别处使用，自动删文件是不可接受的副作用；
  报告里给出路径与体积，让人自己决定。
* **顺手救回可用库**：旧条目若指向的其实是一份 polyDB 目录（用户手工指错过
  位置是常见情况），:func:`cleanup` 会把它**重新挂上**，而不是一并丢掉。
* **记住位写回 ``user_db_paths.json``**：这样"稍后"在下次启动不会反复弹窗，
  与项目里 ``polydb_disabled`` / ``db/nodb_hint_shown`` 的做法一致。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: v4.1.x 及更早写进 ``user_db_paths.json`` 的库槽位键 → 人类可读说明。
#: 键名钉死在这里，**不要**从 config 反查 —— 那些字段已随 v4.2.0 删除。
LEGACY_USER_DB_KEYS: dict[str, str] = {
    "cod_db_path": "COD 无机物库（旧 sqlite）",
    "cod_index_db_path": "COD 全库索引（旧 sqlite）",
    "cod_svn_path": "COD CIF 源目录",
}

#: v4.1.0 删掉的检索引擎类型。``db_mounts.json`` 里这些 ``kind`` 的条目
#: 现在会被静默丢弃，属于"配置残留"。
LEGACY_MOUNT_KINDS: tuple[str, ...] = (
    "cod_inorganics",
    "cod_index",
    "xinmatch",
    "cod_local",
    "cod_full",
)

#: 「已提示过」的记住位（写在 ``user_db_paths.json`` 里）。
DISMISS_KEY = "legacy_config_notice"


def _home_polyxrd() -> Path:
    return Path.home() / ".polyxrd"


def _paths_file(paths_file: Optional[str | Path]) -> Path:
    return Path(paths_file) if paths_file else _home_polyxrd() / "user_db_paths.json"


def _store_file(store_file: Optional[str | Path]) -> Path:
    return Path(store_file) if store_file else _home_polyxrd() / "db_mounts.json"


def _read_json(f: Path) -> dict:
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(f: Path, data: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _size_mb(p: Path) -> float:
    """路径体积 (MB)。目录按其下文件累加；读不到返回 0。

    ⚠️ ``Path("")`` 等于 ``Path(".")`` —— 空路径必须先由调用方挡掉，否则
    一次统计会把**当前工作目录整棵树**扫一遍（实测单条就拖慢 40 s）。
    这里再做一层保险。
    """
    try:
        if not str(p).strip() or p in (Path("."), Path("./")):
            return 0.0
        if p.is_file():
            return round(p.stat().st_size / 1e6, 1)
        if p.is_dir():
            total = 0
            for c in p.rglob("*"):
                try:
                    if c.is_file():
                        total += c.stat().st_size
                except OSError:
                    continue
            return round(total / 1e6, 1)
    except OSError:
        pass
    return 0.0


def _is_polydb_dir(p: Path) -> bool:
    """目录容器的判据：``meta.json`` + ``index.sqlite``（与 db_mounts 同口径）。"""
    try:
        if not str(p).strip() or p in (Path("."), Path("./")):
            return False
        return (p / "meta.json").is_file() and (p / "index.sqlite").is_file()
    except OSError:
        return False


def _opt_path(raw: object) -> Optional[Path]:
    """配置里的路径字符串 → Path；空/空白返回 ``None``（不是 ``Path('.')``）。"""
    s = str(raw or "").strip()
    return Path(s) if s else None


# ── 报告 ──────────────────────────────────────────────────

@dataclass(frozen=True)
class LegacyItem:
    """一条残留配置。

    Attributes:
        source: ``user_db_paths`` / ``db_mounts`` / ``db_mounts_active``。
        key: 残留在配置里的键名或挂载条目 id。
        path: 该配置指向的路径（可能已不存在）。
        exists: 路径当前是否还在。
        size_mb: 路径体积（MB）；不存在为 0。
        is_polydb: 路径是否其实是一份可用的 polyDB 目录（→ 可救回）。
        hint: 人类可读说明（i18n 之外的兜底文案，日志/诊断用）。
    """

    source: str
    key: str
    path: str
    exists: bool
    size_mb: float
    is_polydb: bool
    hint: str


@dataclass(frozen=True)
class LegacyReport:
    """一次盘点的结果。空 ``items`` 表示没有残留（``bool()`` 为 False）。"""

    items: tuple[LegacyItem, ...] = ()
    paths_file: str = ""
    store_file: str = ""

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def total_mb(self) -> float:
        return round(sum(i.size_mb for i in self.items), 1)

    @property
    def existing(self) -> tuple[LegacyItem, ...]:
        """路径仍存在的条目 —— 这些才是占地方的，报告里优先展示。"""
        return tuple(i for i in self.items if i.exists)

    @property
    def recoverable(self) -> tuple[LegacyItem, ...]:
        """指向真 polyDB 目录的条目 —— cleanup 会顺手挂回来。"""
        return tuple(i for i in self.items if i.is_polydb)

    def keys(self) -> list[str]:
        return [i.key for i in self.items]


# ── 盘点 ──────────────────────────────────────────────────

def scan(
    paths_file: Optional[str | Path] = None,
    store_file: Optional[str | Path] = None,
) -> LegacyReport:
    """只读盘点残留配置。**不写任何文件。**

    Args:
        paths_file: ``user_db_paths.json`` 路径；省略时用 ``~/.polyxrd/``。
        store_file: ``db_mounts.json`` 路径；省略时同上。
    """
    pf = _paths_file(paths_file)
    sf = _store_file(store_file)
    items: list[LegacyItem] = []

    data = _read_json(pf)
    for key, hint in LEGACY_USER_DB_KEYS.items():
        p = _opt_path(data.get(key))
        if p is None:
            continue
        items.append(LegacyItem(
            source="user_db_paths", key=key, path=str(p),
            exists=p.exists(), size_mb=_size_mb(p),
            is_polydb=_is_polydb_dir(p), hint=hint,
        ))

    store = _read_json(sf)
    mounts = store.get("mounts") or []
    legacy_ids: set[str] = set()
    if isinstance(mounts, list):
        for raw in mounts:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "")
            if kind not in LEGACY_MOUNT_KINDS:
                continue
            mid = str(raw.get("id") or "")
            if mid:
                legacy_ids.add(mid)
            p = _opt_path(raw.get("path"))
            items.append(LegacyItem(
                source="db_mounts", key=mid or kind,
                path=str(p) if p is not None else "",
                exists=bool(p is not None and p.exists()),
                size_mb=_size_mb(p) if p is not None else 0.0,
                is_polydb=bool(p is not None and _is_polydb_dir(p)),
                hint=f"旧挂载项（引擎 {kind} 已于 v4.1.0 删除）",
            ))
    active = str(store.get("active") or "")
    if active and active in legacy_ids:
        items.append(LegacyItem(
            source="db_mounts_active", key=active, path="",
            exists=False, size_mb=0.0, is_polydb=False,
            hint="当前检索源指向已删除的旧挂载项",
        ))

    return LegacyReport(items=tuple(items), paths_file=str(pf), store_file=str(sf))


# ── 清理 ──────────────────────────────────────────────────

def cleanup(
    report: Optional[LegacyReport] = None,
    *,
    paths_file: Optional[str | Path] = None,
    store_file: Optional[str | Path] = None,
    remount_polydb: bool = True,
) -> list[str]:
    """按报告删除残留配置，返回实际改动的键（空列表 = 什么都没做）。

    行为约定：

    * ``user_db_paths.json``：只删 :data:`LEGACY_USER_DB_KEYS` 里出现的键，
      **其它键原样保留**（polyDB / PDF2 槽位、``polydb_disabled`` 等）；
    * ``db_mounts.json``：删掉旧 kind 的 ``mounts[]`` 条目；``active`` 若指向
      被删条目则清空（下次由界面按默认顺序重选）；
    * ``remount_polydb=True`` 时，路径确实是 polyDB 目录的旧条目会通过
      ``db_mounts.add_mount()`` **重新挂上**，避免"清理把好库也清了"；
    * **不删任何库文件**——``.sqlite`` / 目录一律留在原地。
    """
    rep = report if report is not None else scan(paths_file, store_file)
    if not rep:
        return []
    changed: list[str] = []

    # 1) user_db_paths.json —— 只动旧键
    pf = Path(rep.paths_file)
    data = _read_json(pf)
    touched = False
    for key in LEGACY_USER_DB_KEYS:
        if key in data:
            data.pop(key, None)
            changed.append(key)
            touched = True
    if touched:
        _write_json(pf, data)

    # 2) db_mounts.json —— 删旧 kind 条目 + 清 active
    sf = Path(rep.store_file)
    store = _read_json(sf)
    mounts = store.get("mounts")
    if isinstance(mounts, list):
        kept: list = []
        dropped_ids: set[str] = set()
        for raw in mounts:
            if isinstance(raw, dict) and \
                    str(raw.get("kind") or "") in LEGACY_MOUNT_KINDS:
                dropped_ids.add(str(raw.get("id") or ""))
                changed.append(f"mounts:{raw.get('id') or raw.get('kind')}")
                continue
            kept.append(raw)
        if dropped_ids:
            store["mounts"] = kept
            if str(store.get("active") or "") in dropped_ids:
                store["active"] = ""
                changed.append("active")
            _write_json(sf, store)

    # 3) 顺手把"其实是 polyDB"的旧路径挂回来
    if remount_polydb:
        for item in rep.recoverable:
            try:
                from polyxrd.services import db_mounts

                existing = {str(m.path.resolve()) for m in db_mounts.all_mounts()
                            if m.path is not None}
                if str(Path(item.path).resolve()) in existing:
                    continue
                db_mounts.add_mount(item.path)
                changed.append(f"remount:{item.path}")
            except Exception:  # noqa: BLE001 - 挂载失败不该阻断清理
                continue

    return changed


# ── 「稍后再说」记住位 ────────────────────────────────────

def is_dismissed(paths_file: Optional[str | Path] = None) -> bool:
    """用户是否已选择"稍后再处理"。

    记住位存的是**版本号**：升级到新版本后会重新提示一次 —— 旧版本上的
    "稍后"不该压制新版本的提示（清理项可能随版本变化）。
    """
    data = _read_json(_paths_file(paths_file))
    seen = str(data.get(DISMISS_KEY) or "")
    if not seen:
        return False
    try:
        from polyxrd import __version__

        return seen == str(__version__)
    except Exception:  # noqa: BLE001 - 版本读不出时按"已提示"处理, 不骚扰
        return True


def dismiss(paths_file: Optional[str | Path] = None) -> None:
    """记下"本版本已提示过"（写 ``legacy_config_notice``）。"""
    try:
        from polyxrd import __version__
    except Exception:  # noqa: BLE001
        return
    f = _paths_file(paths_file)
    data = _read_json(f)
    data[DISMISS_KEY] = str(__version__)
    _write_json(f, data)


def describe(report: LegacyReport) -> list[str]:
    """报告 → 逐行人类可读文案（不含 i18n，给日志/诊断/兜底展示用）。"""
    lines: list[str] = []
    for item in report.items:
        if item.source == "db_mounts_active":
            lines.append(f"· 检索源 → {item.key}（已删除的旧库）")
            continue
        state = "存在" if item.exists else "已不存在"
        extra = f"，{item.size_mb} MB" if item.size_mb else ""
        mark = "（可重新挂载为 polyDB）" if item.is_polydb else ""
        lines.append(f"· {item.path or item.key} —— {state}{extra}{mark}")
    return lines


__all__ = [
    "DISMISS_KEY", "LEGACY_MOUNT_KINDS", "LEGACY_USER_DB_KEYS",
    "LegacyItem", "LegacyReport",
    "cleanup", "describe", "dismiss", "is_dismissed", "scan",
]
