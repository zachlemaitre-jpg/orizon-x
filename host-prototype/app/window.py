"""Main window: frameless frosted glass with status, settings, the start/stop button and Quit."""
from __future__ import annotations

import os
from typing import Any, Callable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontInfo, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from app import brand, i18n, settings, status
from app.i18n import tr
from engine import DisplayInfo, State, StreamStats
from messages import Msg

MODE_KEYS = {"extend": "window.mode_extend", "duplicate": "window.mode_duplicate"}
POSITION_KEYS = {"right": "window.position_right", "left": "window.position_left",
                 "above": "window.position_above", "below": "window.position_below"}
MODE_ICONS = {"extend": "etendre_affichage", "duplicate": "dupliquer_affichage"}
POSITION_ICONS = {"right": "position_right", "left": "position_left", "above": "position_above", "below": "position_below"}
INTERVAL_ICON = "interval"  # one icon for every interval of the Frame combo
CHOOSE_ICON = "choose"
STOP_ICON = "stop"
COMBO_ICON_PX = 18
BUTTON_ICON_PX = 18
ENCODER_NAMES = {"amf": "AMF (AMD)", "nvenc": "NVENC (NVIDIA)", "qsv": "QuickSync (Intel)"}  # noms de produits : jamais traduits
ENCODER_VALUES = ("auto", "amf", "nvenc", "qsv", "x264")
LANGUAGE_ITEMS = (("English", "en"), ("Français", "fr"))  # chaque langue dans sa propre langue : jamais traduits
VDD_MISSING_KEY = "display.vdd_missing"  # seule erreur qui propose « Passer en Dupliquer »
FRAME_FIT_KEYS = {"crop": "window.frame_crop", "fit": "window.frame_fit"}
LABEL_COLUMN_PX = 78  # même largeur de libellés dans les deux grilles de réglages : les listes s'alignent
WIDTH = 360
HEIGHT = 670  # 360 de large comme avant ; ~30 px de marge avec un bouton d'action visible (groupe Tableau compris)
RADIUS = 14.0

STYLE_BASE = """
QWidget { color: rgba(255, 255, 255, 235); font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }
QLabel#title { font-size: 16px; font-weight: 600; }
QLabel#detail { color: rgba(255, 255, 255, 160); font-size: 12px; }
QLabel#field { color: rgba(255, 255, 255, 160); }
QLabel#field:disabled { color: rgba(255, 255, 255, 70); }
QLabel#group { color: rgba(255, 255, 255, 210); font-weight: 600; }
QLabel#folderPath { background: rgba(255, 255, 255, 10); border: 1px solid rgba(255, 255, 255, 25);
                    border-radius: 8px; padding: 5px 8px; }
QLabel#folderPath[empty="true"] { color: rgba(255, 255, 255, 110); }
QComboBox { background: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 40); border-radius: 8px;
            padding: 5px 10px; }
QComboBox:hover { border-color: rgba(255, 255, 255, 90); }
QComboBox:disabled { color: rgba(255, 255, 255, 80); background: rgba(255, 255, 255, 6);
                     border-color: rgba(255, 255, 255, 20); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #1D2030; border: 1px solid rgba(255, 255, 255, 40);
                              selection-background-color: rgba(255, 255, 255, 30); outline: none; }
QPushButton#primary { background: rgba(255, 255, 255, 28); border: 1px solid rgba(255, 255, 255, 60);
                      border-radius: 10px; padding: 8px; font-weight: 600; }
QPushButton#primary:hover { background: rgba(255, 255, 255, 42); }
QPushButton#primary:pressed { background: rgba(255, 255, 255, 18); }
QPushButton#secondary { background: transparent; border: 1px solid rgba(255, 255, 255, 45);
                        border-radius: 10px; padding: 8px; color: rgba(255, 255, 255, 200); }
QPushButton#secondary:hover { background: rgba(255, 255, 255, 18); }
QPushButton#secondary:pressed { background: rgba(255, 255, 255, 8); }
QPushButton#choose { background: rgba(255, 255, 255, 18); border: 1px solid rgba(255, 255, 255, 40);
                     border-radius: 8px; padding: 5px 12px; }
QPushButton#choose:hover { background: rgba(255, 255, 255, 30); border-color: rgba(255, 255, 255, 90); }
QPushButton#action { background: rgba(245, 181, 68, 40); border: 1px solid rgba(245, 181, 68, 150);
                     border-radius: 8px; padding: 5px 14px; }
QPushButton#action:hover { background: rgba(245, 181, 68, 70); }
QPushButton#link { background: transparent; border: none; padding: 2px 0; color: rgba(150, 190, 255, 230);
                   text-decoration: underline; }
QPushButton#link:hover { color: rgba(190, 215, 255, 255); }
QToolButton { background: transparent; border: none; border-radius: 6px; padding: 3px 9px; font-size: 13px; }
QToolButton:hover { background: rgba(255, 255, 255, 30); }
QToolButton#close:hover { background: rgba(232, 17, 35, 210); }
"""


def build_style(brand_family: str) -> str:
    # Le QWidget { font-family } global l'emporte sur setFont : le titre de marque a sa propre règle, plus spécifique.
    return STYLE_BASE + f'QLabel#brandTitle {{ font-family: "{brand_family}"; font-size: 26px; font-weight: normal; }}'


def _keyed(keys: dict[str, str]) -> Callable[[str, str], str]:
    return lambda value, lang: tr(keys[value], lang)


def _scale_label(value: str, lang: str) -> str:
    return tr("window.auto", lang) if value == "auto" else tr("window.scale_percent", lang, percent=int(value))


def _encoder_label(value: str, lang: str) -> str:
    if value == "auto":
        return tr("window.auto", lang)
    if value == "x264":
        return tr("window.encoder_cpu", lang)
    return ENCODER_NAMES[value]


class ChoiceCombo(QComboBox):
    """A list of setting values whose labels follow the language; activated = the user's choice."""

    def __init__(self, values: tuple[Any, ...], label: Callable[[Any, str], str], parent: QWidget | None = None,
                 icons: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._icons = icons or {}  # value -> icon name (assets/icons)
        for value in values:
            self.addItem("", value)
        if self._icons:
            self.setIconSize(QSize(COMBO_ICON_PX, COMBO_ICON_PX))
        self.retranslate()
        self.refresh_icons()

    def refresh_icons(self) -> None:
        """(Re)renders the item icons at the current screen's pixel ratio."""
        dpr = self.devicePixelRatioF()
        for i in range(self.count()):
            name = self._icons.get(self.itemData(i))
            if name is not None:
                self.setItemIcon(i, brand.icon(name, COMBO_ICON_PX, dpr))

    def retranslate(self) -> None:
        """Relabels the items in place: neither the selection nor an open list moves."""
        lang = i18n.current_language()
        for i in range(self.count()):
            self.setItemText(i, self._label(self.itemData(i), lang))

    def select(self, value: Any) -> None:
        """Shows `value` without emitting activated (that signal means a click)."""
        self.setCurrentIndex(max(0, self.findData(value)))


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with an ellipsis in the middle to fit, whatever the width it gets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # takes the room it is given

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def _elide(self) -> None:
        available = max(0, self.width() - 2 * 8 - 2)  # the padding and border of the style
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, available))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())


def _pick_folder(parent: QWidget, title: str, start: str) -> str:
    """The folder the user picks in the Windows dialog, or "" if they cancel."""
    return QFileDialog.getExistingDirectory(parent, title, start)


def _interval_label(value: int, lang: str) -> str:
    if value % 3600 == 0:
        return tr("window.interval_hours", lang, count=value // 3600)
    if value % 60 == 0:
        return tr("window.interval_minutes", lang, count=value // 60)
    return tr("window.interval_seconds", lang, count=value)


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


class TitleBar(QWidget):
    """Custom title bar: dragging it moves the window natively (keeps Aero Snap)."""

    def mousePressEvent(self, event) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()


class MainWindow(QWidget):
    mode_changed = Signal(str)
    position_changed = Signal(str)
    scale_changed = Signal(str)
    encoder_changed = Signal(str)
    language_chosen = Signal(str)
    primary_clicked = Signal()
    quit_clicked = Signal()
    use_duplicate_clicked = Signal()
    add_resolution_clicked = Signal(int, int)  # taille exacte de la tablette
    adjust_requested = Signal()  # « Régler dans Windows… »
    frame_folder_chosen = Signal(str)  # dossier du Tableau choisi dans la boîte de dialogue
    frame_interval_changed = Signal(int)
    frame_fit_changed = Signal(str)
    closed_to_tray = Signal()

    def __init__(self, logo: QPixmap, pick_folder: Callable[[QWidget, str, str], str] = _pick_folder) -> None:
        # Réduire et menu système : sans eux, un clic sur l'icône de la barre des tâches ne réduit pas la fenêtre sans cadre.
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Orizon X")
        self.setWindowIcon(QIcon(logo))
        self.setFixedSize(WIDTH, HEIGHT)
        brand_family = brand.load_brand_font()
        self.setStyleSheet(build_style(brand_family))
        self._acrylic = False
        self._state = State.STOPPED
        self._detail_msg: Msg | None = None
        self._stats: StreamStats | None = None  # dernières stats du flux en cours, gardées pour un changement de langue
        self._inexact_size: tuple[int, int] | None = None  # tablette sans mode exact dans cette session
        self._quitting = False
        self._pick_folder = pick_folder  # remplaçable : les tests n'ouvrent pas de vraie boîte de dialogue
        self._frame_folder: str | None = None

        bar = TitleBar(self)
        bar.setFixedHeight(40)
        self._title_bar = bar
        minimize = QToolButton(bar)
        minimize.setText("—")
        minimize.clicked.connect(self.showMinimized)
        close = QToolButton(bar)
        close.setObjectName("close")
        close.setText("✕")
        close.clicked.connect(self.close)
        self._tool_buttons = ((minimize, "window.minimize"), (close, "window.close"))
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

        # Boutons d'action sous l'état : au plus un visible à la fois (erreur pilote, ou mode inexact en flux).
        self._use_duplicate = self._button("action", self.use_duplicate_clicked.emit)
        self._add_resolution = self._button("action", self._on_add_resolution)
        self._use_duplicate.hide()
        self._add_resolution.hide()

        self._combos: dict[str, ChoiceCombo] = {
            "mode": ChoiceCombo(settings.MODES, _keyed(MODE_KEYS), self, MODE_ICONS),
            "position": ChoiceCombo(settings.POSITIONS, _keyed(POSITION_KEYS), self, POSITION_ICONS),
            "scale": ChoiceCombo(settings.SCALES, _scale_label, self),
            "encoder": ChoiceCombo(ENCODER_VALUES, _encoder_label, self),
            "language": ChoiceCombo(tuple(value for _name, value in LANGUAGE_ITEMS),
                                    lambda value, _lang: dict((v, n) for n, v in LANGUAGE_ITEMS)[value], self),
            "frame_interval": ChoiceCombo(settings.FRAME_INTERVALS, _interval_label, self,
                                          {value: INTERVAL_ICON for value in settings.FRAME_INTERVALS}),
            "frame_fit": ChoiceCombo(settings.FRAME_FITS, _keyed(FRAME_FIT_KEYS), self),
        }
        signals = {"mode": self.mode_changed, "position": self.position_changed, "scale": self.scale_changed,
                   "encoder": self.encoder_changed, "language": self.language_chosen,
                   "frame_interval": self.frame_interval_changed, "frame_fit": self.frame_fit_changed}
        for name, combo in self._combos.items():
            combo.activated.connect(lambda _i, name=name: self._on_choice(name, signals[name]))

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self._field_labels: list[tuple[QLabel, str]] = []
        self._labels_by_combo: dict[str, QLabel] = {}
        fields = (("mode", "window.mode"), ("position", "window.position"), ("scale", "window.scale"),
                  ("encoder", "window.encoder"), ("language", "window.language"))
        for row, (name, key) in enumerate(fields):
            label = QLabel(self)
            label.setObjectName("field")
            self._field_labels.append((label, key))
            self._labels_by_combo[name] = label
            form.addWidget(label, row, 0)
            form.addWidget(self._combos[name], row, 1)
        form.setColumnStretch(1, 1)
        form.setColumnMinimumWidth(0, LABEL_COLUMN_PX)

        # Groupe « Tableau » : dossier (chemin raccourci + bouton), intervalle, affichage.
        self._frame_title = QLabel(self)
        self._frame_title.setObjectName("group")
        self._frame_path = ElidedLabel(self)
        self._frame_path.setObjectName("folderPath")
        self._choose_folder = self._button("choose", self._on_choose_folder)
        self._choose_folder.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_choose_icon()
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self._frame_path, 1)
        folder_row.addWidget(self._choose_folder)
        frame_form = QGridLayout()
        frame_form.setHorizontalSpacing(12)
        frame_form.setVerticalSpacing(8)
        self._frame_field_labels: list[tuple[QLabel, str]] = []
        for row, (key, field) in enumerate((("window.frame_folder", folder_row),
                                            ("window.frame_interval", self._combos["frame_interval"]),
                                            ("window.frame_display", self._combos["frame_fit"]))):
            label = QLabel(self)
            label.setObjectName("field")
            self._frame_field_labels.append((label, key))
            frame_form.addWidget(label, row, 0)
            if isinstance(field, QHBoxLayout):
                frame_form.addLayout(field, row, 1)
            else:
                frame_form.addWidget(field, row, 1)
        frame_form.setColumnStretch(1, 1)
        frame_form.setColumnMinimumWidth(0, LABEL_COLUMN_PX)

        self._adjust = self._button("link", self.adjust_requested.emit)
        self._primary = self._button("primary", self.primary_clicked.emit)
        self._quit = self._button("secondary", self.quit_clicked.emit)

        body = QVBoxLayout()
        body.setContentsMargins(22, 4, 22, 20)
        body.setSpacing(6)
        body.addWidget(self._logo)
        body.addWidget(self._brand_title)
        body.addSpacing(8)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addStretch(1)
        status_row.addWidget(self._dot)
        status_row.addWidget(self._title)
        status_row.addStretch(1)
        body.addLayout(status_row)
        body.addWidget(self._detail)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._use_duplicate)
        actions.addWidget(self._add_resolution)
        actions.addStretch(1)
        body.addLayout(actions)
        body.addSpacing(6)
        body.addLayout(form)
        link_row = QHBoxLayout()
        link_row.addStretch(1)
        link_row.addWidget(self._adjust)
        body.addLayout(link_row)
        body.addSpacing(4)
        body.addWidget(self._frame_title)
        body.addLayout(frame_form)
        body.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self._primary, 3)
        buttons.addWidget(self._quit, 2)
        body.addLayout(buttons)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addLayout(body, 1)
        self.set_state(State.STOPPED, None)
        self.retranslate()
        i18n.language_changed.connect(self.retranslate)

    def _button(self, name: str, slot: Callable[[], None]) -> QPushButton:
        button = QPushButton(self)
        button.setObjectName(name)
        button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        button.clicked.connect(lambda _checked=False: slot())
        return button

    # --- mises à jour depuis le contrôleur ---

    def set_acrylic(self, enabled: bool) -> None:
        self._acrylic = enabled
        self.update()

    def set_state(self, state: State, detail: Msg | None) -> None:
        self._state = state
        self._detail_msg = detail
        self._stats = None
        if state is not State.STREAMING:
            self._inexact_size = None  # nouvelle session, tablette partie ou arrêt : le bouton n'a plus d'objet
        self._dot.set_color(status.COLORS[state])
        self._show_state()
        self._update_actions()

    def set_stats(self, stats: StreamStats) -> None:
        if self._state is State.STREAMING:
            self._stats = stats
            self._detail.setText(status.stream_detail(stats))

    def set_display_info(self, info: DisplayInfo) -> None:
        """The session's virtual screen is on; without an exact mode, offer to add the tablet's resolution."""
        self._inexact_size = None if info.exact else info.tablet_size
        self._update_actions()

    def retranslate(self) -> None:
        """Re-applies every visible text in the current language (connected to i18n.language_changed)."""
        lang = i18n.current_language()
        for button, key in self._tool_buttons:
            button.setToolTip(tr(key, lang))
        for label, key in self._field_labels + self._frame_field_labels:
            label.setText(tr(key, lang))
        self._frame_title.setText(tr("window.frame_group", lang))
        self._choose_folder.setText(tr("window.frame_choose", lang))
        self._refresh_frame_folder()
        for combo in self._combos.values():
            combo.retranslate()
        self._combos["language"].select(lang)  # sans signal : activated = clic
        self._adjust.setText(tr("window.adjust_in_windows", lang))
        self._adjust.setToolTip(tr("window.adjust_in_windows_tip", lang))
        self._quit.setText(tr("button.quit", lang))
        self._use_duplicate.setText(tr("button.use_duplicate", lang))
        self._add_resolution.setText(tr("button.add_resolution", lang))
        self._show_state()
        self._update_actions()

    def _show_state(self) -> None:
        lang = i18n.current_language()
        self._title.setText(status.title(self._state, lang))
        if self._stats is not None:
            self._detail.setText(status.stream_detail(self._stats))
        else:
            self._detail.setText(status.detail_for(self._state, self._detail_msg, lang))
        self._primary.setText(status.primary_label(self._state, lang))
        self._refresh_primary_icon()

    def _refresh_primary_icon(self) -> None:
        """The stop icon sits left of the text while the button means Stop; Start/Retry have none."""
        if status.is_active(self._state):
            self._primary.setIconSize(QSize(BUTTON_ICON_PX, BUTTON_ICON_PX))
            self._primary.setIcon(brand.icon(STOP_ICON, BUTTON_ICON_PX, self.devicePixelRatioF()))
        else:
            self._primary.setIcon(QIcon())

    def _refresh_choose_icon(self) -> None:
        """The folder-picker icon sits left of the « Choose… » text."""
        self._choose_folder.setIconSize(QSize(BUTTON_ICON_PX, BUTTON_ICON_PX))
        self._choose_folder.setIcon(brand.icon(CHOOSE_ICON, BUTTON_ICON_PX, self.devicePixelRatioF()))

    def _update_actions(self) -> None:
        vdd_missing = (self._state is State.ERROR and self._detail_msg is not None
                       and self._detail_msg.key == VDD_MISSING_KEY)
        self._use_duplicate.setVisible(vdd_missing)
        size = self._inexact_size
        if size is not None:
            self._add_resolution.setToolTip(tr("window.add_resolution_tip", i18n.current_language(),
                                               width=size[0], height=size[1]))
        self._add_resolution.setVisible(size is not None)

    def _on_add_resolution(self) -> None:
        size = self._inexact_size
        if size is None:
            return
        self._inexact_size = None  # une seule invite UAC par clic ; il revient à la prochaine session inexacte
        self._update_actions()
        self.add_resolution_clicked.emit(size[0], size[1])

    def _on_choice(self, name: str, signal) -> None:
        if name == "mode":
            self._update_layout_fields()
        signal.emit(self._combos[name].currentData())

    def _update_layout_fields(self) -> None:
        """Position and Scale only apply to the virtual screen (Extend)."""
        extend = self._combos["mode"].currentData() == "extend"
        for name in ("position", "scale"):
            self._combos[name].setEnabled(extend)
            self._labels_by_combo[name].setEnabled(extend)

    # --- réglages affichés (sans signal) ---

    def set_mode(self, value: str) -> None:
        self._combos["mode"].select(value)
        self._update_layout_fields()

    def set_position(self, value: str) -> None:
        self._combos["position"].select(value)

    def set_scale(self, value: str) -> None:
        self._combos["scale"].select(value)

    def set_encoder(self, value: str) -> None:
        self._combos["encoder"].select(value)

    def set_frame_folder(self, folder: str | None) -> None:
        self._frame_folder = folder or None
        self._refresh_frame_folder()

    def set_frame_interval(self, value: int) -> None:
        self._combos["frame_interval"].select(value)

    def set_frame_fit(self, value: str) -> None:
        self._combos["frame_fit"].select(value)

    def _refresh_frame_folder(self) -> None:
        empty = self._frame_folder is None
        text = tr("window.frame_no_folder", i18n.current_language()) if empty else self._frame_folder
        self._frame_path.set_full_text(text)
        self._frame_path.setToolTip("" if empty else text)
        self._frame_path.setProperty("empty", empty)
        self._frame_path.style().unpolish(self._frame_path)  # la règle [empty="true"] suit le changement
        self._frame_path.style().polish(self._frame_path)

    def _on_choose_folder(self) -> None:
        lang = i18n.current_language()
        start = self._frame_folder if self._frame_folder and os.path.isdir(self._frame_folder) else ""
        folder = self._pick_folder(self, tr("window.frame_choose_title", lang), start)
        if folder:  # vide : la boîte a été annulée
            self.frame_folder_chosen.emit(os.path.normpath(folder))

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

    def primary_has_icon(self) -> bool:
        return not self._primary.icon().isNull()

    def combo_item_has_icon(self, name: str, value: str) -> bool:
        combo = self._combos[name]
        return not combo.itemIcon(combo.findData(value)).isNull()

    def choose_has_icon(self) -> bool:
        return not self._choose_folder.icon().isNull()

    def quit_text(self) -> str:
        return self._quit.text()

    def adjust_text(self) -> str:
        return self._adjust.text()

    def field_labels(self) -> list[str]:
        return [label.text() for label, _key in self._field_labels]

    def frame_group_title(self) -> str:
        return self._frame_title.text()

    def frame_field_labels(self) -> list[str]:
        return [label.text() for label, _key in self._frame_field_labels]

    def frame_folder_text(self) -> str:
        """The whole text of the folder field (the placeholder when none), not its shortened display."""
        return self._frame_path.full_text()

    def frame_folder_display(self) -> str:
        return self._frame_path.text()

    def choose_folder_text(self) -> str:
        return self._choose_folder.text()

    def click_choose_folder(self) -> None:
        self._choose_folder.click()

    def tooltips(self) -> list[str]:
        return [button.toolTip() for button, _key in self._tool_buttons]

    def combo_items(self, name: str) -> list[tuple[str, str]]:
        combo = self._combos[name]
        return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]

    def selected(self, name: str) -> str:
        return self._combos[name].currentData()

    def is_enabled(self, name: str) -> bool:
        return self._combos[name].isEnabled() and self._labels_by_combo[name].isEnabled()

    def choose(self, name: str, value: str) -> None:
        combo = self._combos[name]
        index = combo.findData(value)
        combo.setCurrentIndex(index)
        combo.activated.emit(index)

    def choose_encoder(self, value: str) -> None:
        self.choose("encoder", value)

    def language_items(self) -> list[tuple[str, str]]:
        return self.combo_items("language")

    def selected_language(self) -> str:
        return self.selected("language")

    def choose_language(self, value: str) -> None:
        self.choose("language", value)

    def use_duplicate_visible(self) -> bool:
        return self._use_duplicate.isVisible()

    def use_duplicate_text(self) -> str:
        return self._use_duplicate.text()

    def add_resolution_visible(self) -> bool:
        return self._add_resolution.isVisible()

    def add_resolution_text(self) -> str:
        return self._add_resolution.text()

    def add_resolution_tooltip(self) -> str:
        return self._add_resolution.toolTip()

    def visible_controls(self) -> list[QWidget]:
        """Every visible label, list and button (the fit test checks none is squeezed or cut)."""
        kinds = (QLabel, QComboBox, QPushButton)
        return [w for w in self.findChildren(QWidget) if isinstance(w, kinds) and w.isVisible()
                and w.window() is self]

    # --- événements Qt ---

    def _refresh_logo(self) -> None:
        self._logo.setPixmap(brand.logo_pixmap(64, self.devicePixelRatioF()))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_logo()  # la fenêtre a pu s'ouvrir sur un écran d'une autre échelle
        for combo in self._combos.values():
            combo.refresh_icons()
        self._refresh_primary_icon()
        self._refresh_choose_icon()

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
