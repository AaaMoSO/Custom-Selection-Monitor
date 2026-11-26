import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from app.capture import CaptureRegion
from app.saver import save_capture


class SaverTests(unittest.TestCase):
    def test_creates_folder_with_tail_and_region(self):
        image = np.zeros((12, 16, 3), dtype=np.uint8)
        image[:, :, 0] = 255
        region = CaptureRegion(100, 200, 16, 12)
        metadata = {"trigger": {"unchanged": 6}, "audio": {"enabled": False}}

        with tempfile.TemporaryDirectory() as tmp:
            folder = save_capture(
                image, tmp, region, datetime(2026, 1, 2, 3, 4, 5), metadata
            )
            self.assertTrue(folder.is_dir())
            self.assertIn("20260102-030405", folder.name)

            tail = folder / "tail.png"
            self.assertTrue(tail.exists())
            with Image.open(tail) as saved:
                self.assertEqual(saved.size, (16, 12))
                self.assertEqual(saved.getpixel((0, 0))[:3], (255, 0, 0))

            payload = json.loads((folder / "region.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["region"]["left"], 100)
            self.assertEqual(payload["region"]["top"], 200)
            self.assertEqual(payload["region"]["width"], 16)
            self.assertEqual(payload["region"]["height"], 12)
            self.assertEqual(payload["region"]["right"], 116)
            self.assertEqual(payload["region"]["bottom"], 212)
            self.assertEqual(payload["capture"]["file"], "tail.png")
            self.assertEqual(payload["capture"]["width"], 16)
            self.assertEqual(payload["trigger"]["unchanged"], 6)
            self.assertFalse(payload["audio"]["enabled"])
            self.assertTrue(payload["created_at"].startswith("2026-01-02T03:04:05"))

    def test_never_overwrites(self):
        image = np.full((4, 4, 3), 7, dtype=np.uint8)
        region = CaptureRegion(0, 0, 4, 4)
        moment = datetime(2026, 1, 2, 3, 4, 5)
        with tempfile.TemporaryDirectory() as tmp:
            first = save_capture(image, tmp, region, moment)
            second = save_capture(image, tmp, region, moment)
            self.assertNotEqual(first, second)
            self.assertTrue((first / "tail.png").exists())
            self.assertTrue((second / "tail.png").exists())
            self.assertEqual(len([p for p in Path(tmp).glob("pause_*") if p.is_dir()]), 2)

    def test_creates_output_root(self):
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        region = CaptureRegion(0, 0, 2, 2)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "deeper"
            folder = save_capture(image, target, region)
            self.assertTrue(target.is_dir())
            self.assertTrue(folder.is_dir())
            self.assertTrue((folder / "tail.png").exists())
            self.assertTrue((folder / "region.json").exists())


if __name__ == "__main__":
    unittest.main()
