"""
项目保存/加载服务
================
支持保存和加载PolyXRD项目文件 (.pxrd 格式)。
使用HDF5存储大数据，JSON存储元数据。
"""
from __future__ import annotations

import json
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np

from polyxrd.models.peak import Peak, PeakList
from polyxrd.models.phase import Phase, PhaseMatchResult
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData


class ProjectService:
    """项目管理服务

    项目文件格式 (.pxrd):
    - ZIP容器，包含:
      - project.json: 项目元数据和结构信息
      - data.npz: XRD数据 (numpy数组压缩存储)

    支持保存和加载:
    - XRD实验数据
    - 物相列表
    - 精修结果
    - 应用设置

    Usage:
        svc = ProjectService()
        svc.save_project("my_project.pxrd", data=data, phases=[...])
        project = svc.load_project("my_project.pxrd")
    """

    def __init__(self) -> None:
        self._version = "0.4.0"

    def save_project(
        self,
        path: str,
        data: Optional[XRDData] = None,
        phases: Optional[list[Phase]] = None,
        results: Optional[list[PhaseMatchResult]] = None,
        peaks: Optional[PeakList] = None,
        metadata: Optional[dict] = None,
        selected_phases: Optional[list[Phase]] = None,
        refinement_result: Optional[RefinementResult] = None,
    ) -> None:
        """保存项目到.pxrd文件

        Args:
            path: 保存路径 (.pxrd)
            data: XRD数据
            phases: 物相列表
            results: 匹配结果
            peaks: 峰列表
            metadata: 附加元数据
            selected_phases: 勾选确认的物相集合 (v0.15 M23, 重开项目时恢复)
            refinement_result: Rietveld 精修结果 (v2.1 P0-1, 重开项目时恢复)
        """
        project_meta = {
            "version": self._version,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "data_count": 0,
            "phase_count": len(phases) if phases else 0,
            "has_results": results is not None and len(results) > 0,
            "has_peaks": peaks is not None and len(peaks) > 0,
        }

        if metadata:
            project_meta["metadata"] = metadata

        if data:
            project_meta["data_count"] = 1
            project_meta["data_info"] = {
                "wavelength": data.wavelength,
                "points": len(data.two_theta),
                "two_theta_min": float(data.two_theta[0]),
                "two_theta_max": float(data.two_theta[-1]),
            }

        if phases:
            project_meta["phases"] = [p.to_dict() for p in phases]

        if results:
            project_meta["results"] = [r.to_dict() for r in results]

        if selected_phases:
            project_meta["selected_phases"] = [
                p.to_dict() for p in selected_phases
            ]

        if peaks:
            project_meta["peaks"] = [p.to_dict() for p in peaks]

        if refinement_result is not None:
            project_meta["refinement"] = self._refine_to_dict(refinement_result)

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(project_meta, ensure_ascii=False, indent=2))

            if data:
                buf = BytesIO()
                np.savez_compressed(
                    buf,
                    two_theta=data.two_theta,
                    intensity=data.intensity,
                    wavelength=np.array([data.wavelength]),
                )
                zf.writestr("data.npz", buf.getvalue())

    def load_project(self, path: str) -> dict:
        """从.pxrd文件加载项目

        Args:
            path: 项目文件路径

        Returns:
            项目数据字典，包含:
            - data: XRDData (如果存在)
            - phases: Phase列表
            - results: PhaseMatchResult列表
            - peaks: PeakList (如果存在)
            - metadata: 项目元数据
            - info: 项目信息
        """
        if not Path(path).exists():
            raise FileNotFoundError(f"项目文件不存在: {path}")

        result: dict = {
            "data": None,
            "phases": [],
            "results": [],
            "peaks": None,
            "metadata": {},
            "info": {},
            "selected_phases": [],
            "refinement_result": None,
        }

        with zipfile.ZipFile(path, "r") as zf:
            if "project.json" not in zf.namelist():
                raise ValueError("无效的项目文件: 缺少project.json")

            with zf.open("project.json") as f:
                project_meta = json.loads(f.read())

            result["info"] = {
                "version": project_meta.get("version", ""),
                "created_at": project_meta.get("created_at", ""),
            }

            if "metadata" in project_meta:
                result["metadata"] = project_meta["metadata"]

            if project_meta.get("data_count", 0) > 0 and "data.npz" in zf.namelist():
                with zf.open("data.npz") as f:
                    buf = BytesIO(f.read())
                    loaded = np.load(buf)
                    wavelength = float(loaded["wavelength"][0])
                    result["data"] = XRDData(
                        two_theta=loaded["two_theta"],
                        intensity=loaded["intensity"],
                        wavelength=wavelength,
                    )

            if "phases" in project_meta:
                result["phases"] = [Phase.from_dict(p) for p in project_meta["phases"]]

            if "selected_phases" in project_meta:
                result["selected_phases"] = [
                    Phase.from_dict(p) for p in project_meta["selected_phases"]
                ]

            if "results" in project_meta:
                result["results"] = []
                for r_data in project_meta["results"]:
                    phase = Phase.from_dict(r_data["phase"])
                    result["results"].append(PhaseMatchResult(
                        phase=phase,
                        score=r_data["score"],
                        matched_peaks=r_data["matched_peaks"],
                        total_peaks=r_data["total_peaks"],
                        confidence=r_data.get("confidence", ""),
                    ))

            if "peaks" in project_meta:
                peaks_list = []
                for p_data in project_meta["peaks"]:
                    peaks_list.append(Peak.from_dict(p_data))
                result["peaks"] = PeakList(peaks_list)

            if "refinement" in project_meta:
                result["refinement_result"] = self._refine_from_dict(
                    project_meta["refinement"]
                )

        return result

    # ------------------------------------------------------------------
    # RefinementResult 序列化 (v2.1 P0-1: 项目文件携带精修结果)
    # ------------------------------------------------------------------

    @staticmethod
    def _refine_to_dict(rr: RefinementResult) -> dict:
        """RefinementResult -> JSON 可序列化 dict (谱数组转 list)。"""

        def _xy(t) -> Optional[dict]:
            if t is None:
                return None
            x, y = t
            return {"x": np.asarray(x).tolist(), "y": np.asarray(y).tolist()}

        fit_params = {}
        for k, v in (rr.fit_params or {}).items():
            # numpy 标量 (.item()) -> python 原生类型, 避免 JSON 序列化漂移
            fit_params[k] = v.item() if hasattr(v, "item") else v

        return {
            "phases": [p.to_dict() for p in rr.phases],
            "observed": _xy(rr.observed_data),
            "simulated": _xy(rr.simulated_data),
            "residual": _xy(rr.residual_data),
            "wR": rr.wR, "Rexp": rr.Rexp, "Rb": rr.Rb, "Rp": rr.Rp,
            "chi2": rr.chi2, "chi2_red": rr.chi2_red,
            "metrics_valid": rr.metrics_valid,
            "metric_note": rr.metric_note,
            "GOF": rr.GOF, "quality": rr.quality,
            "num_cycles": rr.num_cycles, "converged": rr.converged,
            "time_seconds": rr.time_seconds,
            "fit_params": fit_params,
            "warnings": list(rr.warnings),
            # v2.1-B: 结构化诊断 ({code, params}) 随项目文件持久化
            "diagnostics": [
                dict(x) for x in (getattr(rr, "diagnostics", []) or [])
                if isinstance(x, dict)
            ],
        }

    @staticmethod
    def _refine_from_dict(d: dict) -> RefinementResult:
        """_refine_to_dict 的逆变换。"""

        def _xy(t):
            if not t:
                return None
            return (np.asarray(t["x"], dtype=float), np.asarray(t["y"], dtype=float))

        return RefinementResult(
            phases=[Phase.from_dict(p) for p in d.get("phases", [])],
            observed_data=_xy(d.get("observed")),
            simulated_data=_xy(d.get("simulated")),
            residual_data=_xy(d.get("residual")),
            wR=d.get("wR", 0.0),
            Rexp=d.get("Rexp", 0.0),
            Rb=d.get("Rb", 0.0),
            Rp=d.get("Rp", 0.0),
            chi2=d.get("chi2", 0.0),
            chi2_red=d.get("chi2_red", 0.0),
            metrics_valid=d.get("metrics_valid", True),
            metric_note=d.get("metric_note", ""),
            GOF=d.get("GOF", 0.0),
            quality=d.get("quality", ""),
            num_cycles=d.get("num_cycles", 0),
            converged=d.get("converged", False),
            time_seconds=d.get("time_seconds", 0.0),
            fit_params=dict(d.get("fit_params", {})),
            warnings=list(d.get("warnings", [])),
            diagnostics=[
                dict(x) for x in (d.get("diagnostics", []) or [])
                if isinstance(x, dict) and x.get("code")
            ],
        )

    def export_data_csv(self, data: XRDData, path: str) -> None:
        """导出XRD数据为CSV格式"""
        header = f"# PolyXRD Data Export\n# Wavelength: {data.wavelength} Å\n# Source: {data.xray_source}\n# Points: {len(data.two_theta)}\n2θ,Intensity\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            for two_theta, intensity in zip(data.two_theta, data.intensity):
                f.write(f"{two_theta:.4f},{intensity:.2f}\n")

    def export_results_txt(self, results: list[PhaseMatchResult], path: str) -> None:
        """导出匹配结果为文本"""
        with open(path, "w", encoding="utf-8") as f:
            f.write("PolyXRD Phase Identification Results\n")
            f.write("=" * 60 + "\n\n")
            for i, r in enumerate(results, 1):
                f.write(f"#{i} {r.phase.name} ({r.phase.formula})\n")
                f.write(f"   得分: {r.score:.4f}  置信度: {r.confidence}\n")
                f.write(f"   匹配峰数: {r.matched_peaks}/{r.total_peaks}  ({r.coverage:.1f}%)\n")
                if r.phase.space_group:
                    f.write(f"   空间群: {r.phase.space_group}\n")
                if r.phase.lattice:
                    lat = r.phase.lattice
                    f.write(f"   晶胞: a={lat.a:.3f} b={lat.b:.3f} c={lat.c:.3f} Å\n")
                    f.write(f"         α={lat.alpha:.2f} β={lat.beta:.2f} γ={lat.gamma:.2f}°\n")
                f.write("\n")

    @staticmethod
    def _guess_source(wavelength: float) -> str:
        sources = {
            1.5406: "Cu Kα", 0.7107: "Mo Kα",
            1.7889: "Co Kα", 2.2897: "Cr Kα",
        }
        best = min(sources.keys(), key=lambda k: abs(k - wavelength))
        return sources[best] if abs(best - wavelength) < 0.01 else f"Custom ({wavelength:.4f} Å)"