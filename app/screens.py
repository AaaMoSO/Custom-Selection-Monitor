"""Windows DPI 感知与「逻辑坐标 → 物理像素」映射。

Qt 交给我们的坐标是逻辑坐标（受 125% / 150% 缩放影响），而 mss 截屏使用的是
物理像素。本模块用 Win32 ``EnumDisplayMonitors`` 拿到每块显示器的物理矩形，
再与 Qt 的 ``QScreen`` 配对（先按设备名，再按主屏标志，最后按几何位置兜底），
从而得到准确的截取区域。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

from .capture import CaptureRegion

_MONITORINFOF_PRIMARY = 0x0001
_CCHDEVICENAME = 32


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * _CCHDEVICENAME),
    ]


@dataclass(frozen=True)
class PhysicalMonitor:
    device: str
    left: int
    top: int
    width: int
    height: int
    primary: bool = False


def enable_dpi_awareness() -> str:
    """在创建任何窗口之前调用，让进程拿到真实物理像素。"""
    if sys.platform != "win32":
        return "unsupported"

    user32 = ctypes.windll.user32
    try:  # Windows 10 1703+：Per-Monitor-V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:
        pass
    try:  # Windows 8.1+
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    try:  # 老系统
        if user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "none"


def enumerate_monitors() -> list[PhysicalMonitor]:
    """返回物理像素坐标下的显示器列表。"""
    if sys.platform != "win32":
        return []

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    result: list[PhysicalMonitor] = []

    proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(_RECT),
        wintypes.LPARAM,
    )

    def _callback(hmonitor, hdc, lprect, lparam):  # noqa: ANN001
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rect = info.rcMonitor
            result.append(
                PhysicalMonitor(
                    device=str(info.szDevice),
                    left=rect.left,
                    top=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                    primary=bool(info.dwFlags & _MONITORINFOF_PRIMARY),
                )
            )
        return True

    callback = proc_type(_callback)
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return result


def virtual_desktop() -> tuple[int, int, int, int]:
    """物理像素下的虚拟桌面 (left, top, width, height)。"""
    if sys.platform != "win32":
        return (0, 0, 0, 0)
    user32 = ctypes.windll.user32
    left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)
    return (left, top, width, height)


def _device_key(name: str) -> str:
    return name.rsplit("\\", 1)[-1].strip().upper()


def _distance_to_rect(geo, x: int, y: int) -> int:
    dx = max(geo.left() - x, 0, x - (geo.left() + geo.width() - 1))
    dy = max(geo.top() - y, 0, y - (geo.top() + geo.height() - 1))
    return dx * dx + dy * dy


class CoordinateMapper:
    """把 Qt 逻辑坐标换算成截屏用的物理像素。

    ``screens`` 传入 ``QGuiApplication.screens()``，``primary_screen`` 传入
    ``QGuiApplication.primaryScreen()``；本模块不在导入期依赖 Qt。
    """

    def __init__(self, screens=None, primary_screen=None) -> None:
        self._screens = list(screens) if screens else []
        self._primary = primary_screen
        self._monitor_of: dict[int, PhysicalMonitor] = {}

        monitors = enumerate_monitors()
        used: set[int] = set()
        by_device = {_device_key(m.device): m for m in monitors}

        # 1) 按设备名配对（Windows 上多数情况）
        for screen in self._screens:
            monitor = by_device.get(_device_key(screen.name()))
            if monitor is not None and id(monitor) not in used:
                self._monitor_of[id(screen)] = monitor
                used.add(id(monitor))

        # 2) Qt 主屏有时返回的是显示器友好名（如 "N50 Pro 7"），用主屏标志兜底
        if self._primary is not None and id(self._primary) not in self._monitor_of:
            for monitor in monitors:
                if monitor.primary and id(monitor) not in used:
                    self._monitor_of[id(self._primary)] = monitor
                    used.add(id(monitor))
                    break

        # 3) 剩余屏幕：按“逻辑原点与物理原点一致”合成一个等价的物理矩形
        for screen in self._screens:
            if id(screen) in self._monitor_of:
                continue
            geo = screen.geometry()
            dpr = float(screen.devicePixelRatio() or 1.0)
            self._monitor_of[id(screen)] = PhysicalMonitor(
                device=screen.name(),
                left=geo.left(),
                top=geo.top(),
                width=int(round(geo.width() * dpr)),
                height=int(round(geo.height() * dpr)),
            )

    # ------------------------------------------------------------------ 查询
    def monitor_for_screen(self, screen) -> PhysicalMonitor | None:
        return self._monitor_of.get(id(screen))

    def screen_for_point(self, x: int, y: int):
        """命中测试；边界点用“最近屏幕”兜底，避免右下角越界取错屏。"""
        if not self._screens:
            return None
        best = None
        best_distance = None
        for screen in self._screens:
            geo = screen.geometry()
            if (
                geo.left() <= x < geo.left() + geo.width()
                and geo.top() <= y < geo.top() + geo.height()
            ):
                return screen
            distance = _distance_to_rect(geo, x, y)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = screen
        return best

    # ------------------------------------------------------------------ 映射
    def map_point(self, x: float, y: float) -> tuple[int, int]:
        screen = self.screen_for_point(int(x), int(y))
        if screen is None:
            return (int(round(x)), int(round(y)))

        geo = screen.geometry()
        dpr = float(screen.devicePixelRatio() or 1.0)
        monitor = self._monitor_of.get(id(screen))
        if monitor is not None:
            px = monitor.left + (x - geo.left()) * dpr
            py = monitor.top + (y - geo.top()) * dpr
        else:  # 理论上不会走到
            px = geo.left() + (x - geo.left()) * dpr
            py = geo.top() + (y - geo.top()) * dpr
        return (int(round(px)), int(round(py)))

    def map_size(self, left: float, top: float, width: float, height: float) -> tuple[int, int]:
        x1, y1 = self.map_point(left, top)
        x2, y2 = self.map_point(left + width, top + height)
        return (abs(x2 - x1), abs(y2 - y1))

    def to_capture_region(
        self, left: float, top: float, width: float, height: float
    ) -> CaptureRegion | None:
        """逻辑矩形 → 物理区域，并夹紧到虚拟桌面范围内。"""
        if width <= 0 or height <= 0:
            return None

        x1, y1 = self.map_point(left, top)
        x2, y2 = self.map_point(left + width, top + height)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))

        vl, vt, vw, vh = virtual_desktop()
        if vw > 0 and vh > 0:
            x1, y1 = max(x1, vl), max(y1, vt)
            x2, y2 = min(x2, vl + vw), min(y2, vt + vh)

        if x2 <= x1 or y2 <= y1:
            return None
        return CaptureRegion(left=x1, top=y1, width=x2 - x1, height=y2 - y1)
