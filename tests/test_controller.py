import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.audio import AudioDevice
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


class FakeMeter:
    """按顺序返回预设电平，模拟音频门控。"""

    def __init__(self, levels: list[float | None]) -> None:
        self.levels = list(levels)
        self.index = 0
        self.started: list[AudioDevice] = []
        self.stop_calls = 0
        self.error: str | None = None

    def start(self, device: AudioDevice) -> None:
        self.started.append(device)
        self.index = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def level_since_last(self) -> float | None:
        if self.index < len(self.levels):
            value = self.levels[self.index]
            self.index += 1
            return value
        return self.levels[-1] if self.levels else None


class ControllerAudioTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = AppConfig(
            threshold_percent=1.0,
            tolerance=8,
            max_unchanged=5,
            save_folder=str(self.root / "out"),
        )
        self.meter = FakeMeter([-40.0, -40.1, -40.2, -10.0, -10.1])
        self.controller = MonitorController(
            self.config,
            capturer=FakeCapturer(),
            cache=FrameCache(self.root / "frames", capacity=10),
            audio=self.meter,
        )
        self.controller._timer = FakeTimer()
        self.controller.set_region(CaptureRegion(0, 0, 20, 10))
        self.addCleanup(self.controller.shutdown)

    def test_gate_requires_two_samples_then_counts_stable_levels(self):
        controller = self.controller
        controller.configure_audio(True, AudioDevice("dev-id", "测试设备"), 1.5)
        controller.start()
        self.assertEqual(self.meter.started[-1].id, "dev-id")

        controller._tick()  # 只有 1 个电平样本 → 跳过
        self.assertEqual(controller.state, MonitorState.MONITORING)
        self.assertEqual(controller._detector.unchanged_count, 0)
        self.assertEqual(controller.stats()["audio_stable"], None)

        controller._tick()  # 电平 -40.1，与 -40.0 差 0.1 → 稳定 → 比对（n=1）
        self.assertEqual(controller._detector.unchanged_count, 1)
        self.assertTrue(controller.stats()["audio_stable"])

        controller._tick()  # -40.2 仍稳定 → n=2
        self.assertEqual(controller._detector.unchanged_count, 2)

        controller._tick()  # 跳到 -10.0 → 跳过并清零
        self.assertEqual(controller._detector.unchanged_count, 0)
        self.assertFalse(controller.stats()["audio_stable"])
        self.assertEqual(controller.stats()["audio_skipped"], 1)

    def test_audio_level_is_reported_in_stats(self):
        controller = self.controller
        controller.configure_audio(True, AudioDevice("dev", "dev"), 1.5)
        controller.start()
        controller._tick()
        controller._tick()
        self.assertAlmostEqual(controller.stats()["audio_level"], -40.1, places=2)

    def test_disabled_gate_keeps_pixel_behaviour(self):
        controller = self.controller
        controller.configure_audio(False, None, 1.5)
        controller.start()
        controller._tick()  # 基准
        controller._tick()  # n=1
        self.assertEqual(controller._detector.unchanged_count, 1)
        self.assertEqual(self.meter.started, [])
        self.assertIsNone(controller.stats()["audio_level"])

    def test_audio_error_skips_analysis_and_logs_once(self):
        self.meter.error = "device lost"
        messages: list[str] = []
        self.controller.logged.connect(messages.append)
        self.controller.configure_audio(True, AudioDevice("dev", "dev"), 1.5)
        self.controller.start()
        self.controller._tick()
        self.controller._tick()
        self.assertEqual(sum("音频设备不可用" in message for message in messages), 1)
        self.assertEqual(self.controller._detector.unchanged_count, 0)

    def test_pause_stops_audio_and_resume_restarts(self):
        controller = self.controller
        controller.configure_audio(True, AudioDevice("dev", "dev"), 1.5)
        controller.start()
        self.assertEqual(len(self.meter.started), 1)
        controller._tick()
        controller.pause()
        self.assertGreaterEqual(self.meter.stop_calls, 1)
        controller.resume()
        self.assertEqual(len(self.meter.started), 2)


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

    def test_clear_region_stops_monitoring_and_resets(self):
        controller = self.controller
        controller.start()
        controller._tick()
        self.assertTrue(self.cache.wait_idle())
        self.assertIsNotNone(controller.region)

        controller.clear_region()
        self.assertIsNone(controller.region)
        self.assertEqual(controller.state, MonitorState.IDLE)
        self.assertEqual(len(controller.buffer), 0)
        self.assertEqual(self.cache.count, 0)
        self.assertEqual(list((self.root / "frames").glob("*.png")), [])

    def test_clear_region_when_idle_is_safe(self):
        controller = self.controller
        controller.clear_region()
        self.assertIsNone(controller.region)
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
