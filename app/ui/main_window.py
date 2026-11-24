"""主窗口：区域选择、参数设置、状态展示与日志。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..border import RegionBorder
from ..capture import CaptureRegion
from ..config import APP_VERSION, AppConfig
from ..controller import MonitorController
from ..selection import RegionSelector
from ..state import MonitorState

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
        row.addLayout(text, 1)
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

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("变化阈值"), 0, 0)
        grid.addWidget(self._threshold, 0, 1)
        grid.addWidget(QLabel("连续未变化上限"), 0, 2)
        grid.addWidget(self._max_unchanged, 0, 3)
        grid.addWidget(QLabel("像素容差"), 1, 0)
        grid.addWidget(self._tolerance, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        body.addLayout(grid)

        hint = QLabel("变化率低于阈值则 n+1；达到阈值则 n 归零；n 超过上限即暂停并保存最后一帧。")
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
        self._log.setFixedHeight(88)
        return self._log

    # ------------------------------------------------------------------ 绑定
    def _wire(self) -> None:
        self._region_btn.clicked.connect(self._pick_region)
        self._clear_region_btn.clicked.connect(self._clear_region)
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

    def _place_window(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(620, 700)
            return
        available = screen.availableGeometry()
        width = min(660, max(560, available.width() - 120))
        height = min(768, max(480, available.height() - 48))
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

    def _set_preview(self, image: np.ndarray) -> None:
        qimage = self._to_qimage(image)
        pixmap = QPixmap.fromImage(qimage).scaled(
            QSize(_PREVIEW_W - 8, _PREVIEW_H - 8),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(pixmap)

    @staticmethod
    def _to_qimage(image: np.ndarray) -> QImage:
        data = np.ascontiguousarray(image)
        height, width, channels = data.shape
        qimage = QImage(
            data.data, width, height, channels * width, QImage.Format.Format_RGB888
        )
        return qimage.copy()

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
