"""
PolyXRD 应用图标生成器
========================
基于品牌资产 (crystal-mark.png + logo 配色) 生成符合 Windows 多分辨率规范的 .ico。

设计:
- 圆角方形背景 (品牌深色 #0F172A → 蓝色 #0284C7 对角线渐变)
- 居中放置晶胞六边形 + XRD 衍射曲线 (来自 crystal-mark.png, 白色, 占比 ~58%)
- 输出 256/128/64/48/32/24/16 多分辨率 ICO, 同时输出 512×512 高清 PNG 备份

使用:
    python build_icon.py
输出:
    src/polyxrd/resources/app-icon.ico  (7 个尺寸)
    src/polyxrd/resources/app-icon.png  (256x256, 兼容旧代码读取)
    src/polyxrd/resources/app-icon@2x.png (512x512, Retina/高分屏可选)
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

# 品牌配色 (从 logo-horizontal.png 精确采样)
BRAND_DARK = (15, 23, 42)      # #0F172A  slate-950  "Poly"
BRAND_BLUE = (2, 132, 199)      # #0284C7  sky-600    "XRD"
FOREGROUND_WHITE = (255, 255, 255)
FOREGROUND_SOFT = (226, 232, 240)  # #E2E8F0 slate-200 (次要线条)

RES_DIR = Path(__file__).resolve().parent / "src" / "polyxrd" / "resources"
CRYSTAL_MARK = RES_DIR / "crystal-mark.png"
OUT_ICO = RES_DIR / "app-icon.ico"
OUT_PNG = RES_DIR / "app-icon.png"
OUT_PNG_2X = RES_DIR / "app-icon@2x.png"

ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]
SOURCE_SIZE = 512  # 渲染用大尺寸, 再下采样到各档


def _rounded_rect_mask(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """返回 size×size 的圆角方形 L 蒙版 (255=前景, 0=透明)."""
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    radius = int(size * radius_ratio)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return img


def _gradient_bg(size: int, c1=BRAND_DARK, c2=BRAND_BLUE) -> Image.Image:
    """对角线渐变背景 (左上 → 右下)."""
    img = Image.new("RGB", (size, size), c1)
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            r = int(c1[0] * (1 - t) + c2[0] * t)
            g = int(c1[1] * (1 - t) + c2[1] * t)
            b = int(c1[2] * (1 - t) + c2[2] * t)
            px[x, y] = (r, g, b)
    return img


def _colorize_crystal(mark: Image.Image, size: int) -> Image.Image:
    """将 crystal-mark.png 的深色描边改为白色前景, 透明背景保留."""
    rgba = mark.convert("RGBA")
    r, g, b, a = rgba.split()
    # 把 RGB 都设为白, alpha 沿用原图
    white = Image.new("RGB", rgba.size, FOREGROUND_WHITE)
    out = Image.merge("RGBA", (*white.split(), a))
    return out


def _composite(source_size: int = SOURCE_SIZE) -> Image.Image:
    """合成一张 source_size 的图标主图."""
    bg = _gradient_bg(source_size)

    # 晶胞 mark 缩放至 ~58% (留出透气感)
    mark = Image.open(CRYSTAL_MARK).convert("RGBA")
    target = int(source_size * 0.58)
    mark_resized = mark.resize((target, target), Image.LANCZOS)
    fg = _colorize_crystal(mark_resized, target)

    # 居中粘贴
    ox = (source_size - target) // 2
    bg_rgba = bg.convert("RGBA")
    bg_rgba.alpha_composite(fg, (ox, ox))

    # 加圆角蒙版
    mask = _rounded_rect_mask(source_size)
    bg_rgba.putalpha(mask)

    return bg_rgba


def build() -> None:
    print(f"[icon] composing {SOURCE_SIZE}×{SOURCE_SIZE} base…")
    master = _composite(SOURCE_SIZE)

    # 写 2x 高清 PNG
    master.save(OUT_PNG_2X, format="PNG", optimize=True)
    print(f"[icon] wrote {OUT_PNG_2X} ({master.size[0]}×{master.size[1]})")

    # 256 PNG (主入口)
    main256 = master.resize((256, 256), Image.LANCZOS)
    main256.save(OUT_PNG, format="PNG", optimize=True)
    print(f"[icon] wrote {OUT_PNG} (256×256)")

    # 各档 ICO 入口 (LANCZOS 下采样, 小尺寸保留更多细节)
    layers = []
    for s in ICON_SIZES:
        layer = master.resize((s, s), Image.LANCZOS)
        layers.append(layer)
        print(f"[icon]   layer {s}×{s} prepared")

    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    # Pillow ICO saver: 传入最大图, 让 Pillow 按 sizes 下采样生成多分辨率 ICO
    # 用 master (512) 而非 layers[-1] (256) 以确保小尺寸下采样质量最佳
    master.save(
        OUT_ICO,
        format="ICO",
        sizes=[(s, s) for s in ICON_SIZES],
    )
    print(f"[icon] wrote {OUT_ICO} (sizes={ICON_SIZES})")

    # 验证
    with Image.open(OUT_ICO) as ico:
        ico_sizes = sorted(ico.ico.sizes(), key=lambda t: -t[0])
        print(f"[icon] verify {OUT_ICO.name} entries: {ico_sizes}")


if __name__ == "__main__":
    build()