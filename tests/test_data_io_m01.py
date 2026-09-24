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
