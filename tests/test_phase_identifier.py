"""
物相识别测试
"""
import numpy as np
import pytest
from pathlib import Path

from polyxrd.models.xrd_data import XRDData
from polyxrd.services.phase_identifier import PhaseIdentifier
from polyxrd.services.peak_finder import PeakFinder

DATA_DIR = "D:/Project/XRD/test_xrd/txt"


class TestPhaseIdentifier:
    """物相识别测试"""

    def _create_silicon_data(self):
        """创建合成硅粉XRD数据"""
        two_theta = np.linspace(20, 100, 2000)
        intensity = np.zeros_like(two_theta)

        # Si的主要峰
        si_peaks = [
            (28.44, 1000, 0.12),   # (111)
            (47.30, 600, 0.15),    # (220)
            (56.11, 400, 0.12),    # (311)
            (69.13, 200, 0.15),    # (400)
            (76.36, 150, 0.12),    # (331)
            (88.04, 100, 0.15),    # (422)
        ]
        for center, amp, sigma in si_peaks:
            intensity += amp * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)

        intensity += np.random.normal(0, 10, len(two_theta))
        intensity = np.maximum(intensity, 0)

        return XRDData(two_theta=two_theta, intensity=intensity)

    def test_identify_silicon(self):
        """测试识别硅"""
        data = self._create_silicon_data()
        identifier = PhaseIdentifier()
        pf = PeakFinder()

        peaks = pf.find_peaks(data, height=0.05, distance=2.0)
        results = identifier.identify(data, peaks=peaks, top_n=5)

        assert len(results) > 0
        # 第一个结果应该是Silicon
        assert results[0].phase.name == "Silicon"
        # FOM 分值越低越好；Silicon 应匹配多个参考峰
        assert results[0].matched_peaks >= 3
        assert results[0].score < 1.0  # FOM 越低越好，良好的 Silicon 匹配应 < 1.0

    def test_identify_without_pre_peaks(self):
        """测试自动峰检测+识别"""
        data = self._create_silicon_data()
        identifier = PhaseIdentifier()

        results = identifier.identify(data, top_n=3)

        assert len(results) > 0

    def test_phase_database(self):
        """测试物相数据库"""
        identifier = PhaseIdentifier()
        assert len(identifier._phase_database) > 0

        # 检查常见物相是否存在
        phase_names = [p.name for p in identifier._phase_database]
        assert "Silicon" in phase_names
        assert "α-Quartz" in phase_names
        assert "Halite" in phase_names

    def test_add_custom_phase(self):
        """测试添加自定义物相"""
        identifier = PhaseIdentifier()

        from polyxrd.models.phase import Phase
        custom = Phase(
            name="Custom Phase",
            formula="Fe3O4",
            reference_peaks=[
                ((1, 1, 1), 18.35, 100),
                ((2, 2, 0), 30.15, 60),
            ],
        )

        initial_count = len(identifier._phase_database)
        identifier.add_phase(custom)
        assert len(identifier._phase_database) == initial_count + 1

    def test_match_result_properties(self):
        """测试匹配结果属性"""
        from polyxrd.models.phase import Phase, PhaseMatchResult

        phase = Phase(name="Test", reference_peaks=[((1, 0, 0), 20.0, 100)])
        result = PhaseMatchResult(
            phase=phase,
            score=75.0,
            matched_peaks=1,
            total_peaks=1,
            confidence="高置信度",
        )

        assert result.coverage == 100.0
        assert result.confidence == "高置信度"
        assert "phase" in result.to_dict()


class TestCodInorganicsIdentify:
    """COD 无机物库检索路径 (P3 新增, 依赖本地外挂库, 无库则跳过)"""

    @pytest.fixture()
    def cod_ready(self):
        from polyxrd.services.cif_database import CIFDatabase
        cdb = CIFDatabase(enable_cod_local=False)
        return cdb.cod_db_available()

    def test_element_filter_restricts_to_allowed(self, cod_ready):
        """元素过滤必须生效: 所有候选元素 ⊆ must∪maybe"""
        if not cod_ready:
            pytest.skip("COD 无机物库未挂载")
        if not Path(f"{DATA_DIR}/4-1.txt").exists():
            pytest.skip(f"本地试样目录不存在: {DATA_DIR}")
        from polyxrd.services.data_loader import DataLoader
        from polyxrd.services.peak_finder import PeakFinder
        from polyxrd.services.phase_identifier import PhaseIdentifier

        data = DataLoader().load(f"{DATA_DIR}/4-1.txt")
        peaks = PeakFinder().find_peaks(data)
        pi = PhaseIdentifier()
        allowed = {"Zn", "Al", "Ca", "Mg", "F", "O"}
        results = pi.identify_with_cod_inorganics(
            data, peaks=peaks, top_n=10,
            element_filter={"must": list(allowed), "maybe": [], "exclude": []},
        )
        assert len(results) > 0, "4-1 试样在 COD 无机物库应检索到候选"
        for r in results:
            assert r.phase.elements and r.phase.elements.issubset(allowed), (
                f"{r.phase.name} 含过滤范围外元素: {r.phase.elements}"
            )

    def test_fluorite_found_in_top_candidates(self, cod_ready):
        """4-1 试样含 CaF2 (Fluorite), 应出现在前列"""
        if not cod_ready:
            pytest.skip("COD 无机物库未挂载")
        if not Path(f"{DATA_DIR}/4-1.txt").exists():
            pytest.skip(f"本地试样目录不存在: {DATA_DIR}")
        from polyxrd.services.data_loader import DataLoader
        from polyxrd.services.peak_finder import PeakFinder
        from polyxrd.services.phase_identifier import PhaseIdentifier

        data = DataLoader().load(f"{DATA_DIR}/4-1.txt")
        peaks = PeakFinder().find_peaks(data)
        pi = PhaseIdentifier()
        allowed = {"Zn", "Al", "Ca", "Mg", "F", "O"}
        results = pi.identify_with_cod_inorganics(
            data, peaks=peaks, top_n=20,
            element_filter={"must": list(allowed), "maybe": [], "exclude": []},
        )
        names = [r.phase.name for r in results]
        assert any("Ca F2" in n for n in names), f"CaF2 未进入候选: {names[:5]}"
