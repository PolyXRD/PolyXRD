#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正式安装包（Setup）发布前验收 —— 静默安装 + 内置库 + flavor 三项硬判据。

================================================================================
为什么必须用这个脚本，而不是「双击一下看看装不装得上」
================================================================================

**坑 1：安装包必须先拷到「没有 safe-delete ACE」的目录再装。**

项目树（``D:\\Project\\XRD\\PolyXRD\\`` 及其子目录）带一条**继承的**
``Everyone: Deny DeleteSubdirectoriesAndFiles``（safe-delete 防护 ACE）。Inno Setup 的
加载器要在**自己所在目录**建临时文件与日志，被这条 ACE 拒掉 → 弹

    Error creating log file: 拒绝访问。

静默模式下这个对话框被 ``/SUPPRESSMSGBOXES`` 吞掉，于是表现为：

    rc=1  +  **没有安装日志**  +  **零文件落盘**

—— 看起来像「产物损坏」，实际包完全正常，只是**所在目录不能当安装目标**。
（本机实测：同一份字节，项目树内 rc=1；拷到 ``%TEMP%`` 后 rc=0、13,160 个文件。）

**同一条 ACE 的第二种表现（更隐蔽）**：若安装**目标目录**在仓库树内，文件其实会
全部写进去，然后在收尾阶段写「卸载信息 .dat」时被拒 →

    IPersistFile::Save 失败；错误代码 0x80070005  拒绝访问
    Fatal exception … RegCreateKeyEx 失败；错误代码 5
    → Rolling back changes（把刚写进去的文件全删掉）

表现为 **rc=4 + 有安装日志（几 MB）+ 零文件落盘**。
⇒ **安装目标也必须在仓库树之外。**

⚠ 选临时目录时**不要用** ``tempfile.gettempdir()``：它的候选目录都不可写时会
**回落到当前工作目录**，而验收脚本通常从仓库根运行 → 临时目录 = 仓库根 → 踩坑。
本脚本用 ``pick_scratch()`` 显式按优先级试 ``%TEMP%\\pxv`` → ``D:\\pxv`` → ``C:\\pxv``，
并**排除仓库树内**的任何候选。

**坑 2：flavor 不能用字符串 grep 判定。**

``polyxrd/utils/build_flavor.py`` 的源码里就写着字符串 ``"polyxrd._build_flavor"``，
它会被编进 ``build_flavor.pyc`` 的常量池 ⇒ **release 版的 exe 里也有这个字符串**。
grep 出来的"有/无"与变体无关。

正确判据 = **PyInstaller 的 PYZ 目录（TOC）里有没有该模块条目**：

* 有 ``polyxrd._build_flavor`` ⇒ **internal**（marker 模块被打进了包）
* 没有 ⇒ **release**（模块不存在，``_detect()`` 回落到 release）

**坑 3：正式安装包里不能出现便携版专属文件。**

``便携版使用说明.txt`` / ``启动 PolyXRD.bat`` / ``安全模式启动.bat`` 只属于便携包。
混进正式安装包 = 向终端用户宣称「这是便携版」，还附赠一个调试启动器。

**坑 4：验收必须跑在「有正常用户令牌」的 shell 里。**

安装收尾要写 ``HKCU\\...\\Uninstall\\{AppId}_is1``。若跑在一个**受限令牌**
（restricted token / 沙箱注入的 sitecustomize）下，注册表写会被拒 → 致命异常 →
回滚 → rc=4 + 有日志 + 零文件落盘。WorkBuddy 沙箱里就是这种情形：它同时封掉
``%TEMP%`` 与注册表写入（venv python 直接报
``No usable temporary directory found``）。
⇒ **在普通终端里跑**；判不准时先手工装一遍，看现象是包的问题还是环境的问题。

================================================================================
用法
================================================================================
    python scripts/verify_installer.py installer_output/PolyXRD-Setup-v4.1.0.exe

    # 便携包对照（校验它**应当**是 internal）
    python scripts/verify_installer.py --portable installer_output/PolyXRD-v4.1.0-Portable.zip

**零依赖**：只用标准库（PYZ 目录自己解析），不要求装 PyInstaller / numpy / gemmi。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

#: polyDB 容器的 8 个分段文件
POLYDB_SEGMENTS = ('meta.json', 'index.sqlite', 'peaks_d.f32', 'peaks_i.u16',
                   'bins.u8', 'elem.u8', 'sites.bin', 'sites_off.i64')

#: 内置默认库的目录名模式（v4.1.1：动态匹配，换库不再误报）
BUNDLED_LIB_GLOB = 'COD-Inorg-*.polyDB'

#: 内部评估版的 flavor marker 模块（PyInstaller hiddenimports 才会收进 PYZ）
FLAVOR_MARKER_MOD = 'polyxrd._build_flavor'

#: 便携版专属文件 —— **不允许**出现在正式安装包里
PORTABLE_ONLY_FILES = ('便携版使用说明.txt', '启动 PolyXRD.bat', '安全模式启动.bat')

#: 允许出现在包里的业务库文件（polyDB 自身分段除外，polyDB 不在扩展名黑名单里）
BANNED_DB_SUFFIX = ('.sqlite', '.sqlite3', '.db', '.tar', '.xz')

#: pymatgen 自带的对称性数据表 —— 是依赖的一部分，**不是**业务数据库
ALLOWED_DB_FILES = ('pymatgen/symmetry/symm_data_magnetic.sqlite',)

#: 本仓库根目录 —— 安装目标与临时副本**都不得**落在它里面（见下）
REPO_ROOT = Path(__file__).resolve().parent.parent


def pick_scratch(explicit: Path | None = None) -> Path:
    """挑一个「可写 + 不在仓库树内 + 路径尽量短」的临时工作目录。

    ⚠ **不能用 ``tempfile.gettempdir()``** —— 它的候选目录全部不可写时会**回落到
    当前工作目录**；而验收脚本通常就是从仓库根运行的，于是临时目录 = 仓库根 =
    带 safe-delete ACE 的目录 ⇒ 安装在写「卸载信息 .dat」时被拒 → 致命异常 →
    回滚 → rc=4 + 零文件落盘。实测栽过。

    也不要用带 8.3 短名（``ADMINI~1``）的 %TEMP%：同一批 ACL 下它的可写性判定
    可能失败而静默回落。

    ⇒ 显式地、**按优先级**试几个盘根短路径。
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    else:
        env_tmp = os.environ.get('TEMP') or os.environ.get('TMP')
        if env_tmp:
            candidates.append(Path(env_tmp) / 'pxv')
        for drive in ('D:', 'C:'):
            candidates.append(Path(drive + '\\pxv'))
        candidates.append(Path(tempfile.gettempdir()) / 'pxv')

    for cand in candidates:
        try:
            cand = cand.resolve()
        except OSError:
            continue
        # 必须不在仓库树内
        try:
            cand.relative_to(REPO_ROOT)
            continue
        except ValueError:
            pass
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / f'_w{uuid.uuid4().hex[:8]}.tmp'
            probe.write_bytes(b'x')
            probe.unlink()
            return cand
        except OSError:
            continue
    raise RuntimeError('找不到可写且不在仓库树内的临时目录；请用 --scratch 指定')


# ── 卸载注册表项（第二类环境陷阱） ─────────────────────────────────────────
#: 与 scripts/PolyXRD-Setup.iss 的 AppId 对应（Inno 会加 _is1 后缀）
UNINSTALL_KEY = (r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
                 r'\{A8F91C6B-2B3D-4F5E-8B3C-4E01A2C33D01}_is1')


def _uninstall_key_path() -> str:
    return UNINSTALL_KEY


def clear_stale_uninstall_key() -> str | None:
    """删掉「上几次验收遗留」的卸载注册表项，返回说明文字（无则 None）。

    为什么必须清：Inno Setup 安装收尾要写
    ``HKCU\\...\\Uninstall\\{AppId}_is1``。若该项已存在且**带限制性 DACL**
    （典型来源：上一次在受限/沙箱 token 下跑的安装），Inno 会
    「删除旧的 → 建新的」，两步都被拒（RegCreateKeyEx 错误 5 拒绝访问）→
    致命异常 → **回滚**，于是表现为 **rc=4 + 有安装日志 + 零文件落盘**，
    看起来像包坏了，其实包完全正常。

    只删「安装目录已经不存在」的僵尸项 —— 那是上一次验收/卸载没清干净留下的，
    不会碰到用户真正在用的安装。
    """
    try:
        import winreg
    except ImportError:                       # pragma: no cover
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _uninstall_key_path()) as k:
            try:
                loc = str(winreg.QueryValueEx(k, 'InstallLocation')[0])
            except FileNotFoundError:
                loc = ''
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if loc and Path(loc).exists():
        return None                            # 真实安装还在，��乱动
    try:
        import winreg as _wr
        with _wr.OpenKey(_wr.HKEY_CURRENT_USER,
                         r'Software\Microsoft\Windows\CurrentVersion\Uninstall',
                         0, _wr.KEY_ALL_ACCESS) as parent:
            _wr.DeleteKey(parent, Path(_uninstall_key_path()).name)
    except OSError as exc:
        return f'残留卸载项删除失败（{exc}）—— 安装可能因 RegCreateKeyEx 错误 5 回滚'
    return f'已清理僵尸卸载项（InstallLocation={loc or "<空>"}，目录已不存在）'


def drop_uninstall_key_for(install_dir: Path) -> None:
    """验收结束后删掉自己刚建的卸载项（安装目录也要删，否则留下悬空键）。"""
    try:
        import winreg
    except ImportError:                       # pragma: no cover
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _uninstall_key_path()) as k:
            try:
                loc = str(winreg.QueryValueEx(k, 'InstallLocation')[0])
            except FileNotFoundError:
                return
        if not loc:
            return
        if Path(loc).resolve() != install_dir.resolve():
            return                             # 不是我们建的，别动
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r'Software\Microsoft\Windows\CurrentVersion\Uninstall',
                           0, winreg.KEY_ALL_ACCESS) as parent:
            winreg.DeleteKey(parent, Path(_uninstall_key_path()).name)
    except OSError:
        pass


# ── flavor 判定 ────────────────────────────────────────────────────────────
def pyz_toc_names(exe_bytes: bytes) -> set[str]:
    """从 PyInstaller 单文件 exe 里抠出 PYZ 的模块名集合（**纯标准库**）。

    为什么自己解析而不用 PyInstaller：
      * 验收工具应当**零依赖** —— PyInstaller 只在打包时需要，不该成为发布前
        验收的前置条件；
      * 沙箱/受限环境下 ``PyInstaller`` 可能根本装不上或装在别的解释器里。

    PYZ 格式（PyInstaller ≥ 4）::

        b'PYZ\\x00'        magic
        <4B>              python magic
        <4B big-endian>   TOC 偏移（相对 PYZ 块起点）
        ...               各条目（zlib 压缩的 marshal 数据）
        <TOC 偏移处>      marshal 化的 TOC

    TOC 的形态**随 PyInstaller 版本而变**：
      * 旧版 = dict：``{'模块名': (typecode, offset, length)}``
      * PyInstaller 6 = **list**：``[('模块名', (typecode, offset, length)), ...]``
    两种都要认。

    exe 里 PYZ 是**连续存放**的一段字节，所以按 magic 定位起点即可。
    """
    import marshal
    import struct

    idx = exe_bytes.find(b'PYZ\x00')
    if idx < 0:
        raise ValueError('exe 里找不到 PYZ 块')
    toc_pos = struct.unpack('!i', exe_bytes[idx + 8:idx + 12])[0]
    toc = marshal.loads(exe_bytes[idx + toc_pos:])
    if isinstance(toc, dict):
        return set(toc.keys())
    if isinstance(toc, list):
        out = set()
        for item in toc:
            if isinstance(item, (tuple, list)) and item:
                out.add(str(item[0]))
        return out
    raise ValueError(f'未知的 PYZ TOC 类型: {type(toc)}')


def flavor_of_exe(exe: Path, work_dir: Path | None = None) -> str:
    """返回 'internal' / 'release' / 'unknown(...)' —— 基于 PYZ 的 TOC 判定。

    绝不要用「grep 二进制里有没有 polyxrd._build_flavor」来判 —— release 版也有那个
    字符串（它在 build_flavor.pyc 的常量池里）。
    """
    try:
        names = pyz_toc_names(exe.read_bytes())
    except Exception as exc:
        return f'unknown({exc})'
    return 'internal' if FLAVOR_MARKER_MOD in names else 'release'


# ── 小工具 ─────────────────────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.items: dict[str, bool] = {}
        self.detail: dict[str, str] = {}

    def check(self, name: str, ok: bool, note: str = '') -> bool:
        self.items[name] = bool(ok)
        if note:
            self.detail[name] = note
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"   {note}" if note else ''))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(self.items.values())

    def dump(self) -> None:
        print('\n--- 机器可读结果 ---')
        print(json.dumps({'checks': self.items, 'detail': self.detail},
                         ensure_ascii=False, indent=2))


# ── 安装包验收 ─────────────────────────────────────────────────────────────
def verify_setup(setup: Path, scratch: Path | None = None,
                 expect_bundled: bool = True) -> Report:
    """静默安装并验收正式安装包（expect_bundled=False 用于纯客户端小包）。"""
    rep = Report()
    setup = setup.resolve()
    print(f'\n安装包 : {setup}  ({setup.stat().st_size:,} B)')

    # ── 坑 1：先拷出项目树 ──────────────────────────────────────────────
    scratch = pick_scratch(scratch)
    print(f'临时工作目录 : {scratch}   ← 必须离开带 safe-delete ACE 的目录')
    staged = scratch / f'{setup.stem}_verify{uuid.uuid4().hex[:6]}.exe'
    shutil.copy2(setup, staged)
    print(f'临时副本 : {staged}')

    inst = scratch / f'px_install_{uuid.uuid4().hex[:8]}'
    log = scratch / f'px_install_{uuid.uuid4().hex[:8]}.log'
    try:                                   # 兜底：安装目标绝不能落回仓库树
        inst.resolve().relative_to(REPO_ROOT)
        raise RuntimeError('安装目标落在仓库树内 —— 会被 safe-delete ACE 拒绝写入，'
                           '安装将回滚（rc=4）。这不该发生，请检查 pick_scratch()。')
    except ValueError:
        pass
    for p in (inst, log):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()

    stale = clear_stale_uninstall_key()
    if stale:
        print(f'卸载项清理 : {stale}')

    try:
        proc = subprocess.run(
            [str(staged), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
             f'/DIR={inst}', f'/LOG={log}'],
            capture_output=True, text=True, timeout=1800)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = 'timeout'

    rep.check('静默安装 rc=0', rc == 0, f'rc={rc}')
    rep.check('生成了安装日志', log.exists(),
              f'{log.name} {log.stat().st_size if log.exists() else 0:,} B')

    exe = inst / 'PolyXRD.exe'
    if not rep.check('PolyXRD.exe 已落盘', exe.exists(),
                     f'{exe.stat().st_size if exe.exists() else 0:,} B'):
        rep.dump()
        # v4.1.1: 失败路径也要清理临时副本/安装目录，避免在临时区留几百 MB
        shutil.rmtree(inst, ignore_errors=True)
        log.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
        return rep

    files = [p for p in inst.rglob('*') if p.is_file()]
    rep.check('落盘文件数 > 10000', len(files) > 10000, f'{len(files):,} 个')

    # ── 内置库 8/8（v4.1.1 动态取库名；v4.1.2 支持纯客户端小包）──────────
    if not expect_bundled:
        db_files = [p for p in (inst / 'databases').rglob('*')
                    if p.is_file()] if (inst / 'databases').is_dir() else []
        rep.check('纯客户端小包（无内置库）', not db_files, f'{len(db_files)} 个文件')
    else:
        libs = sorted((inst / 'databases').glob(BUNDLED_LIB_GLOB)) \
            if (inst / 'databases').is_dir() else []
        if not rep.check('安装包含内置 polyDB 默认库', bool(libs),
                         f'{len(libs)} 个'):
            rep.dump()
            return rep
        for lib in libs:
            have = [s for s in POLYDB_SEGMENTS if (lib / s).is_file()]
            rep.check(f'内置库 {lib.name} 8/8 分段齐全',
                      len(have) == len(POLYDB_SEGMENTS), f'{len(have)}/8')

    # 意外业务库：polyDB 容器**自身**的 index.sqlite 是它的合法分段，不能算；
    # pymatgen 的对称性数据表是依赖的一部分，也放行。
    stray = []
    for p in inst.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in BANNED_DB_SUFFIX:
            continue
        rel = str(p.relative_to(inst)).replace('\\', '/')
        if '/'.join(rel.split('/')[:2]).endswith('.polyDB') or rel.startswith('databases/'):
            continue
        if any(rel.endswith(a) for a in ALLOWED_DB_FILES):
            continue
        stray.append(rel)
    rep.check('无意外业务库文件', not stray, f'{stray[:5]}')

    # ── flavor ──────────────────────────────────────────────────────────
    fl = flavor_of_exe(exe, scratch)
    rep.check('安装包 exe 为 **release** 变体', fl == 'release', f'flavor={fl}')

    # ── 无便携版专属文件 ────────────────────────────────────────────────
    leaked = [n for n in PORTABLE_ONLY_FILES if (inst / n).exists()]
    rep.check('安装包内无便携版专属文件', not leaked, f'{leaked}')

    shutil.rmtree(inst, ignore_errors=True)
    drop_uninstall_key_for(inst)
    log.unlink(missing_ok=True)
    staged.unlink(missing_ok=True)
    return rep


# ── 便携包对照 ─────────────────────────────────────────────────────────────
def verify_portable(zpath: Path, scratch: Path | None = None,
                    expect_bundled: bool = True) -> Report:
    """便携包必须是 internal 变体，且带便携版辅助文件。"""
    rep = Report()
    zpath = zpath.resolve()
    print(f'\n便携包 : {zpath}  ({zpath.stat().st_size:,} B)')
    scratch = pick_scratch(scratch)
    print(f'临时工作目录 : {scratch}')

    with zipfile.ZipFile(zpath) as zf:
        names = {n.replace('\\', '/') for n in zf.namelist()}
        exe_entries = [n for n in names if n.endswith('PolyXRD.exe')]
        if not rep.check('便携包内含 PolyXRD.exe', bool(exe_entries)):
            rep.dump()
            return rep
        tmp = scratch / f'_port_{uuid.uuid4().hex[:8]}.exe'
        with zf.open(exe_entries[0]) as src, open(tmp, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        # v4.1.1: 动态取库名（换库不再误报）
        lib_dirs = sorted({
            m.group(1) for n in names
            for m in [re.match(r'.*databases/([^/]+\.polyDB)/', n)] if m
        })
        best = 0
        for lib in lib_dirs:
            got = sum(1 for s in POLYDB_SEGMENTS
                      if any(n.endswith(f'databases/{lib}/{s}') for n in names))
            best = max(best, got)
        if not expect_bundled:
            best = len(POLYDB_SEGMENTS) if not lib_dirs else -1
        helpers = [n for n in PORTABLE_ONLY_FILES
                   if any(x.endswith(n) for x in names)]
    try:
        fl = flavor_of_exe(tmp, scratch)
    finally:
        tmp.unlink(missing_ok=True)

    rep.check('便携包 exe 为 **internal** 变体', fl == 'internal', f'flavor={fl}')
    rep.check('便携包内置库 8/8 分段齐全', best == len(POLYDB_SEGMENTS), f'{best}/8')
    rep.check('便携包带便携版辅助文件', len(helpers) == len(PORTABLE_ONLY_FILES), f'{helpers}')
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='PolyXRD 发布安装包 / 便携包验收')
    ap.add_argument('target', type=Path, help='要验收的文件（Setup.exe 或 Portable.zip）')
    ap.add_argument('--portable', action='store_true',
                    help='按「便携包」口径验收（期望 internal 变体 + 便携版辅助文件）')
    ap.add_argument('--scratch', type=Path, default=None,
                    help='临时工作目录（默认 %%TEMP%%；**不要**指向带 safe-delete ACE 的目录）')
    ap.add_argument('--no-bundled-db', action='store_true',
                    help='按纯客户端小包验收（POLYXRD_NO_BUNDLE_DB=1 构建，应无内置库）')
    args = ap.parse_args(argv)

    if not args.target.is_file():
        print(f'文件不存在: {args.target}', file=sys.stderr)
        return 2

    expect_bundled = not args.no_bundled_db
    rep = verify_portable(args.target, args.scratch, expect_bundled) \
        if args.portable else verify_setup(args.target, args.scratch, expect_bundled)
    rep.dump()
    print('\nRESULT:', 'OK' if rep.ok else 'FAIL')
    return 0 if rep.ok else 1


if __name__ == '__main__':
    sys.exit(main())
