import unittest

import numpy as np

from app.buffer import Frame, FrameBuffer
from app.state import ChangeDetector, Decision, DetectorConfig, MonitorState


def frame(value: int = 0) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


class BufferTests(unittest.TestCase):
    def test_evicts_oldest_when_full(self):
        buffer = FrameBuffer(capacity=3)
        for index in range(4):
            evicted = buffer.push(Frame(image=frame(index), captured_at=None))
            if index < 3:
                self.assertIsNone(evicted)
            else:
                self.assertIsNotNone(evicted)
                self.assertEqual(int(evicted.image[0, 0, 0]), 0)
        self.assertEqual(len(buffer), 3)
        self.assertEqual(int(buffer.latest.image[0, 0, 0]), 3)
        self.assertEqual(int(buffer.previous.image[0, 0, 0]), 2)

    def test_clear_and_properties(self):
        buffer = FrameBuffer(capacity=2)
        self.assertIsNone(buffer.latest)
        self.assertIsNone(buffer.previous)
        buffer.push(Frame(image=frame(), captured_at=None))
        self.assertEqual(len(buffer), 1)
        self.assertIsNone(buffer.previous)
        buffer.clear()
        self.assertEqual(len(buffer), 0)

    def test_capacity_must_be_positive(self):
        with self.assertRaises(ValueError):
            FrameBuffer(capacity=0)


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.config = DetectorConfig(threshold_percent=1.0, tolerance=8, max_unchanged=3)
        self.detector = ChangeDetector(self.config)

    def test_idle_ignores_frames(self):
        self.assertEqual(self.detector.feed(frame()), Decision.IGNORED)

    def test_first_frame_is_baseline(self):
        self.detector.start()
        self.assertEqual(self.detector.feed(frame(0)), Decision.BASELINE)
        self.assertEqual(self.detector.unchanged_count, 0)
        self.assertIsNone(self.detector.last_ratio)

    def test_strictly_more_than_limit_triggers(self):
        self.detector.start()
        self.detector.feed(frame(0))
        for expected in (1, 2, 3):
            self.assertEqual(self.detector.feed(frame(0)), Decision.UNCHANGED)
            self.assertEqual(self.detector.unchanged_count, expected)
        self.assertEqual(self.detector.state, MonitorState.MONITORING)
        # 第 4 次未变化：n = 4 > 3 → 触发
        self.assertEqual(self.detector.feed(frame(0)), Decision.TRIGGERED)
        self.assertEqual(self.detector.state, MonitorState.PAUSED)

    def test_change_resets_counter(self):
        self.detector.start()
        self.detector.feed(frame(0))
        self.detector.feed(frame(0))
        self.assertEqual(self.detector.unchanged_count, 1)
        self.assertEqual(self.detector.feed(frame(200)), Decision.CHANGED)
        self.assertEqual(self.detector.unchanged_count, 0)

    def test_paused_ignores_frames(self):
        self.detector.start()
        self.detector.feed(frame(0))
        for _ in range(4):
            self.detector.feed(frame(0))
        self.assertEqual(self.detector.state, MonitorState.PAUSED)
        self.assertEqual(self.detector.feed(frame(0)), Decision.IGNORED)

    def test_resume_rebuilds_baseline(self):
        self.detector.start()
        self.detector.feed(frame(0))
        for _ in range(4):
            self.detector.feed(frame(0))
        self.detector.resume()
        self.assertEqual(self.detector.state, MonitorState.MONITORING)
        self.assertEqual(self.detector.unchanged_count, 0)
        self.assertEqual(self.detector.feed(frame(0)), Decision.BASELINE)

    def test_threshold_boundary_counts_as_change(self):
        detector = ChangeDetector(
            DetectorConfig(threshold_percent=1.0, tolerance=8, max_unchanged=5)
        )
        detector.start()
        detector.feed(np.zeros((10, 10, 3), dtype=np.uint8))
        changed = np.zeros((10, 10, 3), dtype=np.uint8)
        changed[0, 0] = 255  # 1/100 = 1.0%，恰好等于阈值 → 不算“低于”
        self.assertEqual(detector.feed(changed), Decision.CHANGED)

    def test_config_is_clamped(self):
        detector = ChangeDetector(
            DetectorConfig(threshold_percent=500, tolerance=-3, max_unchanged=-9)
        )
        self.assertEqual(detector.config.threshold_percent, 100.0)
        self.assertEqual(detector.config.tolerance, 0)
        self.assertEqual(detector.config.max_unchanged, 0)


if __name__ == "__main__":
    unittest.main()
