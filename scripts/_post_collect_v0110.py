"""v0.11.0 打包收尾 (对应 build.bat 步骤 3/6 的一部分):
把新 EXE 覆盖到 dist, 补 qt.conf, ICU 清理, 数据库自检。
用法: venv/Scripts/python.exe scripts/_post_collect_v0110.py
"""
import glob
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'build', 'PolyXRD')
DIST = os.path.join(ROOT, 'dist', 'PolyXRD')


def main() -> int:
    src_exe = os.path.join(BUILD, 'PolyXRD.exe')
    if not os.path.exists(src_exe):
        print('[FATAL] build/PolyXRD/PolyXRD.exe 不存在')
        return 1

    os.makedirs(DIST, exist_ok=True)

    # ── EXE 覆盖 (单文件原子替换, 绕开沙盒对目录的锁) ──
    dst_exe = os.path.join(DIST, 'PolyXRD.exe')
    tmp = dst_exe + '.new'
    shutil.copy2(src_exe, tmp)
    os.replace(tmp, dst_exe)
    print('[OK] EXE 覆盖:', round(os.path.getsize(dst_exe) / 1e6, 1), 'MB')

    for extra in ('qt.conf',):
        s = os.path.join(BUILD, extra)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(DIST, extra))
            print('[OK] 覆盖', extra)

    # ── ICU 清理 (依赖 OS icuuc shim) ──
    removed = 0
    for pat in (os.path.join(DIST, '_internal', 'icu*.dll'),
                os.path.join(DIST, '_internal', 'PySide6', 'icu*.dll')):
        for f in glob.glob(pat):
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
    print('[OK] ICU cleanup: removed', removed, 'files')

    # ── 数据库自检 (外挂策略) ──
    hits = []
    for pat in ('**/*.sqlite', '**/*.sqlite3', '**/*.db', '**/*.tar.xz'):
        hits += glob.glob(os.path.join(DIST, pat), recursive=True)
    if hits:
        print('[警告] dist 内发现数据库文件:')
        for h in hits:
            print('   ', h, round(os.path.getsize(h) / 1e6, 1), 'MB')
    else:
        print('[OK] 未发现数据库文件 (符合外挂策略)')

    # ── 完整性粗检: _internal 条目数 ──
    n = 0
    for _r, _d, files in os.walk(os.path.join(DIST, '_internal')):
        n += len(files)
    print('[INFO] _internal 文件数:', n)
    if n < 3000:
        print('[警告] _internal 文件数偏少, COLLECT 可能未完整')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
