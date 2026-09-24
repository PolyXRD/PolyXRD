"""
run_dev.bat 的结构护栏。

背景: 首版 run_dev.bat 双击**闪退**。根因不是 Python (程序本身稳定运行 12s 以上),
而是 bat 自己:
  `echo ... (见 README / handover 文档)` 里的**裸 `)`** 提前闭合了
  `if not exist (...)` 代码块 —— cmd.exe 的经典陷阱。后续的 pause / exit / )
  被当成顶层语句, 解析失败 → cmd 放弃执行整个 bat → 控制台一闪就关,
  `pause` 根本没机会运行(所以连报错都看不到)。

另外两个隐患:
  - 文件是 LF 换行: cmd 对 goto/标签按字节偏移定位, 需要 CRLF。
  - `endlocal` 之后才展开 `%RC%`: setlocal 已丢弃变量 → 退出码恒为 0。

本文件把这些约束固化成断言, 避免以后有人"顺手改回中文注释/加个括号"再翻车。

约定: 所有断言只看**有效命令行**(去掉 REM 注释与空行), 因为注释里解释这些
危险写法时会合法地提到它们。
"""
from __future__ import annotations

from pathlib import Path

import pytest

BAT = Path(__file__).resolve().parents[1] / "run_dev.bat"


@pytest.fixture(scope="module")
def raw() -> bytes:
    assert BAT.is_file(), f"缺少 {BAT}"
    return BAT.read_bytes()


@pytest.fixture(scope="module")
def lines(raw: bytes) -> list[str]:
    """按**通用换行**切成行 (不含行尾符)。

    刻意不在 \r\n 上切分: 若文件是纯 LF, `split("\\r\\n")` 会把整份文件当成
    一行, 后面所有基于行的结构校验就会**空转通过** —— 等于护栏失效。
    换行风格由 TestLineEndings 单独负责, 这里只关心"每一行写了什么"。
    解码用 errors='replace': 非 ASCII 由 test_pure_ascii 单独报错, 结构校验
    仍能跑完并给出精确诊断, 而不是级联成一片 ERROR。
    """
    text = raw.decode("ascii", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


@pytest.fixture(scope="module")
def effective(lines: list[str]) -> list[str]:
    """只看真正会被 cmd 执行的命令行: 去掉空行与 REM 注释。"""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.upper().startswith("REM"):
            continue
        out.append(ln)
    return out


class TestLineEndings:
    def test_all_line_endings_are_crlf(self, raw):
        assert b"\r\n" in raw
        assert raw.replace(b"\r\n", b"").count(b"\n") == 0, \
            "存在裸 LF 换行; cmd 对标签/跳转按字节偏移定位, 必须统一 CRLF"

    def test_ends_with_crlf(self, raw):
        assert raw.endswith(b"\r\n"), "最后一行缺 CRLF 会让末字符被吞"


class TestEncoding:
    def test_pure_ascii(self, raw):
        """非 ASCII 会被 cmd 按 OEM 代码页(936)误读。

        首版的 ')' 问题正出在中文注释里, 所以连编码一起禁掉。
        """
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as e:  # pragma: no cover - 失败路径
            pytest.fail(f"run_dev.bat 含非 ASCII 字节: {e}")

    def test_no_bom(self, raw):
        assert not raw.startswith(b"\xef\xbb\xbf"), "带 BOM 会让首行命令报错"


class TestCmdParsingHazards:
    """把会导致 cmd.exe 解析崩溃的写法全部拦下。"""

    def test_no_parens_in_if_lines(self, effective):
        """if 行里出现裸括号 → 块被提前闭合 → 整个 bat 解析失败。

        这是首版闪退的直接原因, 是最重要的一条断言。
        """
        bad = [
            ln for ln in effective
            if ln.strip().lower().startswith("if") and ("(" in ln or ")" in ln)
        ]
        assert not bad, f"if 行里出现括号, cmd 会崩: {bad}"

    def test_no_multiline_if_blocks(self, effective):
        """禁止 `if ... (` 这种多行块 —— 少一处能出错的地方。"""
        for ln in effective:
            s = ln.strip().lower()
            if s.startswith("if") and s.endswith("("):
                pytest.fail(f"使用了多行 if 块, 请改成单行 if 语句: {ln!r}")

    def test_no_parens_inside_echo_text(self, effective):
        """echo 文本里的括号同样会打断块结构 (且容易被忽略)。"""
        for ln in effective:
            s = ln.strip().lower()
            if s.startswith("echo") and ("(" in s or ")" in s):
                pytest.fail(f"echo 文本含括号, 需转义或改写: {ln!r}")

    def test_no_setlocal_endlocal(self, effective):
        """setlocal/endlocal 会丢变量: endlocal 之后 `%RC%` 恒为空。"""
        for ln in effective:
            s = ln.strip().lower()
            assert "setlocal" not in s, f"不要用 setlocal: {ln!r}"
            assert "endlocal" not in s, f"不要用 endlocal: {ln!r}"

    def test_no_goto_or_labels(self, effective):
        """没有标签/跳转就没有字节偏移定位问题, 少一类风险。"""
        for ln in effective:
            s = ln.strip().lower()
            assert not s.startswith("goto"), f"用了 goto: {ln!r}"
            assert not (s.startswith(":") and len(s) > 1), f"定义标签: {ln!r}"


class TestFunctionalityKept:
    """护栏不能把功能一起锁死 —— 该干的事还得干。"""

    def test_launches_module(self, effective):
        joined = "\n".join(effective)
        assert "polyxrd.main" in joined, "必须启动 polyxrd.main"

    def test_sets_pythonpath_to_src(self, effective):
        joined = "\n".join(effective).lower()
        assert "pythonpath" in joined and "src" in joined, \
            "必须把 src 加进 PYTHONPATH, 否则 polyxrd 包导不进来"

    def test_invokes_venv_python(self, effective):
        joined = "\n".join(effective)
        assert "venv\\Scripts\\python.exe" in joined, \
            "必须调用 venv 里的 python.exe, 而不是系统 python"

    def test_pauses_on_failure(self, effective):
        """失败必须 pause, 否则窗口关掉就看不到回溯 —— 这次闪退的教训。"""
        joined = "\n".join(effective).lower()
        assert "pause" in joined, "缺少 pause: 崩溃时窗口会直接关掉"

    def test_pause_is_guarded_by_errorlevel(self, effective):
        """pause 必须只在失败时触发, 否则正常关窗后还要按一次键。

        用 `if errorlevel 1 pause` 这个最老牌的写法: 无变量、无引号比较、无括号。
        """
        joined = "\n".join(effective).lower()
        assert "if errorlevel" in joined, "应当用 `if errorlevel 1 pause` 判断失败"

    def test_echoes_nothing_fancy(self, effective):
        """至少给用户看到它在干什么 (首版连报错都看不到)。"""
        joined = "\n".join(effective)
        assert "echo" in joined.lower(), "应有 echo 提示, 方便定位问题"


class TestConsistency:
    def test_run_dev_documented_in_readme(self):
        readme = BAT.parent / "README.md"
        assert readme.is_file()
        assert "run_dev.bat" in readme.read_text(encoding="utf-8"), \
            "README 应说明 run_dev.bat 的用途"

