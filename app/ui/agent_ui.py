"""Agent 设置与发送前确认对话框。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..agent import (
    DEFAULT_PLAYBOOK,
    ConversationApi,
    ConversationApiError,
    Incident,
    discover_base_url,
    ensure_playbook,
    list_incidents,
    load_incident_detail,
    playbook_path,
    playbook_version,
    write_playbook,
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

        self._cooldown = QSpinBox()
        self._cooldown.setRange(0, 120)
        self._cooldown.setValue(max(0, int(self._config.agent_cooldown_minutes)))
        self._cooldown.setSuffix(" 分钟")
        self._cooldown.setToolTip("同一区域两次询问的最小间隔；0 表示不限制")
        form.addRow("冷却时间", self._cooldown)

        self._hourly = QSpinBox()
        self._hourly.setRange(0, 60)
        self._hourly.setValue(max(0, int(self._config.agent_hourly_limit)))
        self._hourly.setSuffix(" 次")
        self._hourly.setToolTip("每小时最多询问次数；0 表示不限制")
        form.addRow("每小时上限", self._hourly)

        row = QHBoxLayout()
        row.setSpacing(7)
        self._playbook_label = QLabel(self._playbook_text())
        self._playbook_label.setObjectName("hint")
        self._playbook_label.setWordWrap(True)
        self._edit_playbook_btn = QPushButton("编辑")
        self._edit_playbook_btn.setObjectName("ghost")
        self._edit_playbook_btn.clicked.connect(self._open_editor)
        self._open_playbook_btn = QPushButton("打开")
        self._open_playbook_btn.setObjectName("ghost")
        self._open_playbook_btn.clicked.connect(self._open_playbook)
        row.addWidget(self._playbook_label, 1)
        row.addWidget(self._edit_playbook_btn)
        row.addWidget(self._open_playbook_btn)
        form.addRow("规则文件", row)

        history_row = QHBoxLayout()
        history_row.setSpacing(7)
        self._history_btn = QPushButton("处理历史")
        self._history_btn.setObjectName("ghost")
        self._history_btn.clicked.connect(self._open_history)
        history_row.addWidget(self._history_btn)
        history_row.addStretch(1)
        form.addRow("记录", history_row)
        return group

    def _playbook_text(self) -> str:
        target = ensure_playbook()
        return f"{target}（v{playbook_version(target)}）"

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

    def _open_editor(self) -> None:
        dialog = PlaybookEditorDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._playbook_label.setText(self._playbook_text())

    def _open_history(self) -> None:
        AgentHistoryDialog(self).exec()

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
        config.agent_cooldown_minutes = self._cooldown.value()
        config.agent_hourly_limit = self._hourly.value()

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


class PlaybookEditorDialog(QDialog):
    """编辑 data/playbook.md：保存时自动递增版本号，可插入参考图。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("规则手册")
        self.resize(760, 620)
        self._path = ensure_playbook()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(8)
        path_label = QLabel(str(self._path))
        path_label.setObjectName("hint")
        path_label.setWordWrap(True)
        self._version_label = QLabel(f"v{playbook_version(self._path)}")
        self._version_label.setObjectName("caption")
        header.addWidget(path_label, 1)
        header.addWidget(self._version_label)
        layout.addLayout(header)

        self._edit = QPlainTextEdit()
        self._edit.setObjectName("codeEditor")
        self._edit.setPlainText(self._path.read_text(encoding="utf-8"))
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self._edit, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        insert_btn = QPushButton("插入参考图…")
        insert_btn.setObjectName("ghost")
        insert_btn.clicked.connect(self._insert_image)
        restore_btn = QPushButton("恢复模板")
        restore_btn.setObjectName("ghost")
        restore_btn.clicked.connect(self._restore_template)
        buttons.addWidget(insert_btn)
        buttons.addWidget(restore_btn)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        hint = QLabel(
            "每条场景建议按「参考图 + 情况分析 + 解决步骤」写；保存后版本号自动 +1，"
            "Agent 下次会读到新版本。参考图会复制到 data/playbook_images/。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _insert_image(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "选择参考图", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif)"
        )
        if not chosen:
            return
        source = Path(chosen)
        target_dir = paths.data_dir() / "playbook_images"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"ref_{stamp}{source.suffix.lower()}"
        index = 1
        while target.exists():
            target = target_dir / f"ref_{stamp}_{index}{source.suffix.lower()}"
            index += 1
        shutil.copy2(source, target)
        relative = f"playbook_images/{target.name}"
        cursor = self._edit.textCursor()
        cursor.insertText(f"- 参考图：{relative}\n")
        self._edit.setTextCursor(cursor)

    def _restore_template(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复模板",
            "会用内置模板替换当前内容（保存后才生效）。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._edit.setPlainText(DEFAULT_PLAYBOOK)

    def _save(self) -> None:
        text = self._edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "内容为空", "规则手册不能为空。")
            return
        try:
            version = write_playbook(text, self._path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._version_label.setText(f"v{version}")
        self.accept()


class AgentHistoryDialog(QDialog):
    """浏览 data/incidents/ 里的处理记录。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Agent 处理历史")
        self.resize(880, 560)
        self._records: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._list = QListWidget()
        self._list.setMinimumWidth(300)
        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list, 1)
        refresh = QPushButton("刷新")
        refresh.setObjectName("ghost")
        refresh.clicked.connect(self._load)
        left.addWidget(refresh)
        body.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(8)
        self._preview = QLabel("（无尾图）")
        self._preview.setObjectName("preview")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(320, 200)
        right.addWidget(self._preview)
        self._info = QLabel("—")
        self._info.setObjectName("hint")
        self._info.setWordWrap(True)
        right.addWidget(self._info)
        self._reply = QPlainTextEdit()
        self._reply.setObjectName("log")
        self._reply.setReadOnly(True)
        right.addWidget(self._reply, 1)
        body.addLayout(right, 1)
        layout.addLayout(body, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._open_btn = QPushButton("打开记录目录")
        self._open_btn.setObjectName("ghost")
        self._open_btn.clicked.connect(self._open_folder)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        bottom.addWidget(self._open_btn)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        self._load()

    def _load(self) -> None:
        self._records = list_incidents(200)
        self._list.clear()
        for record in self._records:
            moment = str(record.get("captured_at") or "").replace("T", " ")[:19]
            verdict = record.get("verdict") or record.get("status") or "?"
            sequence = record.get("sequence")
            label = f"{moment} · #{sequence} · {verdict}"
            self._list.addItem(label)
        if self._records:
            self._list.setCurrentRow(0)
        else:
            self._info.setText("还没有处理记录。")
            self._reply.setPlainText("")

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= len(self._records):
            return
        detail = load_incident_detail(self._records[row])
        folder = Path(str(detail.get("folder") or ""))
        tail = folder / "tail.png"
        if tail.exists():
            pixmap = QPixmap(str(tail)).scaled(
                QSize(312, 192),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview.setPixmap(pixmap)
        else:
            self._preview.clear()
            self._preview.setText("（无尾图）")

        trigger = detail.get("trigger") or {}
        region = detail.get("region") or {}
        captured = str(detail.get("captured_at") or "").replace("T", " ").split(".")[0]
        lines = [
            f"时间：{captured}",
            f"区域：{region.get('width')}×{region.get('height')} "
            f"@({region.get('left')}, {region.get('top')})",
            f"状态：{detail.get('status')} · 判定：{detail.get('verdict') or '—'}",
            f"静止：{trigger.get('unchanged')}/{trigger.get('max_unchanged')} 次 · {trigger.get('audio') or ''}",
            f"耗时：{detail.get('elapsed_ms')} ms · 会话：{detail.get('session_id') or '—'}",
        ]
        if detail.get("error"):
            lines.append(f"错误：{detail['error']}")
        self._info.setText("\n".join(str(line) for line in lines))
        self._reply.setPlainText(detail.get("reply") or detail.get("message") or "")

    def _open_folder(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._records):
            return
        folder = Path(str(self._records[row].get("folder") or ""))
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
