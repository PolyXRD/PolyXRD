"""PolyXRD 构建后置步骤 (由 build.bat 调用)。

把 build.bat 里原本「多行内联 python -c "..." / powershell @'...'@」片段抽出来,
避免 .bat 经 Git Bash 启动时多行双引号被 cmd 误解析 (表现为
'import' is not recognized / pat was unexpected 等致命语法错误, 导致整条 .bat 中断)。

用法:
  python scripts/_build_post.py icu            # 删除 dist 内 ICU 副本 (依赖 OS icuuc shim)
  python scripts/_build_post.py bundle-polydb  # 把 COD-Inorg polyDB 复制进 dist/PolyXRD/databases
  python scripts/_build_post.py db-layout     # 断言库布局正确 (只允许 databases/<*.polyDB>/ 8 段)
  python scripts/_build_post.py version 1.1.1 # 写 dist/PolyXRD/VERSION.txt 并复制到 installer_output
"""
import datetime
import glob
import os
import sys

DIST = r'dist\PolyXRD'


def icu_cleanup() -> int:
    removed = 0
    for pat in [os.path.join(DIST, '_internal', 'icu*.dll'),
                os.path.join(DIST, '_internal', 'PySide6', 'icu*.dll')]:
        for f in glob.glob(pat):
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
    print(f'  ICU cleanup: removed {removed} files (依赖 OS icuuc shim)')
    return 0


def assert_no_db() -> int:
    # pymatgen 自带的对称性数据表是依赖的一部分, 不算业务数据库 (与 verify_release.ps1 一致)
    allowed = os.path.join('_internal', 'pymatgen', 'symmetry', 'symm_data_magnetic.sqlite')
    hits = []
    for pat in [os.path.join(DIST, '**', '*.sqlite'),
                os.path.join(DIST, '**', '*.sqlite3'),
                os.path.join(DIST, '**', '*.db'),
                os.path.join(DIST, '**', '*.tar.xz')]:
        hits += glob.glob(pat, recursive=True)
    hits = [h for h in hits
            if os.path.relpath(h, DIST).replace('/', '\\') != allowed
            and not os.path.relpath(h, DIST).replace('/', '\\').endswith('\\' + allowed)]
    if hits:
        print('  [警告] 发现被意外打入的数据库文件:')
        for h in hits:
            print('    ', h, round(os.path.getsize(h) / 1e6, 1), 'MB')
    else:
        print('  OK: 未发现数据库文件, 符合 0.10.0 外挂策略')
    return 0


#: polyDB 目录容器的 8 个分段文件 (缺一不可, 与 verify_release.ps1 同一口径)
POLYDB_SEGMENTS = ('meta.json', 'index.sqlite', 'peaks_d.f32', 'peaks_i.u16',
                   'bins.u8', 'elem.u8', 'sites.bin', 'sites_off.i64')


def _read_polydb_meta(path) -> dict:
    """读 polyDB 的 meta.json（失败返回空 dict，由调用方报错）。"""
    import json
    import pathlib

    try:
        meta = json.loads((pathlib.Path(path) / 'meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _validate_polydb_meta(meta: dict, want_variant: str = 'cod-inorg') -> list[str]:
    """v4.1.2：只校验"8 个文件存在"不够 —— 损坏/错变体的库也会通过。

    要求 ``format=polyDB``、``schema_version=1``、``variant`` 匹配、
    ``counts.phases > 0``；返回问题列表（空 = 合格）。
    """
    problems: list[str] = []
    if str(meta.get('format') or '') != 'polyDB':
        problems.append(f"meta.format={meta.get('format')!r} != 'polyDB'")
    try:
        schema = int(meta.get('schema_version') or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != 1:
        problems.append(f"meta.schema_version={meta.get('schema_version')!r} != 1")
    if str(meta.get('variant') or '') != want_variant:
        problems.append(f"meta.variant={meta.get('variant')!r} != {want_variant!r}")
    counts = meta.get('counts') or {}
    try:
        phases = int(counts.get('phases') or 0)
    except (TypeError, ValueError):
        phases = 0
    if phases <= 0:
        problems.append(f"meta.counts.phases={counts.get('phases')!r} <= 0")
    return problems


def _polydb_source_roots() -> list[str]:
    """检索 COD-Inorg polyDB 的候选父目录 (顺序即优先级)。"""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]
    roots = []
    env = os.environ.get('POLYXRD_POLYDB_DIR', '').strip()
    if env:
        roots.append(env)
    roots.append(str(repo / 'databases'))
    roots.append(str(repo.parent / 'PolyXRD-DataBase' / 'polydb'))
    return roots


def bundle_polydb() -> int:
    """把 COD-Inorg polyDB 复制进 ``dist/PolyXRD/databases/``。

    v4.1.0 起便携/安装包**内置**默认库(只要无机物 COD-Inorg): 解压即检索,
    不需要用户先下载外挂库再挂载。运行时由 ``config._polydb_search_roots``
    在冻结态解析 ``<exe 目录>/databases``。

    环境变量 ``POLYXRD_NO_BUNDLE_DB=1`` 可跳过 (用于"纯客户端"小包)。
    """
    import pathlib
    import shutil

    if os.environ.get('POLYXRD_NO_BUNDLE_DB') == '1':
        print('  bundle-polydb: 已按 POLYXRD_NO_BUNDLE_DB=1 跳过 (纯客户端小包)')
        return 0

    found = []
    for root in _polydb_source_roots():
        p = pathlib.Path(root)
        if not p.is_dir():
            continue
        cands = [p] if (p / 'meta.json').is_file() else [
            d for d in p.iterdir()
            if d.is_dir() and (d / 'meta.json').is_file() and 'inorg' in d.name.lower()
        ]
        for c in cands:
            if not all((c / seg).is_file() for seg in POLYDB_SEGMENTS):
                print(f'  [警告] {c.name}: 分段文件不全，跳过')
                continue
            meta = _read_polydb_meta(c)
            problems = _validate_polydb_meta(meta, 'cod-inorg')
            if problems:
                print(f'  [警告] {c.name}: meta 校验失败，跳过 ({"; ".join(problems)})')
                continue
            found.append(c)
    if not found:
        print('  [错误] 未找到任何合格的 COD-Inorg polyDB（默认库是 v4.1.0+ 的核心功能）')
        print('         候选父目录: ' + ', '.join(_polydb_source_roots()))
        print('         修复: 设置 POLYXRD_POLYDB_DIR 指向库目录，或跳过本步用 '
              'set POLYXRD_NO_BUNDLE_DB=1（纯客户端小包）')
        return 1

    src = sorted(found, key=lambda d: d.name)[-1]
    dst_dir = pathlib.Path(DIST) / 'databases'
    dst = dst_dir / src.name
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

    total = 0
    for seg in POLYDB_SEGMENTS:
        shutil.copyfile(src / seg, dst / seg)
        total += (dst / seg).stat().st_size
    meta = _read_polydb_meta(src)
    phases = int((meta.get('counts') or {}).get('phases') or 0)
    print(f'  bundle-polydb: {src.name} -> {dst}  '
          f'({total / 2**20:.0f} MiB, 8/8 段, {phases:,} 相)')
    return 0


def assert_db_layout() -> int:
    """断言 dist 里的参考库布局正确 (取代旧的"dist 内不得有库"检查)。

    v4.1.0 起内置默认库, 所以允许且**只允许**
    ``databases/<*.polyDB>/{8 个分段文件}``; 其它任何 ``.sqlite`` / ``.db`` /
    ``.tar.xz`` 仍属意外打入, 要报警。polyDB 自带的 ``index.sqlite`` 是它的
    正常分段文件, 不算业务库。
    """
    import pathlib

    dist = pathlib.Path(DIST)
    problems: list[str] = []
    libs = list((dist / 'databases').glob('*.polyDB')) if (dist / 'databases').is_dir() else []
    if not libs:
        problems.append('databases/ 下没有 *.polyDB —— 便携版解压后不能直接检索')
    for lib in libs:
        missing = [seg for seg in POLYDB_SEGMENTS if not (lib / seg).is_file()]
        if missing:
            problems.append(f'{lib.name} 缺分段文件: {", ".join(missing)}')
        extra = [p.name for p in lib.iterdir()
                 if p.is_file() and p.name not in POLYDB_SEGMENTS]
        if extra:
            problems.append(f'{lib.name} 含非分段文件: {", ".join(extra[:5])}')
        meta = _read_polydb_meta(lib)
        problems.extend(f'{lib.name}: {p}' for p in
                        _validate_polydb_meta(meta, 'cod-inorg'))

    stray = []
    for pat in ('**/*.sqlite', '**/*.sqlite3', '**/*.db', '**/*.tar.xz'):
        stray += glob.glob(os.path.join(DIST, pat), recursive=True)
    for h in stray:
        rel = os.path.relpath(h, DIST).replace('/', '\\')
        if 'pymatgen\\symmetry\\symm_data_magnetic.sqlite' in rel:
            continue
        if rel.lower().startswith('databases\\') and '.polydb\\' in rel.lower():
            continue
        problems.append(f'意外打入的数据库: {rel} ({os.path.getsize(h) / 1e6:.1f} MB)')
    if problems:
        print('  [错误] 数据库布局检查未通过:')
        for msg in problems:
            print('    -', msg)
        return 1
    else:
        names = ', '.join(lib.name for lib in libs)
        print(f'  OK: 内置库 {names} (8/8 段), 无其它数据库')
    return 0


def _bundled_phase_count() -> str:
    """从 dist 内置库的 meta.json 读相数（避免文档/包内数字与真实库脱节）。"""
    import json
    import pathlib

    try:
        for d in sorted((pathlib.Path(DIST) / 'databases').glob('*.polyDB')):
            meta = json.loads((d / 'meta.json').read_text(encoding='utf-8'))
            n = int((meta.get('counts') or {}).get('phases') or 0)
            if n > 0:
                return f'{n:,} 相'
    except (OSError, ValueError, TypeError):
        pass
    return '内置默认库'


#: flavor → VERSION.txt 首行变体名。未知值不回落到"Release"（那正是 P2-6 想
#: 避免的"内部版自称正式版"），而是原样大写，至少让人看出不对劲。
_FLAVOR_LABEL = {
    "release": "Release",
    "internal": "Internal Evaluation",
}


def _resolve_flavor(explicit: str | None = None) -> str:
    """构建变体：显式参数 > 环境变量 POLYXRD_FLAVOR > release。

    build.bat 在第 35 行就把 ``POLYXRD_FLAVOR`` 定好（默认 release），
    所以这里读环境变量即可与构建链变体一致，无需再传参。
    """
    raw = (explicit or os.environ.get("POLYXRD_FLAVOR") or "release").strip()
    return raw.lower() or "release"


def write_version(ver: str, flavor: str | None = None) -> int:
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    fl = _resolve_flavor(flavor)
    label = _FLAVOR_LABEL.get(fl, fl.upper())
    text = (
        f"PolyXRD v{ver} {label}\n"
        f"Build Date: {stamp}\n"
        f"Version    : {ver}\n"
        f"Flavor     : {fl}\n"
        "ICU: 依赖系统 icuuc shim (PySide6 6.11 不自带 ICU)\n"
        f"Databases: v4.1.0 起**内置默认库** COD-Inorg (polyDB, {_bundled_phase_count()}) ——\n"
        "           解压/安装即可检索, 无需任何下载或挂载。\n"
        "           扩展库 (COD-Full 等): 由 PolyXRD-DataBase 仓库的 Releases 分发；\n"
        "           本仓库 Release 只发程序 (不含任何数据库包)。\n"
        "           PDF2-2004: ICDD 版权库, 不随 Release 分发, 由持授权用户自行准备。\n"
        "           追加库: 菜单「数据库 ▸ 外挂数据库管理… ▸ 挂载文件夹…」指过去即可, 无需重启。\n"
        "Icon: 品牌化应用图标 (crystal-mark + XRD 配色, 多分辨率 ICO)\n"
    )
    out_dir = DIST
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'VERSION.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    inst = 'installer_output'
    if os.path.isdir(inst):
        with open(os.path.join(inst, f'VERSION_v{ver}.txt'), 'w', encoding='utf-8') as f:
            f.write(text)
    print(f'  VERSION.txt 已写入 {path} (Build Date: {stamp})')
    return 0


# ── 便携版附加文件 (v2.0.1) ──────────────────────────────────
# 目的: 提升便携包"拷到别的机器"时的启动稳健性与可自助排障能力。
# 约定: .bat 内容**纯 ASCII + CRLF**(项目红线); 说明文档用 UTF-8(带 BOM, 便于记事本直读)。
_LAUNCHER_BAT = r'''@echo off
chcp 65001 >nul
REM PolyXRD portable launcher (ASCII-only content by project convention)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo [PolyXRD] starting ...
"%~dp0PolyXRD.exe"
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [PolyXRD] exited with code %RC%
if not "%RC%"=="0" echo [PolyXRD] Window flashed then closed? Run the SafeMode launcher.
if not "%RC%"=="0" echo [PolyXRD] Logs: %USERPROFILE%\.polyxrd\logs
if not "%RC%"=="0" pause
'''.replace("\n", "\r\n")

_SAFE_LAUNCHER_BAT = r'''@echo off
chcp 65001 >nul
REM PolyXRD portable launcher - SAFE RENDER (software OpenGL)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set POLYXRD_SAFE_RENDER=1
cd /d "%~dp0"
echo [PolyXRD] starting in SAFE RENDER mode (software OpenGL) ...
"%~dp0PolyXRD.exe"
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [PolyXRD] exited with code %RC%
if not "%RC%"=="0" echo [PolyXRD] Logs: %USERPROFILE%\.polyxrd\logs
if not "%RC%"=="0" pause
'''.replace("\n", "\r\n")

_PORTABLE_README = """PolyXRD 便携版 (免安装) 使用说明
========================================

一、启动
  - 推荐双击「启动 PolyXRD.bat」: 会在启动失败时给出退出码与日志路径, 方便排障。
  - 也可直接双击「PolyXRD.exe」。

二、务必完整解压后再运行
  - 请把整个压缩包**完整解压到一个文件夹**, 再运行里面的 PolyXRD.exe。
  - 不要在压缩软件里直接双击 EXE —— 那样只会释放出单个 EXE, 缺少 `_internal`
    依赖目录, 程序无法启动。

三、如果出现「窗口一闪就退出」
  1) 程序内置**崩溃自愈**: 请**再启动一次**。上一次未正常起来会被记下, 这一次会
     自动改用「保守渲染」(软件 OpenGL) 启动, 通常即可正常打开。
  2) 也可直接双击「安全模式启动.bat」, 强制以保守渲染启动。
  3) 仍打不开: 查看日志目录 `%USERPROFILE%\\.polyxrd\\logs\\`
       startup-*.log        启动流水 (看卡在哪一步)
       crash-*.log          Python 异常
       faulthandler-*.log   原生崩溃 (访问冲突) 的调用栈
       startup-failure-*.log 启动诊断报告
  4) 复位自愈状态 (回到正常渲染): 命令行运行  PolyXRD.exe --reset-render
  5) 无界面诊断 (查文件占用/缺失): 命令行运行  PolyXRD.exe --diagnose

四、数据库 (默认库已内置, 其余外挂)
  - 本包**已内置 COD-Inorg polyDB 默认库**, 解压/安装后直接可检索, 无需下载。
  - 扩展库 (COD-Full 等) 从 PolyXRD-DataBase 仓库的 Releases 下载, 解压后
    菜单「数据库 ▸ 外挂数据库管理…」→「挂载文件夹…」指过去, 选中该行点
    「设为当前」即生效, **无需重启**。
  - 旧 sqlite 检索库 (COD 无机物 / COD 全库索引 / XinMatch) 自 v4.1.0 起不再支持；
    PDF2-2004 仍支持挂载 (ICDD 版权库, 需自备, 不随发行包提供)。

五、系统要求
  - 64 位 Windows 10 / 11。
"""


def write_portable_extras(ver: str = "") -> int:
    """把便携版附加文件写进 dist\\PolyXRD (Setup 阶段已先于本步完成, 故不会进安装包)。"""
    _LAUNCHER_BAT.encode("ascii")        # 红线自检: 内容必须纯 ASCII
    _SAFE_LAUNCHER_BAT.encode("ascii")
    files = {
        "启动 PolyXRD.bat": (_LAUNCHER_BAT, "ascii"),
        "安全模式启动.bat": (_SAFE_LAUNCHER_BAT, "ascii"),
        "便携版使用说明.txt": (_PORTABLE_README.replace("{VER}", ver or ""), "utf-8-sig"),
    }
    for name, (text, enc) in files.items():
        path = os.path.join(DIST, name)
        with open(path, "w", encoding=enc, newline="") as f:
            f.write(text)
        print(f"  portable extra: {name} ({os.path.getsize(path)} B)")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: _build_post.py [icu|bundle-polydb|db-layout|no-db|'
          'version <ver> [flavor]|portable-extras [ver]]')
        return 2
    cmd = sys.argv[1]
    if cmd == 'icu':
        return icu_cleanup()
    if cmd == 'bundle-polydb':
        return bundle_polydb()
    if cmd == 'db-layout':
        return assert_db_layout()
    if cmd == 'no-db':  # 旧名保留: 语义已升级为"布局检查"
        return assert_db_layout()
    if cmd == 'version':
        ver = sys.argv[2] if len(sys.argv) > 2 else ''
        if not ver:
            print('version 子命令需要版本号参数')
            return 2
        # 可选第三参数: flavor（缺省读 POLYXRD_FLAVOR，见 _resolve_flavor）
        fl = sys.argv[3] if len(sys.argv) > 3 else None
        return write_version(ver, fl)
    if cmd == 'portable-extras':
        ver = sys.argv[2] if len(sys.argv) > 2 else ''
        return write_portable_extras(ver)
    print(f'未知子命令: {cmd}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
