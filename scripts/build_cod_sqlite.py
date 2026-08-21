"""
Final COD user_database.mtu parser.

Per phase record (variable length, ~3.2-5.4 KB):
  [0]  7 ASCII digits    COD ID (e.g. "1000005")
  [7]  1 byte            flag (e.g. 0x07)
  [8]  1 byte            flag (e.g. 0x00)
  [9]  7 ASCII digits    COD ID (repeat)
  [16] uint16            formula length
  [18] <len> bytes       formula text
  ...   ...              other fields, padding, flags
  [~50] uint16           SG length, then SG text
  ...   ...              binary atom-coordinate region (contains 'zD'/'zC' patterns)
  ...   ...              d-I peaks region: pairs of (d float32, I float32),
                          d in [0.5, 30], I in [0, 2000], d strictly decreasing
  ...   ...              cell parameters region: 6 consecutive float32,
                          a,b,c in [3, 60], alpha,beta,gamma in [60, 120]
  ...   ...              tail binary

Strategy:
  1) Scan for COD-ID markers -> recover phase boundaries (offset_i, offset_{i+1}).
  2) For each phase record, extract formula / SG by length-prefixed-string scan.
  3) Scan the binary region between COD ID and next COD ID for:
        a) Cell parameters: search for 6 consecutive float32 in valid ranges,
           in order (a, b, c, alpha, beta, gamma), within +/- tolerance.
        b) d-I peaks: longest run of float32 pairs (d, I) with
           d in [0.5, 30] and monotonically non-increasing,
           I in [0, 2000], at least 3 pairs, ending where d stops decreasing.
  4) Write everything to SQLite.

This is reverse-engineered, so we accept some phases will fail to parse
(no formula found, no d-I region). We log them but continue.
"""

from __future__ import annotations

import re
import sqlite3
import struct
import sys
import time
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(__file__).resolve().parent.parent / "cod_data" / "match_inorganics"
USER_DB = DATA_DIR / "user_database.mtu"
OUT_DB = DATA_DIR.parent / "COD_inorganics.sqlite"

COD_ID_RE = re.compile(rb"(?<![0-9])([0-9]{7})(?![0-9])")
SG_RE = re.compile(rb"\b([PAFBCIR][0-9A-Za-z /\-\._]{2,40})\b")


def find_phase_boundaries(buf: bytes, *, min_gap: int = 64) -> list[tuple[int, int]]:
    """Return [(offset, cod_id)] of first COD-ID marker per phase."""
    starts: list[tuple[int, int]] = []
    prev_off = -10000
    for m in COD_ID_RE.finditer(buf):
        cod_id = int(m.group(1))
        if not (1000000 <= cod_id <= 9999999):
            continue
        if m.start() - prev_off > min_gap:
            starts.append((m.start(), cod_id))
        prev_off = m.start()
    return starts


def parse_string_at(buf: bytes, off: int) -> tuple[str, int] | None:
    """If buf[off:off+2] is a uint16 length N and buf[off+2:off+2+N] is
    printable ASCII, return (string, end_offset). Else None.
    """
    if off + 2 > len(buf):
        return None
    n = struct.unpack_from("<H", buf, off)[0]
    if n == 0 or n > 200 or off + 2 + n > len(buf):
        return None
    raw = buf[off + 2: off + 2 + n]
    if not all(32 <= b <= 126 or b == 0 for b in raw):
        return None
    text = raw.decode("latin-1", errors="replace").rstrip("\x00")
    if not text:
        return None
    return text, off + 2 + n


def extract_formula_and_sg(chunk: bytes) -> tuple[str | None, str | None]:
    """Find formula and space group in the first ~200 bytes of the chunk."""
    formula = None
    sg = None
    # Scan first 200 bytes for length-prefixed strings
    for off in range(8, min(200, len(chunk) - 4)):
        res = parse_string_at(chunk, off)
        if not res:
            continue
        text, end = res
        # Heuristic: formula has uppercase element symbols + digits + spaces,
        # contains at least one digit, no lowercase-only words.
        is_formula = (
            formula is None
            and 3 <= len(text) <= 50
            and re.fullmatch(r"[A-Z][A-Za-z0-9 .]*", text) is not None
            and any(c.isdigit() for c in text)
            and not text.isdigit()
        )
        if is_formula:
            formula = text
            continue  # do not also classify this string as SG
        # Heuristic: SG starts with P/F/I/C/A/R + space + digits/symbols.
        # Reject strings that look like chemical formulas (contain element
        # symbols like "Sr", "Fe" — i.e. uppercase+lowercase pairs), because
        # those are formulas, not space groups.
        if sg is None and 3 <= len(text) <= 30:
            if re.fullmatch(r"[PAFBCIR][0-9A-Za-z _/\-]+", text):
                if " " in text:
                    # Reject if it contains element-symbol patterns (e.g. Sr, Fe, Cr)
                    # which indicate a formula, not a space group.
                    if re.search(r"[A-Z][a-z]", text):
                        continue
                    sg = text
        if formula and sg:
            break
    return formula, sg


def extract_cell_params(chunk: bytes) -> tuple[float, float, float, float, float, float] | None:
    """Search the chunk for 6 consecutive float32 LE values that look like
    a, b, c, alpha, beta, gamma.
    """
    n = len(chunk) // 4
    best: tuple[int, list[float]] | None = None
    # Sliding window of 6 float32 = 24 bytes
    for off in range(0, len(chunk) - 24, 4):
        try:
            v = struct.unpack_from("<6f", chunk, off)
        except struct.error:
            continue
        a, b, c, al, be, ga = v
        # Cell lengths 3-60 Å, angles 60-120° (allow monoclinic)
        if not (3.0 <= a <= 60.0 and 3.0 <= b <= 60.0 and 3.0 <= c <= 60.0):
            continue
        if not (60.0 <= al <= 120.0 and 60.0 <= be <= 120.0 and 60.0 <= ga <= 120.0):
            continue
        # Some phases have α=β=γ=90 (orthorhombic/tetragonal/cubic) -> common pattern
        # Score: prefer cases where at least one of α/β/γ is exactly 90
        score = 0
        for ang in (al, be, ga):
            if abs(ang - 90.0) < 0.5:
                score += 1
        # Prefer cases where length values are reasonable (not absurd)
        if 1.0 <= a / b <= 10.0 and 1.0 <= b / c <= 10.0 and 1.0 <= a / c <= 10.0:
            score += 1
        if best is None or score > best[0]:
            best = (score, list(v))
    if best is None:
        return None
    a, b, c, al, be, ga = best[1]
    return (a, b, c, al, be, ga)


def _scan_run_at_align(chunk: bytes, align: int, *,
                       d_lo: float = 0.3, d_hi: float = 30.0,
                       i_lo: float = 0.0, i_hi: float = 10000.0,
                       max_increase: float = 0.5) -> list[tuple[float, float]]:
    """Scan a chunk at a fixed byte alignment (0..7) for the longest run of
    (float32 d, float32 I) pairs where d is in [d_lo, d_hi], I in [i_lo, i_hi],
    and d is non-increasing (allowing small increases up to max_increase).
    Returns the longest valid run.
    """
    best_run: list[tuple[float, float]] = []
    cur_run: list[tuple[float, float]] = []
    prev_d: float | None = None
    # Walk in 8-byte steps starting at the chosen alignment.
    off = align
    while off + 8 <= len(chunk):
        try:
            d, i = struct.unpack_from("<2f", chunk, off)
        except struct.error:
            break
        # Validity check
        if not (d_lo <= d <= d_hi and i_lo <= i <= i_hi):
            if len(cur_run) > len(best_run):
                best_run = cur_run
            cur_run = []
            prev_d = None
            off += 8
            continue
        # Monotonicity: d must be non-increasing (allow small noise increase)
        if prev_d is not None and d > prev_d + max_increase:
            if len(cur_run) > len(best_run):
                best_run = cur_run
            cur_run = []
            prev_d = None
            # do not continue — restart run with this pair as first
        cur_run.append((d, i))
        prev_d = d
        off += 8
    if len(cur_run) > len(best_run):
        best_run = cur_run
    return best_run


def extract_d_peaks(chunk: bytes, *, min_pairs: int = 5) -> list[tuple[float, float]]:
    """Find the longest run of float32 (d, I) pairs.

    The d-I region in user_database.mtu is NOT guaranteed to be 8-byte aligned
    relative to the chunk start (the header before it has variable length).
    So we try all 8 alignments (0..7) and return the longest valid run.

    Validity:
      d in [0.3, 30.0]  (extended low end for high-angle peaks)
      I in [0, 10000]   (relaxed: some phases store I as 0..100, others 0..1000)
      d non-increasing (allow noise up to 0.5 Å)
    """
    best_overall: list[tuple[float, float]] = []
    for align in range(8):
        run = _scan_run_at_align(chunk, align)
        if len(run) > len(best_overall):
            best_overall = run
    return best_overall if len(best_overall) >= min_pairs else []


def parse_one_phase(buf: bytes, start: int, end: int, cod_id: int) -> dict:
    chunk = buf[start:end]
    formula, sg = extract_formula_and_sg(chunk)
    cell = extract_cell_params(chunk)
    peaks = extract_d_peaks(chunk, min_pairs=5)
    return {
        "cod_id": cod_id,
        "formula": formula,
        "space_group": sg,
        "cell_a": cell[0] if cell else None,
        "cell_b": cell[1] if cell else None,
        "cell_c": cell[2] if cell else None,
        "cell_alpha": cell[3] if cell else None,
        "cell_beta": cell[4] if cell else None,
        "cell_gamma": cell[5] if cell else None,
        "n_peaks": len(peaks),
        "peaks_d": " ".join(f"{d:.4f}" for d, _ in peaks),
        "peaks_i": " ".join(f"{i:.1f}" for _, i in peaks),
        "record_offset": start,
        "record_size": end - start,
    }


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS phases;
        DROP TABLE IF EXISTS peaks;
        DROP TABLE IF EXISTS parse_errors;
        CREATE TABLE phases (
            cod_id              INTEGER PRIMARY KEY,
            formula             TEXT,
            space_group         TEXT,
            cell_a              REAL,
            cell_b              REAL,
            cell_c              REAL,
            cell_alpha          REAL,
            cell_beta           REAL,
            cell_gamma          REAL,
            n_peaks             INTEGER,
            peaks_d             TEXT,
            peaks_i             TEXT,
            record_offset       INTEGER,
            record_size         INTEGER
        );
        CREATE INDEX idx_phases_formula ON phases(formula);
        CREATE INDEX idx_phases_sg ON phases(space_group);
        CREATE TABLE parse_errors (
            cod_id      INTEGER PRIMARY KEY,
            reason      TEXT
        );
    """)
    conn.commit()


def main() -> int:
    MB = 1024 * 1024
    print(f"Loading {USER_DB} ({USER_DB.stat().st_size/MB:.1f} MB)...")
    with open(USER_DB, "rb") as fh:
        data = fh.read()

    assert data[:20] == bytes.fromhex('4d41544348215f555345525f4441544142415345')
    n_entries_header = struct.unpack_from("<I", data, 22)[0]
    print(f"  magic OK, n_entries_header={n_entries_header}")

    body = data[256:]
    starts = find_phase_boundaries(body, min_gap=64)
    print(f"  detected {len(starts)} phase starts")
    if not starts:
        print("ERROR: no phase starts detected")
        return 1

    # Open SQLite
    if OUT_DB.exists():
        OUT_DB.unlink()
    conn = sqlite3.connect(OUT_DB)
    init_db(conn)

    n_ok = 0
    n_no_formula = 0
    n_no_peaks = 0
    n_no_cell = 0
    t0 = time.time()
    batch: list[tuple] = []
    err_batch: list[tuple] = []
    BATCH = 500

    for i in range(len(starts)):
        start, cod_id = starts[i]
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        try:
            phase = parse_one_phase(body, start, end, cod_id)
        except Exception as e:
            err_batch.append((cod_id, f"exception: {e}"))
            if len(err_batch) >= BATCH:
                conn.executemany("INSERT OR REPLACE INTO parse_errors VALUES (?,?)", err_batch)
                err_batch.clear()
            continue
        # Classify: cell params are OPTIONAL (many phases store them in the
        # separate cella/b/c/al/be/ga.mti index files, not in user_database.mtu).
        # We accept a phase as long as it has a formula AND d-I peaks.
        if not phase["formula"]:
            n_no_formula += 1
            err_batch.append((cod_id, "no formula"))
        elif not phase["peaks_d"]:
            n_no_peaks += 1
            err_batch.append((cod_id, "no d-I peaks"))
        else:
            n_ok += 1
            if phase["cell_a"] is None:
                n_no_cell += 1  # stat only, still inserted
            batch.append((
                phase["cod_id"], phase["formula"], phase["space_group"],
                phase["cell_a"], phase["cell_b"], phase["cell_c"],
                phase["cell_alpha"], phase["cell_beta"], phase["cell_gamma"],
                phase["n_peaks"], phase["peaks_d"], phase["peaks_i"],
                phase["record_offset"], phase["record_size"],
            ))
        if len(batch) >= BATCH:
            conn.executemany(
                "INSERT OR REPLACE INTO phases VALUES ("
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
            )
            conn.executemany("INSERT OR REPLACE INTO parse_errors VALUES (?,?)", err_batch)
            conn.commit()
            batch.clear()
            err_batch.clear()
        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(starts) - i - 1) / rate
            print(f"  [{i+1}/{len(starts)}] ok={n_ok} no_formula={n_no_formula} "
                  f"no_peaks={n_no_peaks} no_cell={n_no_cell} "
                  f"rate={rate:.0f}/s eta={eta:.0f}s")

    # Flush remaining
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO phases VALUES ("
            "?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
        )
    if err_batch:
        conn.executemany("INSERT OR REPLACE INTO parse_errors VALUES (?,?)", err_batch)
    conn.commit()

    # Stats
    cur = conn.execute("SELECT COUNT(*) FROM phases")
    n_in_db = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM parse_errors")
    n_err = cur.fetchone()[0]
    cur = conn.execute("SELECT MIN(cod_id), MAX(cod_id), AVG(n_peaks) FROM phases")
    mn, mx, avg_pk = cur.fetchone()

    print()
    print("=" * 70)
    print(f"  total phases detected : {len(starts)}")
    print(f"  parsed successfully   : {n_ok}")
    print(f"  failed (no formula)  : {n_no_formula}")
    print(f"  failed (no peaks)   : {n_no_peaks}")
    print(f"  failed (no cell)     : {n_no_cell}")
    print(f"  in DB (phases)       : {n_in_db}")
    print(f"  in DB (errors)       : {n_err}")
    print(f"  cod_id range         : {mn}..{mx}")
    print(f"  avg peaks per phase  : {avg_pk:.1f}")
    print(f"  elapsed              : {time.time()-t0:.1f} s")
    print(f"  SQLite written to    : {OUT_DB}")

    # Sample 5 phases
    print()
    print("--- sample 5 phases from SQLite ---")
    cur = conn.execute("SELECT cod_id, formula, space_group, cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, n_peaks FROM phases LIMIT 5")
    for row in cur:
        cod_id, formula, sg, a, b, c, al, be, ga, npk = row
        print(f"  COD {cod_id}: {formula}  SG={sg}  cell=({a:.3f},{b:.3f},{c:.3f},{al:.1f},{be:.1f},{ga:.1f})  peaks={npk}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
