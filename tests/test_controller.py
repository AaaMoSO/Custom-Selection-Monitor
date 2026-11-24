import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.cache import FrameCache
from app.capture import CaptureRegion
from app.config import AppConfig
from app.controller import MonitorController
from app.state import MonitorState


class FakeCapturer:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def grab(self, region):
        self.calls += 1
        value = 0 if self.calls <= 5 else 255
        return np.full((10, 20, 3), value, dtype=np.uint8)

    def close(self):
        self.closed = True


class FakeTimer:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def isActive(self) -> bool:
        return self.started


class ControllerCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cache = FrameCache(self.root / "frames", capacity=10)
        self.capturer = FakeCapturer()
        self.config = AppConfig(
            threshold_percent=1.0,
            tolerance=8,
            max_unchanged=2,
            save_folder=str(self.root / "out"),
        )
        self.controller = MonitorController(
            self.config, capturer=self.capturer, cache=self.cache, capacity=10
        )
        self.controller._timer = FakeTimer()  # 测试里手动驱动，不依赖 Qt 事件循环
        self.controller.set_region(CaptureRegion(0, 0, 20, 10))
        self.addCleanup(self.controller.shutdown)

    def test_ticks_fill_cache_and_trigger_saves_tail(self):
        controller = self.controller
        self.assertTrue(controller.start())
        for _ in range(4):  # 基准 + 3 次比对，n 超过 2 → 第 4 帧触发
            controller._tick()

        self.assertTrue(self.cache.wait_idle())
        self.assertEqual(controller.state, MonitorState.PAUSED)
        self.assertEqual(len(controller.buffer), 4)
        self.assertEqual(self.cache.count, 4)
        self.assertEqual(len(list((self.root / "frames").glob("*.png"))), 4)

        outputs = list((self.root / "out").glob("pause_*.png"))
        self.assertEqual(len(outputs), 1)
        from PIL import Image

        with Image.open(outputs[0]) as saved:
            self.assertEqual(saved.size, (20, 10))

        # 触发只暂停，不清理缓存
        self.assertEqual(self.cache.count, 4)
        self.assertFalse(controller.state is MonitorState.IDLE)

    def test_stop_clears_cache(self):
        controller = self.controller
        controller.start()
        controller._tick()
        self.assertTrue(self.cache.wait_idle())
        self.assertEqual(self.cache.count, 1)

        controller.stop()
        self.assertEqual(self.cache.count, 0)
        self.assertEqual(list((self.root / "frames").glob("*.png")), [])
        self.assertEqual(controller.state, MonitorState.IDLE)

    def test_resume_keeps_cache_and_starts_new_baseline(self):
        controller = self.controller
        controller.start()
        for _ in range(4):
            controller._tick()
        self.assertTrue(self.cache.wait_idle())
        self.assertEqual(controller.state, MonitorState.PAUSED)
        before = self.cache.count

        controller.resume()
        self.assertEqual(controller.state, MonitorState.MONITORING)
        self.assertEqual(controller.cache.count, before)  # 恢复不丢缓存

        controller._tick()  # 新基准，不参与计数
        self.assertEqual(controller._detector.unchanged_count, 0)
        self.assertTrue(self.cache.wait_idle())
        self.assertEqual(self.cache.count, before + 1)

    def test_cache_error_is_reported_in_log(self):
        blocker = self.root / "blocked"
        blocker.write_text("not a dir", encoding="utf-8")
        broken = FrameCache(blocker, capacity=2)
        self.addCleanup(broken.close)
        controller = MonitorController(
            self.config, capturer=FakeCapturer(), cache=broken, capacity=2
        )
        controller._timer = FakeTimer()
        controller.set_region(CaptureRegion(0, 0, 20, 10))
        messages = []
        controller.logged.connect(messages.append)
        controller.start()
        controller._tick()
        self.assertTrue(broken.wait_idle())
        controller._tick()  # 第二次 tick 上报错误
        self.assertTrue(any("缓存写入失败" in message for message in messages))
        controller.shutdown()


if __name__ == "__main__":
    unittest.main()
