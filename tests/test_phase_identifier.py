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

    def test_organic_db_lattice_none(self):
        """有机/药物相库 (exp 来源, 无晶胞) 必须能加载且 lattice=None。

        #57: 实验谱提取的相 (Mannitol/Valine) 写入 organic_reference_database.json
        时 lattice=null, _build_phases_from_db 必须容忍 None 而不抛 AttributeError。
        """
        identifier = PhaseIdentifier()
        by_key = {p.name.lower(): p for p in identifier._phase_database}
        # builtin + organic 合并后, 实验谱相应存在且 lattice 为 None
        for name in ("mannitol", "valine", "nizatidine"):
            assert name in by_key, f"organic 库的 {name} 未进入可检索列表"
            assert by_key[name].lattice is None, f"{name} 是 exp 来源, lattice 必须为 None"
        # 带晶胞的 (Sucrose, COD 来源) 不应被误置为 None
        assert "sucrose" in by_key
        assert by_key["sucrose"].lattice is not None

    def test_organic_exp_peak_count_cap(self):
        """exp 来源参考卡必须取"最强少数峰"而非全部峰。

        P0 迭代结论: 参考峰 >8 条时, Nizatidine 会与密集谱偶然匹配挤进 BAUXITE 的
        top-10 (误报); 取最强 6 条时零污染且命中不变。此处锁定该上限, 防回归。
        """
        identifier = PhaseIdentifier()
        by_key = {p.name.lower(): p for p in identifier._phase_database}
        for name in ("mannitol", "valine", "nizatidine"):
            n = len(by_key[name].reference_peaks)
            assert 3 <= n <= 8, f"{name} 参考峰 {n} 条超出 [3,8] 区间 (强峰上限被破坏?)"

    def test_organic_no_starch_entry(self):
        """淀粉刻意不入有机库 (P0-2 回退)。

        近非晶宽包络与检出锐峰不对齐: 即便参考峰取自 STARCH.RAW 自身, 单相仍排 #85
        (cov 1/6), 混合物 cov 0/6, 只会引入误报。该缺口留给非晶相识别方案处理。
        """
        identifier = PhaseIdentifier()
        names = {p.name.lower() for p in identifier._phase_database}
        assert "starch" not in names, "淀粉条目被误加回; 见 P0-2 回退结论"

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


class TestPolydbIdentify:
    """polyDB 检索路径 —— v4.1.0 起这是**默认参考库**, 依赖本地外挂库, 无库则跳过。

    基线意义: 这条链路是 GUI 默认走的那条 (COD 无机物库 77,500 相)。旧版这里
    断言的是已删除的 COD sqlite 槽位, 现在换成等价的 polyDB 目录容器。
    """

    @pytest.fixture()
    def poly_db(self) -> Path:
        for cand in (
            Path("D:/Project/XRD/PolyXRD-DataBase/polydb/COD-Inorg-20261021.polyDB"),
            Path("D:/Project/XRD/PolyXRD-DataBase/polydb/COD-Inorg.polyDB"),
        ):
            if cand.is_dir():
                return cand
        pytest.skip("本地没有 COD-Inorg polyDB")

    @pytest.fixture()
    def sample(self):
        txt = Path(f"{DATA_DIR}/4-1.txt")
        if not txt.exists():
            pytest.skip(f"本地试样目录不存在: {DATA_DIR}")
        from polyxrd.services.data_loader import DataLoader
        from polyxrd.services.peak_finder import PeakFinder

        data = DataLoader().load(str(txt))
        return data, PeakFinder().find_peaks(data)

    def test_returns_candidates(self, poly_db, sample):
        data, peaks = sample
        results = PhaseIdentifier().identify_with_polydb(
            data, peaks=peaks, top_n=10, db_path=str(poly_db))
        assert results, "默认 polyDB 上 4-1 试样检索不到任何候选"
        assert len(results) <= 10

    def test_must_have_filter_is_enforced(self, poly_db, sample):
        """``must_have`` 是 AND 语义: 每个候选都必须含全部必有元素。"""
        data, peaks = sample
        results = PhaseIdentifier().identify_with_polydb(
            data, peaks=peaks, top_n=10, db_path=str(poly_db),
            element_filter={"must_have": ["Ca", "F"]})
        assert results, "Ca+F 必有过滤下不该一个候选都没有"
        for r in results:
            els = set(r.phase.elements or ())
            assert {"Ca", "F"} <= els, f"{r.phase.name} 缺必含元素: {sorted(els)}"

    def test_exclude_filter_is_enforced(self, poly_db, sample):
        data, peaks = sample
        results = PhaseIdentifier().identify_with_polydb(
            data, peaks=peaks, top_n=10, db_path=str(poly_db),
            element_filter={"exclude": ["Zn", "S"]})
        for r in results:
            els = set(r.phase.elements or ())
            assert not (els & {"Zn", "S"}), f"{r.phase.name} 含被排除元素: {sorted(els)}"

    def test_fluorite_found_in_top_candidates(self, poly_db, sample):
        """4-1 试样含 CaF2 (Fluorite), 在默认库上应进前列。"""
        data, peaks = sample
        results = PhaseIdentifier().identify_with_polydb(
            data, peaks=peaks, top_n=20, db_path=str(poly_db),
            element_filter={"must_have": ["Ca", "F"]})
        names = [r.phase.name for r in results]
        assert any("Ca F2" in n or "CaF2" in n for n in names),             f"CaF2 未进入候选: {names[:5]}"

    def test_missing_db_returns_empty(self, tmp_path):
        """库不存在时返回空, 不抛异常 (GUI 才不会崩)。"""
        data = XRDData(two_theta=np.linspace(20, 80, 500),
                       intensity=np.zeros(500) + 0.01, wavelength=1.5406)
        res = PhaseIdentifier().identify_with_polydb(
            data, top_n=5, db_path=str(tmp_path / "gone.polyDB"))
        assert res == []
