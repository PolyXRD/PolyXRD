# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# ── 可选数据库打包 (通过环境变量控制) ──────────────────────
#   POLYXRD_NO_COD_DB=1      -> 不打包 cod_index.sqlite (COD 全库, ~431 MB)
#   POLYXRD_NO_INORG_DB=1   -> 不打包 COD_inorganics.sqlite (无机物库, ~258 MB)
# 默认: 两个数据库都打包 (若文件存在)
# 注意: cod_index.sqlite 首次启动会复制到 ~/.polyxrd/cif_db/, 供离线物相检索/精修使用.
#       若打包体积敏感, 设置 POLYXRD_NO_COD_DB=1 即可跳过, 用户可从 COD REST API 按需下载.

_datas_base = [
    ('src/polyxrd/i18n', 'polyxrd/i18n'),
    ('src/polyxrd/resources', 'polyxrd/resources'),
]

# COD 全库 (cod_index.sqlite, crystallography.net, 113K 条目 + 5.1M 原子位点)
if os.environ.get('POLYXRD_NO_COD_DB') != '1':
    _cod_full = 'cod_index.sqlite'
    if os.path.exists(_cod_full):
        _datas_base.append((_cod_full, 'cod'))
        print(f'[PolyXRD.spec] Bundling COD full database: {_cod_full}')
    else:
        print(f'[PolyXRD.spec] COD full database not found, skipping: {_cod_full}')

# COD 无机物库 (COD_inorganics.sqlite, 从 COD 筛选的无机物子集, 预计算 d-I 峰)
if os.environ.get('POLYXRD_NO_INORG_DB') != '1':
    _cod_inorg = 'cod_data/COD_inorganics.sqlite'
    if os.path.exists(_cod_inorg):
        _datas_base.append((_cod_inorg, 'cod_data'))
        print(f'[PolyXRD.spec] Bundling COD inorganics database: {_cod_inorg}')
    else:
        print(f'[PolyXRD.spec] COD inorganics database not found, skipping: {_cod_inorg}')

datas = _datas_base
binaries = []
hiddenimports = ['polyxrd', 'polyxrd.i18n', 'polyxrd.i18n.translations.zh_CN', 'polyxrd.i18n.translations.en_US', 'polyxrd.i18n.translations.ja_JP', 'polyxrd.services.project_service', 'polyxrd.services.structure_simulator', 'polyxrd.services.phase_identifier', 'polyxrd.services.profile_fitting', 'polyxrd.views.widgets.element_periodic_table', 'polyxrd.views.widgets.element_filter_dialog']
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
