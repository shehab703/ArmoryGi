"""
Dedicated reports workspace: edit report framing (title, intro, closing notes)
and preview HTML before exporting DOCX/PDF or spreadsheet data.
"""
from __future__ import annotations

import tempfile
import math
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSplitter,
    QScrollArea,
    QFrame,
    QLabel,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QCheckBox,
    QDoubleSpinBox,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QAbstractItemView,
    QTextBrowser,
    QSizePolicy,
    QToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer
from PyQt6.QtGui import QDesktopServices, QImage, QPixmap
from PyQt6.QtCore import QUrl

from utils.exporters import Exporter
from utils import weapon_reports
from views.map_view import MapView
from utils.report_preview import (
    REPORT_KIND_DATA_EXPORT,
    REPORT_KIND_INDIVIDUAL,
    REPORT_KIND_MULTI_COMPARE,
    REPORT_KIND_BY_CATEGORY,
    REPORT_KIND_FULL_SPECS,
    build_preview_html,
)
from utils.spec_fields import SPEC_FIELDS, save_spec_keys, resolve_spec_keys
from utils.gmdb_sources import get_gmdb_options
from utils.ai_prompts import build_report_assessment_prompt
from utils.ai_service import (
    get_ollama_client,
    is_ai_enabled,
    AI_MODEL_KEY,
    AI_BASE_URL_KEY,
    AI_TIMEOUT_S_KEY,
)


class ClickableMapLabel(QLabel):
    point_clicked = pyqtSignal(int, int)
    drag_started = pyqtSignal(int, int)
    drag_moved = pyqtSignal(int, int)
    drag_finished = pyqtSignal(int, int)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._press_pos: Optional[tuple[int, int]] = None
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x = int(event.position().x())
            y = int(event.position().y())
            self._press_pos = (x, y)
            self._dragging = False
            self.drag_started.emit(x, y)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            x = int(event.position().x())
            y = int(event.position().y())
            if self._press_pos:
                dx = x - self._press_pos[0]
                dy = y - self._press_pos[1]
                if (dx * dx + dy * dy) >= 16:
                    self._dragging = True
            self.drag_moved.emit(x, y)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x = int(event.position().x())
            y = int(event.position().y())
            self.drag_finished.emit(x, y)
            if not self._dragging:
                self.point_clicked.emit(x, y)
            self._press_pos = None
            self._dragging = False
        super().mouseReleaseEvent(event)


class CollapsibleSection(QFrame):
    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._toggle = QToolButton(self)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setText(title)
        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(self._toggle)
        root.addWidget(self._content)
        self._toggle.toggled.connect(self._set_expanded)
        self._set_expanded(expanded)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_title(self, title: str):
        self._toggle.setText(title)

    def _set_expanded(self, expanded: bool):
        self._content.setVisible(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )


class ReportWorkspaceView(QWidget):
    """Split UI: edit panel (left) + HTML preview (right)."""

    def __init__(self, db_manager, tile_cache, parent=None, lang_manager=None, settings=None):
        super().__init__(parent)
        self.db = db_manager
        self.tile_cache = tile_cache
        self.lang_manager = lang_manager
        self.settings = settings
        self._all_weapons: list = []
        self._drag_start_xy: Optional[tuple[int, int]] = None
        self._drag_start_center: Optional[tuple[float, float]] = None
        self._default_lat = 31.5
        self._default_lon = 34.8
        if self.settings is not None:
            self._default_lat = float(self.settings.value("map/default_lat", 31.5, float))
            self._default_lon = float(self.settings.value("map/default_lon", 34.8, float))
        self._map_view_lat = self._default_lat
        self._map_view_lon = self._default_lon
        self._use_interactive_map_picker = False
        self._ai_thread: QThread | None = None
        self._last_preview_context: tuple[str, Optional[int]] | None = None
        self._last_map_state: tuple | None = None
        self._preview_refresh_timer = QTimer(self)
        self._preview_refresh_timer.setSingleShot(True)
        self._preview_refresh_timer.timeout.connect(self._refresh_preview_now)

        root = QVBoxLayout(self)
        self._header_lbl = QLabel("Reports workspace")
        self._header_lbl.setStyleSheet("font-size:16px;font-weight:700;color:#58d8ff;")
        root.addWidget(self._header_lbl)

        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)

        # --- Edit panel (scrollable) ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        edit_host = QWidget()
        edit = QVBoxLayout(edit_host)
        edit.addWidget(QLabel("Report type"))
        self.report_combo = QComboBox()
        self.report_combo.addItem("Data export (spreadsheet / JSON)", REPORT_KIND_DATA_EXPORT)
        self.report_combo.addItem(
            "Individual weapon report (with pictures)", REPORT_KIND_INDIVIDUAL
        )
        self.report_combo.addItem(
            "Multi-weapon comparison (with pictures)", REPORT_KIND_MULTI_COMPARE
        )
        self.report_combo.addItem(
            "Weapon list by category (grouped grid)", REPORT_KIND_BY_CATEGORY
        )
        self.report_combo.addItem(
            "Complete full specifications catalog", REPORT_KIND_FULL_SPECS
        )
        self.report_combo.currentIndexChanged.connect(self._on_report_type_changed)
        edit.addWidget(self.report_combo)

        self.include_map_cb = QCheckBox(
            "Include range & effects map diagram (individual export only)"
        )
        self.include_map_cb.setChecked(True)
        self.include_map_cb.stateChanged.connect(lambda _: self.refresh_preview())
        edit.addWidget(self.include_map_cb)
        self.include_title_cb = QCheckBox("Include title")
        self.include_title_cb.setChecked(True)
        self.include_intro_cb = QCheckBox("Include introduction")
        self.include_intro_cb.setChecked(True)
        self.include_specs_cb = QCheckBox("Include specifications")
        self.include_specs_cb.setChecked(True)
        self.include_gallery_cb = QCheckBox("Include gallery images")
        self.include_gallery_cb.setChecked(True)
        self.include_closing_cb = QCheckBox("Include closing notes")
        self.include_closing_cb.setChecked(True)
        sections_row_1 = QHBoxLayout()
        sections_row_1.addWidget(self.include_title_cb)
        sections_row_1.addWidget(self.include_intro_cb)
        sections_row_1.addWidget(self.include_closing_cb)
        sections_row_2 = QHBoxLayout()
        sections_row_2.addWidget(self.include_specs_cb)
        sections_row_2.addWidget(self.include_gallery_cb)
        sections_row_2.addWidget(self.include_map_cb)
        edit.addLayout(sections_row_1)
        edit.addLayout(sections_row_2)

        self.map_section = CollapsibleSection("Map settings", expanded=True)
        map_section_layout = self.map_section.content_layout()
        self.map_settings_lbl = QLabel("Map settings (for report map image)")
        map_section_layout.addWidget(self.map_settings_lbl)
        map_frame = QFrame()
        map_frame.setFrameShape(QFrame.Shape.StyledPanel)
        map_layout = QVBoxLayout(map_frame)
        map_grid = QGridLayout()
        self.map_lat = QDoubleSpinBox()
        self.map_lat.setRange(-90, 90)
        self.map_lat.setDecimals(6)
        self.map_lat.setValue(self._default_lat)
        self.map_lon = QDoubleSpinBox()
        self.map_lon.setRange(-180, 180)
        self.map_lon.setDecimals(6)
        self.map_lon.setValue(self._default_lon)
        self._map_view_lat = float(self.map_lat.value())
        self._map_view_lon = float(self.map_lon.value())
        self.map_zoom = QSpinBox()
        self.map_zoom.setRange(1, 18)
        self.map_zoom.setValue(7)
        self.map_basemap = QComboBox()
        self.map_basemap.addItem("dark", "dark")
        self.map_basemap.addItem("satellite", "satellite")
        self.map_basemap.addItem("osm", "osm")
        self.map_basemap.addItem("topo", "topo")
        for label, data in get_gmdb_options(self.settings):
            self.map_basemap.addItem(label, data)
        map_grid.addWidget(QLabel("Lat"), 0, 0)
        map_grid.addWidget(self.map_lat, 0, 1)
        map_grid.addWidget(QLabel("Lon"), 0, 2)
        map_grid.addWidget(self.map_lon, 0, 3)
        map_grid.addWidget(QLabel("Zoom"), 1, 0)
        map_grid.addWidget(self.map_zoom, 1, 1)
        map_grid.addWidget(QLabel("Basemap"), 1, 2)
        map_grid.addWidget(self.map_basemap, 1, 3)
        map_layout.addLayout(map_grid)
        try:
            self.map_picker = MapView(self.tile_cache, self.db, offline_only_tiles=True)
            self.map_picker.setMinimumHeight(240)
            self.map_picker.controller.target_point_selected.connect(self._on_real_map_point_selected)
            self._use_interactive_map_picker = True
        except Exception:
            self.map_picker = ClickableMapLabel("Map preview (click to set center)")
            self.map_picker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.map_picker.setMinimumHeight(240)
            self.map_picker.setStyleSheet("background:#0f1720;border:1px solid #304458;border-radius:8px;color:#9db0c3;")
            self.map_picker.setScaledContents(False)
            self.map_picker.point_clicked.connect(self._on_map_picker_clicked)
            self.map_picker.drag_started.connect(self._on_map_drag_started)
            self.map_picker.drag_moved.connect(self._on_map_drag_moved)
            self.map_picker.drag_finished.connect(self._on_map_drag_finished)
        map_layout.addWidget(self.map_picker)
        map_help_row = QHBoxLayout()
        self.map_help_lbl = QLabel("Drag to browse map, then click to set point")
        self.map_help_lbl.setStyleSheet("color:#9aa;")
        self.map_reset_btn = QPushButton("Reset to default center")
        self.map_reset_btn.clicked.connect(self._reset_map_center_defaults)
        map_help_row.addWidget(self.map_help_lbl, 1)
        map_help_row.addWidget(self.map_reset_btn, 0)
        map_layout.addLayout(map_help_row)
        map_section_layout.addWidget(map_frame)
        edit.addWidget(self.map_section)
        self.map_tile_status_lbl = QLabel("Tile coverage: --")
        self.map_tile_status_lbl.setStyleSheet("color:#9aa;")
        edit.addWidget(self.map_tile_status_lbl)
        self.map_lat.valueChanged.connect(self._on_location_spin_changed)
        self.map_lon.valueChanged.connect(self._on_location_spin_changed)
        self.map_zoom.valueChanged.connect(lambda _: self.refresh_preview())
        self.map_basemap.currentIndexChanged.connect(lambda _: self.refresh_preview())

        self.doc_section = CollapsibleSection("Document text settings", expanded=False)
        doc_section_layout = self.doc_section.content_layout()
        self.doc_title_lbl = QLabel("Document title (optional)")
        doc_section_layout.addWidget(self.doc_title_lbl)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Overrides default report title when filled")
        doc_section_layout.addWidget(self.title_edit)

        self.doc_intro_lbl = QLabel("Introduction / cover text (optional)")
        doc_section_layout.addWidget(self.doc_intro_lbl)
        self.intro_edit = QPlainTextEdit()
        self.intro_edit.setPlaceholderText("Shown at the top of the preview and export…")
        self.intro_edit.setMaximumHeight(100)
        doc_section_layout.addWidget(self.intro_edit)

        self.doc_closing_lbl = QLabel("Closing / appendix notes (optional)")
        doc_section_layout.addWidget(self.doc_closing_lbl)
        self.closing_edit = QPlainTextEdit()
        self.closing_edit.setPlaceholderText("Appended at end of DOCX/PDF export…")
        self.closing_edit.setMaximumHeight(90)
        doc_section_layout.addWidget(self.closing_edit)

        ai_row = QHBoxLayout()
        self.ai_intro_btn = QPushButton("AI Draft Intro")
        self.ai_intro_btn.clicked.connect(lambda: self._ai_draft_report_section("intro"))
        self.ai_summary_btn = QPushButton("AI Executive Summary")
        self.ai_summary_btn.clicked.connect(lambda: self._ai_draft_report_section("summary"))
        self.ai_closing_btn = QPushButton("AI Draft Closing")
        self.ai_closing_btn.clicked.connect(lambda: self._ai_draft_report_section("closing"))
        ai_row.addWidget(self.ai_intro_btn)
        ai_row.addWidget(self.ai_summary_btn)
        ai_row.addWidget(self.ai_closing_btn)
        ai_row.addStretch(1)
        doc_section_layout.addLayout(ai_row)
        edit.addWidget(self.doc_section)

        self.tools_section = CollapsibleSection("Weapons and export tools", expanded=True)
        tools_section_layout = self.tools_section.content_layout()
        self.file_format_lbl = QLabel("File format")
        tools_section_layout.addWidget(self.file_format_lbl)
        self.format_combo = QComboBox()
        tools_section_layout.addWidget(self.format_combo)

        self.weapons_lbl = QLabel("Weapons (for individual / comparison)")
        tools_section_layout.addWidget(self.weapons_lbl)
        self.hint_lbl = QLabel()
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setStyleSheet("color:#9aa;")
        tools_section_layout.addWidget(self.hint_lbl)

        self.weapon_list = QListWidget()
        self.weapon_list.setMinimumHeight(180)
        self.weapon_list.itemSelectionChanged.connect(self._on_weapon_selection_changed)
        tools_section_layout.addWidget(self.weapon_list)
        self.spec_fields_lbl = QLabel("Specifications fields (single view + comparison reports)")
        tools_section_layout.addWidget(self.spec_fields_lbl)
        self.spec_fields_list = QListWidget()
        self.spec_fields_list.setMinimumHeight(140)
        self.spec_fields_list.itemChanged.connect(self._on_spec_fields_changed)
        tools_section_layout.addWidget(self.spec_fields_list)

        btn_row = QHBoxLayout()
        self.preview_btn = QPushButton("Refresh preview")
        self.preview_btn.clicked.connect(self.refresh_preview)
        self.preview_pdf_btn = QPushButton("Preview PDF")
        self.preview_pdf_btn.clicked.connect(self._preview_as_pdf)
        self.export_btn = QPushButton("Export to file…")
        self.export_btn.clicked.connect(self._export_to_file)
        self.reload_btn = QPushButton("Reload list")
        self.reload_btn.clicked.connect(self.reload_weapons)
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.preview_pdf_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addWidget(self.reload_btn)
        tools_section_layout.addLayout(btn_row)
        edit.addWidget(self.tools_section)

        edit.addStretch(1)
        scroll.setWidget(edit_host)
        scroll.setMinimumWidth(340)
        split.addWidget(scroll)

        # --- Preview panel ---
        prev_frame = QFrame()
        prev_layout = QVBoxLayout(prev_frame)
        prev_layout.addWidget(QLabel("Preview"))
        self._preview_html = ""

        # Prefer a real HTML engine for fidelity + PDF print.
        self.web = None
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView  # type: ignore

            self.web = QWebEngineView()
            self.web.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            prev_layout.addWidget(self.web)
        except Exception:
            self.preview = QTextBrowser()
            self.preview.setOpenExternalLinks(False)
            self.preview.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            prev_layout.addWidget(self.preview)
        split.addWidget(prev_frame)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 900])

        self.title_edit.textChanged.connect(self.refresh_preview)
        self.intro_edit.textChanged.connect(self.refresh_preview)
        self.closing_edit.textChanged.connect(self.refresh_preview)
        self.include_title_cb.stateChanged.connect(lambda _: self.refresh_preview())
        self.include_intro_cb.stateChanged.connect(lambda _: self.refresh_preview())
        self.include_specs_cb.stateChanged.connect(lambda _: self.refresh_preview())
        self.include_gallery_cb.stateChanged.connect(lambda _: self.refresh_preview())
        self.include_closing_cb.stateChanged.connect(lambda _: self.refresh_preview())

        self.reload_weapons()
        self._load_spec_fields_selector()
        self._on_report_type_changed()
        self.refresh_preview()
        self._refresh_ai_buttons()

    def _load_spec_fields_selector(self):
        selected = set(resolve_spec_keys(self.settings))
        self.spec_fields_list.blockSignals(True)
        self.spec_fields_list.clear()
        for key, label in SPEC_FIELDS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked
            )
            self.spec_fields_list.addItem(item)
        self.spec_fields_list.blockSignals(False)

    def _on_spec_fields_changed(self, _item):
        keys = []
        for idx in range(self.spec_fields_list.count()):
            it = self.spec_fields_list.item(idx)
            if it.checkState() == Qt.CheckState.Checked:
                keys.append(str(it.data(Qt.ItemDataRole.UserRole)))
        if not keys:
            return
        save_spec_keys(self.settings, keys)
        self.refresh_preview()

    def reload_weapons(self):
        # Load full dataset in pages so the selector can scroll through all DB weapons.
        self._all_weapons = []
        offset = 0
        page_size = 1000
        while True:
            batch = self.db.get_weapons_paginated(offset, page_size, filters={})
            if not batch:
                break
            self._all_weapons.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        self.weapon_list.clear()
        for w in self._all_weapons:
            label = f"{w.get('weapon_name', '?')}  —  {w.get('model', '-')}"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, w)
            self.weapon_list.addItem(it)

    def _kind(self) -> str:
        return self.report_combo.currentData()

    def _on_report_type_changed(self):
        kind = self._kind()
        self.include_map_cb.setVisible(kind == REPORT_KIND_INDIVIDUAL)
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        if kind == REPORT_KIND_DATA_EXPORT:
            self.format_combo.addItems(["xlsx", "csv", "json", "docx", "pdf"])
            self.weapon_list.setEnabled(False)
            self.hint_lbl.setText(
                "Spreadsheet / JSON export uses the full dataset (no weapon selection)."
            )
        else:
            self.format_combo.addItems(["docx", "pdf"])
            self.weapon_list.setEnabled(True)
            if kind == REPORT_KIND_INDIVIDUAL:
                self.weapon_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                self.hint_lbl.setText(
                    "Select one weapon. Preview updates after Refresh; export embeds images."
                )
            elif kind == REPORT_KIND_MULTI_COMPARE:
                self.weapon_list.setSelectionMode(
                    QAbstractItemView.SelectionMode.ExtendedSelection
                )
                self.hint_lbl.setText("Select two or more weapons for comparison.")
            else:
                self.weapon_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                self.weapon_list.setEnabled(False)
                self.hint_lbl.setText("Uses all weapons in the database (no selection).")
        self.format_combo.blockSignals(False)
        if kind == REPORT_KIND_INDIVIDUAL:
            self._load_cached_report_drafts()
        self.refresh_preview()

    def _meta(self) -> dict:
        selected_spec_fields = resolve_spec_keys(self.settings)
        return {
            "document_title": self.title_edit.text().strip(),
            "introduction": self.intro_edit.toPlainText().strip(),
            "closing_notes": self.closing_edit.toPlainText().strip(),
            "include_title": self.include_title_cb.isChecked(),
            "include_intro": self.include_intro_cb.isChecked(),
            "include_specs": self.include_specs_cb.isChecked(),
            "include_gallery": self.include_gallery_cb.isChecked(),
            "include_closing": self.include_closing_cb.isChecked(),
            "include_map": self.include_map_cb.isChecked(),
            "lang": self.lang_manager.current_code if self.lang_manager else "en",
            "spec_fields": selected_spec_fields,
        }

    def _include_sections(self) -> dict:
        return {
            "title": self.include_title_cb.isChecked(),
            "intro": self.include_intro_cb.isChecked(),
            "specs": self.include_specs_cb.isChecked(),
            "gallery": self.include_gallery_cb.isChecked(),
            "closing": self.include_closing_cb.isChecked(),
        }

    def _selected_weapons(self) -> list:
        out = []
        for it in self.weapon_list.selectedItems():
            w = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(w, dict):
                out.append(w)
        return out

    def _ensure_full_weapon(self, w: dict) -> dict:
        wid = w.get("id")
        if not wid:
            return w
        loaded = self.db.get_weapon_by_id(int(wid), eager_load=True)
        if loaded:
            return loaded.to_dict(include_images=True, include_variants=True)
        return w

    def _preview_weapons(self) -> list:
        kind = self._kind()
        if kind == REPORT_KIND_DATA_EXPORT:
            return self._all_weapons[:50]
        if kind == REPORT_KIND_INDIVIDUAL:
            sel = self._selected_weapons()
            if len(sel) == 1:
                return [self._ensure_full_weapon(sel[0])]
            return []
        if kind == REPORT_KIND_MULTI_COMPARE:
            return [self._ensure_full_weapon(w) for w in self._selected_weapons()]
        return [self._ensure_full_weapon(w) for w in self._all_weapons]

    def _preview_context_key(self) -> tuple[str, Optional[int]]:
        kind = self._kind()
        if kind == REPORT_KIND_INDIVIDUAL:
            sel = self._selected_weapons()
            if len(sel) == 1:
                return kind, int(sel[0].get("id") or 0)
            return kind, None
        return kind, None

    def _lang_code(self) -> str:
        if self.lang_manager and getattr(self.lang_manager, "current_code", None):
            return str(self.lang_manager.current_code).strip().lower() or "en"
        return "en"

    def _load_cached_report_drafts(self):
        if not self.db:
            return
        kind, weapon_id = self._preview_context_key()
        if kind != REPORT_KIND_INDIVIDUAL or not weapon_id:
            return
        lang = self._lang_code()
        intro = self.db.get_weapon_ai_cache(int(weapon_id), "report_intro", lang)
        summary = self.db.get_weapon_ai_cache(int(weapon_id), "report_summary", lang)
        closing = self.db.get_weapon_ai_cache(int(weapon_id), "report_closing", lang)
        intro_text = str((intro or {}).get("content_text") or "").strip()
        summary_text = str((summary or {}).get("content_text") or "").strip()
        closing_text = str((closing or {}).get("content_text") or "").strip()
        combined_intro = intro_text
        if summary_text and summary_text not in combined_intro:
            combined_intro = f"{summary_text}\n\n{intro_text}".strip()
        self.intro_edit.blockSignals(True)
        self.closing_edit.blockSignals(True)
        self.intro_edit.setPlainText(combined_intro)
        self.closing_edit.setPlainText(closing_text)
        self.intro_edit.blockSignals(False)
        self.closing_edit.blockSignals(False)

    def _on_weapon_selection_changed(self):
        # AI drafts are weapon-specific; clear stale generated text on weapon switch.
        old_key = self._last_preview_context
        new_key = self._preview_context_key()
        if old_key and old_key[0] == REPORT_KIND_INDIVIDUAL and new_key[0] == REPORT_KIND_INDIVIDUAL:
            old_weapon_id = old_key[1]
            new_weapon_id = new_key[1]
            if old_weapon_id != new_weapon_id:
                self.intro_edit.clear()
                self.closing_edit.clear()
                self._load_cached_report_drafts()
        self.refresh_preview()

    def refresh_preview(self):
        self._preview_refresh_timer.start(120)

    def _refresh_preview_now(self):
        map_state = (
            bool(self._use_interactive_map_picker),
            float(self._map_view_lat),
            float(self._map_view_lon),
            float(self.map_lat.value()),
            float(self.map_lon.value()),
            int(self.map_zoom.value()),
            str(self.map_basemap.currentData() or self.map_basemap.currentText()),
        )
        if map_state != self._last_map_state:
            self._update_map_picker_preview()
            self._update_tile_coverage_status()
            self._last_map_state = map_state
        kind = self._kind()
        weapons = self._preview_weapons()
        html = build_preview_html(
            kind,
            weapons,
            meta=self._meta(),
            include_map=self.include_map_cb.isChecked() if kind == REPORT_KIND_INDIVIDUAL else False,
            include_sections=self._include_sections(),
            lang_manager=self.lang_manager,
        )
        self._last_preview_context = self._preview_context_key()
        if html == self._preview_html:
            self._refresh_ai_buttons()
            return
        self._preview_html = html
        if self.web is not None:
            self.web.setHtml(html)
        else:
            self.preview.setHtml(html)
        self._refresh_ai_buttons()

    def _refresh_ai_buttons(self):
        enabled = bool(self.settings and is_ai_enabled(self.settings))
        busy = self._ai_thread is not None
        for b in (getattr(self, "ai_intro_btn", None), getattr(self, "ai_summary_btn", None), getattr(self, "ai_closing_btn", None)):
            if b is not None:
                b.setEnabled(enabled and not busy)

    class _AiWorker(QObject):
        progress = pyqtSignal(str, str)
        finished = pyqtSignal(str, str)
        failed = pyqtSignal(str)

        def __init__(self, settings, lang_manager, report_kind: str, meta: dict, weapons: list[dict], target_section: str):
            super().__init__()
            self._settings = settings
            self._lang_manager = lang_manager
            self._report_kind = report_kind
            self._meta = meta
            self._weapons = weapons
            self._target_section = target_section

        @pyqtSlot()
        def run(self):
            try:
                client = get_ollama_client(self._settings)
                is_ar = bool(self._lang_manager and hasattr(self._lang_manager, "is_arabic") and self._lang_manager.is_arabic())
                system, user = build_report_assessment_prompt(
                    report_kind=self._report_kind,
                    meta=self._meta,
                    weapons=self._weapons,
                    is_ar=is_ar,
                    target_section=self._target_section,
                )
                buf = []
                for chunk in client.chat_stream(system=system, user=user):
                    if chunk:
                        buf.append(str(chunk))
                        self.progress.emit(self._target_section, "".join(buf)[-6000:])
                out = "".join(buf).strip()
                self.finished.emit(self._target_section, out)
            except Exception as e:
                self.failed.emit(str(e))

    def _ai_draft_report_section(self, target_section: str):
        if not (self.settings and is_ai_enabled(self.settings)):
            QMessageBox.information(self, "AI", "Enable local AI (Ollama) in Preferences first.")
            return
        if self._ai_thread is not None:
            return
        kind = str(self._kind())
        meta = self._meta()
        weapons = self._preview_weapons()
        # keep prompts small
        weapons = weapons[:6]

        thread = QThread(self)
        worker = self._AiWorker(self.settings, self.lang_manager, kind, meta, weapons, target_section)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _cleanup():
            try:
                thread.quit()
                thread.wait(1500)
            except Exception:
                pass
            self._ai_thread = None
            self._refresh_ai_buttons()
            worker.deleteLater()
            thread.deleteLater()

        def _ok(section: str, text: str):
            try:
                t = (text or "").strip()
                if not t:
                    return
                if section == "closing":
                    self.closing_edit.setPlainText(t)
                elif section == "intro":
                    self.intro_edit.setPlainText(t)
                else:
                    # summary: prepend to intro (or set if empty)
                    existing = self.intro_edit.toPlainText().strip()
                    if existing:
                        self.intro_edit.setPlainText(t + "\n\n" + existing)
                    else:
                        self.intro_edit.setPlainText(t)
                kind, weapon_id = self._preview_context_key()
                if self.db and kind == REPORT_KIND_INDIVIDUAL and weapon_id:
                    cache_key = "report_summary" if section == "summary" else ("report_intro" if section == "intro" else "report_closing")
                    self.db.save_weapon_ai_cache(
                        int(weapon_id),
                        cache_key,
                        self._lang_code(),
                        content_text=t,
                        content_json={"section": section, "text": t},
                    )
                    if section in {"intro", "summary"}:
                        self.db.save_weapon_ai_cache(
                            int(weapon_id),
                            "report_intro",
                            self._lang_code(),
                            content_text=self.intro_edit.toPlainText().strip(),
                            content_json={"section": "intro_combined", "text": self.intro_edit.toPlainText().strip()},
                        )
                self.refresh_preview()
            finally:
                _cleanup()

        def _progress(section: str, text: str):
            # Show streaming text live in the target editor.
            t = (text or "").strip()
            if not t:
                return
            if section == "closing":
                self.closing_edit.blockSignals(True)
                self.closing_edit.setPlainText(t)
                self.closing_edit.blockSignals(False)
            elif section == "intro":
                self.intro_edit.blockSignals(True)
                self.intro_edit.setPlainText(t)
                self.intro_edit.blockSignals(False)
            else:
                # summary: show in intro while streaming
                self.intro_edit.blockSignals(True)
                self.intro_edit.setPlainText(t)
                self.intro_edit.blockSignals(False)
            self.refresh_preview()

        def _fail(msg: str):
            try:
                base_url = str(self.settings.value(AI_BASE_URL_KEY, "http://localhost:11434", str) or "").strip()
                model_name = str(self.settings.value(AI_MODEL_KEY, "llama3.1", str) or "").strip() or "llama3.1"
                timeout_s = str(self.settings.value(AI_TIMEOUT_S_KEY, 180))
                QMessageBox.warning(
                    self,
                    "AI",
                    f"AI drafting failed.\n\nOllama: {base_url}\nModel: {model_name}\nTimeout: {timeout_s}s\n\n{msg}",
                )
            finally:
                _cleanup()

        worker.progress.connect(_progress)
        worker.finished.connect(_ok)
        worker.failed.connect(_fail)
        self._ai_thread = thread
        self._refresh_ai_buttons()
        thread.start()

    def _current_tile_coverage(self) -> tuple[int, int]:
        """Return (available_tiles, total_tiles) for current map settings."""
        lat = float(self.map_lat.value())
        lon = float(self.map_lon.value())
        zoom = int(self.map_zoom.value())
        basemap = str(self.map_basemap.currentData() or self.map_basemap.currentText())
        tiles_each_side = 5
        tile_size = 256

        center_world_x, center_world_y = self._latlon_to_world_px(lat, lon, zoom, tile_size)
        center_tile_x = int(center_world_x // tile_size)
        center_tile_y = int(center_world_y // tile_size)
        half = tiles_each_side // 2
        base_tile_x = center_tile_x - half
        base_tile_y = center_tile_y - half

        available = 0
        total = tiles_each_side * tiles_each_side
        for tx_off in range(tiles_each_side):
            for ty_off in range(tiles_each_side):
                tx = base_tile_x + tx_off
                ty = base_tile_y + ty_off
                path = self.tile_cache._tile_to_path(basemap, zoom, tx, ty)
                if path.exists():
                    available += 1
        return available, total

    def _update_tile_coverage_status(self):
        avail, total = self._current_tile_coverage()
        pct = int((avail / total) * 100) if total else 0
        self.map_tile_status_lbl.setText(
            f"Tile coverage (offline): {avail}/{total} ({pct}%)"
        )

    @staticmethod
    def _latlon_to_world_px(lat_v: float, lon_v: float, z: int, tile_size: int = 256) -> tuple[float, float]:
        n = 2 ** z
        x = (lon_v + 180.0) / 360.0 * n * tile_size
        lat_rad = math.radians(max(min(lat_v, 85.05112878), -85.05112878))
        y = (
            (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi)
            / 2.0
            * n
            * tile_size
        )
        return x, y

    @staticmethod
    def _world_px_to_latlon(world_x: float, world_y: float, z: int, tile_size: int = 256) -> tuple[float, float]:
        n = 2 ** z
        lon = (world_x / (n * tile_size)) * 360.0 - 180.0
        merc = math.pi * (1 - 2 * world_y / (n * tile_size))
        lat = math.degrees(math.atan(math.sinh(merc)))
        return lat, lon

    def _on_map_picker_clicked(self, x: int, y: int):
        pix = self.map_picker.pixmap()
        if pix is None or pix.isNull():
            return
        label_w = self.map_picker.width()
        label_h = self.map_picker.height()
        img_w = pix.width()
        img_h = pix.height()
        if img_w <= 0 or img_h <= 0:
            return
        x_off = max((label_w - img_w) // 2, 0)
        y_off = max((label_h - img_h) // 2, 0)
        local_x = int((x - x_off) * (img_w / max(label_w, 1)))
        local_y = int((y - y_off) * (img_h / max(label_h, 1)))
        if local_x < 0 or local_y < 0 or local_x >= img_w or local_y >= img_h:
            return
        zoom = int(self.map_zoom.value())
        lat = float(self._map_view_lat)
        lon = float(self._map_view_lon)
        tile_size = 256
        tiles_each_side = 5
        center_world_x, center_world_y = self._latlon_to_world_px(lat, lon, zoom, tile_size)
        center_tile_x = int(center_world_x // tile_size)
        center_tile_y = int(center_world_y // tile_size)
        half = tiles_each_side // 2
        base_tile_x = center_tile_x - half
        base_tile_y = center_tile_y - half
        world_x = base_tile_x * tile_size + local_x
        world_y = base_tile_y * tile_size + local_y
        new_lat, new_lon = self._world_px_to_latlon(world_x, world_y, zoom, tile_size)
        self.map_lat.setValue(float(new_lat))
        self.map_lon.setValue(float(new_lon))

    def _on_map_drag_started(self, x: int, y: int):
        self._drag_start_xy = (x, y)
        self._drag_start_center = (float(self._map_view_lat), float(self._map_view_lon))

    def _on_map_drag_moved(self, x: int, y: int):
        if not self._drag_start_xy or not self._drag_start_center:
            return
        dx = x - self._drag_start_xy[0]
        dy = y - self._drag_start_xy[1]
        zoom = int(self.map_zoom.value())
        lat0, lon0 = self._drag_start_center
        tile_size = 256
        center_world_x, center_world_y = self._latlon_to_world_px(lat0, lon0, zoom, tile_size)
        new_world_x = center_world_x - dx
        new_world_y = center_world_y - dy
        new_lat, new_lon = self._world_px_to_latlon(new_world_x, new_world_y, zoom, tile_size)
        self.map_lat.blockSignals(True)
        self.map_lon.blockSignals(True)
        self._map_view_lat = float(new_lat)
        self._map_view_lon = float(new_lon)
        self.map_lat.blockSignals(False)
        self.map_lon.blockSignals(False)
        self.refresh_preview()

    def _on_map_drag_finished(self, _x: int, _y: int):
        self._drag_start_xy = None
        self._drag_start_center = None

    def _on_location_spin_changed(self, _value):
        # Manual coordinate edits should recenter the browsing view to selection.
        self._map_view_lat = float(self.map_lat.value())
        self._map_view_lon = float(self.map_lon.value())
        self._sync_interactive_map_picker()
        self.refresh_preview()

    def _on_real_map_point_selected(self, lat: float, lon: float):
        self._map_view_lat = float(lat)
        self._map_view_lon = float(lon)
        self.map_lat.setValue(float(lat))
        self.map_lon.setValue(float(lon))

    def _sync_interactive_map_picker(self):
        if not self._use_interactive_map_picker:
            return
        try:
            self.map_picker.set_basemap(str(self.map_basemap.currentData() or self.map_basemap.currentText()))
            self.map_picker.center_on_coordinates(self._map_view_lat, self._map_view_lon, zoom=int(self.map_zoom.value()))
            self.map_picker.add_weapon_marker(
                {
                    "origin_lat": float(self.map_lat.value()),
                    "origin_lon": float(self.map_lon.value()),
                    "weapon_name": "Selected point",
                    "range_km": 0,
                }
            )
        except Exception:
            pass

    def _reset_map_center_defaults(self):
        self.map_lat.setValue(self._default_lat)
        self.map_lon.setValue(self._default_lon)
        self.map_zoom.setValue(7)
        self._map_view_lat = self._default_lat
        self._map_view_lon = self._default_lon

    def set_default_center(self, lat: float, lon: float):
        self._default_lat = float(lat)
        self._default_lon = float(lon)
        self._map_view_lat = float(lat)
        self._map_view_lon = float(lon)
        self.map_lat.setValue(float(lat))
        self.map_lon.setValue(float(lon))

    def _update_map_picker_preview(self):
        if self._use_interactive_map_picker:
            self._sync_interactive_map_picker()
            return
        try:
            from PIL import Image, ImageDraw
        except Exception:
            self.map_picker.setText("Map preview unavailable (Pillow missing)")
            return
        lat = float(self._map_view_lat)
        lon = float(self._map_view_lon)
        zoom = int(self.map_zoom.value())
        basemap = str(self.map_basemap.currentData() or self.map_basemap.currentText())
        tile_size = 256
        tiles_each_side = 5
        center_world_x, center_world_y = self._latlon_to_world_px(lat, lon, zoom, tile_size)
        center_tile_x = int(center_world_x // tile_size)
        center_tile_y = int(center_world_y // tile_size)
        half = tiles_each_side // 2
        base_tile_x = center_tile_x - half
        base_tile_y = center_tile_y - half
        canvas_w = tiles_each_side * tile_size
        canvas_h = tiles_each_side * tile_size
        canvas = Image.new("RGB", (canvas_w, canvas_h), (26, 30, 36))
        draw = ImageDraw.Draw(canvas, "RGBA")
        for tx_off in range(tiles_each_side):
            for ty_off in range(tiles_each_side):
                tx = base_tile_x + tx_off
                ty = base_tile_y + ty_off
                data = self.tile_cache.get_tile(basemap, zoom, tx, ty, offline_only=True)
                x0 = tx_off * tile_size
                y0 = ty_off * tile_size
                if not data:
                    draw.rectangle([x0, y0, x0 + tile_size, y0 + tile_size], fill=(45, 45, 50, 255), outline=(80, 80, 90, 255))
                    continue
                try:
                    from io import BytesIO
                    tile_img = Image.open(BytesIO(data)).convert("RGB")
                    canvas.paste(tile_img, (x0, y0))
                except Exception:
                    draw.rectangle([x0, y0, x0 + tile_size, y0 + tile_size], fill=(45, 45, 50, 255), outline=(80, 80, 90, 255))
        # Show selected point marker (from Lat/Lon fields) while browsing center stays independent.
        sel_lat = float(self.map_lat.value())
        sel_lon = float(self.map_lon.value())
        sel_world_x, sel_world_y = self._latlon_to_world_px(sel_lat, sel_lon, zoom, tile_size)
        mx = int(sel_world_x - (base_tile_x * tile_size))
        my = int(sel_world_y - (base_tile_y * tile_size))
        draw.line([mx - 14, my, mx + 14, my], fill=(40, 245, 220, 255), width=2)
        draw.line([mx, my - 14, mx, my + 14], fill=(40, 245, 220, 255), width=2)
        draw.ellipse([mx - 5, my - 5, mx + 5, my + 5], outline=(255, 255, 255, 255), width=2)
        preview = canvas.resize((480, 240))
        raw = preview.tobytes("raw", "RGB")
        qimg = QImage(raw, preview.width, preview.height, preview.width * 3, QImage.Format.Format_RGB888).copy()
        self.map_picker.setPixmap(QPixmap.fromImage(qimg))

    def _preview_as_pdf(self):
        """Render current HTML preview to a temporary PDF and open it."""
        if self.web is None:
            QMessageBox.information(
                self,
                "PDF preview",
                "PDF preview requires PyQt6-WebEngine. Install/enable it, then restart.",
            )
            return

        tmp = tempfile.NamedTemporaryFile(prefix="armorygis_report_preview_", suffix=".pdf", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            def _done(pdf_bytes):
                try:
                    # pdf_bytes can be QByteArray/bytes depending on binding/version
                    data = bytes(pdf_bytes)
                    Path(tmp_path).write_bytes(data)
                    QDesktopServices.openUrl(QUrl.fromLocalFile(tmp_path))
                except Exception as exc:
                    QMessageBox.critical(self, "PDF preview failed", str(exc))

            # Use callback overload; we persist bytes ourselves.
            self.web.page().printToPdf(_done)
        except Exception as exc:
            QMessageBox.critical(self, "PDF preview failed", str(exc))

    def _export_to_file(self):
        kind = self._kind()
        fmt = self.format_combo.currentText()
        meta = self._meta()
        data = self._all_weapons

        if not data and kind != REPORT_KIND_DATA_EXPORT:
            QMessageBox.warning(self, "No data", "No weapons loaded.")
            return

        if kind == REPORT_KIND_DATA_EXPORT:
            if not data:
                QMessageBox.warning(self, "No data", "No weapons to export.")
                return
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save export file",
                str(Path.home() / f"weapons_export.{fmt}"),
                f"{fmt.upper()} (*.{fmt})",
            )
            if not path:
                return
            try:
                exporter = Exporter(data)
                if fmt == "xlsx":
                    exporter.to_excel(path)
                elif fmt == "csv":
                    exporter.to_csv(path)
                elif fmt == "json":
                    exporter.to_json(path)
                elif fmt == "docx":
                    exporter.to_docx(path)
                elif fmt == "pdf":
                    exporter.to_pdf(path)
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Export failed", str(exc))
            return

        if kind == REPORT_KIND_INDIVIDUAL:
            sel = self._selected_weapons()
            if len(sel) != 1:
                QMessageBox.warning(self, "Selection", "Select exactly one weapon.")
                return
            weapon = self._ensure_full_weapon(sel[0])
            ext = "docx" if fmt == "docx" else "pdf"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / f"weapon_report_{weapon.get('id', 'x')}.{ext}"),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                inc = self.include_map_cb.isChecked()
                map_png_path: Optional[str] = None
                if inc:
                    avail, total = self._current_tile_coverage()
                    if avail < total:
                        proceed = QMessageBox.question(
                            self,
                            "Offline tiles incomplete",
                            (
                                f"Only {avail}/{total} map tiles are cached for this view.\n"
                                "Report map image will contain missing-tile blocks.\n\n"
                                "Continue export?"
                            ),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        )
                        if proceed != QMessageBox.StandardButton.Yes:
                            return
                    map_png_path = self._render_real_map_png(weapon)
                if fmt == "docx":
                    weapon_reports.write_individual_weapon_docx(
                        weapon,
                        path,
                        include_map=inc,
                        meta=meta,
                        lang_manager=self.lang_manager,
                        map_png_path=map_png_path,
                    )
                else:
                    weapon_reports.write_individual_weapon_pdf(
                        weapon,
                        path,
                        include_map=inc,
                        meta=meta,
                        lang_manager=self.lang_manager,
                        map_png_path=map_png_path,
                    )
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return

        if kind == REPORT_KIND_MULTI_COMPARE:
            sel = self._selected_weapons()
            if len(sel) < 2:
                QMessageBox.warning(self, "Selection", "Select at least two weapons.")
                return
            weapons = [self._ensure_full_weapon(w) for w in sel]
            ext = "docx" if fmt == "docx" else "pdf"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / f"weapon_comparison.{ext}"),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                if fmt == "docx":
                    weapon_reports.write_multi_comparison_docx(
                        weapons, path, meta=meta, lang_manager=self.lang_manager
                    )
                else:
                    weapon_reports.write_multi_comparison_pdf(
                        weapons, path, meta=meta, lang_manager=self.lang_manager
                    )
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return

        if kind == REPORT_KIND_BY_CATEGORY:
            weapons = [self._ensure_full_weapon(w) for w in data]
            ext = "docx" if fmt == "docx" else "pdf"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / f"weapons_by_category.{ext}"),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                if fmt == "docx":
                    weapon_reports.write_category_grid_docx(
                        weapons, path, meta=meta, lang_manager=self.lang_manager
                    )
                else:
                    weapon_reports.write_category_grid_pdf(
                        weapons, path, meta=meta, lang_manager=self.lang_manager
                    )
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return

        if kind == REPORT_KIND_FULL_SPECS:
            weapons = [self._ensure_full_weapon(w) for w in data]
            ext = "docx" if fmt == "docx" else "pdf"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / f"weapons_full_specs.{ext}"),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                if fmt == "docx":
                    weapon_reports.write_full_specs_docx(
                        weapons, path, meta=meta, lang_manager=self.lang_manager
                    )
                else:
                    weapon_reports.write_full_specs_catalog_pdf(
                        weapons, path, meta=meta, lang_manager=self.lang_manager
                    )
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))

    def _render_real_map_png(self, weapon: dict) -> str:
        """Render offline real-map snapshot by stitching cached tiles + overlays."""
        from PIL import Image, ImageDraw

        lat = float(self.map_lat.value())
        lon = float(self.map_lon.value())
        zoom = int(self.map_zoom.value())
        basemap = str(self.map_basemap.currentData() or self.map_basemap.currentText())

        max_range = float(weapon.get("range_km") or 0)
        min_range = max(max_range * 0.35, 0.0)

        tile_size = 256
        tiles_each_side = 5  # 5x5 stitched tiles

        center_world_x, center_world_y = self._latlon_to_world_px(lat, lon, zoom, tile_size)
        center_tile_x = int(center_world_x // tile_size)
        center_tile_y = int(center_world_y // tile_size)
        half = tiles_each_side // 2
        base_tile_x = center_tile_x - half
        base_tile_y = center_tile_y - half

        canvas_w = tiles_each_side * tile_size
        canvas_h = tiles_each_side * tile_size
        canvas = Image.new("RGB", (canvas_w, canvas_h), (32, 36, 42))
        draw = ImageDraw.Draw(canvas, "RGBA")

        for tx_off in range(tiles_each_side):
            for ty_off in range(tiles_each_side):
                tx = base_tile_x + tx_off
                ty = base_tile_y + ty_off
                data = self.tile_cache.get_tile(
                    basemap, zoom, tx, ty, offline_only=True
                )
                if not data:
                    # Missing tile: keep dark block and hatch lines.
                    x0 = tx_off * tile_size
                    y0 = ty_off * tile_size
                    draw.rectangle(
                        [x0, y0, x0 + tile_size, y0 + tile_size],
                        fill=(45, 45, 50, 255),
                        outline=(80, 80, 90, 255),
                    )
                    draw.line([x0, y0, x0 + tile_size, y0 + tile_size], fill=(110, 110, 120, 180), width=2)
                    draw.line([x0 + tile_size, y0, x0, y0 + tile_size], fill=(110, 110, 120, 180), width=2)
                    continue
                try:
                    from io import BytesIO

                    tile_img = Image.open(BytesIO(data)).convert("RGB")
                    canvas.paste(tile_img, (tx_off * tile_size, ty_off * tile_size))
                except Exception:
                    pass

        origin_px_x = center_world_x - (base_tile_x * tile_size)
        origin_px_y = center_world_y - (base_tile_y * tile_size)

        # Convert km radius to pixels around center at current zoom/latitude.
        meters_per_pixel = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
        px_per_km = 1000.0 / max(meters_per_pixel, 0.01)
        r_outer = max_range * px_per_km
        r_inner = min_range * px_per_km

        # Outer / inner range rings (effects).
        if r_outer > 1:
            draw.ellipse(
                [
                    origin_px_x - r_outer,
                    origin_px_y - r_outer,
                    origin_px_x + r_outer,
                    origin_px_y + r_outer,
                ],
                outline=(255, 80, 60, 240),
                fill=(255, 40, 40, 70),
                width=3,
            )
        if r_inner > 1:
            draw.ellipse(
                [
                    origin_px_x - r_inner,
                    origin_px_y - r_inner,
                    origin_px_x + r_inner,
                    origin_px_y + r_inner,
                ],
                outline=(255, 220, 120, 240),
                fill=(255, 220, 120, 35),
                width=2,
            )

        # Origin marker
        draw.ellipse(
            [
                origin_px_x - 6,
                origin_px_y - 6,
                origin_px_x + 6,
                origin_px_y + 6,
            ],
            fill=(0, 255, 210, 255),
            outline=(255, 255, 255, 230),
            width=1,
        )

        # Header strip
        draw.rectangle([0, 0, canvas_w, 36], fill=(10, 18, 30, 210))
        draw.text((10, 10), f"{weapon.get('weapon_name', 'Weapon')} | z{zoom} | {basemap}", fill=(220, 235, 250, 255))

        tmp = tempfile.NamedTemporaryFile(prefix="armorygis_map_", suffix=".png", delete=False)
        out_path = tmp.name
        tmp.close()
        canvas.save(out_path, "PNG")
        return out_path

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.retranslate_ui()
        self._load_cached_report_drafts()

    def retranslate_ui(self):
        if not self.lang_manager:
            return
        self._header_lbl.setText(self.lang_manager.tr("Reports workspace"))
        self.map_section.set_title(self.lang_manager.tr("Map settings"))
        self.doc_section.set_title(self.lang_manager.tr("Document text settings"))
        self.tools_section.set_title(self.lang_manager.tr("Weapons and export tools"))
        self.map_settings_lbl.setText(self.lang_manager.tr("Map settings (for report map image)"))
        self.map_help_lbl.setText(self.lang_manager.tr("Drag to browse map, then click to set point"))
        self.map_reset_btn.setText(self.lang_manager.tr("Reset to default center"))
        self.include_title_cb.setText(self.lang_manager.tr("Include title"))
        self.include_intro_cb.setText(self.lang_manager.tr("Include introduction"))
        self.include_specs_cb.setText(self.lang_manager.tr("Include specifications"))
        self.include_gallery_cb.setText(self.lang_manager.tr("Include gallery images"))
        self.include_closing_cb.setText(self.lang_manager.tr("Include closing notes"))
        self.doc_title_lbl.setText(self.lang_manager.tr("Document title (optional)"))
        self.doc_intro_lbl.setText(self.lang_manager.tr("Introduction / cover text (optional)"))
        self.doc_closing_lbl.setText(self.lang_manager.tr("Closing / appendix notes (optional)"))
        self.ai_intro_btn.setText(self.lang_manager.tr("AI Draft Intro"))
        self.ai_summary_btn.setText(self.lang_manager.tr("AI Executive Summary"))
        self.ai_closing_btn.setText(self.lang_manager.tr("AI Draft Closing"))
        self.file_format_lbl.setText(self.lang_manager.tr("File format"))
        self.weapons_lbl.setText(self.lang_manager.tr("Weapons (for individual / comparison)"))
        self.spec_fields_lbl.setText(self.lang_manager.tr("Specifications fields (single view + comparison reports)"))
        self.preview_btn.setText(self.lang_manager.tr("Refresh preview"))
        self.preview_pdf_btn.setText(self.lang_manager.tr("Preview PDF"))
        self.export_btn.setText(self.lang_manager.tr("Export to file…"))
        self.reload_btn.setText(self.lang_manager.tr("Reload list"))
        self.include_map_cb.setText(
            self.lang_manager.tr("Include range & effects map diagram (individual export only)")
        )
