"""真实链路冒烟测试：真实截屏 → 像素比对 → 计数 → 触发 → 落盘。

用法：
    python scripts/smoke_test.py
    python scripts/smoke_test.py --seconds 12 --threshold 0.5 --max-unchanged 2
    python scripts/smoke_test.py --region 100,100,640,480

退出码：0 = 成功触发并写出 PNG；2 = 窗口内未触发（画面一直在变）；1 = 出错。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.screens import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from PIL import Image  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.capture import CaptureRegion  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.controller import MonitorController  # noqa: E402
from app.screens import enumerate_monitors, virtual_desktop  # noqa: E402
from app.state import MonitorState  # noqa: E402


def default_region() -> CaptureRegion:
    monitors = [m for m in enumerate_monitors() if m.primary]
    if monitors:
        m = monitors[0]
    else:
        vl, vt, vw, vh = virtual_desktop()
        if vw <= 0:
            return CaptureRegion(0, 0, 320, 240)
        m = type("M", (), {"left": vl, "top": vt, "width": vw, "height": vh})()
    width = min(480, m.width // 2)
    height = min(320, m.height // 2)
    return CaptureRegion(
        left=m.left + (m.width - width) // 2,
        top=m.top + (m.height - height) // 2,
        width=width,
        height=height,
    )


def parse_region(text: str) -> CaptureRegion:
    parts = [int(v.strip()) for v in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--region 需要 left,top,width,height")
    return CaptureRegion(*parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pause recognition 真实链路冒烟测试")
    parser.add_argument("--seconds", type=int, default=10, help="最长等待秒数")
    parser.add_argument("--threshold", type=float, default=1.0, help="变化阈值百分比")
    parser.add_argument("--max-unchanged", type=int, default=1, help="连续未变化上限")
    parser.add_argument("--tolerance", type=int, default=8, help="像素容差")
    parser.add_argument("--region", type=parse_region, default=None, help="left,top,width,height")
    parser.add_argument("--out", default="", help="保存目录，默认为临时目录")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])

    region = args.region or default_region()
    out_dir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="pr-smoke-"))

    config = AppConfig(
        threshold_percent=args.threshold,
        tolerance=args.tolerance,
        max_unchanged=args.max_unchanged,
        save_folder=str(out_dir),
    )
    controller = MonitorController(config)
    controller.set_region(region)
    controller.logged.connect(lambda message: print("[log]", message))
    controller.failed.connect(lambda message: print("[err]", message))

    result: dict = {"path": None, "payload": None}

    def on_trigger(payload: dict) -> None:
        result["path"] = payload.get("path")
        result["payload"] = payload
        QTimer.singleShot(200, app.quit)

    controller.triggered.connect(on_trigger)
    controller.start()
    QTimer.singleShot(args.seconds * 1000, app.quit)
    app.exec()

    stats = controller.stats()
    cache = controller.cache
    cache.wait_idle()
    controller.shutdown()
    cache_files = sorted(cache.directory.glob("*.png")) if cache.directory.is_dir() else []
    print("缓存目录:", cache.directory, "| 退出后保留帧数:", len(cache_files))
    for path in cache_files[-3:]:
        print("   ", path.name)

    print("区域:", region.describe(), "| 物理桌面:", virtual_desktop())
    print(
        "帧数={frames} 缓存={buffer_size}/{capacity} n={unchanged}/{max_unchanged} "
        "上次变化率={last_ratio} 状态={state}".format(**stats)
    )

    path = result["path"]
    if path is None:
        print("结果: 窗口内未触发（画面持续变化或阈值过低）")
        return 2

    saved = Path(path)
    with Image.open(saved) as image:
        size = image.size
    print("结果: 已触发并保存", saved, "尺寸:", size)
    ok = size == (region.width, region.height) and saved.stat().st_size > 0
    print("校验:", "通过" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
