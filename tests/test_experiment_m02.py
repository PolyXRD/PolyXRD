"""
M02 元数据与多谱/会话测试 (Sprint 3)
====================================
"""
import numpy as np

from polyxrd.models.experiment import (ExperimentalPattern, PatternTable,
                                       SessionDocument)
from polyxrd.models.xrd_data import XRDData


def _xrd(name):
    tt = np.linspace(10, 60, 101)
    return XRDData(two_theta=tt, intensity=np.sin(tt) * 100 + 50,
                   metadata={"name": name})


def _pat(name):
    return ExperimentalPattern(name=name, xrd=_xrd(name), radiation="Cu Kα",
                               source=f"file://{name}.txt")


class TestExperimentalPattern:
    def test_roundtrip(self):
        p = _pat("s1")
        d = ExperimentalPattern.from_dict(p.to_dict())
        assert d.name == "s1"
        assert np.allclose(d.xrd.intensity, p.xrd.intensity)
        assert d.imported_at == p.imported_at

    def test_auto_timestamp(self):
        assert _pat("x").imported_at  # 自动填充


class TestPatternTable:
    def test_add_active_and_remove(self):
        t = PatternTable()
        t.add(_pat("a"))
        t.add(_pat("b"))
        assert len(t) == 2 and t.active.name == "b"
        t.set_active(0)
        assert t.active.name == "a"
        t.remove(0)
        assert len(t) == 1 and t.active.name == "b"

    def test_roundtrip_isolated_xrd(self):
        t = PatternTable()
        a = _pat("a")
        b = _pat("b")
        t.add(a)
        t.add(b)
        # 修改 a 的强度不应影响 b (独立性)
        a.xrd.intensity[:] = 0.0
        assert np.any(b.xrd.intensity != 0.0)
        t2 = PatternTable.from_dict(t.to_dict())
        assert len(t2) == 2 and t2.active.name == "b"
        assert np.allclose(t2.patterns[0].xrd.intensity, 0.0)


class TestSessionDocument:
    def test_save_load(self, tmp_path):
        sess = SessionDocument(patterns=PatternTable())
        sess.patterns.add(_pat("a"))
        sess.patterns.add(_pat("b"))
        sess.payload = {"peaks": [{"two_theta": 28.4, "intensity": 100}]}
        path = tmp_path / "session.json"
        sess.save(path)
        loaded = SessionDocument.load(path)
        assert len(loaded.patterns) == 2
        assert loaded.patterns.patterns[0].xrd is not None
        assert loaded.payload["peaks"][0]["two_theta"] == 28.4

    def test_load_missing_raises(self, tmp_path):
        try:
            SessionDocument.load(tmp_path / "nope.json")
            assert False
        except FileNotFoundError:
            pass
