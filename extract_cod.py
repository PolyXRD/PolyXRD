"""
Extract COD .txz / .tgz / .zip archive.

Usage:
    python extract_cod.py d:\\TEMP\\cod-cifs-mysql.txz d:\\TEMP\\cod
    python extract_cod.py path.txz          # 默认解压到同目录下 cod/

Supports:
  .txz / .tar.xz  (Python tarfile + lzma 原生)
  .tgz / .tar.gz  (Python tarfile 原生)
  .zip            (Python zipfile 原生)

Progress and resume behavior:
  - Skip files already extracted with matching size (fast for re-runs)
  - Print progress every N files / every M bytes
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile
import time
import zipfile
from pathlib import Path

PROGRESS_FILES_INTERVAL = 10000
PROGRESS_BYTES_INTERVAL = 500 * 1024 * 1024  # 500 MB


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} PB"


def extract_tar(archive: Path, dest: Path, mode: str) -> dict:
    """Extract tar.xz or tar.gz archive. mode = "r:xz" or "r:gz" or "r:*".

    Returns stats dict.
    """
    dest.mkdir(parents=True, exist_ok=True)
    total_files = 0
    total_bytes = 0
    skipped = 0
    last_print_files = 0
    last_print_bytes = 0
    start = time.time()
    last_tick = start

    with tarfile.open(archive, mode) as tf:
        # iterate members; safe_extract if member is inside dest
        while True:
            member = tf.next()
            if member is None:
                break
            if member.issym() or member.islnk():
                # skip symlinks to avoid escaping extraction directory
                continue
            # Sanitize: keep only members under cod/ or mysql/ top-level; reject abs path escapes
            if member.name.startswith("/") or ".." in member.name.split("/"):
                print(f"  [SKIP UNSAFE] {member.name}", flush=True)
                continue
            target = Path(dest) / member.name
            # Resolve and ensure still under dest
            try:
                target_resolved = target.resolve()
                dest_resolved = Path(dest).resolve()
                if str(target_resolved).rstrip("\\/") != str(dest_resolved).rstrip("\\/") and \
                   not str(target_resolved).startswith(str(dest_resolved) + os.sep):
                    print(f"  [SKIP ESCAPE] {member.name}", flush=True)
                    continue
            except Exception:
                continue

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            # regular file
            if target.exists():
                try:
                    st_size = target.stat().st_size
                    if st_size == member.size and st_size > 0:
                        skipped += 1
                        continue
                except OSError:
                    pass
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with tf.extractfile(member) as src:
                    if src is None:
                        continue
                    with open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                total_files += 1
                total_bytes += member.size or 0
            except Exception as e:
                print(f"  [ERROR on {member.name}]: {e}", flush=True)
                continue

            if (total_files - last_print_files) >= PROGRESS_FILES_INTERVAL or \
               (total_bytes - last_print_bytes) >= PROGRESS_BYTES_INTERVAL:
                now = time.time()
                dt = max(now - last_tick, 1e-6)
                speed = (total_bytes - last_print_bytes) / dt
                elapsed = now - start
                pct = f"{total_bytes/1e9:.2f} GB ({total_files} files)  speed {human(speed)}/s  elapsed {elapsed/60:.1f} min"
                print(f"  [{time.strftime('%H:%M:%S')}] {pct}", flush=True)
                last_print_files = total_files
                last_print_bytes = total_bytes
                last_tick = now

    elapsed = time.time() - start
    return {
        "type": "tar",
        "files": total_files,
        "bytes": total_bytes,
        "skipped": skipped,
        "elapsed_sec": round(elapsed, 1),
        "dest": str(dest),
    }


def extract_zip(archive: Path, dest: Path) -> dict:
    """Extract ZIP archive (progress-aware, resume via size-check)."""
    dest.mkdir(parents=True, exist_ok=True)
    total_files = 0
    total_bytes = 0
    skipped = 0
    last_print_files = 0
    last_print_bytes = 0
    start = time.time()
    last_tick = start

    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.startswith("/") or ".." in name.split("/"):
                print(f"  [SKIP UNSAFE] {name}", flush=True)
                continue
            target = Path(dest) / name
            try:
                r = target.resolve()
                dr = Path(dest).resolve()
                if str(r) != str(dr) and not str(r).startswith(str(dr) + os.sep):
                    print(f"  [SKIP ESCAPE] {name}", flush=True)
                    continue
            except Exception:
                continue
            if target.exists():
                try:
                    if target.stat().st_size == info.file_size and info.file_size > 0:
                        skipped += 1
                        continue
                except OSError:
                    pass
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info) as src:
                    with open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                total_files += 1
                total_bytes += info.file_size or 0
            except Exception as e:
                print(f"  [ERROR on {name}]: {e}", flush=True)
                continue

            if (total_files - last_print_files) >= PROGRESS_FILES_INTERVAL or \
               (total_bytes - last_print_bytes) >= PROGRESS_BYTES_INTERVAL:
                now = time.time()
                dt = max(now - last_tick, 1e-6)
                speed = (total_bytes - last_print_bytes) / dt
                elapsed = now - start
                print(f"  [{time.strftime('%H:%M:%S')}] {total_bytes/1e9:.2f} GB ({total_files} files)  "
                      f"speed {human(speed)}/s  elapsed {elapsed/60:.1f} min", flush=True)
                last_print_files = total_files
                last_print_bytes = total_bytes
                last_tick = now

    elapsed = time.time() - start
    return {
        "type": "zip",
        "files": total_files,
        "bytes": total_bytes,
        "skipped": skipped,
        "elapsed_sec": round(elapsed, 1),
        "dest": str(dest),
    }


def detect_mode(archive: Path) -> str:
    name = archive.name.lower()
    if name.endswith(".txz") or name.endswith(".tar.xz"):
        return "r:xz"
    if name.endswith(".tgz") or name.endswith(".tar.gz"):
        return "r:gz"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".tar"):
        return "r:"
    return "r:*"  # auto-detect


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract COD archive (.txz/.tgz/.zip)")
    ap.add_argument("archive", help="Archive file path")
    ap.add_argument("dest", nargs="?", default=None,
                    help="Destination directory (default: parent of archive / cod/)")
    args = ap.parse_args(argv)

    archive = Path(args.archive)
    if not archive.exists():
        print(f"ERROR: archive not found: {archive}", file=sys.stderr)
        return 2

    dest = Path(args.dest) if args.dest else (archive.parent / "cod")
    mode = detect_mode(archive)

    print(f"Archive : {archive} ({human(archive.stat().st_size)})")
    print(f"Type    : {mode}")
    print(f"Dest    : {dest}")
    print(f"Free    : ", end="", flush=True)
    try:
        free = shutil.disk_usage(str(dest)).free
        print(human(free))
    except Exception:
        print("(unknown)")
    print()
    t0 = time.time()
    if mode == "zip":
        stats = extract_zip(archive, dest)
    else:
        stats = extract_tar(archive, dest, mode)
    print()
    print("=== Extract finished ===")
    for k, v in stats.items():
        if k == "bytes":
            print(f"  {k:12s}: {human(v)}")
        else:
            print(f"  {k:12s}: {v}")
    print(f"  wall_time   : {time.time()-t0:.1f} sec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
