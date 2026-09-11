"""
matplotlib 中文字体配置
=======================
matplotlib 默认字体栈 (DejaVu Sans / Bitstream Vera / CM) **没有一个含 CJK 字形**,
所以图上的中文会画成一排豆腐块 ``□□□``。本模块在导入时就地改 ``rcParams``,
把系统里有的中文字体插到 ``font.sans-serif`` 最前面。

设计要点
--------
* **幂等**: 反复调用只生效一次 (``_done`` 标志), 可在任意模块 import 期调用。
* **只调顺序, 不动别的**: 找不到任何中文字体时保持 matplotlib 原样, 绝不抛错 ——
  Linux/macOS 上没装中文包也不该让程序启动不了。
* **``axes.unicode_minus=False``**: 中文字体普遍缺 U+2212 (MINUS SIGN), 负号会变
  豆腐块; 关掉后 matplotlib 退回 ASCII 连字符 ``-``, 显示正常。
* **字体族按优先级探测**: 微软雅黑 > 黑体 > 宋体 > 苹方/冬青 > 思源, 覆盖
  Windows / macOS / 常见 Linux 发行版。
"""
from __future__ import annotations

#: 按优先级排列的候选中文字体族 (Linux/macOS/Windows 混合覆盖)。
_CJK_CANDIDATES = (
    "Microsoft YaHei",      # Windows 微软雅黑 (字形与屏显最搭)
    "SimHei",               # Windows 黑体
    "PingFang SC",          # macOS 苹方
    "Hiragino Sans GB",     # macOS 冬青黑体
    "Noto Sans CJK SC",     # Linux 思源黑体 (Noto)
    "Source Han Sans SC",   # Linux 思源黑体 (Adobe)
    "WenQuanYi Micro Hei",  # Linux 文泉驿
    "SimSun",               # Windows 宋体 (兜底, 衬线)
)

_done = False

#: ``ensure_cjk_font()`` 实际选中的字体族 (未调用过时为 None)。
_active: str | None = None


def ensure_cjk_font(force: bool = False) -> str | None:
    """把系统中可用的中文字体插到 matplotlib 字体栈最前。

    Returns:
        实际启用的字体族名; 系统一个中文字体都没有时返回 ``None``
        (此时 rcParams 保持原样, 只是中文会显示为豆腐块)。
    """
    global _done, _active
    if _done and not force:
        return _active

    try:
        import matplotlib
        from matplotlib import font_manager as fm
    except Exception:  # noqa: BLE001 - matplotlib 不可用时静默跳过
        return None

    available = {f.name for f in fm.fontManager.ttflist}
    picked: str | None = next(
        (n for n in _CJK_CANDIDATES if n in available), None
    )

    if picked is not None:
        # 中文字体排最前, 后面保留 DejaVu Sans 等作西文兜底
        stack = matplotlib.rcParams.get("font.sans-serif", [])
        stack = [n for n in stack if n != picked]
        matplotlib.rcParams["font.sans-serif"] = [picked, *stack]
        # mathtext 与普通文本共用字体族, 否则 $..$ 里中文又变豆腐块
        matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
    # 中文字体普遍缺 U+2212; 无论有没有中文字体都关掉, 负号更稳
    matplotlib.rcParams["axes.unicode_minus"] = False

    _active = picked
    _done = True
    return picked
