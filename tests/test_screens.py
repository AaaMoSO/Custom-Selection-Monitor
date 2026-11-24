import unittest
from unittest import mock

import app.screens as screens_module
from app.capture import CaptureRegion
from app.screens import CoordinateMapper, PhysicalMonitor, virtual_desktop


class FakeRect:
    def __init__(self, left: int, top: int, width: int, height: int) -> None:
        self._left = left
        self._top = top
        self._width = width
        self._height = height

    def left(self) -> int:
        return self._left

    def top(self) -> int:
        return self._top

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def center(self):
        return (self._left + self._width // 2, self._top + self._height // 2)

    def getRect(self):
        return (self._left, self._top, self._width, self._height)


class FakeScreen:
    def __init__(self, name: str, left: int, top: int, width: int, height: int, dpr: float) -> None:
        self._name = name
        self._rect = FakeRect(left, top, width, height)
        self._dpr = dpr

    def name(self) -> str:
        return self._name

    def geometry(self) -> FakeRect:
        return self._rect

    def devicePixelRatio(self) -> float:
        return self._dpr


PRIMARY = FakeScreen("N50 Pro 7", 0, 0, 1536, 864, 1.25)
SECONDARY = FakeScreen("\\\\.\\DISPLAY1", 1920, 0, 1536, 864, 1.25)

MONITORS = [
    PhysicalMonitor("\\\\.\\DISPLAY1", 1920, 0, 1920, 1080, primary=False),
    PhysicalMonitor("\\\\.\\DISPLAY2", 0, 0, 1920, 1080, primary=True),
]


class MapperTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            mock.patch.object(screens_module, "enumerate_monitors", return_value=MONITORS),
            mock.patch.object(screens_module, "virtual_desktop", return_value=(0, 0, 3840, 1080)),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.mapper = CoordinateMapper([PRIMARY, SECONDARY], PRIMARY)

    def test_primary_matched_by_flag_not_name(self):
        monitor = self.mapper.monitor_for_screen(PRIMARY)
        self.assertIsNotNone(monitor)
        self.assertEqual(monitor.device, "\\\\.\\DISPLAY2")

    def test_secondary_matched_by_device_name(self):
        monitor = self.mapper.monitor_for_screen(SECONDARY)
        self.assertEqual(monitor.device, "\\\\.\\DISPLAY1")

    def test_primary_corners(self):
        self.assertEqual(self.mapper.map_point(0, 0), (0, 0))
        self.assertEqual(self.mapper.map_point(1536, 864), (1920, 1080))

    def test_secondary_corners(self):
        self.assertEqual(self.mapper.map_point(1920, 0), (1920, 0))
        self.assertEqual(self.mapper.map_point(3456, 864), (3840, 1080))

    def test_region_matches_physical_monitor(self):
        region = self.mapper.to_capture_region(0, 0, 1536, 864)
        self.assertEqual(region, CaptureRegion(0, 0, 1920, 1080))
        region = self.mapper.to_capture_region(1920, 0, 1536, 864)
        self.assertEqual(region, CaptureRegion(1920, 0, 1920, 1080))

    def test_partial_region_scales(self):
        region = self.mapper.to_capture_region(100, 100, 200, 100)
        self.assertEqual(region, CaptureRegion(125, 125, 250, 125))

    def test_clamped_to_virtual_desktop(self):
        region = self.mapper.to_capture_region(1920, 0, 5000, 5000)
        self.assertEqual(region, CaptureRegion(1920, 0, 1920, 1080))

    def test_degenerate_region_is_none(self):
        self.assertIsNone(self.mapper.to_capture_region(10, 10, 0, 50))


if __name__ == "__main__":
    unittest.main()
