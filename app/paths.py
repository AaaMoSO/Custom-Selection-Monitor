"""程序内部路径：数据目录、缓存目录、默认输出目录、配置文件。

原则：所有“程序自己用”的东西都放在程序目录旁边，不往 C 盘用户目录写；
只有用户显式选择的触发输出路径才由用户决定。程序目录不可写时（例如装在
Program Files）自动退回 ``%APPDATA%``，保证仍能运行。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "PauseRecognition"

_DATA_DIR: Path | None = None


def program_dir() -> Path:
    """程序所在目录：源码运行时是项目根目录，打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):  # PyInstaller / py2exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """程序私有数据目录，优先 ``<程序目录>/data``，不可写时退回 APPDATA。"""
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR

    primary = program_dir() / "data"
    try:
        primary.mkdir(parents=True, exist_ok=True)
        probe = primary / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _DATA_DIR = primary
    except OSError:
        base = os.environ.get("APPDATA") or (Path.home() / ".config")
        fallback = Path(base) / APP_DIR_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        _DATA_DIR = fallback
    return _DATA_DIR


def cache_dir() -> Path:
    """10 帧监控缓存的落盘目录（程序目录内，自动清理）。"""
    return data_dir() / "frames"


def default_output_dir() -> Path:
    """用户未指定时，尾图的默认输出目录（同样在程序目录内，避免污染 C 盘）。"""
    return program_dir() / "captures"


def config_path() -> Path:
    return data_dir() / "config.json"


def legacy_config_path() -> Path:
    """旧版本配置位置，仅用于一次性迁移读取。"""
    base = os.environ.get("APPDATA") or (Path.home() / ".config")
    return Path(base) / APP_DIR_NAME / "config.json"


def relative_to_program(path: Path) -> str:
    """用于界面展示的短路径，尽量相对于程序目录。"""
    try:
        return str(Path(path).resolve().relative_to(program_dir().resolve()))
    except (ValueError, OSError):
        return str(path)
