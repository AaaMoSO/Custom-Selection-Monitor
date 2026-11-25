"""Agent 的嵌入式面板：连接设置、规则手册、处理历史。

这些面板直接作为主窗口的标签页使用，不再弹独立窗口。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
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
    discover_base_url,
    ensure_playbook,
    list_incidents,
    load_incident_detail,
    playbook_version,
    write_playbook,
)
from ..config import AppConfig


class AgentConnectionPanel(QWidget):
    """连接地址、目标会话、超时与频控。"""

    saved = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
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
            "若它在 DSH 里等待审批，结果框会提示你。"
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._save_btn = QPushButton("保存设置")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._save)
        self._status = QLabel("—")
        self._status.setObjectName("hint")
        row.addWidget(self._save_btn)
        row.addWidget(self._status, 1)
        layout.addLayout(row)
        layout.addStretch(1)

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
        self._conn_status = QLabel("—")
        self._conn_status.setObjectName("hint")
        row2.addWidget(self._test_btn)
        row2.addWidget(self._conn_status, 1)
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
        return group

    # ------------------------------------------------------------------ 操作
    def _auto_detect(self) -> None:
        self._set_conn_status("探测中…", "#93a4b8")
        _pump_events()
        found = discover_base_url()
        if found:
            self._base.setText(found)
            self._set_conn_status("已找到对话 API", "#34d399")
        else:
            self._set_conn_status("未找到运行中的 DSH，请手动填写", "#fbbf24")

    def _test_connection(self) -> None:
        try:
            api = ConversationApi(self._base.text())
            info = api.describe()
        except Exception as exc:
            self._set_conn_status(f"连接失败：{exc}", "#f87171")
            return
        if info.get("service") != "conversation-api":
            self._set_conn_status("该地址不是对话 API", "#f87171")
            return
        session_id = self._session.text().strip()
        if not session_id:
            self._set_conn_status("服务可用（尚未绑定会话）", "#34d399")
            return
        try:
            api.state(session_id)
        except ConversationApiError as exc:
            self._set_conn_status(f"服务可用，但会话不可用：{exc}", "#fbbf24")
            return
        self._set_conn_status("服务与会话都可用", "#34d399")

    def _create_session(self) -> None:
        try:
            api = ConversationApi(self._base.text())
            session_id = api.create_session(str(paths.program_dir()))
        except Exception as exc:
            QMessageBox.warning(self, "创建会话失败", str(exc))
            return
        self._session.setText(session_id)
        self._set_conn_status("已创建会话", "#34d399")

    def _save(self) -> None:
        if self._enabled.isChecked() and not self._base.text().strip():
            QMessageBox.warning(self, "还差一步", "启用 Agent 前需要填写对话 API 地址，或先点「自动探测」。")
            return
        self.apply_to(self._config)
        self._set_status("已保存", "#34d399")
        self.saved.emit()

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

    def _set_conn_status(self, text: str, color: str) -> None:
        self._conn_status.setText(text)
        self._conn_status.setStyleSheet(f"color: {color};")


class PlaybookPanel(QWidget):
    """直接编辑规则手册。"""

    saved = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = ensure_playbook()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(9)

        title = QLabel("规则手册")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._path_label = QLabel(str(self._path))
        self._path_label.setObjectName("hint")
        self._path_label.setWordWrap(True)
        self._version_label = QLabel(f"v{playbook_version(self._path)}")
        self._version_label.setObjectName("caption")
        header.addWidget(self._path_label, 1)
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
        reload_btn = QPushButton("重新载入")
        reload_btn.setObjectName("ghost")
        reload_btn.clicked.connect(self.reload)
        buttons.addWidget(insert_btn)
        buttons.addWidget(restore_btn)
        buttons.addWidget(reload_btn)
        buttons.addStretch(1)
        self._save_btn = QPushButton("保存手册")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._save)
        buttons.addWidget(self._save_btn)
        layout.addLayout(buttons)

        self._status = QLabel(
            "每条场景建议按「参考图 + 情况分析 + 解决步骤」写；保存后版本号自动 +1，"
            "Agent 下次会读到新版本。参考图会复制到 data/playbook_images/。"
        )
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def reload(self) -> None:
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            self._status.setText(f"读取失败：{exc}")
            return
        self._edit.setPlainText(text)
        self._version_label.setText(f"v{playbook_version(self._path)}")
        self._status.setText("已重新载入")

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
        cursor = self._edit.textCursor()
        cursor.insertText(f"- 参考图：playbook_images/{target.name}\n")
        self._edit.setTextCursor(cursor)
        self._status.setText(f"已插入 {target.name}")

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
        self._status.setText(f"已保存 · v{version}")
        self.saved.emit(version)


class AgentHistoryPanel(QWidget):
    """浏览 data/incidents/ 里的处理记录。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
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
        refresh.clicked.connect(self.refresh)
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
        bottom.addWidget(self._open_btn)
        bottom.addStretch(1)
        layout.addLayout(bottom)

        self.refresh()

    def refresh(self) -> None:
        self._records = list_incidents(200)
        self._list.clear()
        for record in self._records:
            moment = str(record.get("captured_at") or "").replace("T", " ")[:19]
            verdict = record.get("verdict") or record.get("status") or "?"
            sequence = record.get("sequence")
            self._list.addItem(f"{moment} · #{sequence} · {verdict}")
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


def _pump_events() -> None:
    """让探测期间的状态文字先刷新。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()
