import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from app.saver import save_frame


class SaverTests(unittest.TestCase):
    def test_writes_lossless_png(self):
        image = np.zeros((12, 16, 3), dtype=np.uint8)
        image[:, :, 0] = 255
        with tempfile.TemporaryDirectory() as tmp:
            path = save_frame(image, tmp, datetime(2026, 1, 2, 3, 4, 5))
            self.assertTrue(Path(path).exists())
            self.assertEqual(Path(path).suffix, ".png")
            self.assertIn("20260102-030405", Path(path).name)
            with Image.open(path) as saved:
                self.assertEqual(saved.size, (16, 12))
                self.assertEqual(saved.getpixel((0, 0))[:3], (255, 0, 0))

    def test_never_overwrites(self):
        image = np.full((4, 4, 3), 7, dtype=np.uint8)
        moment = datetime(2026, 1, 2, 3, 4, 5)
        with tempfile.TemporaryDirectory() as tmp:
            first = save_frame(image, tmp, moment)
            second = save_frame(image, tmp, moment)
            self.assertNotEqual(first, second)
            self.assertEqual(len(list(Path(tmp).glob("*.png"))), 2)

    def test_creates_folder(self):
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "deeper"
            path = save_frame(image, target)
            self.assertTrue(target.is_dir())
            self.assertTrue(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
