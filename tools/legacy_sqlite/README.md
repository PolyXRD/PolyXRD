# legacy_sqlite —— 旧 COD sqlite 运行时维护脚本（已下线）

**这些脚本不参与运行时，也不参与构建。** 保留它们只为历史可查：万一需要对
v4.2.0 之前生成的旧 `cod_index.sqlite` / `COD_inorganics.sqlite` 做考古式
核对或一次性修复。

## 背景

PolyXRD v4.2.0 删除了本地 COD sqlite 运行时（`services/cod_local.py` 与
`services/cif_database.py`）。物相检索改由外挂 **polyDB**（v4.0.0+ 目录容器
格式）承担，相关代码位于：

| 现在的位置 | 承接的旧功能 |
|---|---|
| `src/polyxrd/services/phase_search.py` | Hanawalt 峰匹配打分、d 分箱预筛、强峰列 |
| `src/polyxrd/services/cif_utils.py` | CIF 解析、公式/元素集判定、位点提取 |
| `src/polyxrd/services/cif_minerals.py` | 内置 12 种矿物 CIF 库 + 外部 CIF 目录 |
| `src/polyxrd/services/polydb.py` | polyDB 只读访问（mmap 列存 + 位图倒排） |

## 目录内容

| 脚本 | 用途 |
|---|---|
| `build_inorg_index_db.py` | 从 COD CIF 目录重建 `COD_inorganics*.sqlite` |
| `_embed_cif_into_inorg.py` | 把 CIF 内容内嵌进旧库的 `cif_gz` 列 |
| `_repack_cod_inorg_zip.py` | 重打旧库发布用的 zip 包 |
| `migrate_inorg_formula.py` | 修正 `phases.formula` 被写成空间群符号的 609 条脏数据 |
| `regenerate_reference_db_peaks.py` | 重算旧库参考峰 d-I 表 |
| `repair_inorg_cell.py` | 修复晶胞参数缺失/异常的记录 |
| `audit_reference_db.py` | 旧库参考峰与 CIF 的一致性对账 |
| `dedup_reference_db.py` | 旧库同相去重 |
| `fix_reference_db_boehmite_albite.py` | 勃姆石/钠长石参考峰专项修正 |
| `fix_reference_db_cristobalite.py` | 方石英参考峰专项修正 |
| `fix_reference_db_hkl.py` | hkl 索引专项修正 |
| `fix_reference_db_ncm811.py` | NCM811 参考峰专项修正 |

## 注意

- 这些脚本 **import 已删除的模块**（`polyxrd.services.cod_local` /
  `cif_database`），在当前代码树上无法直接运行。需要使用时，从 git 历史
  取回旧模块：`git show v4.1.2:src/polyxrd/services/cod_local.py`。
- 新库相关工作一律走 `tools/build_polydb.py` / `tools/build_3cod.py` 与
  `scripts/bench_polydb_search.py`、`scripts/polydb_verify.py`、
  `scripts/audit_polydb_bound.py`。
