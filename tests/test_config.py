import tempfile
import unittest
from pathlib import Path

from app.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            original = AppConfig(
                threshold_percent=2.5,
                tolerance=12,
                max_unchanged=8,
                save_folder=str(Path(tmp) / "shots"),
            )
            original.save(path)
            loaded = AppConfig.load(path)
            self.assertEqual(loaded, original)

    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = AppConfig.load(Path(tmp) / "nope.json")
            self.assertEqual(loaded.threshold_percent, 1.0)
            self.assertEqual(loaded.tolerance, 8)
            self.assertEqual(loaded.max_unchanged, 5)

    def test_broken_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(AppConfig.load(path).max_unchanged, 5)

    def test_resolved_save_folder_uses_default_when_empty(self):
        config = AppConfig()
        self.assertIn("PauseRecognition", str(config.resolved_save_folder()))


if __name__ == "__main__":
    unittest.main()
