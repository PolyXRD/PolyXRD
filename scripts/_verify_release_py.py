"""v0.11.0 发布产物收尾 (Python 等效复刻 scripts/verify_release.ps1)。

为什么不用 .ps1: 本环境安全策略禁止从 Bash 调 PowerShell, 只能走 Python。
逻辑与 verify_release.ps1 一致:
  1. 便携包校验: zip 可读 / 含 PolyXRD.exe / 不含业务数据库
  2. 三个独立外挂数据库包 (每库一包) + 字节对账
  3. SHA-256 清单 -> installer_output/SHA256-v0.11.0.txt

用法: venv/Scripts/python.exe scripts/_verify_release_py.py -v 0.11.0
"""
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'installer_output')

# 与 db_import.py 保持一致 (1.0.1: cod_index 已移入 cod_data/, 无机库用 index 变体)
DB_KINDS = [
    ('COD-inorg-index', os.path.join(ROOT, 'cod_data', 'COD_inorganics_index.sqlite'), 'COD_inorganics_index.sqlite'),
    ('COD-full-index',  os.path.join(ROOT, 'cod_data', 'cod_index.sqlite'),            'cod_index.sqlite'),
    ('PDF2',            os.path.join(ROOT, 'cod_data', 'PDF2_2004.sqlite'),            'PDF2_2004.sqlite'),
]
BANNED_NAMES = {'cod_index.sqlite', 'COD_inorganics.sqlite',
                'COD_inorganics_index.sqlite', 'PDF2_2004.sqlite'}
ALLOWED = 'pymatgen/symmetry/symm_data_magnetic.sqlite'
FAILS = []


def fail(msg):
    print('  [FAIL]', msg)
    FAILS.append(msg)


def mib(n):
    return f'{n / 1048576:.1f} MB'


def check_portable(ver):
    z = os.path.join(OUT, f'PolyXRD-v{ver}-Portable.zip')
    print(f'[1/3] 便携包校验: PolyXRD-v{ver}-Portable.zip')
    if not os.path.exists(z):
        fail('便携包不存在')
        return
    print('      体积', mib(os.path.getsize(z)))
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        print('      条目数', len(names))
        if 'PolyXRD.exe' not in names:
            fail('包内缺少 PolyXRD.exe')
        bad = [n for n in names
               if os.path.basename(n) in BANNED_NAMES
               or ((n.endswith('.sqlite') or n.endswith('.sqlite3') or n.endswith('.db'))
                   and ALLOWED not in n)]
        if bad:
            for b in bad:
                fail('包内不应存在的数据库: ' + b)
        else:
            print('      OK: 未发现业务数据库 (符合外挂策略)')


def build_db_pkgs(ver):
    print('[2/3] 外挂数据库包 (每个库独立成包)')
    built = []
    for suffix, src, inner in DB_KINDS:
        if not os.path.exists(src):
            print(f'      [跳过] 缺少源文件 {src}')
            continue
        pkg = os.path.join(OUT, f'PolyXRD-v{ver}-Databases-{suffix}.zip')
        if os.path.exists(pkg):
            os.remove(pkg)
        src_size = os.path.getsize(src)
        print(f'      写 {os.path.basename(pkg)} (源 {mib(src_size)}) ...')
        with zipfile.ZipFile(pkg, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(src, inner)
        # 对账: 恰好 1 条目 / 名字正确 / 解压字节 == 源字节
        with zipfile.ZipFile(pkg) as zf:
            infos = zf.infolist()
            cnt = len(infos)
            name0 = infos[0].filename if cnt else ''
            total = sum(i.file_size for i in infos)
        ok = cnt == 1 and name0 == inner and total == src_size
        if not ok:
            fail(f'{suffix}: 对账失败 (条目 {cnt}, 名 {name0!r}, 解压 {total} vs 源 {src_size})')
        else:
            print(f'            OK: 1 个条目 / {inner} / 字节对账通过  zip={mib(os.path.getsize(pkg))}')
            built.append(pkg)
    if not built:
        fail('没有生成任何数据库包')
    return built


def sha256_file(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def write_hashes(ver, built):
    print('[3/3] SHA-256')
    targets = [os.path.join(OUT, f'PolyXRD-Setup-v{ver}.exe'),
               os.path.join(OUT, f'PolyXRD-v{ver}-Portable.zip')] + built
    lines = [f'PolyXRD v{ver} 发布产物校验值 (SHA-256)',
             '生成时间: (python 脚本)', '',
             '单位说明: MB = 1,048,576 字节 (资源管理器口径)', '']
    for f in targets:
        if not os.path.exists(f):
            continue
        size = os.path.getsize(f)
        h = sha256_file(f)
        print(f'      {os.path.basename(f):<44} {mib(size):>12}  {h}')
        lines.append(f'{h}  {os.path.basename(f)}')
        lines.append(f'#   size = {size} bytes ({mib(size)})')
    out = os.path.join(OUT, f'SHA256-v{ver}.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('      写入', out)


def main():
    ver = '0.11.0'
    args = sys.argv[1:]
    if '-v' in args:
        ver = args[args.index('-v') + 1]
    print(f'=== PolyXRD v{ver} 发布产物校验 (python 版) ===')
    check_portable(ver)
    built = build_db_pkgs(ver)
    write_hashes(ver, built)
    print()
    if FAILS:
        print(f'RESULT: FAIL ({len(FAILS)} 项)')
        return 1
    print('RESULT: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
