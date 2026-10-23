"""
M01 多格式导入测试 (Sprint 3)
==============================
"""
import numpy as np
import pytest

from polyxrd.services.data_io import (DataFormatError, detect_format,
                                      load_auto)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestDetectFormat:
    def test_by_extension(self, tmp_path):
        p = _write(tmp_path, "a.csv", "x,y\n1,2\n")
        assert detect_format(p) == "csv"
        p2 = _write(tmp_path, "a.xy", "1 2\n")
        assert detect_format(p2) == "xy"

    def test_shimadzu_header(self, tmp_path):
        p = _write(tmp_path, "s.txt",
                   "target Cu\nvoltage 40\ncurrent 30\nscan range 10-80\n"
                   "10.0 100\n20.0 50\n30.0 25\n")
        assert detect_format(p) == "shimadzu"


class TestLoadAuto:
    def test_two_column_txt(self, tmp_path):
        p = _write(tmp_path, "d.txt",
                   "# comment\n10.0 100\n20.0 200\n30.0 300\n")
        d = load_auto(p)
        assert len(d) == 3
        assert d.two_theta[1] == 20.0 and d.intensity[2] == 300.0

    def test_csv_with_header(self, tmp_path):
        p = _write(tmp_path, "d.csv", "2theta,counts\n28.0,50\n28.1,80\n28.2,60\n")
        d = load_auto(p)
        assert abs(d.two_theta[1] - 28.1) < 1e-9 and d.intensity[0] == 50.0

    def test_multicolumn_auto_pick_signal_column(self, tmp_path):
        # 四列: 2θ, 恒定背景, 计数率(剧烈变动), 温度
        rows = [f"{20.0+i*0.1:.1f} 5.0 {100.0*(i % 5)+10.0} {i:.1f}"
                for i in range(12)]
        p = _write(tmp_path, "m.txt", "\n".join(rows))
        d = load_auto(p)
        meta = d.metadata
        assert meta["x_col"] == 0, meta
        assert meta["y_col"] == 2, f"应选计数率列(变动最剧烈), 实际 y_col={meta['y_col']}"
        assert d.intensity[0] == 10.0     # 100*(0%5)+10
        assert d.intensity[1] == 110.0

    def test_explicit_columns(self, tmp_path):
        rows = [f"{i} {20+i} {10*i}" for i in range(5)]  # 2θ 在列1
        p = _write(tmp_path, "e.txt", "\n".join(rows))
        d = load_auto(p, x_col=1, y_col=2)
        assert d.two_theta[0] == 20.0 and d.intensity[1] == 10.0

    def test_empty_raises(self, tmp_path):
        p = _write(tmp_path, "e.txt", "header only no numbers")
        with pytest.raises(DataFormatError):
            load_auto(p)

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_auto(tmp_path / "none.txt")


# ─────────────────────────────────────────────────────────────────
# v4.0.0 回归: 列选择 / 欧式小数 / 残行 / 有效行不足 (svc-data)
# ─────────────────────────────────────────────────────────────────

class TestColumnAndNumberParsing:
    """实测缺陷:
      - 三列文件只给 y_col 时被自动列选择覆盖, 静默选错强度列;
      - 分号分隔的欧式导出 ``20,5;100,5`` 被当千位分隔符, 20.5→205, 100.5→1005;
      - 列数不一致的残行让 np.asarray 抛 "setting an array element with a sequence";
      - 有效行 <3 时抛模型的 "数据点数量必须 >= 3" (无文件名/无定位信息)。
    """

    def test_explicit_y_col_only_is_honored(self, tmp_path):
        # 列2 数值变化最剧烈 (会被自动列选择挑中), 显式 y_col=1 必须优先
        rows = [f"{i} {20+i} {10*i}" for i in range(5)]
        p = _write(tmp_path, "three_col.txt", "\n".join(rows))
        d = load_auto(p, y_col=1)
        assert d.metadata["x_col"] == 0 and d.metadata["y_col"] == 1, d.metadata
        assert d.intensity.tolist() == [20.0, 21.0, 22.0, 23.0, 24.0]

    def test_european_decimal_comma(self, tmp_path):
        text = "2theta;intensity\n20,5;100,5\n21,5;200,5\n22,5;300,5\n"
        p = _write(tmp_path, "eu.xy", text)
        d = load_auto(p)
        assert d.two_theta.tolist() == pytest.approx([20.5, 21.5, 22.5])
        assert d.intensity.tolist() == pytest.approx([100.5, 200.5, 300.5])

    def test_ragged_rows_keep_modal_width(self, tmp_path):
        # 前 3 行 2 列, 第 4 行多一列 (尾随注释列)
        text = "2theta counts\n20 100\n21 200\n22 300\n23 400 junk\n"
        p = _write(tmp_path, "ragged.xy", text)
        d = load_auto(p)
        assert len(d) == 3
        assert d.intensity.tolist() == [100.0, 200.0, 300.0]

    def test_too_few_valid_rows_message(self, tmp_path):
        p = _write(tmp_path, "short.xy", "2theta counts\n20 100\n21 200\n")
        with pytest.raises(DataFormatError) as ei:
            load_auto(p)
        assert "至少需要 3 行" in str(ei.value)

    def test_explicit_column_out_of_range(self, tmp_path):
        p = _write(tmp_path, "two.xy", "10 100\n11 200\n12 300\n")
        with pytest.raises(DataFormatError):
            load_auto(p, x_col=0, y_col=5)
