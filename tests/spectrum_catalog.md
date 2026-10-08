# 谱图数据集目录 (XRData + test_xrd)

> 生成于 2026-10-08 16:09 ｜ 重跑: `./venv/Scripts/python.exe scripts/build_spectrum_catalog.py`
> 机器可读版: `tests/spectrum_catalog.json` ｜ 本清单供后续 agent 直接取用与验收

## 一、总览

- **XRData/IUCr**: 28 个标准样本 (单相 8 + CPD 混合 12 + 铝土矿/花岗闪长岩 + 药物 7), RAW2 二进制 `.RAW` + 部分 `.mdi` 双格式
- **XRData/csuHJW**: 44 个教学样本 (真值写在文件名), `.raw`=Rigaku RINT-2000 / `.TXT` 文本 / `.mdi`
- **test_xrd**: 13 试样基准 (含 wt% 真值+元素限定) + geshi 五格式转换集 + 5/ 原始导出目录
- 验收入口见文末「验收入口映射」; 已知坑点见「坑点速查」

## 二、XRData/IUCr 标准集

| 样品 | 类别 | 真值 (wt% 为称重值) | 格式 | 备注 |
|---|---|---|---|---|
| CORUNDUM | 单相氧化物 | Corundum Al2O3 100.0% | raw |  |
| FLUORITE | 单相卤化物 | Fluorite CaF2 100.0% | raw |  |
| ZINCITE | 单相氧化物 | Zincite ZnO 100.0% | raw |  |
| BRUCITE | 单相氢氧化物 | Brucite Mg(OH)2 100.0% | raw |  |
| MAGNETIT | 单相氧化物 | Magnetite Fe3O4 100.0% | raw |  |
| ZIRCON | 单相硅酸盐 | Zircon ZrSiO4 100.0% | raw |  |
| SILICA | 单相石英 | alpha-Quartz SiO2 100.0% | raw |  |
| CPD-Y2O3 | 单相氧化物 | Y2O3 100.0% | raw |  |
| CPD-1A | 三组分混合(1a) | Al2O3 1.15%; ZnO 4.04%; CaF2 94.81% | mdi + raw |  |
| CPD-1B | 三组分混合(1b) | Al2O3 94.31%; ZnO 1.36%; CaF2 4.33% | mdi + raw |  |
| CPD-1C | 三组分混合(1c) | Al2O3 5.04%; ZnO 93.59%; CaF2 1.36% | mdi + raw |  |
| CPD-1D | 三组分混合(1d) | Al2O3 13.53%; ZnO 32.89%; CaF2 53.58% | mdi + raw | 当前 validate_xrdata.py 未覆盖 (可作扩展验收样本) |
| CPD-1E | 三组分混合(1e) | Al2O3 55.12%; ZnO 15.25%; CaF2 29.62% | mdi + raw | 当前 validate_xrdata.py 未覆盖 (可作扩展验收样本) |
| CPD-1F | 三组分混合(1f) | Al2O3 27.06%; ZnO 55.22%; CaF2 17.72% | raw | 当前 validate_xrdata.py 未覆盖 (可作扩展验收样本) |
| CPD-1G | 三组分混合(1g,可单测) | Al2O3 31.37%; ZnO 34.21%; CaF2 34.42% | raw |  |
| CPD-1H | 三组分混合(1h) | Al2O3 35.12%; ZnO 30.19%; CaF2 34.69% | raw | 当前 validate_xrdata.py 未覆盖 (可作扩展验收样本) |
| CPD-2 | 四组分+择优取向 | Al2O3 21.27%; ZnO 19.94%; CaF2 22.53%; Brucite Mg(OH)2 36.26% | mdi + raw |  |
| CPD-3 | 三组分+非晶 | Al2O3 30.79%; ZnO 19.68%; CaF2 20.06%; Glass (SiO2,非晶) 29.47% | mdi + raw |  |
| CPD-4 | 三组分+微吸收 | Al2O3 50.46%; Magnetite Fe3O4 19.64%; Zircon ZrSiO4 29.9% | raw |  |
| BAUXITE | 七相合成铝土矿 | Gibbsite 54.9%; Boehmite 14.93%; Hematite 10.0%; Goethite 9.98%; Quartz 5.16%; Kaolinite 3.02%; Anatase 2.0% | mdi + raw |  |
| GRANODIO | 天然花岗闪长岩 | Quartz(主); Feldspar(主); Albite(主); Biotite(主); Clinochlore(次); Hornblende(次); Zircon(痕量) | mdi + raw |  |
| PHARM1GR | 五相药物混合(1) | Mannitol; Sucrose; DL-Valine; Starch; Nizatidine | raw |  |
| PHARM2GR | 五相药物混合(2) | Mannitol; Sucrose; DL-Valine; Starch; Nizatidine | raw |  |
| MANNITOL | 单相有机物 | Mannitol 100.0% | raw |  |
| SUCROSE | 单相有机物 | Sucrose 100.0% | raw |  |
| VALINE | 单相有机物 | DL-Valine 100.0% | raw |  |
| STARCH | 单相有机物(近非晶) | Starch 100.0% | raw |  |
| NIZATIDI | 单相有机物 | Nizatidine 100.0% | raw |  |

## 三、XRData/csuHJW 教学集 (真值在文件名)

| 样品 | 类别 | 真值 | 格式 | 备注 |
|---|---|---|---|---|
| data001 | 双相TiO2(锐钛+金红石) | TiO2锐钛矿; TiO2金红石 | mdi + pdf + raw + rpt + txt | .txt/.rpt 是 JADE Phase ID Report, 会防御性报错; 用 .raw (Rigaku 解析器) 或 .mdi |
| data002 | 标准硅 Si | Si 100.0% | pdf + raw | .pdf 为报告非谱图 |
| data003 | AlCoO-650C | Al2O3(Co掺杂) | raw | 仅 .raw (Rigaku), 无 txt 副本 |
| data004 | AlCoO-750C | Al2O3(Co掺杂) | raw + sav + txt | .sav 为 Bruker 专有 |
| data005 | AlCoO-650C | Al2O3(Co掺杂) | raw + txt |  |
| data006 | AlCoO-750C | Al2O3(Co掺杂) | raw + txt |  |
| data007 | 铜 Cu | Cu(FCC) 100.0% | raw + txt | Data007-016 为同一 Cu 系列不同条件 |
| data008 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data009 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data010 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data011 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data012 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data013 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data014 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data015 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data016 | 铜 Cu | Cu(FCC) 100.0% | raw + txt |  |
| data017 | 铜 低角度 | Cu(FCC) 100.0% | raw + txt |  |
| data018 | 铜 高角度 | Cu(FCC) 100.0% | raw + txt |  |
| data019 | Al-Zn-Mg合金时效态 | Al(基体); MgZn2(时效相) | pdf + raw |  |
| data020 | 残余奥氏体钢 | 奥氏体; 铁素体 | pdf + raw |  |
| data021 | 氧化铁 | Fe2O3/Fe3O4 | pdf + raw |  |
| data022 | 黏土矿物 | 黏土(高岭石/云母类) | pdf + raw |  |
| data023 | 含非晶相 ZnO+CaCO3+Al2O3 | ZnO; CaCO3; Al2O3; 非晶 | pdf + raw + sav |  |
| data024 | 炭原丝 | 碳(近非晶) | raw | 近非晶, 不宜强行结晶相匹配 |
| data025 | 高聚物1 | polymer(近非晶) | raw + txt | data025-029 高聚物系列, 近非晶 |
| data026 | 高聚物2 | polymer(近非晶) | raw + txt |  |
| data027 | 高聚物3 | polymer(近非晶) | raw + txt |  |
| data028 | 高聚物4 | polymer(近非晶) | raw + txt |  |
| data029 | 高聚物5 | polymer(近非晶) | raw + txt |  |
| data030 | LiMnO2+Si | LiMnO2; Si(内标) | pdf + raw |  |
| data031 | ZrB-ZrB2 | ZrB; ZrB2 | abc + pdf + raw | .abc 专有格式 |
| data032 | Lansolazole(药物) | Lansolazole | is0 + is1 + is2 + pdf + raw | .is0/.is1/.is2 专有格式; 无机库难覆盖 |
| data033 | 单相锐钛矿 | Anatase TiO2 100.0% | raw + sav |  |
| data034 | 7046-7P(编号样品) | — | raw + sav | 真值未知, 需查 7046-7P 编号含义 |
| data035 | 硬质合金 WC 残余应力 | WC 100.0% | raw + sav | 应力测试用途 |
| data036 | ZnO-CaCO3-SiO2+Al2O3 四元混合 | ZnO; CaCO3; SiO2; Al2O3 | raw |  |
| data037 | Amorphous+SiO2 | SiO2(结晶); 非晶 | raw |  |
| data038 | Y2O3 | Y2O3 100.0% | pdf + raw + rrp | .rrp 专有格式 |
| data039 | LiMnO2+Si | LiMnO2; Si(内标) | raw |  |
| data040 | NCM811 三元正极 | NCM811 LiNi0.8Co0.1Mn0.1O2 | mdi + raw | 致密相; .raw 为 Rigaku 可解析 |
| data041 | ZnO+CaCO3 | ZnO; CaCO3 | cif + lst + mdi + par + raw + txt + xls | 目录型: 子目录含 ZnO.cif/CaCO3.cif 可作精修起点 |
| data042 | 陶瓷ZrSiO4-1180部分晶化 | ZrSiO4; ZrO2; Cristobalite | cif + lst + par + txt | 目录型: 子目录含 3 个 .cif; 仅 par/lst/txt, 原始谱图或需从 par 恢复 |
| data043 | Ni(OH)2 | Ni(OH)2 | apf + cif + lst + par + raw + spf + txt | 目录型: 子目录含 .apf/.spf/.cif 与 07009 Ni(OH)2.raw |
| data044 | Al-MgZn2过时效态 | Al; MgZn2 | cif + par + txt | 目录型: 子目录含 Al.cif/MgZn2.cif; 仅 txt/par |

## 四、test_xrd 13 试样基准

| 试样 | 真值 (wt% 可用时给出) | 格式 | 备注 |
|---|---|---|---|
| 1-1 | LiFePO4 100.0% | mdi + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 1-2 | NCM 811 100.0% | mdi + raw + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 2-1 | ZnO 50.0%; CaCO3 50.0% | mdi + raw + txt + xy | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 2-2 | TiO2锐钛矿; TiO2金红石 | mdi + raw + txt + xy | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 3-1 | ZnO 93.59%; Al2O3 5.04%; CaF2 1.36% | mdi + raw + txt + xy | 端到端验收入口: tests/test_xrd_samples.py (含元素限定); ≈ IUCr CPD-1C (同配比) |
| 3-2 | ZnO 19.68%; Al2O3 30.79%; CaF2 20.06%; 非晶玻璃 29.47% | mdi + raw + txt + xy | 端到端验收入口: tests/test_xrd_samples.py (含元素限定); ≈ IUCr CPD-3 (含非晶) |
| 4-1 | ZnO 19.94%; Al2O3 21.27%; CaF2 22.53%; Mg(OH)2 36.26% | mdi + raw + txt + xy | 端到端验收入口: tests/test_xrd_samples.py (含元素限定); ≈ IUCr CPD-2 (择优取向) |
| 5-1 | SiO2(α-石英); SiO2(方石英); CaCO3; MgCO3; CaMg(CO3)2 | mdi + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 5-2 | SiO2(α-石英); SiO2(方石英); CaCO3; Fe2O3; K{Al2[AlSi3O10](OH)2}（白云母） | mdi + txt + xy | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 5-2b | SiO2(α-石英); SiO2(方石英); CaCO3; Fe2O3; K{Al2[AlSi3O10](OH)2}（白云母） | mdi + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 5-3 | SiO2; Ca2Al2SiO7; Ca5[PO4]3F; α-FeO（OH）; Al2[(OH)4/Si2O5] （高岭土） | mdi + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定) |
| 7-1 | Quartz 5.16%; Boehmite 14.93%; Anatase 2.0%; Goethite 9.98%; Kaolinite 3.02%; Gibbsite 54.9%; Hematite 10.0% | mdi + raw + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定); = IUCr BAUXITE (合成铝土矿) |
| 7-2 | Quartz(主); Feldspar(主); Albite(主); Biotite(主); Clinochlore(次); Hornblende(次); Zircon(痕量) | mdi + raw + txt | 端到端验收入口: tests/test_xrd_samples.py (含元素限定); = IUCr GRANODIO (花岗闪长岩) |

### geshi 格式转换集

- **4-1**: dat + mdi + raw + txt + xy — 格式转换测试集(同一谱图5种格式)；验证 格式转换(dat/mdi/raw/txt/xy) 读入一致性与转换器

### 5/ 原始仪器导出目录

- **5-1#1##20260123-124003_100**: cif + lst + mdi + mtd + par + txt；含 .mtd/.par/.lst 仪器文件与匹配 .cif (精修起点); 5-2b=5-2 无择优取向
- **5-2#1##20260126-164127_100**: cif + jip + lst + mtd + par + txt；含 .mtd/.par/.lst 仪器文件与匹配 .cif (精修起点); 5-2b=5-2 无择优取向
- **5-2b#1##20260202-133922_100**: cif + jip + lst + mdi + par + txt；含 .mtd/.par/.lst 仪器文件与匹配 .cif (精修起点); 5-2b=5-2 无择优取向
- **5-3#1##20260127-163731_100**: cif + lst + mtd + par + txt；含 .mtd/.par/.lst 仪器文件与匹配 .cif (精修起点); 5-2b=5-2 无择优取向

## 五、坑点速查 (后续 agent 必读)

1. csuHJW 的 .raw = Rigaku RINT-2000 二进制(魔数 FI\0\0) → data_loader._load_rigaku_raw 已支持 (2026-10-08 #55); 更早版本会落入启发式兜底返回垃圾。
2. data001：TiO2双相.txt / .rpt = JADE Phase ID Report → data_loader 会防御性报错; 谱图请用 .raw 或 .mdi。
3. IUCr 的 .RAW = Philips RAW2 二进制 → data_loader._load_raw2 支持。
4. IUCr/Must do/ 下 .PRN/.txt 为同批谱图文本副本 (PRN 解析未接入, 仅 txt 已被 harness 用过 CPD 系列)。
5. IUCr/(IUCr) Standard data sets_files/ = 网页资源缓存, 非谱图; gsas/*.gss 与 *.tar.gz 为 GSAS/归档, 未接入。
6. .sav(Bruker)/.is0-2/.abc/.mtd/.par/.lst/.pdf 为专有参数/报告文件, 不作谱图解析。
7. IUCr CPD-1D/1E/1F/1H 及 Must do 全套当前 validate_xrdata.py 未覆盖 → 扩展验收可用样本。
8. test_xrd/geshi = 4-1 同谱图五格式 (dat/mdi/raw/txt/xy) → 格式转换一致性验收。
9. test_xrd/txt/元素限定.txt = 13 试样元素过滤真值; tests/test_xrd_samples.py 已内置。
10. 近非晶样本 (STARCH/data024/高聚物系列/CPD-3 玻璃) 不出尖锐峰, 召回漏检属预期内, 不算算法失败。
11. MANNITOL/VALINE 同时是有机库 (organic_reference_database.json) 的 exp 来源谱 — 改检索算法时勿破坏 #57 依赖。

## 六、验收入口映射

| 入口脚本 | 覆盖范围 | 产物 |
|---|---|---|
| `tests/validate_xrdata.py` | XRData 37 样本检索召回 (MANIFEST) + pdf2 兜底 + builtin 精修 | `tests/xrdata_validation_results.{json,csv}` |
| `tests/make_xrdata_checklist.py` | 重算召回(元素多重集匹配)并出最终清单 | `tests/xrdata_checklist.{md,csv}` |
| `tests/test_xrd_samples.py` | test_xrd 13 试样端到端 (元素限定三态过滤 + Rietveld 定量) | `tests/ 下 PolyXRD_测试报告*.txt` |
| `scripts/build_organic_db.py` | 有机库构建 (依赖 IUCr MANNITOL/VALINE.RAW 作 exp 来源) | `src/polyxrd/resources/database/organic_reference_database.json` |
| `tests/probe_organic_id.py / probe_xrdata_load.py` | 快速探针 (有机命中 / 各格式加载) | `stdout` |

## 七、未归类文件 (参考)

- **xrdata_iucr**: 78 个 — (IUCr) Standard data sets_files/IUCr-logo-White.png, (IUCr) Standard data sets_files/analytics.js.下载, (IUCr) Standard data sets_files/band.js.下载, (IUCr) Standard data sets_files/college-font.css, (IUCr) Standard data sets_files/compact-painter.js.下载, (IUCr) Standard data sets_files/decorators.js.下载, (IUCr) Standard data sets_files/detailed-painter.js.下载, (IUCr) Standard data sets_files/ether-painters.js.下载, (IUCr) Standard data sets_files/ethers.css, (IUCr) Standard data sets_files/ethers.js.下载, (IUCr) Standard data sets_files/event-utils.js.下载, (IUCr) Standard data sets_files/events.css …
- **xrdata_csuhjw**: 25 个 — Data041/CaCO3.cif, Data041/Data041.XLS, Data041/Data041.lst, Data041/Data041.par, Data041/Data041：ZnO+CaCO3.mdi, Data041/Data041：ZnO+CaCO3.raw, Data041/Data041：ZnO+CaCO3.txt, Data041/ZnO.cif, Data042/Cristobalite.cif, Data042/Data042：1：陶瓷ZrSiO-1180 部分晶化.lst, Data042/Data042：1：陶瓷ZrSiO-1180 部分晶化.par, Data042/Data042：1：陶瓷ZrSiO-1180 部分晶化.txt …
- **test_xrd**: 8 个 — mdi/物相结果+wt%.txt, mdi/物相结果.txt, raw/物相结果+wt%.txt, raw/物相结果.txt, xy/物相结果+wt%.txt, xy/物相结果.txt, 物相结果+wt%.txt, 物相结果.txt
