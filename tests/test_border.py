import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

try:  # PySide6 属于运行时依赖，缺失时跳过
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

from app.capture import CaptureRegion


def _red_pixels(image: QImage) -> int:
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            color = image.pixelColor(x, y)
            if color.red() > 200 and color.green() < 60 and color.blue() < 60:
                count += 1
    return count


@unittest.skipUnless(HAS_QT, "PySide6 不可用")
class RegionBorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        from app.border import RegionBorder

        self.border = RegionBorder()
        self.addCleanup(self.border.close)

    def test_region_creates_one_window_per_screen(self):
        from PySide6.QtCore import QRect

        self.border.set_region(CaptureRegion(0, 0, 200, 150), QRect(100, 100, 150, 100))
        self.app.processEvents()
        self.assertEqual(len(self.border._windows), len(QGuiApplication.screens()))
        self.assertTrue(all(w.isVisible() for w in self.border._windows))

    def test_border_is_painted_around_region(self):
        from PySide6.QtCore import QRect

        self.border.set_style("#ff0000", 5, True)
        self.border.set_region(CaptureRegion(0, 0, 200, 150), QRect(100, 100, 150, 100))
        self.app.processEvents()

        window = self.border._windows[0]
        canvas = QImage(window.width(), window.height(), QImage.Format.Format_ARGB32)
        canvas.fill(0)
        window.render(canvas)

        reds = _red_pixels(canvas)
        self.assertGreater(reds, 50)
        # 选区中心不应被描边覆盖
        center = canvas.pixelColor(175, 150)
        self.assertFalse(center.red() > 200 and center.green() < 60)

    def test_toggle_hides_but_keeps_region(self):
        from PySide6.QtCore import QRect

        self.border.set_style("#ff0000", 4, True)
        self.border.set_region(CaptureRegion(0, 0, 200, 150), QRect(100, 100, 150, 100))
        self.app.processEvents()
        self.assertTrue(self.border.visible)

        self.border.set_style("#ff0000", 4, False)
        self.app.processEvents()
        self.assertFalse(self.border.visible)
        self.assertTrue(all(not w.isVisible() for w in self.border._windows))
        self.assertIsNotNone(self.border.logical_rect)

        self.border.set_style("#00ff00", 8, True)
        self.app.processEvents()
        self.assertTrue(all(w.isVisible() for w in self.border._windows))
        self.assertEqual(self.border.border_width, 8)
        self.assertEqual(self.border.border_color.name(), "#00ff00")

    def test_invalid_color_falls_back(self):
        self.border.set_style("not-a-color", 3, True)
        self.assertEqual(self.border.border_color.name(), "#38bdf8")

    def test_clear_removes_windows(self):
        from PySide6.QtCore import QRect

        self.border.set_region(CaptureRegion(0, 0, 100, 100), QRect(10, 10, 80, 80))
        self.app.processEvents()
        self.assertTrue(self.border._windows)
        self.border.clear()
        self.assertEqual(self.border._windows, [])
        self.assertIsNone(self.border.logical_rect)

    def test_none_region_clears(self):
        from PySide6.QtCore import QRect

        self.border.set_region(CaptureRegion(0, 0, 100, 100), QRect(10, 10, 80, 80))
        self.app.processEvents()
        self.border.set_region(None)
        self.assertIsNone(self.border.logical_rect)


class BorderConfigTests(unittest.TestCase):
    def test_config_roundtrip_with_border_fields(self):
        import tempfile

        from app.config import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = AppConfig(border_visible=False, border_color="#ff8800", border_width=9)
            config.save(path)
            loaded = AppConfig.load(path)
            self.assertFalse(loaded.border_visible)
            self.assertEqual(loaded.border_color, "#ff8800")
            self.assertEqual(loaded.border_width, 9)

    def test_old_config_without_border_fields_gets_defaults(self):
        import json
        import tempfile

        from app.config import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"max_unchanged": 3}), encoding="utf-8")
            loaded = AppConfig.load(path)
            self.assertTrue(loaded.border_visible)
            self.assertEqual(loaded.border_color, "#38bdf8")
            self.assertEqual(loaded.border_width, 3)


if __name__ == "__main__":
    unittest.main()
