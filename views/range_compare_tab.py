"""Dedicated map tab: multi-weapon range comparison (ranges only)."""
from __future__ import annotations

import json
import logging
import math

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from views.map_view import MapView

logger = logging.getLogger(__name__)

COMPARE_COLORS = [
    "#00e5ff",
    "#ff6b6b",
    "#ffd166",
    "#06d6a0",
    "#9b5de5",
    "#f15bb5",
    "#00bbf9",
    "#fee440",
    "#8ac926",
    "#ff9f1c",
    "#118ab2",
    "#ef476f",
]


class RangeCompareTab(QWidget):
    """Isolated map workspace for comparing weapon ranges side-by-side."""

    compare_changed = pyqtSignal(int)

    def __init__(self, db_manager, tile_cache, settings=None, lang_manager=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.tile_cache = tile_cache
        self.settings = settings
        self.lang_manager = lang_manager
        self._catalog: list[dict] = []
        self._on_map: dict[int, dict] = {}
        self._color_idx = 0
        self._place_queue: list[dict] = []
        self._place_mode = False
        self._catalog_loaded = False
        self._focused_weapon_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # —— Side panel (weapon picker + legend) ——
        side = QFrame()
        side.setObjectName("rangeCompareSide")
        side.setMinimumWidth(260)
        side.setMaximumWidth(360)
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(10, 10, 10, 10)
        side_l.setSpacing(8)

        title = QLabel(self._tr("Range comparison"))
        title.setObjectName("rangeCompareTitle")
        side_l.addWidget(title)

        hint = QLabel(
            self._tr("Select weapons and add them to the map. Only range rings are shown.")
        )
        hint.setWordWrap(True)
        hint.setObjectName("rangeCompareHint")
        side_l.addWidget(hint)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self._tr("Search weapons…"))
        self.search_edit.textChanged.connect(self._filter_list)
        side_l.addWidget(self.search_edit)

        self.weapon_list = QListWidget()
        self.weapon_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.weapon_list.setAlternatingRowColors(True)
        side_l.addWidget(self.weapon_list, 1)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton(self._tr("Add to map"))
        self.add_btn.clicked.connect(self._add_selected)
        self.place_btn = QPushButton(self._tr("Click to place"))
        self.place_btn.setCheckable(True)
        self.place_btn.toggled.connect(self._toggle_place_mode)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.place_btn)
        side_l.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        self.fit_btn = QPushButton(self._tr("Fit all"))
        self.fit_btn.clicked.connect(self._fit_all)
        self.clear_btn = QPushButton(self._tr("Clear"))
        self.clear_btn.clicked.connect(self._clear_all)
        btn_row2.addWidget(self.fit_btn)
        btn_row2.addWidget(self.clear_btn)
        side_l.addLayout(btn_row2)

        layer_row = QHBoxLayout()
        self.front_btn = QPushButton(self._tr("Bring forward"))
        self.back_btn = QPushButton(self._tr("Send backward"))
        self.front_btn.clicked.connect(self._bring_selected_forward)
        self.back_btn.clicked.connect(self._send_selected_backward)
        layer_row.addWidget(self.front_btn)
        layer_row.addWidget(self.back_btn)
        side_l.addLayout(layer_row)

        legend_title = QLabel(self._tr("On map"))
        side_l.addWidget(legend_title)
        self.legend_list = QListWidget()
        self.legend_list.setMaximumHeight(160)
        side_l.addWidget(self.legend_list)

        self.count_label = QLabel("0")
        side_l.addWidget(self.count_label)

        splitter.addWidget(side)

        # —— Map area ——
        map_wrap = QWidget()
        map_l = QVBoxLayout(map_wrap)
        map_l.setContentsMargins(0, 0, 0, 0)
        map_l.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 0)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_out_btn = QPushButton("−")
        self.center_btn = QPushButton(self._tr("Center"))
        self.zoom_in_btn.setFixedWidth(36)
        self.zoom_out_btn.setFixedWidth(36)
        toolbar.addWidget(self.zoom_in_btn)
        toolbar.addWidget(self.zoom_out_btn)
        toolbar.addWidget(self.center_btn)
        toolbar.addStretch(1)
        map_l.addLayout(toolbar)

        self.map_view = MapView(tile_cache, db_manager, qsettings=settings)
        self.map_view.set_compare_mode(True)
        map_l.addWidget(self.map_view, 1)

        splitter.addWidget(map_wrap)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 900])

        self.zoom_in_btn.clicked.connect(self.map_view.zoom_in)
        self.zoom_out_btn.clicked.connect(self.map_view.zoom_out)
        self.center_btn.clicked.connect(self._center_default)
        self.map_view.compare_point_selected.connect(self._on_map_click_place)
        self.map_view.compare_weapon_moved.connect(self._on_compare_weapon_moved)
        self.map_view.compare_weapon_focus.connect(self._on_compare_weapon_focus)
        self.legend_list.currentRowChanged.connect(self._on_legend_row_changed)

    def on_tab_activated(self):
        """Called when user switches to Map tab — fix WebEngine layout, load catalog once."""
        if self.map_view and self.map_view.page():
            self.map_view.page().runJavaScript(
                "if (window.map && map.invalidateSize) { map.invalidateSize(false); }"
            )
        if not self._catalog_loaded:
            self.refresh_catalog()
            self._catalog_loaded = True

    def _tr(self, text: str) -> str:
        if self.lang_manager and hasattr(self.lang_manager, "tr"):
            return self.lang_manager.tr(text)
        return text

    def refresh_catalog(self):
        self._catalog = []
        if not self.db:
            self._filter_list()
            return
        try:
            total = self.db.get_weapon_count()
            rows = self.db.get_weapons_paginated(0, max(total, 1), filters={})
            for w in rows:
                wid = w.get("id")
                if wid is None:
                    continue
                self._catalog.append(
                    {
                        "id": int(wid),
                        "weapon_name": w.get("weapon_name") or "",
                        "range_km": float(w.get("range_km") or 0),
                        "origin_lat": w.get("origin_lat"),
                        "origin_lon": w.get("origin_lon"),
                        "warhead_weight_kg": w.get("warhead_weight_kg"),
                    }
                )
        except Exception:
            logger.debug("range compare catalog load failed", exc_info=True)
        self._filter_list()

    def _filter_list(self):
        q = (self.search_edit.text() or "").strip().lower()
        self.weapon_list.clear()
        for w in self._catalog:
            name = str(w.get("weapon_name") or "")
            if q and q not in name.lower():
                continue
            item = QListWidgetItem(name)
            rk = w.get("range_km") or 0
            item.setToolTip(f"{name}\n{rk:.0f} km")
            item.setData(Qt.ItemDataRole.UserRole, w)
            if int(w["id"]) in self._on_map:
                item.setForeground(Qt.GlobalColor.darkGray)
            self.weapon_list.addItem(item)

    def _next_color(self) -> str:
        c = COMPARE_COLORS[self._color_idx % len(COMPARE_COLORS)]
        self._color_idx += 1
        return c

    def _default_center(self) -> tuple[float, float]:
        if self.settings:
            try:
                lat = float(self.settings.value("map/default_lat", 31.5))
                lon = float(self.settings.value("map/default_lon", 34.8))
                return lat, lon
            except Exception:
                pass
        return 31.5, 34.8

    def _center_default(self):
        lat, lon = self._default_center()
        self.map_view.center_on_coordinates(lat, lon, zoom=6)

    def _offset_lat_lon(self, lat: float, lon: float, index: int) -> tuple[float, float]:
        """Spiral offset so multiple weapons without coords remain visible."""
        if index <= 0:
            return lat, lon
        angle = index * 1.047
        km = 12 + (index * 8)
        dlat = (km / 111.0) * math.cos(angle)
        dlon = (km / (111.0 * max(0.2, math.cos(math.radians(lat))))) * math.sin(angle)
        return lat + dlat, lon + dlon

    def _weapon_entry(self, weapon: dict, lat: float, lon: float) -> dict:
        wid = int(weapon["id"])
        existing = self._on_map.get(wid)
        color = existing["color"] if existing else self._next_color()
        max_km = float(weapon.get("range_km") or 0)
        min_km = max(max_km * 0.35, 0.0)
        layer_order = existing["layer_order"] if existing else len(self._on_map)
        return {
            "id": wid,
            "name": str(weapon.get("weapon_name") or f"Weapon {wid}"),
            "range_km": max_km,
            "min_range_km": min_km,
            "lat": float(lat),
            "lon": float(lon),
            "color": color,
            "layer_order": int(layer_order),
        }

    def _sorted_compare_payload(self) -> list[dict]:
        return sorted(self._on_map.values(), key=lambda w: int(w.get("layer_order", 0)))

    def _push_map(self):
        payload = self._sorted_compare_payload()
        self.map_view.set_compare_weapons(payload)
        self._refresh_legend()
        self.count_label.setText(self._format_count(len(payload)))
        self.compare_changed.emit(len(payload))
        self._filter_list()

    def _on_compare_weapon_moved(self, weapon_id: int, lat: float, lon: float):
        entry = self._on_map.get(int(weapon_id))
        if not entry:
            return
        entry["lat"] = float(lat)
        entry["lon"] = float(lon)

    def _on_compare_weapon_focus(self, weapon_id: int):
        self._focused_weapon_id = int(weapon_id)
        for i in range(self.legend_list.count()):
            item = self.legend_list.item(i)
            if item and int(item.data(Qt.ItemDataRole.UserRole) or -1) == int(weapon_id):
                self.legend_list.setCurrentRow(i)
                break

    def _on_legend_row_changed(self, row: int):
        if row < 0:
            return
        item = self.legend_list.item(row)
        if not item:
            return
        wid = int(item.data(Qt.ItemDataRole.UserRole) or 0)
        if wid:
            self._focused_weapon_id = wid
            self.map_view.bring_compare_weapon_front(wid)

    def _selected_legend_weapon_id(self) -> int | None:
        row = self.legend_list.currentRow()
        if row < 0:
            return self._focused_weapon_id
        item = self.legend_list.item(row)
        if not item:
            return self._focused_weapon_id
        wid = int(item.data(Qt.ItemDataRole.UserRole) or 0)
        return wid or self._focused_weapon_id

    def _bring_selected_forward(self):
        wid = self._selected_legend_weapon_id()
        if wid is None or wid not in self._on_map:
            return
        orders = [int(v.get("layer_order", 0)) for v in self._on_map.values()]
        self._on_map[wid]["layer_order"] = max(orders, default=0) + 1
        self._push_map()
        self.map_view.bring_compare_weapon_front(wid)

    def _send_selected_backward(self):
        wid = self._selected_legend_weapon_id()
        if wid is None or wid not in self._on_map:
            return
        orders = [int(v.get("layer_order", 0)) for v in self._on_map.values()]
        self._on_map[wid]["layer_order"] = min(orders, default=0) - 1
        self._push_map()
        self.map_view.send_compare_weapon_back(wid)

    def _refresh_legend(self):
        self.legend_list.blockSignals(True)
        self.legend_list.clear()
        for w in self._sorted_compare_payload():
            item = QListWidgetItem(f"● {w['name']} — {w['range_km']:.0f} km")
            item.setData(Qt.ItemDataRole.UserRole, int(w["id"]))
            try:
                from PyQt6.QtGui import QColor

                item.setForeground(QColor(w["color"]))
            except Exception:
                item.setForeground(Qt.GlobalColor.white)
            self.legend_list.addItem(item)
        self.legend_list.blockSignals(False)

    def _add_selected(self):
        items = self.weapon_list.selectedItems()
        if not items:
            return
        base_lat, base_lon = self._default_center()
        idx = len(self._on_map)
        for item in items:
            w = item.data(Qt.ItemDataRole.UserRole)
            if not w:
                continue
            wid = int(w["id"])
            lat = w.get("origin_lat")
            lon = w.get("origin_lon")
            if lat is not None and lon is not None:
                try:
                    lat, lon = float(lat), float(lon)
                except (TypeError, ValueError):
                    lat, lon = self._offset_lat_lon(base_lat, base_lon, idx)
                    idx += 1
            else:
                lat, lon = self._offset_lat_lon(base_lat, base_lon, idx)
                idx += 1
            self._on_map[wid] = self._weapon_entry(w, lat, lon)
        self._push_map()
        if self._on_map:
            self.map_view.fit_compare_bounds()

    def _toggle_place_mode(self, on: bool):
        self._place_mode = bool(on)
        items = self.weapon_list.selectedItems()
        self._place_queue = [it.data(Qt.ItemDataRole.UserRole) for it in items if it.data(Qt.ItemDataRole.UserRole)]
        if self._place_mode:
            self.place_btn.setText(self._tr("Click map…"))
            self.map_view.set_compare_place_mode(True)
        else:
            self.place_btn.setText(self._tr("Click to place"))
            self.map_view.set_compare_place_mode(False)
            self._place_queue = []

    def _on_map_click_place(self, lat: float, lon: float):
        if not self._place_mode or not self._place_queue:
            return
        w = self._place_queue.pop(0)
        wid = int(w["id"])
        self._on_map[wid] = self._weapon_entry(w, lat, lon)
        self._push_map()
        if not self._place_queue:
            self.place_btn.setChecked(False)

    def _fit_all(self):
        self.map_view.fit_compare_bounds()

    def _clear_all(self):
        self._on_map.clear()
        self._color_idx = 0
        self.map_view.clear_compare_weapons()
        self.legend_list.clear()
        self.count_label.setText(self._format_count(0))
        self.compare_changed.emit(0)
        self._filter_list()

    def add_weapon(self, weapon: dict):
        """Add one weapon ring to the compare map (from external selection)."""
        if not weapon or weapon.get("id") is None:
            return
        wid = int(weapon["id"])
        base_lat, base_lon = self._default_center()
        lat = weapon.get("origin_lat")
        lon = weapon.get("origin_lon")
        if lat is not None and lon is not None:
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                lat, lon = self._offset_lat_lon(base_lat, base_lon, len(self._on_map))
        else:
            lat, lon = self._offset_lat_lon(base_lat, base_lon, len(self._on_map))
        self._on_map[wid] = self._weapon_entry(weapon, lat, lon)
        self._push_map()
        self.map_view.fit_compare_bounds()

    def _format_count(self, n: int) -> str:
        template = self._tr("{n} weapons on map")
        return template.replace("{n}", str(int(n)))

    def retranslate(self):
        """Refresh visible labels after language change."""
        self.add_btn.setText(self._tr("Add to map"))
        self.place_btn.setText(self._tr("Click to place"))
        self.fit_btn.setText(self._tr("Fit all"))
        self.clear_btn.setText(self._tr("Clear"))
        self.front_btn.setText(self._tr("Bring forward"))
        self.back_btn.setText(self._tr("Send backward"))
        self.center_btn.setText(self._tr("Center"))
        self.search_edit.setPlaceholderText(self._tr("Search weapons…"))
        self.count_label.setText(self._format_count(len(self._on_map)))
