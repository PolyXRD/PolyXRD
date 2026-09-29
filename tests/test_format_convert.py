"""谱图格式转换的实测验证 (基于 test_xrd/geshi 的真实样例)。

可直接跑: python tests/test_format_convert.py
或 pytest:  pytest tests/test_format_convert.py -q

样例目录不在时整体 skip, 不阻塞其它回归。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from polyxrd.services.data_io import detect_format, load_auto          # noqa: E402
from polyxrd.services.pattern_convert import (                          # noqa: E402
    TARGET_EXTS,
    TARGET_FORMATS,
    convert_pattern_file,
    load_pattern,
    write_pattern,
)

GESHI = Path(r"D:/Project/XRD/test_xrd\geshi")
SAMPLE = GESHI / "4-1.dat"

pytestmark = pytest.mark.skipif(
    not SAMPLE.exists(), reason=f"样例目录不存在: {GESHI}"
)

# 实测基线 (见 .workbuddy/memory 记录)
N_FULL = 7251          # .dat/.txt/.xy/.raw 的点数
X0, X1 = 5.0, 150.0
Y0, Y1 = 207.0, 90.0
N_MDI = 7250           # .mdi 转换时丢了首点 207
MDI_X0 = 5.02


@pytest.fixture(scope="module")
def dat():
    return load_auto(SAMPLE)


# ----------------------------------------------------------------------
# 读取: 新增的 .mdi / .raw 必须与既有文本格式一致
# ----------------------------------------------------------------------

def test_text_family_is_identical(dat):
    """geshi 的 .txt / .xy 与 .dat 内容一致。"""
    for name in ("4-1.txt", "4-1.xy"):
        other = load_auto(GESHI / name)
        np.testing.assert_array_equal(other.two_theta, dat.two_theta)
        np.testing.assert_array_equal(other.intensity, dat.intensity)


def test_raw2_reads_exactly_like_dat(dat):
    """.raw (RAW2) 解析后与 .dat 完全一致 —— 头长 316 + 7251×float32。"""
    assert detect_format(GESHI / "4-1.raw") == "raw"
    raw = load_auto(GESHI / "4-1.raw")
    assert len(raw) == N_FULL
    assert raw.two_theta[0] == pytest.approx(X0)
    assert raw.two_theta[-1] == pytest.approx(X1)
    assert raw.intensity[0] == Y0
    assert raw.intensity[-1] == Y1
    # 角度轴由 start + step*i 生成, 与文本读出的十进制值只差浮点尾数
    np.testing.assert_allclose(raw.two_theta, dat.two_theta, rtol=0, atol=1e-6)
    np.testing.assert_array_equal(raw.intensity, dat.intensity)
    assert raw.metadata.get("raw2_header_len") == 316
    assert raw.wavelength == pytest.approx(1.5406, abs=1e-3)


def test_mdi_reads_with_dropped_first_point_corrected(dat):
    """.mdi 少一个首点; 读端须用头里的 stop 反推 start, 否则整条谱平移一个步长。"""
    assert detect_format(GESHI / "4-1.mdi") == "mdi"
    mdi = load_auto(GESHI / "4-1.mdi")
    assert len(mdi) == N_MDI
    # 关键: 对齐到 150.000 (而非从 5.000 起算)
    assert mdi.two_theta[0] == pytest.approx(MDI_X0)
    assert mdi.two_theta[-1] == pytest.approx(X1)
    # 逐点等于 .dat 的第 2..末点 (角度轴浮点尾数允许 1e-6)
    np.testing.assert_allclose(mdi.two_theta, dat.two_theta[1:], rtol=0, atol=1e-6)
    np.testing.assert_array_equal(mdi.intensity, dat.intensity[1:])


# ----------------------------------------------------------------------
# 转换: 与原厂导出逐字节比对
# ----------------------------------------------------------------------

def test_convert_dat_to_txt_is_byte_identical(tmp_path):
    out = tmp_path / "4-1.txt"
    convert_pattern_file(SAMPLE, out, "txt")
    assert out.read_bytes() == (GESHI / "4-1.txt").read_bytes()


def test_convert_dat_to_xy_is_byte_identical(tmp_path):
    out = tmp_path / "4-1.xy"
    convert_pattern_file(SAMPLE, out, "xy")
    assert out.read_bytes() == (GESHI / "4-1.xy").read_bytes()


# ----------------------------------------------------------------------
# 往返: 每种目标格式写出后都要能读回, 且与源一致
# ----------------------------------------------------------------------

@pytest.mark.parametrize("key,ext", [t for t in TARGET_FORMATS if t[0] != "xrdml"])
def test_roundtrip_every_target(key, ext, dat, tmp_path):
    out = tmp_path / f"rt{ext}"
    write_pattern(dat, out, key)
    assert out.exists() and out.stat().st_size > 0
    back = load_pattern(out)
    assert len(back) == len(dat)
    np.testing.assert_allclose(back.two_theta, dat.two_theta, rtol=0, atol=1e-6)
    np.testing.assert_allclose(back.intensity, dat.intensity, rtol=0, atol=1e-9)


def test_roundtrip_through_mdi_and_back_keeps_full_range(dat, tmp_path):
    """.dat → .mdi → 读回: 不再平移 (start/stop 按实际首末点写)。"""
    mid = tmp_path / "a.mdi"
    write_pattern(dat, mid, "mdi")
    back = load_pattern(mid)
    assert back.two_theta[0] == pytest.approx(X0)
    assert back.two_theta[-1] == pytest.approx(X1)
    np.testing.assert_array_equal(back.intensity, dat.intensity)


def test_roundtrip_through_raw_and_back(dat, tmp_path):
    mid = tmp_path / "a.raw"
    write_pattern(dat, mid, "raw")
    back = load_pattern(mid)
    assert back.two_theta[0] == pytest.approx(X0)
    assert back.two_theta[-1] == pytest.approx(X1)
    np.testing.assert_array_equal(back.intensity, dat.intensity)
    # 自写文件的头长也应是 316
    assert back.metadata.get("raw2_header_len") == 316


def test_xrdml_target_writes_file(dat, tmp_path):
    out = tmp_path / "a.xrdml"
    write_pattern(dat, out, "xrdml")
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert "<xrdMeasurement" in text
    assert text.count("<positions>") == 1


# ----------------------------------------------------------------------
# 便利入口
# ----------------------------------------------------------------------

def test_convert_without_dst_swaps_extension(tmp_path):
    """dst=None → 同主名换扩展名。

    注意: 必须先把源文件**复制**到临时目录再转, 否则缺省推导出的目标名就是样例
    文件本身, 会把它覆盖掉(本特性开发中就踩过这个坑, 故转换器已加防呆)。
    """
    src = tmp_path / "4-1.dat"
    src.write_bytes(SAMPLE.read_bytes())
    out = convert_pattern_file(src, None, "mdi")
    assert out == src.with_suffix(TARGET_EXTS["mdi"])
    assert out.exists()
    # 我们自己写的 .mdi 是无损的 (start/count 按实际首点与点数写), 所以读回仍是
    # 5.0000 起、7251 点 —— 不会像原厂样例那样少一个首点。
    back = load_pattern(out)
    assert len(back) == N_FULL
    assert back.two_theta[0] == pytest.approx(X0)
    assert back.two_theta[-1] == pytest.approx(X1)
    np.testing.assert_array_equal(back.intensity, load_auto(SAMPLE).intensity)


def test_convert_refuses_to_overwrite_source(tmp_path):
    """输出路径 == 源文件时必须报错, 不许静默覆盖源文件。"""
    from polyxrd.services.data_io import DataFormatError

    src = tmp_path / "4-1.dat"
    src.write_bytes(SAMPLE.read_bytes())

    with pytest.raises(DataFormatError):
        convert_pattern_file(src, src, "dat")
    # dst=None 且目标扩展名与源相同时, 同样要拦下
    with pytest.raises(DataFormatError):
        convert_pattern_file(src, None, "dat")
    assert src.read_bytes() == SAMPLE.read_bytes()


def test_unsupported_format_raises(dat, tmp_path):
    from polyxrd.services.data_io import DataFormatError

    with pytest.raises(DataFormatError):
        write_pattern(dat, tmp_path / "x.foo", "foo")


def test_non_uniform_axis_rejected(tmp_path):
    """非等间距数据不能写 MDI/RAW2, 必须明确报错而不是悄悄写坏。"""
    from polyxrd.models.xrd_data import XRDData
    from polyxrd.services.data_io import DataFormatError

    x = np.array([10.0, 10.5, 12.0, 13.1, 15.0])
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    odd = XRDData(two_theta=x, intensity=y)
    with pytest.raises(DataFormatError):
        write_pattern(odd, tmp_path / "odd.mdi", "mdi")
    # 但两列文本应能写
    write_pattern(odd, tmp_path / "odd.xy", "xy")
    assert (tmp_path / "odd.xy").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
