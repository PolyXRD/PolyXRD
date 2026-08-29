"""Progress monitor for rebuild_cod_from_tar — run in separate shell."""
import sqlite3
import time
from pathlib import Path

DB = Path(r"d:\TEMP\PolyXRD\cod_index.sqlite")
prev_entries = 0
prev_sites = 0

while True:
    try:
        sz = round(DB.stat().st_size / 1024 / 1024, 1) if DB.exists() else 0
        c = sqlite3.connect(str(DB), timeout=5)
        n = c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
        ns = c.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
        n_cif = c.execute("SELECT COUNT(*) FROM cod_entries WHERE LENGTH(cif_gz) > 0").fetchone()[0]
        cif_mb = round((c.execute("SELECT COALESCE(SUM(LENGTH(cif_gz)),0) FROM cod_entries").fetchone()[0] or 0) / 1024 / 1024, 1)
        c.close()
        dn = n - prev_entries
        dns = ns - prev_sites
        prev_entries = n
        prev_sites = ns
        pct = round(n / 93391 * 100, 1)
        print(f"[{time.strftime('%H:%M:%S')}] entries={n:>6d}/93391 ({pct:>4.1f}%, +{dn:>4d})  "
              f"sites={ns:>7d}(+{dns:>4d})  cif_gz={n_cif:>6d}(sum {cif_mb:>4.1f}MB)  "
              f"DB={sz:>5.1f}MB  mtime={time.strftime('%H:%M:%S', time.localtime(DB.stat().st_mtime))}")
        if n >= 93300:
            print(" -> Build appears complete!")
            break
    except sqlite3.OperationalError as e:
        print(f"[{time.strftime('%H:%M:%S')}] DB locked? {e}")
    except FileNotFoundError:
        print(f"[{time.strftime('%H:%M:%S')}] DB not yet created")

    time.sleep(30)
