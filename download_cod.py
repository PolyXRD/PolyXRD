"""Download COD CIF archive with resume support and progress display.
URL: http://www.crystallography.net/archives/cod-cifs-mysql.txz
"""
import os
import sys
import time
import urllib.request
from pathlib import Path

URL = "http://www.crystallography.net/archives/cod-cifs-mysql.txz"
DEST = Path(r"d:\TEMP\cod-cifs-mysql.txz")

# 999.99MB/s burst limit
PROGRESS_INTERVAL = 30  # seconds between progress prints


def get_remote_size() -> int:
    """Use HEAD to check remote size."""
    class HeadRequest(urllib.request.Request):
        def get_method(self): return "HEAD"
    try:
        req = HeadRequest(URL, headers={"User-Agent": "PolyXRD-COD-Downloader/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return int(resp.headers.get("Content-Length", 0))
    except Exception as e:
        print(f"  HEAD failed: {e}", flush=True)
        return 0


def download_resume() -> None:
    remote_size = get_remote_size()
    print(f"Remote size: {remote_size/1e9:.2f} GB ({remote_size} bytes)")

    existing = DEST.stat().st_size if DEST.exists() else 0
    if existing > 0:
        print(f"Existing partial file: {existing/1e9:.2f} GB", flush=True)
    if remote_size and existing >= remote_size:
        print("File already complete.")
        return

    req_headers = {"User-Agent": "PolyXRD-COD-Downloader/1.0"}
    if existing > 0:
        req_headers["Range"] = f"bytes={existing}-"

    req = urllib.request.Request(URL, headers=req_headers)

    mode = "ab" if existing > 0 else "wb"
    downloaded = existing
    last_tick = time.time()
    last_bytes = existing
    start = time.time()
    last_progress_print = 0.0
    block_size = 1024 * 1024  # 1 MB

    with urllib.request.urlopen(req, timeout=600) as resp:
        # Check partial content
        actual_start = 0
        if resp.status == 206:
            cr = resp.headers.get("Content-Range", "")
            print(f"  Resuming (206): {cr}", flush=True)
            actual_start = existing
        elif existing > 0 and resp.status == 200:
            print("  Server does not support resume, starting from scratch", flush=True)
            mode = "wb"
            downloaded = 0
            actual_start = 0

        total_bytes = remote_size if remote_size else downloaded + int(
            resp.headers.get("Content-Length", 0)
        )

        with open(DEST, mode) as fp:
            while True:
                chunk = resp.read(block_size)
                if not chunk:
                    break
                fp.write(chunk)
                downloaded += len(chunk)
                now = time.time()

                # Progress print: every 30 sec or 1% progress
                elapsed_total = now - start
                pct = (downloaded / total_bytes * 100) if total_bytes else 0
                delta_t = now - last_tick
                if delta_t >= 0.0:
                    rate = (downloaded - last_bytes) / (1024 * 1024) / max(delta_t, 1e-6)
                else:
                    rate = 0.0
                if (now - last_progress_print) >= PROGRESS_INTERVAL or (
                    pct and pct // 1 > (last_progress_print // 1 if last_progress_print else -1)
                ):
                    eta = ((total_bytes - downloaded) / (downloaded - actual_start) * (now - start)) \
                        if downloaded > actual_start and total_bytes else 0
                    eta_h = int(eta // 3600)
                    eta_m = int((eta % 3600) // 60)
                    print(
                        f"  [{time.strftime('%H:%M:%S')}] "
                        f"{downloaded/1e9:.2f}/{total_bytes/1e9:.2f} GB  "
                        f"{pct:5.1f}%  "
                        f"Speed: {rate:.2f} MB/s  "
                        f"ETA: {eta_h}h{eta_m:02d}m  "
                        f"Elapsed: {elapsed_total/60:.0f} min",
                        flush=True,
                    )
                    last_progress_print = now
                    last_tick = now
                    last_bytes = downloaded

    elapsed = time.time() - start
    final_size = DEST.stat().st_size
    speed = (final_size - actual_start) / (1024 * 1024) / max(elapsed, 1e-6)
    print(
        f"\nDownload finished. Size: {final_size/1e9:.2f} GB  "
        f"Elapsed: {elapsed/60:.1f} min  Avg speed: {speed:.2f} MB/s",
        flush=True,
    )


if __name__ == "__main__":
    print(f"URL: {URL}")
    print(f"DEST: {DEST}")
    # Check available free space on target drive
    drv = DEST.drive or "D:"
    try:
        import shutil
        total, used, free = shutil.disk_usage(drv)
        print(f"Drive {drv}: free={free/1e9:.1f} GB, total={total/1e9:.1f} GB")
        if free < 30 * 1024**3:  # need archive + extracted = >100GB
            print(f"  WARNING: Free space may be insufficient (< 30 GB free for archive alone)")
    except Exception as e:
        print(f"  Cannot check disk space: {e}")
    download_resume()
