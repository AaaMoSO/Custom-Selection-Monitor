"""numpy 图像与 QImage 的转换（主窗口与对话框共用）。"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


def numpy_to_qimage(image: np.ndarray) -> QImage:
    data = np.ascontiguousarray(image)
    height, width, channels = data.shape
    qimage = QImage(data.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return qimage.copy()
