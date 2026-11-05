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
5. **类型可注册 (v4.6.0)**: 挂载类型不再写死成 if/elif 的三种 kind, 而是登记
   在 :data:`MOUNT_KINDS` 注册表里 (见 :class:`MountKind`)。内置的 polyDB /
   PDF2 / user 只是**种子**; 插件或集成方调 :func:`register_kind` 就能让一种
   新格式享受一等公民待遇 —— 自动判别、探测、列表展示、检索分发全部自动接上,
   不必改本模块。判别/探测函数一律写成**薄包装**, 调用时才解析模块级函数名,
   这样测试 monkeypatch `_probe_polydb` 一类函数仍然生效。
6. **元数据可展示**: :func:`probe` 额外返回 polyDB 的 `meta` / `dataset` /
   `built` / `schema_version` —— 界面要能说清"这是哪份库、哪版格式、什么时候
   构的"。这些键是**附加**的: 现有键名与含义一个不变, 老版 meta.json 与老版
   db_mounts.json 都不需要迁移 (缺字段一律退化为空串 / 0)。
7. **可重命名**: 用户自加的库可以改名 (:func:`rename_mount`), 只改这一行的
   `label`; 空名 = 恢复按目录名/文件名显示。内置项的名字由类型/变体决定,
   不许改 —— 否则同类型的两份库在列表里会变得分不清哪份是哪份。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

#: 支持的挂载类型 → 检索引擎。
#: 引擎名即 ``PhaseIdentifier.identify_with_*`` 的后缀, 便于按 kind 分发。
#:
#: v5.2 起**只有两种**: 参考库一律是 polyDB（COD-Inorg / COD-Full /
#: PDF2-2004 三个变体共用同一套 reader 与打分），``user`` 是用户自建库。
#: PDF2-2004 的独立 sqlite 通道（kind ``pdf2``）已随旧格式一并删除。
KIND_ENGINE: dict[str, str] = {
    "polydb": "polydb",
    "user": "user",
}

#: 类型 → i18n 键 (内置项显示名)。用户自己加的多份库用"类型名 · 目录名"区分。
KIND_LABEL_KEY: dict[str, str] = {
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
#:
#: ``pdf2`` 这个 id 故意保持不变：历史项目文件的 ``db_source="pdf2"`` 与
#: 历史测试里的字面量都还要能用，只是它现在指向 polyDB 变体 ``pdf2-2004``。
_POLYDB_DEFAULT_IDS = {
    "polydb:cod-inorg": "cod-inorg",
    "polydb:cod-full": "cod-full",
    "pdf2": "pdf2-2004",
}

#: polyDB 变体 → i18n 键。各变体是独立的库，在列表里必须能一眼区分。
_POLYDB_LABEL_KEY = {
    "cod-inorg": "db_mounts.kind.polydb_inorg",
    "cod-full": "db_mounts.kind.polydb_full",
    "pdf2-2004": "db_manager.kind.pdf2",
}


# ── 类型注册表 ────────────────────────────────────────────────
#
# v4.6.0 之前, "这个路径是哪类库"由 detect_kind 里的 if/elif 和 probe() 里的
# if/elif 各自回答一遍, is_dir / engine 又各写一次。只有三种内置 kind 时还能
# 接受, 但每多一种库都要同时改四处, 插件想挂自建格式就只能改源码。注册表把
# 这四处收敛成 MountKind 的六个字段, 内置三类降级为**种子注册**。

@dataclass(frozen=True)
class MountKind:
    """一类可挂载数据库的完整描述 (= 注册表里的一条)。

    Attributes:
        key: 类型名; 用户自加项的 id 前缀与 ``db_source`` 的 kind 段都用它。
        engine: 检索引擎名 (``PhaseIdentifier.identify_with_*`` 的后缀)。
        probe: ``Path -> dict`` 的只读探测; 返回的键并入 :func:`probe` 的结果。
            失败时返回 ``error`` 短标记 (如 ``polydb_not_ready``), 由 UI 译文案。
            **不许**在这里改配置 —— 探测会被列表刷新高频调用。
        detect: ``Path -> bool`` 的纯判别; 目录型看目录、文件型看文件 (由
            ``is_dir`` 决定)。判不出就返回 False, 不抛异常。
        label_key: 内置项的 i18n 显示名键; 用户自加项用不到 (空串)。
        is_dir: True = 库是目录容器 (polyDB 这类), False = 单个库文件 (sqlite)。
    """

    key: str
    engine: str
    probe: Callable[[Path], dict]
    detect: Callable[[Path], bool]
    label_key: str = ""
    is_dir: bool = False


#: 已注册类型 → MountKind。内置三类在模块末尾由 :func:`_seed_builtin_kinds`
#: 注册 (那时探测/判别函数都已定义; lambda 仍延迟到调用时才解析函数名)。
MOUNT_KINDS: dict[str, MountKind] = {}


def register_kind(kind: MountKind | None = None, *, replace: bool = False,
                  **fields) -> MountKind:
    """注册一类可挂载的数据库, 让它成为与内置类型平级的一等公民。

    注册后立即生效: :func:`detect_kind` 会认它、:func:`add_mount` 会收它,
    它会出现在 :func:`all_mounts` / :func:`probe_all` / :func:`source_entries`
    里, ``Mount.is_dir`` / ``Mount.engine`` 也按注册信息回答。

    Args:
        kind: 完整的 :class:`MountKind`。
        replace: key 已注册时是否覆盖。默认拒绝 —— 两个来源抢同一个类型名
            应当报错, 而不是后注册的静默顶掉前一个; 内置类型想换实现时由
            本模块自己用 ``replace=True`` 重注册。
        **fields: 省略 ``kind`` 时按 :class:`MountKind` 的字段名逐个给,
            便于调用方少写一层构造 (例如只登记一个目录型库)。

    Raises:
        ValueError: key 为空, 或重复注册且未给 ``replace=True``。
    """
    if kind is None:
        kind = MountKind(**fields)
    elif fields:
        raise TypeError("register_kind(): 传了 MountKind 就不能再给字段")
    if not kind.key:
        raise ValueError("挂载类型必须有 key")
    if kind.key in MOUNT_KINDS and not replace:
        raise ValueError(f"挂载类型已注册: {kind.key}")
    MOUNT_KINDS[kind.key] = kind
    # 兼容层: 老代码直接读这两个 dict (UI 类型下拉、db_source 解析等),
    # 注册/覆盖时同步写进去, 不要求外部跟着改成读注册表。
    KIND_ENGINE[kind.key] = kind.engine
    KIND_LABEL_KEY[kind.key] = kind.label_key
    return kind


def get_kind(key: str) -> Optional[MountKind]:
    """按类型名取注册信息; 未注册返回 None (旧 json 里的未知 kind 由此跳过)。"""
    return MOUNT_KINDS.get(key or "")


def iter_kinds() -> tuple[MountKind, ...]:
    """全部已注册类型 (注册顺序的快照, 迭代中注册/注销不会改变本次结果)。"""
    return tuple(MOUNT_KINDS.values())


@dataclass(frozen=True)
class Mount:
    """一个已挂载的数据库 (= 列表里的一行)。

    Attributes:
        id: 稳定标识; 也是物相检索的 ``db_source`` 取值。
        kind: 库类型, 见 :data:`MOUNT_KINDS` 注册表。
        path: 库位置。目录型 (polyDB) 是**目录**, 文件型是**文件**; 未挂载时可为 None。
        label_key: 内置项的 i18n 显示名键 (用户自加项为空)。
        label: 用户自定义显示名 (rename_mount 写这里) / 空 = 按目录文件名显示。
        builtin: True = 由配置槽位派生 (卸载 = 清配置), False = 写在本模块 json 里。
        variant: polyDB 变体 (``cod-inorg`` / ``cod-full``); 非 polyDB 为空串。
        dataset: polyDB 数据集名 (meta.json 的 name / dataset); 其余类型为空串。
        built: polyDB 构建时间 (meta.json 的 build.date / started_at)。
        schema_version: polyDB 格式版本; 其余类型为 0。
    """

    id: str
    kind: str
    path: Optional[Path] = None
    label_key: str = ""
    label: str = ""
    builtin: bool = True
    variant: str = ""
    #: 下面三个是 polyDB 元数据在"已落盘挂载项"上的缓存 (v4.6.0 新增, 可缺省)。
    #: 库文件被挪走时 probe 读不到 meta.json, 列表仍能显示"它是哪份库"。
    dataset: str = ""
    built: str = ""
    schema_version: int = 0

    # ── 便捷属性 ──────────────────────────────────────────
    @property
    def is_dir(self) -> bool:
        # 目录/文件由注册表决定: 新注册的目录型库不必再改这里。
        spec = get_kind(self.kind)
        return bool(spec.is_dir) if spec is not None else False

    @property
    def exists(self) -> bool:
        p = self.path
        if p is None:
            return False
        return p.is_dir() if self.is_dir else p.is_file()

    @property
    def engine(self) -> str:
        spec = get_kind(self.kind)
        return spec.engine if spec is not None else ""

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


def _as_int(value, default: int = 0) -> int:
    """把 json 里的版本号/计数安全转 int; 坏值退化为默认值而不是抛异常。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


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
    # 用户自建库: 位置由 user_db 固定管理, 这里只作为"可检索的一行"出现
    try:
        from polyxrd.services import user_db

        _add("user", "user", user_db.user_db_path(), KIND_LABEL_KEY["user"])
    except Exception:  # noqa: BLE001
        pass
    return out


def _custom_mounts() -> list[Mount]:
    """读取用户自加项。

    只认**当前已注册**的 kind: 旧版 json 里残留的未知类型 (例如已删除的检索
    引擎) 直接跳过 —— 列表里出现一行永远"不可用"的幽灵库, 比少一行更糟。
    老文件缺 dataset/built/schema_version 时一律当空值, 不需要迁移。
    """
    out: list[Mount] = []
    for raw in _load_store().get("mounts", []):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        path = raw.get("path") or ""
        if get_kind(kind) is None or not path:
            continue
        out.append(Mount(
            id=str(raw.get("id") or _mount_id(kind, Path(path))),
            kind=kind,
            path=Path(path),
            label=str(raw.get("label") or ""),
            builtin=False,
            variant=str(raw.get("variant") or ""),
            dataset=str(raw.get("dataset") or ""),
            built=str(raw.get("built") or ""),
            schema_version=_as_int(raw.get("schema_version")),
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
        path: 库文件 (sqlite / 自定义单文件库) 或库目录 (polyDB / 自定义目录型库)。
        kind: 显式指定类型; 省略则按注册表 (见 :data:`MOUNT_KINDS`) 自动判别。
        label: 自定义显示名; 省略时由目录名/完整文件名生成。

    Raises:
        ValueError: 路径不合格 (不存在 / 不是已注册类型的库), 消息带人工可读原因。
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
    # polyDB 的元数据在挂载时**顺手落盘**: 库之后被挪走/移动硬盘没插上时,
    # 列表仍能说清"这是哪份库、哪版格式、什么时候构的", 不必等 probe 读到目录。
    meta: dict = _read_polydb_meta(p) if real_kind == "polydb" else {}
    data = _load_store()
    mounts = [m for m in data.get("mounts", []) if isinstance(m, dict)]
    for raw in mounts:
        if raw.get("id") == mid:
            return Mount(id=mid, kind=real_kind, path=p,
                         label=str(raw.get("label") or label), builtin=False,
                         variant=str(raw.get("variant") or ""),
                         dataset=str(raw.get("dataset") or ""),
                         built=str(raw.get("built") or ""),
                         schema_version=_as_int(raw.get("schema_version")))
    record = {
        "id": mid,
        "kind": real_kind,
        "path": str(p.resolve()),
        "label": label,
        "variant": str(meta.get("variant") or ""),
        "added_at": _now(),
    }
    if real_kind == "polydb":
        # 仍是同一份 version=1 的 json: 新键只是附加 —— 老版本读到多余键会
        # 忽略, 老文件缺这些键时 _custom_mounts 也按空值处理 (双向兼容)。
        record.update({
            "dataset": str(meta.get("dataset") or ""),
            "built": str(meta.get("built") or ""),
            "schema_version": _as_int(meta.get("schema_version")),
        })
    mounts.append(record)
    data["mounts"] = mounts
    _save_store(data)
    return Mount(id=mid, kind=real_kind, path=p, label=label, builtin=False,
                 variant=str(meta.get("variant") or ""),
                 dataset=str(meta.get("dataset") or ""),
                 built=str(meta.get("built") or ""),
                 schema_version=_as_int(meta.get("schema_version")))


def remove_mount(mount_id: str) -> None:
    """从列表移除一个挂载项。

    内置项: 清对应配置槽位 (与旧「取消挂载」等价); 用户自加项: 从 json 删掉。
    """
    m = get_mount(mount_id)
    if m is None:
        raise KeyError(mount_id)
    if m.builtin:
        from polyxrd.config import get_config

        if m.kind == "polydb":
            get_config().set_polydb_path(None, m.variant or "cod-inorg")
        elif m.kind == "user":
            raise ValueError("用户自建库请在其管理界面清空, 不能在此卸载")
        if active_id() == mount_id:
            set_active("")
        return
    data = _load_store()
    data["mounts"] = [r for r in data.get("mounts", [])
                      if isinstance(r, dict) and r.get("id") != mount_id]
    if data.get("active") == mount_id:
        data["active"] = ""
    _save_store(data)


def rename_mount(mount_id: str, label: str) -> Mount:
    """给用户自加的挂载项改名 (**只改这一行的显示名**, 不碰库文件与其他行)。

    Args:
        mount_id: 挂载项 id。
        label: 新显示名; 空串/纯空白 = 清掉自定义名, 恢复按目录名/文件名显示
            (改名后想"反悔"就传空串, 不必重新挂载)。

    Returns:
        更新后的 :class:`Mount` (其 ``label`` 已生效)。

    Raises:
        KeyError: ``mount_id`` 不在列表里。
        ValueError: 内置项不允许改名。

    为什么内置项不许改: 内置项的显示名 = "类型/变体", 是用户辨认"这行是哪份
    库"的唯一依据; 允许改成"我的库"之后, 同类型的另一份内置库在列表里就分不
    清了。用户真想自定义, 应该把自己那份库单独挂进来。

    只落盘 ``mounts[].label``; 仍按整份 json 原子替换 (不就地改文件)。
    probe 的结果与显示名无关, 所以不动探测缓存; 列表刷新时行名取
    ``Mount.display_name()``, 立刻就能看到新名字。
    """
    m = get_mount(mount_id)
    if m is None:
        raise KeyError(mount_id)
    if m.builtin:
        raise ValueError("内置挂载项的显示名由类型/变体决定, 不能重命名"
                         "（想用自定义名请改为挂载你自己的那份库）")
    data = _load_store()
    mounts = [r for r in data.get("mounts", []) if isinstance(r, dict)]
    target = next((r for r in mounts if r.get("id") == mount_id), None)
    if target is None:
        # all_mounts 里有、json 里没有: 理论上不该发生 (自加项都写在 json 里),
        # 真发生了说明 store 被外部改坏, 按"找不到"报, 不伪造一个落盘项。
        raise KeyError(mount_id)
    clean = (label or "").strip()
    target["label"] = clean
    target["renamed_at"] = _now()
    data["mounts"] = mounts
    _save_store(data)
    return replace(m, label=clean)


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

def _read_polydb_meta(path: str | Path) -> dict:
    """安全读取 polyDB 的 ``meta.json``, 返回列表/详情要展示的摘要。

    Args:
        path: polyDB 目录 (误传文件时按"没有 meta"处理, 不抛异常)。

    Returns:
        ``{format, schema_version, variant, dataset, built, counts}``;
        文件不存在 / JSON 坏 / 顶层不是 dict 时返回同结构的空摘要 —— 这只是
        描述性信息, **绝不能**因为库是半成品而把挂载页整体弄崩。

    meta.json 的字段在不同构库脚本版本里略有差异, 这里做归一化:
      · 数据集名: ``name`` 优先, 其次 ``dataset``; 两者都没有就是空串, 由 UI
        用目录名兜底。不拿 ``source.scope`` 冒充 —— "inorg" 是构建范围,
        不是库名, 显示出来只会让人误以为那就是数据集名;
      · 构建时间: ``build.date`` 优先, 其次 ``build.started_at`` (现有构库
        产物只有后者; 以后加了 date 也不用改这里);
      · counts 里只保留能转 int 的项, 坏值直接丢, 防止把展示链带崩。
    """
    empty = {"format": "", "schema_version": 0, "variant": "",
             "dataset": "", "built": "", "counts": {}}
    try:
        raw = json.loads((Path(path) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    build = raw.get("build")
    if not isinstance(build, dict):
        build = {}
    counts: dict[str, int] = {}
    raw_counts = raw.get("counts")
    if isinstance(raw_counts, dict):
        for k, v in raw_counts.items():
            try:
                counts[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    return {
        "format": str(raw.get("format") or ""),
        "schema_version": _as_int(raw.get("schema_version")),
        "variant": str(raw.get("variant") or ""),
        "dataset": str(raw.get("name") or raw.get("dataset") or ""),
        "built": str(build.get("date") or build.get("started_at")
                     or raw.get("built") or ""),
        "counts": counts,
    }


def _read_polydb_variant(path: Path) -> str:
    """兼容旧调用: 只取变体名 (解析逻辑统一在 :func:`_read_polydb_meta`)。"""
    return str(_read_polydb_meta(path).get("variant") or "")


def is_polydb_dir(path: str | Path) -> bool:
    """polyDB 目录容器的判据: 有 ``index.sqlite`` + ``meta.json``。

    不直接依赖 PolyDatabase 打开 (那会读 memmap); 只做存在性判别, 快。
    """
    p = Path(path)
    return (p.is_dir() and (p / "index.sqlite").is_file()
            and (p / "meta.json").is_file())


def _detect_any(p: Path) -> tuple[str, str]:
    """按注册表判别路径, 返回 ``(kind, 失败说明)``。

    探测顺序是**后注册的优先**: 插件新增的格式通常比内置类型更具体, 让插件
    先认。v5.2 起内置只有 polyDB（目录型）与用户库（不参与自动判别）。
    """
    if p.is_dir():
        for spec in reversed(iter_kinds()):
            if spec.is_dir and spec.detect(p):
                return spec.key, ""
        return "", "目录里没有 meta.json + index.sqlite, 不是 polyDB 目录"
    for spec in reversed(iter_kinds()):
        if not spec.is_dir and spec.detect(p):
            return spec.key, ""
    # 文件路径没有任何注册类型认领。v5.2 起物相库只支持 polyDB 目录容器，
    # 旧的 PDF2 / COD sqlite 通道已删除 —— 这里给的是可执行的迁移指引。
    if p.suffix.lower() in _DB_SUFFIXES:
        if _looks_like_legacy_cod(p):
            return "", (
                "旧格式 COD / XinMatch sqlite 检索库：自 v4.1.0 起只支持 polyDB。"
                "请改用 PolyXRD-DataBase 的 polyDB 库。")
        return "", (
            "旧格式 sqlite 物相库：自 v5.2 起只支持 polyDB 目录"
            "（PDF2-2004 也已改为 polyDB，请用 build_pdf2_polydb.py 重打包）。")
    return "", f"不是可用的数据库文件: {p.name}"


def detect_kind(path: str | Path, expect: str | None = None) -> tuple[str, str]:
    """判别一个路径属于哪类库, 返回 ``(kind, 说明)``; 判不出时 kind 为空。

    判别规则全部来自注册表 (见 :data:`MOUNT_KINDS`), 本函数只负责"自动认"
    与"按调用方声明的类型校验"两种模式。

    Args:
        expect: 调用方已声明的类型; 给了就**只做校验**, 不猜 —— 用户明确
            说"这是个 PDF2 库"时, 若内容其实是 polyDB 目录, 应当报错而不是
            静默改判 (拿错库只会静默检索不到东西, 这是本项目踩过的坑)。
    """
    p = Path(path)
    found, reason = _detect_any(p)
    if not found:
        return "", reason
    if expect and found != expect:
        spec = get_kind(found)
        if spec is not None and spec.is_dir:
            name = "polyDB 目录" if found == "polydb" else f"{found} 目录"
            return "", f"这是 {name}, 不是 {expect}"
        return "", f"该文件是 {found}, 不是 {expect}"
    return found, ""


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
        ``{ok, rows, size_mb, engine, error, hint, detail, has_top_peaks,
        meta, dataset, built, schema_version}``
        —— 后四个是 v4.6.0 **附加**的 polyDB 元数据; 其余类型 / 老调用方
        拿到的仍是原来的键 (meta 为空 dict, 版本号 0)。

    探测分派走注册表: 自定义类型只要在 :class:`MountKind.probe` 里给了实现,
    这里不需要再加分支。插件探测函数自己抛异常时兜底成 ``probe_error`` ——
    一行坏的插件库不能把整张挂载表 (以及依赖它的物相页) 拖崩。
    """
    p = mount.path
    base = {"ok": False, "rows": 0, "size_mb": 0.0, "engine": mount.engine,
            "error": "", "hint": "", "detail": "", "has_top_peaks": False,
            "meta": {}, "dataset": mount.dataset, "built": mount.built,
            "schema_version": mount.schema_version}
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
    spec = get_kind(mount.kind)
    try:
        if spec is not None:
            res.update(spec.probe(p))
        else:
            # 未注册的 kind（旧 json 残留）：明确报"类型未知"，不再尝试任何
            # 旧格式探测 —— v5.2 起只认注册表里的类型。
            res.update({"error": "unknown_kind", "detail": mount.kind})
    except Exception as e:  # noqa: BLE001 - 探测失败原因原样给 UI
        res.update({"error": "probe_error", "detail": f"{e}"})
    if use_cache:
        _PROBE_CACHE[key] = dict(res)
    return res


def _probe_polydb(p: Path) -> dict:
    """polyDB 目录的探测 (只读 meta.json + 只读打开数组段, 不改任何配置)。

    失败时 ``error`` 仍是 ``polydb_not_ready`` / ``polydb_error`` 两个老值
    (UI 与历史测试按它出文案), 但**仍附带 meta 摘要**: 半成品/损坏的库也要
    能显示"它本该是哪份库", 否则用户只看到一行"不可用"无从判断修哪个文件。
    """
    meta = _read_polydb_meta(p)
    extra = {"meta": meta, "dataset": meta["dataset"], "built": meta["built"],
             "schema_version": meta["schema_version"]}
    try:
        from polyxrd.services.polydb import PolyDatabase

        db = PolyDatabase(p)
        if not db.is_ready():
            return {"error": "polydb_not_ready", "detail": str(p),
                    "size_mb": _dir_size_mb(p), **extra}
        st = db.stats()
        return {"ok": True, "rows": int(st.phases), "size_mb": _dir_size_mb(p),
                "detail": f"variant={st.variant or '?'}", **extra}
    except Exception as e:  # noqa: BLE001 - 探测失败原因原样给 UI
        return {"error": "polydb_error", "detail": f"{e}", **extra}


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
    """探测全部挂载项, 返回 ``mount 字段 + probe 字段`` 合并后的行数据。

    行里带 ``engine`` (检索引擎名) 与 ``meta`` / ``dataset`` / ``built`` /
    ``schema_version`` (polyDB 元数据); 名称取 ``Mount.display_name()``,
    所以 :func:`rename_mount` 改完名刷新列表就能看到。
    """
    out: list[dict] = []
    for m in (mounts if mounts is not None else all_mounts()):
        row = {"mount": m, "id": m.id, "kind": m.kind,
               "path": str(m.path) if m.path else "",
               "exists": m.exists,
               "builtin": m.builtin, "variant": m.variant,
               "label_key": m.label_key, "label": m.display_name(),
               "engine": m.engine,
               "meta": {}, "dataset": m.dataset, "built": m.built,
               "schema_version": m.schema_version}
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
        if not _iter_polydb_dirs(path):
            # 目录里可能全是旧格式 sqlite（用户照着老教程找来的）。只说"没有
            # polyDB 目录"会让他以为指错了文件夹 —— 把旧库点名并给出迁移方向。
            legacy = _iter_db_files(path)
            if legacy:
                names = "、".join(f.name for f in legacy[:3])
                if len(legacy) > 3:
                    names += f" 等 {len(legacy)} 个"
                return (f"该文件夹下没有 polyDB 目录（含 meta.json + index.sqlite）；"
                        f"发现旧格式 sqlite 库 {names} —— 自 v5.2 起不再支持，"
                        f"请改用 polyDB 目录（PDF2-2004 需用 build_pdf2_polydb.py 重打包）。")
            return ("该文件夹下没有 polyDB 目录（含 meta.json + index.sqlite）；"
                    "只扫本层与下一层，不递归更深。")
    detail = ""
    if reasons:
        detail = "；".join(reasons[:3])
        if len(reasons) > 3:
            detail += f" 等 {len(reasons)} 个"
    if detail:
        return f"这个路径上的数据库都不合格：{detail}"
    return f"这个路径上没有可用的数据库：{path}"


#: 目录扫描时用于**识别并给出迁移提示**的 sqlite 后缀（v5.2 起不再挂载）。
_DB_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".db3", ".sqlite2")


def _is_backup_name(name: str) -> bool:
    """备份命名 (``.bak`` / 名字带 ``~`` / ``.tmp``) —— 一律不当成库。

    备份有两种写法: ``x.sqlite~`` 与 ``x~.sqlite``; 目录形式同样会有
    ``X.polyDB.bak`` / ``X~.polyDB``。手工建库或复制库时常留下这种目录,
    它们同样有 meta.json + index.sqlite, 单看内容分辨不出来 —— 挂上去了
    用户会在数据源下拉里看到两个同名库, 分不清哪份是备份。
    """
    n = name.lower()
    return ".bak" in n or "~" in n or n.endswith(".tmp")


def _iter_db_files(path: Path) -> list[Path]:
    """目录本层的候选数据库文件 (排除 .bak / ~ / .tmp 备份)。"""
    out: list[Path] = []
    try:
        for p in sorted(path.iterdir()):
            if not p.is_file():
                continue
            if _is_backup_name(p.name):
                continue
            if p.suffix.lower() in _DB_SUFFIXES:
                out.append(p)
    except OSError:
        return []
    return out


def _iter_polydb_dirs(path: Path) -> list[Path]:
    """目录**本层与下一层**的 polyDB 容器 (排除备份目录)。

    下一层也扫, 是因为常见布局是 ``PolyXRD-DataBase/polydb/<xxx>.polyDB`` ——
    用户指到 ``polydb`` 目录时应当一次把里面几份库都挂上。
    """
    out: list[Path] = []
    try:
        for d in sorted(path.iterdir()):
            if not d.is_dir() or _is_backup_name(d.name):
                continue
            if is_polydb_dir(d):
                out.append(d)
            else:
                try:
                    out.extend(sorted(x for x in d.iterdir()
                                      if x.is_dir() and is_polydb_dir(x)
                                      and not _is_backup_name(x.name)))
                except OSError:
                    continue
    except OSError:
        return out
    return out


def _looks_like_legacy_cod(p: Path) -> bool:
    """判断一个 sqlite 文件是否更像 v4.1.0 之前的 COD / XinMatch 检索库。

    只读打开，仅用于把 "no_matching_table" 翻译成可执行的迁移指引；
    不参与挂载判定（旧库无论如何都不再支持）。
    """
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return bool(tables & {
        "cod_entries", "cod_atomic_sites", "cod_inorganics",
        "entries", "peaks", "element_combo", "xinmatch_entries",
    })


def mount_any_report(path: str | Path) -> tuple[list[Mount], list[str]]:
    """同 :func:`mount_any`，但把"被跳过的候选 + 原因"也返回给 UI。

    v4.1.2：挂一个混合文件夹时，以前只要有一个库成功就静默丢掉失败原因
    （例如旧 COD sqlite 不再兼容），用户看到"挂载成功"却不知道别的库为何
    没进来。返回值 ``(mounted, skipped_reasons)``。
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(_why_not_mounted(p))

    if p.is_dir() and not is_polydb_dir(p):
        candidates: list[Path] = _iter_polydb_dirs(p)
        legacy = _iter_db_files(p)
    else:
        candidates = [p]
        legacy = []

    mounted: list[Mount] = []
    reasons: list[str] = []
    # 目录里躺着的旧 sqlite 库：不再尝试挂载，但要说清为什么被跳过。
    for f in legacy:
        reasons.append(
            f"{f.name}: 旧格式 sqlite 物相库自 v5.2 起不再支持，请改用 polyDB 目录")
    for cand in candidates:
        try:
            mounted.append(add_mount(cand))
        except ValueError as e:
            reasons.append(f"{cand.name}: {e}")
            continue

    if not mounted:
        raise ValueError(_why_not_mounted(p, reasons))
    clear_probe_cache()
    return mounted, reasons


def mount_any(path: str | Path) -> list[Mount]:
    """挂载一个路径下**全部**合格的库, 一次挂全 (幂等)。

    Args:
        path: 数据库文件, 或含库的文件夹。

    Raises:
        ValueError: 一个都没挂上, 消息带人工可读原因。
    """
    mounted, _skipped = mount_any_report(path)
    return mounted


# ── 内置类型种子 ──────────────────────────────────────────────

def _seed_builtin_kinds() -> None:
    """把内置两类登记进注册表 (在三处探测/判别函数都定义完之后调用)。

    probe/detect 一律写成**薄包装**而不是直接绑函数对象: 测试与本模块使用者
    会 monkeypatch ``_probe_polydb`` / ``_probe_user`` 这些模块级函数, 包一层
    lambda 让名字在**调用时**才解析, monkeypatch 才能生效。
    ``replace=True`` 是给"模块被 reload / 测试里重复 seed"留的余地; 正常
    导入时注册表是空的, 不会覆盖任何人的插件类型。
    """
    # 参考库（COD-Inorg / COD-Full / PDF2-2004 三个变体）: 目录容器,
    # 判据 = meta.json + index.sqlite。PDF2 已是 polyDB，不再有独立 kind。
    register_kind(MountKind(
        key="polydb", engine="polydb",
        label_key=KIND_LABEL_KEY["polydb"],
        probe=lambda p: _probe_polydb(p),
        detect=lambda p: is_polydb_dir(p),
        is_dir=True), replace=True)
    # 用户自建库: 位置由 user_db 自己管, 不参与自动判别 (detect 恒 False),
    # 只作为内置的一行出现在列表里。
    register_kind(MountKind(
        key="user", engine="user",
        label_key=KIND_LABEL_KEY["user"],
        probe=lambda p: _probe_user(p),
        detect=lambda p: False,
        is_dir=False), replace=True)


_seed_builtin_kinds()

__all__ = [
    "KIND_ENGINE", "KIND_LABEL_KEY", "MOUNT_KINDS", "Mount", "MountKind",
    "add_mount", "active_id", "active_mount", "all_mounts", "clear_probe_cache",
    "default_mounts", "describe", "detect_kind", "get_kind", "get_mount",
    "is_polydb_dir", "iter_kinds", "mount_any", "mount_any_report", "probe",
    "probe_all", "register_kind", "remove_mount", "rename_mount",
    "resolve_mount", "resolve_source", "set_active", "source_entries",
]
