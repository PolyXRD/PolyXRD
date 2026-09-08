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
triples = re.findall(r"\('([^']+)',\s*'([^']+)',\s*'(?:BINARY|DATA|EXTENSION|EXECUTABLE)'\)", text)

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