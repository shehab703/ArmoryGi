from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QHeaderView,
    QAbstractItemView,
    QLineEdit,
    QComboBox,
    QLabel,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtGui import QDrag, QIcon, QPixmap
from PyQt6.QtCore import QMimeData
import json
from pathlib import Path
from database.db_manager import Category, Country, GuidanceType, PropulsionType
from utils.ui_helpers import style_data_table


class DataGridView(QWidget):
    weapon_selected = pyqtSignal(dict)
    data_changed = pyqtSignal()

    def __init__(self, db_manager, parent=None, lang_manager=None):
        super().__init__(parent)
        self.db = db_manager
        self.lang_manager = lang_manager
        self._weapons = []
        self._selected_weapon = None
        self._active_filters = {}
        self._is_loading = False
        self._drag_start_pos = QPoint()
        self._on_add = None
        self._on_edit = None
        self._on_delete = None
        self._on_export = None

        layout = QVBoxLayout(self)

        # Filter/search bar similar to modern data grid header filters.
        filters_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search model, name, manufacturer...")
        self.category_filter = QComboBox()
        self.country_filter = QComboBox()
        self.min_range_input = QLineEdit()
        self.max_range_input = QLineEdit()
        self.min_range_input.setPlaceholderText("Min range km")
        self.max_range_input.setPlaceholderText("Max range km")
        self.apply_btn = QPushButton("Apply")
        self.clear_btn = QPushButton("Clear")
        self.search_lbl = QLabel("Search")
        self.category_lbl = QLabel("Category")
        self.country_lbl = QLabel("Country")

        self.category_filter.addItem("All Categories", "")
        self.country_filter.addItem("All Countries", "")
        self._load_filter_options()

        field_align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        for widget in (self.search_input, self.min_range_input, self.max_range_input):
            widget.setAlignment(field_align)

        filters_layout.addWidget(self.search_lbl)
        filters_layout.addWidget(self.search_input, 2)
        filters_layout.addWidget(self.category_lbl)
        filters_layout.addWidget(self.category_filter, 1)
        filters_layout.addWidget(self.country_lbl)
        filters_layout.addWidget(self.country_filter, 1)
        filters_layout.addWidget(self.min_range_input)
        filters_layout.addWidget(self.max_range_input)
        filters_layout.addWidget(self.apply_btn)
        filters_layout.addWidget(self.clear_btn)
        layout.addLayout(filters_layout)

        # Action panel placed under filters inside Data Grid interface.
        actions_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        self.export_btn = QPushButton("Reports")
        actions_layout.addWidget(self.add_btn)
        actions_layout.addWidget(self.edit_btn)
        actions_layout.addWidget(self.delete_btn)
        actions_layout.addWidget(self.export_btn)
        actions_layout.addStretch(1)
        layout.addLayout(actions_layout)

        self.table = QTableView(self)
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(
            [
                "Category", "Country", "Missile Name", "Type", "Length", "Diameter", "Weight",
                "Warhead Type", "Warhead Weight", "Range (km)", "Speed (Mach)", "Guidance",
                "Propulsion", "Platform", "Status", "Manufacturer", "Introduction Year", "Image Preview"
            ]
        )
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setDragEnabled(True)
        style_data_table(self.table, min_row_height=40)
        layout.addWidget(self.table)

        self.table.clicked.connect(self._on_click)
        self.table.doubleClicked.connect(self._on_click)
        self._model.itemChanged.connect(self._on_item_changed)
        self.table.viewport().installEventFilter(self)
        self.apply_btn.clicked.connect(self.load_weapons)
        self.clear_btn.clicked.connect(self._clear_filters)
        self.search_input.returnPressed.connect(self.load_weapons)
        self.add_btn.clicked.connect(self._emit_add)
        self.edit_btn.clicked.connect(self._emit_edit)
        self.delete_btn.clicked.connect(self._emit_delete)
        self.export_btn.clicked.connect(self._emit_export)
        self.retranslate_ui()

    def _on_click(self, index):
        weapon = index.sibling(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if weapon:
            self._selected_weapon = weapon
            self.weapon_selected.emit(self._selected_weapon)

    def _load_filter_options(self):
        with self.db.get_session() as session:
            categories = session.query(Category).order_by(Category.name.asc()).all()
            countries = session.query(Country).order_by(Country.name.asc()).all()
        self.category_filter.clear()
        self.country_filter.clear()
        self.category_filter.addItem(self._tr("All Categories"), "")
        self.country_filter.addItem(self._tr("All Countries"), "")
        for row in categories:
            name = str(row.name)
            self.category_filter.addItem(str(self._tr_data(name)), name)
        for row in countries:
            name = str(row.name)
            self.country_filter.addItem(str(self._tr_data(name)), name)

    def _build_filters(self):
        filters = {}
        if self.search_input.text().strip():
            filters["search"] = self.search_input.text().strip()
        if self.category_filter.currentData():
            filters["category"] = self.category_filter.currentData()
        if self.country_filter.currentData():
            filters["country"] = self.country_filter.currentData()
        if self.min_range_input.text().strip():
            try:
                filters["min_range"] = float(self.min_range_input.text().strip())
            except ValueError:
                pass
        if self.max_range_input.text().strip():
            try:
                filters["max_range"] = float(self.max_range_input.text().strip())
            except ValueError:
                pass
        self._active_filters = filters
        return filters

    def _clear_filters(self):
        self.search_input.clear()
        self.category_filter.setCurrentIndex(0)
        self.country_filter.setCurrentIndex(0)
        self.min_range_input.clear()
        self.max_range_input.clear()
        self.load_weapons()

    def load_weapons(self):
        self._is_loading = True
        self._weapons = self.db.get_weapons_paginated(0, 1000, filters=self._build_filters())
        self._model.removeRows(0, self._model.rowCount())
        self._model.setHorizontalHeaderLabels(
            [
                self._tr("Category"), self._tr("Country"), self._tr("Missile Name"), self._tr("Type"),
                self._tr("Length"), self._tr("Diameter"), self._tr("Weight"), self._tr("Warhead Type"),
                self._tr("Warhead Weight"), self._tr("Range (km)"), self._tr("Speed (Mach)"), self._tr("Guidance"),
                self._tr("Propulsion"), self._tr("Platform"), self._tr("Status"), self._tr("Manufacturer"),
                self._tr("Introduction Year"), self._tr("Image Preview")
            ]
        )
        cell_align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        for weapon in self._weapons:
            row_items = [
                QStandardItem(str(self._tr_data(weapon.get("category", "")))),
                QStandardItem(str(self._tr_data(weapon.get("country", "")))),
                QStandardItem(str(weapon.get("weapon_name", ""))),
                QStandardItem(str(weapon.get("model", ""))),
                QStandardItem(str(weapon.get("length_m", ""))),
                QStandardItem(str(weapon.get("diameter_m", ""))),
                QStandardItem(str(weapon.get("weight_kg", ""))),
                QStandardItem(str(self._tr_data(weapon.get("warhead_type", "")))),
                QStandardItem(str(weapon.get("warhead_weight_kg", ""))),
                QStandardItem(str(weapon.get("range_km", ""))),
                QStandardItem(str(weapon.get("speed_mach", ""))),
                QStandardItem(str(self._tr_data(weapon.get("guidance", "")))),
                QStandardItem(str(self._tr_data(weapon.get("propulsion", "")))),
                QStandardItem(str(self._tr_data(weapon.get("platform", "")))),
                QStandardItem(str(self._tr_data(weapon.get("status", "")))),
                QStandardItem(str(self._tr_data(weapon.get("manufacturer", "")))),
                QStandardItem(str(weapon.get("intro_year", ""))),
                QStandardItem(str(Path(str(weapon.get("primary_image", ""))).name if weapon.get("primary_image") else "")),
            ]
            for item in row_items:
                item.setTextAlignment(cell_align)
                item.setEditable(True)
            row_items[17].setEditable(False)
            primary_image = weapon.get("primary_image")
            if primary_image and Path(str(primary_image)).exists():
                pixmap = QPixmap(str(primary_image))
                if not pixmap.isNull():
                    row_items[17].setIcon(QIcon(pixmap))
            for item in row_items:
                item.setData(weapon, Qt.ItemDataRole.UserRole)
                item.setData(weapon.get("id"), Qt.ItemDataRole.UserRole + 1)
            self._model.appendRow(row_items)
        self.table.resizeRowsToContents()
        self._is_loading = False
        self.data_changed.emit()

    def refresh(self):
        self.load_weapons()

    def get_selected_weapon(self):
        indexes = self.table.selectionModel().selectedRows()
        if indexes:
            weapon = indexes[0].sibling(indexes[0].row(), 2).data(Qt.ItemDataRole.UserRole)
            if weapon:
                self._selected_weapon = weapon
        return self._selected_weapon

    def active_filters_text(self):
        if not self._active_filters:
            return self._tr("No filters")
        return ", ".join([f"{k}={v}" for k, v in self._active_filters.items()])

    def _on_item_changed(self, item: QStandardItem):
        if self._is_loading:
            return
        row = item.row()
        id_item = self._model.item(row, 0)
        weapon_id = id_item.data(Qt.ItemDataRole.UserRole + 1)
        if not weapon_id:
            return

        column_map = {
            0: "category",
            1: "country",
            2: "weapon_name",
            3: "model",
            4: "length_m",
            5: "diameter_m",
            6: "weight_kg",
            7: "warhead_type",
            8: "warhead_weight_kg",
            9: "range_km",
            10: "speed_mach",
            11: "guidance",
            12: "propulsion",
            13: "platform",
            14: "status",
            15: "manufacturer",
            16: "intro_year",
        }
        field = column_map.get(item.column())
        if not field:
            return
        value = item.text().strip()
        if field in {"range_km", "speed_mach", "length_m", "diameter_m", "weight_kg", "warhead_weight_kg"}:
            try:
                value = float(value) if value else None
            except ValueError:
                return
        elif field in {"intro_year"}:
            try:
                value = int(value) if value else None
            except ValueError:
                return
        elif field in {"category", "country", "guidance", "propulsion"}:
            lookup_value = value
            if self.lang_manager and hasattr(self.lang_manager, "untr_data"):
                lookup_value = self.lang_manager.untr_data(value)
            with self.db.get_session() as session:
                if field == "category":
                    obj = session.query(Category).filter(Category.name == lookup_value).first()
                    if obj:
                        field, value = "category_id", obj.id
                elif field == "country":
                    obj = session.query(Country).filter(Country.name == lookup_value).first()
                    if obj:
                        field, value = "country_id", obj.id
                elif field == "guidance":
                    obj = session.query(GuidanceType).filter(GuidanceType.name == lookup_value).first()
                    if obj:
                        field, value = "guidance_id", obj.id
                elif field == "propulsion":
                    obj = session.query(PropulsionType).filter(PropulsionType.name == lookup_value).first()
                    if obj:
                        field, value = "propulsion_id", obj.id
        updated = self.db.update_weapon(int(weapon_id), {field: value})
        if updated:
            item.setData(updated.to_dict(include_images=True, include_variants=False), Qt.ItemDataRole.UserRole)

    def eventFilter(self, obj, event):
        if obj is self.table.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = event.pos()
            elif event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                if (event.pos() - self._drag_start_pos).manhattanLength() > 6:
                    weapon = self.get_selected_weapon()
                    if weapon:
                        self._start_drag(weapon)
                        return True
        return super().eventFilter(obj, event)

    def _start_drag(self, weapon: dict):
        drag = QDrag(self.table)
        mime = QMimeData()
        payload = json.dumps(weapon)
        mime.setData("application/x-armory-weapon", payload.encode("utf-8"))
        mime.setText(payload)
        drag.setMimeData(mime)
        drag.exec()

    def set_action_handlers(self, on_add, on_edit, on_delete, on_export):
        self._on_add = on_add
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._on_export = on_export

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.retranslate_ui()

    def retranslate_ui(self):
        self.search_lbl.setText(self._tr("Search"))
        self.category_lbl.setText(self._tr("Category"))
        self.country_lbl.setText(self._tr("Country"))
        self.search_input.setPlaceholderText(self._tr("Search model, name, manufacturer..."))
        self.min_range_input.setPlaceholderText(self._tr("Min range km"))
        self.max_range_input.setPlaceholderText(self._tr("Max range km"))
        self.apply_btn.setText(self._tr("Apply"))
        self.clear_btn.setText(self._tr("Clear"))
        self.add_btn.setText(self._tr("Add"))
        self.edit_btn.setText(self._tr("Edit"))
        self.delete_btn.setText(self._tr("Delete"))
        self.export_btn.setText(self._tr("Reports"))
        self._load_filter_options()
        self.load_weapons()

    def _emit_add(self):
        if callable(self._on_add):
            self._on_add()

    def _emit_edit(self):
        if callable(self._on_edit):
            self._on_edit()

    def _emit_delete(self):
        if callable(self._on_delete):
            self._on_delete()

    def _emit_export(self):
        if callable(self._on_export):
            self._on_export()

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def _tr_data(self, value):
        if self.lang_manager:
            return self.lang_manager.tr_data(value)
        return value