"""v0.15.0 GitHub Release 创建 + 附件上传 (curl 流式上传, 沿用 v0.10/v0.11 验证过的路径)。

★ 硬性政策: PDF2-2004 (ICDD 版权库) 与 Portable.zip 永不上传。
上传 4 个附件: Setup.exe / Databases-COD-inorg-index.zip / Databases-COD-full-index.zip / SHA256
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

OWNER, REPO = 'PolyXRD', 'PolyXRD'
TAG = 'v0.15.0'
VERSION = '0.15.0'
BASE = f'https://api.github.com/repos/{OWNER}/{REPO}'
INST = r'D:/Project/XRD/PolyXRD\installer_output'
CURL = r'C:\Windows\System32\curl.exe'
BANNED = re.compile(r'PDF2|Portable', re.I)

BODY = """## PolyXRD v0.15.0

发布日期：2026-09-20 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v0.14.0 → v0.15.0）

- **M22 图谱交互**：横坐标自适应缩放，滚轮缩放 + 拖动平移
- **M23 物相列表重构**：勾选驱动（勾选即参与叠加显示与精修）；右键导出物相 CIF；勾选集合随项目持久化
- **M24 精修页布局重构**：残差细条与主图 X 轴同步、精修日志移左栏、已勾选物相区与外部程序容器独立分区
- **M25 外部精修程序集成**（本版重点）
  - **GSAS-II / MAUD / FullProf 三引擎一键启动**：自动探测安装路径，亦可手动指定（`external_tools.json` 持久化）；精修页外部程序面板带状态灯（绿=可用）
  - **FullProf (fp2k 8.20) 批处理精修端到端**：`.dat`/`.pcr` 自动生成、两遍标度自校准、fp2k SYMBOLIC 限位编号自动发现、保守模式 W 扫描兜底、`.sum`/`.out` 结果解析回写日志区
  - MAUD 检测修复：定位 `jdk/bin/java.exe`，GUI 启动路径解析正确（三引擎状态灯全绿）
- **中文使用手册**：`docs/manual/` 提供《使用手册》（15 页 PDF / 14 页 PPTX）与《快速入门》（6 页 PDF / 8 页 PPTX），含软件截图与 Rietveld 原理讲解
- 精修 GUI 决议：快速精修与多步精修向导保持两条独立路径

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v0.15.0.exe | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| PolyXRD-v0.15.0-Databases-COD-inorg-index.zip | COD 无机物库外挂包（**瘦身索引式**，71,199 相 + 31.1 万原子位点；CIF 由本地 `cod/cif` 目录或 COD REST 在线提供） |
| PolyXRD-v0.15.0-Databases-COD-full-index.zip | COD 全库索引外挂包 |
| SHA256-v0.15.0.txt | 发布产物 SHA-256 校验和 |

> **Portable 免安装包不随 Release 发布**（按需提供）。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装后启动（详细图文见《使用手册》/《快速入门》）
2. 按需下载数据库包，解压到磁盘任意目录
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位点「导入…」→ 立即生效

> 一个库都不装也能用：程序内置 118 种常见参考物相。
> 无机物库用于日常物相检索；全库索引用于 COD 全库/合并检索。
> GSAS-II / MAUD / FullProf 为可选外部引擎：在「数据库 ▸ 外部程序」中检测或指定路径后即可从精修页一键启动。
"""

ASSETS = [
    ('PolyXRD-Setup-v0.15.0.exe', 'application/vnd.microsoft.portable-executable'),
    ('PolyXRD-v0.15.0-Databases-COD-inorg-index.zip', 'application/zip'),
    ('PolyXRD-v0.15.0-Databases-COD-full-index.zip', 'application/zip'),
    ('SHA256-v0.15.0.txt', 'text/plain'),
]


def get_token() -> str:
    p = subprocess.run(['git', 'credential', 'fill'],
                       input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True)
    m = re.search(r'^password=(.+)$', p.stdout, re.M)
    if not m:
        raise SystemExit('拿不到 GitHub token')
    tok = m.group(1).strip()
    if '\r' in p.stdout:
        tok = tok.replace('\r', '')
    return tok


def gh_json(url, token, method='GET', data=None, extra=None):
    cmd = [CURL, '-sS', '-X', method,
           '-H', f'Authorization: Bearer {token}',
           '-H', 'Accept: application/vnd.github+json',
           '-H', 'User-Agent: PolyXRD-release-py/1.2']
    for k, v in (extra or {}).items():
        cmd += ['-H', f'{k}: {v}']
    if data is not None:
        # 中文 payload 经命令行参数传给 curl 会静默失败, 必须落盘用 @file 传递
        tmp = os.path.join(INST, '_payload.json')
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data)
        cmd += ['--data-binary', f'@{tmp}']
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    # text=True 会用 cp936 解码含中文/emoji 的 UTF-8 响应 → 静默失败, 必须 bytes + utf-8
    out = p.stdout.decode('utf-8', 'replace')
    err = p.stderr.decode('utf-8', 'replace')
    if not out.strip():
        if data is not None:
            print('  [warn] 空响应 stderr:', err[:200])
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        print('  [warn] 非 JSON 响应:', out[:300])
        return None


def main() -> int:
    token = get_token()
    print(f'token acquired (len={len(token)})')

    # ── 幂等: 找或建 Release ──
    rel = gh_json(f'{BASE}/releases/tags/{TAG}', token)
    if rel and 'id' in rel:
        print(f"Release ALREADY EXISTS: id={rel['id']} url={rel['html_url']}")
    else:
        payload = json.dumps({
            'tag_name': TAG, 'target_commitish': 'main',
            'name': f'PolyXRD v{VERSION}', 'body': BODY,
            'draft': False, 'prerelease': False,
            'make_latest': 'true', 'generate_release_notes': False,
        })
        rel = gh_json(f'{BASE}/releases', token, 'POST', payload,
                      {'Content-Type': 'application/json'})
        if not rel or 'id' not in rel:
            print('创建 Release 失败:', rel)
            return 1
        print(f"CREATED release id={rel['id']} url={rel['html_url']}")
    rid = rel['id']
    upload_base = rel['upload_url'].split('{')[0]

    # ── 刷新 body ──
    patch = json.dumps({'body': BODY, 'name': f'PolyXRD v{VERSION}'})
    gh_json(f'{BASE}/releases/{rid}', token, 'PATCH', patch,
            {'Content-Type': 'application/json'})
    print('release body refreshed')

    # ── 已有附件 (幂等) ──
    assets = gh_json(f'{BASE}/releases/{rid}/assets?per_page=100', token) or []
    have = {a['name']: a for a in assets}
    if have:
        print('已有附件:', list(have))

    # ── 逐个上传 (小→大; PDF2/Portable 守卫) ──
    for name, ctype in sorted(ASSETS, key=lambda x: os.path.getsize(os.path.join(INST, x[0]))):
        if BANNED.search(name):
            raise SystemExit(f'拒绝上传: {name} 命中禁用关键字 (PDF2 版权 / Portable 不发布)')
        path = os.path.join(INST, name)
        if not os.path.exists(path):
            raise SystemExit(f'附件不存在: {path}')
        size = os.path.getsize(path)
        if name in have and have[name].get('state') == 'uploaded' and have[name]['size'] == size:
            print(f'SKIP {name} (已上传, 大小一致)')
            continue
        if name in have:
            gh_json(f"{BASE}/releases/assets/{have[name]['id']}", token, 'DELETE')
            print(f'  删除旧附件 {name}')
        url = f'{upload_base}?name={urllib.parse.quote(name)}'
        print(f'Uploading {name} ({size/1048576:.1f} MB) ...')
        ok = False
        for attempt in range(1, 7):
            t0 = time.time()
            p = subprocess.run(
                [CURL, '-sS', '-X', 'POST', '--data-binary', f'@{path}',
                 '-H', f'Authorization: Bearer {token}',
                 '-H', f'Content-Type: {ctype}',
                 '-H', 'User-Agent: PolyXRD-release-py/1.2', url],
                capture_output=True, text=True, timeout=3600)
            dt = time.time() - t0
            try:
                info = json.loads(p.stdout) if p.stdout.strip() else {}
            except json.JSONDecodeError:
                info = {}
            if info.get('state') == 'uploaded':
                print(f'  OK in {dt:.0f}s ({size/1048576/dt:.2f} MB/s) -> {info["browser_download_url"]}')
                ok = True
                break
            print(f'  retry {attempt}/6: {p.stdout[:200]} {p.stderr[:200]}')
            time.sleep(5 * min(attempt, 6))
        if not ok:
            print(f'FAILED 上传 {name}')
            return 1

    # ── 终检 + 政策自检 ──
    fin = gh_json(f'{BASE}/releases/tags/{TAG}', token)
    print('=== FINAL RELEASE INFO ===')
    print('Release :', fin['html_url'])
    for a in fin['assets']:
        print(f"  {a['name']}  {a['size']/1048576:.1f} MB  -> {a['browser_download_url']}")
    leaked = [a['name'] for a in fin['assets'] if BANNED.search(a['name'])]
    if leaked:
        raise SystemExit(f'严重: Release 上出现违禁附件 -> {leaked}')
    print('政策自检: Release 附件中无 PDF2 / Portable ✔')
    print('=== DONE ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
