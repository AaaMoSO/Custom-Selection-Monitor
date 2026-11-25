"""深色主题样式表。"""

from __future__ import annotations

from pathlib import Path

_QSS_TEMPLATE = """
QWidget {
    color: #dbe6f1;
    font-size: 13px;
}
QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QMainWindow, QWidget#shell {
    background: #0b0f14;
}

QLabel#title {
    font-size: 22px;
    font-weight: 700;
    color: #eef4fb;
}
QLabel#subtitle {
    color: #7c8b9d;
    font-size: 12px;
}
QLabel#cardTitle {
    color: #8fa2b6;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#hint {
    color: #64748b;
    font-size: 11px;
}
QLabel#caption {
    color: #6f7f92;
    font-size: 11px;
}
QLabel#metricValue {
    color: #e8f1fa;
    font-size: 17px;
    font-weight: 600;
}
QLabel#regionValue {
    color: #cfe0f0;
    font-size: 13px;
    font-weight: 600;
}
QLabel#version {
    color: #47576b;
    font-size: 11px;
}

QFrame#card {
    background: #11161d;
    border: 1px solid #1d2632;
    border-radius: 12px;
}

QLabel#stateChip {
    border-radius: 11px;
    padding: 4px 14px;
    font-weight: 700;
    font-size: 12px;
}
QLabel#stateChip[state="idle"] {
    background: #1a2230;
    color: #93a4b8;
    border: 1px solid #26313f;
}
QLabel#stateChip[state="monitoring"] {
    background: rgba(52, 211, 153, 0.14);
    color: #34d399;
    border: 1px solid rgba(52, 211, 153, 0.35);
}
QLabel#stateChip[state="paused"] {
    background: rgba(251, 191, 36, 0.14);
    color: #fbbf24;
    border: 1px solid rgba(251, 191, 36, 0.35);
}

QPushButton {
    background: #16202b;
    border: 1px solid #263547;
    border-radius: 9px;
    padding: 8px 16px;
    color: #d7e3ef;
    font-weight: 600;
}
QPushButton:hover {
    background: #1b2836;
    border-color: #33465c;
}
QPushButton:pressed {
    background: #131c26;
}
QPushButton:disabled {
    color: #4d5b6b;
    background: #121920;
    border-color: #1b2430;
}
QPushButton#primary {
    background: #0ea5e9;
    border: none;
    color: #04121c;
    font-weight: 700;
    padding: 10px 18px;
}
QPushButton#primary:hover {
    background: #38bdf8;
}
QPushButton#primary:pressed {
    background: #0284c7;
}
QPushButton#primary:disabled {
    background: #12313f;
    color: #4f6b7a;
}
QPushButton#ghost {
    background: transparent;
    border: 1px solid #263547;
}
QPushButton#ghost:hover {
    background: #16202b;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0c1219;
    border: 1px solid #22303f;
    border-radius: 8px;
    padding: 6px 10px;
    color: #dbe6f1;
    min-height: 20px;
    selection-background-color: #1d4ed8;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #0ea5e9;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: #55647a;
}
QComboBox {
    padding-right: 26px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url("__ARROW_ICON__");
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background: #11161d;
    border: 1px solid #22303f;
    border-radius: 6px;
    color: #dbe6f1;
    selection-background-color: #0ea5e9;
    selection-color: #04121c;
    outline: none;
    padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 0px;
    height: 0px;
    border: none;
}

QLabel#preview {
    background: #0a0f15;
    border: 1px dashed #24303f;
    border-radius: 10px;
    color: #46586c;
    font-size: 11px;
}
QLabel#lastSaved {
    color: #7c8b9d;
    font-size: 11px;
}

QCheckBox {
    color: #c3d2e2;
    spacing: 8px;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #2f4155;
    background: #0c1219;
}
QCheckBox::indicator:hover {
    border-color: #3f5771;
}
QCheckBox::indicator:checked {
    background: #0ea5e9;
    border-color: #0ea5e9;
    image: url("__CHECK_ICON__");
}

QListWidget {
    background: #0c1219;
    border: 1px solid #1a2330;
    border-radius: 10px;
    color: #c3d2e2;
    outline: none;
    padding: 4px;
}
QListWidget::item {
    padding: 6px 8px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background: #16202b;
}
QListWidget::item:selected {
    background: #0ea5e9;
    color: #04121c;
}

QPlainTextEdit {
    background: #090e14;
    border: 1px solid #1a2330;
    border-radius: 10px;
    color: #b8c7d9;
    padding: 8px;
    selection-background-color: #1d4ed8;
}
QPlainTextEdit#codeEditor {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}
QPlainTextEdit#log {
    background: #090e14;
    border: 1px solid #1a2330;
    border-radius: 10px;
    color: #8ea0b4;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    padding: 8px;
}

QScrollArea {
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #24303f;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #33465c;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0px;
}

QToolTip {
    background: #111923;
    color: #dbe6f1;
    border: 1px solid #2a3a4d;
    padding: 4px 8px;
}

QDialog {
    background: #0b0f14;
}
QLabel#dialogTitle {
    font-size: 17px;
    font-weight: 700;
    color: #eef4fb;
}
QGroupBox {
    border: 1px solid #1d2632;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px 10px 8px 10px;
    color: #8fa2b6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #8fa2b6;
    font-weight: 700;
    font-size: 11px;
}
"""

_ASSETS = Path(__file__).resolve().parent / "assets"
_CHECK_ICON = (_ASSETS / "check.png").as_posix()
_ARROW_ICON = (_ASSETS / "arrow.png").as_posix()
APP_QSS = (
    _QSS_TEMPLATE.replace("__CHECK_ICON__", _CHECK_ICON)
    .replace("__ARROW_ICON__", _ARROW_ICON)
)
