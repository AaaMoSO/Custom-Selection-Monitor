"""触发时的人工确认对话框（其余 Agent 界面已并入主窗口标签页）。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..agent import Incident
from .qt_image import numpy_to_qimage

_PREVIEW_W = 360
_PREVIEW_H = 240


class HandoffDialog(QDialog):
    """给用户看尾图，问是否交给 Agent。"""

    def __init__(self, incident: Incident, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("发现异常")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("发现异常，是否交给 Agent 处理？")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        preview = QLabel()
        preview.setObjectName("preview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(_PREVIEW_W, _PREVIEW_H)
        if incident.tail_image is not None:
            pixmap = QPixmap.fromImage(numpy_to_qimage(incident.tail_image)).scaled(
                QSize(_PREVIEW_W - 8, _PREVIEW_H - 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            preview.setPixmap(pixmap)
        else:
            preview.setText("（尾图不可用）")
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)

        info = QLabel(
            f"时间：{incident.captured_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"区域：{incident.region.width}×{incident.region.height} "
            f"@({incident.region.left}, {incident.region.top})\n"
            f"判定：连续 {incident.unchanged} 次未变化（上限 {incident.max_unchanged}）"
            f" · {incident.audio_text}"
        )
        info.setObjectName("hint")
        info.setWordWrap(True)
        layout.addWidget(info)

        warning = QLabel(
            "Agent 会读取规则文件并可能直接操作桌面（点击/按键/关窗）。"
            "如果它在 DSH 里需要审批，界面会提示你。"
        )
        warning.setObjectName("hint")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        row = QHBoxLayout()
        row.setSpacing(9)
        ignore = QPushButton("忽略")
        ignore.setObjectName("ghost")
        ignore.clicked.connect(self.reject)
        send = QPushButton("交给 Agent")
        send.setObjectName("primary")
        send.setDefault(True)
        send.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(ignore)
        row.addWidget(send)
        layout.addLayout(row)
