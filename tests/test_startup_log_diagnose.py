"""启动日志判读器单测（P0-1 配套）。

判读表是 P0-1 的"最后一公里"：探针已在 v5.2 落地，现场拿到日志后必须能
一条命令定位阶段。这里用**真实日志行格式**（`[时间] [pid=N] 消息`）钉住
判定逻辑，并覆盖现场那 15 次启动的两种失败形态（A 组 PermissionError 前
无 context、B 组停在 showing main window）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_diag_startup", ROOT / "scripts" / "diagnose_startup_log.py")
    mod = importlib.util.module_from_spec(spec)
    # dataclass 装饰器要求模块已注册（否则 sys.modules[cls.__module__] 为 None）
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


D = _load()

CTX = ("[2026-10-29 14:02:02] [pid=4884] context: admin=True "
       "remote_session=False cif_db='C:\\Program Files\\PolyXRD\\cod_data\\cif_db' "
       "exists=True writable=False opengl=<unset> qpa=<unset> dpi_scale=<unset>")


def _log(*lines: str) -> str:
    return "\n".join(lines)


class TestParse:
    def test_parses_pid_and_milestones(self):
        text = _log(
            "[2026-10-29 14:20:42] [pid=4312] QApplication OK",
            "[2026-10-29 14:20:42] [pid=4312] context: admin=True "
            "remote_session=False cif_db='x' exists=True writable=True "
            "opengl=<unset> qpa=<unset> dpi_scale=<unset>",
            "[2026-10-29 14:20:43] [pid=4312] showing main window",
            "[2026-10-29 14:20:43] [pid=4312] shown visible=True",
            "[2026-10-29 14:20:43] [pid=4312] first-paint",
            "[2026-10-29 14:20:43] [pid=4312] ui-tick0",
            "[2026-10-29 14:20:43] [pid=4312] settled",
        )
        recs = D.parse_log(text)
        assert len(recs) == 1
        r = recs[0]
        assert r.pid == 4312
        assert r.context["admin"] == "True"
        assert r.context["writable"] == "True"
        assert r.context["cif_db"] == "x"
        assert "settled" in r.seen

    def test_context_with_spaces_in_path_parses_whole(self):
        """现场路径含空格（Program Files）—— 引号包裹的值必须整体取出。"""
        r = D.parse_log(CTX)[0]
        assert r.context["cif_db"] == (
            "C:\\Program Files\\PolyXRD\\cod_data\\cif_db")
        assert r.context["exists"] == "True"
        assert r.context["writable"] == "False"

    def test_interleaved_two_instances_are_split_by_pid(self):
        text = _log(
            "[2026-10-29 14:22:46] [pid=1604] context: admin=True "
            "remote_session=False cif_db='x' exists=True writable=True "
            "opengl=<unset> qpa=<unset> dpi_scale=<unset>",
            "[2026-10-29 14:22:47] [pid=1708] context: admin=True "
            "remote_session=False cif_db='x' exists=True writable=True "
            "opengl=<unset> qpa=<unset> dpi_scale=<unset>",
            "[2026-10-29 14:22:47] [pid=1708] showing main window",
            "[2026-10-29 14:22:46] [pid=1604] showing main window",
            "[2026-10-29 14:22:48] [pid=1708] shown visible=True",
            "[2026-10-29 14:22:48] [pid=1708] settled",
        )
        recs = {r.pid: r for r in D.parse_log(text)}
        assert set(recs) == {1604, 1708}
        assert "settled" in recs[1708].seen
        assert "settled" not in recs[1604].seen

    def test_non_probe_lines_are_kept_but_not_milestones(self):
        text = _log("[2026-10-29 14:00:00] [pid=1] faulthandler enabled")
        r = D.parse_log(text)[0]
        assert r.seen == []
        assert any("faulthandler" in ln for ln in r.lines)


class TestJudge:
    def _rec(self, *msgs):
        body = _log(*[f"[2026-10-29 14:00:00] [pid=9] {m}" for m in msgs])
        return D.parse_log(body)[0]

    def test_completed(self):
        r = self._rec("context: admin=True", "showing main window",
                      "shown visible=True", "ui-tick0", "first-paint",
                      "settled")
        assert D.judge(r)[0] == "completed"

    def test_show_call_stage(self):
        """B 组现场：停在 showing main window。"""
        r = self._rec("context: admin=True", "showing main window")
        stage, hint = D.judge(r)
        assert stage == "show-call"
        assert "平台窗口创建" in hint

    def test_mapped_stage(self):
        r = self._rec("context: admin=True", "showing main window",
                      "shown visible=True")
        assert D.judge(r)[0] == "mapped"

    def test_first_paint_stage(self):
        r = self._rec("context: admin=True", "showing main window",
                      "shown visible=True", "ui-tick0")
        assert D.judge(r)[0] == "first-paint"

    def test_after_first_paint_stage(self):
        r = self._rec("context: admin=True", "showing main window",
                      "shown visible=True", "ui-tick0", "first-paint")
        assert D.judge(r)[0] == "after-first-paint"

    def test_construct_stage(self):
        r = self._rec("context: admin=True")
        assert D.judge(r)[0] == "construct"

    def test_pre_context_stage(self):
        """A 组：崩在 QApplication 之前（旧版连 context 都没有）。"""
        r = self._rec("faulthandler enabled")
        assert D.judge(r)[0] == "pre-context"

    def test_alive_pid_not_counted_as_failure(self):
        r = self._rec("context: admin=True", "showing main window")
        assert D.judge(r, alive=True)[0] == "running"


class TestSummarize:
    def test_counts_and_context_grouping(self):
        text = _log(
            CTX.replace("pid=4884", "pid=101"),
            "[2026-10-29 14:02:03] [pid=101] showing main window",
            CTX.replace("pid=4884", "pid=102"),
            "[2026-10-29 14:02:04] [pid=102] showing main window",
            "[2026-10-29 14:02:04] [pid=102] shown visible=True",
            "[2026-10-29 14:02:04] [pid=102] settled",
        )
        s = D.summarize(D.parse_log(text))
        assert s["total_launches"] == 2
        assert s["failures"] == 1
        assert s["by_stage"]["show-call"] == 1
        assert s["by_stage"]["completed"] == 1
        ck = [k for k in s["by_context"]][0]
        assert "writable=False" in ck
        assert s["by_context"][ck]["fail"] == 1
        # 同一 context 下成功也计入（这里 102 的 writable=True 是另一键）
        assert any(v["ok"] == 1 for v in s["by_context"].values())

    def test_report_mentions_failure_stage(self):
        text = _log(
            CTX, "[2026-10-29 14:02:03] [pid=4884] showing main window")
        rep = D.format_report(D.summarize(D.parse_log(text)))
        assert "平台窗口创建" in rep
        assert "pid=4884" in rep

    def test_main_cli_json(self, tmp_path, capsys):
        log = tmp_path / "startup-2026-10-29.log"
        log.write_text(_log(CTX,
                            "[2026-10-29 14:02:03] [pid=4884] showing main window"),
                       encoding="utf-8")
        assert D.main(["--json", str(log)]) == 0
        import json
        got = json.loads(capsys.readouterr().out)
        assert got["total_launches"] == 1
        assert got["rows"][0]["stage"] == "show-call"

    def test_main_missing_file_returns_2(self, tmp_path):
        assert D.main([str(tmp_path / "nope.log")]) == 2
