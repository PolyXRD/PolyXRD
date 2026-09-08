# 物相分析 v2 重设计 (M21 — Phase Analysis Redesign)

> 状态: 设计稿 (待用户确认后实施)
> 参考: Match! 4 交互范式 (本机 C:\Program Files\Match4)
> 日期: 2026-09-08 | 基线: commit 2883cd0, 259 tests green

---

## 1. 现状痛点 (用户实测反馈)

| # | 现状 (phase_view.py) | 问题 |
|---|---|---|
| P1 | 单击候选 `clear_plot()` 后只画该相 (L405-406) | 多物相样品无法叠加对比, 无逐相颜色 |
| P2 | 匹配峰用**贯穿全高**的竖线标注 (L478, L504) | 噪声大; Match! 用**底部参考棒** (高度∝I/100) |
| P3 | 只有正向匹配: 参考峰→实验峰 (L421-437) | 缺反向视角: 样品实测峰有哪些**没被任何选中相解释** (= 残差峰, 提示漏检物相) |
| P4 | 无计算谱叠加 | 看不到选中相联合起来对整条谱线的解释程度 |
| P5 | 无峰-物相归属表 | 无法逐峰查看 "这个峰属于哪个相" |
| P6 | 匹配逻辑内嵌在视图层 (L409-437) | 不可单测, 与 `_on_candidate_clicked` 耦合 |

## 2. Match! 交互范式 (对齐点)

```
┌─────────────────────────────────────────────────────────┐
│  实验(黑线) + 计算谱(红线, 选中相合成)                      │  ← 主区
│  残差曲线(灰, 底部偏移)                                   │
│─────────────────────────────────────────────────────────│
│ 相1 ██████    ███  ██        █     (参考棒, 颜色A)        │  ← 棒区
│ 相2   ████████   ███    ██  (参考棒, 颜色B)               │    (每相一行
│ 未解释峰 ▲     ▲            (红色▲标记)                   │     或同区叠色)
└─────────────────────────────────────────────────────────┘
```

- **选中即叠加**: 候选列表勾选 (可多选) → 该相参考棒进底部棒区 + 实验峰按归属染色
- **峰标记双向**: 匹配到的实验峰顶画"相颜色圆点"; 未被解释的实验峰画红色▼ (残差峰)
- **计算谱叠加**: 选中相的合成谱 (红线) 盖在实验谱上, 视觉直接判断组合好坏
- **残差曲线**: 实验−计算 (灰线, 底部偏移) — 有精修权重时用精修值, 无则用等权
- **峰表**: 2θ / d / I / 归属相 (色块) / Δ2θ

## 3. 架构与数据流

```
用户勾选候选 ──▶ PhaseView._on_selection_changed
                    │
                    ▼
        PhaseViewModel.update_selection(phases)      ── state + signal
                    │
                    ▼
   services/phase_display.py (纯函数, 单测核心)
     ├ assign_peaks()          双向匹配 → PeakAssignment[]
     ├ combined_pattern()       选中相合成谱
     └ residual()               实验−计算
                    │
                    ▼
        widgets/pattern_display.py  (新绘图控件, 双区布局)
                    │
                    ▼
        PhaseView 底部: PeakMatchTable (峰-归属表)
```

---

## 4. 原子模块规格

### M21-A `src/polyxrd/services/phase_display.py` (新建, 纯逻辑)

**A1. 相位色板**

```python
PHASE_PALETTE: tuple[str, ...] = ("#E53935", "#1E88E5", "#43A047", "#FB8C00",
                                  "#8E24AA", "#00ACC1", "#6D4C41", "#546E7A")

def phase_color(i: int) -> str:
    """第 i 个选中相的颜色; 超出色板长度取模循环。
    边界: i<0 → 取模同 i=0; 返回恒为 PHASE_PALETTE 成员。"""
```

**A2. 双向峰归属** (核心)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PeakAssignment:
    two_theta: float                 # 实验峰 2θ
    intensity: float                 # 实验峰强度
    d_spacing: Optional[float]       # 实验峰 d (可 None)
    phase_index: Optional[int]       # 匹配到的选中相下标; None = 未解释 (残差峰)
    phase_name: Optional[str]
    ref_two_theta: Optional[float]  # 匹配到的参考峰 2θ
    delta_2theta: Optional[float]    # Δ2θ = 实验 − 参考 (符号约定与 calibration 一致)
    hkl: Optional[tuple]             # 参考峰 hkl

def assign_peaks(
    exp_peaks: list[Peak],               # 实测峰 (phase_vm.peaks.peaks)
    phases: list[Phase],                 # 选中相列表
    tolerance: float = 0.30,            # 2θ 容差 (度), 来自 UI 容差 SpinBox
) -> tuple[list[PeakAssignment], list[list[bool]]]:
    """
    双向匹配:
      正向: 每个选中相的每条参考峰 → 是否存在 |Δ2θ|≤tolerance 的实验峰 (沿用现有语义);
      反向: 每个实验峰 → 在所有选中相的参考峰中取 |Δ2θ| 最小且 ≤tolerance 者归属
            (并列时取 Δ 绝对值更小; 再并列取相下标小者, 保证确定性)。
    返回: (每实验峰的 PeakAssignment, 每相每参考峰的命中布尔表)
    算法: 参考峰收集为 [(phase_idx, ref_2θ, hkl, I)] 排序后, 每实验峰二分/线性找最近
          (N_ref 通常 < 100, 线性即可; 复杂度 O(N_exp × N_ref))。
    边界:
      - phases 为空 → 全部 phase_index=None (全残差峰)
      - exp_peaks 为空 → ([], [])
      - 同一参考峰可被多个实验峰命中 (允许; 布尔表只记录"是否命中")
      - 一个实验峰只归属一个相 (最近者), 但布尔表中多个相都可标记命中
    验收: 纯函数; 给定合成数据断言归属/未解释/容差边界 (Δ=tolerance 恰好含/恰超出)。"""
```

**A3. 合成谱 (选中相联合计算谱)**

```python
def combined_pattern(
    two_theta: np.ndarray,               # 实验谱 2θ 轴
    phases: list[Phase],
    weights: Optional[list[float]] = None,  # 各相权重; None = 等权 1/n
    fwhm: float = 0.15,
    eta: float = 0.5,
    peak_shape: str = "pseudo-voigt",
    scale_to_exp: bool = True,           # True: 峰高对齐实验最强峰 (显示用)
) -> np.ndarray:
    """
    实现: 从 RietveldRefiner._compute_spectrum_from_ref 提取为模块级纯函数
    spectrum_from_refs() (refiner 改调用之, 行为不变 — 见 M21-D2), 此处复用。
    scale_to_exp: y_calc *= max(y_exp)/max(y_calc) (仅显示用途; 残差计算在
    归一化后的标度下进行, 避免量纲失衡)。
    边界: phases 空 → 全 0 数组; two_theta 空 → 空。
    验收: 单相合成谱峰位与参考峰一致 (±1 步长); 双相 = 各单相之和 (线性叠加)。"""
```

**A4. 残差**

```python
def residual(y_exp: np.ndarray, y_calc: np.ndarray) -> np.ndarray:
    """y_exp − y_calc; 长度不一致 → ValueError; NaN 透传。"""
```

### M21-B `src/polyxrd/views/widgets/pattern_display.py` (新建绘图控件)

```python
class PatternDisplayWidget(QWidget):
    """Match! 式双区谱图: 上=实验+计算+残差, 下=逐相参考棒区。
    基于 matplotlib GridSpec(2,1, height_ratios=[4,1], sharex)。"""

    # ── API ──────────────────────────────────────────────
    def set_experiment(self, data: XRDData) -> None
        # 黑线 (color="#1a1a1a", lw=1.1); 重置主区; 触发重绘
    def set_selected_phases(self, phase_sticks: list[tuple[str, list, str]]) -> None
        # [(phase_name, ref_peaks[(hkl,2θ,I)], color)] — 棒区每相一行:
        # 棒高 = I/100 × row_height, 底部基线 y = -i × row_height;
        # 相名标在棒区左侧 (fontsize 7, 同色); >6 相时只画棒不标名 (tooltip)
    def set_calculated(self, two_theta, y_calc) -> None
        # 红线 (color="#D32F2F", lw=1.0, alpha=0.85) 盖在实验上; None=隐藏
    def set_residual_curve(self, two_theta, y_res) -> None
        # 灰线画在主区底部偏移 (offset = -0.12 × ymax), 附零基线; None=隐藏
    def set_peak_assignments(self, assignments: list[PeakAssignment]) -> None
        # 主区: 每个实验峰顶部画归属相颜色的实心圆点 (半径4pt, zorder高);
        # phase_index=None 的峰画红色倒三角 ▼ (marker="v", color="#F44336")
        # + 峰顶 2θ 文字 (fontsize 6, 仅未解释峰, 避免拥挤)
    def set_info_text(self, html: str) -> None
    def clear_all(self) -> None            # 恢复空白双区
    def export_image(self, path, dpi=300) -> None
    # ── Signals ─────────────────────────────────────────
    peak_clicked = Signal(object)           # 点中实验峰 (向上给峰表联动)
    # ── 边界 ───────────────────────────────────────────
    # 空实验 + 有相 → 只画棒区; 残差/计算未设置时对应元素隐藏;
    # 颜色循环见 A1; x 轴联动 (棒区缩放跟随主区)。
    # 验收: offscreen 单测 — set_experiment 后 axes 有 1 条黑线;
    #       2 相 → 棒区 2 组 Line2D 且基线不同; assignments 混合归属时
    #       圆点数+▼数 = 峰总数; clear_all 后 artists 为空。
```

### M21-C `src/polyxrd/views/widgets/peak_match_table.py` (新建峰-归属表)

```python
class PeakMatchTable(QTableWidget):
    """底部峰表: 已匹配 / 未解释 两个分区。"""
    COLUMNS = ["2θ (°)", "d (Å)", "I", "归属物相", "Δ2θ", "hkl"]

    def set_assignments(self, assignments: list[PeakAssignment],
                        colors: list[str]) -> None:
        """行序按 2θ 升序; 已匹配行: 第4列放 [■色块+相名] (富文本);
        未解释行: 整行浅红底 (#FFEBEE), 归属列显示 "—未解释—"。
        点击行 → peak_row_clicked(two_theta) 信号 (谱图上闪高该峰)。"""
    # 验收: offscreen — 3 峰 2 相数据下行数=3, 未解释行背景色可断言。
```

### M21-D 视图与 VM 改造

**D1. `PhaseViewModel` (viewmodels/phase_vm.py) 扩展**

```python
# 新增状态与信号
self.selected_phases: list[Phase] = []        # 勾选中的候选 (有序, 先选在前)
selection_changed = Signal(list)             # list[Phase]

def update_selection(self, phase: Phase, checked: bool) -> None:
    """勾选→追加 (去重: 同 name+formula); 取消→移除; 超过 8 相弹提示截断。"""

def current_assignment(self, tolerance: float) -> tuple:
    """(assignments, ref_hit_table) = assign_peaks(peaks, selected_phases, tol)。
    无峰或无选中 → ([], [])。结果缓存 (tolerance/选择未变不重算)。"""
```

**D2. `rietveld_refiner.py` 小重构 (无行为变化)**

`_compute_spectrum_from_ref` 的谱合成内核提取为 `services/phase_display.spectrum_from_refs()`
(签名同 A3 内核), refiner 方法变薄壳调用 — 回归全绿即等价性证明。

**D3. `phase_view.py` 重排 (保留现有识别控制面板)**

- 谱图区换 `PatternDisplayWidget`; 识别控制面板 (元素过滤/库源/方法/候选列表) 保留
- 候选列表项改为**可勾选** (QListWidgetItem setCheckState); 勾选框切换 → D1.update_selection
  → 重算归属 → 刷新谱图 + 峰表 + 信息条 (逐相覆盖率 | 总覆盖 | 未解释峰数)
- 原 "单击预览" 保留但不再 clear: 单击 = 峰表过滤到该相 + 谱图该相棒高亮 (加粗)
- 新增按钮: 「清除选择」「叠加计算谱 (开/关)」「显示残差 (开/关)」
- 容差 SpinBox 同时驱动匹配 (替代现硬编码传参)
- 保留 `phase_confirmed` 信号语义 (确认的物相集合 = 当前勾选项) → 精修向导不变

### M21-E 测试计划

| 文件 | 覆盖 |
|---|---|
| `tests/test_phase_display.py` (新) | A1 色板取模 / A2 双向归属 (含空相、空峰、容差边界 Δ=tol±ε、并列取近、确定性) / A3 单相峰位、双相线性叠加、scale_to_exp / A4 残差与长度不匹配 |
| `tests/test_pattern_display.py` (新, offscreen) | B: 各 set_* 的 artists 计数与颜色断言; clear_all; 空数据边界 |
| `tests/test_peak_match_table.py` (新, offscreen) | C: 行数/未解释行背景/信号 |
| `tests/test_rietveld.py` (既有) | D2 重构后全绿 = 谱合成等价性回归 |

## 5. 实施顺序 (每步可独立验收)

1. **S1**: M21-A 服务层 + `test_phase_display.py` (纯逻辑, 零 UI 风险)
2. **S2**: D2 谱合成提取 + 既有回归 (证明等价)
3. **S3**: M21-B 绘图控件 + offscreen 测试
4. **S4**: M21-C 峰表 + D1 VM 扩展 + 测试
5. **S5**: D3 视图重排接线 + 全量回归 + 打包测试版

预计改动: 新增 ~700 行 (服务 180 / 控件 260 / 峰表 120 / 测试 300+), 修改 phase_view.py ~200 行。
不动: 识别算法 (fom/search-match)、精修管线、报告导出 — 本次纯展示层重设计。

## 6. 与 Match! 的对齐差异 (有意为之)

- Match! 的 "flag + 全谱候选浏览" 保留为候选列表勾选, 不引入其复杂的多窗口
- 残差峰用红色▼ + 计算谱叠加联合表达, 比 Match! 的纯标记更直观判断组合完整性
- 棒区逐相一行 (Match! 是同区叠色), 行式更易读且实现简单; 后续可加开关合并
