"""把触发时刻的截图复制到目标文件夹。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image


def save_frame(
    image: np.ndarray,
    folder: str | Path,
    captured_at: datetime | None = None,
    prefix: str = "pause",
) -> Path:
    """把一帧 RGB 图像以 PNG 写入 ``folder``，返回实际落盘路径。

    以无损 PNG 保存，保证“复制一份”不引入二次压缩误差。
    同名文件已存在时自动追加序号，绝不覆盖历史截图。
    """
    target_dir = Path(folder).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)

    moment = captured_at or datetime.now()
    stem = f"{prefix}_{moment.strftime('%Y%m%d-%H%M%S')}"

    candidate = target_dir / f"{stem}.png"
    index = 1
    while candidate.exists():
        candidate = target_dir / f"{stem}_{index}.png"
        index += 1

    Image.fromarray(image).save(candidate, format="PNG")
    return candidate
