"""v0.11.0 打包收尾: Portable.zip (仅本地, 不随 Release 发布) + VERSION.txt。"""
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'dist', 'PolyXRD')
OUT = os.path.join(ROOT, 'installer_output')
APPVER = '0.11.0'
ZIP = os.path.join(OUT, f'PolyXRD-v{APPVER}-Portable.zip')


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(ZIP):
        os.remove(ZIP)

    # ── 先写 VERSION.txt 进 dist (这样便携包能带上它) ──
    txt = (
        f"PolyXRD v{APPVER} Release\n"
        f"Version    : {APPVER}\n"
        f"Build Date : {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "ICU: 依赖系统 icuuc shim (PySide6 6.11 不自带 ICU)\n"
        "Databases: 外挂, 且各库独立打包 (随包不含数据库)。按需只下一个:\n"
        f"           PolyXRD-v{APPVER}-Databases-COD-inorg.zip  COD 无机物库 v2 (主检索库, 内嵌 CIF, 推荐)\n"
        f"           PolyXRD-v{APPVER}-Databases-COD-full.zip   COD 全库索引\n"
        "           PDF2-2004: ICDD 版权库, 不随 Release 分发, 由持授权用户自行准备。\n"
        "           解压后在菜单「数据库 ▸ 外挂数据库管理…」逐个导入 (可只挂其中一个)。\n"
        "           未导入时仅内置 118 种参考物相可用。\n"
        "Icon: 品牌化应用图标 (crystal-mark + XRD 配色, 多分辨率 ICO)\n"
    )
    with open(os.path.join(SRC, 'VERSION.txt'), 'w', encoding='utf-8') as f:
        f.write(txt)
    print('[OK] VERSION.txt 写入 dist')

    files = []
    for r, _d, fs in os.walk(SRC):
        for f in fs:
            full = os.path.join(r, f)
            rel = os.path.relpath(full, SRC)
            files.append((full, rel.replace(os.sep, '/')))
    print(f'[1/1] 打包 {len(files)} 个文件 -> Portable.zip ...')

    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, (full, rel) in enumerate(files, 1):
            z.write(full, rel)
            if i % 3000 == 0:
                print(f'    ... {i}/{len(files)}')
    print('[OK] Portable.zip:', round(os.path.getsize(ZIP) / 1e6, 1), 'MB (本地自用, 不上传)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
