"""
Favorites-only dashboard: same weapon cards as Control Panel, filter/sort for quick access.
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QListView,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QPushButton,
    QLabel,
    QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QIcon, QPixmap

from database.db_manager import Category
from views.dashboard_view import CardDelegate


class FavoritesDashboardView(QWidget):
    """Weapon cards (favorites only) with category + range filters and sorting."""

    weapon_selected = pyqtSignal(dict)
    weapon_open_requested = pyqtSignal(dict)

    def __init__(self, db_manager, lang_manager=None):
        super().__init__()
        self.db = db_manager
        self.lang_manager = lang_manager
        layout = QVBoxLayout(self)

        self._title_lbl = QLabel("Favorites dashboard")
        layout.addWidget(self._title_lbl)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search favorites...")
        self.category = QComboBox()
        self.category.addItem("All Categories", "")
        self.min_range = QDoubleSpinBox()
        self.min_range.setRange(0.0, 1_000_000.0)
        self.min_range.setDecimals(1)
        self.min_range.setSpecialValueText("Min km")
        self.min_range.setMinimum(-1.0)
        self.min_range.setValue(-1.0)
        self.max_range = QDoubleSpinBox()
        self.max_range.setRange(0.0, 1_000_000.0)
        self.max_range.setDecimals(1)
        self.max_range.setSpecialValueText("Max km")
        self.max_range.setMinimum(-1.0)
        self.max_range.setValue(-1.0)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Sort: Name A→Z", ("weapon_name", "asc"))
        self.sort_combo.addItem("Sort: Name Z→A", ("weapon_name", "desc"))
        self.sort_combo.addItem("Sort: Range ↑", ("range_km", "asc"))
        self.sort_combo.addItem("Sort: Range ↓", ("range_km", "desc"))
        self.sort_combo.addItem("Sort: Category A→Z", ("category", "asc"))
        self.sort_combo.addItem("Sort: Category Z→A", ("category", "desc"))

        self.apply_btn = QPushButton("Apply")
        self.clear_btn = QPushButton("Reset")

        filters.addWidget(self.search, 2)
        filters.addWidget(self.category, 1)
        filters.addWidget(self.min_range, 1)
        filters.addWidget(self.max_range, 1)
        filters.addWidget(self.sort_combo, 1)
        filters.addWidget(self.apply_btn)
        filters.addWidget(self.clear_btn)
        layout.addLayout(filters)

        self.list = QListView(self)
        self.model = QStandardItemModel(self)
        self.list.setModel(self.model)
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setItemDelegate(CardDelegate(self.lang_manager, self.list))
        self.list.setGridSize(QSize(328, 156))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setSpacing(10)
        layout.addWidget(self.list)
        self._thumb_icon_cache: dict[tuple[str, int], QIcon] = {}

        self.list.clicked.connect(self._on_click)
        self.list.doubleClicked.connect(self._on_double_click)
        self.apply_btn.clicked.connect(self.refresh)
        self.clear_btn.clicked.connect(self._reset_filters)
        self.search.returnPressed.connect(self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.sort_combo.currentIndexChanged.connect(self.refresh)

        self._load_categories()
        self.refresh()

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def _tr_data(self, value):
        if self.lang_manager:
            return self.lang_manager.tr_data(value)
        return value

    def _load_categories(self):
        self.category.blockSignals(True)
        try:
            current = self.category.currentData()
            self.category.clear()
            self.category.addItem(self._tr("All Categories"), "")
            with self.db.get_session() as session:
                seen = set()
                for item in session.query(Category).order_by(Category.name.asc()).all():
                    key = (item.name or "").strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    self.category.addItem(str(self._tr_data(item.name)), item.name)
            idx = self.category.findData(current)
            self.category.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self.category.blockSignals(False)

    def _reset_filters(self):
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.min_range.setValue(-1.0)
        self.max_range.setValue(-1.0)
        self.sort_combo.setCurrentIndex(0)
        self.refresh()

    def _filter_dict(self) -> dict:
        filters: dict = {"favorite": True}
        if self.search.text().strip():
            filters["search"] = self.search.text().strip()
        if self.category.currentData():
            filters["category"] = self.category.currentData()
        if self.min_range.value() >= 0:
            filters["min_range"] = float(self.min_range.value())
        if self.max_range.value() >= 0:
            filters["max_range"] = float(self.max_range.value())
        return filters

    def refresh(self):
        self.model.clear()
        sort_by, sort_order = self.sort_combo.currentData()
        weapons = self.db.get_weapons_paginated(
            0,
            500,
            filters=self._filter_dict(),
            sort_by=sort_by,
            sort_order=sort_order,
        )
        for weapon in weapons:
            item = QStandardItem(weapon.get("weapon_name", "Unknown"))
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
                    item.setData(icon, Qt.ItemDataRole.DecorationRole)
            self.model.appendRow(item)

    def _on_click(self, index):
        weapon = index.data(Qt.ItemDataRole.UserRole)
        if weapon:
            self.weapon_selected.emit(weapon)

    def _on_double_click(self, index):
        weapon = index.data(Qt.ItemDataRole.UserRole)
        if weapon:
            self.weapon_open_requested.emit(weapon)

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.list.setItemDelegate(CardDelegate(self.lang_manager, self.list))
        self.retranslate_ui()

    def retranslate_ui(self):
        self.search.setPlaceholderText(self._tr("Search favorites..."))
        self.apply_btn.setText(self._tr("Apply"))
        self.clear_btn.setText(self._tr("Reset"))
        self.min_range.setSpecialValueText(self._tr("Min km"))
        self.max_range.setSpecialValueText(self._tr("Max km"))
        # Rebuild sort labels (indices preserved by data)
        sort_data = [self.sort_combo.itemData(i) for i in range(self.sort_combo.count())]
        labels = [
            self._tr("Sort: Name A→Z"),
            self._tr("Sort: Name Z→A"),
            self._tr("Sort: Range ↑"),
            self._tr("Sort: Range ↓"),
            self._tr("Sort: Category A→Z"),
            self._tr("Sort: Category Z→A"),
        ]
        self.sort_combo.blockSignals(True)
        try:
            for i, lab in enumerate(labels):
                if i < self.sort_combo.count():
                    self.sort_combo.setItemText(i, lab)
            cur = self.sort_combo.currentIndex()
            self.sort_combo.setCurrentIndex(cur if cur >= 0 else 0)
        finally:
            self.sort_combo.blockSignals(False)
        self._load_categories()
        self._title_lbl.setText(self._tr("Favorites dashboard"))
