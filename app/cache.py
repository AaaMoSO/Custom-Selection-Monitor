"""磁盘帧缓存：把最近 N 帧镜像到程序目录，磁盘上永远只保留 N 张。

写盘在后台线程完成（PNG 编码 1080p 约 80–100 ms），不阻塞 1 fps 的采样与比对；
容量淘汰、目录清理也都由工作线程按队列顺序执行。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import Queue

import numpy as np
from PIL import Image

FILE_PREFIX = "frame_"


class FrameCache:
    """最近 ``capacity`` 帧的磁盘镜像，目录里最多出现 ``capacity`` 个文件。"""

    def __init__(self, directory: str | Path, capacity: int = 10) -> None:
        self._directory = Path(directory)
        self._capacity = max(1, int(capacity))
        self._queue: Queue = Queue()
        self._lock = threading.Lock()
        self._files: deque[Path] = deque()
        self._sequence = 0
        self._error: Exception | None = None
        self._worker: threading.Thread | None = None
        self._start_worker()

    # ------------------------------------------------------------------ 属性
    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._files)

    @property
    def latest(self) -> Path | None:
        with self._lock:
            return self._files[-1] if self._files else None

    @property
    def error(self) -> Exception | None:
        with self._lock:
            return self._error

    def consume_error(self) -> Exception | None:
        """取出并清空错误（供调用方一次性上报）。"""
        with self._lock:
            error, self._error = self._error, None
            return error

    # ------------------------------------------------------------------ 写入
    def store(self, image: np.ndarray, captured_at: datetime | None = None) -> None:
        """排队写入一帧；实际编码与淘汰在后台线程完成。"""
        self._queue.put((image, captured_at or datetime.now()))

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """等待队列中的写入完成（测试与退出时使用）。"""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    # ------------------------------------------------------------------ 清理
    def clear(self) -> None:
        """停止工作线程并删除目录内所有缓存帧。"""
        self._stop_worker()
        with self._lock:
            self._files.clear()
            self._sequence = 0
            self._error = None
        self._remove_files()

    def reset(self) -> None:
        """清空缓存并重新启动工作线程（新一轮监控开始时调用）。"""
        self.clear()
        self._start_worker()

    def close(self) -> None:
        """停止工作线程，但保留磁盘上的最后一组缓存帧（便于退出后查看）。"""
        self._stop_worker()

    # ------------------------------------------------------------------ 内部
    def _start_worker(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._run, name="frame-cache", daemon=True
        )
        self._worker.start()

    def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._queue.put(None)
        worker.join(timeout=10)
        self._worker = None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            image, captured_at = item
            try:
                path = self._write(image, captured_at)
                with self._lock:
                    self._files.append(path)
                    while len(self._files) > self._capacity:
                        stale = self._files.popleft()
                        _unlink(stale)
            except Exception as exc:  # 缓存是辅助功能，失败不打断监控
                with self._lock:
                    self._error = exc
            finally:
                self._queue.task_done()

    def _write(self, image: np.ndarray, captured_at: datetime) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        name = f"{FILE_PREFIX}{sequence:06d}_{captured_at.strftime('%Y%m%d-%H%M%S')}.png"
        path = self._directory / name
        Image.fromarray(image).save(path, format="PNG", compress_level=1)
        return path

    def _remove_files(self) -> None:
        if not self._directory.is_dir():
            return
        for path in self._directory.glob(f"{FILE_PREFIX}*.png"):
            _unlink(path)


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
