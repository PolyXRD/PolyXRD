# -*- coding: utf-8 -*-
"""修正 XRData 验证结果: 用元素多重集精确匹配重算召回 (修正 COD/PDF2 化学式重排导致的漏判)。

读取 tests/xrdata_validation_results.json, 对每个真值组分重新判定 cod/builtin/pdf2 命中,
生成修正后的 xrdata_checklist.csv 与 xrdata_validation_results_fixed.json。
若 tests/xrdata_refine_results.json 存在, 一并合并精修结果。
"""
import os, re, json, csv

ROOT = r"D:/Project/XRD/PolyXRD"
ID_JSON = os.path.join(ROOT, "tests", "xrdata_validation_results.json")
REF_JSON = os.path.join(ROOT, "tests", "xrdata_refine_results.json")
OUT_JSON = os.path.join(ROOT, "tests", "xrdata_validation_results_fixed.json")
OUT_CSV = os.path.join(ROOT, "tests", "xrdata_checklist.csv")

def parse_formula(f):
    """简单 Hill 记法 → 元素多重集 (处理一层 (Group)n)。"""
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
    """cand=(name,formula,...); 命中条件: 任一 key 为 name/formula 子串, 或 key 解析的元素多重集 == cand 元素多重集。"""
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

with open(ID_JSON, encoding="utf-8") as f:
    results = json.load(f)

refine_map = {}
if os.path.exists(REF_JSON):
    with open(REF_JSON, encoding="utf-8") as f:
        for r in json.load(f):
            refine_map[r["label"]] = r

for r in results:
    top_cod = r.get("top_cod") or []
    top_b = r.get("top_builtin") or []
    top_p = r.get("top_pdf2") or []
    for comp in r.get("recall", []):
        keys = comp["comp"]
        comp["cod_rank"] = rank_of(top_cod, keys)
        comp["builtin_rank"] = rank_of(top_b, keys)
        comp["pdf2_rank"] = rank_of(top_p, keys) if top_p else None
        comp["found"] = any(comp.get(k) for k in ("cod_rank","builtin_rank","pdf2_rank"))
    rr = sum(1 for c in r["recall"] if c["found"]) / max(1, len(r["recall"]))
    r["recall_rate"] = round(rr, 3)
    # 合并精修
    if r["label"] in refine_map:
        r["refine"] = refine_map[r["label"]]

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# 汇总
n = len(results); ok = [r for r in results if r.get("status") == "ok" or r.get("status") == "ERROR"]
tot = totf = cod_h = b_h = p_h = 0
for r in results:
    for c in r.get("recall", []):
        tot += 1
        if c["found"]: totf += 1
        if c.get("cod_rank"): cod_h += 1
        if c.get("builtin_rank"): b_h += 1
        if c.get("pdf2_rank"): p_h += 1

# 写 CSV 清单
with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["样品","格式","类别","真值组分数","召回率","cod_inorganics命中组分","builtin命中","pdf2兜底",
                "精修相","Rwp%","GOF","质量","精修窗口","状态"])
    for r in results:
        rc = r.get("recall", [])
        truth_n = len(rc)
        found = sum(1 for c in rc if c["found"])
        cod_s = sum(1 for c in rc if c.get("cod_rank"))
        b_s = sum(1 for c in rc if c.get("builtin_rank"))
        p_s = sum(1 for c in rc if c.get("pdf2_rank"))
        rf = r.get("refine") or {}
        w.writerow([r["label"], r["fmt"], r["category"], truth_n, f"{r.get('recall_rate')}",
                    cod_s, b_s, p_s, rf.get("phase",""), rf.get("Rwp",""),
                    rf.get("GOF",""), rf.get("quality",""), rf.get("window",""), r.get("status")])

print("修正后汇总:", flush=True)
print(f"  样品={n}  真值组分={tot}  召回={totf} ({totf/tot*100:.1f}%)", flush=True)
print(f"  cod_inorganics 命中={cod_h}  builtin 命中={b_h}  pdf2兜底命中={p_h}", flush=True)
print("CSV:", OUT_CSV, flush=True)
print("FIXED JSON:", OUT_JSON, flush=True)
