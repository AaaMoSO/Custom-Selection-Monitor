"""配置读写：阈值、连续未变化上限、容差、尾图输出目录。

配置文件放在程序目录的 ``data/config.json``，不写 C 盘用户目录；
旧版本曾把它放在 ``%APPDATA%``，首次读取时做一次兼容迁移。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths

APP_NAME = "PauseRecognition"
APP_VERSION = "0.1.0"


def config_dir() -> Path:
    """兼容旧接口：返回配置文件所在目录。"""
    return paths.data_dir()


def default_save_folder() -> Path:
    """尾图默认输出目录（程序目录内的 captures/）。"""
    return paths.default_output_dir()


@dataclass
class AppConfig:
    threshold_percent: float = 1.0
    tolerance: int = 8
    max_unchanged: int = 5
    save_folder: str = ""
    border_visible: bool = True
    border_color: str = "#38bdf8"
    border_width: int = 3
    audio_enabled: bool = False
    audio_device_id: str = ""
    audio_device_name: str = ""
    audio_tolerance_db: float = 1.5
    agent_enabled: bool = False
    agent_base_url: str = ""
    agent_session_id: str = ""
    agent_timeout_ms: int = 300_000

    def resolved_save_folder(self) -> Path:
        return Path(self.save_folder) if self.save_folder else default_save_folder()

    # ------------------------------------------------------------------ 持久化
    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        file = path or paths.config_path()
        if path is None and not file.exists():
            legacy = paths.legacy_config_path()
            if legacy.exists():
                file = legacy
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            return cls(
                threshold_percent=float(raw.get("threshold_percent", 1.0)),
                tolerance=int(raw.get("tolerance", 8)),
                max_unchanged=int(raw.get("max_unchanged", 5)),
                save_folder=str(raw.get("save_folder", "")),
                border_visible=bool(raw.get("border_visible", True)),
                border_color=str(raw.get("border_color", "#38bdf8")),
                border_width=int(raw.get("border_width", 3)),
                audio_enabled=bool(raw.get("audio_enabled", False)),
                audio_device_id=str(raw.get("audio_device_id", "")),
                audio_device_name=str(raw.get("audio_device_name", "")),
                audio_tolerance_db=float(raw.get("audio_tolerance_db", 1.5)),
                agent_enabled=bool(raw.get("agent_enabled", False)),
                agent_base_url=str(raw.get("agent_base_url", "")),
                agent_session_id=str(raw.get("agent_session_id", "")),
                agent_timeout_ms=int(raw.get("agent_timeout_ms", 300_000)),
            )
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> Path:
        file = path or paths.config_path()
        file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(file)
        return file
