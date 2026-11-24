"""启动入口：先确认依赖，缺依赖时给出可操作的提示，而不是甩一段 traceback。"""

from __future__ import annotations

import sys

_REQUIRED = {
    "PySide6": "PySide6",
    "mss": "mss",
    "numpy": "numpy",
    "PIL": "Pillow",
}


def missing_dependencies() -> list[str]:
    """返回当前解释器缺少的依赖（导入名 → 包名）。"""
    missing: list[str] = []
    for module, package in _REQUIRED.items():
        try:
            __import__(module)
        except ModuleNotFoundError:
            missing.append(package)
    return missing


def _explain(missing: list[str]) -> None:
    print("无法启动：当前 Python 解释器缺少依赖：" + "、".join(missing))
    print(f"当前解释器：{sys.executable}")

    executable = sys.executable.lower()
    if "libreoffice" in executable or "inkscape" in executable:
        print("这是其他软件自带的 Python，不能用来运行本项目。")
    print()
    print("请改用装过依赖的 Python 运行，例如在项目目录执行：")
    print("    python run.py")
    print("若还没安装依赖，先执行：")
    print("    python -m pip install -r requirements.txt")
    print()
    print("也可以直接双击 run.bat，它会自动挑选可用的解释器。")


def main() -> int:
    missing = missing_dependencies()
    if missing:
        _explain(missing)
        return 1

    from app.main import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
