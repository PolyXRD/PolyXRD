"""Second pass: download CIF for phases missing cell_b (but have cell_a).

The first pass only downloaded CIFs for phases missing cell_a.
Now we need to handle phases that have cell_a but are missing cell_b/c/angles.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQLITE_DB = ROOT / "cod_data" / "COD_inorganics.sqlite"
PROGRESS_FILE = ROOT / "cod_data" / "cif_download_pass2_progress.json"

CIF_PATTERNS = {
    "cell_a":     re.compile(r"_cell_length_a\s+([0-9.]+)"),
    "cell_b":     re.compile(r"_cell_length_b\s+([0-9.]+)"),
    "cell_c":     re.compile(r"_cell_length_c\s+([0-9.]+)"),
    "cell_alpha":  re.compile(r"_cell_angle_alpha\s+([0-9.]+)"),
    "cell_beta":   re.compile(r"_cell_angle_beta\s+([0-9.]+)"),
    "cell_gamma":  re.compile(r"_cell_angle_gamma\s+([0-9.]+)"),
}


def download_cif(cod_id: int, timeout: int = 20, retries: int = 2) -> str | None:
    url = f"https://www.crystallography.net/cod/{cod_id}.cif"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (PolyXRD/1.0)"
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
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
    result = {}
    for key, regex in CIF_PATTERNS.items():
        m = regex.search(text)
        if m:
            try:
                v = float(m.group(1))
                if v > 0:
                    result[key] = v
            except ValueError:
                pass
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args()

    t0 = time.time()

    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM phases").fetchone()[0]

    # Find phases with cell_a > 0 but cell_b = NULL or 0
    rows = cur.execute(
        "SELECT cod_id FROM phases WHERE cell_a > 0 "
        "AND (cell_b IS NULL OR cell_b = 0)"
    ).fetchall()
    missing_b_ids = [r["cod_id"] for r in rows]
    print(f"Phases with cell_a but missing cell_b: {len(missing_b_ids)}")

    if not missing_b_ids:
        print("Nothing to do!")
        return

    # Load progress
    done = set()
    if PROGRESS_FILE.exists():
        done = set(json.loads(PROGRESS_FILE.read_text()).get("done", []))
    todo = [cid for cid in missing_b_ids if cid not in done]
    print(f"Already done: {len(done)}, to process: {len(todo)}")

    if not todo:
        print("All done!")
        return

    stats = {"downloaded": 0, "not_found": 0, "filled": 0}
    pending_updates = []
    BATCH = args.batch

    def flush():
        nonlocal pending_updates
        if not pending_updates:
            return
        for u in pending_updates:
            sets = [f"{k} = ?" for k in u if k != "cod_id"]
            vals = [u[k] for k in u if k != "cod_id"]
            vals.append(u["cod_id"])
            cur.execute(
                f"UPDATE phases SET {', '.join(sets)} WHERE cod_id = ?", vals
            )
        conn.commit()
        pending_updates = []

    def process_one(cod_id: int):
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
                row = cur.execute(
                    "SELECT cell_b, cell_c, cell_alpha, cell_beta, cell_gamma "
                    "FROM phases WHERE cod_id = ?", (cid,)
                ).fetchone()
                if row:
                    for col in ("cell_b", "cell_c", "cell_alpha",
                                "cell_beta", "cell_gamma"):
                        if col in result:
                            old = row[col]
                            if old is None or old == 0:
                                update[col] = result[col]
                                stats["filled"] += 1
                pending_updates.append(update)
                done.add(cid)

            if len(pending_updates) >= BATCH:
                flush()
                json.dump({"done": list(done)},
                          open(PROGRESS_FILE, "w"))

            if processed % 500 == 0:
                elapsed = time.time() - t0
                rate = processed / elapsed
                remaining = len(todo) - processed
                eta = remaining / rate if rate > 0 else 0
                print(f"  [{processed}/{len(todo)}] "
                      f"dl={stats['downloaded']} "
                      f"filled={stats['filled']} "
                      f"rate={rate:.1f}/s "
                      f"eta={eta/60:.0f}min")

    flush()
    json.dump({"done": list(done)}, open(PROGRESS_FILE, "w"))

    # Final coverage
    print("\n=== Final coverage ===")
    for col in ("cell_a", "cell_b", "cell_c",
                "cell_alpha", "cell_beta", "cell_gamma", "space_group"):
        if col == "space_group":
            n = cur.execute(
                f"SELECT COUNT(*) FROM phases WHERE {col} IS NOT NULL AND {col} != ''"
            ).fetchone()[0]
        else:
            n = cur.execute(
                f"SELECT COUNT(*) FROM phases WHERE {col} IS NOT NULL AND {col} > 0"
            ).fetchone()[0]
        print(f"  {col:15s}: {n}/{total} ({n/total*100:.2f}%)")

    n_full = cur.execute(
        "SELECT COUNT(*) FROM phases WHERE "
        "cell_a > 0 AND cell_b > 0 AND cell_c > 0 "
        "AND cell_alpha > 0 AND cell_beta > 0 AND cell_gamma > 0 "
        "AND space_group IS NOT NULL AND TRIM(space_group) != '' "
        "AND n_peaks > 0"
    ).fetchone()[0]
    print(f"\n  完整模型(6参+SG+峰): {n_full}/{total} ({n_full/total*100:.2f}%)")

    conn.close()
    dt = time.time() - t0
    print(f"\nDone in {dt/60:.1f} min")


if __name__ == "__main__":
    main()
