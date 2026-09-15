"""v0.11.0: 给 COD 无机物库内嵌 CIF (cif_gz) + 原子位点子集。

产出: cod_data/COD_inorganics.sqlite (原地升级, 原文件先备份为
COD_inorganics.sqlite.bak_<ts>)。

数据源:
  - CIF 全文: cod/cif/<d>/<dd>/<ddd>/<cod_id>.cif (110,152 个, 无机库 cod_id 100% 命中抽样)
  - 原子位点: cod_index.sqlite 的 cod_atomic_sites 中与无机库 cod_id 相交的子集
    (约 31 万行, 作为"不需要 CIF 全文"的快速路径; 其余相由 cif_gz 运行时解析)

表结构变更 (与 cod_local.get_cif Level-2 / get_atomic_sites 的读取约定一致):
  - phases 表新增列 cif_gz BLOB   (gzip 压缩的 CIF 1.1 全文; 缺失为 NULL)
  - 新增 cod_atomic_sites 表      (与 cod_index.sqlite 同 schema, 子集)
  - 新增/更新 meta 表             (cif_source / cif_count / schema_version)
"""
import gzip
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INORG = os.path.join(ROOT, 'cod_data', 'COD_inorganics.sqlite')
CIF_ROOT = os.path.join(ROOT, 'cod', 'cif')
INDEX_DB = os.path.join(ROOT, 'cod_index.sqlite')

BATCH = 400


def cif_path_for(cod_id: int) -> str:
    s = str(cod_id)
    return os.path.join(CIF_ROOT, s[0], s[1:3], s[3:5], s + '.cif')


def main() -> int:
    t0 = time.time()
    if not os.path.exists(INORG):
        print('[FATAL] 无机库不存在:', INORG)
        return 1
    if not os.path.isdir(CIF_ROOT):
        print('[FATAL] CIF 目录不存在:', CIF_ROOT)
        return 1

    # ── 0. 备份 + 工作副本 ─────────────────────────────────
    bak = INORG + '.bak_' + time.strftime('%Y%m%d_%H%M%S')
    print('[0] 备份原库 ->', bak)
    shutil.copy2(INORG, bak)

    work = INORG + '.work'
    if os.path.exists(work):
        os.remove(work)
    shutil.copy2(bak, work)

    conn = sqlite3.connect(work)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cols = [r['name'] for r in cur.execute('PRAGMA table_info(phases)')]
    if 'cif_gz' not in cols:
        cur.execute('ALTER TABLE phases ADD COLUMN cif_gz BLOB')
        print('[1] phases 表新增 cif_gz 列')
    else:
        print('[1] cif_gz 列已存在, 跳过 ALTER')

    # ── 2. 原子位点子集 (快速路径) ─────────────────────────
    print('[2] 迁移原子位点子集 ...')
    cur.execute('DROP TABLE IF EXISTS cod_atomic_sites')
    cur.execute(
        'CREATE TABLE cod_atomic_sites ('
        ' cod_id INTEGER NOT NULL,'
        ' site_idx INTEGER NOT NULL,'
        ' label TEXT, element TEXT NOT NULL,'
        ' x REAL NOT NULL, y REAL NOT NULL, z REAL NOT NULL,'
        ' occupancy REAL,'
        ' PRIMARY KEY (cod_id, site_idx))'
    )
    cur.execute('CREATE INDEX idx_sites_cod_id ON cod_atomic_sites(cod_id)')

    icur = sqlite3.connect(INDEX_DB)
    icur.row_factory = sqlite3.Row
    id_rows = [r[0] for r in cur.execute('SELECT cod_id FROM phases ORDER BY cod_id')]
    print('    无机相总数:', len(id_rows))
    sites_total = 0
    for i in range(0, len(id_rows), 900):
        chunk = id_rows[i:i + 900]
        q = ('SELECT cod_id, site_idx, label, element, x, y, z, occupancy '
             'FROM cod_atomic_sites WHERE cod_id IN (%s) ORDER BY cod_id, site_idx'
             % ','.join('?' * len(chunk)))
        rows = icur.execute(q, chunk).fetchall()
        if rows:
            cur.executemany(
                'INSERT OR REPLACE INTO cod_atomic_sites VALUES (?,?,?,?,?,?,?,?)',
                [(r['cod_id'], r['site_idx'], r['label'], r['element'],
                  r['x'], r['y'], r['z'], r['occupancy']) for r in rows])
            sites_total += len(rows)
        if (i // 900) % 20 == 0:
            print(f'    ... {i}/{len(id_rows)} (已迁 {sites_total} 行位点)')
    conn.commit()
    print(f'    位点子集迁移完成: {sites_total} 行')

    # ── 3. 内嵌 CIF 全文 ───────────────────────────────────
    print('[3] 内嵌 CIF (gzip) ...')
    updated = missing = 0
    pend = []
    for n, cid in enumerate(id_rows, 1):
        p = cif_path_for(cid)
        if os.path.exists(p):
            with open(p, 'rb') as f:
                raw = f.read()
            pend.append((gzip.compress(raw, 6), cid))
        else:
            missing += 1
        if len(pend) >= BATCH:
            cur.executemany('UPDATE phases SET cif_gz=? WHERE cod_id=?', pend)
            updated += len(pend)
            pend = []
        if n % 5000 == 0:
            conn.commit()
            el = time.time() - t0
            eta = el / n * (len(id_rows) - n)
            print(f'    ... {n}/{len(id_rows)} (嵌入 {updated}, 缺 {missing}) '
                  f'耗时 {el:.0f}s ETA {eta:.0f}s')
    if pend:
        cur.executemany('UPDATE phases SET cif_gz=? WHERE cod_id=?', pend)
        updated += len(pend)
    conn.commit()
    print(f'    CIF 嵌入完成: {updated} 条嵌入, {missing} 条缺失')

    # ── 4. meta 记录 ──────────────────────────────────────
    print('[4] 写 meta ...')
    try:
        cur.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
    except Exception:
        pass
    for k, v in [
        ('schema_version', '2'),
        ('cif_source', os.path.relpath(CIF_ROOT, ROOT)),
        ('cif_embedded', str(updated)),
        ('cif_missing', str(missing)),
        ('atomic_sites_rows', str(sites_total)),
        ('build_time', time.strftime('%Y-%m-%d %H:%M:%S')),
    ]:
        cur.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (k, v))
    conn.commit()

    # ── 5. VACUUM + 对账 ─────────────────────────────────
    print('[5] VACUUM (空间回收, 可能较慢) ...')
    cur.execute('VACUUM')
    conn.close()
    icur.close()

    chk = sqlite3.connect(work)
    n1 = chk.execute('SELECT COUNT(*) FROM phases WHERE cif_gz IS NOT NULL').fetchone()[0]
    n2 = chk.execute('SELECT COUNT(*) FROM phases').fetchone()[0]
    n3 = chk.execute('SELECT COUNT(*) FROM cod_atomic_sites').fetchone()[0]
    chk.execute('PRAGMA integrity_check')
    ok = chk.fetchone()[0]
    chk.close()
    size = os.path.getsize(work)
    print(f'[对账] cif_gz 非空 {n1}/{n2} (覆盖率 {n1/max(n2,1)*100:.1f}%), '
          f'位点 {n3} 行, integrity={ok}, 体积 {size/1e6:.1f} MB')

    if ok != 'ok' or n1 == 0:
        print('[FATAL] 完整性检查未通过, 不替换原库')
        return 1

    os.replace(work, INORG)
    print(f'[DONE] 已替换 {INORG}  总耗时 {time.time()-t0:.0f}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
