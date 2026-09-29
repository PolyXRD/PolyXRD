"""v0.11.0 Release 附件上传 (curl 版)。

教训: urllib 用文件对象作 POST data 时 Content-Length 处理不可靠,
35 分钟传不出一个附件。改用 v0.10.0 验证过的 curl.exe 流式上传。
Release 本体 (id 388914987) 已存在且已挂到 v0.11.0, 本脚本只管附件。
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

OWNER, REPO = 'PolyXRD', 'PolyXRD'
TAG = 'v0.11.0'
BASE = f'https://api.github.com/repos/{OWNER}/{REPO}'
INST = r'D:/Project/XRD/PolyXRD\installer_output'
CURL = r'C:\Windows\System32\curl.exe'
BANNED = re.compile(r'PDF2|Portable', re.I)

ASSETS = [
    ('PolyXRD-v0.11.0-Databases-COD-full.zip', 'application/zip'),
    ('PolyXRD-v0.11.0-Databases-COD-inorg.zip', 'application/zip'),
    ('PolyXRD-Setup-v0.11.0.exe', 'application/vnd.microsoft.portable-executable'),
]


def get_token() -> str:
    p = subprocess.run(['git', 'credential', 'fill'],
                       input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True)
    m = re.search(r'^password=(.+)$', p.stdout, re.M)
    if not m:
        raise SystemExit('拿不到 GitHub token')
    return m.group(1).strip()


def gh(url, token, method='GET'):
    p = subprocess.run(
        [CURL, '-sS', '-X', method,
         '-H', f'Authorization: Bearer {token}',
         '-H', 'Accept: application/vnd.github+json',
         '-H', 'User-Agent: PolyXRD-release-py/1.1', url],
        capture_output=True, text=True, timeout=120)
    try:
        return json.loads(p.stdout) if p.stdout.strip() else None
    except json.JSONDecodeError:
        print('  [warn] 非 JSON 响应:', p.stdout[:200], p.stderr[:200])
        return None


def main() -> int:
    token = get_token()
    print(f'token acquired (len={len(token)})')

    rel = gh(f'{BASE}/releases/tags/{TAG}', token)
    if not rel or 'id' not in rel:
        raise SystemExit(f'找不到 tag={TAG} 的 Release')
    rid = rel['id']
    print(f"Release id={rid} tag={rel['tag_name']} url={rel['html_url']}")
    upload_base = rel['upload_url'].split('{')[0]

    assets = gh(f'{BASE}/releases/{rid}/assets?per_page=100', token) or []
    have = {a['name']: a for a in assets}
    if have:
        print('已有附件:', {k: (v['size'], v['state']) for k, v in have.items()})

    for name, ctype in ASSETS:
        if BANNED.search(name):
            raise SystemExit(f'拒绝上传: {name} 命中禁用关键字')
        path = os.path.join(INST, name)
        size = os.path.getsize(path)
        if name in have and have[name].get('state') == 'uploaded' and have[name]['size'] == size:
            print(f'SKIP {name} (已上传, 大小一致)')
            continue
        if name in have:
            gh(f"{BASE}/releases/assets/{have[name]['id']}", token, 'DELETE')
            print(f'  已删除旧附件 {name}')

        url = f'{upload_base}?name={urllib.parse.quote(name)}'
        mb = size / 1048576
        print(f'Uploading {name} ({mb:.1f} MB) ...', flush=True)
        ok = False
        for attempt in range(1, 7):
            t0 = time.time()
            p = subprocess.run(
                [CURL, '-sS', '-X', 'POST',
                 '-H', f'Authorization: Bearer {token}',
                 '-H', 'Accept: application/vnd.github+json',
                 '-H', f'Content-Type: {ctype}',
                 '-H', 'User-Agent: PolyXRD-upload-py/1.0',
                 '--data-binary', f'@{path}', url],
                capture_output=True, text=True, timeout=7200)
            dt = time.time() - t0
            try:
                info = json.loads(p.stdout)
            except json.JSONDecodeError:
                info = {}
            if p.returncode == 0 and info.get('browser_download_url'):
                print(f'  OK in {dt:.0f}s ({mb/dt:.2f} MB/s) -> {info["browser_download_url"]}', flush=True)
                ok = True
                break
            print(f'  retry {attempt}/6 curl exit={p.returncode}: '
                  f'{(p.stderr or p.stdout)[:200]}', flush=True)
            time.sleep(5 * min(attempt, 6))
        if not ok:
            print(f'FAILED 上传 {name}')
            return 1

    # ── 终检 + 政策自检 ──
    fin = gh(f'{BASE}/releases/tags/{TAG}', token)
    print('=== FINAL RELEASE INFO ===')
    print('Release :', fin['html_url'])
    for a in fin['assets']:
        print(f"  {a['name']}  {a['size']/1048576:.1f} MB  state={a['state']}")
    leaked = [a['name'] for a in fin['assets'] if BANNED.search(a['name'])]
    if leaked:
        raise SystemExit(f'严重: Release 上出现违禁附件 -> {leaked}')
    print('政策自检: Release 附件中无 PDF2 / Portable ✔')
    print('=== DONE ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
