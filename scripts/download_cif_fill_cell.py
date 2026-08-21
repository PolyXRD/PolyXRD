"""Batch download CIF files from COD and fill missing cell parameters.

Downloads from https://www.crystallography.net/cod/{cod_id}.cif
Parses _cell_length_a/b/c and _cell_angle_alpha/beta/gamma.
Updates SQLite directly. Supports resume via progress log.

Usage:
  python scripts/download_cif_fill_cell.py [--workers 10] [--batch 500]
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQLITE_DB = ROOT / "cod_data" / "COD_inorganics.sqlite"
MISSING_IDS_FILE = ROOT / "cod_data" / "missing_cell_ids.json"
PROGRESS_FILE = ROOT / "cod_data" / "cif_download_progress.json"

# CIF cell parameter patterns
CIF_PATTERNS = {
    "cell_a":     r"_cell_length_a\s+([0-9.]+)",
    "cell_b":     r"_cell_length_b\s+([0-9.]+)",
    "cell_c":     r"_cell_length_c\s+([0-9.]+)",
    "cell_alpha":  r"_cell_angle_alpha\s+([0-9.]+)",
    "cell_beta":   r"_cell_angle_beta\s+([0-9.]+)",
    "cell_gamma":  r"_cell_angle_gamma\s+([0-9.]+)",
}
CIF_COMPILED = {k: re.compile(p) for k, p in CIF_PATTERNS.items()}

# Also parse formula and space group from CIF (bonus)
CIF_SG_RE = re.compile(r"_symmetry_space_group_name_H-M\s+'?([^'\n]+)'?")
CIF_FORMULA_RE = re.compile(r"_chemical_formula_sum\s+'?([^'\n]+)'?")


def download_cif(cod_id: int, timeout: int = 20, retries: int = 2) -> str | None:
    """Download CIF text from COD. Returns text or None."""
    url = f"https://www.crystallography.net/cod/{cod_id}.cif"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (PolyXRD/1.0; crystallography research)"
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # Not found, don't retry
            if attempt < retries:
                time.sleep(1)
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return None
    return None


def parse_cif_cell(text: str) -> dict[str, float]:
    """Parse cell parameters from CIF text."""
    result = {}
    for key, regex in CIF_COMPILED.items():
        m = regex.search(text)
        if m:
            try:
                v = float(m.group(1))
                if v > 0:
                    result[key] = v
            except ValueError:
                pass
    # Also try SG and formula
    m = CIF_SG_RE.search(text)
    if m:
        result["space_group"] = m.group(1).strip()
    m = CIF_FORMULA_RE.search(text)
    if m:
        result["formula"] = m.group(1).strip()
    return result


def load_progress() -> set[int]:
    """Load set of already-processed cod_ids."""
    if PROGRESS_FILE.exists():
        data = json.loads(PROGRESS_FILE.read_text())
        return set(data.get("done", []))
    return set()


def save_progress(done: set[int]) -> None:
    """Save progress for resume."""
    PROGRESS_FILE.write_text(json.dumps({"done": list(done)}))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=10,
                        help="Number of concurrent download threads")
    parser.add_argument("--batch", type=int, default=500,
                        help="SQLite commit batch size")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max cod_ids to process (0 = all)")
    args = parser.parse_args()

    t0 = time.time()

    # Load missing ids
    missing_ids = json.loads(MISSING_IDS_FILE.read_text())
    print(f"Total missing cell_a: {len(missing_ids)}")

    # Load progress (resume)
    done = load_progress()
    todo = [cid for cid in missing_ids if cid not in done]
    if args.limit > 0:
        todo = todo[:args.limit]
    print(f"Already done: {len(done)}, to process: {len(todo)}")
    if not todo:
        print("Nothing to do!")
        return

    # Open SQLite
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stats = {"downloaded": 0, "not_found": 0, "error": 0,
             "cell_filled": 0, "sg_filled": 0, "formula_filled": 0}
    pending_updates: list[dict] = []
    BATCH = args.batch

    def flush_updates():
        nonlocal pending_updates
        if not pending_updates:
            return
        for u in pending_updates:
            sets = []
            vals = []
            for k, v in u.items():
                if k == "cod_id":
                    continue
                sets.append(f"{k} = ?")
                vals.append(v)
            vals.append(u["cod_id"])
            cur.execute(
                f"UPDATE phases SET {', '.join(sets)} WHERE cod_id = ?", vals
            )
        conn.commit()
        pending_updates = []

    def process_one(cod_id: int) -> dict | None:
        text = download_cif(cod_id)
        if text is None:
            return None
        cell = parse_cif_cell(text)
        if not cell:
            return None
        cell["cod_id"] = cod_id
        return cell

    print(f"Downloading with {args.workers} workers...")
    processed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_one, cid): cid for cid in todo}
        for future in as_completed(futures):
            cid = futures[future]
            processed += 1
            try:
                result = future.result()
            except Exception:
                result = None

            if result is None:
                stats["not_found" if result is None else "error"] += 1
                done.add(cid)
            else:
                stats["downloaded"] += 1
                update = {"cod_id": cid}
                # Only fill fields that are currently missing/zero
                row = cur.execute(
                    "SELECT cell_a, cell_b, cell_c, cell_alpha, cell_beta, "
                    "cell_gamma, space_group FROM phases WHERE cod_id = ?",
                    (cid,)
                ).fetchone()
                if row:
                    for col in ("cell_a", "cell_b", "cell_c",
                                "cell_alpha", "cell_beta", "cell_gamma"):
                        col_key = col.replace("cell_", "cell_") if col.startswith("cell_") else col
                        # Map SQLite column to CIF key
                        cif_key = col  # same naming
                        if cif_key in result:
                            old = row[col]
                            if old is None or old == 0:
                                update[col] = result[cif_key]
                                stats["cell_filled"] += 1
                    # Bonus: fill SG if missing
                    if "space_group" in result:
                        old_sg = row["space_group"]
                        if not old_sg or not old_sg.strip():
                            update["space_group"] = result["space_group"]
                            stats["sg_filled"] += 1
                pending_updates.append(update)
                done.add(cid)

            if len(pending_updates) >= BATCH:
                flush_updates()
                save_progress(done)

            if processed % 500 == 0:
                elapsed = time.time() - t0
                rate = processed / elapsed
                remaining = len(todo) - processed
                eta = remaining / rate if rate > 0 else 0
                print(f"  [{processed}/{len(todo)}] "
                      f"downloaded={stats['downloaded']} "
                      f"not_found={stats['not_found']} "
                      f"cell_filled={stats['cell_filled']} "
                      f"rate={rate:.1f}/s "
                      f"eta={eta/60:.0f}min")

    flush_updates()
    save_progress(done)

    # Final coverage
    total = cur.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
    print(f"\n=== Final coverage ===")
    for col in ("cell_a", "cell_b", "cell_c",
                "cell_alpha", "cell_beta", "cell_gamma", "space_group"):
        n = cur.execute(
            f"SELECT COUNT(*) FROM phases WHERE {col} IS NOT NULL AND {col} != '' AND {col} != 0"
        ).fetchone()[0]
        pct = n / total * 100
        print(f"  {col:15s}: {n:>6d}/{total} ({pct:.2f}%)")

    conn.close()
    dt = time.time() - t0
    print(f"\nStats: {stats}")
    print(f"Done in {dt/60:.1f} min")


if __name__ == "__main__":
    main()
