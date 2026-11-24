"""应用入口：设置 DPI 感知、加载配置、组装控制器与窗口。"""

from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from .config import APP_NAME, APP_VERSION, AppConfig
from .controller import MonitorController
from .screens import enable_dpi_awareness
from .ui.main_window import MainWindow
from .ui.theme import APP_QSS


def main() -> int:
    # 必须在 QApplication 之前，否则拿不到物理像素坐标
    enable_dpi_awareness()

    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)
    QCoreApplication.setOrganizationName("AaaMoSO")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)

    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    font.setPointSize(9)
    app.setFont(font)

    config = AppConfig.load()
    if not config.save_folder:
        config.save_folder = str(config.resolved_save_folder())

    controller = MonitorController(config)
    window = MainWindow(controller, config)
    window.show()

    try:
        return app.exec()
    finally:
        controller.shutdown()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
