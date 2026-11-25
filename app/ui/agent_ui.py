"""Agent 设置与发送前确认对话框。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..agent import (
    ConversationApi,
    ConversationApiError,
    Incident,
    discover_base_url,
    ensure_playbook,
    playbook_path,
)
from ..config import AppConfig
from .qt_image import numpy_to_qimage

_PREVIEW_W = 360
_PREVIEW_H = 240


class AgentSettingsDialog(QDialog):
    """连接地址、目标会话、超时与规则文件。"""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agent 接管设置")
        self.setMinimumWidth(560)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Agent 接管")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "异常发生时弹窗确认，再把「安全头 + 事件信息 + 尾图 + 规则文件路径」发给 DSH 会话。"
        )
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self._enabled = QCheckBox("异常时询问是否交给 Agent")
        self._enabled.setChecked(bool(config.agent_enabled))
        layout.addWidget(self._enabled)

        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_session_group())
        layout.addWidget(self._build_options_group())

        note = QLabel(
            "发送前一定会弹窗确认；确认后 Agent 可能直接操作桌面（点击/按键/关窗）。"
            "若它在 DSH 里等待审批，界面会提示你。"
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ 构建
    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("连接")
        form = QFormLayout(group)
        form.setContentsMargins(12, 14, 12, 10)
        form.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(7)
        self._base = QLineEdit(self._config.agent_base_url)
        self._base.setPlaceholderText("http://127.0.0.1:56193/conversation-api")
        self._detect_btn = QPushButton("自动探测")
        self._detect_btn.setObjectName("ghost")
        self._detect_btn.clicked.connect(self._auto_detect)
        row.addWidget(self._base, 1)
        row.addWidget(self._detect_btn)
        form.addRow("接口地址", row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self._test_btn = QPushButton("测试连接")
        self._test_btn.setObjectName("ghost")
        self._test_btn.clicked.connect(self._test_connection)
        self._status = QLabel("—")
        self._status.setObjectName("hint")
        row2.addWidget(self._test_btn)
        row2.addWidget(self._status, 1)
        form.addRow("", row2)
        return group

    def _build_session_group(self) -> QGroupBox:
        group = QGroupBox("会话")
        form = QFormLayout(group)
        form.setContentsMargins(12, 14, 12, 10)
        form.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(7)
        self._session = QLineEdit(self._config.agent_session_id)
        self._session.setPlaceholderText("留空则在首次发送时自动创建")
        self._new_session_btn = QPushButton("新建会话")
        self._new_session_btn.setObjectName("ghost")
        self._new_session_btn.clicked.connect(self._create_session)
        row.addWidget(self._session, 1)
        row.addWidget(self._new_session_btn)
        form.addRow("会话 ID", row)

        hint = QLabel(f"新会话的工作目录：{paths.program_dir()}")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return group

    def _build_options_group(self) -> QGroupBox:
        group = QGroupBox("其它")
        form = QFormLayout(group)
        form.setContentsMargins(12, 14, 12, 10)
        form.setSpacing(8)

        self._timeout = QSpinBox()
        self._timeout.setRange(30, 3600)
        self._timeout.setValue(max(30, int(self._config.agent_timeout_ms / 1000)))
        self._timeout.setSuffix(" 秒")
        form.addRow("等待上限", self._timeout)

        row = QHBoxLayout()
        row.setSpacing(7)
        self._playbook_label = QLabel(str(playbook_path()))
        self._playbook_label.setObjectName("hint")
        self._playbook_label.setWordWrap(True)
        self._open_playbook_btn = QPushButton("打开规则文件")
        self._open_playbook_btn.setObjectName("ghost")
        self._open_playbook_btn.clicked.connect(self._open_playbook)
        row.addWidget(self._playbook_label, 1)
        row.addWidget(self._open_playbook_btn)
        form.addRow("规则文件", row)
        return group

    # ------------------------------------------------------------------ 操作
    def _auto_detect(self) -> None:
        self._set_status("探测中…", "#93a4b8")
        _pump_events()
        found = discover_base_url()
        if found:
            self._base.setText(found)
            self._set_status("已找到对话 API", "#34d399")
        else:
            self._set_status("未找到运行中的 DSH，请手动填写", "#fbbf24")

    def _test_connection(self) -> None:
        try:
            api = ConversationApi(self._base.text())
            info = api.describe()
        except Exception as exc:
            self._set_status(f"连接失败：{exc}", "#f87171")
            return
        if info.get("service") != "conversation-api":
            self._set_status("该地址不是对话 API", "#f87171")
            return
        session_id = self._session.text().strip()
        if not session_id:
            self._set_status("服务可用（尚未绑定会话）", "#34d399")
            return
        try:
            api.state(session_id)
        except ConversationApiError as exc:
            self._set_status(f"服务可用，但会话不可用：{exc}", "#fbbf24")
            return
        self._set_status("服务与会话都可用", "#34d399")

    def _create_session(self) -> None:
        try:
            api = ConversationApi(self._base.text())
            session_id = api.create_session(str(paths.program_dir()))
        except Exception as exc:
            QMessageBox.warning(self, "创建会话失败", str(exc))
            return
        self._session.setText(session_id)
        self._set_status("已创建会话", "#34d399")

    def _open_playbook(self) -> None:
        target = ensure_playbook()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _on_save(self) -> None:
        if self._enabled.isChecked() and not self._base.text().strip():
            QMessageBox.warning(self, "还差一步", "启用 Agent 前需要填写对话 API 地址，或先点「自动探测」。")
            return
        self.accept()

    def apply_to(self, config: AppConfig) -> None:
        config.agent_enabled = self._enabled.isChecked()
        config.agent_base_url = self._base.text().strip()
        config.agent_session_id = self._session.text().strip()
        config.agent_timeout_ms = self._timeout.value() * 1000

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color};")


class HandoffDialog(QDialog):
    """触发时的人工确认：给用户看尾图，问是否交给 Agent。"""

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


def _pump_events() -> None:
    """让探测期间的状态文字先刷新。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()
