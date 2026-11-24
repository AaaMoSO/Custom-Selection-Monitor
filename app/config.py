"""配置读写：阈值、连续未变化上限、容差、保存目录。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "PauseRecognition"
APP_VERSION = "0.1.0"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME


def default_save_folder() -> Path:
    pictures = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures"
    return pictures / "PauseRecognition"


@dataclass
class AppConfig:
    threshold_percent: float = 1.0
    tolerance: int = 8
    max_unchanged: int = 5
    save_folder: str = ""

    def resolved_save_folder(self) -> Path:
        return Path(self.save_folder) if self.save_folder else default_save_folder()

    # ------------------------------------------------------------------ 持久化
    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        file = path or (config_dir() / "config.json")
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            return cls(
                threshold_percent=float(raw.get("threshold_percent", 1.0)),
                tolerance=int(raw.get("tolerance", 8)),
                max_unchanged=int(raw.get("max_unchanged", 5)),
                save_folder=str(raw.get("save_folder", "")),
            )
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> Path:
        file = path or (config_dir() / "config.json")
        file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(file)
        return file
