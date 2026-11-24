import unittest

import numpy as np

from app.diff import change_ratio, compare


def solid(value: int, shape=(10, 10, 3)) -> np.ndarray:
    return np.full(shape, value, dtype=np.uint8)


class DiffTests(unittest.TestCase):
    def test_identical_frames(self):
        frame = solid(120)
        result = compare(frame, frame.copy())
        self.assertEqual(result.changed_pixels, 0)
        self.assertEqual(result.ratio, 0.0)
        self.assertTrue(result.unchanged)

    def test_within_tolerance_is_same_pixel(self):
        base = solid(100)
        other = base.copy()
        other[0, 0] = 108  # 三个通道都差 8，恰好等于容差
        self.assertEqual(compare(base, other, tolerance=8).changed_pixels, 0)
        self.assertEqual(compare(base, other, tolerance=7).changed_pixels, 1)

    def test_one_pixel_changed(self):
        base = solid(0)
        other = base.copy()
        other[3, 7] = 255
        result = compare(base, other, tolerance=8)
        self.assertEqual(result.changed_pixels, 1)
        self.assertAlmostEqual(result.ratio, 1.0)  # 1 / 100

    def test_full_change_is_100_percent(self):
        base = solid(0)
        other = solid(255)
        self.assertAlmostEqual(compare(base, other).ratio, 100.0)

    def test_half_change(self):
        base = solid(0)
        other = base.copy()
        other[:5, :] = 255
        self.assertAlmostEqual(compare(base, other).ratio, 50.0)

    def test_tolerance_zero(self):
        base = solid(10)
        other = base.copy()
        other[0, 0] = 11
        self.assertEqual(compare(base, other, tolerance=0).changed_pixels, 1)

    def test_shape_mismatch_treated_as_changed(self):
        self.assertEqual(compare(solid(0, (4, 4, 3)), solid(0, (5, 5, 3))).ratio, 100.0)

    def test_none_is_changed(self):
        self.assertEqual(compare(None, solid(0)).ratio, 100.0)
        self.assertEqual(compare(solid(0), None).ratio, 100.0)

    def test_change_ratio_helper(self):
        base = solid(0)
        other = base.copy()
        other[:2, :] = 99
        self.assertAlmostEqual(change_ratio(base, other), 20.0)


if __name__ == "__main__":
    unittest.main()
