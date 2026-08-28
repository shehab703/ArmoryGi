"""Headless tests for the full-width 2D media gallery of the 3D viewer tab.

Run:  python -m pytest tests/test_weapon_3d_gallery.py -q
In CI, export ``QT_QPA_PLATFORM=offscreen`` — no display is required.
"""
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 is required for the GUI tests")

try:  # views.weapon_3d_view imports QtWebEngine at import time
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
except Exception:  # pragma: no cover - environment dependent
    pytest.skip("PyQt6-WebEngine is required to import views.weapon_3d_view", allow_module_level=True)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from views.weapon_3d_view import (  # noqa: E402
    GALLERY_ZOOM_MAX,
    _WeaponGalleryPanel,
    collect_gallery_images,
    load_scaled_pixmap,
    normalize_path,
)
from utils.weapon_media_library import ensure_weapon_media_dirs  # noqa: E402

pytestmark = pytest.mark.usefixtures("qapp")


# --------------------------------------------------------------------------- #
# helpers / fakes
# --------------------------------------------------------------------------- #
def write_image(path: Path, color: str = "#ff0000", size=(120, 80)) -> str:
    image = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.fillRect(image.rect(), QColor(color))
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path), "PNG"), f"could not write test image: {path}"
    return str(path)


class FakeLang:
    def __init__(self, arabic: bool = True):
        self._arabic = arabic

    def is_arabic(self) -> bool:
        return self._arabic

    def tr(self, text: str) -> str:
        return text


class FakeDb:
    """Records gallery writes instead of touching SQLAlchemy."""

    def __init__(self):
        self.calls = []
        self.primary_image = None

    def add_weapon_image(self, weapon_id, image_path, is_primary=False, caption=None):
        self.calls.append((int(weapon_id), str(image_path), bool(is_primary)))
        if is_primary:
            self.primary_image = str(image_path)
        return True


@pytest.fixture(autouse=True)
def isolate_media_root(tmp_path, monkeypatch):
    """Keep test images out of the developer's real ~/.armorygis data folder."""
    import utils.weapon_media_library as media

    monkeypatch.setattr(media, "GALLERY_ROOT", tmp_path / "media-root")


@pytest.fixture()
def weapon_with_images(tmp_path):
    """A weapon dict whose gallery comes from the DB rows (three images)."""
    import utils.weapon_media_library as media

    images_dir = media.GALLERY_ROOT / "gallery-unit-test_4242" / "images"
    paths = [write_image(images_dir / f"img{i}.png", color) for i, color in
             enumerate(("#ff0000", "#00ff00", "#0000ff"))]
    return {
        "id": 4242,
        "model": "gallery-unit-test",
        "weapon_name": "Gallery Fixture",
        "images": [
            {"image_path": p, "is_primary": i == 0, "display_order": i}
            for i, p in enumerate(paths)
        ],
        "primary_image": paths[0],
    }


def make_panel(weapon, db=None, arabic=True):
    panel = _WeaponGalleryPanel(db_manager=db or FakeDb(), lang_manager=FakeLang(arabic))
    panel.load_weapon(weapon)
    return panel


@pytest.fixture()
def gallery(qapp, weapon_with_images):
    panel = make_panel(weapon_with_images)
    panel.resize(900, 600)
    panel.show()
    yield panel
    panel.close()


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_normalize_path_is_absolute():
    assert Path(normalize_path("a.png")).is_absolute()


def test_collect_orders_by_display_order_and_dedupes(tmp_path):
    """DB rows only — the media folder for this fake model is empty here."""
    first = write_image(tmp_path / "first.png", "#ffffff")
    second = write_image(tmp_path / "second.png", "#eeeeee")
    weapon = {
        "id": 1,
        "model": "dedupe",
        "primary_image": second,
        "images": [
            {"image_path": first, "is_primary": False, "display_order": 0},
            {"image_path": second, "is_primary": True, "display_order": 1},
            {"image_path": first, "is_primary": False, "display_order": 2},
        ],
    }
    collected = collect_gallery_images(weapon, allowed_exts={".png"})
    assert collected[0] == second          # the primary image leads the gallery
    assert len(collected) == 2             # duplicates collapse
    assert first in collected


def test_collect_skips_unsupported_extensions(tmp_path):
    write_image(tmp_path / "ok.png", "#123456")
    note = tmp_path / "notes.txt"
    note.write_text("nope", encoding="utf-8")
    weapon = {"id": 7, "model": "ext", "images": [{"image_path": str(note)}]}
    assert collect_gallery_images(weapon, {".png"}) == []


def test_load_scaled_pixmap_caps_large_images(tmp_path):
    big = write_image(tmp_path / "big.png", "#00ff00", size=(900, 700))
    pix = load_scaled_pixmap(big, max_side=300)
    assert pix is not None and max(pix.width(), pix.height()) <= 300
    assert load_scaled_pixmap(str(tmp_path / "missing.png")) is None


def test_media_folder_images_join_the_gallery(tmp_path, weapon_with_images):
    """Files dropped in the weapon media folder appear without a DB row."""
    images_dir, _ = ensure_weapon_media_dirs(weapon_with_images)
    loose = write_image(images_dir / "loose.png", "#00ffff")
    bare_weapon = {"id": 4242, "model": "gallery-unit-test"}     # no DB rows at all
    collected = collect_gallery_images(bare_weapon, {".png"})
    assert loose in collected                 # the loose file is picked up
    assert len(collected) == 4                # ...together with the three fixture images


# --------------------------------------------------------------------------- #
# gallery panel behaviour
# --------------------------------------------------------------------------- #
def test_gallery_loads_images_from_db_rows(gallery):
    assert gallery.image_count() == 3
    assert gallery.counter_label.text() == "1 / 3"
    assert gallery.filmstrip.count() == 3
    assert gallery.stage.has_image()


def test_navigation_wraps_both_directions(gallery):
    gallery.navigate(1)
    gallery.navigate(1)
    assert gallery.index == 2
    gallery.navigate(1)
    assert gallery.index == 0
    gallery.navigate(-1)
    assert gallery.index == 2
    assert gallery.counter_label.text() == "3 / 3"


def test_arabic_swipe_right_moves_to_next(gallery):
    gallery._on_swipe_flick(120.0)
    assert gallery.index == 1
    gallery._on_swipe_flick(-120.0)
    assert gallery.index == 0


def test_english_swipe_left_moves_to_next(weapon_with_images):
    panel = make_panel(weapon_with_images, arabic=False)
    panel._on_swipe_flick(-120.0)
    assert panel.index == 1
    panel._on_swipe_flick(120.0)
    assert panel.index == 0
    panel.close()


def test_small_swipe_does_not_navigate(gallery):
    gallery._on_swipe_flick(10.0)
    assert gallery.index == 0


def test_arrow_keys_follow_reading_direction(gallery):
    gallery._on_stage_key(int(Qt.Key.Key_Right))   # Arabic: Right == previous
    assert gallery.index == 2
    gallery._on_stage_key(int(Qt.Key.Key_Left))    # Arabic: Left == next
    assert gallery.index == 0
    gallery._on_stage_key(int(Qt.Key.Key_End))
    assert gallery.index == 2
    gallery._on_stage_key(int(Qt.Key.Key_Home))
    assert gallery.index == 0


def test_zoom_keys_and_clamping(gallery):
    gallery._on_stage_key(int(Qt.Key.Key_Plus))
    assert gallery.stage.zoom_factor() > 1.0
    for _ in range(14):
        gallery.stage.zoom_by(1.5)
    assert gallery.stage.zoom_factor() <= GALLERY_ZOOM_MAX
    gallery._on_stage_key(int(Qt.Key.Key_0))
    assert gallery.stage.zoom_factor() == pytest.approx(1.0)


def test_panning_is_clamped_when_zoomed(gallery):
    from PyQt6.QtCore import QPointF, QEvent
    from PyQt6.QtGui import QMouseEvent

    gallery.stage.zoom_by(3.0)
    center = QPointF(gallery.stage.rect().center())
    far = QPointF(9999.0, 9999.0)
    gallery.stage._press_point = center
    gallery.stage._press_pan = QPointF(gallery.stage._pan)
    gallery.stage._drag_active = True
    gallery.stage._drag_moved = True
    gallery.stage.mouseMoveEvent(
        QMouseEvent(QEvent.Type.MouseMove, far, far, far, Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    )
    assert abs(gallery.stage._pan.x()) <= gallery.stage.width()
    assert abs(gallery.stage._pan.y()) <= gallery.stage.height()
    gallery.stage._drag_active = False


def test_wheel_navigation_follows_reading_direction(gallery):
    gallery._on_wheel_navigate(-1)     # wheel down
    assert gallery.index == 1          # Arabic: wheel down advances
    gallery._on_wheel_navigate(1)      # wheel up
    assert gallery.index == 0


def test_wheel_navigation_is_direction_agnostic(weapon_with_images):
    """Wheel/horizontal-scroll input means the same thing in Arabic and English."""
    panel = make_panel(weapon_with_images, arabic=False)
    panel._on_wheel_navigate(-1)   # wheel down
    assert panel.index == 1
    panel._on_wheel_navigate(1)    # wheel up
    assert panel.index == 0
    panel.close()


def test_filmstrip_click_jumps_to_image(gallery):
    gallery.filmstrip.setCurrentRow(2)
    gallery._on_filmstrip_clicked(gallery.filmstrip.item(2))
    assert gallery.index == 2


def test_set_as_primary_persists_and_notifies(gallery, weapon_with_images):
    received = []
    gallery.primary_image_changed.connect(lambda wid: received.append(wid))
    gallery.go_to(2)
    path = gallery.image_paths[2]
    gallery._set_as_primary()
    assert gallery.db.calls == [(4242, path, True)]
    assert received == [4242]
    assert gallery.image_paths[0] == path     # the new primary leads the gallery
    assert gallery.index == 0


def test_imported_paths_are_staged_and_saved(qapp, tmp_path, weapon_with_images):
    """Drag & drop / "add images" copies files into the media folder and registers them."""
    import utils.weapon_media_library as media

    panel = make_panel(weapon_with_images)
    try:
        source = write_image(tmp_path / "dropped.png", "#654321")
        assert panel._import_paths([source]) == 1
        assert panel.db.calls[-1][0] == 4242
        staged = panel.db.calls[-1][1]
        assert Path(staged).parent == media.GALLERY_ROOT / "gallery-unit-test_4242" / "images"
        assert Path(staged).exists()
    finally:
        panel.close()


def test_empty_gallery_shows_hint(qapp):
    panel = make_panel({"id": 99, "model": "no-media-at-all"})
    assert panel.image_count() == 0
    assert not panel.stage.has_image()
    assert "لا توجد صور" in panel.stage._empty_message or not panel.prev_btn.isEnabled()
    assert not panel.primary_btn.isEnabled()
    panel.close()


def test_no_weapon_selected_is_safe(qapp):
    panel = make_panel(None)
    panel.navigate(1)
    panel.reload()
    assert panel.image_count() == 0
    panel.close()


def test_slideshow_only_runs_with_multiple_images(gallery):
    gallery._toggle_slideshow(True)
    assert gallery._slideshow_timer.isActive()
    gallery._toggle_slideshow(False)
    assert not gallery._slideshow_timer.isActive()


def test_fullscreen_round_trip_reparents_the_panel(gallery):
    """Fullscreen re-parents the gallery into a dialog and restores it afterwards."""
    original_parent = gallery.parent()
    gallery.toggle_fullscreen()
    try:
        assert gallery._fs_dialog is not None
        assert gallery.parent() is gallery._fs_dialog
        assert gallery._fs_dialog.isVisible()
        assert gallery.btn_exit_fullscreen.isVisible()
    finally:
        gallery.toggle_fullscreen()
    assert gallery._fs_dialog is None
    assert gallery.parent() is original_parent
    assert not gallery.btn_exit_fullscreen.isVisible()
    assert gallery.stage.has_image()
    assert gallery.image_count() == 3


def test_escape_key_leaves_fullscreen(gallery):
    from PyQt6.QtTest import QTest

    gallery.toggle_fullscreen()
    assert gallery._fs_dialog is not None
    QTest.keyClick(gallery._fs_dialog, Qt.Key.Key_Escape)
    app = QApplication.instance()
    app.processEvents()
    assert gallery._fs_dialog is None
    assert gallery.image_count() == 3


def test_3d_view_exposes_gallery_api():
    """The tab keeps the API MainWindow relies on, and adds the gallery mode."""
    from views.weapon_3d_view import Weapon3DView

    assert hasattr(Weapon3DView, "load_weapon")
    assert hasattr(Weapon3DView, "set_mode")
    assert hasattr(Weapon3DView, "primary_image_changed")
    assert hasattr(Weapon3DView, "MODE_GALLERY")
