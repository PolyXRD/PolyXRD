"""
导出服务
========
导出分析结果为各种格式。
"""
from __future__ import annotations

import json
from pathlib import Path


from polyxrd.models.phase import Phase
from polyxrd.models.refinement import RefinementResult
from polyxrd.models.xrd_data import XRDData


class ExportService:
    """导出服务

    支持导出：
    - Rietveld结果 (.gpx, .cif, .txt, .csv)
    - 物相分析报告 (.json, .txt)
    - 图谱图片 (.png, .pdf, .svg)
    - CIF文件

    Usage:
        exporter = ExportService()
        exporter.export_rietveld_result(result, "output", "json")
    """

    def export_rietveld_result(
        self,
        result: RefinementResult,
        output_dir: str | Path,
        format: str = "json",
    ) -> list[str]:
        """导出Rietveld精修结果

        Args:
            result: 精修结果
            output_dir: 输出目录
            format: 输出格式

        Returns:
            生成的文件路径列表
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_files = []

        if format == "json":
            path = output_dir / "rietveld_result.json"
            data = result.to_dict()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            generated_files.append(str(path))

        elif format == "txt":
            path = output_dir / "rietveld_result.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(result.summary())
            generated_files.append(str(path))

        elif format == "csv":
            path = output_dir / "phases.csv"
            self._export_phases_csv(result.phases, path)
            generated_files.append(str(path))

            params_path = output_dir / "parameters.csv"
            self._export_params_csv(result.fit_params, params_path)
            generated_files.append(str(params_path))

        elif format == "all":
            generated_files.extend(
                self.export_rietveld_result(result, output_dir, "json")
            )
            generated_files.extend(
                self.export_rietveld_result(result, output_dir, "txt")
            )
            generated_files.extend(
                self.export_rietveld_result(result, output_dir, "csv")
            )

        return generated_files

    def export_phase_report(
        self,
        phases: list[Phase],
        output_path: str | Path,
        format: str = "json",
    ) -> str:
        """导出物相分析报告

        Args:
            phases: 物相列表
            output_path: 输出路径
            format: 输出格式

        Returns:
            生成的文件路径
        """
        output_path = Path(output_path)

        if format == "json":
            data = [p.to_dict() for p in phases]
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        elif format == "txt":
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write("  XRD物相分析报告\n")
                f.write("=" * 60 + "\n\n")
                for i, phase in enumerate(phases, 1):
                    f.write(f"物相 {i}: {phase.name}\n")
                    f.write(f"  化学式: {phase.formula}\n")
                    f.write(f"  匹配度: {phase.match_score:.1f}%\n")
                    if phase.lattice is not None:
                        lat = phase.lattice
                        f.write(f"  晶格参数: a={lat.a:.4f}, "
                                f"b={lat.b:.4f}, c={lat.c:.4f} Å\n")
                        f.write(f"            α={lat.alpha:.2f}, "
                                f"β={lat.beta:.2f}, γ={lat.gamma:.2f}°\n")
                    else:
                        f.write("  晶格参数: -\n")
                    f.write(f"  空间群: {phase.space_group}\n")
                    f.write(f"  质量分数: {phase.weight_fraction:.2f} wt%\n")
                    if phase.reference_peaks:
                        f.write(f"  参考峰数: {len(phase.reference_peaks)}\n")
                        for hkl, two_theta, intensity in phase.reference_peaks[:5]:
                            hkl_str = f"({hkl[0]}{hkl[1]}{hkl[2]})"
                            f.write(f"    2θ={two_theta:.3f}, "
                                    f"hkl={hkl_str}, "
                                    f"I={intensity:.1f}\n")
                    f.write("\n")

        elif format == "csv":
            self._export_phases_csv(phases, output_path)

        return str(output_path)

    def export_plot(
        self,
        figure,
        output_path: str | Path,
        dpi: int = 300,
        format: str = "png",
    ) -> str:
        """导出图谱

        Args:
            figure: matplotlib Figure 对象
            output_path: 输出路径
            dpi: 分辨率
            format: 图片格式

        Returns:
            生成的文件路径
        """
        output_path = Path(output_path)

        if not output_path.suffix:
            output_path = output_path.with_suffix(f".{format}")

        figure.savefig(str(output_path), dpi=dpi, bbox_inches="tight")
        return str(output_path)

    def export_cif(
        self,
        structure,
        output_path: str | Path,
    ) -> str:
        """导出CIF文件

        Args:
            structure: pymatgen Structure 对象
            output_path: 输出路径

        Returns:
            生成的文件路径
        """
        output_path = Path(output_path)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".cif")

        structure.to(filename=str(output_path))
        return str(output_path)

    def export_xrd_data(
        self,
        data: XRDData,
        output_path: str | Path,
        format: str = "csv",
    ) -> str:
        """导出XRD数据

        Args:
            data: XRD数据
            output_path: 输出路径
            format: 输出格式

        Returns:
            生成的文件路径
        """
        output_path = Path(output_path)
        if not output_path.suffix:
            output_path = output_path.with_suffix(f".{format}")

        if format == "csv":
            data.export_csv(output_path)
        elif format == "xy":
            data.export_csv(output_path, delimiter=" ")
        elif format == "json":
            # v1.1.1: 补显式编码。此前 open() 未指定 encoding, 中文 Windows 上会按
            # GBK 落盘 —— 同一个文件在英文机器上读就是乱码。ensure_ascii=False 让
            # 导出的 JSON 直接是可读中文 (文件本身已明确是 UTF-8)。
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data.to_dict(), f, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"不支持的导出格式: {format}")

        return str(output_path)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _export_phases_csv(phases: list[Phase], path: Path) -> None:
        """导出物相CSV"""
        import csv

        # v1.1.1: utf-8-sig (带 BOM)。表头是中文, 而 Excel / WPS 打开**不带 BOM**
        # 的 UTF-8 CSV 时会按系统 ANSI 代码页解释 → 中文必然是乱码。
        # 带 BOM 后 Excel(任意语言环境)、LibreOffice、pandas 都能正确识别。
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "物相名称", "化学式", "匹配度(%)", "质量分数(wt%)",
                "a(Å)", "b(Å)", "c(Å)", "α(°)", "β(°)", "γ(°)",
                "空间群", "参考峰数",
            ])
            for phase in phases:
                lat = phase.lattice
                if lat is not None:
                    a_str = f"{lat.a:.4f}"
                    b_str = f"{lat.b:.4f}"
                    c_str = f"{lat.c:.4f}"
                    alpha_str = f"{lat.alpha:.2f}"
                    beta_str = f"{lat.beta:.2f}"
                    gamma_str = f"{lat.gamma:.2f}"
                else:
                    a_str = b_str = c_str = alpha_str = beta_str = gamma_str = "-"

                writer.writerow([
                    phase.name,
                    phase.formula,
                    f"{phase.match_score:.1f}",
                    f"{phase.weight_fraction:.2f}",
                    a_str,
                    b_str,
                    c_str,
                    alpha_str,
                    beta_str,
                    gamma_str,
                    phase.space_group,
                    len(phase.reference_peaks),
                ])

    @staticmethod
    def _export_params_csv(params: dict, path: Path) -> None:
        """导出参数CSV"""
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["参数名", "值"])
            for key, value in params.items():
                writer.writerow([key, str(value)])