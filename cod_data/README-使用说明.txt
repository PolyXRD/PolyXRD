PolyXRD COD 无机物数据库外挂包
==============================
Version       : v0.8.21 (对应 PolyXRD 0.8.21+)
Pack Date     : 2026-08-21
Database File : COD_inorganics.sqlite
Database Size : 258.6 MB
Phase Count   : 71199
Source        : Crystallography Open Database (COD) inorganic subset 20260821
Schema        : phases(ref_id, formula, mineral, formula_nl, a, b, c, ...), dpeaks(pid, d, intensity)
App Min Ver   : PolyXRD 0.8.21

Contents
--------
  COD_inorganics.sqlite          主数据库文件 (SQLite 3)
  install_COD_database.bat       Windows 一键安装脚本 (推荐)
  README-使用说明.txt            本文件

安装方式(两种二选一)
--------------------
[A] 一键安装 (推荐 Windows 用户):
    双击 install_COD_database.bat
    → 自动复制到 %LOCALAPPDATA%\PolyXRD\databases\
    → 自动写入注册表告知 PolyXRD
    → 重启 PolyXRD 即可使用

[B] 手动安装 (跨平台通用):
    1. 打开 PolyXRD → 菜单 "文件" → "导入外部数据库"
    2. 选择本目录下的 COD_inorganics.sqlite
    3. 确认完成, 物相检索功能立即可用

    或者: 把 COD_inorganics.sqlite 放到 PolyXRD.exe 所在
    目录下的 cod_data\COD_inorganics.sqlite, 程序会自动发现.
