"""
数据管理ViewModel
=================
管理数据加载、保存、预处理等状态。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from polyxrd.models.xrd_data import XRDData, BackgroundResult
from polyxrd.services.data_loader import DataLoader, save_xy
from polyxrd.services.data_preprocessor import DataPreprocessor


class DataViewModel(QObject):
    """数据管理ViewModel

    Signals:
        data_loaded: 数据加载完成
        data_updated: 数据更新
        background_subtracted: 背景扣除完成
        error: 错误发生
    """

    data_loaded = Signal(object)
    data_updated = Signal(object)
    background_subtracted = Signal(object)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loader = DataLoader()
        self._preprocessor = DataPreprocessor()

        self._raw_data: Optional[XRDData] = None
        self._processed_data: Optional[XRDData] = None
        self._background_result: Optional[BackgroundResult] = None
        self._file_path: Optional[Path] = None

    @property
    def raw_data(self) -> Optional[XRDData]:
        return self._raw_data

    @property
    def current_data(self) -> Optional[XRDData]:
        """返回当前数据 (已处理或原始)"""
        return self._processed_data or self._raw_data

    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def load_file(
        self,
        file_path: str | Path,
        wavelength: Optional[float] = None,
    ) -> None:
        """加载数据文件"""
        try:
            data = self._loader.load(file_path, wavelength=wavelength)
            self._raw_data = data
            self._processed_data = data.copy()
            self._file_path = Path(file_path)
            self.data_loaded.emit(data)
            self.data_updated.emit(data)
        except Exception as e:
            self.error.emit(str(e))

    def save_file(self, file_path: str | Path, format: str = "xy") -> None:
        """保存数据"""
        data = self.current_data
        if data is None:
            self.error.emit("没有数据可保存")
            return

        try:
            save_xy(data, file_path, fmt=format)
        except Exception as e:
            self.error.emit(str(e))

    def subtract_background(
        self,
        method: str = "snip",
        **kwargs,
    ) -> None:
        """背景扣除"""
        data = self.current_data
        if data is None:
            self.error.emit("请先加载数据")
            return

        try:
            result = self._preprocessor.subtract_background(data, method=method, **kwargs)
            self._background_result = result
            self._processed_data = result.corrected
            self.background_subtracted.emit(result)
            self.data_updated.emit(self._processed_data)
        except Exception as e:
            self.error.emit(f"背景扣除失败: {e}")

    def smooth_data(
        self,
        method: str = "savgol",
        window: int = 11,
        **kwargs,
    ) -> None:
        """平滑数据"""
        data = self.current_data
        if data is None:
            self.error.emit("请先加载数据")
            return

        try:
            smoothed = self._preprocessor.smooth(data, method=method, window=window, **kwargs)
            self._processed_data = smoothed
            self.data_updated.emit(smoothed)
        except Exception as e:
            self.error.emit(f"平滑失败: {e}")

    def strip_ka_alpha2(
        self,
        wavelength_alpha1: float = 1.5406,
        wavelength_alpha2: float = 1.5444,
        ratio: float = 0.5,
    ) -> None:
        """Kα2峰剥离"""
        data = self.current_data
        if data is None:
            self.error.emit("请先加载数据")
            return

        try:
            corrected = self._preprocessor.strip_ka_alpha2(
                data, wavelength_alpha1, wavelength_alpha2, ratio
            )
            self._processed_data = corrected
            self.data_updated.emit(corrected)
        except Exception as e:
            self.error.emit(f"Kα2剥离失败: {e}")

    def reset_to_raw(self) -> None:
        """重置为原始数据"""
        if self._raw_data:
            self._processed_data = self._raw_data.copy()
            self.data_updated.emit(self._processed_data)

    def normalize(self) -> None:
        """归一化"""
        data = self.current_data
        if data is None:
            self.error.emit("请先加载数据")
            return
        self._processed_data = data.normalize()
        self.data_updated.emit(self._processed_data)

    def crop(self, two_theta_min: float, two_theta_max: float) -> None:
        """裁剪2θ范围"""
        data = self.current_data
        if data is None:
            self.error.emit("请先加载数据")
            return
        self._processed_data = data.crop(two_theta_min, two_theta_max)
        self.data_updated.emit(self._processed_data)
