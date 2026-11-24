"""监控调度器：把 1 帧/秒的截屏、缓存、判定、保存串起来。

缓存分两层：
* 内存环形缓存 ``FrameBuffer``（10 帧，用于比对与计数，避免频繁读盘）；
* 磁盘镜像 ``FrameCache``（写入程序目录 ``data/frames``，磁盘上同样只留 10 张）。
两者都是 1 秒 1 次，磁盘编码在后台线程完成，不阻塞采样。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from . import paths
from .buffer import Frame, FrameBuffer
from .cache import FrameCache
from .capture import CaptureRegion, ScreenCapturer
from .config import AppConfig
from .saver import save_frame
from .state import ChangeDetector, Decision, DetectorConfig, MonitorState


class MonitorController(QObject):
    statsChanged = Signal(dict)
    stateChanged = Signal(object)  # MonitorState
    triggered = Signal(dict)
    logged = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        *,
        capacity: int = 10,
        interval_ms: int = 1000,
        capturer: ScreenCapturer | None = None,
        cache: FrameCache | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._interval_ms = int(interval_ms)
        self._capacity = int(capacity)
        self._buffer = FrameBuffer(self._capacity)
        self._capturer = capturer if capturer is not None else ScreenCapturer()
        self._cache = (
            cache
            if cache is not None
            else FrameCache(paths.cache_dir(), capacity=self._capacity)
        )
        self._detector = ChangeDetector(self._detector_config())
        self._region: CaptureRegion | None = None
        self._frames_captured = 0

        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ 属性
    @property
    def region(self) -> CaptureRegion | None:
        return self._region

    @property
    def state(self) -> MonitorState:
        return self._detector.state

    @property
    def buffer(self) -> FrameBuffer:
        return self._buffer

    @property
    def cache(self) -> FrameCache:
        return self._cache

    @property
    def interval_ms(self) -> int:
        return self._interval_ms

    @property
    def capacity(self) -> int:
        return self._capacity

    # ------------------------------------------------------------------ 设置
    def set_region(self, region: CaptureRegion) -> None:
        if self._detector.state is not MonitorState.IDLE:
            raise RuntimeError("监控进行中不能修改区域")
        self._region = region
        self._buffer.clear()
        self._frames_captured = 0
        self.statsChanged.emit(self.stats())

    def apply_settings(
        self,
        *,
        threshold_percent: float,
        tolerance: int,
        max_unchanged: int,
        save_folder: str,
    ) -> None:
        self._config.threshold_percent = float(threshold_percent)
        self._config.tolerance = int(tolerance)
        self._config.max_unchanged = int(max_unchanged)
        self._config.save_folder = str(save_folder)
        self._detector.update_config(self._detector_config())
        self.statsChanged.emit(self.stats())

    def _detector_config(self) -> DetectorConfig:
        return DetectorConfig(
            threshold_percent=self._config.threshold_percent,
            tolerance=self._config.tolerance,
            max_unchanged=self._config.max_unchanged,
        ).validated()

    # ------------------------------------------------------------------ 流程
    def start(self) -> bool:
        if self._region is None:
            self.failed.emit("请先框选监控区域")
            return False
        if self._detector.state is not MonitorState.IDLE:
            return False

        self._buffer.clear()
        self._frames_captured = 0
        self._cache.reset()
        self._detector.start()
        self._timer.start()
        self.logged.emit(
            f"开始监控 {self._region.describe()}，"
            f"阈值 {self._config.threshold_percent:g}%，上限 {self._config.max_unchanged} 次；"
            f"缓存目录 {self._cache.directory}"
        )
        self.stateChanged.emit(self._detector.state)
        self.statsChanged.emit(self.stats())
        return True

    def pause(self) -> None:
        if self._detector.state is not MonitorState.MONITORING:
            return
        self._timer.stop()
        self._detector.pause()
        self.logged.emit("已手动暂停监控（缓存保留）")
        self.stateChanged.emit(self._detector.state)
        self.statsChanged.emit(self.stats())

    def resume(self) -> None:
        if self._detector.state is not MonitorState.PAUSED:
            return
        self._detector.resume()
        self._timer.start()
        self.logged.emit("继续监控：首帧作为新基准，缓存保留")
        self.stateChanged.emit(self._detector.state)
        self.statsChanged.emit(self.stats())

    def stop(self) -> None:
        self._timer.stop()
        self._detector.stop()
        self._buffer.clear()
        self._cache.reset()
        self._frames_captured = 0
        self.logged.emit("已停止监控并清空缓存")
        self.stateChanged.emit(self._detector.state)
        self.statsChanged.emit(self.stats())

    def shutdown(self) -> None:
        self._timer.stop()
        self._capturer.close()
        self._cache.close()

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict:
        return {
            "state": self._detector.state,
            "region": self._region,
            "frames": self._frames_captured,
            "buffer_size": len(self._buffer),
            "capacity": self._capacity,
            "unchanged": self._detector.unchanged_count,
            "max_unchanged": self._config.max_unchanged,
            "last_ratio": self._detector.last_ratio,
            "threshold": self._config.threshold_percent,
            "tolerance": self._config.tolerance,
            "interval_ms": self._interval_ms,
            "cache_dir": str(self._cache.directory),
            "cache_size": self._cache.count,
        }

    # ------------------------------------------------------------------ 心跳
    def _tick(self) -> None:
        region = self._region
        if region is None:
            self._timer.stop()
            return

        captured_at = datetime.now()
        try:
            image = self._capturer.grab(region)
        except Exception as exc:  # 捕获失败（分辨率切换、锁屏等）不应让程序崩溃
            self._timer.stop()
            self._detector.stop()
            self.failed.emit(f"截屏失败：{exc}")
            self.stateChanged.emit(self._detector.state)
            self.statsChanged.emit(self.stats())
            return

        decision = self._detector.feed(image)
        ratio = self._detector.last_ratio
        frame = Frame(image=image, captured_at=captured_at, ratio=ratio)
        self._buffer.push(frame)
        self._frames_captured += 1
        self._cache.store(image, captured_at)

        cache_error = self._cache.consume_error()
        if cache_error is not None:
            self.logged.emit(f"缓存写入失败：{cache_error}")

        if decision is Decision.TRIGGERED:
            self._timer.stop()
            self._handle_trigger(frame, captured_at)

        self.statsChanged.emit(self.stats())

    def _handle_trigger(self, frame: Frame, captured_at: datetime) -> None:
        self.stateChanged.emit(self._detector.state)
        folder = self._config.resolved_save_folder()
        path = None
        try:
            path = save_frame(frame.image, folder, captured_at)
            self.logged.emit(
                f"连续 {self._detector.unchanged_count} 次未变化（上限 "
                f"{self._config.max_unchanged}），尾图已输出：{path}"
            )
        except Exception as exc:
            self.failed.emit(f"保存尾图失败：{exc}")

        self.triggered.emit(
            {
                "path": path,
                "ratio": self._detector.last_ratio,
                "unchanged": self._detector.unchanged_count,
                "captured_at": captured_at,
                "image": frame.image,
                "region": self._region,
            }
        )
