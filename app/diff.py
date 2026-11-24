"""像素差异比较。

判定口径（与产品定义一致）：
- 逐像素比较 RGB，若某像素任一通道的差值 **大于** ``tolerance``，该像素计为“变化”；
  否则视为同一像素（容差用于吸收视频噪点、抗锯齿、轻微渐变）。
- 变化率 = 变化像素数 / 总像素数 × 100，取值范围 [0, 100]。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_TOLERANCE = 8


@dataclass(frozen=True)
class CompareResult:
    """一次比对的完整结果。"""

    ratio: float
    changed_pixels: int
    total_pixels: int
    magnitude: float

    @property
    def unchanged(self) -> bool:
        return self.changed_pixels == 0


def compare(
    previous: np.ndarray | None,
    current: np.ndarray | None,
    tolerance: int = DEFAULT_TOLERANCE,
) -> CompareResult:
    """比较两张同尺寸 RGB 图像。

    任何一张为空或尺寸不一致时视为完全变化（返回 100%），
    调用方通常会把第一帧当作基准帧而不参与比较。
    """
    if previous is None or current is None:
        return CompareResult(ratio=100.0, changed_pixels=0, total_pixels=0, magnitude=0.0)
    if previous.shape != current.shape:
        return CompareResult(ratio=100.0, changed_pixels=0, total_pixels=0, magnitude=0.0)

    total = int(previous.shape[0] * previous.shape[1])
    if total == 0:
        return CompareResult(ratio=0.0, changed_pixels=0, total_pixels=0, magnitude=0.0)

    diff = np.subtract(current, previous, dtype=np.int16)
    diff = np.abs(diff)

    if diff.ndim == 3:
        changed_mask = np.any(diff > int(tolerance), axis=2)
        magnitude = float(diff.max()) if changed_mask.any() else 0.0
    else:
        changed_mask = diff > int(tolerance)
        magnitude = float(diff.max()) if changed_mask.any() else 0.0

    changed = int(np.count_nonzero(changed_mask))
    return CompareResult(
        ratio=changed * 100.0 / total,
        changed_pixels=changed,
        total_pixels=total,
        magnitude=magnitude,
    )


def change_ratio(
    previous: np.ndarray | None,
    current: np.ndarray | None,
    tolerance: int = DEFAULT_TOLERANCE,
) -> float:
    """便捷函数：只取变化率百分比。"""
    return compare(previous, current, tolerance).ratio
