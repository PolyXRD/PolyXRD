# tools/ · 外挂物相库构建工具（polyDB v1）

本目录放 **polyDB 外挂库的构建器**，让"库"和"程序"都可复现、可版本管理。

v4.0.0 之前这两个工具只存在于开发机的 `PolyXRD-DataBase/tools/`（仓库外），
导致"库是怎么建的"无法追溯、格式演进没有对照物。本次按发布准备要求入库。

> **发布政策（2026-10-23）**：**数据库不在本仓库上传/发布**。库包统一由独立仓库
> [PolyXRD-DataBase](https://github.com/PolyXRD/PolyXRD-DataBase) 的 Releases 分发；
> 本仓库只在本地构建与校验（`scripts/polydb_verify.py` 等），Release 恒 3 个程序附件。

| 文件 | 作用 |
|---|---|
| `build_polydb.py` | COD CIF → `*.polyDB` 目录容器（两阶段并行 + 断点续跑 + 条数守恒检查） |
| `fastcif.py` | 快速 CIF 解析（实测 0.87 ms/条） |
| `fastxrd.py` | 峰计算（与 `build_3cod.py` 定稿口径一致：λ=1.5406、2θ 5~100.76°、等价反射按 2θ 合并、I 归一 1000） |

## 需要的数据（不进仓库）

```
PolyXRD-DataBase/            # 数据根，默认 <仓库父目录>/PolyXRD-DataBase
├── COD/                     # COD 原始 CIF 归档（四级分片目录，~109 GiB）
└── inorg_manifest.sqlite    # COD 清单 + is_inorg 判别（~289 MB）
```

三者都可用环境变量覆盖：

| 变量 | 默认 |
|---|---|
| `POLYXRD_DATABASE_ROOT` | `<仓库父目录>/PolyXRD-DataBase` |
| `POLYXRD_COD_ROOT` | `<数据根>/COD` |
| `POLYXRD_MANIFEST` | `<数据根>/inorg_manifest.sqlite` |

## 建库

```bash
# 无机物库（默认交互库，~79k 输入相）
python tools/build_polydb.py --scope inorg --workers 8

# 全库（~53.5 万相）
python tools/build_polydb.py --scope full --workers 8

# 试产 / 调试：只建前 5000 相到指定目录
python tools/build_polydb.py --scope inorg --limit 5000 --out D:/tmp/test.polyDB
```

产物落在 `<数据根>/polydb/COD-Inorg-<YYYYMMDD>.polyDB` 与
`COD-Full-<YYYYMMDD>.polyDB`（目录容器，格式见
[`docs/外挂库格式规范-polyDB-v1.md`](../docs/外挂库格式规范-polyDB-v1.md)）。

**注意**：首轮全量必须带 `--force`（断点续跑会复用旧 part 文件，陈旧 part 会静默吞数据；
构建器已加条数守恒检查：输入 == 入库 + skip，不平即告警）。

## 验收（建完必须做）

```bash
# 1) 结构 + 校验和 + 抽样回算（L1/L2/L3）
python scripts/polydb_verify.py <库目录>

# 2) 检索正确性：search 前 N vs 全库暴力，逐条一致
python scripts/bench_polydb_bruteforce.py <库目录> --n 100

# 3) 前置键 = 精确前三键
python scripts/audit_polydb_bound.py <库目录>

# 4) 发布冒烟（挂载 → 体检 → 检索 → 精修 → 导出）
python scripts/smoke_release_v400.py
```

## 实测基线（2026-10-21 构建，供对照）

| 库 | 相数 | 体积 | 构建 | 检索 |
|---|---|---|---|---|
| `COD-Inorg-20261021.polyDB` | 77,500 | 89.9 MB | 532 s / 8 进程 | 0.5~0.7 s/样本 |
| `COD-Full-20261021.polyDB` | 521,361 | 1,107.7 MB | — | 1.9~2.3 s/样本 |

skip 原因分布（Inorg）：`no_sites` 1,065 / `no_pattern` 336 / `volume_too_large` 179 /
`no_volume` 118，合计 1,698；79,198 = 77,500 + 1,698 条数守恒。
