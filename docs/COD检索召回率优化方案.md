# COD 检索召回率优化方案

> **版本**: v0.9.11 · **日期**: 2026-09-10
> **问题**: 13 试样 E2E 基准中，COD 无机物库 (71,199 物相) 检索召回率低
> — α-石英、MgCO₃、白云石、白云母、高岭土、钙长石等真物相常落在预筛池 100 名之外
> **根因**: 不是排序问题（排序已优化到 Top-10 27%），而是**召回**问题
> — 真物相在预筛阶段就被截断，下游 FOM 精排无候选可排

---

## 〇、实测复盘（2026-09-10，提交 `3cd3b0d` 后补）

本方案成稿于动手之前，实测后**部分前提被否定**，以实测为准：

| 方案 | 文档判断 | 实测结论 |
|---|---|---|
| **A. `tolerance_rel=0.005`** | P0，修复低角度漏配 | ❌ **不是主杠杆**。放宽 d 容差对 Top-N 无显著贡献，反而引入误配 |
| **D. `min_match=2` + `max_ref_peaks=80`** | P1，提升低含量相召回 | ❌ 同上，未产生显著增益 |
| **真正的主杠杆** | 文档未识别 | ✅ **寻峰参数**。`find_peaks` 默认 `distance=5.0°` 丢弃相邻强线（ZnO 31.8/34.4/36.3 只剩 36.3），平均检出峰 8.8→64 后 Top-40 22→28、MRR +0.066 |
| **排序口径去饱和** | 文档称"排序已优化" | ⚠️ 部分成立。`1-clip(fom/1.2)` 饱和式改为 `0.9·exp(-fom/0.8)+0.1·h`，单独收益 +0~1 不显著 |
| **B/C/E/F（倒排索引、两阶段、分组、强度门槛）** | 待实施 | ⏸ **未实施，前提仍然成立**（全量扫描 71,199 相是真实瓶颈），保留待评估 |

**教训**: 优化前应先做**单变量消融**定位瓶颈，而不是按"看起来最像"的机制（d 容差）下手。
本轮基准脚本见 `tests/bench_*.py`（该目录已 gitignore），完整成绩见 `docs/基准报告-v0.9.11.md`。

---

## 一、现状分析

### 1.1 当前流程

```
实验峰 d-I (13 试样, 15~35 峰)
  → 全量顺序扫描 71,199 物相 (Python 逐行循环, 无倒排索引)
  → d 值匹配 (tolerance=0.02 Å 固定绝对容差)
  → 门槛过滤 (min_match=3, max_ref_peaks=40)
  → Hanawalt 排序截断 (limit=100)
  → 下游 FOM 精排 (强判别器, 但候选池已漏)
```

### 1.2 基准数据

测试集: `E:\TEMP\test_xrd\txt\` 13 个真实试样 / COD 无机物库 / `prefilter_limit=100`

| 排序口径 | Top-1 | Top-5 | Top-10 |
|---|---|---|---|
| 旧 (Hanawalt 字典序) | 12% (6/51) | 22% (11/51) | 24% (12/51) |
| 新 (混合 0.3/0.7) | 14% (7/51) | 25% (13/51) | 27% (14/51) |
| 池=200 时混合口径 | 16% (8/51) | 27% (14/51) | 29% (15/51) |

池从 100 扩到 200 时 Top-10 提升 27%→29%，说明真物相确实被 `limit=100` 截断。

### 1.3 瓶颈定位

| 瓶颈 | 位置 | 机制 | 影响 |
|---|---|---|---|
| **瓶颈 1** | d 值匹配容差 | `tolerance=0.02 Å` 固定绝对容差，在 d=4 Å (2θ≈22°) 只对应 ~0.11° 的 2θ 窗口，比峰 FWHM 还窄 | 低角度真峰漏配 |
| **瓶颈 2** | 全量顺序扫描 | 逐行遍历 71,199 物相做 Python 循环，无 d 值倒排索引 | 性能差 + 无法做更精细的匹配 |
| **瓶颈 3** | 排序截断 | `limit=100` 把排 150+ 的真物相截掉 | 召回率上限被池大小锁死 |
| **瓶颈 4** | 门槛过滤 | `min_match=3` 对低含量相峰数不足时直接丢弃 | 次要相召回低 |
| **瓶颈 5** | 参考峰截取 | `max_ref_peaks=40` 对多峰相覆盖不全 | 召回率受限于参考峰覆盖 |

---

## 二、优化方案

### 方案 A: 启用相对容差 `tolerance_rel`（P0, 一行改动）

**文件**: `src/polyxrd/services/phase_identifier.py` ~L906

**问题**: 当前 `tolerance=0.02 Å` 是纯绝对容差。代码已实现 `tolerance_rel` 参数但默认为 0（关闭）。固定 d 容差在 2θ 空间极不均匀：

| d (Å) | 2θ (°) | 绝对容差 0.02 Å 对应 2θ 窗口 | 问题 |
|---|---|---|---|
| 4.0 | ~22° | ~0.11° | 比峰 FWHM 还窄 → 漏配真峰 |
| 2.0 | ~45° | ~0.23° | 合理 |
| 1.0 | ~90° | ~2.8° | 过宽 → 误配杂相 |

相对分量 `tolerance_rel·d` 让匹配窗口在 2θ 空间近似恒定（低角度放宽、高角度收紧）。

**改动**:

```python
# phase_identifier.py identify_with_cod_inorganics() 调用处
cands = cdb.search_cod_by_d_peaks(
    d_list, i_list,
    tolerance=prefilter_tolerance,        # 0.02 绝对下限
    tolerance_rel=prefilter_tolerance_rel, # 0.005 ← 从 0.0 改为 0.005
    min_match=prefilter_min_match,
    max_ref_peaks=prefilter_max_ref_peaks,
    limit=prefilter_limit,
    elements_allowed=elements_allowed,
)
```

同时把函数签名的默认值改：
```python
prefilter_tolerance_rel: float = 0.005,  # 原 0.0
```

**验证**: `bench_cod_recall.py` 已验证 `rel.5% m3 r40` 配置召回优于基线。

**预期收益**: 低角度峰（d > 3 Å）漏配修复，直接提升石英、白云石等常见矿物召回。

---

### 方案 B: SQLite d-bucket 倒排索引（P1, 结构性改造）

**文件**: `src/polyxrd/services/cif_database.py` 建库 + 查询

**问题**: 当前 `search_cod_by_d_peaks` 逐行遍历 71,199 个物相做 Python 循环匹配，无 d 值倒排索引。每次搜索都扫全表。

**方案**: 建库时新增 `cod_peak_buckets` 倒排表：

```sql
CREATE TABLE cod_peak_buckets (
    cod_id    INTEGER NOT NULL,
    d_bucket  REAL NOT NULL,       -- round(d, 1) 或 round(d*10)/10，分桶键
    d_value   REAL NOT NULL,       -- 精确 d 值
    intensity REAL NOT NULL,
    PRIMARY KEY (cod_id, d_bucket, d_value)
);
CREATE INDEX idx_buckets_d ON cod_peak_buckets(d_bucket);
CREATE INDEX idx_buckets_cod ON cod_peak_buckets(cod_id);
```

**搜索逻辑改为两阶段**:

```python
def search_cod_by_d_peaks_v2(self, measured_d, measured_i, ...):
    # 阶段 1: 用测量峰 d 值查 bucket，收集命中物相 ID 集合
    candidate_ids = set()
    for d in measured_d:
        bucket = round(d, 1)  # 或自定义分桶函数
        rows = conn.execute(
            "SELECT DISTINCT cod_id FROM cod_peak_buckets WHERE d_bucket BETWEEN ? AND ?",
            (bucket - 0.1, bucket + 0.1)
        ).fetchall()
        candidate_ids.update(r["cod_id"] for r in rows)

    # 阶段 2: 仅对命中物相做精细 d-I 匹配 (通常 < 2000 个)
    for cod_id in candidate_ids:
        ref_peaks = conn.execute(
            "SELECT d_value, intensity FROM cod_peak_buckets WHERE cod_id = ?",
            (cod_id,)
        ).fetchall()
        # ... 原有 Hanawalt 评分逻辑 ...
```

**性能对比**:

| 指标 | 旧 (全量扫描) | 新 (倒排索引) |
|---|---|---|
| 扫描物相数 | 71,199 | < 2,000 (通常) |
| 每次搜索耗时 | 1.5~3 s | < 0.2 s (预估) |
| 可放大池 | 100 (耗时受限) | 500+ (无性能压力) |

**建库增量**: `cod_peak_buckets` 表约 71,199 × 40 峰/相 ≈ 285 万行，SQLite 索引后约 30~50 MB，可接受。

---

### 方案 C: 两阶段搜索 — 快筛 + 精排（P0, 中等改动）

**文件**: `src/polyxrd/services/phase_identifier.py` + `cif_database.py`

**问题**: 盲目放大 `prefilter_limit` 到 200 会增加下游 FOM 计算耗时（每个候选要做 pymatgen 峰计算 + FOM 评分）。需要在不增加精排负担的前提下扩大有效池。

**方案**:

```python
# 阶段 1: 主峰 bucket 快筛 → 500 候选 (仅 main_peak_match + top_precision)
cands_raw = cdb.search_cod_by_d_peaks(
    d_list, i_list,
    tolerance=0.02, tolerance_rel=0.005,
    min_match=2, max_ref_peaks=80,
    limit=500,  # 大池快筛
    elements_allowed=elements_allowed,
)

# 阶段 2: 对 500 候选做完整 d-I Hanawalt 精排 → 取 top 200
cands = hanawalt_rerank(cands_raw)[:200]

# 阶段 3: 下游 FOM 精排 (仅 200 候选, 非原 100)
```

这样有效池从 100 扩到 200，但 FOM 精排只增加 100 个候选的耗时（可接受）。

---

### 方案 D: 降低 `min_match` + 提高 `max_ref_peaks`（P1, 两行改动）

**文件**: `src/polyxrd/services/phase_identifier.py` 函数签名

**问题**: `min_match=3` 对低含量相（如 4-1 试样中 Fluorite 仅 3.5%）峰数不足时直接丢弃；`max_ref_peaks=40` 对多峰相覆盖不全。

**改动**:

```python
prefilter_min_match: int = 2      # 原 3 → 2: 低含量相峰少时也能进候选
prefilter_max_ref_peaks: int = 80 # 原 40 → 80: 多峰相覆盖更全
```

**验证**: `bench_cod_recall.py` 已验证 `rel.3% m2 r80` 在多个试样上召回有提升。

**代价**: 候选池变大，需配合方案 C 控制下游耗时。`min_match=2` 可能引入更多杂相，但下游 FOM 是强判别器可以过滤。

---

### 方案 E: Hanawalt 分组预筛（P2, 与方案 B 互补）

**文件**: `src/polyxrd/services/cif_database.py`

**问题**: 当前 `main_peak_match` 只用于排序，不用于预筛。经典 Hanawalt 索引的核心思想是按主峰 d 值分组，搜索时只看最强测量峰附近的组。

**方案**: 建库时按物相最强峰 d 值分桶（0.05 Å 间隔）：

```sql
CREATE TABLE cod_main_peak_groups (
    d_group   REAL NOT NULL,   -- round(d / 0.05) * 0.05
    cod_id    INTEGER NOT NULL,
    main_d    REAL NOT NULL,
    main_i    REAL NOT NULL,
    PRIMARY KEY (d_group, cod_id)
);
CREATE INDEX idx_main_peak_d ON cod_main_peak_groups(d_group);
```

搜索时用测量峰的最强峰 d 值定位：

```python
# 样品最强峰 d 值
main_meas_d = max(measured_d, key=lambda d: measured_i[...])

# 只看 ±0.1 Å 内的组 (2 个桶宽)
groups = conn.execute(
    "SELECT cod_id, main_d, main_i FROM cod_main_peak_groups "
    "WHERE d_group BETWEEN ? AND ?",
    (main_meas_d - 0.1, main_meas_d + 0.1)
).fetchall()
# 仅对这些物相做完整匹配
```

**与方案 B 的关系**: B 是按所有测量峰的 d 值查倒排索引（多对多），E 是按主峰定位（一对一）。两者可叠加：先用 E 缩小到主峰匹配组，再用 B 精细匹配。

---

### 方案 F: 弱峰强度加权预筛门槛（P2, 小改动）

**文件**: `src/polyxrd/services/cif_database.py` `search_cod_by_d_peaks()`

**问题**: 当前 `intensity_weighted_top_recall` 只用于排序，不用于预筛。密集低强度峰物相（如某些杂相）可能碰巧覆盖多个测量弱峰而进入候选池，挤占真物相名额。

**方案**: 增加预筛门槛 — 物相最强去重峰覆盖的测量峰强度和低于全谱强度 10% 的直接淘汰：

```python
# 在 search_cod_by_d_peaks 的循环内, 排序前增加:
if use_intensity and total_i > 0:
    iwt_ratio = covered_i_sum / total_i
    if iwt_ratio < 0.10:  # 物相最强峰解释的测量峰强度不足 10%
        continue  # 直接淘汰, 不进候选池
```

**效果**: 减少杂相干扰，让真物相在候选池中排名更靠前。

---

## 三、实施优先级与路线图

| 优先级 | 方案 | 改动量 | 预期收益 | 依赖 |
|---|---|---|---|---|
| **P0** | A. 启用 `tolerance_rel=0.005` | 1 行 | 修复低角度漏配 | 无 |
| **P0** | C. 两阶段搜索 + 池扩到 200 | 中等 | Top-10 27%→29%+ | A |
| **P1** | D. `min_match=2` + `max_ref_peaks=80` | 2 行 | 低含量相召回提升 | C |
| **P1** | B. d-bucket 倒排索引 | 中等 | 扫描 71199→2000, 性能+召回双升 | 建库脚本 |
| **P2** | E. Hanawalt 分组预筛 | 中等 | 与 B 互补, 可叠加 | B |
| **P2** | F. 弱峰强度加权预筛门槛 | 小 | 减少杂相干扰 | 无 |

### 建议实施顺序

```
Step 1: 方案 A (1 行改动) → 跑 bench_cod_recall.py 验证
Step 2: 方案 D (2 行改动) → 跑 bench_cod_recall.py 验证
Step 3: 方案 C (两阶段搜索) → 跑 bench_cod_ranking.py 验证排序
Step 4: 方案 B (倒排索引) → 重建数据库 + 跑全量 342 测试回归
Step 5: 方案 E/F (可选, 叠加优化)
```

---

## 四、验证方法

### 4.1 召回率诊断

```bash
# 已有基准脚本 (tests/ 已 gitignore, 不进库)
python tests/bench_cod_recall.py
# 对比不同 tolerance/min_match/max_ref_peaks 配置的召回率

python tests/bench_cod_ranking.py
# 对比不同排序策略的 Top-1/5/10 命中率
```

### 4.2 全量回归

```bash
# 快速 (跳过长 wR 测试)
.\venv\Scripts\python.exe -m pytest tests\ --ignore=tests\test_rietveld_engine_opt.py -v -x
# 预期: 342 passed

# wR 验收 (长, 10-12 min)
.\venv\Scripts\python.exe -m pytest tests\test_rietveld_engine_opt.py -v -s
# 预期: 3 passed
```

### 4.3 13 试样 E2E

```bash
.\venv\Scripts\python.exe -m pytest tests\test_xrd_samples.py -v -s
# 对比 Top-1/5/10 命中率与基线 (14% / 25% / 27%)
```

---

## 五、风险评估

| 风险 | 概率 | 缓解 |
|---|---|---|
| `tolerance_rel` 放宽引入误配 | 低 | 下游 FOM 是强判别器, 误配候选会被过滤 |
| `min_match=2` 引入杂相 | 中 | 配合方案 F 强度加权门槛; FOM 精排可过滤 |
| 倒排索引建库耗时 | 中 | 一次性建库, 约 71K 物相 × 40 峰 ≈ 285 万行, 预计 1~2 min |
| 倒排索引体积增加 | 低 | 约 30~50 MB, 可接受 |
| 两阶段搜索阶段 1 漏真物相 | 低 | 阶段 1 用大池 (500), 阶段 2 才截断 |

---

## 六、长期方向

- **方案 B (倒排索引) 是结构性改造**, 一旦落地, 后续可在此基础设施上做更复杂的检索 (如考虑峰形匹配、强度一致性评分), 而不再受全量扫描的性能限制。
- **方案 E (Hanawalt 分组) 是经典方法**, 与 B 互补, 可叠加使用。
- 最终目标: Top-10 命中率 27% → 40%+ (接近商用软件水平), 主要受限于候选池质量而非排序。

---

> **附**: 基准脚本位于 `tests/` (该目录已 gitignore, 不随仓库提交):
> - `tests/bench_cod_recall.py` — 召回率诊断 (多配置扫描)
> - `tests/bench_match_factor.py` — 新旧 FoM 同候选集重排对比
> - `tests/bench_cod_ranking.py` — 多排序策略扫描
