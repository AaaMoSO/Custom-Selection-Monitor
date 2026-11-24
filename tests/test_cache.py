import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.cache import FILE_PREFIX, FrameCache


def image(value: int = 0, size: int = 8) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


class FrameCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "frames"

    def test_keeps_only_capacity_files(self):
        cache = FrameCache(self.dir, capacity=3)
        for value in range(5):
            cache.store(image(value))
        self.assertTrue(cache.wait_idle())
        self.assertEqual(cache.count, 3)
        files = sorted(self.dir.glob(f"{FILE_PREFIX}*.png"))
        self.assertEqual(len(files), 3)
        # 最早的 000001 / 000002 应被淘汰
        names = [p.name for p in files]
        self.assertNotIn("000001", " ".join(names))
        self.assertTrue(names[-1].startswith("frame_000005"))
        cache.close()

    def test_clear_removes_files(self):
        cache = FrameCache(self.dir, capacity=4)
        cache.store(image(1))
        cache.store(image(2))
        self.assertTrue(cache.wait_idle())
        self.assertEqual(cache.count, 2)
        cache.clear()
        self.assertEqual(cache.count, 0)
        self.assertEqual(list(self.dir.glob(f"{FILE_PREFIX}*.png")), [])

    def test_reset_restarts_and_reuses_sequence(self):
        cache = FrameCache(self.dir, capacity=4)
        cache.store(image(1))
        self.assertTrue(cache.wait_idle())
        cache.reset()
        cache.store(image(2))
        self.assertTrue(cache.wait_idle())
        self.assertEqual(cache.count, 1)
        self.assertEqual(len(list(self.dir.glob("*.png"))), 1)
        cache.close()

    def test_write_error_is_recorded_not_raised(self):
        blocker = Path(self._tmp.name) / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        cache = FrameCache(blocker, capacity=2)
        cache.store(image(1))
        self.assertTrue(cache.wait_idle())
        error = cache.consume_error()
        self.assertIsNotNone(error)
        self.assertIsNone(cache.consume_error())  # 只上报一次
        cache.close()

    def test_latest_points_to_newest(self):
        cache = FrameCache(self.dir, capacity=3)
        cache.store(image(7))
        self.assertTrue(cache.wait_idle())
        latest = cache.latest
        self.assertIsNotNone(latest)
        self.assertTrue(latest.name.endswith(".png"))
        cache.close()

    def test_capacity_floor(self):
        cache = FrameCache(self.dir, capacity=0)
        self.assertEqual(cache.capacity, 1)
        cache.close()


if __name__ == "__main__":
    unittest.main()
