"""
实验元数据与多谱管理 (M02, Sprint 3)
====================================
ExperimentalPattern (单谱+元数据) / PatternTable (多谱) / SessionDocument
(会话持久化: 谱表+峰表+识别结果等, json 文件)。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from polyxrd.models.xrd_data import XRDData


@dataclass
class ExperimentalPattern:
    """一条实验衍射谱 + 元数据。

    Attributes:
        name: 显示名
        xrd: XRDData (2θ/intensity/wavelength)
        radiation: 辐射类型 (Cu Kα / Fe Kα / ...), 默认 "Cu Kα"
        source: 来源 (仪器/文件路径)
        imported_at: ISO 时间戳 (str)
        note: 备注
    """
    name: str = ""
    xrd: Optional[XRDData] = None
    radiation: str = "Cu Kα"
    source: str = ""
    imported_at: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.imported_at:
            self.imported_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "xrd": self.xrd.to_dict() if self.xrd else None,
            "radiation": self.radiation,
            "source": self.source,
            "imported_at": self.imported_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentalPattern":
        xrd = data.get("xrd")
        return cls(
            name=data.get("name", ""),
            xrd=XRDData.from_dict(xrd) if xrd else None,
            radiation=data.get("radiation", "Cu Kα"),
            source=data.get("source", ""),
            imported_at=data.get("imported_at", ""),
            note=data.get("note", ""),
        )


@dataclass
class PatternTable:
    """多谱管理表: 每条谱独立, 切换 active 不影响彼此峰表。"""
    patterns: list = field(default_factory=list)      # list[ExperimentalPattern]
    active_index: int = 0

    def __len__(self) -> int:
        return len(self.patterns)

    def add(self, pattern: ExperimentalPattern) -> None:
        self.patterns.append(pattern)
        self.active_index = len(self.patterns) - 1

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.patterns):
            self.patterns.pop(index)
            self.active_index = min(max(0, index - 1), len(self.patterns) - 1)

    @property
    def active(self) -> Optional[ExperimentalPattern]:
        if 0 <= self.active_index < len(self.patterns):
            return self.patterns[self.active_index]
        return None

    def set_active(self, index: int) -> None:
        if 0 <= index < len(self.patterns):
            self.active_index = index

    def to_dict(self) -> dict:
        return {
            "patterns": [p.to_dict() for p in self.patterns],
            "active_index": self.active_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PatternTable":
        return cls(
            patterns=[ExperimentalPattern.from_dict(d) for d in data.get("patterns", [])],
            active_index=data.get("active_index", 0),
        )


@dataclass
class SessionDocument:
    """会话文档: 谱表 + 峰表 + 识别/精修结果 + 附加字段, json 持久化。"""
    version: str = "1.0"
    patterns: PatternTable = field(default_factory=PatternTable)
    payload: dict = field(default_factory=dict)   # 附加 (峰表/结果等序列化)

    def save(self, path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "app": "polyxrd",
            "version": self.version,
            "patterns": self.patterns.to_dict(),
            "payload": self.payload,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path) -> "SessionDocument":
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return cls(
            version=doc.get("version", "1.0"),
            patterns=PatternTable.from_dict(doc.get("patterns", {})),
            payload=doc.get("payload", {}),
        )
