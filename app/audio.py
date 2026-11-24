"""系统音频输出电平采集（WASAPI loopback）。

只做两件事：枚举可回环录制的输出设备；在后台线程持续采集，按调用间隔
返回该区间内的 RMS 电平（dBFS）。音频线程与 UI/采样线程解耦，采集阻塞
不会拖慢 1 fps 的截屏。

说明：Windows 的 loopback 录制的是“正在播放的混音”，因此静音时电平会
掉到极低值（约 -180 dBFS），不代表设备失效。
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

_RMS_FLOOR = 1e-9
_SILENCE_DB = -90.0


@dataclass(frozen=True)
class AudioDevice:
    """一个可回环录制的音频输出设备。"""

    id: str
    name: str


def soundcard_available() -> bool:
    try:
        import soundcard  # noqa: F401
    except Exception:
        return False
    return True


def list_output_devices() -> list[AudioDevice]:
    """列出所有支持 loopback 的输出设备（扬声器/HDMI）。"""
    try:
        import soundcard as sc
    except Exception:
        return []

    try:
        microphones = sc.all_microphones(include_loopback=True)
    except Exception:
        return []

    devices: list[AudioDevice] = []
    for mic in microphones:
        try:
            if not getattr(mic, "isloopback", False):
                continue
            devices.append(AudioDevice(id=str(mic.id), name=str(mic.name)))
        except Exception:
            continue
    return devices


def default_output_device() -> AudioDevice | None:
    """系统默认输出设备（找不到时返回 None）。"""
    try:
        import soundcard as sc

        speaker = sc.default_speaker()
        return AudioDevice(id=str(speaker.id), name=str(speaker.name))
    except Exception:
        return None


def to_db(rms: float) -> float:
    """RMS → dBFS，0 值落到 -180 dB。"""
    return 20.0 * math.log10(max(float(rms), _RMS_FLOOR))


def is_silent(level_db: float | None) -> bool:
    return level_db is None or level_db <= _SILENCE_DB


class AudioMeter:
    """后台采集指定输出设备的电平，按区间取 RMS。"""

    def __init__(self, samplerate: int = 48000, block_seconds: float = 0.1) -> None:
        self._samplerate = int(samplerate)
        self._block_frames = max(256, int(self._samplerate * block_seconds))
        self._lock = threading.Lock()
        self._blocks: deque[tuple[float, float]] = deque(maxlen=240)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._device: AudioDevice | None = None
        self._error: str | None = None

    # ------------------------------------------------------------------ 属性
    @property
    def device(self) -> AudioDevice | None:
        return self._device

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    # ------------------------------------------------------------------ 生命周期
    def start(self, device: AudioDevice) -> None:
        self.stop()
        self._device = device
        self._error = None
        self._ready.clear()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(device,), name="audio-meter", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        with self._lock:
            self._blocks.clear()
        self._ready.clear()

    # ------------------------------------------------------------------ 采样
    def level_since_last(self) -> float | None:
        """返回上次调用以来（最多回溯 2 秒）的 RMS 电平；无数据返回 None。"""
        now = time.monotonic()
        with self._lock:
            blocks = list(self._blocks)
            self._blocks.clear()

        recent = [rms for stamp, rms in blocks if now - stamp <= 2.0]
        if not recent:
            return None
        combined = math.sqrt(sum(value * value for value in recent) / len(recent))
        return to_db(combined)

    def _run(self, device: AudioDevice) -> None:
        try:
            import numpy as np
            import soundcard as sc

            microphone = sc.get_microphone(device.id, include_loopback=True)
            with microphone.recorder(
                samplerate=self._samplerate,
                channels=2,
                blocksize=self._block_frames,
            ) as recorder:
                while not self._stop.is_set():
                    data = recorder.record(numframes=self._block_frames)
                    rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))
                    self._push_block(rms)
        except Exception as exc:  # 设备被占用/拔出/格式不支持
            with self._lock:
                self._error = str(exc)
            self._ready.set()

    def _push_block(self, rms: float) -> None:
        """记录一个分块电平（也供测试直接注入）。"""
        with self._lock:
            self._blocks.append((time.monotonic(), rms))
        self._ready.set()
