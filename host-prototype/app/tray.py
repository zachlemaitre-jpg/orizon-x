"""Notification-area icon: state badge, tooltip and the right-click menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app import status
from engine import State


def badge_icon(logo: QPixmap, color: str) -> QIcon:
    """The logo with a coloured dot in the bottom-right corner."""
    pixmap = logo.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(10, 10, 14), 4))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(36, 36, 26, 26))
    painter.end()
    return QIcon(pixmap)


class Tray(QObject):
    show_requested = Signal()
    toggle_requested = Signal()
    open_log_requested = Signal()
    autostart_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self, logo: QPixmap, *, autostart_supported: bool, autostart_enabled: bool) -> None:
        super().__init__()
        self._logo = logo
        self._icon = QSystemTrayIcon()
        self._menu = QMenu()
        self._status = self._menu.addAction("")
        self._status.setEnabled(False)
        self._menu.addSeparator()
        self._toggle = self._add("Arrêter", self.toggle_requested.emit)
        self._add("Ouvrir la fenêtre", self.show_requested.emit)
        self._add("Ouvrir le journal", self.open_log_requested.emit)
        self._autostart = self._menu.addAction("Lancer avec Windows")
        self._autostart.setCheckable(True)
        self._autostart.setChecked(autostart_enabled)
        self._autostart.setEnabled(autostart_supported)
        if not autostart_supported:
            self._autostart.setToolTip("Disponible dans l'appli compilée (OrizonX.exe)")
        self._autostart.toggled.connect(self.autostart_toggled.emit)
        self._menu.addSeparator()
        self._add("Quitter", self.quit_requested.emit)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self.set_state(State.STOPPED, "Arrêté.")
        self._icon.show()

    def _add(self, text: str, slot) -> QAction:
        action = self._menu.addAction(text)
        action.triggered.connect(slot)
        return action

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_requested.emit()

    def set_state(self, state: State, detail: str) -> None:
        title = status.TITLES[state]
        self._status.setText(f"{title} — {status.detail_for(state, detail)}"[:90])
        self._icon.setToolTip(f"Orizon X — {title}\n{status.detail_for(state, detail)}"[:120])
        self._icon.setIcon(badge_icon(self._logo, status.COLORS[state]))
        self._toggle.setText(status.primary_label(state))

    def set_autostart_checked(self, checked: bool) -> None:
        self._autostart.blockSignals(True)
        self._autostart.setChecked(checked)
        self._autostart.blockSignals(False)

    def show_message(self, title: str, text: str) -> None:
        self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)

    def hide(self) -> None:
        self._icon.hide()

    # --- accès pour les tests ---

    def toggle_text(self) -> str:
        return self._toggle.text()

    def status_text(self) -> str:
        return self._status.text()

    def tooltip(self) -> str:
        return self._icon.toolTip()

    def autostart_action_enabled(self) -> bool:
        return self._autostart.isEnabled()

    def trigger(self, text: str) -> None:
        for action in self._menu.actions():
            if action.text() == text:
                action.trigger()
                return
        raise KeyError(text)
