"""Main window: frameless frosted glass with status, settings and the start/stop button."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontInfo, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from app import brand, status
from engine import Outputs, State, StreamStats

AUTO_OUTPUT_LABEL = "Auto (taille de la tablette)"
ENCODER_ITEMS = (("Auto", "auto"), ("AMF (AMD)", "amf"), ("NVENC (NVIDIA)", "nvenc"))
RADIUS = 14.0

STYLE_BASE = """
QWidget { color: rgba(255, 255, 255, 235); font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }
QLabel#title { font-size: 16px; font-weight: 600; }
QLabel#detail { color: rgba(255, 255, 255, 160); font-size: 12px; }
QLabel#field { color: rgba(255, 255, 255, 160); }
QComboBox { background: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 40); border-radius: 8px;
            padding: 5px 10px; }
QComboBox:hover { border-color: rgba(255, 255, 255, 90); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #1D2030; border: 1px solid rgba(255, 255, 255, 40);
                              selection-background-color: rgba(255, 255, 255, 30); outline: none; }
QPushButton#primary { background: rgba(255, 255, 255, 28); border: 1px solid rgba(255, 255, 255, 60);
                      border-radius: 10px; padding: 8px; font-weight: 600; }
QPushButton#primary:hover { background: rgba(255, 255, 255, 42); }
QPushButton#primary:pressed { background: rgba(255, 255, 255, 18); }
QToolButton { background: transparent; border: none; border-radius: 6px; padding: 3px 9px; font-size: 13px; }
QToolButton:hover { background: rgba(255, 255, 255, 30); }
QToolButton#close:hover { background: rgba(232, 17, 35, 210); }
"""


def build_style(brand_family: str) -> str:
    # Le QWidget { font-family } global l'emporte sur setFont : le titre de marque a sa propre règle, plus spécifique.
    return STYLE_BASE + f'QLabel#brandTitle {{ font-family: "{brand_family}"; font-size: 26px; font-weight: normal; }}'


class StatusDot(QWidget):
    """Small coloured dot: the state at a glance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._color = QColor(status.COLORS[State.STOPPED])

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(self.rect()))


class OutputCombo(QComboBox):
    """Screen list that is never rebuilt while open: the list would jump under the cursor."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._popup_open = False
        self._pending: Outputs | None = None

    def set_outputs(self, outputs: Outputs, selected: str) -> None:
        if self._popup_open:
            self._pending = outputs  # appliqué à la fermeture de la liste
            return
        self._pending = None
        self.clear()
        self.addItem(AUTO_OUTPUT_LABEL, "auto")
        for index, size in outputs:
            label = f"Écran {index} — {size[0]}×{size[1]}" if size else f"Écran {index}"
            self.addItem(label, str(index))
        if self.findData(selected) < 0:
            self.addItem(f"Écran {selected}", selected)  # réglage gardé même si l'écran est absent
        self.setCurrentIndex(self.findData(selected))

    def showPopup(self) -> None:
        self._popup_open = True
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        if self._pending is not None:
            # Au prochain tour de boucle : Qt émet activated juste après hidePopup, avec un index de l'ancienne liste.
            QTimer.singleShot(0, self._apply_pending)

    def _apply_pending(self) -> None:
        if self._pending is not None and not self._popup_open:
            self.set_outputs(self._pending, self.currentData())  # garde le choix fait dans la liste


class TitleBar(QWidget):
    """Custom title bar: dragging it moves the window natively (keeps Aero Snap)."""

    def mousePressEvent(self, event) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()


class MainWindow(QWidget):
    output_changed = Signal(str)
    encoder_changed = Signal(str)
    primary_clicked = Signal()
    closed_to_tray = Signal()
    shown = Signal()

    def __init__(self, logo: QPixmap) -> None:
        # Réduire et menu système : sans eux, un clic sur l'icône de la barre des tâches ne réduit pas la fenêtre sans cadre.
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Orizon X")
        self.setWindowIcon(QIcon(logo))
        self.setFixedSize(360, 380)
        brand_family = brand.load_brand_font()
        self.setStyleSheet(build_style(brand_family))
        self._acrylic = False
        self._state = State.STOPPED
        self._quitting = False

        bar = TitleBar(self)
        bar.setFixedHeight(40)
        self._title_bar = bar
        minimize = QToolButton(bar)
        minimize.setText("—")
        minimize.setToolTip("Réduire")
        minimize.clicked.connect(self.showMinimized)
        close = QToolButton(bar)
        close.setObjectName("close")
        close.setText("✕")
        close.setToolTip("Fermer (Orizon X continue dans la zone de notification)")
        close.clicked.connect(self.close)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 0, 8, 0)
        bar_layout.setSpacing(8)
        bar_layout.addStretch(1)
        bar_layout.addWidget(minimize)
        bar_layout.addWidget(close)

        self._logo = QLabel(self)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_logo()
        self._brand_title = QLabel("Orizon X", self)
        self._brand_title.setObjectName("brandTitle")
        self._brand_title.setFont(QFont(brand_family, 26))
        self._brand_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._dot = StatusDot(self)
        self._title = QLabel(self)
        self._title.setObjectName("title")
        self._detail = QLabel(self)
        self._detail.setObjectName("detail")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setWordWrap(True)
        self._detail.setMinimumHeight(34)

        self._outputs = OutputCombo(self)
        self._outputs.addItem(AUTO_OUTPUT_LABEL, "auto")
        self._outputs.activated.connect(lambda _i: self.output_changed.emit(self._outputs.currentData()))
        self._encoders = QComboBox(self)
        for label, value in ENCODER_ITEMS:
            self._encoders.addItem(label, value)
        self._encoders.activated.connect(lambda _i: self.encoder_changed.emit(self._encoders.currentData()))

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        for row, (text, combo) in enumerate((("Écran", self._outputs), ("Encodeur", self._encoders))):
            label = QLabel(text, self)
            label.setObjectName("field")
            form.addWidget(label, row, 0)
            form.addWidget(combo, row, 1)
        form.setColumnStretch(1, 1)

        self._primary = QPushButton(self)
        self._primary.setObjectName("primary")
        self._primary.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._primary.clicked.connect(self.primary_clicked.emit)

        body = QVBoxLayout()
        body.setContentsMargins(22, 4, 22, 20)
        body.setSpacing(6)
        body.addWidget(self._logo)
        body.addWidget(self._brand_title)
        body.addSpacing(10)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addStretch(1)
        status_row.addWidget(self._dot)
        status_row.addWidget(self._title)
        status_row.addStretch(1)
        body.addLayout(status_row)
        body.addWidget(self._detail)
        body.addSpacing(8)
        body.addLayout(form)
        body.addSpacing(12)
        body.addWidget(self._primary)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addLayout(body)
        root.addStretch(1)
        self.set_state(State.STOPPED, "")

    # --- mises à jour depuis le contrôleur ---

    def set_acrylic(self, enabled: bool) -> None:
        self._acrylic = enabled
        self.update()

    def set_state(self, state: State, detail: str) -> None:
        self._state = state
        self._dot.set_color(status.COLORS[state])
        self._title.setText(status.TITLES[state])
        self._detail.setText(status.detail_for(state, detail))
        self._primary.setText(status.primary_label(state))

    def set_stats(self, stats: StreamStats) -> None:
        if self._state is State.STREAMING:
            self._detail.setText(status.stream_detail(stats))

    def set_outputs(self, outputs: Outputs, selected: str) -> None:
        self._outputs.set_outputs(outputs, selected)

    def set_encoder(self, selected: str) -> None:
        self._encoders.setCurrentIndex(max(0, self._encoders.findData(selected)))

    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def prepare_quit(self) -> None:
        """From now on a close really closes (no hide-to-tray, no hint)."""
        self._quitting = True

    # --- accès pour les tests (et choix simulés de l'utilisateur) ---

    def brand_title_family(self) -> str:
        self._brand_title.ensurePolished()
        return QFontInfo(self._brand_title.font()).family()

    def brand_title_text(self) -> str:
        return self._brand_title.text()

    def title_bar_texts(self) -> list[str]:
        return [label.text() for label in self._title_bar.findChildren(QLabel)]

    def title_text(self) -> str:
        return self._title.text()

    def detail_text(self) -> str:
        return self._detail.text()

    def primary_text(self) -> str:
        return self._primary.text()

    def output_items(self) -> list[tuple[str, str]]:
        return [(self._outputs.itemText(i), self._outputs.itemData(i)) for i in range(self._outputs.count())]

    def selected_output(self) -> str:
        return self._outputs.currentData()

    def choose_output(self, value: str) -> None:
        index = self._outputs.findData(value)
        self._outputs.setCurrentIndex(index)
        self._outputs.activated.emit(index)

    def choose_encoder(self, value: str) -> None:
        index = self._encoders.findData(value)
        self._encoders.setCurrentIndex(index)
        self._encoders.activated.emit(index)

    # --- événements Qt ---

    def _refresh_logo(self) -> None:
        self._logo.setPixmap(brand.logo_pixmap(44, self.devicePixelRatioF()))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_logo()  # la fenêtre a pu s'ouvrir sur un écran d'une autre échelle
        self.shown.emit()

    def closeEvent(self, event) -> None:
        if self._quitting:
            event.accept()
            return
        event.ignore()  # la croix cache la fenêtre ; seul « Quitter » ferme l'appli
        self.hide()
        self.closed_to_tray.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        if self._acrylic:
            painter.fillPath(path, QColor(18, 20, 30, 120))  # teinte sombre sur le flou Acrylic
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor(40, 44, 66))
            gradient.setColorAt(1.0, QColor(16, 18, 28))
            painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(255, 255, 255, 31), 1))
        painter.drawPath(path)
