from PyQt6.QtWidgets import (
    QWidget,
    QListView,
    QStyledItemDelegate,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QPushButton,
    QFileDialog,
    QLabel,
    QCheckBox,
    QFrame,
    QMessageBox,
    QToolButton,
    QFormLayout,
)
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal, QEvent
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QStandardItemModel,
    QStandardItem,
    QPixmap,
    QIcon,
    QMouseEvent,
    QFontMetrics,
)
from database.db_manager import Category, Country, WeaponModel
from pathlib import Path
from config import APP_DATA_DIR
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from utils.weapon_media_library import stage_gallery_image, stage_model_file, ensure_weapon_media_dirs

class CardDelegate(QStyledItemDelegate):
    favorite_toggle_requested = pyqtSignal(dict)

    def __init__(self, lang_manager=None, parent=None):
        super().__init__(parent)
        self.lang_manager = lang_manager

    CATEGORY_COLORS = {
        "Air-to-Air Missile (AAM)": QColor(37, 99, 235),
        "Air-to-Surface Missile (ASM)": QColor(217, 119, 6),
        "Anti-Tank Guided Missile (ATGM)": QColor(220, 38, 38),
        "Cruise Missile": QColor(5, 150, 105),
    }

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        weapon = index.data(Qt.ItemDataRole.UserRole) or {}
        category = weapon.get("category", "")
        accent = self.CATEGORY_COLORS.get(category, QColor(100, 116, 139))
        card_rect = option.rect.adjusted(4, 4, -4, -4)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(226, 232, 240, 90))
        painter.drawRoundedRect(card_rect.adjusted(0, 2, 0, 2), 12, 12)

        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(card_rect, 12, 12)

        strip_rect = QRect(card_rect.x() + 1, card_rect.y() + 1, card_rect.width() - 2, 5)
        painter.setBrush(accent)
        painter.drawRoundedRect(strip_rect, 10, 10)

        painter.setPen(QPen(QColor(216, 227, 243), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card_rect, 12, 12)

        favorite_rect = self._favorite_icon_rect(card_rect)
        favorite_on = bool(weapon.get("is_favorite")) if weapon else False
        if favorite_on:
            painter.setBrush(QColor(254, 243, 199))
            painter.setPen(QPen(QColor(245, 158, 11), 1))
        else:
            painter.setBrush(QColor(248, 250, 252))
            painter.setPen(QPen(QColor(203, 213, 225), 1))
        painter.drawRoundedRect(favorite_rect, 7, 7)
        painter.setPen(QColor(180, 83, 9) if favorite_on else QColor(148, 163, 184))
        painter.drawText(favorite_rect, int(Qt.AlignmentFlag.AlignCenter), "★")

        image_rect = QRect(card_rect.x() + 12, card_rect.y() + 16, 80, 80)
        painter.setBrush(QColor(241, 245, 249))
        painter.setPen(QPen(QColor(203, 213, 225), 1))
        painter.drawRoundedRect(image_rect, 10, 10)

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon and hasattr(icon, "pixmap"):
            pix = icon.pixmap(76, 76)
            if not pix.isNull():
                painter.drawPixmap(image_rect.adjusted(2, 2, -2, -2), pix)

        name = index.data(Qt.ItemDataRole.DisplayRole)
        text_x = image_rect.right() + 12
        text_w = max(40, card_rect.right() - text_x - 10)

        painter.setPen(QColor(31, 45, 61))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        name_text = QFontMetrics(font).elidedText(
            str(name), Qt.TextElideMode.ElideRight, text_w
        )
        painter.drawText(
            QRect(text_x, card_rect.y() + 18, text_w, 22),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            name_text,
        )

        if weapon:
            country = self._tr_data(weapon.get("country", "N/A"))
            category_tr = self._tr_data(weapon.get("category", "-"))
            subtext = f"{country} | {weapon.get('range_km', 0)} km"
            font.setBold(False)
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(QColor(71, 85, 105))
            sub_elided = QFontMetrics(font).elidedText(
                subtext, Qt.TextElideMode.ElideRight, text_w
            )
            painter.drawText(
                QRect(text_x, card_rect.y() + 44, text_w, 20),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                sub_elided,
            )
            model = str(weapon.get("model", "-"))
            category_text = str(category_tr)
            meta = QFontMetrics(font).elidedText(
                f"{model} • {category_text}", Qt.TextElideMode.ElideRight, text_w
            )
            painter.setPen(QColor(100, 116, 139))
            painter.drawText(
                QRect(text_x, card_rect.y() + 66, text_w, 20),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                meta,
            )

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(320, 142)

    def _tr_data(self, value):
        if self.lang_manager:
            return self.lang_manager.tr_data(value)
        return value

    def _favorite_icon_rect(self, card_rect: QRect) -> QRect:
        return QRect(card_rect.x() + 10, card_rect.y() + 10, 22, 22)

    def editorEvent(self, event, model, option, index):
        if event is None:
            return super().editorEvent(event, model, option, index)
        if event.type() == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            weapon = index.data(Qt.ItemDataRole.UserRole) or {}
            card_rect = option.rect.adjusted(3, 3, -3, -3)
            if weapon and self._favorite_icon_rect(card_rect).contains(event.pos()):
                self.favorite_toggle_requested.emit(weapon)
                return True
        return super().editorEvent(event, model, option, index)

class DashboardView(QWidget):
    weapon_selected = pyqtSignal(dict)
    weapon_open_requested = pyqtSignal(dict)
    toggle_detail_pane_requested = pyqtSignal()
    favorites_changed = pyqtSignal()

    def __init__(self, db_manager, lang_manager=None):
        super().__init__()
        self.db = db_manager
        self.lang_manager = lang_manager
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search cards...")
        self.category = QComboBox()
        self.country = QComboBox()
        self.apply_btn = QPushButton("Filter")
        self.clear_btn = QPushButton("Reset")
        self.toggle_detail_btn = QToolButton()
        self.toggle_detail_btn.setText("∆")
        self.toggle_detail_btn.setToolTip("Hide/Show right pane")
        self.toggle_detail_btn.clicked.connect(self.toggle_detail_pane_requested.emit)
        self.category.addItem("All Categories", "")
        self.country.addItem("All Countries", "")
        self._load_lookups()
        filters.addWidget(self.search, 2)
        filters.addWidget(self.category, 1)
        filters.addWidget(self.country, 1)
        filters.addWidget(self.apply_btn)
        filters.addWidget(self.clear_btn)
        filters.addWidget(self.toggle_detail_btn)
        layout.addLayout(filters)

        self.list = QListView(self)
        self.model = QStandardItemModel(self)
        self.list.setModel(self.model)
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.card_delegate = CardDelegate(self.lang_manager, self.list)
        self.list.setItemDelegate(self.card_delegate)
        self.list.setGridSize(QSize(328, 156))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setSpacing(10)
        layout.addWidget(self.list)
        self._thumb_icon_cache: dict[tuple[str, int], QIcon] = {}

        self.list.clicked.connect(self._on_click)
        self.list.doubleClicked.connect(self._on_double_click)
        self.card_delegate.favorite_toggle_requested.connect(self._toggle_favorite_from_card)
        self.apply_btn.clicked.connect(self.refresh)
        self.clear_btn.clicked.connect(self._reset_filters)
        self.search.returnPressed.connect(self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.country.currentIndexChanged.connect(self.refresh)

        # Gallery / thumbnail management panel for selected weapon card.
        gallery_panel = QFrame(self)
        gallery_panel.setFrameShape(QFrame.Shape.StyledPanel)
        gallery_panel.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #d8e3f3; border-radius: 8px; }"
        )
        gp_layout = QVBoxLayout(gallery_panel)
        gp_layout.setSpacing(10)
        self.selected_weapon_lbl = QLabel("Selected weapon: none")
        self.image_path_input = QLineEdit()
        self.image_path_input.setPlaceholderText("PNG path for gallery / thumbnail")
        self.browse_png_btn = QPushButton("Browse PNG")
        self.browse_png_btn.clicked.connect(self._browse_png)
        self.png_ext_lbl = QLabel(".png  .jpg  .jpeg  .webp")
        self.png_ext_lbl.setStyleSheet("color: #64748b; font-size: 11px; padding: 0 6px;")
        self.browse_multi_btn = QPushButton("Browse multiple images…")
        self.browse_multi_btn.clicked.connect(self._browse_images_multi)
        self.set_primary_check = QCheckBox("Set as dashboard thumbnail (primary)")
        self.add_gallery_btn = QPushButton("Add Image to Weapon Gallery")
        self.add_gallery_btn.clicked.connect(self._add_gallery_image)
        self.add_multi_gallery_btn = QPushButton("Add multiple images to gallery")
        self.add_multi_gallery_btn.clicked.connect(self._add_gallery_images_bulk)
        self.model_path_input = QLineEdit()
        self.model_path_input.setPlaceholderText("3D model path (.obj, .stl, .ply, .fbx, .dae, .glb, .gltf, .usdz)")
        self.model_set_primary_check = QCheckBox("Set as primary 3D model")
        self.model_set_primary_check.setChecked(True)
        self.model_convert_preview_check = QCheckBox("Auto-convert OBJ/DAE to GLB (preview)")
        self.model_convert_preview_check.setChecked(False)
        self.browse_model_btn = QPushButton("Browse 3D Model")
        self.browse_model_btn.clicked.connect(self._browse_model_file)
        self.model_ext_lbl = QLabel(".obj  .stl  .glb  .gltf  .fbx  .dae")
        self.model_ext_lbl.setStyleSheet("color: #64748b; font-size: 11px; padding: 0 6px;")
        self.add_model_btn = QPushButton("Add 3D model to selected weapon")
        self.add_model_btn.clicked.connect(self._add_weapon_model)
        self.restage_models_btn = QPushButton("Re-stage existing models")
        self.restage_models_btn.clicked.connect(self._restage_existing_models)
        sel_row = QHBoxLayout()
        sel_row.addWidget(self.selected_weapon_lbl, 1)
        self.favorite_check = QCheckBox("Favorite (Favorites tab)")
        self.favorite_check.setEnabled(False)
        self.favorite_check.toggled.connect(self._on_favorite_toggled)
        sel_row.addWidget(self.favorite_check)
        gp_layout.addLayout(sel_row)
        gallery_tools_header = QHBoxLayout()
        self.toggle_gallery_tools_btn = QToolButton()
        self.toggle_gallery_tools_btn.setCheckable(True)
        self.toggle_gallery_tools_btn.setChecked(False)
        self.toggle_gallery_tools_btn.setText("▷")
        self.toggle_gallery_tools_btn.setToolTip("Show/hide input tools")
        self.toggle_gallery_tools_btn.clicked.connect(self._toggle_gallery_tools)
        self.gallery_tools_lbl = QLabel("Gallery tools")
        gallery_tools_header.addWidget(self.toggle_gallery_tools_btn)
        gallery_tools_header.addWidget(self.gallery_tools_lbl)
        gallery_tools_header.addStretch(1)
        gp_layout.addLayout(gallery_tools_header)

        self.gallery_tools_host = QWidget()
        tools_layout = QVBoxLayout(self.gallery_tools_host)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(10)

        png_form = QFormLayout()
        png_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        png_row = QHBoxLayout()
        png_row.setSpacing(8)
        png_row.addWidget(self.image_path_input, 1)
        png_row.addWidget(self.browse_png_btn)
        png_row.addWidget(self.png_ext_lbl)
        png_row_w = QWidget()
        png_row_w.setLayout(png_row)
        self.png_field_lbl = QLabel(self._tr("Gallery/Thumbnail PNG File Path"))
        png_form.addRow(self.png_field_lbl, png_row_w)
        tools_layout.addLayout(png_form)

        model_form = QFormLayout()
        model_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self.model_path_input, 1)
        model_row.addWidget(self.browse_model_btn)
        model_row.addWidget(self.model_ext_lbl)
        model_row_w = QWidget()
        model_row_w.setLayout(model_row)
        self.model_field_lbl = QLabel(self._tr("3D Model Path"))
        model_form.addRow(self.model_field_lbl, model_row_w)
        tools_layout.addLayout(model_form)

        browse_multi_row = QHBoxLayout()
        browse_multi_row.addWidget(self.browse_multi_btn)
        browse_multi_row.addStretch(1)
        tools_layout.addLayout(browse_multi_row)

        row_options = QHBoxLayout()
        row_options.setSpacing(12)
        row_options.addWidget(self.set_primary_check)
        row_options.addWidget(self.model_set_primary_check)
        row_options.addWidget(self.model_convert_preview_check)
        row_options.addStretch(1)
        tools_layout.addLayout(row_options)

        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)
        row_actions.addWidget(self.add_gallery_btn)
        row_actions.addWidget(self.add_multi_gallery_btn)
        row_actions.addWidget(self.add_model_btn)
        row_actions.addWidget(self.restage_models_btn)
        tools_layout.addLayout(row_actions)
        gp_layout.addWidget(self.gallery_tools_host)
        self.gallery_tools_host.setVisible(False)
        layout.addWidget(gallery_panel)
        self._selected_weapon = None
        self._favorite_syncing = False
        self.retranslate_ui()

    def _on_click(self, index):
        weapon = index.data(Qt.ItemDataRole.UserRole)
        if weapon:
            self._selected_weapon = weapon
            self.selected_weapon_lbl.setText(
                f"Selected weapon: {weapon.get('weapon_name', 'Unknown')} ({weapon.get('model', '-')})"
            )
            self._sync_favorite_checkbox()
            self.weapon_selected.emit(weapon)

    def _sync_favorite_checkbox(self):
        self._favorite_syncing = True
        try:
            if self._selected_weapon:
                self.favorite_check.setEnabled(True)
                self.favorite_check.setChecked(bool(self._selected_weapon.get("is_favorite")))
            else:
                self.favorite_check.setEnabled(False)
                self.favorite_check.setChecked(False)
        finally:
            self._favorite_syncing = False

    def _on_favorite_toggled(self, checked: bool):
        if self._favorite_syncing:
            return
        if not self._selected_weapon:
            return
        wid = self._selected_weapon.get("id")
        if not wid:
            return
        self.db.update_weapon(int(wid), {"is_favorite": checked})
        self._selected_weapon["is_favorite"] = checked
        self.refresh()
        self._reselect_weapon_by_id(int(wid))
        self.favorites_changed.emit()

    def _on_double_click(self, index):
        weapon = index.data(Qt.ItemDataRole.UserRole)
        if not weapon:
            return
        self._on_click(index)
        self.weapon_open_requested.emit(weapon)

    def _toggle_favorite_from_card(self, weapon: dict):
        wid = weapon.get("id")
        if not wid:
            return
        new_value = not bool(weapon.get("is_favorite"))
        self.db.update_weapon(int(wid), {"is_favorite": new_value})
        if self._selected_weapon and int(self._selected_weapon.get("id", -1)) == int(wid):
            self._selected_weapon["is_favorite"] = new_value
            self._sync_favorite_checkbox()
        self.refresh()
        self._reselect_weapon_by_id(int(wid))
        self.favorites_changed.emit()

    def refresh(self):
        """Reload dashboard cards from the database."""
        self.model.clear()
        filters = {}
        if self.search.text().strip():
            filters["search"] = self.search.text().strip()
        if self.category.currentData():
            filters["category"] = self.category.currentData()
        if self.country.currentData():
            filters["country"] = self.country.currentData()
        weapons = self.db.get_weapons_paginated(0, 250, filters=filters)
        for weapon in weapons:
            item = QStandardItem(weapon.get('weapon_name', 'Unknown'))
            item.setEditable(False)
            item.setData(weapon, Qt.ItemDataRole.UserRole)
            image_path = weapon.get("primary_image")
            if image_path and Path(str(image_path)).exists():
                img_path = Path(str(image_path))
                try:
                    cache_key = (str(img_path), int(img_path.stat().st_mtime_ns))
                except OSError:
                    cache_key = None
                icon = self._thumb_icon_cache.get(cache_key) if cache_key else None
                if icon is None:
                    pixmap = QPixmap(str(img_path))
                    if not pixmap.isNull():
                        icon = QIcon(pixmap)
                        if cache_key:
                            self._thumb_icon_cache[cache_key] = icon
                            if len(self._thumb_icon_cache) > 512:
                                self._thumb_icon_cache.clear()
                if icon is not None:
                    # Transparent PNGs render correctly via QPixmap with alpha channel.
                    item.setData(icon, Qt.ItemDataRole.DecorationRole)
            self.model.appendRow(item)
        if self._selected_weapon:
            self._selected_weapon = next(
                (w for w in weapons if int(w.get("id", -1)) == int(self._selected_weapon.get("id", -2))),
                self._selected_weapon,
            )
            self._sync_favorite_checkbox()

    def _load_lookups(self):
        with self.db.get_session() as session:
            seen_categories = set()
            for item in session.query(Category).order_by(Category.name.asc()).all():
                key = (item.name or "").strip().lower()
                if not key or key in seen_categories:
                    continue
                seen_categories.add(key)
                self.category.addItem(item.name, item.name)
            seen_countries = set()
            for item in session.query(Country).order_by(Country.name.asc()).all():
                key = (item.name or "").strip().lower()
                if not key or key in seen_countries:
                    continue
                seen_countries.add(key)
                self.country.addItem(item.name, item.name)

    def _reset_filters(self):
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.country.setCurrentIndex(0)
        self.refresh()

    def _browse_png(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PNG thumbnail",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp);;All files (*.*)",
        )
        if path:
            self.image_path_input.setText(path)

    def _browse_images_multi(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._tr("Select images for gallery"),
            str(Path.home()),
            self._tr("Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp);;All files (*.*)"),
        )
        if paths:
            self.image_path_input.setText("; ".join(paths))

    def _add_gallery_images_bulk(self):
        if not self._selected_weapon:
            indexes = self.list.selectedIndexes()
            if indexes:
                self._selected_weapon = indexes[0].data(Qt.ItemDataRole.UserRole)
        if not self._selected_weapon:
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("Please select a weapon first."))
            return
        weapon_id = self._selected_weapon.get("id")
        if not weapon_id:
            QMessageBox.critical(self, self._tr("Gallery"), self._tr("Failed to save images."))
            return
        raw = self.image_path_input.text().strip()
        paths = [p.strip() for p in raw.split(";") if p.strip()] if raw else []
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                self._tr("Select images for gallery"),
                str(Path.home()),
                self._tr("Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp);;All files (*.*)"),
            )
        if not paths:
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("No image files selected."))
            return
        weapon_obj = self._selected_weapon or {}
        staged_paths = [stage_gallery_image(weapon_obj, p) for p in paths]
        added, skipped = self.db.add_weapon_images_batch(
            int(weapon_id),
            staged_paths,
            set_first_as_primary=self.set_primary_check.isChecked(),
        )
        if added == 0:
            QMessageBox.warning(
                self,
                self._tr("Gallery"),
                f"No new images added (duplicates or invalid files). Skipped: {skipped}",
            )
            return
        self.refresh()
        self._reselect_weapon_by_id(int(weapon_id))
        self.image_path_input.clear()
        QMessageBox.information(
            self,
            self._tr("Gallery"),
            f"Added {added} image(s) to gallery. Skipped or duplicates: {skipped}.",
        )

    def _add_gallery_image(self):
        if not self._selected_weapon:
            indexes = self.list.selectedIndexes()
            if indexes:
                self._selected_weapon = indexes[0].data(Qt.ItemDataRole.UserRole)
        if not self._selected_weapon:
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("Please select a weapon first."))
            return
        img_path = self.image_path_input.text().strip()
        if not img_path or not Path(img_path).exists():
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("Please select a valid image file."))
            return
        weapon_id = self._selected_weapon.get("id")
        if not weapon_id:
            QMessageBox.critical(self, self._tr("Gallery"), self._tr("Failed to save image."))
            return
        img_path = stage_gallery_image(self._selected_weapon or {}, img_path)
        ok = self.db.add_weapon_image(
            int(weapon_id),
            img_path,
            is_primary=self.set_primary_check.isChecked(),
        )
        if not ok:
            QMessageBox.critical(self, self._tr("Gallery"), self._tr("Failed to save image."))
            return
        self.refresh()
        self._reselect_weapon_by_id(int(weapon_id))
        self.image_path_input.clear()
        QMessageBox.information(self, self._tr("Gallery"), self._tr("Image saved successfully."))

    def _browse_model_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("Select 3D model"),
            str(Path.home()),
            self._tr("3D Models (*.obj *.stl *.ply *.fbx *.dae *.glb *.gltf *.usdz);;All files (*.*)"),
        )
        if path:
            self.model_path_input.setText(path)

    def _add_weapon_model(self):
        if not self._selected_weapon:
            indexes = self.list.selectedIndexes()
            if indexes:
                self._selected_weapon = indexes[0].data(Qt.ItemDataRole.UserRole)
        if not self._selected_weapon:
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("Please select a weapon first."))
            return
        model_path = self.model_path_input.text().strip()
        if not model_path or not Path(model_path).exists():
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("Please select a valid 3D model file."))
            return
        weapon_id = self._selected_weapon.get("id")
        if not weapon_id:
            QMessageBox.critical(self, self._tr("Gallery"), self._tr("Failed to save model."))
            return
        source_model_path = stage_model_file(self._selected_weapon or {}, model_path)
        source_model_path = self._stage_model_for_preview(source_model_path, int(weapon_id))
        model_to_store, converted = self._maybe_convert_model_for_preview(
            source_model_path,
            allow_convert=self.model_convert_preview_check.isChecked(),
        )
        ok = self.db.add_weapon_model(
            int(weapon_id),
            model_to_store,
            is_primary=self.model_set_primary_check.isChecked(),
        )
        if not ok:
            QMessageBox.critical(self, self._tr("Gallery"), self._tr("Failed to save model."))
            return
        self.refresh()
        self._reselect_weapon_by_id(int(weapon_id))
        if self._selected_weapon:
            self.weapon_selected.emit(self._selected_weapon)
        self.model_path_input.clear()
        if converted:
            QMessageBox.information(
                self,
                self._tr("Gallery"),
                self._tr("3D model converted to GLB and saved successfully."),
            )
        else:
            QMessageBox.information(self, self._tr("Gallery"), self._tr("3D model saved successfully."))
        # Ensure folder tree exists even when model/image already existed.
        ensure_weapon_media_dirs(self._selected_weapon or {})

    def _maybe_convert_model_for_preview(self, model_path: str, allow_convert: bool = False) -> tuple[str, bool]:
        src = Path(model_path)
        if not allow_convert:
            return model_path, False
        if src.suffix.lower() not in {".obj", ".dae"}:
            return model_path, False
        try:
            import trimesh  # type: ignore
        except Exception:
            QMessageBox.information(
                self,
                self._tr("Gallery"),
                self._tr("Converter dependency missing; saving original model format."),
            )
            return model_path, False
        try:
            mesh = trimesh.load(str(src), force="scene")
            out_dir = APP_DATA_DIR / "converted_models"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{src.stem}_converted.glb"
            glb_data = mesh.export(file_type="glb")
            out_path.write_bytes(glb_data)
            return str(out_path), True
        except Exception:
            QMessageBox.information(
                self,
                self._tr("Gallery"),
                self._tr("Auto-convert failed; saving original model format."),
            )
            return model_path, False

    def _stage_model_for_preview(self, model_path: str, weapon_id: int) -> str:
        """
        Copy model file + referenced sidecar assets into app-managed storage.
        This keeps texture/color resources available even if original folders move.
        """
        src = Path(model_path).expanduser().resolve(strict=False)
        if not src.exists() or not src.is_file():
            return model_path
        try:
            src_key = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:10]
            bundle_root = APP_DATA_DIR / "model_assets" / f"weapon_{weapon_id}" / f"{src.stem}_{src_key}"
            bundle_root.mkdir(parents=True, exist_ok=True)
            staged_model = bundle_root / src.name
            shutil.copy2(src, staged_model)
            ext = src.suffix.lower()
            if ext == ".gltf":
                self._copy_gltf_references(src, bundle_root)
            elif ext == ".obj":
                self._copy_obj_references(src, bundle_root)
            elif ext == ".dae":
                self._copy_dae_references(src, bundle_root)
            return str(staged_model)
        except Exception:
            return model_path

    def _copy_local_asset(self, src_base: Path, rel_asset_path: str, target_root: Path):
        rel_norm = (rel_asset_path or "").strip().replace("\\", "/")
        if not rel_norm or rel_norm.startswith(("http://", "https://", "data:")):
            return
        src_asset = (src_base / rel_norm).resolve(strict=False)
        if not src_asset.exists() or not src_asset.is_file():
            return
        target_asset = target_root / Path(rel_norm)
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_asset, target_asset)

    def _copy_gltf_references(self, src_model: Path, target_root: Path):
        try:
            doc = json.loads(src_model.read_text(encoding="utf-8"))
        except Exception:
            return
        src_base = src_model.parent
        for key in ("buffers", "images"):
            for item in doc.get(key, []) or []:
                uri = item.get("uri")
                if uri:
                    self._copy_local_asset(src_base, uri, target_root)

    def _copy_obj_references(self, src_model: Path, target_root: Path):
        src_base = src_model.parent
        mtllibs: list[str] = []
        try:
            for line in src_model.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("mtllib "):
                    mtllibs.append(line.split(None, 1)[1].strip())
        except Exception:
            return
        texture_pattern = re.compile(r"^(?:map_|bump|disp|decal|norm)\S*\s+(.+)$", re.IGNORECASE)
        for mtl_rel in mtllibs:
            self._copy_local_asset(src_base, mtl_rel, target_root)
            mtl_path = (src_base / mtl_rel).resolve(strict=False)
            if not mtl_path.exists() or not mtl_path.is_file():
                continue
            try:
                for line in mtl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    match = texture_pattern.match(line.strip())
                    if match:
                        tex_ref = match.group(1).strip().split(maxsplit=1)[-1].strip('"')
                        self._copy_local_asset(src_base, tex_ref, target_root)
            except Exception:
                continue

    def _copy_dae_references(self, src_model: Path, target_root: Path):
        src_base = src_model.parent
        try:
            root = ET.fromstring(src_model.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag != "init_from":
                continue
            ref = (node.text or "").strip()
            if ref:
                self._copy_local_asset(src_base, ref, target_root)

    def _restage_existing_models(self):
        confirm = QMessageBox.question(
            self,
            self._tr("Gallery"),
            self._tr("Re-stage all existing model paths into app storage now?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        migrated = 0
        skipped = 0
        missing = 0
        app_assets_root = (APP_DATA_DIR / "model_assets").resolve(strict=False)
        try:
            with self.db.get_session() as session:
                rows = session.query(WeaponModel).all()
                for row in rows:
                    src = Path(str(row.model_path)).expanduser().resolve(strict=False)
                    if app_assets_root == src or app_assets_root in src.parents:
                        skipped += 1
                        continue
                    if not src.exists() or not src.is_file():
                        missing += 1
                        continue
                    staged = self._stage_model_for_preview(str(src), int(row.weapon_id))
                    if not staged:
                        skipped += 1
                        continue
                    staged_path = Path(staged).expanduser().resolve(strict=False)
                    if str(staged_path).lower() == str(src).lower():
                        skipped += 1
                        continue
                    row.model_path = str(staged_path)
                    row.model_format = staged_path.suffix.lower().lstrip(".")
                    migrated += 1
                session.commit()
            self.refresh()
            QMessageBox.information(
                self,
                self._tr("Gallery"),
                self._tr(
                    f"Re-stage complete. Updated: {migrated}, skipped: {skipped}, missing: {missing}."
                ),
            )
        except Exception:
            QMessageBox.critical(
                self,
                self._tr("Gallery"),
                self._tr("Model re-stage failed."),
            )

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.card_delegate = CardDelegate(self.lang_manager, self.list)
        self.list.setItemDelegate(self.card_delegate)
        self.card_delegate.favorite_toggle_requested.connect(self._toggle_favorite_from_card)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.search.setPlaceholderText(self._tr("Search cards..."))
        self.apply_btn.setText(self._tr("Filter"))
        self.clear_btn.setText(self._tr("Reset"))
        self.toggle_detail_btn.setToolTip(self._tr("Hide/Show right pane"))
        self.toggle_gallery_tools_btn.setToolTip(self._tr("Show/hide input tools"))
        self.selected_weapon_lbl.setText(self._tr("Selected weapon: none"))
        self.gallery_tools_lbl.setText(self._tr("Gallery tools"))
        self.png_field_lbl.setText(self._tr("Gallery/Thumbnail PNG File Path"))
        self.model_field_lbl.setText(self._tr("3D Model Path"))
        self.image_path_input.setPlaceholderText(self._tr("PNG path for gallery / thumbnail"))
        self.model_path_input.setPlaceholderText(self._tr("3D model path (.obj, .stl, .ply, .fbx, .dae, .glb, .gltf, .usdz)"))
        self.browse_png_btn.setText(self._tr("Browse PNG"))
        self.png_ext_lbl.setText(self._tr(".png  .jpg  .jpeg  .webp"))
        self.model_ext_lbl.setText(self._tr(".obj  .stl  .glb  .gltf  .fbx  .dae"))
        self.set_primary_check.setText(self._tr("Set as dashboard thumbnail (primary)"))
        self.model_set_primary_check.setText(self._tr("Set as primary 3D model"))
        self.model_convert_preview_check.setText(self._tr("Auto-convert OBJ/DAE to GLB (preview)"))
        self.add_gallery_btn.setText(self._tr("Add Image to Weapon Gallery"))
        self.add_multi_gallery_btn.setText(self._tr("Add multiple images to gallery"))
        self.browse_multi_btn.setText(self._tr("Browse multiple images…"))
        self.browse_model_btn.setText(self._tr("Browse 3D Model"))
        self.add_model_btn.setText(self._tr("Add 3D model to selected weapon"))
        self.restage_models_btn.setText(self._tr("Re-stage existing models"))
        self.favorite_check.setText(self._tr("Favorite (Favorites tab)"))
        self._rebuild_filter_lookups()

    def _rebuild_filter_lookups(self):
        current_category = self.category.currentData()
        current_country = self.country.currentData()
        self.category.clear()
        self.country.clear()
        self.category.addItem(self._tr("All Categories"), "")
        self.country.addItem(self._tr("All Countries"), "")
        with self.db.get_session() as session:
            seen_categories = set()
            for item in session.query(Category).order_by(Category.name.asc()).all():
                key = (item.name or "").strip().lower()
                if not key or key in seen_categories:
                    continue
                seen_categories.add(key)
                self.category.addItem(str(self._tr_data(item.name)), item.name)
            seen_countries = set()
            for item in session.query(Country).order_by(Country.name.asc()).all():
                key = (item.name or "").strip().lower()
                if not key or key in seen_countries:
                    continue
                seen_countries.add(key)
                self.country.addItem(str(self._tr_data(item.name)), item.name)
        idx_cat = self.category.findData(current_category)
        idx_country = self.country.findData(current_country)
        self.category.setCurrentIndex(idx_cat if idx_cat >= 0 else 0)
        self.country.setCurrentIndex(idx_country if idx_country >= 0 else 0)

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def _tr_data(self, value):
        if self.lang_manager:
            return self.lang_manager.tr_data(value)
        return value

    def _reselect_weapon_by_id(self, weapon_id: int):
        for row in range(self.model.rowCount()):
            idx = self.model.index(row, 0)
            weapon = idx.data(Qt.ItemDataRole.UserRole) or {}
            if int(weapon.get("id", -1)) == int(weapon_id):
                self.list.setCurrentIndex(idx)
                self._selected_weapon = weapon
                self.selected_weapon_lbl.setText(
                    f"{self._tr('Selected weapon:')} {weapon.get('weapon_name', self._tr('Unknown'))} ({weapon.get('model', '-')})"
                )
                self._sync_favorite_checkbox()
                break

    def _toggle_gallery_tools(self):
        expanded = self.toggle_gallery_tools_btn.isChecked()
        self.gallery_tools_host.setVisible(expanded)
        self.toggle_gallery_tools_btn.setText("∆" if expanded else "▷")