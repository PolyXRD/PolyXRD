#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UTF-8 静态守卫 (v1.1.1)
========================

扫描 ``src/polyxrd`` 下所有 Python 文件, 找出**依赖平台默认编码**的文本 I/O:
同一个 exe 在中文 (GBK) / 日文 (CP932) / 英文 (CP1252) Windows 上会得到不同结果,
典型症状是导出文件、日志、配置换一台机器打开就是乱码。

检查项 (用 ``tokenize`` 做词法级判断 —— 注释与字符串里的 ``open()`` 不算):

  1. ``open(...)`` / ``io.open(...)``                 文本模式且未指定 ``encoding=``
  2. ``Path.read_text`` / ``Path.write_text``         未指定 ``encoding=``
  3. ``subprocess.run/Popen/...``                     未指定 ``encoding=`` 或 ``text=True``
  4. ``logging.FileHandler`` / ``logging.basicConfig`` 未指定 ``encoding=``

``open`` 的**二进制模式** (``"rb"`` / ``"wb"`` / ``"r+b"`` …) 与编码无关, 自动跳过。

用法::

    python scripts/check_utf8_encoding.py             # 检查, 有发现则 exit 1
    python scripts/check_utf8_encoding.py --summary   # 只打印统计

编码约定 (见 docs/CHANGELOG.md v1.1.1):
  * **读取**面向用户的文本 (仪器导出 / Excel 导出的 CSV / 峰表) 用 ``utf-8-sig``
    —— 这类文件常带 BOM, 用 ``utf-8`` 会让首行首列多出 ``\\ufeff`` 导致解析失败
    (峰表会静默丢掉第一个峰)。
  * **写给 Excel / WPS 打开的 CSV** (表头含中文) 也用 ``utf-8-sig``, 否则按系统
    ANSI 代码页解释必然乱码。
  * **程序间交换的数据文件** (.xy / .dat / 峰表) 用 ``utf-8`` 且不加 BOM,
    避免第三方解析器把 BOM 当成数据。
"""
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "polyxrd"

_SUBPROC_NAMES = {"run", "Popen", "check_output", "check_call", "call"}


def _split_args(inner):
    """Split a call's token list into argument groups at depth-0 commas."""
    args, cur, depth = [], [], 0
    for t in inner:
        if t.type == tokenize.OP and t.string in "([{":
            depth += 1
        elif t.type == tokenize.OP and t.string in ")]}":
            depth -= 1
        if depth == 0 and t.type == tokenize.OP and t.string == ",":
            args.append(cur)
            cur = []
            continue
        cur.append(t)
    if cur:
        args.append(cur)
    return args


def _is_binary_mode(inner) -> bool:
    """True when the ``mode`` argument of an ``open()`` call is binary.

    Only the mode argument is inspected (2nd positional, or ``mode=``) so that a
    path containing the letter ``b`` is not mistaken for a binary mode.
    """
    args = _split_args(inner)
    mode_tokens = []
    for idx, t in enumerate(inner):
        if (t.type == tokenize.NAME and t.string == "mode"
                and idx + 2 < len(inner)
                and inner[idx + 1].type == tokenize.OP
                and inner[idx + 1].string == "="):
            mode_tokens = [inner[idx + 2]]
            break
    if not mode_tokens and len(args) >= 2:
        mode_tokens = [t for t in args[1] if t.type == tokenize.STRING]
    return any("b" in t.string for t in mode_tokens)


def _call_text(src: str, toks, i_open: int, i_close: int) -> str:
    """Slice the source between two ``tokenize`` token indices."""
    start = toks[i_open].start
    end = toks[i_close].end
    lines = src.splitlines(keepends=True)
    if start[0] == end[0]:
        return lines[start[0] - 1][start[1]:end[1]]
    parts = [lines[start[0] - 1][start[1]:]]
    parts.extend(lines[start[0]:end[0] - 1])
    parts.append(lines[end[0] - 1][:end[1]])
    return "".join(parts)


def _label_for(name: str, attr: bool, owner: str | None) -> str | None:
    if name == "open":
        return "io.open" if attr and owner == "io" else ("open" if not attr else None)
    if name in ("read_text", "write_text"):
        return name if attr else None
    if name in _SUBPROC_NAMES:
        return "subprocess" if attr and owner == "subprocess" else None
    if name == "FileHandler":
        return "FileHandler"
    if name == "basicConfig" and attr and owner in ("logging", "log"):
        return "basicConfig"
    return None


def _scan_source(src: str, rel: str) -> list[str]:
    out: list[str] = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        return [f"{rel}: tokenize 失败 ({exc})"]

    for i, tok in enumerate(toks):
        if tok.type != tokenize.NAME:
            continue
        name = tok.string
        # owner: `io.open` / `subprocess.run` / `p.read_text`
        attr = bool(i >= 2 and toks[i - 1].type == tokenize.OP
                    and toks[i - 1].string == ".")
        owner = toks[i - 2].string if attr and toks[i - 2].type == tokenize.NAME else None
        label = _label_for(name, attr, owner)
        if label is None:
            continue
        # next meaningful token must be '('
        j = i + 1
        while j < len(toks) and toks[j].type in (
                tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                tokenize.INDENT, tokenize.DEDENT):
            j += 1
        if j >= len(toks) or not (toks[j].type == tokenize.OP and toks[j].string == "("):
            continue
        # walk to the matching ')'
        depth = 0
        k = j
        while k < len(toks):
            if toks[k].type == tokenize.OP and toks[k].string in "([{":
                depth += 1
            elif toks[k].type == tokenize.OP and toks[k].string in ")]}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if k >= len(toks):
            continue
        inner = toks[j + 1:k]
        call = _call_text(src, toks, j, k)

        # encoding / text=True already given?
        names = {t.string for t in inner if t.type == tokenize.NAME}
        if "encoding" in names or "universal_newlines" in names:
            continue
        if "text" in names:
            continue

        # subprocess: encoding only matters when a pipe is actually decoded
        if label == "subprocess":
            if "capture_output" not in names and "PIPE" not in names:
                continue

        # binary mode is encoding-agnostic: look only at the *mode* argument
        # (2nd positional, or mode=), never at the path (which may contain "b")
        if label in ("open", "io.open"):
            if _is_binary_mode(inner):
                continue
        out.append(f"{rel}:{tok.start[0]}: [{label}] {' '.join(call.split())[:88]}")
    return out


def scan() -> list[str]:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(f"{rel}: 无法按 UTF-8 读取 ({exc})")
            continue
        findings.extend(_scan_source(src, rel))
    return findings


_SELFTEST_SRC = '''
import io, subprocess, logging
from pathlib import Path

def should_flag():
    f = open("out.txt", "w")
    Path("a.txt").read_text()
    subprocess.run(["x"], capture_output=True)
    with io.open("c.txt", "r") as fh:
        pass
    logging.basicConfig(filename="l.log")

def should_not_flag():
    # open("commented.txt", "w")   -- comment, must be ignored
    open("plain.txt", "w", encoding="utf-8")
    open("binary.bin", "wb")       # binary mode
    open("weird.b.name", "w", encoding="utf-8")
    Path("b.txt").read_text(encoding="utf-8-sig")
    subprocess.run(["x"])          # no pipe -> not text I/O
    subprocess.run(["x"], capture_output=True, encoding="utf-8")
    subprocess.Popen(["gui"], cwd=".")   # fire-and-forget
    logging.FileHandler("x.log", encoding="utf-8")
    s = "open(x.txt, w)"           # inside a string literal
'''
_SELFTEST_EXPECTED_LINES = [6, 7, 8, 9, 11]


def selftest() -> int:
    """Guard the guard: it must catch real offenders and ignore non-offenders."""
    found = _scan_source(_SELFTEST_SRC, "selftest.py")
    lines = sorted({int(f.split(":")[1]) for f in found})
    print("selftest findings:")
    for f in found:
        print("  " + f)
    ok = lines == _SELFTEST_EXPECTED_LINES
    print(f"flagged lines {lines} vs expected {_SELFTEST_EXPECTED_LINES}")
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    findings = scan()
    summary_only = "--summary" in sys.argv
    n_files = len({f.split(":")[0] for f in findings})
    print(f"扫描目录: {ROOT}")
    print(f"未指定 encoding 的文本 I/O: {len(findings)} 处 (涉及 {n_files} 个文件)")
    if findings and not summary_only:
        print()
        for f in findings:
            print("  " + f)
    if findings:
        print('\nFAIL: 文本 I/O 必须显式指定 encoding (读取用户数据用 "utf-8-sig",'
              ' 其余用 "utf-8")。')
        return 1
    print("OK: 所有文本 I/O 均已显式指定编码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
