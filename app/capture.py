"""屏幕区域截取（基于 mss，物理像素坐标）。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CaptureRegion:
    """以物理像素描述的屏幕矩形。"""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def to_mss(self) -> dict[str, int]:
        return {
            "left": int(self.left),
            "top": int(self.top),
            "width": int(self.width),
            "height": int(self.height),
        }

    def describe(self) -> str:
        return f"{self.width}×{self.height} @ ({self.left}, {self.top})"


class ScreenCapturer:
    """复用同一个 mss 实例截屏；只能在创建它的线程里使用。"""

    def __init__(self) -> None:
        self._sct = None

    def _ensure(self):
        if self._sct is None:
            import mss

            factory = getattr(mss, "MSS", None) or mss.mss  # 10.2+ 推荐 MSS
            self._sct = factory()
        return self._sct

    def grab(self, region: CaptureRegion) -> np.ndarray:
        """截取区域并返回 H×W×3 uint8 RGB 数组。"""
        if not region.is_valid():
            raise ValueError(f"无效的截取区域: {region}")

        sct = self._ensure()
        try:
            shot = sct.grab(region.to_mss())
        except Exception:
            # mss 实例在分辨率变化后可能失效，重建一次再试
            self.close()
            sct = self._ensure()
            shot = sct.grab(region.to_mss())

        # mss 返回 BGRA
        bgra = np.asarray(shot, dtype=np.uint8)
        return np.ascontiguousarray(bgra[:, :, 2::-1])

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
