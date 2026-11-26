"""把触发时刻的截图与选框位置打包成一个文件夹。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .config import APP_NAME, APP_VERSION


def save_capture(
    image: np.ndarray,
    folder: str | Path,
    region,
    captured_at: datetime | None = None,
    metadata: dict | None = None,
    prefix: str = "pause",
) -> Path:
    """在 ``folder`` 下创建一个文件夹，内含尾图与选框位置。

    文件夹结构：

    * ``tail.png``   —— 触发帧（无损 PNG）
    * ``region.json`` —— 选框的屏幕坐标、显示器布局、触发参数

    同名文件夹已存在时自动追加序号，绝不覆盖历史记录。
    """
    target_root = Path(folder).expanduser()
    target_root.mkdir(parents=True, exist_ok=True)

    moment = captured_at or datetime.now()
    stem = f"{prefix}_{moment.strftime('%Y%m%d-%H%M%S')}"

    directory = target_root / stem
    index = 1
    while directory.exists():
        directory = target_root / f"{stem}_{index}"
        index += 1
    directory.mkdir(parents=True)

    Image.fromarray(image).save(directory / "tail.png", format="PNG")

    screen = _screen_info()
    payload = {
        "created_at": moment.astimezone().isoformat(timespec="seconds"),
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "capture": {
            "file": "tail.png",
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        },
        "region": {
            "left": int(region.left),
            "top": int(region.top),
            "width": int(region.width),
            "height": int(region.height),
            "right": int(region.right),
            "bottom": int(region.bottom),
            "monitor": _monitor_of(region, screen.get("monitors") or []),
        },
        "screen": screen,
        "trigger": dict((metadata or {}).get("trigger") or {}),
        "audio": dict((metadata or {}).get("audio") or {}),
    }
    (directory / "region.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return directory


def _screen_info() -> dict:
    """物理像素下的虚拟桌面与各显示器矩形；取不到时返回空字典。"""
    try:
        from .screens import enumerate_monitors, virtual_desktop

        left, top, width, height = virtual_desktop()
        monitors = [
            {
                "device": monitor.device,
                "left": monitor.left,
                "top": monitor.top,
                "width": monitor.width,
                "height": monitor.height,
                "primary": monitor.primary,
            }
            for monitor in enumerate_monitors()
        ]
        return {
            "virtual": {"left": left, "top": top, "width": width, "height": height},
            "monitors": monitors,
        }
    except Exception:
        return {}


def _monitor_of(region, monitors: list[dict]) -> str:
    """选框中心点落在哪块显示器上。"""
    center_x = region.left + region.width // 2
    center_y = region.top + region.height // 2
    for monitor in monitors:
        if (
            monitor["left"] <= center_x < monitor["left"] + monitor["width"]
            and monitor["top"] <= center_y < monitor["top"] + monitor["height"]
        ):
            return str(monitor["device"])
    return ""
