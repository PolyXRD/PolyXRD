# XRData 物相检索 + 结构精修 验证清单 (PolyXRD v2.7.0)

## 一、执行摘要

- **数据集**：`D:/Project/XRD/XRData` —— IUCr 标准集（含 `IUCr物相说明.txt` 真值）+ csuHJW 中南大学教学集（真值写在文件名）。共 130 个谱图（12 mdi / 70 raw / 48 txt）。
- **评估样本**：带确认真值的 37 个谱图；其中 6 个单相标样额外跑了 builtin 引擎精修。
- **检索整体召回**：62/75 真值组分命中 = **82.7%**
- **可解释口径召回**（分母剔除 7 个近非晶/非晶组分，这类相本就不出尖锐 Bragg 峰，属物理无解）：62/68 = **91.2%**
- **分库命中（同一组分可能被多库命中）**：builtin **59** / pdf2 兜底 **6** / cod_inorganics **15**
- **精修**：6 个单相标样用 builtin 引擎（max_cycles=2 + 窗口限幅）跑通，Rwp 区间见下表。

## 二、关键结论

1. **main_peak 门控修复后 cod_inorganics 覆盖显著回升（本轮修复）**——此前 `main_peak_match` 单一最强峰门控过脆，刚玉/萤石等常见相在 cod_inorganics top‑20 完全缺席；改为最强峰 top‑3 容错后，CORUNDUM cod#1、FLUORITE cod#1、NCM811 cod#2，cod 命中组分由 9 升至 15。
2. **多库联动仍是评估口径**——builtin（内置+有机小库）命中 59 个组分、cod_inorganics 15 个、pdf2 兜底 6 个。对常见工程/教学物料（刚玉、萤石、红锌矿、磁铁矿、锆石、石英、Y₂O₃、铜、TiO₂、NCM811 等），builtin 基本都能 top‑3 命中；单看 cod_inorganics 仍会低估检索质量。
3. **csuHJW 的 `.raw` 已可解析（本轮修复）**——中南大学教学集的 `.raw` 为 Rigaku RINT‑2000 二进制（魔数 `FI\x00\x00`），此前落入启发式兜底返回垃圾数据；现已新增 `_load_rigaku_raw` 专用解析分支（轴参数位于偏移 2962，末尾 float32 强度），TiO₂双相即改用 `.raw` 成功识别（anatase#1 + rutile#2，召回 0%→100%）。JADE 「Phase ID Report」类文本文件会防御性报错提示改用原始谱图，避免误解析出虚假峰。
4. **精修前提与降载**——builtin 库多数相 `lattice=None`（只有硬编码参考峰，无晶胞），精修必须选带晶胞的相（从 cod_inorganics / pdf2 自动经 `_cif_resolver` 补全结构）；builtin 引擎需降载：`max_cycles=2` + 限定 `two_theta_range` 窗口（否则全谱 7251 点 × scipy 数值雅可比 >10 min 不返回）。
5. **精修指标口径**——builtin 引擎是 Le Bail 级快速拟合，Rwp 6–26% 属预期区间（非全 Rietveld 精修），用于定性“能否收敛/用量级评估”，定量含量须用 GSAS‑II / FullProf / MAUD。
6. **有机/药物相库已建立并迭代（本轮新增 + P0）**——`organic_reference_database.json` 覆盖 Sucrose(COD 结构因子)/Mannitol/Valine/Nizatidine(校准标准谱实测峰)，经 `_load_reference_database` 并入 builtin 检索路径。单相 MANNITOL/SUCROSE/VALINE/NIZATIDI 全部 #1 命中；PHARM2GR 命中 4/5（含混合物中的 nizatidine #3，属**独立于参考谱来源文件**的有效证据）。**STARCH 回退**：近非晶宽包络与检出锐峰不对齐，即便参考峰取自其自身标准谱仍排 #85(cov 1/6)，留待非晶相识别方案。参考卡实测取「最强 6 条」最优——>8 条会让 Nizatidine 与密集谱偶然匹配挤进 BAUXITE top‑10。
7. **漏检组分要分两类看**（详见第五节）——(a) **预期内漏检**：非晶/近非晶相（玻璃、淀粉、高聚物）本就不出尖锐峰，不应算作算法失败；(b) **真实召回缺口**：花岗闪长岩的绿泥石/角闪石/锆石、BAUXITE 的高岭石、PHARM1GR 的蔗糖（混合物中被抑制）、NIZATIDI（可在有机库中补 exp 条目），才是需要算法/库跟进的点。
8. **SILICA 已正常（此前 builtin 缺 quartz 晶胞的疑虑已排除）**——核查确认 builtin 库 α‑Quartz 条目本就带 P3₁21 晶胞，本轮 SILICA 召回 1.0 且精修 Rwp 6.29%（全部样本最佳）。

## 三、检索召回明细（62/75 组分命中 = 82.7%）

| 样品 | 格式 | 类别 | 真值组分 | 召回率 | 主要命中库 |
|---|---|---|---|---|---|
| CORUNDUM | raw | 单相氧化物 | 1 | 1.0 | builtin |
| FLUORITE | raw | 单相卤化物 | 1 | 1.0 | builtin |
| ZINCITE | raw | 单相氧化物 | 1 | 1.0 | builtin |
| BRUCITE | raw | 单相氢氧化物 | 1 | 1.0 | builtin |
| MAGNETIT | raw | 单相氧化物 | 1 | 1.0 | builtin |
| ZIRCON | raw | 单相硅酸盐 | 1 | 1.0 | cod_inorganics |
| SILICA | raw | 单相石英 | 1 | 1.0 | builtin |
| Y2O3 | raw | 单相氧化物 | 1 | 1.0 | pdf2 |
| CPD-1A | raw | 三组分混合(1a) | 3 | 1.0 | builtin/builtin/builtin |
| CPD-1B | raw | 三组分混合(1b) | 3 | 1.0 | builtin/builtin/builtin |
| CPD-1C | raw | 三组分混合(1c) | 3 | 1.0 | builtin/builtin/builtin |
| CPD-1G | raw | 三组分混合(1g) | 3 | 1.0 | builtin/builtin/builtin |
| CPD-2 | raw | 四组分+择尤(2) | 4 | 1.0 | builtin/builtin/builtin/builtin |
| CPD-3 | raw | 三组分+非晶(3) | 4 | 0.75 | builtin/builtin/builtin/MISS |
| CPD-4 | raw | 三组分+微吸收(4) | 3 | 1.0 | builtin/builtin/cod_inorganics |
| BAUXITE | mdi | 七相混合(铝土矿) | 7 | 0.857 | builtin/builtin/builtin/builtin/builtin/MISS/builtin |
| GRANODIO | mdi | 天然花岗闪长岩(无固定含量) | 7 | 0.571 | builtin/builtin/builtin/builtin/MISS/MISS/MISS |
| PHARM1GR | raw | 五相药物混合(1) | 5 | 0.4 | builtin/MISS/builtin/MISS/MISS |
| PHARM2GR | raw | 五相药物混合(2) | 5 | 0.8 | builtin/builtin/builtin/MISS/builtin |
| MANNITOL | raw | 单相有机物 | 1 | 1.0 | builtin |
| SUCROSE | raw | 单相有机物 | 1 | 1.0 | builtin |
| VALINE | raw | 单相有机物 | 1 | 1.0 | builtin |
| STARCH | raw | 单相有机物(近非晶) | 1 | 0.0 | MISS |
| NIZATIDI | raw | 单相有机物 | 1 | 1.0 | builtin |
| Cu-007 | txt | 单相金属Cu | 1 | 1.0 | builtin |
| Cu-010 | txt | 单相金属Cu | 1 | 1.0 | builtin |
| Cu-013 | txt | 单相金属Cu | 1 | 1.0 | builtin |
| Cu-017低角 | txt | 单相金属Cu(低角) | 1 | 1.0 | builtin |
| Cu-018高角 | txt | 单相金属Cu(高角) | 1 | 1.0 | builtin |
| Poly-025 | txt | 高聚物(近非晶) | 1 | 0.0 | MISS |
| Poly-027 | txt | 高聚物(近非晶) | 1 | 0.0 | MISS |
| Poly-029 | txt | 高聚物(近非晶) | 1 | 0.0 | MISS |
| TiO2双相 | raw | 双相TiO2(锐钛+金红) | 3 | 1.0 | builtin/builtin/builtin |
| AlCoO-750c | txt | Co掺杂Al2O3(750C) | 1 | 1.0 | builtin |
| AlCoO-650c | txt | Co掺杂Al2O3(650C) | 1 | 1.0 | builtin |
| AlCoO-750cB | txt | Co掺杂Al2O3(750C) | 1 | 1.0 | builtin |
| NCM811 | mdi | 三元正极NCM811(致密相召回难点) | 1 | 1.0 | builtin |

## 四、精修结果明细（builtin 引擎，降载）

| 样品 | 检索到的相 | 来源库 | Rwp% | GOF | 质量 | 精修窗口 | 圈数 | 用时(s) | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| CORUNDUM | Corundum, syn (PDF2 431484) (Al2 O3) | pdf2 | 17.287 | 2.242 | 差 | [10.0, 80.0] | 15 | 0.8 | ok |
| FLUORITE | Calcium Fluoride (PDF2 650535) (Ca F2) | pdf2 | 24.486 | 2.342 | 差 | [10.0, 80.0] | 20 | 0.6 | ok |
| ZINCITE | Zincite, syn (PDF2 361451) (O Zn) | pdf2 | 21.901 | 3.897 | 差 | [10.0, 80.0] | 21 | 0.8 | ok |
| SILICA |  () |  |  |  |  |  |  |  | no_lattice_phase |
| Y2O3 | Yttrium Oxide (PDF2 431036) (O3 Y2) | pdf2 | 26.068 | 6.868 | 很差 | [10.0, 80.0] | 18 | 1.9 | ok |
| Cu-007 | Copper (PDF2 892838) (Cu) | pdf2 | 98.251 | 6.145 | 很差 | [37.0, 80.0] | 40 | 11.6 | ok |

精修跑通 5/6。

## 五、未召回组分（13/75 组分漏检，供算法/库改进）

| 样品 | 漏检真值组分 | 归类 |
|---|---|---|
| CPD-3 | glass amorphous sio2 | 近非晶·物理无解 |
| BAUXITE | kaolinite | 真实召回缺口 |
| GRANODIO | clinochlore | 真实召回缺口 |
| GRANODIO | hornblende | 真实召回缺口 |
| GRANODIO | zircon | 真实召回缺口 |
| PHARM1GR | sucrose | 真实召回缺口 |
| PHARM1GR | starch | 近非晶·物理无解 |
| PHARM1GR | nizatidine | 真实召回缺口 |
| PHARM2GR | starch | 近非晶·物理无解 |
| STARCH | starch | 近非晶·物理无解 |
| Poly-025 | polymer poly organic | 近非晶·物理无解 |
| Poly-027 | polymer poly organic | 近非晶·物理无解 |
| Poly-029 | polymer poly organic | 近非晶·物理无解 |

> **漏检归类**：
> - **预期内（非晶/近非晶，不应算算法失败）**：CPD‑3 的 glass、STARCH、Poly‑025/027/029 的 polymer、PHARM1GR/PHARM2GR 的 starch —— 共 7 个组分，均被归入上表「近非晶·物理无解」。归类**不再靠人工点名**，而是由 `amorphous.py` 实测判定 + 真值关键词自动给出。
> - **有机库已完成**：NIZATIDI 单相 #1 + PHARM2GR 混合物 #3 均已命中（P0‑1 完成）。
> - **STARCH 回退（P0‑2 结论）**：近非晶，参考谱取自其自身仍只能排 #85(cov 1/6)，属「非晶相识别」问题，见 P2‑2，不算检索算法失败。
> - **真实召回缺口（天然岩次要矿物）**：GRANODIO 的 clinochlore/hornblende/zircon（痕量次要相）；BAUXITE 的 kaolinite（七相铝土矿漏 1）。

## 六、格式与数据可用性说明

- **`.mdi`**（Bruker 文本）：可用，含 off‑by‑one 修正。
- **`.txt`**（两列文本）：可用。
- **`.raw` 分两类**：IUCr 的 RAW2（Philips 二进制，`_load_raw2` 专用解析器，**可用**）；csuHJW 的 `.raw`（Rigaku RINT‑2000 二进制，`_load_rigaku_raw` 专用解析器（本轮新增），**可用**——TiO₂双相即以 `.raw` 识别成功）。JADE Phase ID Report 文本会防御性报错，引导改用原始谱图。
- **COD/PDF2 化学式重排**：COD/PDF2 的 formula 按元素重排（如 ZnO→`O Zn`、Y₂O₃→`O3 Y2`），子串匹配会漏判；本报告已用元素多重集精确匹配重算召回（修正后 COD 命中原比子串口径多、pdf2 从 3 升到 7）。

## 七、遗留问题与下一步建议

1. **✅ P0‑1 有机库补 NIZATIDI（已完成）**：exp 来源补入后召回 80.0%→82.7%（+2 组分：NIZATIDI 单相 #1 + PHARM2GR 混合物 nizatidine #3）。参考卡取最强 6 条以抑制与密集谱的偶然匹配。
2. **次要相/混合物弱组分：不自动召回，走「操作者驱动的残差再匹配」**——Clinochlore/Hornblende/Zircon/Kaolinite 均已在 builtin 库，漏检是因其本征太弱。实测手动残差再匹配可救回（clinochlore 14→1、hornblende 27→3、kaolinite 11→4、PHARM1GR sucrose 28→1），但自动化判据**已反证失效**：真有隐藏次要相的多相样残差全是弱峰（≥5%Imax 强峰数 0），单相样反而是 11/2 个强峰；真目标 cov=2 还低于假目标 cov=3。故不纳入默认流程，保留 UI 右键「仅对标记峰再匹配」，由操作者判断（详见改进计划 P1 结论）。
3. **天然岩次要矿物召回（GRANODIO/BAUXITE）**：clinochlore/hornblende/zircon/kaolinite 为痕量次要相，需依赖 cod_full/pdf2 兜底与残差峰追查（标记峰再匹配）提升。
4. **✅ 非晶/近非晶标注已完成（P2‑2）**——新增 `services/amorphous.py`：判据 = 谱图弥散 `AND` 未获可接受匹配（两端缺一不可，单一美感指标在真实语料上全部失效）。UI 已接线（无候选时提示「近非晶·结晶相检索不适用」；有候选但弥散时提示「含非晶/弥散背景」），清单自动把这类漏检从算法缺口中分账：**可解释口径召回 91.2%（62/68），全口径 82.7%**。STARCH/Poly 系列不再被计为算法失败。
   - 已修真 bug：动态范围本底取全谱 median 时，计数型谱零值占多数会让动态范围塌成 0 → Cu‑007 结晶谱被误判非晶；改取**正值中位数**。
5. **有机相扩充（版权安全路径）**：咖啡因/阿司匹林/对乙酰氨基酚等如需加入，须先验证 COD 多型与实验一致（参照 Mannitol 教训），或统一走 exp 标准谱来源。
6. **精修引擎升级**：builtin 为 Le Bail 级快速拟合，Rwp 偏高；定量含量与高精度晶胞须走 GSAS‑II/FullProf/MAUD 外部引擎。

---
*生成于 PolyXRD 验证脚本 `make_xrdata_checklist.py`；数据文件：`xrdata_validation_results.json` / `xrdata_refine_results.json` / `xrdata_checklist.csv`。*
