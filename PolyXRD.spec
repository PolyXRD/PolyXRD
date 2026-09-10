# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# ── 数据库打包策略 (0.10.0 起: 默认【不】打包) ────────────────
# 数据库改外挂: 单独下载 → 解压 → 在 GUI「数据库 ▸ 外挂数据库管理…」导入。
# 好处是安装包从 ~900 MB 降到 ~150 MB, 且数据库可独立更新, 不必重发客户端。
#
#   POLYXRD_WITH_DB=1   -> 仍然内嵌三个库 (仅供内部/离线整包分发)
#
# 内嵌时各库的去向 (与运行时解析路径一致, 不要随意改):
#   cod_index.sqlite      -> 'cod'       (cod_local._BUNDLED_COD_DB_SUBPATH)
#   COD_inorganics.sqlite -> 'cod_data'
#   PDF2_2004.sqlite      -> 'cod_data'

_datas_base = [
    ('src/polyxrd/i18n', 'polyxrd/i18n'),
    ('src/polyxrd/resources', 'polyxrd/resources'),
]

_WITH_DB = os.environ.get('POLYXRD_WITH_DB') == '1'

if _WITH_DB:
    # COD 全库 (cod_index.sqlite, crystallography.net, 113K 条目 + 5.1M 原子位点)
    _cod_full = 'cod_index.sqlite'
    if os.path.exists(_cod_full):
        _datas_base.append((_cod_full, 'cod'))
        print(f'[PolyXRD.spec] Bundling COD full database: {_cod_full}')
    else:
        print(f'[PolyXRD.spec] COD full database not found, skipping: {_cod_full}')

    # COD 无机物库 (从 COD 筛选的无机物子集, 预计算 d-I 峰)
    _cod_inorg = 'cod_data/COD_inorganics.sqlite'
    if os.path.exists(_cod_inorg):
        _datas_base.append((_cod_inorg, 'cod_data'))
        print(f'[PolyXRD.spec] Bundling COD inorganics database: {_cod_inorg}')
    else:
        print(f'[PolyXRD.spec] COD inorganics database not found, skipping: {_cod_inorg}')

    # PDF2-2004 库 (ICDD PDF-2 2004, 163K 物相, 带空间群/晶胞)
    _pdf2 = 'cod_data/PDF2_2004.sqlite'
    if os.path.exists(_pdf2):
        _datas_base.append((_pdf2, 'cod_data'))
        print(f'[PolyXRD.spec] Bundling PDF2-2004 database: {_pdf2}')
    else:
        print(f'[PolyXRD.spec] PDF2-2004 database not found, skipping: {_pdf2}')
else:
    print('[PolyXRD.spec] Databases EXTERNAL (0.10.0 default): '
          'no .sqlite bundled. Import via GUI.'
          ' Set POLYXRD_WITH_DB=1 to bundle them anyway.')

datas = _datas_base
binaries = []
hiddenimports = ['polyxrd', 'polyxrd.i18n', 'polyxrd.i18n.translations.zh_CN', 'polyxrd.i18n.translations.en_US', 'polyxrd.i18n.translations.ja_JP', 'polyxrd.services.project_service', 'polyxrd.services.structure_simulator', 'polyxrd.services.phase_identifier', 'polyxrd.services.profile_fitting', 'polyxrd.services.db_import', 'polyxrd.services.cod_local', 'polyxrd.views.widgets.database_dialog', 'polyxrd.views.widgets.element_periodic_table', 'polyxrd.views.widgets.element_filter_dialog']
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
