"""v0.15.0 Release 附件替换: 无机库包换瘦身索引式 (986.5 MiB → 134.1 MiB) + 刷新 SHA256。"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

CURL = r'C:\Windows\System32\curl.exe'
BASE = 'https://api.github.com/repos/PolyXRD/PolyXRD'
TAG = 'v0.15.0'
REPLACE = [
    ('installer_output/slim-index/PolyXRD-v0.15.0-Databases-COD-inorg-index.zip', 'application/zip'),
    ('installer_output/SHA256-v0.15.0.txt', 'text/plain'),
]
BANNED = re.compile(r'PDF2|Portable', re.I)


def get_token():
    p = subprocess.run(['git', 'credential', 'fill'],
                       input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True)
    m = re.search(r'^password=(.+)$', p.stdout, re.M)
    return m.group(1).strip()


def gh_json(url, token, method='GET', data=None, extra=None):
    cmd = [CURL, '-sS', '-X', method,
           '-H', f'Authorization: Bearer {token}',
           '-H', 'Accept: application/vnd.github+json',
           '-H', 'User-Agent: PolyXRD-release-py/1.3']
    for k, v in (extra or {}).items():
        cmd += ['-H', f'{k}: {v}']
    if data is not None:
        tmp = 'installer_output/_payload.json'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data)
        cmd += ['--data-binary', f'@{tmp}']
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    out = p.stdout.decode('utf-8', 'replace')
    if not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        print('[warn] 非 JSON:', out[:200])
        return None


def main():
    token = get_token()
    rel = gh_json(f'{BASE}/releases/tags/{TAG}', token)
    rid = rel['id']
    print('release id =', rid)
    assets = gh_json(f'{BASE}/releases/{rid}/assets?per_page=100', token) or []
    have = {a['name']: a for a in assets}
    upload_base = rel['upload_url'].split('{')[0]

    # ── 删除要替换的附件 ──
    targets = {os.path.basename(p) for p, _ in REPLACE}
    for name, a in have.items():
        if name in targets:
            gh_json(f"{BASE}/releases/assets/{a['id']}", token, 'DELETE')
            print('已删除旧附件:', name)

    # ── 上传 ──
    for path, ctype in REPLACE:
        if BANNED.search(path):
            raise SystemExit(f'拒绝上传: {path}')
        size = os.path.getsize(path)
        name = os.path.basename(path)
        url = f'{upload_base}?name={urllib.parse.quote(name)}'
        print(f'Uploading {name} ({size/1048576:.1f} MB) ...', flush=True)
        ok = False
        for attempt in range(1, 7):
            p = subprocess.run(
                [CURL, '-sS', '-X', 'POST', '--data-binary', f'@{path}',
                 '-H', f'Authorization: Bearer {token}',
                 '-H', f'Content-Type: {ctype}',
                 '-H', 'User-Agent: PolyXRD-release-py/1.3', url],
                capture_output=True, timeout=3600)
            try:
                info = json.loads(p.stdout.decode('utf-8', 'replace')) if p.stdout.strip() else {}
            except json.JSONDecodeError:
                info = {}
            if info.get('state') == 'uploaded':
                print(f'  OK -> {info["browser_download_url"]}', flush=True)
                ok = True
                break
            print(f'  retry {attempt}: {p.stdout[:150]} {p.stderr[:150]}', flush=True)
            time.sleep(5 * attempt)
        if not ok:
            raise SystemExit(f'上传失败: {name}')

    # ── 刷新正文 (瘦身式说明) ──
    import importlib.util
    spec = importlib.util.spec_from_file_location('rel', 'scripts/_create_release_v0150.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    gh_json(f'{BASE}/releases/{rid}', token, 'PATCH',
            json.dumps({'body': m.BODY, 'name': f'PolyXRD v{m.VERSION}'}),
            {'Content-Type': 'application/json'})
    print('body refreshed')

    fin = gh_json(f'{BASE}/releases/tags/{TAG}', token)
    print('=== FINAL ===')
    for a in fin['assets']:
        print(f"  {a['name']}  {a['size']/1048576:.1f} MB")
    leaked = [a['name'] for a in fin['assets'] if BANNED.search(a['name'])]
    if leaked:
        raise SystemExit(f'违禁附件: {leaked}')
    print('政策自检通过 ✔')


if __name__ == '__main__':
    main()
