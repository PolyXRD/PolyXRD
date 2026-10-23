"""外挂数据库挂载注册表 (v4.0.0)
================================

「外挂数据库管理」原本是**按类型一个槽位**的模型: COD 无机物库、COD 全库索引、
PDF2-2004、XinMatch 格式库各占一个固定槽位, 每个槽位只能挂一份库。这个模型
在只有四类库、且每类只可能挂一份的年代够用, 但在下面这些场景里会直接卡住:

  · 同一类库有**多份**: 手里既有 ``COD-Inorg-20261021.polyDB`` 又有自己裁的
    无机子集, 想按项目切换;
  · 同一类库放在**两处**: 一份内置盘常驻、一份移动硬盘随身带;
  · 想挂**同一格式的别人家的库**: 同事导出的 polyDB 子集。

所以 v4.0.0 把模型换成**列表**: 界面上是一张表, 一行 = 一个已挂载的数据库,
想挂几个挂几个; 每行有稳定 id, 物相检索的「数据源」就是这张表的某一行的 id。
选中哪一行, 就用哪一行去检索。

设计要点
--------
1. **零迁移**: 内置挂载项 (polyDB 两个变体、PDF2、用户自建库) 由配置现算
   (:func:`default_mounts`), 不写进 json。用户升级后打开界面, 原来挂着的库
   仍然在列表里, 位置不变; 卸载内置项 = 清对应配置槽位 (与旧行为一致)。
   只有**用户额外加的**挂载项才落盘到 ``~/.polyxrd/db_mounts.json``。
2. **id 稳定**: 内置项 id 取固定名 (``polydb:cod-inorg`` / ``pdf2`` / ...), 这样
   历史代码与历史测试里的 ``db_source="pdf2"`` 一类字面量继续有效; 用户加的
   项 id 取 ``<kind>:<路径摘要>``, 同一路径反复添加得到同一个 id (幂等)。
   已删除的旧槽位字面量 (``cod_inorganics`` / ``cod_index`` / ``xinmatch``)
   经 :data:`_LEGACY_ALIASES` 映射到语义等价的新库, 老配置不会报"库不存在"。
3. **探测与展示分离**: :func:`probe` 只读库、不写配置; 失败原因原样返回给
   UI, 由界面决定显示成"未挂载"还是"无法使用"。
4. **不碰打分**: 本模块只回答"用哪份库", 不参与候选生成/打分/FOM 口径 ——
   物相匹配准确性由既有引擎负责, 本次改造对结果**零影响**(同一路径必然
   落到同一个引擎分支)。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

#: 支持的挂载类型 → 检索引擎。
#: 引擎名即 ``PhaseIdentifier.identify_with_*`` 的后缀, 便于按 kind 分发。
#:
#: v4.1.0 起**只有三种**: 默认参考库是 polyDB（COD-Inorg / COD-Full 两个变体），
#: PDF2 是用户自备的 ICDD 商业库，``user`` 是用户自建库。旧 sqlite 槽位
#: ``cod_inorganics`` / ``cod_index`` / ``xinmatch`` 连同对应检索引擎一起删除。
KIND_ENGINE: dict[str, str] = {
    "pdf2": "pdf2",
    "polydb": "polydb",
    "user": "user",
}

#: 类型 → i18n 键 (内置项显示名)。用户自己加的多份库用"类型名 · 目录名"区分。
KIND_LABEL_KEY: dict[str, str] = {
    "pdf2": "db_manager.kind.pdf2",
    "polydb": "db_mounts.kind.polydb_inorg",
    "user": "db_mounts.kind.user",
}

#: 老代码/老测试/老配置里用过的字面量 → 挂载 id。``db_source`` 兼容层靠它。
#:
#: ``cod_inorganics`` 一类是 v4.1.0 删掉的旧槽位: 老用户存的
#: ``db_source="cod_inorganics"`` 现在应落到**默认的 polyDB 无机库**上
#: （同一批 COD 无机物的新格式），而不是报"库不存在"。
_LEGACY_ALIASES: dict[str, str] = {
    "polydb_inorg": "polydb:cod-inorg",
    "polydb_full": "polydb:cod-full",
    # 已删除的旧槽位 → 语义等价的新库
    "cod_inorganics": "polydb:cod-inorg",
    "xinmatch": "polydb:cod-inorg",
    "cod_index": "polydb:cod-full",
    "cod_full": "polydb:cod-full",
    "cod_local": "polydb:cod-full",
}

#: 「内置」挂载项 id → polyDB 变体。空串表示不是 polyDB。
_POLYDB_DEFAULT_IDS = {"polydb:cod-inorg": "cod-inorg", "polydb:cod-full": "cod-full"}

#: polyDB 变体 → i18n 键。两个变体是两份独立的库 (无机子集 / 全库),
#: 在列表里必须能一眼区分, 所以各有各的显示名。
_POLYDB_LABEL_KEY = {
    "cod-inorg": "db_mounts.kind.polydb_inorg",
    "cod-full": "db_mounts.kind.polydb_full",
}


@dataclass(frozen=True)
class Mount:
    """一个已挂载的数据库 (= 列表里的一行)。

    Attributes:
        id: 稳定标识; 也是物相检索的 ``db_source`` 取值。
        kind: 库类型, 见 :data:`KIND_ENGINE`。
        path: 库位置。polyDB 是**目录**, 其余是**文件**; 未挂载时可为 None。
        label_key: 内置项的 i18n 显示名键 (用户自加项为空)。
        label: 用户自定义显示名 / 由目录名生成的显示名。
        builtin: True = 由配置槽位派生 (卸载 = 清配置), False = 写在本模块 json 里。
        variant: polyDB 变体 (``cod-inorg`` / ``cod-full``); 非 polyDB 为空串。
    """

    id: str
    kind: str
    path: Optional[Path] = None
    label_key: str = ""
    label: str = ""
    builtin: bool = True
    variant: str = ""

    # ── 便捷属性 ──────────────────────────────────────────
    @property
    def is_dir(self) -> bool:
        return self.kind == "polydb"

    @property
    def exists(self) -> bool:
        p = self.path
        if p is None:
            return False
        return p.is_dir() if self.is_dir else p.is_file()

    @property
    def engine(self) -> str:
        return KIND_ENGINE.get(self.kind, "")

    def display_name(self) -> str:
        """不带翻译的显示名 (内置项的本地化名由 UI 按 ``label_key`` 取)。"""
        if self.label:
            return self.label
        if self.path is not None:
            return self.path.name
        return self.id


# ── 持久化 ────────────────────────────────────────────────────

def _store_file() -> Path:
    return Path.home() / ".polyxrd" / "db_mounts.json"


def _load_store() -> dict:
    f = _store_file()
    if not f.exists():
        return {"version": 1, "active": "", "mounts": []}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "active": "", "mounts": []}
    if not isinstance(data, dict):
        return {"version": 1, "active": "", "mounts": []}
    data.setdefault("version", 1)
    data.setdefault("active", "")
    if not isinstance(data.get("mounts"), list):
        data["mounts"] = []
    return data


def _save_store(data: dict) -> None:
    f = _store_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def _mount_id(kind: str, path: Path) -> str:
    """按 (类型, 路径) 生成稳定 id; 同一路径反复添加得到同一个 id。"""
    raw = f"{kind}|{path.resolve()}".encode("utf-8")
    return f"{kind}:{hashlib.sha1(raw).hexdigest()[:8]}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 内置挂载项 (由配置现算) ────────────────────────────────────

def default_mounts() -> list[Mount]:
    """由配置派生的内置挂载项 (零迁移: 老用户升级后列表不空)。

    只返回**当前确实有路径**的项; 路径不存在也照样返回 (``exists=False``),
    这样界面能显示"未挂载"而不是让整行凭空消失。

    v4.1.0: 默认库 = polyDB 的 ``cod-inorg`` 变体。它的路径可能来自用户挂载,
    也可能来自**自动发现**（便携版 ``<exe>/databases``、源码模式的构库产物
    目录），所以干净安装后第一行就是可用的 COD-Inorg。
    """
    from polyxrd.config import get_config

    cfg = get_config()
    out: list[Mount] = []

    def _add(mid: str, kind: str, path: Optional[Path], label_key: str,
             variant: str = "") -> None:
        out.append(Mount(id=mid, kind=kind, path=Path(path) if path else None,
                         label_key=label_key, builtin=True, variant=variant))

    # 顺序即界面默认顺序: 默认参考库排第一, 可选库在后
    for mid, variant in _POLYDB_DEFAULT_IDS.items():
        _add(mid, "polydb", cfg.get_polydb_path(variant),
             _POLYDB_LABEL_KEY[variant], variant)
    _add("pdf2", "pdf2", cfg.get_pdf2_db_path(), KIND_LABEL_KEY["pdf2"])
    # 用户自建库: 位置由 user_db 固定管理, 这里只作为"可检索的一行"出现
    try:
        from polyxrd.services import user_db

        _add("user", "user", user_db.user_db_path(), KIND_LABEL_KEY["user"])
    except Exception:  # noqa: BLE001
        pass
    return out


def _custom_mounts() -> list[Mount]:
    out: list[Mount] = []
    for raw in _load_store().get("mounts", []):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        path = raw.get("path") or ""
        if kind not in KIND_ENGINE or not path:
            continue
        out.append(Mount(
            id=str(raw.get("id") or _mount_id(kind, Path(path))),
            kind=kind,
            path=Path(path),
            label=str(raw.get("label") or ""),
            builtin=False,
            variant=str(raw.get("variant") or ""),
        ))
    return out


def all_mounts(include_user: bool = True) -> list[Mount]:
    """全部挂载项: 内置项在前 (固定顺序), 用户自加项在后。

    同 (kind, path) 的重复项只留一条 —— 用户把某个库既通过旧槽位导入、
    又在新界面加了一次时, 列表里不该出现两行完全一样的库。
    """
    seen: set[tuple[str, str]] = set()
    out: list[Mount] = []
    for m in default_mounts() + _custom_mounts():
        if not include_user and m.kind == "user":
            continue
        # 去重键: 有路径按"类型+路径"; 没路径 (尚未挂载的槽位) 按 id ——
        # 否则两个都没挂的 polyDB 变体 (路径都是 None) 会互相顶掉。
        key = ((m.kind, str(m.path.resolve())) if m.path is not None
               else ("", m.id))
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def get_mount(mount_id: str) -> Optional[Mount]:
    for m in all_mounts():
        if m.id == mount_id:
            return m
    return None


def add_mount(path: str | Path, kind: str | None = None,
              label: str = "") -> Mount:
    """把一个合格的库加进列表 (幂等: 同一路径重复添加返回同一条)。

    Args:
        path: 库文件 (sqlite) 或库目录 (polyDB)。
        kind: 显式指定类型; 省略则自动判别。
        label: 自定义显示名; 省略时由目录名/文件名词干生成。

    Raises:
        ValueError: 路径不合格 (不存在 / 不是库), 消息带人工可读原因。
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"路径不存在: {p}")
    real_kind, note = detect_kind(p, kind)
    if not real_kind:
        raise ValueError(note or "该路径下没有可用的数据库")
    mid = _mount_id(real_kind, p)
    # 内置项已覆盖同一份库 → 直接返回内置项, 不重复落盘
    for m in all_mounts():
        if m.path is not None and m.path.resolve() == p.resolve():
            return m
    if not label:
        # 用完整文件名/目录名 (含后缀): 同类型挂多份时, 用户就是靠这个区分
        # ".db" 与 ".polyDB" 的 —— 去掉后缀只会让两行看起来一样。
        label = p.name
    data = _load_store()
    mounts = [m for m in data.get("mounts", []) if isinstance(m, dict)]
    for raw in mounts:
        if raw.get("id") == mid:
            return Mount(id=mid, kind=real_kind, path=p, label=str(raw.get("label") or label),
                         builtin=False)
    mounts.append({
        "id": mid,
        "kind": real_kind,
        "path": str(p.resolve()),
        "label": label,
        "variant": _read_polydb_variant(p) if real_kind == "polydb" else "",
        "added_at": _now(),
    })
    data["mounts"] = mounts
    _save_store(data)
    return Mount(id=mid, kind=real_kind, path=p, label=label, builtin=False)


def remove_mount(mount_id: str) -> None:
    """从列表移除一个挂载项。

    内置项: 清对应配置槽位 (与旧「取消挂载」等价); 用户自加项: 从 json 删掉。
    """
    m = get_mount(mount_id)
    if m is None:
        raise KeyError(mount_id)
    if m.builtin:
        from polyxrd.services import db_import

        if m.kind == "polydb":
            from polyxrd.config import get_config

            get_config().set_polydb_path(None, m.variant or "cod-inorg")
        elif m.kind == "user":
            raise ValueError("用户自建库请在其管理界面清空, 不能在此卸载")
        else:
            db_import.clear_import(m.kind)
        if active_id() == mount_id:
            set_active("")
        return
    data = _load_store()
    data["mounts"] = [r for r in data.get("mounts", [])
                      if isinstance(r, dict) and r.get("id") != mount_id]
    if data.get("active") == mount_id:
        data["active"] = ""
    _save_store(data)


def set_active(mount_id: str) -> None:
    """记住"当前用于物相检索"的那一行 (空串 = 不指定)。"""
    data = _load_store()
    data["active"] = mount_id or ""
    _save_store(data)


def active_id() -> str:
    return str(_load_store().get("active") or "")


def active_mount() -> Optional[Mount]:
    mid = active_id()
    if not mid:
        return None
    return get_mount(mid)


# ── 类型判别 ──────────────────────────────────────────────────

def _read_polydb_variant(path: Path) -> str:
    try:
        meta = json.loads((Path(path) / "meta.json").read_text(encoding="utf-8"))
        return str(meta.get("variant") or "")
    except Exception:  # noqa: BLE001
        return ""


def is_polydb_dir(path: str | Path) -> bool:
    """polyDB 目录容器的判据: 有 ``index.sqlite`` + ``meta.json``。

    不直接依赖 PolyDatabase 打开 (那会读 memmap); 只做存在性判别, 快。
    """
    p = Path(path)
    return (p.is_dir() and (p / "index.sqlite").is_file()
            and (p / "meta.json").is_file())


def detect_kind(path: str | Path, expect: str | None = None) -> tuple[str, str]:
    """判别一个路径属于哪类库, 返回 ``(kind, 说明)``; 判不出时 kind 为空。

    Args:
        expect: 调用方已声明的类型; 给了就**只做校验**, 不猜 —— 用户明确
            说"这是个 PDF2 库"时, 若内容其实是 COD 无机库, 应当报错而不是
            静默改判 (拿错库只会静默检索不到东西, 这是本项目踩过的坑)。
    """
    p = Path(path)
    if p.is_dir():
        if not is_polydb_dir(p):
            return "", "目录里没有 meta.json + index.sqlite, 不是 polyDB 目录"
        if expect and expect != "polydb":
            return "", f"这是 polyDB 目录, 不是 {expect}"
        return "polydb", ""
    from polyxrd.services.db_import import inspect_db_file

    ins = inspect_db_file(p)
    if not ins.ok:
        detail = ins.error + (f" ({ins.hint})" if ins.hint else "")
        return "", f"不是可用的数据库文件: {detail}"
    if expect and ins.kind != expect:
        return "", f"该文件是 {ins.kind}, 不是 {expect}"
    return str(ins.kind or ""), ""


# ── 探测 (只读) ───────────────────────────────────────────────

_PROBE_CACHE: dict[tuple[str, str, float], dict] = {}


def _dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0.0
    return round(total / 1e6, 1)


def probe(mount: Mount, use_cache: bool = True) -> dict:
    """探测一个挂载项: 是否可用、多少个相、占多大、失败原因。

    Returns:
        ``{ok, rows, size_mb, engine, error, hint, detail, has_top_peaks}``
    """
    p = mount.path
    base = {"ok": False, "rows": 0, "size_mb": 0.0, "engine": mount.engine,
            "error": "", "hint": "", "detail": "", "has_top_peaks": False}
    if p is None:
        base["error"] = "unmounted"
        return base
    try:
        stamp = p.stat().st_mtime
    except OSError:
        base["error"] = "missing"
        base["detail"] = str(p)
        return base
    key = (mount.id, str(p), stamp)
    if use_cache and key in _PROBE_CACHE:
        return dict(_PROBE_CACHE[key])

    res = dict(base)
    if mount.kind == "polydb":
        res.update(_probe_polydb(p))
    elif mount.kind == "user":
        res.update(_probe_user(p))
    else:
        from polyxrd.services.db_import import inspect_db_file

        ins = inspect_db_file(p)
        res.update({
            "ok": ins.ok,
            "rows": ins.rows,
            "size_mb": ins.size_mb,
            "error": ins.error,
            "hint": ins.hint,
            "has_top_peaks": ins.has_top_peaks,
            "detail": "",
        })
    if use_cache:
        _PROBE_CACHE[key] = dict(res)
    return res


def _probe_polydb(p: Path) -> dict:
    try:
        from polyxrd.services.polydb import PolyDatabase

        db = PolyDatabase(p)
        if not db.is_ready():
            return {"error": "polydb_not_ready", "detail": str(p),
                    "size_mb": _dir_size_mb(p)}
        st = db.stats()
        return {"ok": True, "rows": int(st.phases), "size_mb": _dir_size_mb(p),
                "detail": f"variant={st.variant or '?'}"}
    except Exception as e:  # noqa: BLE001 - 探测失败原因原样给 UI
        return {"error": "polydb_error", "detail": f"{e}"}


def _probe_user(p: Path) -> dict:
    try:
        from polyxrd.services import user_db

        st = user_db.user_stats()
        return {"ok": bool(st.get("rows")), "rows": int(st.get("rows") or 0),
                "size_mb": float(st.get("size_mb") or 0.0),
                "error": "" if st.get("rows") else "user_db_empty"}
    except Exception as e:  # noqa: BLE001
        return {"error": "user_db_error", "detail": f"{e}"}


def probe_all(mounts: Optional[Iterable[Mount]] = None) -> list[dict]:
    """探测全部挂载项, 返回 ``mount 字段 + probe 字段`` 合并后的行数据。"""
    out: list[dict] = []
    for m in (mounts if mounts is not None else all_mounts()):
        row = {"mount": m, "id": m.id, "kind": m.kind,
               "path": str(m.path) if m.path else "",
               "exists": m.exists,
               "builtin": m.builtin, "variant": m.variant,
               "label_key": m.label_key, "label": m.display_name()}
        row.update(probe(m))
        out.append(row)
    return out


def clear_probe_cache() -> None:
    _PROBE_CACHE.clear()


# ── 与检索链路的接缝 ──────────────────────────────────────────

def resolve_mount(db_source: str) -> Optional[Mount]:
    """把 ``db_source`` 解析成挂载项 (解析不出返回 None)。

    与 :func:`resolve_source` 的区别: 这里返回整条记录, 调用方可以据此判断
    "这是内置项还是用户自加项" (决定要不要传显式库路径) 以及"库还在不在"。
    """
    key = (db_source or "").strip()
    if not key:
        return None
    key = _LEGACY_ALIASES.get(key, key)
    if key == "polydb":
        key = "polydb:cod-inorg"
    m = get_mount(key)
    if m is not None:
        return m
    if key in KIND_ENGINE:
        # 类型名本身: 合成一条"按配置解析路径"的临时记录
        return Mount(id=key, kind=key, path=None, builtin=True,
                     label_key=KIND_LABEL_KEY.get(key, ""))
    return None


def resolve_source(db_source: str) -> tuple[Optional[str], Optional[Path]]:
    """把物相检索的 ``db_source`` 解析成 ``(kind, path)``。

    兼容三种写法, 保证历史代码与历史测试不受影响:
      · 内置挂载 id (``pdf2`` / ``cod_index`` / ``xinmatch`` / ``polydb:cod-inorg``);
      · 老字面量别名 (``cod_full`` / ``polydb`` / ``polydb_full`` ...);
      · 用户自加项 id (``polydb:1a2b3c4d``)。

    解析不出 (例如 ``builtin`` / ``merged``, 或库已被挪走) 时返回 ``(None, None)``,
    调用方据此走原有分支。
    """
    m = resolve_mount(db_source)
    if m is None:
        return None, None
    return m.kind, (m.path if m.exists else None)


def source_entries() -> list[dict]:
    """给「数据源下拉」用的条目列表 (= 列表式挂载的全部行 + 探测结果)。

    不可用的项也返回并带 ``ok=False``, 由 UI 置灰 —— 让用户看见"这个库现在
    不可用", 而不是在列表里找不到而以为程序坏了。
    """
    return probe_all()


def describe(db_source: str) -> str:
    """一行人类可读描述 (日志/状态栏用)。"""
    kind, path = resolve_source(db_source)
    if kind is None:
        return db_source or "-"
    return f"{kind} @ {path}" if path else kind


def _why_not_mounted(path: Path, reasons: list[str] | None = None) -> str:
    """拼一句能指向下一步的失败说明。"""
    if not path.exists():
        return f"路径不存在：{path}"
    if path.is_dir():
        if not _iter_db_files(path) and not _iter_polydb_dirs(path):
            return ("该文件夹下没有 .sqlite / .db 文件，也没有 polyDB 目录"
                    "（含 meta.json + index.sqlite）；只扫本层，不递归子目录。")
    detail = ""
    if reasons:
        detail = "；".join(reasons[:3])
        if len(reasons) > 3:
            detail += f" 等 {len(reasons)} 个"
    if detail:
        return f"这个路径上的数据库都不合格：{detail}"
    return f"这个路径上没有可用的数据库：{path}"


#: 目录扫描时认的 sqlite 后缀（v4.1.0 起只剩 PDF2 一类 sqlite 库）。
_DB_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".db3", ".sqlite2")


def _iter_db_files(path: Path) -> list[Path]:
    """目录本层的候选数据库文件 (排除 .bak / ~ / .tmp 备份)。"""
    out: list[Path] = []
    try:
        for p in sorted(path.iterdir()):
            if not p.is_file():
                continue
            name = p.name.lower()
            # 备份命名有两种写法: `x.sqlite~` 与 `x~.sqlite`, 一律按"名字里带 ~"排除
            if ".bak" in name or "~" in name or name.endswith(".tmp"):
                continue
            if p.suffix.lower() in _DB_SUFFIXES:
                out.append(p)
    except OSError:
        return []
    return out


def _iter_polydb_dirs(path: Path) -> list[Path]:
    """目录**本层与下一层**的 polyDB 容器。

    下一层也扫, 是因为常见布局是 ``PolyXRD-DataBase/polydb/<xxx>.polyDB`` ——
    用户指到 ``polydb`` 目录时应当一次把里面几份库都挂上。
    """
    out: list[Path] = []
    try:
        for d in sorted(path.iterdir()):
            if not d.is_dir():
                continue
            if is_polydb_dir(d):
                out.append(d)
            else:
                try:
                    out.extend(sorted(x for x in d.iterdir()
                                      if x.is_dir() and is_polydb_dir(x)))
                except OSError:
                    continue
    except OSError:
        return out
    return out


def mount_any(path: str | Path) -> list[Mount]:
    """挂载一个路径下**全部**合格的库, 一次挂全 (幂等)。

    判据只有"内容合格", 与放在哪个文件夹无关:

      · 文件: 逐个按 sqlite 库判别 (COD 无机物 / 全库索引 / PDF2 / XinMatch);
      · 目录: 本层的 sqlite 文件 + 本层/下一层的 polyDB 容器。

    挂载**不改动任何配置槽位** —— 全部记进挂载注册表, 所以同一类型可以挂
    多份, 也不会把用户原有的槽位设置顶掉 (旧 ``db_import.mount_databases``
    是"每类覆盖配置槽位"的语义, 只保留给兼容用途)。

    Args:
        path: 数据库文件, 或含库的文件夹。

    Raises:
        ValueError: 一个都没挂上, 消息带人工可读原因。
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(_why_not_mounted(p))

    if is_polydb_dir(p):
        candidates: list[Path] = [p]
    elif p.is_file():
        candidates = [p]
    elif p.is_dir():
        candidates = _iter_polydb_dirs(p) + _iter_db_files(p)
    else:
        candidates = []

    mounted: list[Mount] = []
    reasons: list[str] = []
    for cand in candidates:
        try:
            mounted.append(add_mount(cand))
        except ValueError as e:
            reasons.append(f"{cand.name}: {e}")
            continue

    if not mounted:
        raise ValueError(_why_not_mounted(p, reasons))
    clear_probe_cache()
    return mounted


__all__ = [
    "KIND_ENGINE", "KIND_LABEL_KEY", "Mount",
    "add_mount", "active_id", "active_mount", "all_mounts", "clear_probe_cache",
    "default_mounts", "describe", "detect_kind", "get_mount", "is_polydb_dir",
    "mount_any", "probe", "probe_all", "remove_mount", "resolve_mount",
    "resolve_source", "set_active", "source_entries",
]
