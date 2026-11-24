"""监控状态机：负责“未变化次数 n”的累加、归零与暂停触发。

规则（与产品定义一致）：

1. 第一帧只作为基准，不参与比较、不计数。
2. 之后每帧与上一帧比较，变化率 ``< threshold_percent`` 视为未变化 → ``n += 1``。
3. 任意一次比较的变化率 ``>= threshold_percent`` → ``n = 0``。
4. ``n > max_unchanged``（严格大于）→ 触发，状态转为 ``PAUSED``。
5. 恢复监控时清空基准与计数器，把恢复后的第一帧当作新基准（缓存不清空）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

import numpy as np

from .diff import DEFAULT_TOLERANCE, CompareResult, compare


class MonitorState(Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    PAUSED = "paused"


class Decision(Enum):
    IGNORED = "ignored"
    BASELINE = "baseline"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    TRIGGERED = "triggered"


@dataclass(frozen=True)
class DetectorConfig:
    threshold_percent: float = 1.0
    tolerance: int = DEFAULT_TOLERANCE
    max_unchanged: int = 5

    def validated(self) -> "DetectorConfig":
        """把参数夹到合法区间，避免非法配置让状态机卡死。"""
        return replace(
            self,
            threshold_percent=min(100.0, max(0.0, float(self.threshold_percent))),
            tolerance=max(0, int(self.tolerance)),
            max_unchanged=max(0, int(self.max_unchanged)),
        )


class ChangeDetector:
    """把“帧流”翻译成“未变化计数 / 触发”的纯逻辑状态机。"""

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = (config or DetectorConfig()).validated()
        self._state = MonitorState.IDLE
        self._baseline: np.ndarray | None = None
        self._unchanged = 0
        self._last_result: CompareResult | None = None

    # ------------------------------------------------------------------ 状态
    @property
    def state(self) -> MonitorState:
        return self._state

    @property
    def unchanged_count(self) -> int:
        return self._unchanged

    @property
    def last_result(self) -> CompareResult | None:
        return self._last_result

    @property
    def last_ratio(self) -> float | None:
        return self._last_result.ratio if self._last_result is not None else None

    def update_config(self, config: DetectorConfig) -> None:
        self.config = config.validated()

    def start(self) -> None:
        """开始一轮全新监控：清基准、清计数。"""
        self._state = MonitorState.MONITORING
        self._baseline = None
        self._unchanged = 0
        self._last_result = None

    def resume(self) -> None:
        """从暂停恢复。

        基准与计数器都要清空：暂停时 ``n`` 已经超过上限，若直接沿用，
        恢复后的第一次“未变化”会立刻再次触发。
        """
        self.start()

    def pause(self) -> None:
        if self._state is MonitorState.MONITORING:
            self._state = MonitorState.PAUSED

    def stop(self) -> None:
        self._state = MonitorState.IDLE
        self._baseline = None
        self._unchanged = 0

    # ------------------------------------------------------------------ 帧流
    def feed(self, image: np.ndarray) -> Decision:
        """喂入一帧，返回判定结果。"""
        if self._state is not MonitorState.MONITORING:
            return Decision.IGNORED

        if self._baseline is None:
            self._baseline = image
            self._last_result = None
            return Decision.BASELINE

        result = compare(self._baseline, image, self.config.tolerance)
        self._baseline = image
        self._last_result = result

        if result.ratio < self.config.threshold_percent:
            self._unchanged += 1
            if self._unchanged > self.config.max_unchanged:
                self._state = MonitorState.PAUSED
                return Decision.TRIGGERED
            return Decision.UNCHANGED

        self._unchanged = 0
        return Decision.CHANGED
