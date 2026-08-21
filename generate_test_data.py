"""
PolyXRD 测试数据生成器
====================
生成模拟的XRD数据用于测试。
"""
import numpy as np
from pathlib import Path


def generate_si_powder_data(filepath: str, num_points: int = 500) -> None:
    """生成模拟硅粉XRD数据 (NIST SRM 640e标准参考)"""
    two_theta = np.linspace(20.0, 100.0, num_points)
    wavelength = 1.5406  # Cu Kα1

    # Si的主要衍射峰 (d-spacing, hkl)
    si_peaks = [
        (3.1355, (1, 1, 1), 100),
        (1.9200, (2, 2, 0), 60),
        (1.6374, (3, 1, 1), 35),
        (1.3573, (4, 0, 0), 15),
        (1.2459, (3, 3, 1), 25),
        (1.0918, (4, 2, 2), 10),
        (1.0452, (5, 1, 1), 8),
        (0.9600, (4, 4, 0), 5),
        (0.9175, (6, 2, 0), 5),
        (0.8287, (5, 3, 1), 8),
        (0.7838, (4, 4, 4), 5),
    ]

    intensity = np.zeros_like(two_theta)

    for d, hkl, rel_intensity in si_peaks:
        # 计算峰位2θ
        sin_theta = wavelength / (2 * d)
        if sin_theta <= 1:
            theta = np.arcsin(sin_theta)
            peak_2theta = 2 * np.degrees(theta)

            # 计算多重性
            h, k, l = hkl
            if h == k == l:
                mult = 8
            elif h == k:
                mult = 12
            elif h == 0 and k == 0:
                mult = 6
            else:
                mult = 24

            # 峰形 (Gaussian + Lorentzian)
            fwhm = 0.15  # 度
            sigma = fwhm / 2.355
            gamma = fwhm / 2.0

            # 混合峰形
            gauss = np.exp(-0.5 * ((two_theta - peak_2theta) / sigma) ** 2)
            lorentz = gamma**2 / ((two_theta - peak_2theta) ** 2 + gamma**2)
            peak_shape = 0.5 * gauss + 0.5 * lorentz

            intensity += rel_intensity * mult * peak_shape

    # 添加背景
    background = 2 * np.exp(-((two_theta - 60) / 30) ** 2) + 0.5
    intensity += background

    # 添加噪声
    noise = np.random.normal(0, 0.5, num_points)
    intensity += noise
    intensity = np.maximum(intensity, 0)

    # 写入文件
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# PolyXRD 测试数据 - Silicon Powder (NIST SRM 640e)\n")
        f.write(f"# Wavelength: {wavelength} A (Cu Ka1)\n")
        f.write(f"# TwoTheta range: {two_theta[0]:.2f} - {two_theta[-1]:.2f}\n")
        f.write(f"# Points: {num_points}\n")
        f.write("# Two_Theta\tIntensity\n")
        for tt, intens in zip(two_theta, intensity):
            f.write(f"{tt:.4f}\t{intens:.2f}\n")

    print(f"已生成测试数据: {filepath}")


def generate_sio2_quartz_data(filepath: str, num_points: int = 500) -> None:
    """生成模拟α-石英XRD数据"""
    two_theta = np.linspace(15.0, 90.0, num_points)
    wavelength = 1.5406

    # α-Quartz的主要衍射峰
    quartz_peaks = [
        (3.3434, (1, 0, 0), 100),
        (3.2340, (0, 1, 0), 100),
        (2.4580, (1, 0, 1), 25),
        (2.2830, (1, 1, 0), 60),
        (1.9820, (1, 0, 2), 5),
        (1.8150, (2, 0, 0), 10),
        (1.6720, (2, 0, 1), 8),
        (1.5530, (1, 1, 2), 15),
        (1.4690, (0, 2, 0), 20),
        (1.3790, (2, 1, 0), 5),
        (1.2970, (1, 2, 1), 10),
        (1.2280, (2, 0, 2), 5),
        (1.1810, (3, 0, 0), 5),
    ]

    intensity = np.zeros_like(two_theta)

    for d, hkl, rel_intensity in quartz_peaks:
        sin_theta = wavelength / (2 * d)
        if sin_theta <= 1:
            theta = np.arcsin(sin_theta)
            peak_2theta = 2 * np.degrees(theta)

            h, k, l = hkl
            if h == 0 and k == 0:
                mult = 2
            elif h == 0 or k == 0:
                mult = 4
            else:
                mult = 8

            fwhm = 0.12
            sigma = fwhm / 2.355
            gamma = fwhm / 2.0

            gauss = np.exp(-0.5 * ((two_theta - peak_2theta) / sigma) ** 2)
            lorentz = gamma**2 / ((two_theta - peak_2theta) ** 2 + gamma**2)
            peak_shape = 0.6 * gauss + 0.4 * lorentz

            intensity += rel_intensity * mult * peak_shape

    # 添加背景和噪声
    background = 1.5 * np.exp(-((two_theta - 50) / 25) ** 2) + 0.3
    intensity += background
    noise = np.random.normal(0, 0.3, num_points)
    intensity += noise
    intensity = np.maximum(intensity, 0)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# PolyXRD 测试数据 - alpha-Quartz\n")
        f.write(f"# Wavelength: {wavelength} A (Cu Ka1)\n")
        f.write(f"# Two_Theta range: {two_theta[0]:.2f} - {two_theta[-1]:.2f}\n")
        f.write(f"# Points: {num_points}\n")
        f.write("# Two_Theta\tIntensity\n")
        for tt, intens in zip(two_theta, intensity):
            f.write(f"{tt:.4f}\t{intens:.2f}\n")

    print(f"已生成测试数据: {filepath}")


def generate_nacl_data(filepath: str, num_points: int = 500) -> None:
    """生成模拟NaCl (Halite) XRD数据"""
    two_theta = np.linspace(20.0, 80.0, num_points)
    wavelength = 1.5406

    # NaCl的主要衍射峰
    nacl_peaks = [
        (2.8214, (1, 1, 1), 100),
        (1.9990, (2, 0, 0), 55),
        (1.6310, (2, 2, 0), 30),
        (1.4100, (3, 1, 1), 10),
        (1.2900, (2, 2, 2), 10),
        (1.1050, (4, 0, 0), 5),
        (1.0420, (3, 3, 1), 10),
        (0.9995, (4, 2, 0), 5),
    ]

    intensity = np.zeros_like(two_theta)

    for d, hkl, rel_intensity in nacl_peaks:
        sin_theta = wavelength / (2 * d)
        if sin_theta <= 1:
            theta = np.arcsin(sin_theta)
            peak_2theta = 2 * np.degrees(theta)

            h, k, l = hkl
            if h == k == l:
                mult = 8
            elif h == k:
                mult = 12
            elif h == 0:
                mult = 6
            else:
                mult = 24

            fwhm = 0.18
            sigma = fwhm / 2.355
            gamma = fwhm / 2.0

            gauss = np.exp(-0.5 * ((two_theta - peak_2theta) / sigma) ** 2)
            lorentz = gamma**2 / ((two_theta - peak_2theta) ** 2 + gamma**2)
            peak_shape = 0.4 * gauss + 0.6 * lorentz

            intensity += rel_intensity * mult * peak_shape

    background = 1.0 * np.exp(-((two_theta - 45) / 20) ** 2) + 0.2
    intensity += background
    noise = np.random.normal(0, 0.3, num_points)
    intensity += noise
    intensity = np.maximum(intensity, 0)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# PolyXRD 测试数据 - NaCl (Halite)\n")
        f.write(f"# Wavelength: {wavelength} A (Cu Ka1)\n")
        f.write(f"# Two_Theta range: {two_theta[0]:.2f} - {two_theta[-1]:.2f}\n")
        f.write(f"# Points: {num_points}\n")
        f.write("# Two_Theta\tIntensity\n")
        for tt, intens in zip(two_theta, intensity):
            f.write(f"{tt:.4f}\t{intens:.2f}\n")

    print(f"已生成测试数据: {filepath}")


def main():
    """生成所有测试数据"""
    # 确保测试数据目录存在
    test_dir = Path(__file__).parent / "test_data"
    test_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("  PolyXRD 测试数据生成")
    print("=" * 50)
    print()

    # 生成各种测试数据
    generate_si_powder_data(str(test_dir / "si_powder.xy"))
    print()
    generate_sio2_quartz_data(str(test_dir / "sio2_quartz.xy"))
    print()
    generate_nacl_data(str(test_dir / "nacl_halite.xy"))

    print()
    print("=" * 50)
    print(f"  测试数据生成完成！")
    print(f"  输出目录: {test_dir}")
    print("=" * 50)


if __name__ == "__main__":
    np.random.seed(42)  # 固定种子以便复现
    main()
