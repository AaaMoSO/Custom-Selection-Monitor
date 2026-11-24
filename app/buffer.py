"""截图环形缓存：最多保留 ``capacity`` 张，超出后自动淘汰最早的一张。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class Frame:
    """一帧截图。``image`` 为 H×W×3 的 uint8 RGB 数组。"""

    image: np.ndarray
    captured_at: datetime
    ratio: float | None = None


class FrameBuffer:
    """固定容量的环形缓存，行为等价于“最多保留 10 张，多了清最早的”。"""

    def __init__(self, capacity: int = 10) -> None:
        if capacity < 1:
            raise ValueError("capacity 必须 >= 1")
        self._capacity = int(capacity)
        self._frames: deque[Frame] = deque(maxlen=self._capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._frames)

    def __iter__(self):
        return iter(self._frames)

    @property
    def frames(self) -> tuple[Frame, ...]:
        return tuple(self._frames)

    @property
    def latest(self) -> Frame | None:
        return self._frames[-1] if self._frames else None

    @property
    def previous(self) -> Frame | None:
        return self._frames[-2] if len(self._frames) >= 2 else None

    def push(self, frame: Frame) -> Frame | None:
        """压入一帧；缓存已满时返回被淘汰的最早帧，否则返回 None。"""
        evicted: Frame | None = None
        if len(self._frames) == self._capacity:
            evicted = self._frames[0]
        self._frames.append(frame)
        return evicted

    def clear(self) -> None:
        self._frames.clear()

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"FrameBuffer(capacity={self._capacity}, size={len(self._frames)})"
