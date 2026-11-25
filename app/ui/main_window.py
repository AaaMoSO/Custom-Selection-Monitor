"""主窗口：区域选择、参数设置、状态展示与日志。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..agent import (
    AgentGate,
    AgentSendTask,
    Incident,
    build_message,
    ensure_playbook,
    incident_dir,
    new_incident_id,
    playbook_version,
    save_failure,
    save_incident,
    save_reply,
)
from ..audio import AudioDevice, default_output_device, is_silent, list_output_devices
from ..border import RegionBorder
from ..capture import CaptureRegion
from ..config import APP_VERSION, AppConfig
from ..controller import MonitorController
from ..selection import RegionSelector
from ..state import MonitorState
from .agent_ui import AgentSettingsDialog, HandoffDialog
from .qt_image import numpy_to_qimage

_PREVIEW_W = 172
_PREVIEW_H = 97


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(7)
    if title:
        label = QLabel(title)
        label.setObjectName("cardTitle")
        layout.addWidget(label)
    return frame, layout


def _metric(caption: str) -> tuple[QWidget, QLabel]:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    value = QLabel("—")
    value.setObjectName("metricValue")
    label = QLabel(caption)
    label.setObjectName("caption")
    layout.addWidget(value)
    layout.addWidget(label)
    return box, value


class MainWindow(QMainWindow):
    def __init__(self, controller: MonitorController, config: AppConfig) -> None:
        super().__init__()
        self._controller = controller
        self._config = config
        self._selector = RegionSelector(self)
        self._border = RegionBorder(self)
        self._audio_devices: list[AudioDevice] = []
        self._audio_indicator_cache: tuple[str, str] | None = None
        self._incident_seq = 0
        self._agent_tasks: list[AgentSendTask] = []
        self._agent_gate = AgentGate()
        self._loading = True

        self._build()
        self._wire()
        self._load_config()
        self._loading = False

        self._apply_chip(controller.state)
        self._sync_buttons(controller.state, controller.region)
        self._append_log(
            f"Pause recognition v{APP_VERSION} · 每 {controller.interval_ms // 1000} 秒截取一帧，"
            f"缓存 {controller.capacity} 张"
        )
        self._append_log(
            f"帧缓存目录：{paths.relative_to_program(controller.cache.directory)}（自动清理）"
        )
        self._append_log("请先「框选区域」，再点击「开始监控」。")

        self._place_window()

    # ------------------------------------------------------------------ 构建
    def _build(self) -> None:
        self.setWindowTitle("Pause recognition · 屏幕静默监控")
        self.setMinimumSize(560, 480)

        shell = QWidget()
        shell.setObjectName("shell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("root")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(9)
        scroll.setWidget(content)
        shell_layout.addWidget(scroll)
        self.setCentralWidget(shell)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_region_card())
        layout.addWidget(self._build_params_card())
        layout.addWidget(self._build_status_card())
        layout.addLayout(self._build_controls())
        layout.addWidget(self._build_log())
        layout.addStretch(1)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel("Pause recognition")
        title.setObjectName("title")
        subtitle = QLabel("屏幕区域静默监控 · 像素差判定 · 触发即存档")
        subtitle.setObjectName("subtitle")
        text.addWidget(title)
        text.addWidget(subtitle)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("version")
        version.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self._agent_btn = QPushButton("Agent")
        self._agent_btn.setObjectName("ghost")
        self._agent_btn.setToolTip("配置：异常发生时是否交给 DSH Agent 处理")
        row.addLayout(text, 1)
        row.addWidget(self._agent_btn)
        row.addWidget(version)
        return row

    def _build_region_card(self) -> QFrame:
        card, body = _card("监控区域 · 输出与缓存")

        row = QHBoxLayout()
        row.setSpacing(9)
        self._region_label = QLabel("尚未选择区域")
        self._region_label.setObjectName("regionValue")
        self._region_btn = QPushButton("框选区域")
        self._region_btn.setObjectName("ghost")
        self._clear_region_btn = QPushButton("解除")
        self._clear_region_btn.setObjectName("ghost")
        self._clear_region_btn.setToolTip("解除当前框选，清除区域与缓存")
        self._clear_region_btn.setEnabled(False)
        row.addWidget(self._region_label, 1)
        row.addWidget(self._clear_region_btn)
        row.addWidget(self._region_btn)
        body.addLayout(row)

        border_row = QHBoxLayout()
        border_row.setSpacing(8)
        self._border_toggle = QCheckBox("显示区域边框")
        self._border_toggle.setChecked(True)
        self._border_toggle.setToolTip("在屏幕上始终标注被框选区域（置顶、鼠标穿透、不会被截进监控画面）")
        border_row.addWidget(self._border_toggle)

        color_label = QLabel("颜色")
        color_label.setObjectName("caption")
        border_row.addWidget(color_label)
        self._border_color_btn = QPushButton()
        self._border_color_btn.setObjectName("colorSwatch")
        self._border_color_btn.setFixedSize(46, 22)
        self._border_color_btn.setToolTip("选择边框颜色")
        border_row.addWidget(self._border_color_btn)

        width_label = QLabel("粗细")
        width_label.setObjectName("caption")
        border_row.addWidget(width_label)
        self._border_width = QSpinBox()
        self._border_width.setRange(1, 20)
        self._border_width.setValue(3)
        self._border_width.setSuffix(" px")
        self._border_width.setFixedWidth(84)
        self._border_width.setToolTip("边框线宽（逻辑像素）")
        border_row.addWidget(self._border_width)
        border_row.addStretch(1)
        body.addLayout(border_row)

        file_row = QHBoxLayout()
        file_row.setSpacing(7)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("尾图输出目录（触发暂停时保存）…")
        self._folder_edit.setToolTip("异常触发时，尾图保存到这个目录；可随时修改")
        file_row.addWidget(self._folder_edit, 1)
        self._browse_btn = QPushButton("浏览")
        self._browse_btn.setObjectName("ghost")
        self._open_btn = QPushButton("打开输出")
        self._open_btn.setObjectName("ghost")
        self._open_btn.setToolTip("打开尾图输出目录")
        self._cache_btn = QPushButton("打开缓存")
        self._cache_btn.setObjectName("ghost")
        self._cache_btn.setToolTip("打开程序目录内的帧缓存文件夹")
        file_row.addWidget(self._browse_btn)
        file_row.addWidget(self._open_btn)
        file_row.addWidget(self._cache_btn)
        body.addLayout(file_row)

        cache_relative = paths.relative_to_program(paths.cache_dir())
        hint = QLabel(
            f"拖拽框选任意矩形（按物理像素截取，已处理 DPI 缩放）；"
            f"最近 10 帧缓存于 {cache_relative}，自动清理，不写系统盘。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint.setToolTip(f"帧缓存目录：{paths.cache_dir()}")
        body.addWidget(hint)
        return card

    def _build_params_card(self) -> QFrame:
        card, body = _card("判定参数")

        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.001, 100.0)
        self._threshold.setDecimals(3)
        self._threshold.setSingleStep(0.1)
        self._threshold.setValue(1.0)
        self._threshold.setSuffix(" %")
        self._threshold.setToolTip("前后两帧变化像素占比低于该值，视为「未变化」")

        self._max_unchanged = QSpinBox()
        self._max_unchanged.setRange(1, 9999)
        self._max_unchanged.setValue(5)
        self._max_unchanged.setSuffix(" 次")
        self._max_unchanged.setToolTip("连续未变化次数超过该值即暂停并保存最后一帧")

        self._tolerance = QSpinBox()
        self._tolerance.setRange(0, 64)
        self._tolerance.setValue(8)
        self._tolerance.setSuffix(" 级")
        self._tolerance.setToolTip("单像素任一通道差值不超过该值即视为同一像素，用于吸收噪点")

        self._audio_toggle = QCheckBox("声音检测")
        self._audio_toggle.setToolTip(
            "开启后，只有相邻两次采样之间音频电平变化不超过容差时才做像素比对；\n"
            "音频电平变化会跳过本次比对并清零连续计数。"
        )
        self._audio_tolerance = QDoubleSpinBox()
        self._audio_tolerance.setRange(0.1, 20.0)
        self._audio_tolerance.setDecimals(1)
        self._audio_tolerance.setSingleStep(0.5)
        self._audio_tolerance.setValue(1.5)
        self._audio_tolerance.setSuffix(" dB")
        self._audio_tolerance.setFixedWidth(88)
        self._audio_tolerance.setToolTip("相邻两次采样的电平差不超过该值，才算音频“保持不变”")

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("变化阈值"), 0, 0)
        grid.addWidget(self._threshold, 0, 1)
        grid.addWidget(QLabel("连续未变化上限"), 0, 2)
        grid.addWidget(self._max_unchanged, 0, 3)
        grid.addWidget(QLabel("像素容差"), 1, 0)
        grid.addWidget(self._tolerance, 1, 1)

        audio_inline = QHBoxLayout()
        audio_inline.setSpacing(7)
        tolerance_label = QLabel("容差")
        tolerance_label.setObjectName("caption")
        audio_inline.addWidget(self._audio_toggle)
        audio_inline.addWidget(tolerance_label)
        audio_inline.addWidget(self._audio_tolerance)
        audio_inline.addStretch(1)
        grid.addLayout(audio_inline, 1, 2, 1, 2)

        self._audio_combo = QComboBox()
        self._audio_combo.setMinimumWidth(180)
        self._audio_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._audio_combo.setToolTip("选择要监听的音频输出设备（WASAPI 回环）")
        self._audio_refresh_btn = QPushButton("刷新")
        self._audio_refresh_btn.setObjectName("ghost")
        self._audio_refresh_btn.setToolTip("重新检测音频输出设备")
        self._audio_level_label = QLabel("—")
        self._audio_level_label.setObjectName("audioLevel")
        self._audio_level_label.setFixedWidth(92)
        self._audio_level_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._audio_level_label.setToolTip("当前音频电平：绿色=稳定，黄色=变化，静音=-90 dBFS 以下")

        device_row = QHBoxLayout()
        device_row.setSpacing(7)
        device_row.addWidget(self._audio_combo, 1)
        device_row.addWidget(self._audio_refresh_btn)
        device_row.addWidget(self._audio_level_label)
        grid.addWidget(QLabel("输出设备"), 2, 0)
        grid.addLayout(device_row, 2, 1, 1, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        body.addLayout(grid)

        hint = QLabel(
            "变化率低于阈值则 n+1；达到阈值则 n 归零；n 超过上限即暂停。"
            "开启声音检测后，音频变化会跳过比对并清零计数。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        body.addWidget(hint)
        return card

    def _build_status_card(self) -> QFrame:
        card, body = _card("运行状态")

        row = QHBoxLayout()
        row.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(7)

        chip_row = QHBoxLayout()
        self._chip = QLabel("空闲")
        self._chip.setObjectName("stateChip")
        self._chip.setProperty("state", "idle")
        self._chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip_row.addWidget(self._chip)
        chip_row.addStretch(1)
        left.addLayout(chip_row)

        metrics = QHBoxLayout()
        metrics.setSpacing(16)
        box, self._frames_value = _metric("已采样帧")
        metrics.addWidget(box)
        box, self._buffer_value = _metric("缓存")
        metrics.addWidget(box)
        box, self._n_value = _metric("连续未变化")
        metrics.addWidget(box)
        box, self._ratio_value = _metric("上次变化率")
        metrics.addWidget(box)
        left.addLayout(metrics)
        left.addStretch(1)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(3)
        self._preview = QLabel("触发暂停时\n显示保存的画面")
        self._preview.setObjectName("preview")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(_PREVIEW_W, _PREVIEW_H)
        self._last_saved = QLabel("尾图输出：—")
        self._last_saved.setObjectName("lastSaved")
        self._last_saved.setFixedWidth(_PREVIEW_W)
        right.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._last_saved, 0, Qt.AlignmentFlag.AlignRight)
        row.addLayout(right)
        body.addLayout(row)
        return card

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(9)
        self._action_btn = QPushButton("开始监控")
        self._action_btn.setObjectName("primary")
        self._action_btn.setMinimumHeight(38)
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setObjectName("ghost")
        self._stop_btn.setMinimumHeight(38)
        self._stop_btn.setMinimumWidth(88)
        row.addWidget(self._action_btn, 1)
        row.addWidget(self._stop_btn)
        return row

    def _build_log(self) -> QPlainTextEdit:
        self._log = QPlainTextEdit()
        self._log.setObjectName("log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(400)
        self._log.setFixedHeight(78)
        return self._log

    # ------------------------------------------------------------------ 绑定
    def _wire(self) -> None:
        self._region_btn.clicked.connect(self._pick_region)
        self._clear_region_btn.clicked.connect(self._clear_region)
        self._agent_btn.clicked.connect(self._open_agent_settings)
        self._selector.selected.connect(self._on_region_selected)
        self._selector.cancelled.connect(self._on_region_cancelled)
        self._action_btn.clicked.connect(self._on_action)
        self._stop_btn.clicked.connect(self._controller.stop)

        self._controller.statsChanged.connect(self._on_stats)
        self._controller.stateChanged.connect(self._on_state)
        self._controller.triggered.connect(self._on_triggered)
        self._controller.logged.connect(self._append_log)
        self._controller.failed.connect(self._on_failed)

        for spin in (self._threshold, self._max_unchanged, self._tolerance):
            spin.valueChanged.connect(self._persist)
        self._folder_edit.editingFinished.connect(self._persist)
        self._browse_btn.clicked.connect(self._browse)
        self._open_btn.clicked.connect(self._open_output)
        self._cache_btn.clicked.connect(self._open_cache)
        self._border_toggle.toggled.connect(self._on_border_changed)
        self._border_width.valueChanged.connect(self._on_border_changed)
        self._border_color_btn.clicked.connect(self._choose_border_color)
        self._audio_toggle.toggled.connect(self._on_audio_changed)
        self._audio_tolerance.valueChanged.connect(self._on_audio_changed)
        self._audio_combo.currentIndexChanged.connect(self._on_audio_changed)
        self._audio_refresh_btn.clicked.connect(self._reload_audio_devices)

        app = QGuiApplication.instance()
        if app is not None:
            app.screenAdded.connect(lambda *_: self._border.refresh())
            app.screenRemoved.connect(lambda *_: self._border.refresh())

    def _load_config(self) -> None:
        self._threshold.setValue(self._config.threshold_percent)
        self._max_unchanged.setValue(self._config.max_unchanged)
        self._tolerance.setValue(self._config.tolerance)
        self._folder_edit.setText(str(self._config.resolved_save_folder()))
        self._border_toggle.setChecked(bool(self._config.border_visible))
        self._border_width.setValue(int(self._config.border_width))
        self._update_color_swatch()
        self._apply_border_style()

        self._audio_toggle.setChecked(bool(self._config.audio_enabled))
        self._audio_tolerance.setValue(float(self._config.audio_tolerance_db))
        self._audio_devices = list_output_devices()
        self._populate_audio_combo(self._config.audio_device_id)
        if self._audio_toggle.isChecked() and not self._audio_devices:
            self._audio_toggle.setChecked(False)
        self._sync_audio_controls()
        device = self._selected_audio_device()
        self._controller.configure_audio(
            self._audio_toggle.isChecked() and device is not None,
            device,
            self._config.audio_tolerance_db,
        )

    def _place_window(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(620, 700)
            return
        available = screen.availableGeometry()
        width = min(720, max(560, available.width() - 120))
        height = min(776, max(480, available.height() - 40))
        self.resize(width, height)
        self.move(
            available.left() + (available.width() - width) // 2,
            available.top() + (available.height() - height) // 2,
        )

    # ------------------------------------------------------------------ 交互
    def _on_action(self) -> None:
        state = self._controller.state
        if state is MonitorState.IDLE:
            self._controller.start()
        elif state is MonitorState.MONITORING:
            self._controller.pause()
        else:
            self._controller.resume()

    def _pick_region(self) -> None:
        if self._controller.state is not MonitorState.IDLE:
            self._append_log("请先停止当前监控，再重新框选区域")
            return
        self._region_btn.setEnabled(False)
        try:
            self._selector.begin()
        except Exception as exc:  # 遮罩创建失败时不要卡住按钮
            self._append_log(f"无法启动框选：{exc}")
            self._sync_buttons(self._controller.state, self._controller.region)

    def _on_region_cancelled(self) -> None:
        self._append_log("已取消框选")
        self._sync_buttons(self._controller.state, self._controller.region)

    def _clear_region(self) -> None:
        if self._controller.region is None:
            return
        self._controller.clear_region()
        self._border.clear()
        self._region_label.setText("尚未选择区域")
        self._sync_buttons(self._controller.state, None)
        self._append_log("已解除框选，可重新选择区域")

    def _on_region_selected(self, region: CaptureRegion) -> None:
        try:
            self._controller.set_region(region)
        except RuntimeError as exc:
            self._append_log(str(exc))
            return
        self._region_label.setText(region.describe())
        self._append_log(f"已选择区域 {region.describe()}")
        self._apply_border_style()
        self._border.set_region(region, self._selector.last_band)
        self.raise_()
        self.activateWindow()
        self._sync_buttons(self._controller.state, region)

    def _browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择尾图输出目录", start)
        if chosen:
            self._folder_edit.setText(chosen)
            self._persist()

    def _open_output(self) -> None:
        folder = Path(self._folder_edit.text().strip() or str(self._config.resolved_save_folder()))
        self._open_path(folder, "尾图输出目录")

    def _open_cache(self) -> None:
        self._open_path(self._controller.cache.directory, "帧缓存目录")

    def _open_path(self, folder: Path, purpose: str) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._append_log(f"无法打开{purpose}：{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------------ 边框
    def _on_border_changed(self, *args) -> None:
        if self._loading:
            return
        self._config.border_visible = self._border_toggle.isChecked()
        self._config.border_width = self._border_width.value()
        self._apply_border_style()
        self._persist()

    def _choose_border_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._config.border_color), self, "选择边框颜色"
        )
        if not color.isValid():
            return
        self._config.border_color = color.name()
        self._update_color_swatch()
        self._apply_border_style()
        self._persist()

    def _update_color_swatch(self) -> None:
        color = QColor(self._config.border_color)
        if not color.isValid():
            color = QColor("#38bdf8")
        self._border_color_btn.setStyleSheet(
            f"QPushButton#colorSwatch {{ background: {color.name()};"
            f" border: 1px solid #2a3a4d; border-radius: 6px; }}"
            f"QPushButton#colorSwatch:hover {{ border-color: #4b637a; }}"
        )

    def _apply_border_style(self) -> None:
        self._border.set_style(
            self._config.border_color,
            self._config.border_width,
            self._config.border_visible,
        )

    # ------------------------------------------------------------------ 声音
    def _on_audio_changed(self, *args) -> None:
        if self._loading:
            return
        enabled = self._audio_toggle.isChecked()
        device = self._selected_audio_device()
        if enabled and device is None:
            self._loading = True
            self._audio_toggle.setChecked(False)
            self._loading = False
            enabled = False
            self._append_log("未检测到可用的音频输出设备，无法开启声音检测")
        self._config.audio_enabled = enabled
        self._config.audio_tolerance_db = self._audio_tolerance.value()
        if device is not None:
            self._config.audio_device_id = device.id
            self._config.audio_device_name = device.name
        self._controller.configure_audio(
            enabled, device if enabled else None, self._config.audio_tolerance_db
        )
        self._sync_audio_controls()
        self._persist()

    def _reload_audio_devices(self, *args) -> None:
        previous = self._selected_audio_device()
        preferred_id = previous.id if previous is not None else self._config.audio_device_id
        self._audio_devices = list_output_devices()
        self._populate_audio_combo(preferred_id)
        self._sync_audio_controls()
        if not self._audio_devices:
            self._append_log("未检测到可用的音频输出设备（需要声卡与 soundcard 依赖）")
        elif not self._loading:
            self._append_log(f"检测到 {len(self._audio_devices)} 个音频输出设备")
            if self._audio_toggle.isChecked():
                self._on_audio_changed()

    def _populate_audio_combo(self, preferred_id: str) -> None:
        self._audio_combo.blockSignals(True)
        self._audio_combo.clear()
        if self._audio_devices:
            for device in self._audio_devices:
                self._audio_combo.addItem(device.name, device.id)
            index = self._audio_combo.findData(preferred_id) if preferred_id else -1
            if index < 0:
                default = default_output_device()
                if default is not None:
                    index = self._audio_combo.findData(default.id)
            self._audio_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self._audio_combo.addItem("未检测到音频输出设备", "")
        self._audio_combo.blockSignals(False)

    def _selected_audio_device(self) -> AudioDevice | None:
        device_id = self._audio_combo.currentData()
        if not device_id:
            return None
        for device in self._audio_devices:
            if device.id == device_id:
                return device
        return AudioDevice(id=device_id, name=self._audio_combo.currentText())

    def _sync_audio_controls(self) -> None:
        has_devices = bool(self._audio_devices)
        enabled = has_devices and self._audio_toggle.isChecked()
        self._audio_toggle.setEnabled(has_devices)
        self._audio_combo.setEnabled(enabled)
        self._audio_tolerance.setEnabled(enabled)
        self._audio_level_label.setEnabled(enabled)
        if not has_devices:
            self._audio_toggle.setToolTip("未检测到可回环录制的音频输出设备")
        else:
            self._audio_toggle.setToolTip(
                "开启后，只有相邻两次采样之间音频电平变化不超过容差时才做像素比对；\n"
                "音频电平变化会跳过本次比对并清零连续计数。"
            )

    def _update_audio_indicator(self, stats: dict) -> None:
        enabled = bool(stats.get("audio_enabled"))
        level = stats.get("audio_level")
        stable = stats.get("audio_stable")
        state = stats.get("state")

        if not enabled:
            text, color = "—", "#64748b"
        elif level is None:
            if state is MonitorState.MONITORING:
                text, color = "…", "#64748b"
            else:
                text, color = "待机", "#64748b"
        elif is_silent(level):
            text, color = "静音", "#93a4b8"
        elif stable is True:
            text, color = f"{level:.1f} dBFS", "#34d399"
        elif stable is False:
            text, color = f"{level:.1f} dBFS", "#fbbf24"
        else:
            text, color = f"{level:.1f} dBFS", "#93a4b8"

        cache_key = (text, color)
        if cache_key == self._audio_indicator_cache:
            return
        self._audio_indicator_cache = cache_key
        self._audio_level_label.setText(text)
        self._audio_level_label.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;"
        )

    def _persist(self) -> None:
        if self._loading:
            return
        folder = self._folder_edit.text().strip()
        self._config.threshold_percent = self._threshold.value()
        self._config.tolerance = self._tolerance.value()
        self._config.max_unchanged = self._max_unchanged.value()
        self._config.save_folder = folder
        self._config.border_visible = self._border_toggle.isChecked()
        self._config.border_width = self._border_width.value()
        self._config.audio_enabled = self._audio_toggle.isChecked()
        self._config.audio_tolerance_db = self._audio_tolerance.value()
        audio_device = self._selected_audio_device()
        if audio_device is not None:
            self._config.audio_device_id = audio_device.id
            self._config.audio_device_name = audio_device.name
        self._controller.apply_settings(
            threshold_percent=self._config.threshold_percent,
            tolerance=self._config.tolerance,
            max_unchanged=self._config.max_unchanged,
            save_folder=folder,
        )
        try:
            self._config.save()
        except OSError as exc:
            self._append_log(f"配置保存失败：{exc}")

    # ------------------------------------------------------------------ 状态
    def _on_stats(self, stats: dict) -> None:
        self._frames_value.setText(str(stats["frames"]))
        self._buffer_value.setText(f"{stats['buffer_size']} / {stats['capacity']}")
        self._n_value.setText(f"{stats['unchanged']} / {stats['max_unchanged']}")
        ratio = stats.get("last_ratio")
        self._ratio_value.setText("—" if ratio is None else f"{ratio:.3f}%")

        region = stats.get("region")
        if region is not None:
            self._region_label.setText(region.describe())
        else:
            self._region_label.setText("尚未选择区域")
        self._update_audio_indicator(stats)
        self._sync_buttons(stats["state"], region)

    def _on_state(self, state: MonitorState) -> None:
        self._apply_chip(state)
        self._sync_buttons(state, self._controller.region)

    def _apply_chip(self, state: MonitorState) -> None:
        mapping = {
            MonitorState.IDLE: ("空闲", "idle"),
            MonitorState.MONITORING: ("监控中", "monitoring"),
            MonitorState.PAUSED: ("已暂停", "paused"),
        }
        text, prop = mapping[state]
        self._chip.setText(text)
        self._chip.setProperty("state", prop)
        style = self._chip.style()
        style.unpolish(self._chip)
        style.polish(self._chip)

    def _sync_buttons(self, state: MonitorState, region: CaptureRegion | None) -> None:
        self._clear_region_btn.setEnabled(region is not None)
        if state is MonitorState.IDLE:
            self._action_btn.setText("开始监控")
            self._action_btn.setEnabled(region is not None)
            self._stop_btn.setEnabled(False)
            self._region_btn.setEnabled(True)
        elif state is MonitorState.MONITORING:
            self._action_btn.setText("暂停监控")
            self._action_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
            self._region_btn.setEnabled(False)
        else:
            self._action_btn.setText("继续监控")
            self._action_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
            self._region_btn.setEnabled(False)

    def _on_triggered(self, payload: dict) -> None:
        image = payload.get("image")
        if isinstance(image, np.ndarray):
            self._set_preview(image)
        path = payload.get("path")
        if path:
            name = Path(path).name
            metrics = self._last_saved.fontMetrics()
            self._last_saved.setText(
                metrics.elidedText(
                    f"尾图输出：{name}", Qt.TextElideMode.ElideMiddle, _PREVIEW_W
                )
            )
            self._last_saved.setToolTip(str(path))
        QApplication.alert(self, 2500)
        if not self._config.agent_enabled:
            return
        if not self._config.agent_base_url.strip():
            self._append_log("Agent 已启用但未配置接口地址")
            QMessageBox.information(
                self, "Agent 未配置", "请先在「Agent」设置里填写接口地址，或点「自动探测」。"
            )
            return
        if self._agent_tasks:
            self._append_log("上一个 Agent 任务仍在进行，本次未询问")
            return

        region = payload.get("region")
        if not isinstance(region, CaptureRegion):
            return
        decision = self._agent_gate.check(
            region,
            payload.get("image"),
            cooldown_minutes=self._config.agent_cooldown_minutes,
            hourly_limit=self._config.agent_hourly_limit,
        )
        if not decision.allowed:
            self._append_log(f"本次未询问 Agent：{decision.reason}")
            return
        self._offer_handoff(payload, decision.recurrence)

    def _set_preview(self, image: np.ndarray) -> None:
        pixmap = QPixmap.fromImage(numpy_to_qimage(image)).scaled(
            QSize(_PREVIEW_W - 8, _PREVIEW_H - 8),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(pixmap)

    # ------------------------------------------------------------------ Agent
    def _open_agent_settings(self) -> None:
        ensure_playbook()
        dialog = AgentSettingsDialog(self._config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply_to(self._config)
        self._persist()
        state = "已启用" if self._config.agent_enabled else "已关闭"
        self._append_log(f"Agent 接管：{state}")

    def _audio_text(self, stats: dict) -> str:
        if not stats.get("audio_enabled"):
            return "音频未启用"
        level = stats.get("audio_level")
        if level is None:
            return "音频无数据"
        stable = stats.get("audio_stable")
        label = "稳定" if stable is True else "变化" if stable is False else "待判"
        return f"音频 {level:.1f} dBFS · {label}"

    def _offer_handoff(self, payload: dict, recurrence: int = 0) -> None:
        region = payload.get("region")
        if not isinstance(region, CaptureRegion):
            return
        stats = self._controller.stats()
        captured_at = payload.get("captured_at") or datetime.now()
        incident = Incident(
            incident_id=new_incident_id(captured_at),
            sequence=self._incident_seq + 1,
            captured_at=captured_at,
            region=region,
            unchanged=int(payload.get("unchanged") or stats.get("unchanged") or 0),
            max_unchanged=int(stats.get("max_unchanged") or self._config.max_unchanged),
            ratio=payload.get("ratio"),
            audio_text=self._audio_text(stats),
            recurrence=recurrence,
            tail_image=payload.get("image"),
        )

        dialog = HandoffDialog(incident, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._append_log("已忽略本次异常，未交给 Agent")
            return

        self._incident_seq += 1
        try:
            playbook = ensure_playbook()
            message = build_message(incident, playbook, playbook_version(playbook))
            folder = save_incident(incident, message)
        except OSError as exc:
            self._append_log(f"保存异常记录失败：{exc}")
            return

        self._append_log(
            f"已交给 Agent（异常 #{incident.sequence}），等待回执…（监控保持暂停，处理完可点继续监控）"
        )
        task = AgentSendTask(
            base_url=self._config.agent_base_url,
            session_id=self._config.agent_session_id,
            cwd=str(paths.program_dir()),
            prompt=message,
            files=[str(folder / "tail.png")],
            timeout_ms=self._config.agent_timeout_ms,
            request_id=incident.incident_id,
        )
        task.completed.connect(
            lambda result, inc=incident, t=task: self._on_agent_completed(inc, result, t)
        )
        task.failed.connect(
            lambda error, inc=incident, t=task: self._on_agent_failed(inc, error, t)
        )
        self._agent_tasks.append(task)
        task.start()

    def _on_agent_completed(self, incident: Incident, result: dict, task: AgentSendTask) -> None:
        self._release_task(task)
        try:
            text, parsed = save_reply(incident, result)
        except OSError as exc:
            self._append_log(f"保存 Agent 回执失败：{exc}")
            return

        session_id = str(result.get("sessionId") or "")
        if session_id and session_id != self._config.agent_session_id:
            self._config.agent_session_id = session_id
            try:
                self._config.save()
            except OSError as exc:
                self._append_log(f"保存会话 ID 失败：{exc}")

        reason = str(result.get("reason") or "")
        if parsed:
            verdict = str(parsed.get("verdict") or "unknown")
            summary = str(parsed.get("summary") or "")
            confidence = parsed.get("confidence")
            line = f"Agent 回执：{verdict}"
            if isinstance(confidence, (int, float)):
                line += f"（置信度 {float(confidence):.2f}）"
            self._append_log(line + (f" · {summary}" if summary else ""))
        elif text:
            self._append_log(f"Agent 回复（未结构化）：{text[:120]}")
        else:
            self._append_log(f"Agent 未返回文本（reason={reason or 'unknown'}）")

        box = QMessageBox(self)
        box.setWindowTitle("Agent 处理结果")
        if reason == "input-required":
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("Agent 需要你在 DSH 里确认")
            box.setInformativeText(text[:300] if text else "请切到 DSH 的对应会话完成审批。")
        elif reason == "timeout":
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("等待 Agent 超时")
            box.setInformativeText(text[:300] if text else "Agent 可能仍在后台运行。")
        elif parsed:
            box.setIcon(QMessageBox.Icon.Information)
            verdict = str(parsed.get("verdict") or "unknown")
            confidence = parsed.get("confidence")
            suffix = (
                f"（置信度 {float(confidence):.2f}）"
                if isinstance(confidence, (int, float))
                else ""
            )
            box.setText(f"Agent 判定：{verdict}{suffix}")
            box.setInformativeText(str(parsed.get("summary") or ""))
        else:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText("Agent 已回复")
            box.setInformativeText(text[:300] if text else "没有可显示的内容。")
        box.setDetailedText(text or "（无正文）")
        box.exec()

    def _on_agent_failed(self, incident: Incident, error: str, task: AgentSendTask) -> None:
        self._release_task(task)
        try:
            save_failure(incident, error)
        except OSError:
            pass
        self._append_log(f"Agent 发送失败：{error}")
        QMessageBox.warning(self, "Agent 发送失败", error)

    def _release_task(self, task: AgentSendTask) -> None:
        if task in self._agent_tasks:
            self._agent_tasks.remove(task)

    def _on_failed(self, message: str) -> None:
        self._append_log(f"错误：{message}")
        QMessageBox.warning(self, "发生错误", message)

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log.appendPlainText(f"[{stamp}] {message}")

    # ------------------------------------------------------------------ 收尾
    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._selector.active:
            self._selector.cancel()
        self._border.close()
        self._controller.shutdown()
        super().closeEvent(event)
