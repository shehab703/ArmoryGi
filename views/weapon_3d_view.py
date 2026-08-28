#!/usr/bin/env python3
"""
Professional 3D Weapon Viewer — immersive 3D presentation + full-width 2D media gallery.

Two presentation modes share a single tab (instant switching, nothing is torn down):

* ``3D Viewer`` — model-viewer (glTF/GLB/USDZ) with a Three.js fallback for CAD meshes.
* ``2D Gallery`` — full-width photo/lightbox with:
    - swipe navigation (mouse drag, touchscreen, trackpad two-finger swipe)
    - filmstrip thumbnails, prev/next buttons, wheel and keyboard navigation
    - RTL-aware direction (Arabic reading direction flips nav/swipe/arrows)
    - cursor-anchored zoom + pan, animated slide/fade transitions
    - slideshow, fullscreen presentation mode, drag & drop import
    - "set as primary image" persisted through ``db_manager.add_weapon_image``
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QFileDialog, QMessageBox, QFrame, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QStackedWidget, QListWidget, QListWidgetItem,
    QListView, QDialog, QApplication, QSizePolicy, QAbstractItemView, QButtonGroup
)
from PyQt6.QtCore import (
    Qt, QUrl, QTimer, QPointF, QRectF, QSize, QSizeF, QEvent, QEasingCurve,
    QPropertyAnimation, pyqtProperty, pyqtSignal
)
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QIcon, QImageReader, QPainter, QPen, QPixmap, QDesktopServices
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from utils.weapon_media_library import (
    DEFAULT_GALLERY_2D_EXTENSIONS,
    GALLERY_2D_EXTENSIONS_KEY,
    discover_gallery_images,
    discover_models,
    ensure_weapon_media_dirs,
    parse_image_extensions_csv,
    stage_gallery_image,
    weapon_media_root,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Gallery tuning
# --------------------------------------------------------------------------- #
GALLERY_MAX_DECODE_SIDE = 4096      # decode cap — avoids OOM on huge TIFFs
GALLERY_THUMB_SIDE = 168            # filmstrip thumbnail longest edge
SWIPE_THRESHOLD_PX = 48             # drag distance that counts as a swipe
SWIPE_RESIST_PX = 200               # max live rubber-band offset while dragging
SLIDE_DURATION_MS = 240
SLIDESHOW_INTERVAL_MS = 4000
GALLERY_ZOOM_MIN = 0.5
GALLERY_ZOOM_MAX = 8.0


# --------------------------------------------------------------------------- #
# Pure helpers (kept Qt-light so they can be unit tested without a display)
# --------------------------------------------------------------------------- #
def normalize_path(path: Any) -> str:
    """Absolute, symlink-free path text used for de-duplication."""
    try:
        return str(Path(str(path)).expanduser().resolve(strict=False))
    except (OSError, ValueError, RuntimeError):
        return str(path)


def collect_gallery_images(weapon: Optional[Dict], allowed_exts=None) -> List[str]:
    """Ordered gallery sources for a weapon: primary image, DB gallery, media folder.

    Duplicates are removed by normalized path, so an image that lives inside the
    weapon media folder and is also registered in the DB appears only once.
    """
    if allowed_exts is None:
        allowed_exts = parse_image_extensions_csv(DEFAULT_GALLERY_2D_EXTENSIONS)
    exts = {str(e).lower() for e in allowed_exts}
    data = dict(weapon) if isinstance(weapon, dict) else {}

    entries: List[tuple] = []

    def push(raw_path: Any, is_primary: bool = False) -> None:
        if not raw_path:
            return
        path = str(raw_path)
        if Path(path).suffix.lower() not in exts:
            return
        entries.append((path, bool(is_primary)))

    push(data.get("primary_image"), is_primary=True)
    rows = list(data.get("images") or [])
    try:
        rows.sort(key=lambda r: (int(r.get("display_order") or 0), str(r.get("image_path") or "")))
    except (TypeError, ValueError):
        pass
    for row in rows:
        if isinstance(row, dict):
            push(row.get("image_path"), is_primary=bool(row.get("is_primary")))
    if data:
        # Files dropped into the weapon media folder are part of the gallery too.
        try:
            for folder_path in discover_gallery_images(data, allowed_exts=exts):
                push(folder_path)
        except OSError:
            logger.debug("Gallery folder scan failed for %s", data.get("model"), exc_info=True)

    ordered: List[str] = []
    index_by_key: Dict[str, int] = {}
    for path, is_primary in entries:
        key = normalize_path(path).lower()
        if key in index_by_key:
            # Keep a single entry, but let a flagged primary lead the list.
            position = index_by_key[key]
            if is_primary and position != 0:
                ordered.insert(0, ordered.pop(position))
                for i, existing in enumerate(ordered):
                    index_by_key[normalize_path(existing).lower()] = i
            continue
        index_by_key[key] = len(ordered)
        ordered.append(path)
    return ordered


def load_scaled_pixmap(path: str, max_side: int = GALLERY_MAX_DECODE_SIDE) -> Optional[QPixmap]:
    """Decode an image, capped at ``max_side`` pixels, honouring EXIF orientation."""
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    try:
        reader = QImageReader(str(file_path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            longest = max(size.width(), size.height())
            if longest > max_side and longest > 0:
                factor = float(max_side) / float(longest)
                reader.setScaledSize(QSize(max(1, int(size.width() * factor)),
                                           max(1, int(size.height() * factor))))
        image = reader.read()
        if image is None or image.isNull():
            image = QImageReader(str(file_path)).read()
        if image is None or image.isNull():
            return None
        return QPixmap.fromImage(image)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Stage: the full-width image canvas (paint-based, so it needs no WebEngine)
# --------------------------------------------------------------------------- #
class _GalleryStage(QWidget):
    """Full-width image canvas with swipe/drag panning, cursor-anchored zoom,
    slide+fade transition animation and key forwarding to the owning gallery."""

    navigate_requested = pyqtSignal(int)     # -1 previous, +1 next (already RTL-mapped)
    wheel_navigate = pyqtSignal(int)         # raw wheel direction, RTL-mapped by panel
    swipe_flick = pyqtSignal(float)          # horizontal drag delta in pixels
    zoom_changed = pyqtSignal(float)
    key_pressed = pyqtSignal(int)            # Qt.Key value the panel should act on
    double_clicked = pyqtSignal()

    _FORWARDED_KEYS = frozenset({
        Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
        Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Comma, Qt.Key.Key_Period,
        Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore,
        Qt.Key.Key_0, Qt.Key.Key_Space, Qt.Key.Key_F, Qt.Key.Key_Z, Qt.Key.Key_P,
        Qt.Key.Key_Escape,
    })

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("weaponGalleryStage")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(240)

        self._pixmap: Optional[QPixmap] = None
        self._empty_message = ""
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._slide = 0.0
        self._fade = 1.0

        self._press_point: Optional[QPointF] = None
        self._press_pan = QPointF(0.0, 0.0)
        self._drag_active = False
        self._drag_moved = False
        self._wheel_accum = 0.0

        self._slide_anim = QPropertyAnimation(self, b"slide", self)
        self._slide_anim.setDuration(SLIDE_DURATION_MS)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim = QPropertyAnimation(self, b"fade", self)
        self._fade_anim.setDuration(SLIDE_DURATION_MS + 90)
        self._fade_anim.setStartValue(0.15)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)

    # -- animatable properties ------------------------------------------------
    def _get_slide(self) -> float:
        return self._slide

    def _set_slide(self, value: float) -> None:
        self._slide = float(value)
        self.update()

    slide = pyqtProperty(float, _get_slide, _set_slide)

    def _get_fade(self) -> float:
        return self._fade

    def _set_fade(self, value: float) -> None:
        self._fade = max(0.0, min(1.0, float(value)))
        self.update()

    fade = pyqtProperty(float, _get_fade, _set_fade)

    # -- state ----------------------------------------------------------------
    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def is_zoomed(self) -> bool:
        return self._zoom > 1.0 + 1e-3

    def zoom_factor(self) -> float:
        return self._zoom

    def set_empty_message(self, text: str) -> None:
        self._empty_message = text or ""
        self._pixmap = None
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def set_pixmap(self, pixmap: Optional[QPixmap], enter_from: int = 0) -> None:
        """Show ``pixmap``; ``enter_from`` (+1 right, -1 left) plays the slide-in."""
        if pixmap is None or pixmap.isNull():
            self.set_empty_message(self._empty_message)
            return
        self._pixmap = pixmap
        if enter_from:
            span = max(180.0, self.width() * 0.5)
            self._set_slide(enter_from * span)
            self._set_fade(0.15)
            self._slide_anim.stop()
            self._slide_anim.setStartValue(self._slide)
            self._slide_anim.setEndValue(0.0)
            self._slide_anim.start()
            self._fade_anim.stop()
            self._fade_anim.start()
        else:
            self._slide_anim.stop()
            self._fade_anim.stop()
            self._set_slide(0.0)
            self._set_fade(1.0)
        self._clamp_pan()
        self.update()

    def set_slide_rest(self) -> None:
        """Snap the rubber-band drag offset back to zero."""
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide)
        self._slide_anim.setEndValue(0.0)
        self._slide_anim.setDuration(170)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._slide_anim.start()

    # -- zoom -----------------------------------------------------------------
    def zoom_by(self, factor: float) -> None:
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        self.zoom_at(center, factor)

    def zoom_at(self, pivot: QPointF, factor: float) -> None:
        old = self._zoom
        new = max(GALLERY_ZOOM_MIN, min(GALLERY_ZOOM_MAX, old * factor))
        if abs(new - old) < 1e-6:
            return
        ux = pivot.x() - self.width() / 2.0
        uy = pivot.y() - self.height() / 2.0
        k = new / old
        self._pan = QPointF(ux - (ux - self._pan.x()) * k, uy - (uy - self._pan.y()) * k)
        self._zoom = new
        self._clamp_pan()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def fit(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.zoom_changed.emit(self._zoom)
        self.update()

    def _clamp_pan(self) -> None:
        base = self._fit_rect()
        if base.isNull() or not self.has_image():
            self._pan = QPointF(0.0, 0.0)
            return
        width = base.width() * self._zoom
        height = base.height() * self._zoom
        max_x = max(0.0, (width - self.width()) / 2.0 + 28.0)
        max_y = max(0.0, (height - self.height()) / 2.0 + 28.0)
        self._pan = QPointF(
            max(-max_x, min(max_x, self._pan.x())),
            max(-max_y, min(max_y, self._pan.y())),
        )

    # -- geometry -------------------------------------------------------------
    def _fit_rect(self) -> QRectF:
        if not self.has_image():
            return QRectF()
        avail = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        if avail.width() <= 1 or avail.height() <= 1:
            return QRectF()
        scaled = QSizeF(float(self._pixmap.width()), float(self._pixmap.height())).scaled(
            QSizeF(avail.width(), avail.height()), Qt.AspectRatioMode.KeepAspectRatio
        )
        if scaled.width() <= 0 or scaled.height() <= 0:
            return QRectF()
        x = avail.x() + (avail.width() - scaled.width()) / 2.0
        y = avail.y() + (avail.height() - scaled.height()) / 2.0
        return QRectF(x, y, scaled.width(), scaled.height())

    # -- painting -------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#060e1a"))
        self._paint_backdrop(painter)
        if not self.has_image():
            self._paint_empty_state(painter)
            painter.end()
            return
        base = self._fit_rect()
        if base.isNull():
            painter.end()
            return
        width = base.width() * self._zoom
        height = base.height() * self._zoom
        center_x = self.width() / 2.0 + self._pan.x() + self._slide
        center_y = self.height() / 2.0 + self._pan.y()
        target = QRectF(center_x - width / 2.0, center_y - height / 2.0, width, height)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._zoom < 2.5)
        painter.setOpacity(self._fade)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        painter.setOpacity(1.0)
        painter.setPen(QPen(QColor("#1e3652"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target)
        painter.restore()
        if self.is_zoomed():
            self._paint_zoom_badge(painter)

    def _paint_backdrop(self, painter: QPainter) -> None:
        painter.save()
        rect = self.rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(88, 168, 255, 14))
        radius = min(rect.width(), rect.height()) * 0.42
        painter.drawEllipse(QPointF(rect.center()), radius, radius)
        pen = QPen(QColor(30, 54, 82, 42))
        pen.setWidth(1)
        painter.setPen(pen)
        step = 46
        x = step
        while x < rect.width():
            painter.drawLine(int(x), 0, int(x), int(rect.height()))
            x += step
        y = step
        while y < rect.height():
            painter.drawLine(0, int(y), int(rect.width()), int(y))
            y += step
        painter.restore()

    def _paint_empty_state(self, painter: QPainter) -> None:
        rect = self.rect()
        painter.setPen(QColor("#4a7099"))
        font = QFont(self.font())
        font.setPointSizeF(max(13.0, font.pointSizeF() + 3.0))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._empty_message or "—")

    def _paint_zoom_badge(self, painter: QPainter) -> None:
        text = f"{int(round(self._zoom * 100))}%"
        painter.save()
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(9.0, font.pointSizeF() - 1.0))
        painter.setFont(font)
        metrics_rect = painter.fontMetrics().boundingRect(text)
        box = QRectF(self.rect().right() - metrics_rect.width() - 30,
                     self.rect().top() + 12,
                     metrics_rect.width() + 20,
                     metrics_rect.height() + 12)
        painter.setPen(QPen(QColor("#2a4f75"), 1))
        painter.setBrush(QColor(8, 22, 36, 210))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor("#8ad8ff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    # -- input: mouse / touch (Qt emulates mouse for single-finger touch) -----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.has_image():
            self._press_point = event.position()
            self._press_pan = QPointF(self._pan)
            self._drag_active = True
            self._drag_moved = False
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            if self.is_zoomed():
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and self._press_point is not None:
            delta = event.position() - self._press_point
            if abs(delta.x()) + abs(delta.y()) > 4:
                self._drag_moved = True
            if self.is_zoomed():
                self._pan = self._press_pan + QPointF(delta.x(), delta.y())
                self._clamp_pan()
            else:
                # rubber-band swipe feedback, soft-clamped
                raw = delta.x()
                limit = float(SWIPE_RESIST_PX)
                self._slide = max(-limit, min(limit, raw * 0.75))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._drag_active:
            super().mouseReleaseEvent(event)
            return
        self._drag_active = False
        self.unsetCursor()
        dx = 0.0
        if self._press_point is not None:
            dx = event.position().x() - self._press_point.x()
        self._press_point = None
        if not self._drag_moved:
            self.set_slide_rest()
            event.accept()
            return
        if self.is_zoomed():
            self._set_slide(0.0)
            event.accept()
            return
        if abs(dx) >= SWIPE_THRESHOLD_PX:
            self.swipe_flick.emit(dx)
        else:
            self.set_slide_rest()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.has_image():
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if not self.has_image():
            event.ignore()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = event.angleDelta().y() or event.pixelDelta().y()
            self.zoom_at(event.position(), 1.2 if dy > 0 else 1 / 1.2)
            event.accept()
            return
        dy = event.angleDelta().y()
        if dy == 0:
            dy = event.pixelDelta().y()
        if not dy:
            event.ignore()
            return
        self._wheel_accum += float(dy)
        stepped = False
        while abs(self._wheel_accum) >= 120.0:
            step = 1 if self._wheel_accum > 0 else -1
            self._wheel_accum -= step * 120.0
            self.wheel_navigate.emit(step)
            stepped = True
        if not stepped:
            self._wheel_accum *= 0.6
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key in self._FORWARDED_KEYS:
            self.key_pressed.emit(int(key))
            event.accept()
            return
        super().keyPressEvent(event)

    def event(self, event):
        """Trackpad/touchpad gestures: two-finger swipe navigates, pinch zooms."""
        try:
            if event.type() == QEvent.Type.NativeGesture:
                gesture = event.gestureType()
                if gesture == Qt.NativeGestureType.ZoomGesture:
                    value = float(event.value())
                    if abs(value) > 1e-4:
                        self.zoom_at(QPointF(self.rect().center()), 1.0 + value)
                        return True
                if gesture == Qt.NativeGestureType.SwipeGesture:
                    direction = event.swipeDirection()
                    if direction in (Qt.SwipeDirection.LeftSwipe, Qt.SwipeDirection.RightSwipe):
                        self.swipe_flick.emit(
                            -2.0 * SWIPE_THRESHOLD_PX if direction == Qt.SwipeDirection.LeftSwipe
                            else 2.0 * SWIPE_THRESHOLD_PX
                        )
                        return True
        except (AttributeError, RuntimeError, ValueError):
            pass
        return super().event(event)

    def resizeEvent(self, event):
        self._clamp_pan()
        self.update()
        super().resizeEvent(event)


# --------------------------------------------------------------------------- #
# Gallery panel: chrome around the stage (bars, filmstrip, actions)
# --------------------------------------------------------------------------- #
class _WeaponGalleryPanel(QWidget):
    """Full-width 2D weapon media gallery with navigation and lightbox actions."""

    primary_image_changed = pyqtSignal(int)

    def __init__(self, db_manager=None, settings=None, lang_manager=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.settings = settings
        self.lang_manager = lang_manager
        self.weapon: Optional[Dict] = None
        self.image_paths: List[str] = []
        self.index = 0
        self._home_layout = None
        self._fs_dialog: Optional[QDialog] = None
        self._leaving_fullscreen = False
        self._filmstrip_updating = False
        self._init_ui()

        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.setInterval(SLIDESHOW_INTERVAL_MS)
        self._slideshow_timer.timeout.connect(lambda: self.navigate(1))

    # -- UI -------------------------------------------------------------------
    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # Top bar: counter + filename + zoom tools
        top = QFrame()
        top.setObjectName("galleryTopBar")
        top.setStyleSheet("QFrame#galleryTopBar{background:#081221;border:1px solid #1e3652;border-radius:10px;padding:6px 10px;}")
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(4, 2, 4, 2)
        top_row.setSpacing(8)

        self.counter_label = QLabel("— / —")
        self.counter_label.setStyleSheet("font-size:12pt;font-weight:700;color:#7fd4ff;")
        top_row.addWidget(self.counter_label)

        self.file_label = QLabel("")
        self.file_label.setStyleSheet("font-size:10pt;color:#7aa8d4;")
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        top_row.addWidget(self.file_label, 1)

        self.zoom_out_btn = self._tool_button("−", "تصغير / Zoom out")
        self.zoom_out_btn.clicked.connect(lambda: self.stage.zoom_by(1 / 1.25))
        top_row.addWidget(self.zoom_out_btn)

        self.zoom_reset_btn = self._tool_button("ملاءمة", "ملاءمة العرض / Fit")
        self.zoom_reset_btn.clicked.connect(self.stage_fit)
        top_row.addWidget(self.zoom_reset_btn)

        self.zoom_in_btn = self._tool_button("+", "تكبير / Zoom in")
        self.zoom_in_btn.clicked.connect(lambda: self.stage.zoom_by(1.25))
        top_row.addWidget(self.zoom_in_btn)

        self.btn_exit_fullscreen = self._tool_button("✕ ملء الشاشة", "إنهاء العرض الكامل (Esc)")
        self.btn_exit_fullscreen.clicked.connect(self._leave_fullscreen)
        self.btn_exit_fullscreen.setVisible(False)
        top_row.addWidget(self.btn_exit_fullscreen)
        root.addWidget(top)

        # The stage (full width, grows)
        self.stage = _GalleryStage(self)
        self.stage.navigate_requested.connect(self.navigate)
        self.stage.wheel_navigate.connect(self._on_wheel_navigate)
        self.stage.swipe_flick.connect(self._on_swipe_flick)
        self.stage.zoom_changed.connect(self._on_zoom_changed)
        self.stage.key_pressed.connect(self._on_stage_key)
        self.stage.double_clicked.connect(self.toggle_fullscreen)
        self.stage.set_empty_message("لا توجد صور في المعرض")
        self.stage.setToolTip(
            "اختصارات: سحب بالماوس/اللمس للتنقل • ←/→ • ,/. • Home/End • "
            "+/- تكبير/تصغير • 0 ملاءمة • مسافة عرض تلقائي • F ملء الشاشة • P تعيين كرئيسية"
        )
        root.addWidget(self.stage, 1)

        # Filmstrip thumbnails
        self.filmstrip = QListWidget(self)
        self.filmstrip.setObjectName("galleryFilmstrip")
        self.filmstrip.setViewMode(QListView.ViewMode.IconMode)
        self.filmstrip.setFlow(QListView.Flow.LeftToRight)
        self.filmstrip.setWrapping(False)
        self.filmstrip.setResizeMode(QListView.ResizeMode.Adjust)
        self.filmstrip.setMovement(QListView.Movement.Static)
        self.filmstrip.setIconSize(QSize(120, 80))
        self.filmstrip.setSpacing(6)
        self.filmstrip.setUniformItemSizes(True)
        self.filmstrip.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.filmstrip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.filmstrip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.filmstrip.setFixedHeight(112)
        self.filmstrip.setVisible(False)
        self.filmstrip.setStyleSheet(
            "QListWidget#galleryFilmstrip{background:#0a1525;border:1px solid #1e3652;border-radius:10px;padding:6px;}"
            "QListWidget#galleryFilmstrip::item{border:1px solid transparent;border-radius:8px;padding:2px;color:#7aa8d4;}"
            "QListWidget#galleryFilmstrip::item:selected{background:#0d3a6e;border:1px solid #58a8ff;}"
            "QListWidget#galleryFilmstrip::item:hover{border:1px solid #2a4f75;}"
        )
        self.filmstrip.itemClicked.connect(self._on_filmstrip_clicked)
        root.addWidget(self.filmstrip)

        # Bottom navigation bar
        bottom = QFrame()
        bottom.setObjectName("galleryBottomBar")
        bottom.setStyleSheet("QFrame#galleryBottomBar{background:#081221;border:1px solid #1e3652;border-radius:10px;padding:6px 10px;}")
        nav_row = QHBoxLayout(bottom)
        nav_row.setContentsMargins(4, 2, 4, 2)
        nav_row.setSpacing(8)

        self.prev_btn = self._nav_button("السابق", "الصورة السابقة (→ في العربية / ← في الإنجليزية)")
        self.prev_btn.clicked.connect(lambda: self.navigate(-1))
        nav_row.addWidget(self.prev_btn)

        self.next_btn = self._nav_button("التالي", "الصورة التالية (← في العربية / → في الإنجليزية)")
        self.next_btn.clicked.connect(lambda: self.navigate(1))
        nav_row.addWidget(self.next_btn)

        self.count_badge = QLabel("0 صورة")
        self.count_badge.setStyleSheet("font-size:10pt;color:#6f92b8;padding:0 8px;")
        nav_row.addWidget(self.count_badge)

        nav_row.addStretch(1)

        self.slideshow_btn = self._nav_button("عرض تلقائي", "تشغيل/إيقاف العرض التلقائي (مسافة)")
        self.slideshow_btn.setCheckable(True)
        self.slideshow_btn.clicked.connect(self._toggle_slideshow)
        nav_row.addWidget(self.slideshow_btn)

        self.primary_btn = self._nav_button("تعيين كصورة رئيسية", "حفظ الصورة الحالية كالصورة الرئيسية للسلاح")
        self.primary_btn.clicked.connect(self._set_as_primary)
        nav_row.addWidget(self.primary_btn)

        self.add_btn = self._nav_button("+ إضافة صور", "إضافة صور إلى المعرض (يمكن السحب والإفلات هنا)")
        self.add_btn.clicked.connect(self._add_images)
        nav_row.addWidget(self.add_btn)

        self.folder_btn = self._nav_button("مجلد الوسائط", "فتح مجلد وسائط هذا السلاح")
        self.folder_btn.clicked.connect(self._open_media_folder)
        nav_row.addWidget(self.folder_btn)

        self.fullscreen_btn = self._nav_button("ملء الشاشة", "عرض كامل النافذة (F)")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        nav_row.addWidget(self.fullscreen_btn)

        self.reload_btn = self._nav_button("تحديث", "إعادة فحص ملفات ومعرض الصور")
        self.reload_btn.clicked.connect(self.reload)
        nav_row.addWidget(self.reload_btn)

        root.addWidget(bottom)

        self._apply_layout_direction()
        self.setAcceptDrops(True)

    def _tool_button(self, text: str, tip: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QToolButton{color:#aaddff;background:#142b45;border:1px solid #2a4f75;border-radius:8px;padding:4px 10px;font-size:10pt;}"
            "QToolButton:hover{border:1px solid #58a8ff;color:#7fd4ff;}"
        )
        return button

    def _nav_button(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton{font-weight:600;background:#142b45;color:#aaddff;border:1px solid #2a4f75;"
            "border-radius:8px;padding:7px 12px;min-height:30px;}"
            "QPushButton:hover{border:1px solid #58a8ff;color:#7fd4ff;background:#0d3a6e;}"
            "QPushButton:checked{background:#0d3a6e;color:#8ad8ff;border:1px solid #58a8ff;}"
            "QPushButton:disabled{color:#41617f;border-color:#1b2f45;background:#0d1a2b;}"
        )
        return button

    # -- language / direction --------------------------------------------------
    def _is_arabic(self) -> bool:
        manager = self.lang_manager
        return bool(manager is not None and hasattr(manager, "is_arabic") and manager.is_arabic())

    def _tr(self, text: str) -> str:
        if self.lang_manager is not None and hasattr(self.lang_manager, "tr"):
            try:
                return self.lang_manager.tr(text)
            except Exception:
                return text
        return text

    def _apply_layout_direction(self) -> None:
        rtl = self._is_arabic()
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
        # Arrow glyphs follow the reading direction; logical order stays prev → next.
        self.prev_btn.setText("السابق ›" if rtl else "‹ السابق")
        self.next_btn.setText("‹ التالي" if rtl else "التالي ›")

    def set_language_manager(self, lang_manager) -> None:
        self.lang_manager = lang_manager
        self._apply_layout_direction()

    def set_home_layout(self, layout) -> None:
        """Layout the panel returns to when leaving fullscreen."""
        self._home_layout = layout

    # -- data -----------------------------------------------------------------
    def allowed_extensions(self) -> set:
        if self.settings is None:
            return parse_image_extensions_csv(DEFAULT_GALLERY_2D_EXTENSIONS)
        try:
            raw = self.settings.value(GALLERY_2D_EXTENSIONS_KEY, DEFAULT_GALLERY_2D_EXTENSIONS, str)
        except TypeError:
            raw = self.settings.value(GALLERY_2D_EXTENSIONS_KEY, DEFAULT_GALLERY_2D_EXTENSIONS)
        return parse_image_extensions_csv(raw)

    def load_weapon(self, weapon: Optional[Dict]) -> None:
        self._stop_slideshow()
        self.weapon = dict(weapon) if isinstance(weapon, dict) else None
        self.reload()

    def reload(self) -> None:
        weapon = self.weapon or {}
        if weapon:
            try:
                ensure_weapon_media_dirs(weapon)
            except OSError:
                logger.debug("Could not prepare the weapon media folder", exc_info=True)
        current_path = self.image_paths[self.index] if self.image_paths and 0 <= self.index < len(self.image_paths) else None
        self.image_paths = collect_gallery_images(weapon, self.allowed_extensions())
        if current_path and current_path in self.image_paths:
            self.index = self.image_paths.index(current_path)
        else:
            self.index = 0
        self._rebuild_filmstrip()
        self.show_current(0)

    def image_count(self) -> int:
        return len(self.image_paths)

    # -- rendering ------------------------------------------------------------
    def show_current(self, direction: int = 0) -> None:
        if not self.image_paths:
            self.stage.set_pixmap(None)
            self.stage.set_empty_message(
                "لا توجد صور لهذا السلاح — اضغط \"+ إضافة صور\" أو اسحب الصور إلى هنا"
                if self.weapon else "اختر سلاحًا لعرض معرض صوره"
            )
            self.counter_label.setText("— / —")
            self.file_label.setText("")
            self.count_badge.setText("0 صورة")
            self._update_enabled_state()
            return
        self.index = max(0, min(self.index, len(self.image_paths) - 1))
        path = self.image_paths[self.index]
        pixmap = load_scaled_pixmap(path, GALLERY_MAX_DECODE_SIDE)
        if pixmap is None or pixmap.isNull():
            self.stage.set_empty_message(f"تعذّر تحميل الصورة:\n{path}")
            self.file_label.setText(Path(path).name)
        else:
            self.stage.set_pixmap(pixmap, direction)
            self.file_label.setText(f"{Path(path).name}  •  {pixmap.width()}×{pixmap.height()}")
        self.counter_label.setText(f"{self.index + 1} / {len(self.image_paths)}")
        self.count_badge.setText(f"{len(self.image_paths)} صورة في المعرض")
        self._sync_filmstrip_selection()
        self._update_enabled_state()

    def navigate(self, delta: int) -> None:
        if not self.image_paths or delta == 0:
            return
        total = len(self.image_paths)
        self.index = (self.index + delta) % total
        self.show_current(self._visual_direction(delta))

    def go_to(self, index: int) -> None:
        if not self.image_paths:
            return
        index = max(0, min(index, len(self.image_paths) - 1))
        delta = index - self.index
        self.index = index
        self.show_current(self._visual_direction(1 if delta >= 0 else -1))

    def _visual_direction(self, delta: int) -> int:
        """Where the incoming image slides in from: +1 right, -1 left (RTL aware)."""
        rtl = self._is_arabic()
        return 1 if bool(delta > 0) != rtl else -1

    def stage_fit(self) -> None:
        self.stage.fit()

    def _on_zoom_changed(self, factor: float) -> None:
        self.zoom_reset_btn.setText("ملاءمة" if factor <= 1.0 + 1e-3 else f"{int(round(factor * 100))}%")

    # -- input adapters --------------------------------------------------------
    def _on_wheel_navigate(self, step: int) -> None:
        # Vertical scrolling is reading-direction agnostic: wheel down advances.
        self.navigate(-step)

    def _on_swipe_flick(self, dx: float) -> None:
        rtl = self._is_arabic()
        if abs(dx) < SWIPE_THRESHOLD_PX:
            self.stage.set_slide_rest()
            return
        # Dragging towards the "next page" direction (left in LTR, right in RTL) advances.
        self.navigate(1 if bool(dx > 0) == rtl else -1)

    def _on_stage_key(self, key: int) -> None:
        qkey = Qt.Key(key)
        rtl = self._is_arabic()
        next_key = Qt.Key.Key_Left if rtl else Qt.Key.Key_Right
        prev_key = Qt.Key.Key_Right if rtl else Qt.Key.Key_Left
        if qkey in (next_key, Qt.Key.Key_Period, Qt.Key.Key_Down):
            self.navigate(1)
        elif qkey in (prev_key, Qt.Key.Key_Comma, Qt.Key.Key_Up):
            self.navigate(-1)
        elif qkey == Qt.Key.Key_Home:
            self.go_to(0)
        elif qkey == Qt.Key.Key_End:
            self.go_to(len(self.image_paths) - 1)
        elif qkey in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.stage.zoom_by(1.25)
        elif qkey in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.stage.zoom_by(1 / 1.25)
        elif qkey == Qt.Key.Key_0:
            self.stage.fit()
        elif qkey == Qt.Key.Key_Space:
            self._toggle_slideshow(self.slideshow_btn.isChecked())
        elif qkey == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif qkey == Qt.Key.Key_P:
            self._set_as_primary()
        elif qkey == Qt.Key.Key_Escape:
            if self._fs_dialog is not None:
                self._leave_fullscreen()
        else:
            self.stage.set_slide_rest()

    def keyPressEvent(self, event):
        self._on_stage_key(int(event.key()))

    # -- filmstrip -------------------------------------------------------------
    def _rebuild_filmstrip(self) -> None:
        self._filmstrip_updating = True
        self.filmstrip.clear()
        for i, path in enumerate(self.image_paths):
            item = QListWidgetItem(self.filmstrip)
            item.setText(f"{i + 1}")
            item.setToolTip(Path(path).name)
            item.setSizeHint(QSize(136, 100))
            thumb = load_scaled_pixmap(path, GALLERY_THUMB_SIDE)
            if thumb is not None and not thumb.isNull():
                item.setIcon(QIcon(thumb))
            self.filmstrip.addItem(item)
        self.filmstrip.setVisible(len(self.image_paths) > 1)
        self._filmstrip_updating = False
        self._sync_filmstrip_selection()

    def _sync_filmstrip_selection(self) -> None:
        if self._filmstrip_updating:
            return
        self.filmstrip.blockSignals(True)
        if self.image_paths:
            self.filmstrip.setCurrentRow(self.index)
            current = self.filmstrip.currentItem()
            if current is not None:
                self.filmstrip.scrollToItem(current)
        self.filmstrip.blockSignals(False)

    def _on_filmstrip_clicked(self, item: QListWidgetItem) -> None:
        if self._filmstrip_updating:
            return
        self.go_to(self.filmstrip.row(item))

    def _update_enabled_state(self) -> None:
        has_images = bool(self.image_paths)
        multiple = len(self.image_paths) > 1
        for button in (self.prev_btn, self.next_btn):
            button.setEnabled(multiple)
        for button in (self.zoom_in_btn, self.zoom_out_btn, self.zoom_reset_btn):
            button.setEnabled(has_images)
        for button in (self.primary_btn, self.fullscreen_btn, self.slideshow_btn):
            button.setEnabled(has_images)
        if not multiple:
            self._stop_slideshow()

    # -- actions ---------------------------------------------------------------
    def _toggle_slideshow(self, checked: bool) -> None:
        if checked and len(self.image_paths) > 1:
            self._slideshow_timer.start()
            self.slideshow_btn.setText("إيقاف العرض")
        else:
            self._stop_slideshow()

    def _stop_slideshow(self) -> None:
        self._slideshow_timer.stop()
        if hasattr(self, "slideshow_btn"):
            self.slideshow_btn.setChecked(False)
            self.slideshow_btn.setText("عرض تلقائي")

    def _set_as_primary(self) -> None:
        if not self.image_paths or not self.weapon:
            return
        path = self.image_paths[self.index]
        weapon_id = self.weapon.get("id")
        if not weapon_id or self.db is None or not hasattr(self.db, "add_weapon_image"):
            QMessageBox.information(
                self, self._tr("Gallery"),
                "لا يمكن حفظ الصورة الرئيسية: لم يتم تحديد السلاح أو قاعدة البيانات غير متاحة."
            )
            return
        try:
            saved = bool(self.db.add_weapon_image(int(weapon_id), path, is_primary=True))
        except Exception as exc:  # keep the gallery usable if persistence fails
            QMessageBox.warning(self, self._tr("Gallery"), f"فشل حفظ الصورة الرئيسية:\n{exc}")
            return
        if not saved:
            QMessageBox.warning(self, self._tr("Gallery"), "فشل حفظ الصورة الرئيسية.")
            return
        self.weapon["primary_image"] = path
        self.image_paths = collect_gallery_images(self.weapon, self.allowed_extensions())
        if path in self.image_paths:
            self.index = self.image_paths.index(path)
        self._rebuild_filmstrip()
        self.show_current(0)
        self.file_label.setText(self._tr("الصورة الرئيسية المحدّثة") + f"  •  {Path(path).name}")
        self.primary_image_changed.emit(int(weapon_id))

    def _add_images(self) -> None:
        if not self.weapon:
            QMessageBox.information(self, self._tr("Gallery"), self._tr("Please select a weapon first."))
            return
        filters = " ".join(f"*{ext}" for ext in sorted(self.allowed_extensions()))
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._tr("Add gallery images"), str(Path.home()), f"Images ({filters})"
        )
        if not paths:
            return
        self._import_paths(paths)

    def _import_paths(self, paths: List[str]) -> int:
        weapon = self.weapon or {}
        weapon_id = weapon.get("id")
        has_primary = bool(weapon.get("primary_image"))
        added = 0
        for raw in paths:
            try:
                staged = stage_gallery_image(weapon, raw)
            except OSError:
                logger.debug("Could not stage %s into the media folder", raw, exc_info=True)
                staged = raw
            if weapon_id and self.db is not None and hasattr(self.db, "add_weapon_image"):
                try:
                    ok = bool(self.db.add_weapon_image(int(weapon_id), staged, is_primary=not has_primary))
                    has_primary = has_primary or ok
                    added += 1 if ok else 0
                    continue
                except Exception:
                    pass
            self.weapon = dict(weapon)
            images = list(self.weapon.get("images") or [])
            images.append({"image_path": staged})
            self.weapon["images"] = images
            added += 1
        self.reload()
        if weapon_id and added and self.db is not None:
            self.primary_image_changed.emit(int(weapon_id))
        if not added:
            QMessageBox.information(self, self._tr("Gallery"), "لم تتم إضافة أي صورة صالحة.")
        return added

    def _open_media_folder(self) -> None:
        if not self.weapon:
            return
        try:
            root = weapon_media_root(self.weapon)
        except OSError:
            logger.debug("Could not resolve the weapon media root", exc_info=True)
            return
        if not root.exists():
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))):
            QMessageBox.information(self, self._tr("Gallery"), str(root))

    # -- drag & drop ------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if self.weapon and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        exts = self.allowed_extensions()
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local and Path(local).suffix.lower() in exts:
                paths.append(local)
        if paths:
            event.acceptProposedAction()
            self._import_paths(paths)

    # -- fullscreen lightbox -----------------------------------------------------
    def toggle_fullscreen(self) -> None:
        if self._fs_dialog is not None:
            self._leave_fullscreen()
            return
        # Never parent the dialog to the panel itself: that would create a widget
        # cycle as soon as the panel is re-parented into the dialog below.
        candidate = self.window()
        dialog = QDialog(None if candidate is self or candidate is None else candidate)
        dialog.setObjectName("galleryFullscreenDialog")
        dialog.setWindowTitle(self._tr("2D Gallery"))
        dialog.setStyleSheet("QDialog#galleryFullscreenDialog{background:#040b14;}")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        dialog.setMouseTracking(True)
        self.setParent(dialog)
        layout.addWidget(self)
        dialog.finished.connect(self._leave_fullscreen)
        self._fs_dialog = dialog
        try:
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            if screen is not None:
                dialog.setScreen(screen)
        except (AttributeError, RuntimeError):
            pass
        self.btn_exit_fullscreen.setVisible(True)
        dialog.showFullScreen()
        dialog.setFocus()
        self.stage.setFocus(Qt.FocusReason.OtherFocusReason)
        self.stage.update()

    def _leave_fullscreen(self) -> None:
        if self._fs_dialog is None or self._leaving_fullscreen:
            return
        self._leaving_fullscreen = True
        dialog = self._fs_dialog
        self._fs_dialog = None
        try:
            self.btn_exit_fullscreen.setVisible(False)
        except RuntimeError:
            pass
        if self._home_layout is not None:
            self._home_layout.addWidget(self)
        else:
            self.setParent(None)
        try:
            dialog.blockSignals(True)
            dialog.hide()
            dialog.deleteLater()
        except RuntimeError:
            pass
        self._leaving_fullscreen = False
        self.stage.update()


# --------------------------------------------------------------------------- #
# The 3D tab itself
# --------------------------------------------------------------------------- #
class Weapon3DView(QWidget):
    """Dedicated professional weapon presentation tab: 3D viewer + 2D gallery."""

    primary_image_changed = pyqtSignal(int)

    MODE_3D = 0
    MODE_GALLERY = 1

    def __init__(self, db_manager, tile_cache=None, lang_manager=None, settings=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.tile_cache = tile_cache
        self.lang_manager = lang_manager
        self.settings = settings
        self.weapon = None
        self.mode = self.MODE_3D
        self._last_loaded_model_path = None
        self._last_auto_rotate = True
        self._init_ui()

    # ------------------------------------------------------------------ UI ---
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Professional header bar
        header_frame = QFrame()
        header_frame.setObjectName("weapon3dHeader")
        header_frame.setStyleSheet(
            "QFrame{background:#081221;border:1px solid #1e3652;border-radius:10px;padding:8px 14px;}"
        )
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        self.title_label = QLabel("◉ عرض السلاح — 3D Viewer & 2D Gallery")
        self.title_label.setStyleSheet("font-size:18pt;font-weight:700;color:#e0edff;")
        header.addWidget(self.title_label, 1)

        self.info_label = QLabel("اختر سلاحًا من القائمة لعرضه")
        self.info_label.setStyleSheet("font-size:11pt;color:#7aa8d4;")
        header.addWidget(self.info_label, 0)

        # Mode switch: 3D model <-> full-width 2D gallery
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.btn_mode_3d = self._mode_button("نموذج 3D")
        self.btn_mode_3d.setChecked(True)
        self.btn_mode_gallery = self._mode_button("معرض 2D")
        for button in (self.btn_mode_3d, self.btn_mode_gallery):
            self.mode_group.addButton(button)
            header.addWidget(button)
        self.btn_mode_3d.clicked.connect(lambda: self.set_mode(self.MODE_3D))
        self.btn_mode_gallery.clicked.connect(lambda: self.set_mode(self.MODE_GALLERY))

        self.info_toggle = self._mode_button("ℹ المعلومات")
        self.info_toggle.setCheckable(True)
        self.info_toggle.setChecked(True)
        self.info_toggle.setToolTip("إظهار/إخفاء لوحة المواصفات (لوضع 3D)")
        self.info_toggle.clicked.connect(self._apply_mode_layout)
        header.addWidget(self.info_toggle)
        root.addWidget(header_frame)

        # Main split layout: info/controls | stage (3D viewer or 2D gallery)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setHandleWidth(3)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setStyleSheet("QSplitter::handle{background:#15273f;border-radius:4px;}")

        # Left panel: model info + controls
        left_panel = QWidget()
        self.left_panel = left_panel
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)

        # Weapon info card
        info_card = QFrame()
        info_card.setStyleSheet("QFrame{background:#0e1b2e;border:1px solid #1e3652;border-radius:10px;padding:10px;}")
        info_grid = QVBoxLayout(info_card)
        info_grid.setContentsMargins(4, 4, 4, 4)
        info_title = QLabel("معلومات السلاح")
        info_title.setStyleSheet(
            "font-size:12pt;font-weight:700;color:#7fd4ff;padding-bottom:6px;border-bottom:1px solid #1e3652;"
        )
        info_grid.addWidget(info_title)

        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["المواصفة", "القيمة"])
        self.info_table.horizontalHeader().setStretchLastSection(True)
        self.info_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.info_table.setMinimumHeight(200)
        self.info_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.info_table.setStyleSheet(
            "QTableWidget{background:#0a1525;border:1px solid #1e3652;border-radius:8px;gridline-color:#1e3652;"
            "alternate-background-color:#0b182b;color:#d0e6ff;}"
            "QHeaderView::section{background:#15273f;color:#8ad8ff;font-weight:600;padding:6px;border:none;"
            "border-bottom:1px solid #1e3652;border-right:1px solid #1e3652;}"
        )
        info_grid.addWidget(self.info_table)
        left_layout.addWidget(info_card, 1)

        # Professional controls
        controls_frame = QFrame()
        controls_frame.setStyleSheet("QFrame{background:#081221;border:1px solid #1e3652;border-radius:10px;padding:10px;}")
        controls_grid = QVBoxLayout(controls_frame)
        controls_grid.setContentsMargins(4, 4, 4, 4)
        controls_title = QLabel("عناصر التحكم")
        controls_title.setStyleSheet(
            "font-size:11pt;font-weight:700;color:#7fd4ff;padding-bottom:6px;border-bottom:1px solid #1e3652;"
        )
        controls_grid.addWidget(controls_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.load_btn = QPushButton("تحميل نموذج 3D")
        self.load_btn.clicked.connect(self._load_3d_model)
        self.load_btn.setStyleSheet(
            "QPushButton{font-weight:700;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #13458a,stop:1 #0a2545);"
            "color:#cce8ff;border:none;border-radius:8px;padding:8px 14px;min-height:36px;}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1a5fa8,stop:1 #0b3566);}"
        )
        btn_row.addWidget(self.load_btn)

        self.rotate_btn = QPushButton("دوران تلقائي")
        self.rotate_btn.setCheckable(True)
        self.rotate_btn.setChecked(True)
        self.rotate_btn.clicked.connect(self._toggle_rotate)
        self.rotate_btn.setStyleSheet(
            "QPushButton{font-weight:600;background:#142b45;color:#aaddff;border:1px solid #2a4f75;"
            "border-radius:8px;padding:8px 14px;min-height:36px;}"
            "QPushButton:checked{background:#0d3a6e;color:#7fd4ff;border:1px solid #58a8ff;}"
            "QPushButton:hover{border:1px solid #58a8ff;}"
        )
        btn_row.addWidget(self.rotate_btn)
        btn_row.addStretch(1)
        controls_grid.addLayout(btn_row)

        self.gallery_btn = QPushButton("عرض الصور (2D)")
        self.gallery_btn.clicked.connect(lambda: self.set_mode(self.MODE_GALLERY))
        self.gallery_btn.setStyleSheet(
            "QPushButton{font-weight:600;background:#142b45;color:#aaddff;border:1px solid #2a4f75;"
            "border-radius:8px;padding:8px 14px;min-height:32px;}"
            "QPushButton:hover{border:1px solid #58a8ff;color:#7fd4ff;}"
        )
        controls_grid.addWidget(self.gallery_btn)

        # Status label
        self.status_label = QLabel("جاهز — اختر سلاحًا للعرض")
        self.status_label.setStyleSheet("font-size:10pt;color:#7aa8d4;padding-top:6px;")
        self.status_label.setWordWrap(True)
        controls_grid.addWidget(self.status_label)

        left_layout.addWidget(controls_frame, 0)
        self.splitter.addWidget(left_panel)

        # Right panel: stacked 3D viewer / 2D gallery
        right_frame = QFrame()
        right_frame.setStyleSheet("QFrame{background:#060e1a;border:1px solid #1e3652;border-radius:10px;}")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        self.stage_stack = QStackedWidget()
        right_layout.addWidget(self.stage_stack, 1)

        # Page 0 — 3D viewer
        viewer_page = QWidget()
        viewer_layout = QVBoxLayout(viewer_page)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_header = QHBoxLayout()
        viewer_header.addWidget(QLabel("عرض ثلاثي الأبعاد"))
        viewer_header.addStretch(1)
        viewer_layout.addLayout(viewer_header)

        self.viewer = QWebEngineView()
        web_settings = self.viewer.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self.viewer.setHtml(self._build_placeholder_html())
        viewer_layout.addWidget(self.viewer, 1)
        self.stage_stack.addWidget(viewer_page)

        # Page 1 — full-width 2D gallery
        gallery_host = QWidget()
        self.gallery_host_layout = QVBoxLayout(gallery_host)
        self.gallery_host_layout.setContentsMargins(0, 0, 0, 0)
        self.gallery_host_layout.setSpacing(0)
        self.gallery = _WeaponGalleryPanel(
            db_manager=self.db, settings=self.settings, lang_manager=self.lang_manager
        )
        self.gallery.set_home_layout(self.gallery_host_layout)
        self.gallery.primary_image_changed.connect(self.primary_image_changed)
        self.gallery_host_layout.addWidget(self.gallery)
        self.stage_stack.addWidget(gallery_host)

        self.splitter.addWidget(right_frame)
        self.splitter.setSizes([360, 640])
        root.addWidget(self.splitter, 1)

        self._apply_mode_layout()
        self._update_mode_badges()

    def _mode_button(self, text: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton{font-weight:700;background:#0e1b2e;color:#8fb6dd;border:1px solid #2a4f75;"
            "border-radius:8px;padding:7px 14px;min-height:30px;}"
            "QPushButton:hover{border:1px solid #58a8ff;color:#cde4ff;}"
            "QPushButton:checked{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1a5fa8,stop:1 #0b3566);"
            "color:#eaf5ff;border:1px solid #58a8ff;}"
        )
        return button

    # ------------------------------------------------------------- modes --- #
    def set_mode(self, mode: int) -> None:
        self.mode = self.MODE_GALLERY if mode == self.MODE_GALLERY else self.MODE_3D
        self.stage_stack.setCurrentIndex(self.mode)
        if self.mode == self.MODE_GALLERY:
            self.gallery.reload()
        self._apply_mode_layout()
        self._update_mode_badges()

    def _apply_mode_layout(self) -> None:
        """Gallery mode is presented full width; 3D mode keeps the info column."""
        gallery_mode = self.mode == self.MODE_GALLERY
        show_info = self.info_toggle.isChecked() and not gallery_mode
        self.left_panel.setVisible(show_info)
        self.info_toggle.setEnabled(not gallery_mode)
        self.info_toggle.setVisible(not gallery_mode or not show_info)
        if gallery_mode:
            self.splitter.setSizes([0, max(1, self.width())])
        else:
            self.splitter.setSizes([360, max(1, self.width() - 380)])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_mode_layout()

    def _update_mode_badges(self) -> None:
        images = self.gallery.image_count() if hasattr(self, "gallery") else 0
        models = 0
        if isinstance(self.weapon, dict):
            rows = self.weapon.get("models") or []
            models = len(rows) if isinstance(rows, list) else 0
            if not models and self.weapon.get("primary_model"):
                models = 1
        self.btn_mode_gallery.setText(f"معرض 2D ({images})" if images else "معرض 2D")
        self.btn_mode_3d.setText(f"نموذج 3D ({models})" if models else "نموذج 3D")
        self.gallery_btn.setText(f"عرض الصور (2D) — {images} صورة" if images else "عرض الصور (2D)")

    # ------------------------------------------------------------- 3D ---- #
    def _build_placeholder_html(self) -> str:
        return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  html,body{margin:0;height:100%;background:#060e1a;display:flex;align-items:center;justify-content:center;}
  .placeholder{color:#4a7099;font-family:Segoe UI,sans-serif;font-size:18px;font-weight:600;letter-spacing:0.5px;text-align:center;}
  .placeholder-sub{color:#2a4877;font-size:13px;margin-top:8px;font-weight:400;}
</style>
</head>
<body>
  <div class="placeholder">
    <div>◉ عرض السلاح</div>
    <div class="placeholder-sub">نموذج ثلاثي الأبعاد، أو بدّل إلى "معرض 2D" لعرض صور السلاح بعرض كامل</div>
  </div>
</body>
</html>"""

    def load_weapon(self, weapon: dict):
        if not weapon:
            self.weapon = None
            self.title_label.setText("◉ عرض السلاح — 3D Viewer & 2D Gallery")
            self.info_table.setRowCount(0)
            self.status_label.setText("جاهز — اختر سلاحًا للعرض")
            self.viewer.setHtml(self._build_placeholder_html())
            self.gallery.load_weapon(None)
            self._update_mode_badges()
            return
        self.weapon = dict(weapon) if isinstance(weapon, dict) else weapon
        name = self.weapon.get("weapon_name", "سلاح غير معروف")
        model_name = self.weapon.get("model", "—")
        self.title_label.setText(f"◉ {name}")
        self.info_label.setText(f"{self._tr('الموديل')}: {model_name}")
        self.status_label.setText("سلاح محمّل — اضغط تحميل نموذج 3D")
        self._update_info_table()

        # Gallery first: it decides whether it has anything worth showing
        self.gallery.load_weapon(self.weapon)
        images_available = self.gallery.image_count()

        # Auto-load 3D if a primary model exists
        primary_model = self.weapon.get("primary_model")
        if not primary_model and self.weapon.get("models"):
            primary_model = (self.weapon.get("models") or [{}])[0].get("model_path")
        model_on_disk = bool(primary_model and Path(str(primary_model)).exists())
        if model_on_disk:
            self._load_model_file(str(primary_model))
        elif images_available:
            self.set_mode(self.MODE_GALLERY)
            self.status_label.setText(
                f"لا يوجد نموذج 3D لهذا السلاح — فُتح معرض الصور بعرض كامل ({images_available} صورة)"
            )
        else:
            self.viewer.setHtml(self._build_placeholder_html())
            self.status_label.setText("لا توجد وسائط لهذا السلاح — يمكن إضافة صور من معرض 2D")
        self._update_mode_badges()

    def _update_info_table(self):
        if not self.weapon:
            self.info_table.setRowCount(0)
            return
        fields = [
            ("اسم السلاح", self.weapon.get("weapon_name", "")),
            ("الموديل", self.weapon.get("model", "")),
            ("الدولة", self.weapon.get("country", "")),
            ("الفئة", self.weapon.get("category", "")),
            ("المدى (كم)", str(self.weapon.get("range_km", "—"))),
            ("السرعة (ماخ)", str(self.weapon.get("speed_mach", "—"))),
            ("الحالة", self.weapon.get("status", "")),
            ("المصنع", self.weapon.get("manufacturer", "")),
            ("سنة الإدخال", str(self.weapon.get("intro_year", "—"))),
            ("عدد الصور", str(self.gallery.image_count())),
        ]
        self.info_table.setRowCount(len(fields))
        for i, (k, v) in enumerate(fields):
            item_k = QTableWidgetItem(str(k))
            item_k.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item_k.setBackground(Qt.GlobalColor.transparent)
            item_v = QTableWidgetItem(str(v) if v is not None else "—")
            item_v.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item_v.setBackground(Qt.GlobalColor.transparent)
            self.info_table.setItem(i, 0, item_k)
            self.info_table.setItem(i, 1, item_v)

    def _load_3d_model(self):
        if not self.weapon:
            QMessageBox.information(self, "عرض ثلاثي الأبعاد", "يرجى اختيار سلاح أولاً")
            return
        ensure_weapon_media_dirs(self.weapon)
        primary_model = self.weapon.get("primary_model")
        discovered = []
        if not primary_model and self.weapon.get("models"):
            for row in (self.weapon.get("models") or []):
                if isinstance(row, dict) and row.get("model_path"):
                    discovered.append(str(row.get("model_path")))
        if not discovered:
            discovered = discover_models(self.weapon)
        if primary_model and Path(str(primary_model)).exists():
            discovered.insert(0, str(primary_model))
        discovered = [p for p in discovered if Path(p).exists()]
        if not discovered:
            images = self.gallery.image_count()
            if images:
                self.set_mode(self.MODE_GALLERY)
                QMessageBox.information(
                    self, "عرض ثلاثي الأبعاد",
                    f"لا يوجد نموذج ثلاثي الأبعاد — تم فتح معرض الصور ({images} صورة)."
                )
                return
            QMessageBox.information(self, "عرض ثلاثي الأبعاد", "لا يوجد نموذج ثلاثي الأبعاد لهذا السلاح")
            return
        # For single model auto-load; if multiple, show selection
        if len(discovered) == 1:
            self._load_model_file(discovered[0])
        else:
            # Simple selection dialog
            from PyQt6.QtWidgets import QInputDialog
            items = [Path(p).name for p in discovered]
            choice, ok = QInputDialog.getItem(
                self,
                "اختر نموذجًا",
                "نماذج متاحة لهذا السلاح:",
                items,
                0,
                False,
            )
            if ok and choice:
                selected_path = discovered[items.index(choice)]
                self._load_model_file(selected_path)

    def _load_model_file(self, path: str):
        model_path = Path(path)
        if not model_path.exists():
            QMessageBox.warning(self, "عرض ثلاثي الأبعاد", f"الملف غير موجود:\n{path}")
            return
        ext = model_path.suffix.lower()
        name = model_path.name
        # Professional 3D presentation HTML
        html = self._build_3d_viewer_html(str(path), name, ext)
        self.viewer.setHtml(html, QUrl.fromLocalFile(str(path)))
        self._last_loaded_model_path = str(path)
        self.status_label.setText(f"نموذج محمّل: {name}")
        if self.mode != self.MODE_3D:
            self.set_mode(self.MODE_3D)

    def _build_3d_viewer_html(self, file_path: str, file_name: str, ext: str) -> str:
        safe_path = QUrl.fromLocalFile(file_path).toString()
        is_model_viewer_compatible = ext in (".glb", ".gltf", ".usdz")
        if is_model_viewer_compatible:
            return self._build_model_viewer_page(safe_path, file_name)
        else:
            return self._build_threejs_fallback_page(file_path, file_name, ext)

    def _model_viewer_script_src(self) -> str:
        """Offline-first: prefer the vendored model-viewer bundle, fall back to CDN."""
        vendored = Path(__file__).resolve().parents[1] / "resources" / "html" / "Js" / "model-viewer.min.js"
        if vendored.exists():
            return QUrl.fromLocalFile(str(vendored)).toString()
        return "https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"

    def _build_model_viewer_page(self, url: str, name: str) -> str:
        script_src = self._model_viewer_script_src()
        return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}</title>
<style>
  html,body{{margin:0;padding:0;height:100%;background:#060e1a;color:#d5e3f0;font-family:Segoe UI,sans-serif;}}
  body{{display:flex;flex-direction:column;align-items:center;justify-content:center;}}
  #scene{{width:100%;height:100vh;position:relative;background:#060e1a;overflow:hidden;}}
  #overlay{{position:absolute;top:16px;right:20px;background:rgba(8,22,36,0.85);border:1px solid #1e3652;border-radius:10px;padding:14px 18px;color:#cde4ff;backdrop-filter:blur(6px);pointer-events:none;max-width:340px;}}
  #overlay h2{{font-size:16px;font-weight:700;margin:0 0 8px;color:#58a8ff;}}
  #overlay p{{font-size:13px;margin:0;color:#8aa2c2;}}
  model-viewer{{width:100%;height:100vh;display:block;background:transparent;}}
</style>
<script type="module" src="{script_src}"></script>
</head>
<body>
<div id="scene">
  <div id="overlay">
    <h2>◉ {name}</h2>
    <p>نموذج ثلاثي الأبعاد تفاعلي — اسحب للدوران، وقرّب للتكبير.</p>
  </div>
  <model-viewer
    id="model"
    src="{url}"
    alt="{name}"
    auto-rotate
    rotation-per-second="35deg"
    camera-controls
    environment-image="neutral"
    exposure="1.1"
    shadow-intensity="0.7"
    tone-mapping="neutral"
    style="background:transparent;"
  ></model-viewer>
</div>
</body>
</html>"""

    def _build_threejs_fallback_page(self, file_path: str, file_name: str, ext: str) -> str:
        # Professional static preview with model metadata for unsupported formats
        size_kb = Path(file_path).stat().st_size / 1024.0 if Path(file_path).exists() else 0
        return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{file_name}</title>
<style>
  html,body{{margin:0;height:100%;background:#060e1a;color:#d5e3f0;font-family:Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;}}
  .card{{background:#081221;border:1px solid #1e3652;border-radius:16px;padding:36px 40px;max-width:520px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.35);}}
  .card h2{{font-size:20px;font-weight:700;color:#58a8ff;margin-bottom:12px;}}
  .card .meta{{font-size:14px;color:#8aa2c2;line-height:1.7;margin-top:10px;}}
  .card .hint{{font-size:12px;color:#4a7099;margin-top:20px;padding-top:14px;border-top:1px solid #1e3652;}}
</style>
</head>
<body>
  <div class="card">
    <h2>◉ {file_name}</h2>
    <p style="font-size:15px;color:#a6bdd8;">هذا التنسيق (<strong>{ext}</strong>) لا يدعم العرض التفاعلي المباشر عبر المتصفح.</p>
    <div class="meta">
      <strong>المسار:</strong> {file_path}<br>
      <strong>الحجم:</strong> {size_kb:.1f} كيلوبايت<br>
      <strong>التنسيق:</strong> {ext}<br>
    </div>
    <div class="hint">
      للمشاهدة التفاعلية: استخدم نموذجًا بصيغة <strong>.glb</strong> أو <strong>.gltf</strong> أو <strong>.usdz</strong>.
    </div>
  </div>
</body>
</html>"""

    def _toggle_rotate(self, checked: bool):
        self._last_auto_rotate = bool(checked)
        # Rebuild viewer with updated autorotate state if a model is loaded
        if self._last_loaded_model_path:
            self._load_model_file(self._last_loaded_model_path)

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text
