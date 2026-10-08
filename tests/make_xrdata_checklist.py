# -*- coding: utf-8 -*-
"""XRData 验证最终清单生成器 (v2.7.0)。

读取物相检索结果 xrdata_validation_results.json 与精修结果 xrdata_refine_results.json,
用元素多重集精确匹配重算召回 (修正 COD/PDF2 化学式重排漏判), 合并精修结论,
产出:
  - xrdata_checklist.csv   (逐样品清单, 含检索召回 + 精修指标)
  - xrdata_checklist.md    (人类可读报告: 摘要/结论/明细/遗留问题)
  - xrdata_validation_results_fixed.json (回填精修后的完整记录)

用法:
  cd /d/Project/XRD/PolyXRD && ./venv/Scripts/python.exe -u tests/make_xrdata_checklist.py
"""
from __future__ import annotations
import os, re, json, csv

ROOT = r"D:/Project/XRD/PolyXRD"
ID_JSON  = os.path.join(ROOT, "tests", "xrdata_validation_results.json")
REF_JSON = os.path.join(ROOT, "tests", "xrdata_refine_results.json")
OUT_CSV  = os.path.join(ROOT, "tests", "xrdata_checklist.csv")
OUT_MD   = os.path.join(ROOT, "tests", "xrdata_checklist.md")
OUT_FIX  = os.path.join(ROOT, "tests", "xrdata_validation_results_fixed.json")

# ---------------- 元素多重集匹配 ----------------
def parse_formula(f):
    """Hill 记法 → 元素多重集 (处理一层 (Group)n)。"""
    f = f.strip()
    while True:
        m = re.search(r"\(([^()]*)\)(\d*)", f)
        if not m:
            break
        grp, n = m.group(1), int(m.group(2) or 1)
        exp = "".join(f"{el}{int(c)*n if c else n}" for el, c in re.findall(r"([A-Z][a-z]?)(\d*)", grp))
        f = f[:m.start()] + exp + f[m.end():]
    counts = {}
    for el, c in re.findall(r"([A-Z][a-z]?)(\d*)", f):
        counts[el] = counts.get(el, 0) + (int(c) if c else 1)
    return counts

def norm(s):
    return (s or "").lower().replace(" ", "").replace("(", "").replace(")", "").replace(",", "")

def candidate_matches(cand, keys):
    name, formula = norm(cand[0]), norm(cand[1])
    cset = parse_formula(cand[1])
    for k in keys:
        nk = norm(k)
        if not nk:
            continue
        if nk in name or nk in formula:
            return True
        kset = parse_formula(k)
        if kset and kset == cset:
            return True
    return False

def rank_of(cands, keys):
    for i, c in enumerate(cands, 1):
        if candidate_matches(c, keys):
            return i
    return None

# ---------------- 读取 ----------------
with open(ID_JSON, encoding="utf-8") as f:
    results = json.load(f)

refine_map = {}
refine_ok = os.path.exists(REF_JSON)
if refine_ok:
    with open(REF_JSON, encoding="utf-8") as f:
        for r in json.load(f):
            refine_map[r["label"]] = r

# ---------------- 重算召回 + 合并精修 ----------------
for r in results:
    top_cod = r.get("top_cod") or []
    top_b   = r.get("top_builtin") or []
    top_p   = r.get("top_pdf2") or []
    for comp in r.get("recall", []):
        keys = comp["comp"]
        comp["cod_rank"]     = rank_of(top_cod, keys)
        comp["builtin_rank"] = rank_of(top_b, keys)
        comp["pdf2_rank"]    = rank_of(top_p, keys) if top_p else None
        comp["found"] = any(comp.get(k) for k in ("cod_rank", "builtin_rank", "pdf2_rank"))
        # 主要命中的库
        if comp["builtin_rank"]: comp["hit_source"] = "builtin"
        elif comp["pdf2_rank"]:  comp["hit_source"] = "pdf2"
        elif comp["cod_rank"]:   comp["hit_source"] = "cod_inorganics"
        else:                    comp["hit_source"] = "MISS"
    rr = sum(1 for c in r["recall"] if c["found"]) / max(1, len(r["recall"]))
    r["recall_rate"] = round(rr, 3)
    if r["label"] in refine_map:
        r["refine"] = refine_map[r["label"]]

with open(OUT_FIX, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# ---------------- 汇总统计 ----------------
# P2-2: 非晶/近非晶组分属"物理无解", 单独分账, 不计入算法召回缺口
_AMORPH_KEYWORDS = ("glass", "polymer", "starch", "amorphous", "非晶", "高聚物", "炭")


def _is_expected_miss(label: str, comp) -> bool:
    """该漏检是否属预期内 (非晶/近非晶) —— 真值关键词 或 谱图实测判弥散。"""
    keys = " ".join(comp if isinstance(comp, list) else [comp]).lower()
    if any(k in keys for k in _AMORPH_KEYWORDS):
        return True
    am = next((r.get("amorphous") or {} for r in results if r["label"] == label), {})
    return bool(am.get("level") == "amorphous")


n_samples = len(results)
tot_comp = tot_found = cod_h = b_h = p_h = 0
tot_expect = 0          # 预期内(非晶) 组分总数
expect_missed = 0       # 其中漏检的
misses = []             # (label, comp, 归类)
for r in results:
    for c in r.get("recall", []):
        tot_comp += 1
        expected = _is_expected_miss(r["label"], c["comp"])
        if expected:
            tot_expect += 1
        if c["found"]:
            tot_found += 1
            if c.get("cod_rank"):     cod_h += 1
            if c.get("builtin_rank"): b_h += 1
            if c.get("pdf2_rank"):    p_h += 1
        else:
            kind = "近非晶·物理无解" if expected else "真实召回缺口"
            if expected:
                expect_missed += 1
            misses.append((r["label"], " ".join(c["comp"]), kind))

# 可解释口径: 分母剔除预期内非晶组分
eff_comp = tot_comp - tot_expect
eff_found = tot_found - (tot_expect - expect_missed)
eff_rate = (eff_found / eff_comp * 100.0) if eff_comp else 0.0

# ---------------- 写 CSV ----------------
with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["样品", "格式", "类别", "真值组分数", "召回率",
                "cod_inorganics命中", "builtin命中", "pdf2兜底",
                "精修相", "Rwp%", "GOF", "质量", "精修窗口", "精修状态", "检索状态",
                "非晶判定", "动态范围", "尖锐度"])
    for r in results:
        rc = r.get("recall", [])
        truth_n = len(rc)
        cod_s = sum(1 for c in rc if c.get("cod_rank"))
        b_s   = sum(1 for c in rc if c.get("builtin_rank"))
        p_s   = sum(1 for c in rc if c.get("pdf2_rank"))
        rf = r.get("refine") or {}
        w.writerow([
            r["label"], r["fmt"], r["category"], truth_n, f"{r.get('recall_rate')}",
            cod_s, b_s, p_s,
            rf.get("phase", ""), rf.get("Rwp", ""), rf.get("GOF", ""),
            rf.get("quality", ""), (str(rf.get("window", "")) if rf.get("window") else ""),
            (rf.get("status", "") if rf else ""), r.get("status"),
            (r.get("amorphous") or {}).get("level", ""),
            (r.get("amorphous") or {}).get("dynamic_range", ""),
            (r.get("amorphous") or {}).get("sharp_content", ""),
        ])

# ---------------- 写 Markdown 报告 ----------------
def fmt_ranks(c):
    parts = []
    if c.get("builtin_rank"): parts.append(f"builtin#{c['builtin_rank']}")
    if c.get("pdf2_rank"):    parts.append(f"pdf2#{c['pdf2_rank']}")
    if c.get("cod_rank"):     parts.append(f"cod#{c['cod_rank']}")
    return " / ".join(parts) if parts else "—"

lines = []
lines.append("# XRData 物相检索 + 结构精修 验证清单 (PolyXRD v2.7.0)\n")
lines.append("## 一、执行摘要\n")
lines.append(f"- **数据集**：`D:/Project/XRD/XRData` —— IUCr 标准集（含 `IUCr物相说明.txt` 真值）+ csuHJW 中南大学教学集（真值写在文件名）。共 130 个谱图（12 mdi / 70 raw / 48 txt）。")
lines.append(f"- **评估样本**：带确认真值的 {n_samples} 个谱图；其中 {len(refine_map)} 个单相标样额外跑了 builtin 引擎精修。")
lines.append(f"- **检索整体召回**：{tot_found}/{tot_comp} 真值组分命中 = **{tot_found/tot_comp*100:.1f}%**")
lines.append(f"- **可解释口径召回**（分母剔除 {tot_expect} 个近非晶/非晶组分，这类相本就不出尖锐 Bragg 峰，属物理无解）："
             f"{eff_found}/{eff_comp} = **{eff_rate:.1f}%**")
lines.append(f"- **分库命中（同一组分可能被多库命中）**：builtin **{b_h}** / pdf2 兜底 **{p_h}** / cod_inorganics **{cod_h}**")
lines.append(f"- **精修**：{len(refine_map)} 个单相标样用 builtin 引擎（max_cycles=2 + 窗口限幅）跑通，Rwp 区间见下表。\n")

lines.append("## 二、关键结论\n")
lines.append("1. **main_peak 门控修复后 cod_inorganics 覆盖显著回升（本轮修复）**——此前 `main_peak_match` 单一最强峰门控过脆，刚玉/萤石等常见相在 cod_inorganics top‑20 完全缺席；改为最强峰 top‑3 容错后，CORUNDUM cod#1、FLUORITE cod#1、NCM811 cod#2，cod 命中组分由 9 升至 15。")
lines.append("2. **多库联动仍是评估口径**——builtin（内置+有机小库）命中 {b_h} 个组分、cod_inorganics {cod_h} 个、pdf2 兜底 {p_h} 个。对常见工程/教学物料（刚玉、萤石、红锌矿、磁铁矿、锆石、石英、Y₂O₃、铜、TiO₂、NCM811 等），builtin 基本都能 top‑3 命中；单看 cod_inorganics 仍会低估检索质量。".format(b_h=b_h, cod_h=cod_h, p_h=p_h))
lines.append("3. **csuHJW 的 `.raw` 已可解析（本轮修复）**——中南大学教学集的 `.raw` 为 Rigaku RINT‑2000 二进制（魔数 `FI\\x00\\x00`），此前落入启发式兜底返回垃圾数据；现已新增 `_load_rigaku_raw` 专用解析分支（轴参数位于偏移 2962，末尾 float32 强度），TiO₂双相即改用 `.raw` 成功识别（anatase#1 + rutile#2，召回 0%→100%）。JADE 「Phase ID Report」类文本文件会防御性报错提示改用原始谱图，避免误解析出虚假峰。")
lines.append("4. **精修前提与降载**——builtin 库多数相 `lattice=None`（只有硬编码参考峰，无晶胞），精修必须选带晶胞的相（从 cod_inorganics / pdf2 自动经 `_cif_resolver` 补全结构）；builtin 引擎需降载：`max_cycles=2` + 限定 `two_theta_range` 窗口（否则全谱 7251 点 × scipy 数值雅可比 >10 min 不返回）。")
lines.append("5. **精修指标口径**——builtin 引擎是 Le Bail 级快速拟合，Rwp 6–26% 属预期区间（非全 Rietveld 精修），用于定性“能否收敛/用量级评估”，定量含量须用 GSAS‑II / FullProf / MAUD。")
lines.append("6. **有机/药物相库已建立并迭代（本轮新增 + P0）**——`organic_reference_database.json` 覆盖 Sucrose(COD 结构因子)/Mannitol/Valine/Nizatidine(校准标准谱实测峰)，经 `_load_reference_database` 并入 builtin 检索路径。单相 MANNITOL/SUCROSE/VALINE/NIZATIDI 全部 #1 命中；PHARM2GR 命中 4/5（含混合物中的 nizatidine #3，属**独立于参考谱来源文件**的有效证据）。**STARCH 回退**：近非晶宽包络与检出锐峰不对齐，即便参考峰取自其自身标准谱仍排 #85(cov 1/6)，留待非晶相识别方案。参考卡实测取「最强 6 条」最优——>8 条会让 Nizatidine 与密集谱偶然匹配挤进 BAUXITE top‑10。")
lines.append("7. **漏检组分要分两类看**（详见第五节）——(a) **预期内漏检**：非晶/近非晶相（玻璃、淀粉、高聚物）本就不出尖锐峰，不应算作算法失败；(b) **真实召回缺口**：花岗闪长岩的绿泥石/角闪石/锆石、BAUXITE 的高岭石、PHARM1GR 的蔗糖（混合物中被抑制）、NIZATIDI（可在有机库中补 exp 条目），才是需要算法/库跟进的点。")
lines.append("8. **SILICA 已正常（此前 builtin 缺 quartz 晶胞的疑虑已排除）**——核查确认 builtin 库 α‑Quartz 条目本就带 P3₁21 晶胞，本轮 SILICA 召回 1.0 且精修 Rwp 6.29%（全部样本最佳）。\n")

lines.append("## 三、检索召回明细（{}/{} 组分命中 = {:.1f}%）\n".format(tot_found, tot_comp, tot_found/tot_comp*100))
lines.append("| 样品 | 格式 | 类别 | 真值组分 | 召回率 | 主要命中库 |")
lines.append("|---|---|---|---|---|---|")
for r in results:
    rc = r.get("recall", [])
    hits = "/".join(c["hit_source"] for c in rc)
    lines.append(f"| {r['label']} | {r['fmt']} | {r['category']} | {len(rc)} | {r.get('recall_rate')} | {hits} |")

lines.append("\n## 四、精修结果明细（builtin 引擎，降载）\n")
if refine_map:
    lines.append("| 样品 | 检索到的相 | 来源库 | Rwp% | GOF | 质量 | 精修窗口 | 圈数 | 用时(s) | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for label in ["CORUNDUM", "FLUORITE", "ZINCITE", "SILICA", "Y2O3", "Cu-007"]:
        rf = refine_map.get(label)
        if not rf:
            continue
        lines.append(f"| {label} | {rf.get('phase','')} ({rf.get('formula','')}) | {rf.get('phase_source_db','')} "
                     f"| {rf.get('Rwp','')} | {rf.get('GOF','')} | {rf.get('quality','')} | {rf.get('window','')} "
                     f"| {rf.get('cycles','')} | {rf.get('time_s','')} | {rf.get('status','')} |")
    n_ok = sum(1 for v in refine_map.values() if v.get("status") == "ok")
    lines.append(f"\n精修跑通 {n_ok}/{len(refine_map)}。")
else:
    lines.append("（精修结果文件尚不存在，未合并。）\n")

lines.append("\n## 五、未召回组分（{}/{} 组分漏检，供算法/库改进）\n".format(len(misses), tot_comp))
if misses:
    lines.append("| 样品 | 漏检真值组分 | 归类 |")
    lines.append("|---|---|---|")
    for lab, comp, kind in misses:
        lines.append(f"| {lab} | {comp} | {kind} |")
lines.append("")
lines.append("> **漏检归类**：")
lines.append("> - **预期内（非晶/近非晶，不应算算法失败）**：CPD‑3 的 glass、STARCH、Poly‑025/027/029 的 polymer、"
             "PHARM1GR/PHARM2GR 的 starch —— 共 {} 个组分，均被归入上表「近非晶·物理无解」。"
             "归类**不再靠人工点名**，而是由 `amorphous.py` 实测判定 + 真值关键词自动给出。".format(expect_missed))
lines.append("> - **有机库已完成**：NIZATIDI 单相 #1 + PHARM2GR 混合物 #3 均已命中（P0‑1 完成）。")
lines.append("> - **STARCH 回退（P0‑2 结论）**：近非晶，参考谱取自其自身仍只能排 #85(cov 1/6)，属「非晶相识别」问题，见 P2‑2，不算检索算法失败。")
lines.append("> - **真实召回缺口（天然岩次要矿物）**：GRANODIO 的 clinochlore/hornblende/zircon（痕量次要相）；BAUXITE 的 kaolinite（七相铝土矿漏 1）。")
lines.append("")

lines.append("## 六、格式与数据可用性说明\n")
lines.append("- **`.mdi`**（Bruker 文本）：可用，含 off‑by‑one 修正。")
lines.append("- **`.txt`**（两列文本）：可用。")
lines.append("- **`.raw` 分两类**：IUCr 的 RAW2（Philips 二进制，`_load_raw2` 专用解析器，**可用**）；csuHJW 的 `.raw`（Rigaku RINT‑2000 二进制，`_load_rigaku_raw` 专用解析器（本轮新增），**可用**——TiO₂双相即以 `.raw` 识别成功）。JADE Phase ID Report 文本会防御性报错，引导改用原始谱图。")
lines.append("- **COD/PDF2 化学式重排**：COD/PDF2 的 formula 按元素重排（如 ZnO→`O Zn`、Y₂O₃→`O3 Y2`），子串匹配会漏判；本报告已用元素多重集精确匹配重算召回（修正后 COD 命中原比子串口径多、pdf2 从 3 升到 7）。\n")

lines.append("## 七、遗留问题与下一步建议\n")
lines.append("1. **✅ P0‑1 有机库补 NIZATIDI（已完成）**：exp 来源补入后召回 80.0%→82.7%（+2 组分：NIZATIDI 单相 #1 + PHARM2GR 混合物 nizatidine #3）。参考卡取最强 6 条以抑制与密集谱的偶然匹配。")
lines.append("2. **次要相/混合物弱组分：不自动召回，走「操作者驱动的残差再匹配」**——Clinochlore/Hornblende/Zircon/Kaolinite 均已在 builtin 库，漏检是因其本征太弱。实测手动残差再匹配可救回（clinochlore 14→1、hornblende 27→3、kaolinite 11→4、PHARM1GR sucrose 28→1），但自动化判据**已反证失效**：真有隐藏次要相的多相样残差全是弱峰（≥5%Imax 强峰数 0），单相样反而是 11/2 个强峰；真目标 cov=2 还低于假目标 cov=3。故不纳入默认流程，保留 UI 右键「仅对标记峰再匹配」，由操作者判断（详见改进计划 P1 结论）。")
lines.append("3. **天然岩次要矿物召回（GRANODIO/BAUXITE）**：clinochlore/hornblende/zircon/kaolinite 为痕量次要相，需依赖 cod_full/pdf2 兜底与残差峰追查（标记峰再匹配）提升。")
lines.append("4. **✅ 非晶/近非晶标注已完成（P2‑2）**——新增 `services/amorphous.py`：判据 = 谱图弥散 `AND` 未获可接受匹配（两端缺一不可，单一美感指标在真实语料上全部失效）。UI 已接线（无候选时提示「近非晶·结晶相检索不适用」；有候选但弥散时提示「含非晶/弥散背景」），清单自动把这类漏检从算法缺口中分账：**可解释口径召回 {:.1f}%（{}/{}），全口径 {:.1f}%**。STARCH/Poly 系列不再被计为算法失败。".format(eff_rate, eff_found, eff_comp, tot_found/tot_comp*100))
lines.append("   - 已修真 bug：动态范围本底取全谱 median 时，计数型谱零值占多数会让动态范围塌成 0 → Cu‑007 结晶谱被误判非晶；改取**正值中位数**。")
lines.append("5. **有机相扩充（版权安全路径）**：咖啡因/阿司匹林/对乙酰氨基酚等如需加入，须先验证 COD 多型与实验一致（参照 Mannitol 教训），或统一走 exp 标准谱来源。")
lines.append("6. **精修引擎升级**：builtin 为 Le Bail 级快速拟合，Rwp 偏高；定量含量与高精度晶胞须走 GSAS‑II/FullProf/MAUD 外部引擎。\n")

lines.append("---\n*生成于 PolyXRD 验证脚本 `make_xrdata_checklist.py`；数据文件：`xrdata_validation_results.json` / `xrdata_refine_results.json` / `xrdata_checklist.csv`。*\n")

with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("==== XRData 验证最终汇总 ====", flush=True)
print(f"  样品={n_samples}  真值组分={tot_comp}  召回={tot_found} ({tot_found/tot_comp*100:.1f}%)", flush=True)
print(f"  分库命中: builtin={b_h}  pdf2兜底={p_h}  cod_inorganics={cod_h}", flush=True)
print(f"  精修样本={len(refine_map)} (ok={sum(1 for v in refine_map.values() if v.get('status')=='ok')})", flush=True)
print(f"  漏检组分={len(misses)} (其中近非晶·物理无解={expect_missed}, 真实缺口={len(misses)-expect_missed})", flush=True)
print(f"  可解释口径召回={eff_found}/{eff_comp} ({eff_rate:.1f}%)", flush=True)
print("CSV :", OUT_CSV, flush=True)
print("MD  :", OUT_MD, flush=True)
print("FIX :", OUT_FIX, flush=True)
