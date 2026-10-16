# -*- coding: utf-8 -*-
"""PolyXRD 家族统一注册机制（单文件模块 · 零三方依赖 · PySide6 延迟导入）。

================================================================================
机制说明
================================================================================
* 注册码由**开发方**根据用户提供的「单位部门名称」生成（见同目录
  ``make_reg_code.py``）；用户在软件内「帮助 → 输入注册码」粘贴后即完成注册。
* 注册码格式::

      PXRD1-XXXX-XXXX-XXXX-XXXX-...

  ``PXRD1`` 为格式版本号；其后是 Base32 编码的
  ``UTF8(单位名) + 0x00 + HMAC-SHA256(密钥, 单位名)[:8]``。
  软件端重新计算 HMAC 即可校验真伪并**还原出单位部门名称**（用于状态栏展示），
  无需联网、无需机器码，同一注册码可在同一单位的多台电脑使用。
* 注册状态保存在 ``registration.json``（默认 ``%APPDATA%/PolyXRD/Registration/
  <app_id>.json``，各项目也可显式传入自己的配置目录）；每次启动时重新校验
  注册码，手改 JSON 伪造「已注册」无效。
* 安全级别：离线混淆级（密钥随软件分发，可被逆向提取）。适用于"告知版权 +
  自助注册"场景；如需更强绑定（按机器码 / 按 app 绑定），见 README.md。

================================================================================
接入步骤（每个项目约 4 处，详见 README.md）
================================================================================
1. 复制本文件到项目源码树（如 ``src/<pkg>/utils/registration.py``）；
2. 主窗口 ``__init__`` 创建::

       from <pkg>.utils.registration import RegistrationManager
       self._reg = RegistrationManager(__app_name__,
                                       config.app_config_dir() / "registration.json")

3. 帮助菜单::

       self._reg.add_help_action(help_menu, self)      # 「输入注册码 (&R)…」

4. 状态栏最左一排::

       status_bar.addWidget(self._reg.label(self))     # 显示 已注册：XXX / 未注册

5. 启动提示（窗口 show 之后，用 QTimer 保证不阻塞冒烟测试）::

       QTimer.singleShot(0, lambda: self._reg.startup_check(self))
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 常量
# ------------------------------------------------------------------------------
#: 注册码格式版本前缀（改格式时递增，如 PXRD2）
CODE_PREFIX = "PXRD1"

#: Base32 分组长度（每 N 字符一个连字符，便于阅读 / 口述 / 手抄）
_GROUP = 4

#: HMAC 截断长度（字节）
_MAC_LEN = 8

#: 密钥 —— **混淆级**：随软件分发，可被逆向提取。
#: 修改密钥会使此前生成的所有注册码失效，请谨慎并同步 make_reg_code.py 的说明。
_SECRET_KEY = b"PolyXRD::Family::Registration::sshztx@outlook.com"

#: 版权提示中的联系邮箱
CONTACT_EMAIL = "sshztx@outlook.com"

#: 未注册启动提示文案（按需求固定）
UNREGISTERED_NOTICE = (
    "本软件未注册，版权所有，禁止用于商业用途。\n"
    f"如需注册请联系 {CONTACT_EMAIL}"
)

#: 状态文件默认根目录（%APPDATA%/PolyXRD/Registration，非 Windows 回退 ~/.polyxrd）
_STATE_VENDOR = "PolyXRD"
_STATE_DIR_NAME = "Registration"

_UNIT_MAX_LEN = 100


# ------------------------------------------------------------------------------
# 内置三语文案（模块自包含，不依赖各项目 i18n；可用 set_language() 同步）
# ------------------------------------------------------------------------------
_LANGUAGES = ("zh", "en", "ja")
_current_language = "zh"

_TRANSLATIONS: dict[str, dict[str, str]] = {
    # 菜单 / 对话框
    "输入注册码 (&R)…": {"en": "Enter Registration &Code…", "ja": "登録コード入力 (&R)…"},
    "输入注册码": {"en": "Enter Registration Code", "ja": "登録コードの入力"},
    "请粘贴注册码（由开发方根据「单位部门名称」生成）：": {
        "en": "Paste the registration code (issued by the developer for your organization):",
        "ja": "登録コードを貼り付けてください（開発元が組織名に基じて発行）:",
    },
    "确定": {"en": "OK", "ja": "OK"},
    "取消": {"en": "Cancel", "ja": "キャンセル"},
    # 提示 / 状态
    "未注册": {"en": "Unregistered", "ja": "未登録"},
    "已注册：{}": {"en": "Registered: {}", "ja": "登録済み: {}"},
    "注册成功：{}": {"en": "Registration successful: {}", "ja": "登録成功: {}"},
    "注册码无效，请检查后重试。": {
        "en": "Invalid registration code. Please check and retry.",
        "ja": "登録コードが無効です。確認して再試行してください。",
    },
    "注册状态保存失败：{}": {
        "en": "Failed to save registration state: {}",
        "ja": "登録状態の保存に失敗しました: {}",
    },
    "注册信息": {"en": "Registration", "ja": "登録情報"},
}


def set_language(lang: str) -> None:
    """同步界面语言（zh / en / ja），供各项目语言切换时调用。"""
    global _current_language
    _current_language = lang if lang in _LANGUAGES else "zh"


def current_language() -> str:
    return _current_language


def tr(text: str) -> str:
    """翻译一条模块内置文案（未收录原样透传）。"""
    entry = _TRANSLATIONS.get(text)
    if entry is None:
        return text
    return entry.get(_current_language) or text


# ------------------------------------------------------------------------------
# 注册码：生成 / 校验（纯 stdlib，可在无 Qt 环境运行）
# ------------------------------------------------------------------------------
def _mac(unit: str) -> bytes:
    return hmac.new(_SECRET_KEY, unit.encode("utf-8"), hashlib.sha256).digest()[:_MAC_LEN]


def _valid_unit(name: str) -> bool:
    """单位名合法性：非空、≤100 字符、不含控制字符（注册码内不允许 0x00）。"""
    if not name or len(name) > _UNIT_MAX_LEN:
        return False
    return all(ord(ch) >= 32 for ch in name)


def _normalize_unit(unit: str) -> str:
    """归一化单位名（压缩连续空白）；非法时抛 ValueError。"""
    name = " ".join(str(unit).split())
    if not _valid_unit(name):
        raise ValueError(f"单位部门名称不合法（1–{_UNIT_MAX_LEN} 字符，不含控制字符）")
    return name


def _group(code: str) -> str:
    return "-".join(code[i:i + _GROUP] for i in range(0, len(code), _GROUP))


def generate_code(unit: str) -> str:
    """开发方使用：根据「单位部门名称」生成注册码。"""
    name = _normalize_unit(unit)
    payload = name.encode("utf-8") + b"\x00" + _mac(name)
    body = base64.b32encode(payload).decode("ascii").rstrip("=")
    return f"{CODE_PREFIX}-{_group(body)}"


def _normalize_code(raw: str) -> str:
    """归一化用户输入：去空白 / 连字符（含全角）、大写、去版本前缀。"""
    text = "".join(str(raw).split())
    for dash in ("-", "－", "—", "–"):
        text = text.replace(dash, "")
    text = text.upper()
    if text.startswith(CODE_PREFIX):
        text = text[len(CODE_PREFIX):]
    return text


def _verify_body(body: str) -> Optional[str]:
    if not body:
        return None
    padded = body + "=" * (-len(body) % 8)
    try:
        payload = base64.b32decode(padded)
    except Exception:  # noqa: BLE001 —— 任意非法输入都只返回 None
        return None
    name_bytes, sep, mac = payload.rpartition(b"\x00")
    if not sep or not name_bytes or len(mac) != _MAC_LEN:
        return None
    try:
        name = name_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not _valid_unit(name):
        return None
    if not hmac.compare_digest(_mac(name), mac):
        return None
    return name


def verify_code(raw: str) -> Optional[str]:
    """软件端使用：校验注册码，成功返回「单位部门名称」，失败返回 None。

    容错：允许带/不带 ``PXRD1-`` 前缀、任意空白与连字符、大小写混输。
    （Base32 字符集为 A-Z2-7，不含数字 1，故 body 不可能以 "PXRD1" 开头，
    前缀最多剥一次即可，无需重试。）
    """
    return _verify_body(_normalize_code(raw))


# ------------------------------------------------------------------------------
# 注册状态：存取（JSON，启动时重新校验，防手改伪造）
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class RegistrationState:
    """注册状态（不可变快照）。"""

    registered: bool
    unit: str = ""
    code: str = ""

    @property
    def status_text(self) -> str:
        return tr("已注册：{}").format(self.unit) if self.registered else tr("未注册")


def default_state_path(app_id: str = "PolyXRD") -> Path:
    """注册状态文件默认路径（各项目通常显式传入自己的配置目录）。"""
    base = os.environ.get("APPDATA")
    if base:
        root = Path(base) / _STATE_VENDOR / _STATE_DIR_NAME
    else:
        root = Path.home() / ".polyxrd" / _STATE_DIR_NAME.lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in app_id) or "app"
    return root / f"{safe}.json"


def load_state(state_path: Path | str) -> RegistrationState:
    """读取注册状态；文件缺失 / 损坏 / 校验失败一律按未注册处理。"""
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
        code = str(data.get("code", "")).strip()
        unit = str(data.get("unit", "")).strip()
    except (OSError, ValueError) as exc:
        logger.debug("注册状态读取失败（按未注册处理）：%s | %s", state_path, exc)
        return RegistrationState(False)
    if code and unit and verify_code(code) == unit:
        return RegistrationState(True, unit, code)
    return RegistrationState(False)


def save_state(state_path: Path | str, code: str) -> RegistrationState:
    """校验并持久化注册码；无效时抛 ValueError。"""
    unit = verify_code(code)
    if unit is None:
        raise ValueError("注册码无效")
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"code": str(code).strip(), "unit": unit}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("注册成功：%s -> %s", unit, path)
    return RegistrationState(True, unit, str(code).strip())


# ------------------------------------------------------------------------------
# Qt UI（PySide6 延迟导入：核心逻辑不依赖 Qt，可在无 Qt 环境测试/生成注册码）
# ------------------------------------------------------------------------------
def _prompt_skipped() -> bool:
    """离屏 / 冒烟 / 显式禁用时不弹启动提示（自动化测试友好）。"""
    if os.environ.get("POLYXRD_REG_NO_PROMPT") == "1":
        return True
    return os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"


def make_status_label(parent, state: RegistrationState):
    """状态栏注册标签（右对齐；已注册：XXX / 未注册）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    label = QLabel(parent)
    label.setObjectName("regStatusLabel")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    refresh_status_label(label, state)
    return label


def add_status_label(status_bar, parent, state: RegistrationState):
    """把注册标签加到状态栏**最右侧并右对齐**，返回 QLabel。

    ``stretch=1`` 让标签吃掉中间空白，单位部门名称始终贴着状态栏右端，
    不会因为窗口变宽而漂到中间。各项目接入只需这一行::

        status_bar = self.statusBar()
        registration.add_status_label(status_bar, self, state)
    """
    label = make_status_label(parent, state)
    status_bar.addPermanentWidget(label, 1)
    return label


def refresh_status_label(label, state: RegistrationState) -> None:
    """刷新状态栏注册标签（注册成功后调用）。"""
    label.setText(state.status_text)
    if state.registered:
        label.setToolTip(f"{tr('注册信息')}: {state.unit}")
    else:
        label.setToolTip(f"{tr('未注册')} · {CONTACT_EMAIL}")


def prompt_for_code(parent, state_path: Path | str, app_name: str = "") -> Optional[RegistrationState]:
    """弹出「输入注册码」对话框；注册成功返回新状态，取消/失败返回 None。"""
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QVBoxLayout,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("输入注册码"))
    dialog.setMinimumWidth(520)
    layout = QVBoxLayout(dialog)
    layout.setSpacing(8)

    hint = QLabel(tr("请粘贴注册码（由开发方根据「单位部门名称」生成）："))
    hint.setWordWrap(True)
    layout.addWidget(hint)

    edit = QLineEdit()
    edit.setPlaceholderText(tr("PXRD1-XXXX-XXXX-XXXX-XXXX"))
    layout.addWidget(edit)

    error = QLabel("")
    error.setWordWrap(True)
    error.setStyleSheet("color: #c0392b;")
    layout.addWidget(error)

    row = QHBoxLayout()
    ok_button = QPushButton(tr("确定"))
    cancel_button = QPushButton(tr("取消"))
    row.addStretch(1)
    row.addWidget(ok_button)
    row.addWidget(cancel_button)
    layout.addLayout(row)

    outcome: dict[str, RegistrationState] = {}

    def _on_ok() -> None:
        state = None
        try:
            state = save_state(state_path, edit.text())
        except ValueError:
            error.setText(tr("注册码无效，请检查后重试。"))
            return
        except OSError as exc:
            error.setText(tr("注册状态保存失败：{}").format(exc))
            return
        outcome["state"] = state
        dialog.accept()

    ok_button.clicked.connect(_on_ok)
    cancel_button.clicked.connect(dialog.reject)
    edit.returnPressed.connect(_on_ok)
    edit.setFocus()

    if not dialog.exec() or "state" not in outcome:
        return None
    state = outcome["state"]
    # 显式 addButton 而非静态 QMessageBox.information：
    # 静态方法的标准按钮文案依赖 Qt 内置翻译（离屏/精简打包环境下可能是 "OK"），
    # 显式构造可保证文案确定、行为一致。
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(app_name or tr("注册信息"))
    box.setText(tr("注册成功：{}").format(state.unit))
    box.addButton(tr("确定"), QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    return state


def startup_prompt(parent, state_path: Path | str, app_name: str = "") -> RegistrationState:
    """未注册时的启动提示：[确定] 关闭继续使用 / [输入注册码] 直接注册。"""
    from PySide6.QtWidgets import QMessageBox

    state = load_state(state_path)
    if state.registered or _prompt_skipped():
        return state

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(app_name or tr("注册信息"))
    box.setText(UNREGISTERED_NOTICE)
    ok_button = box.addButton(tr("确定"), QMessageBox.ButtonRole.AcceptRole)
    reg_button = box.addButton(tr("输入注册码"), QMessageBox.ButtonRole.ActionRole)
    ok_button.setDefault(True)
    ok_button.setAutoDefault(True)
    box.exec()

    if box.clickedButton() is reg_button:
        new_state = prompt_for_code(parent, state_path, app_name)
        if new_state is not None and new_state.registered:
            return new_state
    return state


class RegistrationManager:
    """一个项目一份的注册管理器（持有状态路径 + 状态栏标签缓存）。

    典型用法::

        self._reg = RegistrationManager(__app_name__, state_path)
        ...
        self._reg.add_help_action(help_menu, self)      # 帮助菜单
        # 状态栏最右侧（右对齐）显示注册的单位部门名称
        self._reg.attach_status_label(self.statusBar(), self)
        QTimer.singleShot(0, lambda: self._reg.startup_check(self))

    只想拿标签、自己决定摆放位置时用 :meth:`label`::

        status_bar.addWidget(self._reg.label(self))     # 或 addPermanentWidget
    """

    def __init__(self, app_name: str, state_path: Path | str) -> None:
        self.app_name = app_name
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self._label = None

    # ---- 状态栏 ----
    def label(self, parent):
        """惰性创建注册标签（右对齐），重复调用返回同一实例。

        注意：标签本身只是右对齐的，**摆放位置由调用方决定**；
        要「状态栏最右侧」请用 :meth:`attach_status_label`。
        """
        if self._label is None:
            self._label = make_status_label(parent, self.state)
        return self._label

    def attach_status_label(self, status_bar, parent):
        """把注册标签加到状态栏最右侧（右对齐）并返回它。

        重复调用安全：标签只创建一次，重复调用只重新摆放。
        """
        if self._label is None:
            self._label = add_status_label(status_bar, parent, self.state)
        else:
            status_bar.addPermanentWidget(self._label, 1)
        return self._label

    def refresh(self) -> None:
        """重新读取状态并刷新标签（注册成功后由内部调用）。"""
        self.state = load_state(self.state_path)
        if self._label is not None:
            refresh_status_label(self._label, self.state)

    # ---- 启动提示 ----
    def startup_check(self, parent) -> RegistrationState:
        """启动时调用：已注册静默返回；未注册弹提示（离屏/冒烟自动跳过）。"""
        before = self.state
        self.state = startup_prompt(parent, self.state_path, self.app_name)
        if self.state.registered != before.registered:
            self.refresh()
        return self.state

    # ---- 帮助菜单 ----
    def add_help_action(self, menu, parent) -> None:
        """在帮助菜单追加「输入注册码 (&R)…」。"""
        from PySide6.QtGui import QAction

        action = QAction(tr("输入注册码 (&R)…"), parent)
        action.triggered.connect(lambda: self._on_enter_code(parent))
        menu.addAction(action)

    def _on_enter_code(self, parent) -> None:
        new_state = prompt_for_code(parent, self.state_path, self.app_name)
        if new_state is not None and new_state.registered:
            self.refresh()
