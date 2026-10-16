# -*- coding: utf-8 -*-
"""注册机制单元测试（v2.10.0）。

这套测试锁的是**行为契约**，分为三块：

1. **注册码算法**（``generate_code`` / ``verify_code``）——算法实现逐字复用
   ``D:/Project/XRD/PolyXRD-Reg/registration.py``（家族单点实现），这里不重复
   发明轮子，只守住「往返一致 / 篡改必拒 / 格式容错」三条不可回退的性质。
2. **注册状态存取**（``load_state`` / ``save_state``）——含**防手改**：状态文件是
   明文 JSON，用户改得动，所以每次读取都用注册码重新算一遍单位名来兜底。
3. **构建变体探测**（``build_flavor``）——``_build_flavor.py`` 是构建期烧入的模块，
   **缺失/损坏一律回落到 release**（保守方向：宁可多要一次注册，也不能让内部版
   静默变成无人监管的"免注册正式版"）。

弹窗 / 菜单这类 Qt 交互由离屏探针覆盖，不进 pytest 套件（构造主窗口较重且易脆）。
"""
from __future__ import annotations

import importlib
import json
import sys
import types

import pytest

from polyxrd.utils import build_flavor, registration


# ==============================================================================
# 1. 注册码算法
# ==============================================================================
@pytest.mark.parametrize(
    "unit",
    [
        "清华大学材料学院",
        "PolyXRD Lab",
        "A",                 # 最短合法单位名（1 字符）
        "分析测试中心 (2026)",
        "X" * 100,           # 长度上限
        "多  空格  名称",      # 连续空白会被归一化
        "日本語テスト",
    ],
)
def test_generate_verify_roundtrip(unit: str) -> None:
    """任何合法单位名都能生成注册码，并由 verify_code 原样还原。"""
    expected = " ".join(unit.split())  # 归一化口径与 _normalize_unit 一致
    code = registration.generate_code(unit)
    assert code.startswith(registration.CODE_PREFIX + "-")
    assert registration.verify_code(code) == expected


def test_unit_name_is_normalized() -> None:
    """首尾空白被裁掉、连续空白被压成一个空格，且该归一化对使用者透明。"""
    code = registration.generate_code("  材料  学院  ")
    assert registration.verify_code(code) == "材料 学院"


def test_tampered_body_is_always_rejected() -> None:
    """穷举单字符变异：只要 Base32 还能解码，就必须被 HMAC 判定无效。

    这是「注册码不可guess」的核心性质 —— 允许 -1/+1 字符漂一位就能通过的算法
    等于没有校验。
    """
    unit = "某某大学材料系"
    body = registration.generate_code(unit)[len(registration.CODE_PREFIX):]
    body = body.replace("-", "")

    checked = 0
    for index in range(len(body)):
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567":
            if ch == body[index]:
                continue
            assert registration.verify_code(body[:index] + ch + body[index + 1:]) is None
            checked += 1
    assert checked > 0


def test_rejects_mac_borrowed_from_another_unit() -> None:
    """把自己的 MAC 拼给别人也必须失败（即 MAC 与单位名强绑定）。"""
    import base64

    def build(name: str, mac: bytes) -> str:
        payload = name.encode("utf-8") + b"\x00" + mac
        return base64.b32encode(payload).decode("ascii").rstrip("=")

    # 用「甲」的名字 + 空 MAC 伪装
    forged = build("甲方单位", b"\x00" * 8)
    assert registration.verify_code(forged) is None


@pytest.mark.parametrize(
    "transform",
    [
        lambda c: c,
        lambda c: c.lower(),
        lambda c: c[len(registration.CODE_PREFIX):],      # 不带前缀
        lambda c: c.replace("-", ""),
        lambda c: c.replace("-", "－"),                    # 全角连字符
        lambda c: c.replace("-", " "),                     # 用户复制成空格
        lambda c: f"  {c}  \n",                            # 首尾空白/换行
    ],
)
def test_input_format_tolerance(transform) -> None:
    """用户粘贴方式五花八门 —— 大小写、前后缀、连字符形态都不应影响核验。"""
    unit = "理化测试中心"
    assert registration.verify_code(transform(registration.generate_code(unit))) == unit


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "x", registration.CODE_PREFIX, "PXRD1-!!!!", "12345", "A" * 300],
)
def test_garbage_input_rejected(bad: str) -> None:
    """非法输入一律返回 None（而非抛异常）——调用方直接判 `is None` 即可。"""
    assert registration.verify_code(bad) is None


@pytest.mark.parametrize("ok_unit", ["材料\n学院", "材料\t学院"])
def test_whitespace_including_newline_is_normalized(ok_unit: str) -> None:
    """换行/制表符属于空白，被压成单个空格后仍合法。

    ⚠️ 后果：``"A\\nB"`` 与 ``"A B"`` 会生成**同一枚**注册码。这是刻意行为
    （免得用户从 Excel 粘一行名字就报错），不是缺陷 —— 但验收时要知道。
    """
    assert registration.verify_code(registration.generate_code(ok_unit)) == "材料 学院"


@pytest.mark.parametrize("bad_unit", ["", "   ", "X" * 101, "材料\x00学院", "材料\x01学院"])
def test_invalid_unit_rejected(bad_unit: str) -> None:
    """生成侧对非法单位名**明确报错**，不静默产出垃圾注册码。

    空串 / 纯空白 / 超长 / 含非空白控制字符（\x00 会破坏注册码的 0x00 分隔符）
    都拒绝。
    """
    with pytest.raises(ValueError):
        registration.generate_code(bad_unit)


def test_notice_wording_is_pinned() -> None:
    """版权提示文案按需求逐字固定，改动必须显式修改本测试。"""
    assert registration.UNREGISTERED_NOTICE == (
        "本软件未注册，版权所有，禁止用于商业用途。\n"
        "如需注册请联系 sshztx@outlook.com"
    )
    assert registration.CONTACT_EMAIL == "sshztx@outlook.com"


# ==============================================================================
# 2. 注册状态存取
# ==============================================================================
def test_missing_state_file_is_unregistered(tmp_path) -> None:
    assert registration.load_state(tmp_path / "nope.json").registered is False


def test_save_then_load_roundtrip(tmp_path) -> None:
    state_path = tmp_path / "registration.json"
    saved = registration.save_state(state_path, registration.generate_code("计量科学研究院"))

    assert saved.registered is True
    assert saved.unit == "计量科学研究院"
    assert registration.load_state(state_path) == saved


def test_save_rejects_invalid_code(tmp_path) -> None:
    with pytest.raises(ValueError):
        registration.save_state(tmp_path / "registration.json", "PXRD1-BADBAD")


def test_corrupt_state_file_is_unregistered(tmp_path) -> None:
    state_path = tmp_path / "registration.json"
    state_path.write_text("{not json", encoding="utf-8")
    assert registration.load_state(state_path).registered is False


def test_state_unit_tampering_rejected(tmp_path) -> None:
    """状态文件是明文 —— 手改 unit 必须被"重新算一遍注册码"当场识破。"""
    state_path = tmp_path / "registration.json"
    registration.save_state(state_path, registration.generate_code("原始单位"))

    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["unit"] = "随便改个单位名"
    state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert registration.load_state(state_path).registered is False


def test_state_code_removed_is_unregistered(tmp_path) -> None:
    state_path = tmp_path / "registration.json"
    registration.save_state(state_path, registration.generate_code("原始单位"))

    data = json.loads(state_path.read_text(encoding="utf-8"))
    data["code"] = ""
    state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert registration.load_state(state_path).registered is False


# ==============================================================================
# 3. 构建变体（flavor）
# ==============================================================================
@pytest.fixture(autouse=True)
def _clean_flavor_cache():
    """``build_flavor.flavor()`` 带进程级缓存，每个用例前后都要清干净。"""
    build_flavor._reset_cache()
    yield
    build_flavor._reset_cache()


def _inject_flavor_module(monkeypatch, value) -> None:
    module = types.ModuleType("polyxrd._build_flavor")
    if value is not None:
        module.BUILD_FLAVOR = value
    monkeypatch.setitem(sys.modules, "polyxrd._build_flavor", module)
    monkeypatch.setattr(sys.modules["polyxrd"], "_build_flavor", module, raising=False)


def test_flavor_defaults_to_release_when_module_absent(monkeypatch) -> None:
    """缺失 flavor 模块 = 正式发布版（保守默认：注册机制保留）。"""
    monkeypatch.delitem(sys.modules, "polyxrd._build_flavor", raising=False)
    assert build_flavor.flavor() == build_flavor.FLAVOR_RELEASE
    assert build_flavor.is_internal() is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("internal", "internal"),
        ("INTERNAL", "internal"),
        (" Internal ", "internal"),
        ("release", "release"),
        ("banana", "release"),   # 未知取值 -> 保守回落
        ("", "release"),
    ],
)
def test_flavor_detection_values(monkeypatch, value, expected) -> None:
    _inject_flavor_module(monkeypatch, value)
    assert build_flavor.flavor() == expected


def test_flavor_module_without_attribute_falls_back(monkeypatch) -> None:
    """模块存在但没有 BUILD_FLAVOR（内容损坏）也要落回 release，不能崩。"""
    _inject_flavor_module(monkeypatch, None)
    assert build_flavor.flavor() == build_flavor.FLAVOR_RELEASE


def test_internal_build_label_is_fixed_wording() -> None:
    assert build_flavor.INTERNAL_BUILD_LABEL == "内部评估版本"


# ==============================================================================
# 4. i18n：帮助菜单入口必须在三语字典里齐备
# ==============================================================================
@pytest.mark.parametrize("lang_module", ["zh_CN", "en_US", "ja_JP"])
def test_enter_code_translation_present(lang_module: str) -> None:
    module = importlib.import_module(f"polyxrd.i18n.translations.{lang_module}")
    text = module.translations["registration"]["enter_code"]
    assert text and isinstance(text, str)
    assert "&" in text  # 带助记键，与其他菜单项风格一致


def test_chinese_menu_wording() -> None:
    module = importlib.import_module("polyxrd.i18n.translations.zh_CN")
    assert module.translations["registration"]["enter_code"] == "输入注册码(&R)…"
