"""全屏框选遮罩：支持多显示器，输出物理像素区域。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .capture import CaptureRegion
from .screens import CoordinateMapper

_DIM = QColor(8, 10, 14, 150)
_ACCENT = QColor(56, 189, 248)
_TEXT = QColor(230, 237, 243)
_HUD_BG = QColor(11, 15, 20, 210)

_MIN_SIZE = 8


class _Overlay(QWidget):
    """每块显示器一个全屏遮罩窗口。"""

    def __init__(self, selector: "RegionSelector", screen) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._selector = selector
        self._screen = screen
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(screen.geometry())

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), _DIM)

        band = self._selector.global_band()
        if band is None or band.width() < 1 or band.height() < 1:
            self._paint_hint(painter)
            return

        geo = self.geometry()
        local = band.translated(-geo.topLeft()).intersected(self.rect())
        if local.isEmpty():
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(local, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        self._paint_edges(painter, band, geo)
        self._paint_size(painter, band, geo)
        painter.end()

    def _paint_edges(self, painter: QPainter, band: QRect, geo: QRect) -> None:
        painter.setPen(QPen(_ACCENT, 1.6))
        width, height = self.width(), self.height()
        left = band.left() - geo.left()
        right = band.right() - geo.left()
        top = band.top() - geo.top()
        bottom = band.bottom() - geo.top()
        x1, x2 = max(0, left), min(width, right)
        y1, y2 = max(0, top), min(height, bottom)

        if 0 <= top <= height and x2 > x1:
            painter.drawLine(x1, top, x2, top)
        if 0 <= bottom <= height and x2 > x1:
            painter.drawLine(x1, bottom, x2, bottom)
        if 0 <= left <= width and y2 > y1:
            painter.drawLine(left, y1, left, y2)
        if 0 <= right <= width and y2 > y1:
            painter.drawLine(right, y1, right, y2)

    def _paint_size(self, painter: QPainter, band: QRect, geo: QRect) -> None:
        corner = band.bottomRight()
        if not self.geometry().contains(corner):
            return

        size = self._selector.physical_size(band)
        painter.setFont(self.font())
        text = f"{size[0]} × {size[1]} px"
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text) + 16
        th = metrics.height() + 10

        x = min(max(8, corner.x() - geo.left() + 12), self.width() - tw - 8)
        y = corner.y() - geo.top() + 12
        if y + th > self.height() - 8:
            y = corner.y() - geo.top() - th - 12

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_HUD_BG)
        painter.drawRoundedRect(QRect(int(x), int(y), int(tw), int(th)), 6, 6)
        painter.setPen(_TEXT)
        painter.drawText(QRect(int(x), int(y), int(tw), int(th)), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_hint(self, painter: QPainter) -> None:
        if not self.geometry().contains(QCursor.pos()):
            return
        text = "拖拽框选监控区域   ·   右键 / Esc 取消"
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text) + 28
        th = metrics.height() + 16
        x = (self.width() - tw) // 2
        y = max(24, int(self.height() * 0.12))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_HUD_BG)
        painter.drawRoundedRect(QRect(x, y, tw, th), 8, 8)
        painter.setPen(_TEXT)
        painter.drawText(QRect(x, y, tw, th), Qt.AlignmentFlag.AlignCenter, text)

    # ------------------------------------------------------------------ 交互
    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.RightButton:
            self._selector.cancel()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._selector.press(QCursor.pos())

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001, N802
        self._selector.move_to(QCursor.pos())

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._selector.release(QCursor.pos())

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() == Qt.Key.Key_Escape:
            self._selector.cancel()
        else:
            super().keyPressEvent(event)


class RegionSelector(QObject):
    """框选流程控制：begin → 用户拖拽 → selected / cancelled。"""

    selected = Signal(object)  # CaptureRegion
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._overlays: list[_Overlay] = []
        self._mapper: CoordinateMapper | None = None
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._last_band: QRect | None = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def last_band(self) -> QRect | None:
        """最近一次成功框选的逻辑矩形（用于把边框画回屏幕）。"""
        return self._last_band

    def begin(self) -> None:
        if self._active:
            return
        self._active = True
        self._start = None
        self._current = None
        self._mapper = CoordinateMapper(
            QGuiApplication.screens(), QGuiApplication.primaryScreen()
        )

        for screen in QGuiApplication.screens():
            overlay = _Overlay(self, screen)
            overlay.show()
            overlay.raise_()
            self._overlays.append(overlay)

        app = QGuiApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        if self._overlays:
            self._overlays[0].activateWindow()
            self._overlays[0].setFocus(Qt.FocusReason.MouseFocusReason)

    # ------------------------------------------------------------------ 状态
    def global_band(self) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()

    def physical_size(self, band: QRect) -> tuple[int, int]:
        if self._mapper is None:
            return (band.width(), band.height())
        return self._mapper.map_size(band.x(), band.y(), band.width(), band.height())

    # ------------------------------------------------------------------ 事件
    def press(self, point: QPoint) -> None:
        self._start = point
        self._current = point
        self._refresh()

    def move_to(self, point: QPoint) -> None:
        if self._start is None:
            return
        self._current = point
        self._refresh()

    def release(self, point: QPoint) -> None:
        if self._start is None:
            self.cancel()
            return
        self._current = point
        band = self.global_band()
        region: CaptureRegion | None = None
        if band is not None and band.width() >= _MIN_SIZE and band.height() >= _MIN_SIZE and self._mapper:
            region = self._mapper.to_capture_region(
                band.x(), band.y(), band.width(), band.height()
            )
        self._teardown()
        if region is not None:
            self._last_band = QRect(band)
            self.selected.emit(region)
        else:
            self.cancelled.emit()

    def cancel(self) -> None:
        if not self._active:
            return
        self._teardown()
        self.cancelled.emit()

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001, N802
        if (
            self._active
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.cancel()
            return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ 内部
    def _refresh(self) -> None:
        for overlay in self._overlays:
            overlay.update()

    def _teardown(self) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        for overlay in self._overlays:
            overlay.hide()
            overlay.deleteLater()
        self._overlays.clear()
        self._start = None
        self._current = None
        self._active = False
