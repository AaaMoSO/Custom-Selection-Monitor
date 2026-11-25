import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

try:  # PySide6 属于运行时依赖，缺失时跳过 GUI 冒烟
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

import numpy as np


@unittest.skipUnless(HAS_QT, "PySide6 不可用")
class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.ui.theme import APP_QSS

        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(APP_QSS)

    def test_build_render_and_trigger_preview(self):
        from PySide6.QtWidgets import QScrollArea

        from app.capture import CaptureRegion
        from app.config import AppConfig
        from app.controller import MonitorController
        from app.state import MonitorState
        from app.ui.main_window import MainWindow

        config = AppConfig(save_folder=str(Path(os.environ.get("TEMP", ".")) / "pr-smoke"))
        controller = MonitorController(config)
        window = MainWindow(controller, config)
        window.resize(720, 776)
        window.show()
        self.app.processEvents()

        image = window.grab()
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), 0)

        scroll = window.findChild(QScrollArea)
        self.assertIsNotNone(scroll)
        # 内容高度应能放进默认窗口（不依赖滚动条）
        self.assertLessEqual(scroll.widget().sizeHint().height(), 790)

        # 取消框选后按钮必须恢复可用，不能卡死
        window._region_btn.setEnabled(False)
        window._on_region_cancelled()
        self.assertTrue(window._region_btn.isEnabled())

        region = CaptureRegion(0, 0, 1920, 1080)
        controller.set_region(region)
        window._on_stats(
            {
                "state": MonitorState.MONITORING,
                "region": region,
                "frames": 17,
                "buffer_size": 10,
                "capacity": 10,
                "unchanged": 3,
                "max_unchanged": 5,
                "last_ratio": 0.041,
                "threshold": 1.0,
                "tolerance": 8,
                "interval_ms": 1000,
            }
        )
        self.assertEqual(window._frames_value.text(), "17")
        self.assertEqual(window._buffer_value.text(), "10 / 10")
        self.assertEqual(window._n_value.text(), "3 / 5")

        window._apply_chip(MonitorState.PAUSED)
        self.app.processEvents()
        self.assertEqual(window._chip.property("state"), "paused")

        # 边框开关要即时生效，但不该真的写配置文件
        from unittest import mock

        with mock.patch.object(MainWindow, "_persist"):
            window._border_toggle.setChecked(False)
            self.assertFalse(window._border.visible)
            window._border_toggle.setChecked(True)
            self.assertTrue(window._border.visible)
            window._border_width.setValue(7)
            self.assertEqual(window._border.border_width, 7)

        preview = np.zeros((120, 200, 3), dtype=np.uint8)
        preview[:, :, 0] = 200
        window._on_triggered(
            {
                "image": preview,
                "path": Path("C:/shots/pause_20260101-000000.png"),
                "ratio": 0.0,
                "unchanged": 6,
            }
        )
        self.app.processEvents()
        self.assertIsNotNone(window._preview.pixmap())
        self.assertIn("pause_", window._last_saved.toolTip())

        window.close()
        controller.shutdown()

    def test_region_selector_emits_physical_region(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QImage

        from app.selection import RegionSelector

        selector = RegionSelector()
        captured = []
        selector.selected.connect(captured.append)
        selector.begin()
        selector.press(QPoint(100, 100))
        selector.move_to(QPoint(300, 220))

        # 强制走一遍绘制逻辑（遮罩底色 + 选区镂空 + 边框 + 尺寸标签）
        for overlay in selector._overlays:  # noqa: SLF001 - 测试内部绘制
            canvas = QImage(overlay.width(), overlay.height(), QImage.Format.Format_ARGB32)
            overlay.render(canvas)
            self.assertFalse(canvas.isNull())

        selector.release(QPoint(300, 220))

        self.assertEqual(len(captured), 1)
        region = captured[0]
        self.assertGreater(region.width, 0)
        self.assertGreater(region.height, 0)
        self.assertFalse(selector.active)

    def test_region_selector_cancel(self):
        from PySide6.QtCore import QPoint

        from app.selection import RegionSelector

        selector = RegionSelector()
        events = []
        selector.cancelled.connect(lambda: events.append(True))
        selector.begin()
        selector.press(QPoint(50, 50))
        selector.release(QPoint(52, 52))  # 小于最小尺寸 → 视为取消
        self.assertTrue(events)
        self.assertFalse(selector.active)

    def test_clear_region_resets_ui_and_border(self):
        from PySide6.QtCore import QRect

        from app.capture import CaptureRegion
        from app.config import AppConfig
        from app.controller import MonitorController
        from app.ui.main_window import MainWindow

        config = AppConfig(save_folder=str(Path(os.environ.get("TEMP", ".")) / "pr-smoke-2"))
        controller = MonitorController(config)
        window = MainWindow(controller, config)
        window.show()
        self.app.processEvents()

        region = CaptureRegion(0, 0, 400, 300)
        controller.set_region(region)
        window._border.set_region(region, QRect(50, 50, 200, 150))
        window._sync_buttons(controller.state, region)
        self.assertTrue(window._clear_region_btn.isEnabled())
        self.assertIsNotNone(window._border.logical_rect)

        window._clear_region()
        self.app.processEvents()

        self.assertIsNone(controller.region)
        self.assertIsNone(window._border.logical_rect)
        self.assertFalse(window._clear_region_btn.isEnabled())
        self.assertEqual(window._region_label.text(), "尚未选择区域")
        self.assertFalse(window._action_btn.isEnabled())

        window.close()
        controller.shutdown()

    def test_agent_dialogs_construct(self):
        import datetime

        from app.agent import Incident, new_incident_id
        from app.capture import CaptureRegion
        from app.config import AppConfig
        from app.ui.agent_ui import AgentSettingsDialog, HandoffDialog

        config = AppConfig(agent_enabled=True, agent_base_url="http://127.0.0.1:1/conversation-api")
        settings = AgentSettingsDialog(config)
        self.assertIn("Agent", settings.windowTitle())
        settings.close()

        incident = Incident(
            incident_id=new_incident_id(),
            sequence=1,
            captured_at=datetime.datetime.now(),
            region=CaptureRegion(0, 0, 100, 80),
            unchanged=6,
            max_unchanged=5,
            ratio=0.0,
            audio_text="音频未启用",
            tail_image=np.zeros((80, 100, 3), dtype=np.uint8),
        )
        handoff = HandoffDialog(incident)
        self.assertEqual(handoff.windowTitle(), "发现异常")
        handoff.close()


if __name__ == "__main__":
    unittest.main()
