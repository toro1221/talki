"""System tray icon with programmatic icons and context menu."""

import math

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QIcon
from PySide6.QtCore import QObject, Signal, QRectF


STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_PROCESSING = "processing"


def _create_icon(state: str, size: int = 64) -> QIcon:
    """Generate a tray icon programmatically via QPainter."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = size / 2, size / 2
    margin = size * 0.1

    if state == STATE_IDLE:
        color = QColor(160, 160, 160)
    elif state == STATE_LISTENING:
        color = QColor(76, 175, 80)  # Green
    elif state == STATE_PROCESSING:
        color = QColor(255, 152, 0)  # Orange
    else:
        color = QColor(160, 160, 160)

    pen = QPen(color, size * 0.06)
    painter.setPen(pen)

    # Microphone body (rounded rect)
    mic_w = size * 0.28
    mic_h = size * 0.38
    mic_x = cx - mic_w / 2
    mic_y = margin + size * 0.02
    painter.setBrush(QBrush(color) if state != STATE_IDLE else QBrush(QColor(0, 0, 0, 0)))
    painter.drawRoundedRect(QRectF(mic_x, mic_y, mic_w, mic_h),
                            mic_w / 2, mic_w / 2)

    # Microphone cradle arc
    cradle_w = size * 0.48
    cradle_h = size * 0.30
    cradle_x = cx - cradle_w / 2
    cradle_y = mic_y + mic_h * 0.4
    painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
    painter.drawArc(QRectF(cradle_x, cradle_y, cradle_w, cradle_h),
                    0, -180 * 16)

    # Stand line
    stand_top = cradle_y + cradle_h / 2
    stand_bottom = size - margin - size * 0.06
    painter.drawLine(int(cx), int(stand_top), int(cx), int(stand_bottom))

    # Base line
    base_w = size * 0.3
    painter.drawLine(int(cx - base_w / 2), int(stand_bottom),
                     int(cx + base_w / 2), int(stand_bottom))

    # Sound waves for listening state
    if state == STATE_LISTENING:
        wave_pen = QPen(QColor(76, 175, 80, 150), size * 0.04)
        painter.setPen(wave_pen)
        for i, radius in enumerate([size * 0.12, size * 0.20]):
            alpha = 200 - i * 60
            wave_pen.setColor(QColor(76, 175, 80, max(alpha, 60)))
            painter.setPen(wave_pen)
            wave_rect = QRectF(cx + size * 0.18 - radius,
                               cy - size * 0.15 - radius,
                               radius * 2, radius * 2)
            painter.drawArc(wave_rect, -45 * 16, 90 * 16)
            # Mirror on left side
            wave_rect_l = QRectF(cx - size * 0.18 - radius,
                                 cy - size * 0.15 - radius,
                                 radius * 2, radius * 2)
            painter.drawArc(wave_rect_l, 135 * 16, 90 * 16)

    # Spinner dots for processing state
    if state == STATE_PROCESSING:
        dot_pen = QPen(QColor(255, 152, 0))
        painter.setPen(dot_pen)
        painter.setBrush(QBrush(QColor(255, 152, 0)))
        for i in range(3):
            angle = (i * 120) * math.pi / 180
            dot_x = cx + math.cos(angle) * size * 0.08 + size * 0.28
            dot_y = cy - size * 0.1 + math.sin(angle) * size * 0.08
            painter.drawEllipse(QRectF(dot_x - 2, dot_y - 2, 4, 4))

    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._state = STATE_IDLE
        self._icons = {
            STATE_IDLE: _create_icon(STATE_IDLE),
            STATE_LISTENING: _create_icon(STATE_LISTENING),
            STATE_PROCESSING: _create_icon(STATE_PROCESSING),
        }
        self._status_action = None
        self._setup_menu()
        self.set_state(STATE_IDLE)
        self.activated.connect(self._on_activated)

    def _setup_menu(self):
        menu = QMenu()
        self._status_action = menu.addAction("Status: Idle")
        self._status_action.setEnabled(False)
        menu.addSeparator()
        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self.settings_requested.emit)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_requested.emit)
        self.setContextMenu(menu)

    def set_state(self, state: str):
        self._state = state
        icon = self._icons.get(state, self._icons[STATE_IDLE])
        self.setIcon(icon)

        labels = {
            STATE_IDLE: "Idle",
            STATE_LISTENING: "Listening...",
            STATE_PROCESSING: "Processing...",
        }
        label = labels.get(state, "Idle")
        self.setToolTip(f"Talki - {label}")
        if self._status_action:
            self._status_action.setText(f"Status: {label}")

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.settings_requested.emit()
