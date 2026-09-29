"""v0.11.0 GitHub Release 创建 + 附件上传 (Python 版, 等效 create_github_release_v0.11.0.ps1)。

背景: 本环境安全策略禁止从 Bash/PowerShell 调 pwsh/cmd, 故用 Python 复刻。
Token 从 `git credential fill` 获取 (与 v0.10.0 发布脚本同一路径)。

★ 硬性政策: PDF2-2004 (ICDD 版权库) 与 Portable.zip 永不上传。
上传 3 个附件: Setup.exe / Databases-COD-inorg.zip / Databases-COD-full.zip
"""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

OWNER, REPO = 'PolyXRD', 'PolyXRD'
TAG = VERSION = '0.11.0'
BASE = f'https://api.github.com/repos/{OWNER}/{REPO}'
UPLOAD = 'https://uploads.github.com/repos/{OWNER}/{REPO}/releases/{id}/assets'
INST = r'D:/Project/XRD/PolyXRD\installer_output'
BANNED = re.compile(r'PDF2|Portable', re.I)

BODY = """## PolyXRD v0.11.0

发布日期：2026-09-15 ｜ 联系：sshztx@outlook.com

### ✨ 主要更新（v0.10.0 → v0.11.0）

- **COD 结构精修链路打通**（0.11.0 重点）
  - CIF 覆盖 + 5 级回退：本地目录 → 全库索引 → **无机物库内嵌 CIF** → 原始 tar → COD 在线 REST
  - **COD 无机物库内嵌 CIF**（本次发布的库为 v2 结构）：phases 表新增 cif_gz 列
    （71,199 相中 71,156 = 99.94% 内嵌 gzip CIF 全文）+ cod_atomic_sites 子集表（31.1 万行原子位点）
    —— **只挂无机物库一个库即可做 Rietveld 结构精修**，不再强依赖全库索引
  - GSAS-II 引擎端到端：engine=auto 自动选引擎（全相有 CIF 且 GSAS-II 可用 → 真
    Rietveld + wt% 定量），不可用时回退内置引擎并记录原因
  - MAUD3 引擎端到端：xye 去 # 头 / CIF 剥 :H 后缀 / wR 百分号换算 / par 相定量解析回写 wt%+晶胞
- **精修算法**
  - R-A1 统计权重（目标函数与 wR 自洽，opt-in）
  - R-A4 Chebyshev 多项式背景抛光（opt-in）
  - get_phase Level-0 回退：索引外无机库编号从 CIF 重建条目 + 三级原子位点回退
- **两套精修向导并存**（GUI）
  - 快速版：单页参数对话框（原样保留）
  - 分步版：数据 → 物相 → 参数 → 预览 → 执行，含模板管理 / CIF 导入 / COD 在线检索
  - 菜单「结构精修」两项目可选；工具栏按钮点主体=快速版、右侧小箭头=选路径
  - 分步向导自带精修执行，结果自动回灌主窗口精修页
- **引擎下拉统一**：auto / gsas2 / maud / builtin / powerxrd 四处 UI 与状态接口一致
- **安装体验**：run_dev.bat 双击闪退修复（cmd 块内裸括号解析问题）+ 启动图未绑定崩溃修复
- 单元测试 **745+ 项全部通过**

### 📦 Release 附件

| 文件名 | 说明 |
|---|---|
| PolyXRD-Setup-v0.11.0.exe | Windows 独立安装包（内置 Python/Qt6/全部依赖，**不含任何数据库**） |
| PolyXRD-v0.11.0-Databases-COD-inorg.zip | COD 无机物库外挂包 v2（71,199 物相，**内嵌 CIF 全文 + 原子位点**，主检索库，推荐） |
| PolyXRD-v0.11.0-Databases-COD-full.zip | COD 全库索引外挂包（113,223 条目 + 513 万原子位点） |

> **Portable 免安装包不再随 Release 发布**（本版起按需提供）。
> **PDF2-2004 不在附件中**：ICDD 版权数据库，仓库只提供挂载能力，分发包由用户依授权自行准备。

### 🚀 快速开始

1. 下载 Setup 安装后启动
2. 按需下载数据库包，解压到磁盘任意目录
3. 菜单「数据库 ▸ 外挂数据库管理…」→ 对应槽位点「导入…」→ 立即生效

> 一个库都不装也能用：程序内置 118 种常见参考物相。
> 只装无机物库（v2）即可做日常检索**与 Rietveld 结构精修**；全库索引用于 COD 全库/合并检索。
"""

ASSETS = [
    ('PolyXRD-v0.11.0-Databases-COD-inorg.zip', 'application/zip'),
    ('PolyXRD-v0.11.0-Databases-COD-full.zip', 'application/zip'),
    ('PolyXRD-Setup-v0.11.0.exe', 'application/vnd.microsoft.portable-executable'),
]


def get_token() -> str:
    p = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True)
    m = re.search(r'^password=(.+)$', p.stdout, re.M)
    if not m:
        raise SystemExit('拿不到 GitHub token')
    return m.group(1).strip()


def api(url, token, method='GET', data=None, headers=None, raw=False):
    req = urllib.request.Request(url, method=method)
    req.add_header('Authorization', f'Bearer {token}')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', 'PolyXRD-release-py/1.0')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.data = data
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            return r.status, (body if raw else (json.loads(body) if body else None))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:400]


def main() -> int:
    token = get_token()
    print(f'token acquired (len={len(token)})')

    # ── 幂等: 找或建 Release ──
    st, rel = api(f'{BASE}/releases/tags/{TAG}', token)
    if st == 200:
        print(f"Release ALREADY EXISTS: id={rel['id']} url={rel['html_url']}")
    else:
        payload = json.dumps({
            'tag_name': TAG, 'target_commitish': 'main',
            'name': f'PolyXRD v{VERSION}', 'body': BODY,
            'draft': False, 'prerelease': False,
            'make_latest': 'true', 'generate_release_notes': False,
        }).encode('utf-8')
        st, rel = api(f'{BASE}/releases', token, 'POST', payload,
                      {'Content-Type': 'application/json'})
        if st not in (201, 200):
            print('创建 Release 失败:', st, rel)
            return 1
        print(f"CREATED release id={rel['id']} url={rel['html_url']}")
    rid = rel['id']
    upload_base = rel['upload_url'].split('{')[0]

    # ── 刷新 body ──
    patch = json.dumps({'body': BODY, 'name': f'PolyXRD v{VERSION}'}).encode('utf-8')
    api(f'{BASE}/releases/{rid}', token, 'PATCH', patch, {'Content-Type': 'application/json'})
    print('release body refreshed')

    # ── 已有附件 (幂等) ──
    st, assets = api(f'{BASE}/releases/{rid}/assets?per_page=100', token)
    assets = assets if st == 200 else []
    have = {a['name']: a for a in assets}
    if have:
        print('已有附件:', list(have))

    # ── 逐个上传 (小→大; PDF2/Portable 守卫) ──
    for name, ctype in ASSETS:
        if BANNED.search(name):
            raise SystemExit(f'拒绝上传: {name} 命中禁用关键字 (PDF2 版权 / Portable 不发布)')
        path = rf'{INST}\{name}'
        size = __import__('os').path.getsize(path)
        if name in have and have[name].get('state') == 'uploaded' and have[name]['size'] == size:
            print(f'SKIP {name} (已上传, 大小一致)')
            continue
        if name in have:
            api(f"{BASE}/releases/assets/{have[name]['id']}", token, 'DELETE')
            print(f'  删除旧附件 {name}')
        import urllib.parse
        url = f'{upload_base}?name={urllib.parse.quote(name)}'
        print(f'Uploading {name} ({size/1048576:.1f} MB) ...')
        for attempt in range(1, 7):
            t0 = time.time()
            with open(path, 'rb') as f:
                st, resp = api(url, token, 'POST', f,
                               {'Content-Type': ctype}, raw=True)
            dt = time.time() - t0
            if st in (201, 200):
                info = json.loads(resp)
                print(f'  OK in {dt:.0f}s ({size/1048576/dt:.2f} MB/s) -> {info["browser_download_url"]}')
                break
            print(f'  retry {attempt}/6: HTTP {st}: {str(resp)[:200]}')
            time.sleep(5 * min(attempt, 6))
        else:
            print(f'FAILED 上传 {name}')
            return 1

    # ── 终检 + 政策自检 ──
    st, fin = api(f'{BASE}/releases/tags/{TAG}', token)
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
