"""Notification-area icon: state badge, tooltip and the right-click menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app import i18n, status
from app.i18n import tr
from engine import State
from messages import Msg


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
        self._state = State.STOPPED
        self._detail: Msg | None = None
        self._autostart_supported = autostart_supported
        self._icon = QSystemTrayIcon()
        self._menu = QMenu()
        self._status = self._menu.addAction("")
        self._status.setEnabled(False)
        self._menu.addSeparator()
        self._labels: list[tuple[QAction, str]] = []  # (action, clé) des entrées à libellé fixe
        self._toggle = self._menu.addAction("")
        self._toggle.triggered.connect(self.toggle_requested.emit)
        self._add("tray.open_window", self.show_requested.emit)
        self._add("tray.open_log", self.open_log_requested.emit)
        self._autostart = self._menu.addAction("")
        self._labels.append((self._autostart, "tray.autostart"))
        self._autostart.setCheckable(True)
        self._autostart.setChecked(autostart_enabled)
        self._autostart.setEnabled(autostart_supported)
        self._autostart.toggled.connect(self.autostart_toggled.emit)
        self._menu.addSeparator()
        self._add("tray.quit", self.quit_requested.emit)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self.set_state(State.STOPPED, None)
        self.retranslate()
        i18n.language_changed.connect(self.retranslate)
        self._icon.show()

    def _add(self, key: str, slot) -> QAction:
        action = self._menu.addAction("")
        action.triggered.connect(slot)
        self._labels.append((action, key))
        return action

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_requested.emit()

    def set_state(self, state: State, detail: Msg | None) -> None:
        self._state = state
        self._detail = detail
        self._icon.setIcon(badge_icon(self._logo, status.COLORS[state]))
        self._show_state()

    def retranslate(self) -> None:
        """Re-applies every menu text in the current language (connected to i18n.language_changed)."""
        lang = i18n.current_language()
        for action, key in self._labels:
            action.setText(tr(key, lang))
        if not self._autostart_supported:
            self._autostart.setToolTip(tr("tray.autostart_unavailable", lang))
        self._show_state()

    def _show_state(self) -> None:
        lang = i18n.current_language()
        title = status.title(self._state, lang)
        detail = status.detail_for(self._state, self._detail, lang)
        self._status.setText(f"{title} — {detail}"[:90])
        self._icon.setToolTip(f"Orizon X — {title}\n{detail}"[:120])
        self._toggle.setText(status.primary_label(self._state, lang))

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

    def is_visible(self) -> bool:
        return self._icon.isVisible()

    def autostart_action_enabled(self) -> bool:
        return self._autostart.isEnabled()

    def autostart_tooltip(self) -> str:
        return self._autostart.toolTip()

    def menu_texts(self) -> list[str]:
        return [action.text() for action in self._menu.actions() if not action.isSeparator()]

    def trigger(self, text: str) -> None:
        for action in self._menu.actions():
            if action.text() == text:
                action.trigger()
                return
        raise KeyError(text)
