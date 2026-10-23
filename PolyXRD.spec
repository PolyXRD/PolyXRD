# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# spec 自身所在目录 (= 仓库根)。PyInstaller 构建时把 SPECPATH 注入 globals。
_SPEC_DIR = globals().get('SPECPATH', os.getcwd())

# 必须随包的非库资源 (库资源见下面的 polyDB 段)。
_datas_base = [
    ('src/polyxrd/i18n', 'polyxrd/i18n'),
    ('src/polyxrd/resources', 'polyxrd/resources'),
]

# ── 参考数据库策略 (v4.1.0: 默认【不】随 exe 收集) ────────────────
# v4.1.0 起可检索的参考库只有一种: **polyDB 目录容器**
# (``COD-Inorg-<日期>.polyDB/``, 8 个分段文件 + meta.json, mmap 只读)。
# 旧的 ``cod_index.sqlite`` / ``COD_inorganics.sqlite`` / ``PDF2_2004.sqlite``
# 槽位已全部删除, 因此本 spec 不再收集任何 .sqlite。
#
# 默认策略: 数据库**不进 _internal**, 由 build.bat 在第 3 步把
# ``<repo>/../PolyXRD-DataBase/polydb/COD-Inorg-*.polyDB`` 复制到
# ``dist/PolyXRD/databases/`` —— 便携版解压即可检索, 且用户能直接看到、
# 替换库目录 (运行时解析路径见 config._polydb_search_roots:
# 冻结态 = ``<exe 目录>/databases``)。
#
#   POLYXRD_WITH_POLYDB=1  -> 由 spec 直接收集进 ``databases/``
#                             (仅当想让"单跑 pyinstaller"也自带库时用)
_POLYDB_ENV = os.environ.get('POLYXRD_POLYDB_DIR', '').strip()


def _find_polydb(variant_hint: str):
    """找到要内嵌的 polyDB 目录 (最新的那份), 找不到返回 None。

    搜索顺序: ``POLYXRD_POLYDB_DIR`` → 仓库 ``databases/`` → 构库仓库
    ``../PolyXRD-DataBase/polydb``。判据与运行时一致: 目录里有
    ``meta.json`` + ``index.sqlite``。
    """
    roots = []
    if _POLYDB_ENV:
        roots.append(Path(_POLYDB_ENV))
    roots.append(Path(_SPEC_DIR) / 'databases')
    roots.append(Path(_SPEC_DIR).parent / 'PolyXRD-DataBase' / 'polydb')

    found = []
    for root in roots:
        if not root.is_dir():
            continue
        cands = [root] if (root / 'meta.json').is_file() else [
            d for d in root.iterdir() if d.is_dir() and (d / 'meta.json').is_file()
        ]
        for cand in cands:
            if variant_hint.lower() in cand.name.lower():
                found.append(cand)
    if not found:
        return None
    return sorted(found, key=lambda p: p.name)[-1]


_WITH_POLYDB = os.environ.get('POLYXRD_WITH_POLYDB') == '1'

if _WITH_POLYDB:
    _polydb = _find_polydb('cod-inorg')
    if _polydb is not None:
        # polyDB 是目录容器: 整目录收进 databases/<目录名>, 分段文件一个都不能少。
        _datas_base.append((str(_polydb), f'databases/{_polydb.name}'))
        print(f'[PolyXRD.spec] Bundling polyDB: {_polydb.name}')
    else:
        print('[PolyXRD.spec] POLYXRD_WITH_POLYDB=1 but no COD-Inorg *.polyDB '
              'found, skipping')
else:
    print('[PolyXRD.spec] Reference databases EXTERNAL: polyDB goes to '
          'dist/PolyXRD/databases by build.bat (portable = ready to search).')

datas = _datas_base
binaries = []
hiddenimports = ['polyxrd', 'polyxrd.i18n', 'polyxrd.i18n.translations.zh_CN', 'polyxrd.i18n.translations.en_US', 'polyxrd.i18n.translations.ja_JP', 'polyxrd.services.project_service', 'polyxrd.services.structure_simulator', 'polyxrd.services.phase_identifier', 'polyxrd.services.profile_fitting', 'polyxrd.services.db_import', 'polyxrd.services.cod_local', 'polyxrd.views.widgets.database_dialog', 'polyxrd.views.widgets.element_periodic_table', 'polyxrd.views.widgets.element_filter_dialog']

# ── 构建变体 flavor (v2.10.0): 存在 src/polyxrd/_build_flavor.py -> 内部评估版 ──
# build_flavor._detect() 是在 try/except 里动态 import 该模块的, PyInstaller 的
# 静态依赖分析可能不把它算进图里。一旦漏收集, 内部版会【静默退化成正式版】——
# "内部版不弹注册提示"这个承诺失效, 反而开始每次启动骚扰内部用户, 且极难察觉。
# 所以这里显式把它挂进依赖图, 并用 print 让构建日志可核对。
_BUILD_FLAVOR_SRC = os.path.join(_SPEC_DIR, 'src', 'polyxrd', '_build_flavor.py')
if os.path.exists(_BUILD_FLAVOR_SRC):
    hiddenimports.append('polyxrd._build_flavor')
    print('[PolyXRD.spec] flavor module FOUND -> internal edition '
          '(no registration prompts)')
else:
    print('[PolyXRD.spec] flavor module absent -> release edition '
          '(registration enabled)')
# ── ICU 修复: PySide6 6.11 不再自带 ICU, Qt6 启动需 icuuc/icudt/icuin 系列 ──
# 从系统已知位置 (mamba/conda 通用 ICU 78) 收集, 避免 Qt6 找不到 ICU 而 LoadLibrary 失败
import os as _os
for _icu_root in [
    _os.path.expandvars(r'%USERPROFILE%\AppData\Roaming\mamba\pkgs\icu-78.3*'),
    _os.path.expandvars(r'%USERPROFILE%\AppData\Roaming\mamba\pkgs\https\conda.anaconda.org\conda-forge\win-64\icu-78.3*'),
    r'C:\Program Files (x86)\Microsoft\EdgeWebView\Application',  # Edge WebView2 自带 ICU
]:
    if glob_module := __import__('glob').glob(_icu_root):
        for d in glob_module:
            _bin = _os.path.join(d, 'Library', 'bin')
            if _os.path.isdir(_bin):
                for _f in ['icuuc.dll', 'icudt.dll', 'icuin.dll',
                           'icuio.dll', 'icutu.dll',
                           'icuuc74.dll', 'icudt74.dll',
                           'icuuc75.dll', 'icudt75.dll',
                           'icuuc76.dll', 'icudt76.dll',
                           'icuuc77.dll', 'icudt77.dll',
                           'icuuc78.dll', 'icudt78.dll']:
                    _src = _os.path.join(_bin, _f)
                    if _os.path.isfile(_src):
                        binaries.append((_src, '.'))
                        print(f'[PolyXRD.spec] Bundling ICU: { _f }')
                break
        break
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('matplotlib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pymatgen')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('lmfit')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('scipy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('numpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyqtgraph')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('spglib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('plotly')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['src/polyxrd/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PolyXRD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src/polyxrd/resources/app-icon.ico'],
    manifest='app.manifest',
)
# 沙盒安全删除拦截, COLLECT 阶段尝试 shutil.rmtree 失败;
# build.bat/手动构建脚本会通过 _do_collect.py 替代这一步.
try:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='PolyXRD',
    )
except Exception as _e:
    print(f'[PolyXRD.spec] COLLECT failed (likely safe-delete): {_e}')
    print('[PolyXRD.spec] 请手动跑: python _do_collect.py')
    coll = None
