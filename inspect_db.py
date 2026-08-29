"""Quick inspect of COD sqlite schema and content."""
import sqlite3

DB = r"d:\TEMP\PolyXRD\cod_index.sqlite"
c = sqlite3.connect(DB)

print("Tables:")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print("  ", r[0])

print("\ncod_entries columns:")
for r in c.execute("PRAGMA table_info(cod_entries)"):
    print(f"   {r[1]:25s} {r[2]}")

print("\ncod_atomic_sites columns:")
for r in c.execute("PRAGMA table_info(cod_atomic_sites)"):
    print(f"   {r[1]:25s} {r[2]}")

print("\ncod_entries count:", c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0])
print("cod_atomic_sites count:", c.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0])
print("meta:")
for k, v in c.execute("SELECT key,value FROM meta"):
    print(f"  {k} = {v}")

print("\nSample 3 entries:")
for r in c.execute("SELECT cod_id, file, formula, formula_red, elements, mineral_name, space_group_number, a, b, c, volume FROM cod_entries LIMIT 3"):
    print(" ", r)

print("\nAtomic sites sample (COD 1000000?):")
for r in c.execute("SELECT cod_id, site_idx, label, element, x, y, z FROM cod_atomic_sites LIMIT 5"):
    print(" ", r)

c.close()
