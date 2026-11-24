"""常驻区域边框：始终置顶、鼠标穿透，标出正在监控的矩形。

关键点：
* 边框窗口用 ``SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`` 把自己排除在
  屏幕截图之外，所以即使描边压在选区边界上，也不会被 mss 截进监控画面、
  不会污染像素比对（Windows 10 2004+ 支持）。
* 系统不支持该 API 时自动退让：把描边整体画到选区**外侧**，同样不遮挡监控内容。
* 鼠标穿透 + 不抢占焦点，不会影响用户操作其他窗口。
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .capture import CaptureRegion
from .screens import CoordinateMapper

_WDA_EXCLUDEFROMCAPTURE = 0x00000011


def exclude_from_capture(widget: QWidget) -> bool:
    """让窗口不出现在屏幕截图里；返回是否成功。"""
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        ok = user32.SetWindowDisplayAffinity(
            ctypes.c_void_p(hwnd), ctypes.c_uint(_WDA_EXCLUDEFROMCAPTURE)
        )
        return bool(ok)
    except Exception:
        return False


class _BorderWindow(QWidget):
    """每块显示器一个全屏透明窗，只绘制边框与屏幕相交的部分。"""

    def __init__(self, owner: "RegionBorder", screen) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self._owner = owner
        self._screen = screen
        self._excluded = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(screen.geometry())

    @property
    def screen_ref(self):
        return self._screen

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        if not self._excluded:
            self._excluded = exclude_from_capture(self)
            if not self._excluded:
                self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        rect = self._owner.logical_rect
        width = self._owner.border_width
        if rect is None or rect.isEmpty() or width <= 0:
            return

        local = rect.translated(-self.geometry().topLeft())
        if not local.intersects(self.rect()):
            return

        if not self._excluded:
            # 无法排除截图时把描边推到选区外侧，避免盖住被监控的像素
            local = local.adjusted(-width, -width, width, width)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(self._owner.border_color, width)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.drawRect(local)


class RegionBorder(QObject):
    """管理区域边框的显示、颜色、粗细与开关。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._windows: list[_BorderWindow] = []
        self._screen_signature: tuple = ()
        self._logical: QRect | None = None
        self._color = QColor("#38bdf8")
        self._width = 3
        self._visible = True

    # ------------------------------------------------------------------ 属性
    @property
    def logical_rect(self) -> QRect | None:
        return self._logical

    @property
    def border_color(self) -> QColor:
        return self._color

    @property
    def border_width(self) -> int:
        return self._width

    @property
    def visible(self) -> bool:
        return self._visible

    # ------------------------------------------------------------------ 设置
    def set_style(self, color: str | QColor, width: int, visible: bool) -> None:
        self._color = QColor(color) if not isinstance(color, QColor) else QColor(color)
        if not self._color.isValid():
            self._color = QColor("#38bdf8")
        self._width = max(1, int(width))
        self._visible = bool(visible)
        self._refresh()

    def set_region(
        self,
        region: CaptureRegion | None,
        logical_rect: QRect | None = None,
    ) -> None:
        if region is None or not region.is_valid():
            self.clear()
            return
        if logical_rect is not None and not logical_rect.isEmpty():
            rect = QRect(logical_rect)
        else:
            rect = self._derive_logical(region)
        if rect.isEmpty():
            self.clear()
            return
        self._logical = rect
        self._refresh()

    def clear(self) -> None:
        self._logical = None
        for window in self._windows:
            window.hide()
        self._destroy_windows()

    def refresh(self) -> None:
        """显示器增删/分辨率变化后重新铺满屏幕。"""
        self._screen_signature = ()
        self._refresh()

    # ------------------------------------------------------------------ 内部
    def _derive_logical(self, region: CaptureRegion) -> QRect:
        mapper = CoordinateMapper(
            QGuiApplication.screens(), QGuiApplication.primaryScreen()
        )
        left, top, width, height = mapper.to_logical_rect(region)
        return QRect(left, top, width, height)

    def _refresh(self) -> None:
        if not self._visible or self._logical is None:
            for window in self._windows:
                window.hide()
            return

        self._ensure_windows()
        for window in self._windows:
            window.setGeometry(window.screen_ref.geometry())
            window.show()
            window.raise_()
            window.update()

    def _ensure_windows(self) -> None:
        screens = QGuiApplication.screens()
        signature = tuple(
            (s.name(), s.geometry().getRect(), float(s.devicePixelRatio() or 1.0))
            for s in screens
        )
        if signature == self._screen_signature and len(self._windows) == len(screens):
            return

        self._destroy_windows()
        self._screen_signature = signature
        for screen in screens:
            window = _BorderWindow(self, screen)
            window.setGeometry(screen.geometry())
            self._windows.append(window)

    def _destroy_windows(self) -> None:
        for window in self._windows:
            window.hide()
            window.deleteLater()
        self._windows.clear()
        self._screen_signature = ()

    def close(self) -> None:
        self._logical = None
        self._destroy_windows()
