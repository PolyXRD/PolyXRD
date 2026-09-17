"""手动复制 PyInstaller COLLECT 产物 (3-tuple: rel, src, type).

路径以本脚本位置推导 (scripts/ 的上级 = 仓库根), 不再硬编码盘符 —
盘符迁移 (D:→E:) 后依然可用。
"""
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, 'dist', 'PolyXRD', '_internal')
TOC = os.path.join(ROOT, 'build', 'PolyXRD', 'COLLECT-00.toc')

text = open(TOC, encoding='utf-8', errors='ignore').read()
# 三元组: ('rel', 'src', 'TYPE')
#
# 注意: 这里【故意】不匹配 'EXECUTABLE'。
# COLLECT-00.toc 里 EXECUTABLE 那条的 rel 是 'PolyXRD.exe' (相对 dist\PolyXRD\ 根),
# 而本脚本的 DST 是 dist\PolyXRD\_internal\ —— 若一并收集会往 _internal 里多塞一份
# 39 MB 的 PolyXRD.exe 副本 (2026-09-16 实测), 启动器只认 dist\PolyXRD\PolyXRD.exe,
# 因此这份副本纯属冗余。EXE 由 build.bat / 手工 cp 负责放到 dist 根目录。
triples = re.findall(r"\('([^']+)',\s*'([^']+)',\s*'(?:BINARY|DATA|EXTENSION)'\)", text)

copied = skipped = missing = 0
miss_list = []
for rel, src in triples:
    if not os.path.isabs(src):
        continue
    dst = os.path.join(DST, rel)
    if not os.path.exists(src):
        miss_list.append(src)
        missing += 1
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        skipped += 1
        continue
    try:
        shutil.copy2(src, dst)
        copied += 1
    except Exception as e:
        miss_list.append((src, str(e)))
        missing += 1

print(f'TRIPLE={len(triples)} COPIED={copied} SKIPPED={skipped} MISSING={missing}')
for m in miss_list[:8]:
    print('  miss:', m)