"""Shared settings form widget used by SettingsDialog and SettingsPanel."""
from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QColorDialog,
    QFileDialog,
)

from config import APP_CONFIG, LANGUAGE_CONFIG, THEME_CONFIG, TILE_CACHE_CONFIG
from utils.ai_service import (
    AI_ENABLED_KEY,
    AI_BASE_URL_KEY,
    AI_MODEL_KEY,
    AI_TEMPERATURE_KEY,
    AI_TIMEOUT_S_KEY,
)
from utils.database_tools import backup_sqlite, export_database, import_sqlite_into_active
from utils.gmdb_sources import GMDB_DIR_KEY
from utils.map_settings import (
    DEFAULT_BASEMAP,
    MAP_BASEMAP_KEY,
    MAP_DEFAULT_LAT_KEY,
    MAP_DEFAULT_LON_KEY,
    MAP_TILE_MODE_KEY,
    TILE_MODE_OFFLINE,
)
from utils.weapon_media_library import (
    DEFAULT_GALLERY_2D_EXTENSIONS,
    GALLERY_2D_EXTENSIONS_KEY,
)

STARTUP_TAB_MODE_KEY = "ui/startup_tab_mode"
STARTUP_TAB_MODE_CONTROL = "control_panel"
STARTUP_TAB_MODE_LAST = "last_tab"
BRAND_COMPANY_NAME_KEY = "ui/company_name"
BRAND_LOGO_PATH_KEY = "ui/company_logo_path"
BRAND_LOGO_SIZE_KEY = "ui/company_logo_size"
BRAND_LOGO_WIDTH_KEY = "ui/company_logo_width"
BRAND_LOGO_HEIGHT_KEY = "ui/company_logo_height"
BRAND_LOGO_SCALE_PERCENT_KEY = "ui/company_logo_scale_percent"

_AI_SWOT_MODEL_TIP = (
    "SWOT / analysis tip: Prefer instruction-tuned models (presets listed first).\n"
    "Examples: llama3.3:70b-instruct-q4_K_M or qwen2.5:32b-instruct for accuracy and numbered structure; "
    "for Arabic-heavy UI, qwen2.5:14b/32b-instruct often behaves well.\n"
    "Use temperature ~0.2-0.4 for analytical drafts. Install with: ollama pull <tag>"
)

_FONT_OVERRIDE_START = "/* ARMORY_FONT_OVERRIDE_START */"
_FONT_OVERRIDE_END = "/* ARMORY_FONT_OVERRIDE_END */"

BASEMAP_LABELS = {
    "dark": "Dark (Carto)",
    "satellite": "Satellite (Esri)",
    "osm": "OpenStreetMap",
    "topo": "OpenTopoMap",
}

THEME_LABELS = {
    "dark": "Dark",
    "light": "Light",
    "orange_black": "Orange Black",
    "cyber_neon": "Cyber Neon",
}


class SettingsForm(QWidget):
    settings_applied = pyqtSignal()
    precache_requested = pyqtSignal(list)
    world_precache_requested = pyqtSignal()

    def __init__(
        self,
        settings=None,
        theme_manager=None,
        lang_manager=None,
        db_manager=None,
        tile_cache=None,
        include_ai: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.theme_manager = theme_manager
        self.lang_manager = lang_manager
        self.db_manager = db_manager
        self.tile_cache = tile_cache
        self.include_ai = include_ai
        default_font = "#1a1a1a" if THEME_CONFIG.get("default_theme") == "light" else "#e6e6e6"
        self._font_color = self.settings.value("ui/font_color", default_font, str)
        self._cache_status_labels: dict[str, QLabel] = {}
        self._basemap_row_labels: dict[str, QLabel] = {}
        self._basemap_download_btns: list[QPushButton] = []
        self._row_labels: list[tuple[QLabel, str]] = []
        self._general_group: Optional[QGroupBox] = None
        self._map_group: Optional[QGroupBox] = None
        self._brand_group: Optional[QGroupBox] = None
        self._files_group: Optional[QGroupBox] = None
        self._ai_group: Optional[QGroupBox] = None
        self._database_group: Optional[QGroupBox] = None
        self._cache_hdr_basemap: Optional[QLabel] = None
        self._cache_hdr_status: Optional[QLabel] = None
        self._dl_all_btn: Optional[QPushButton] = None
        self._refresh_cache_btn: Optional[QPushButton] = None
        self._logo_browse_btn: Optional[QPushButton] = None
        self._gmdb_browse_btn: Optional[QPushButton] = None
        self._ai_hint_lbl: Optional[QLabel] = None
        self._build_ui()
        self.refresh_cache_status()

    def _tr(self, english: str) -> str:
        if self.lang_manager and hasattr(self.lang_manager, "tr"):
            try:
                return str(self.lang_manager.tr(english))
            except Exception:
                pass
        return english

    def _form_row(self, form: QFormLayout, key: str, widget) -> QLabel:
        lbl = QLabel(self._tr(key))
        form.addRow(lbl, widget)
        self._row_labels.append((lbl, key))
        return lbl

    def _rebuild_combo(self, combo: QComboBox, items: list[tuple[str, object]]):
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(self._tr(label), data)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        root.addWidget(self._build_general_group())
        root.addWidget(self._build_map_group())
        root.addWidget(self._build_brand_group())
        root.addWidget(self._build_files_group())
        if self.include_ai:
            root.addWidget(self._build_ai_group())
        root.addWidget(self._build_database_group())
        root.addStretch(1)

    def _build_general_group(self) -> QGroupBox:
        self._general_group = QGroupBox(self._tr("General"))
        form = QFormLayout(self._general_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.language_combo = QComboBox()
        self.language_combo.addItem(self._tr("English"), "en")
        self.language_combo.addItem(self._tr("Arabic"), "ar")
        saved_lang = self.settings.value("language", LANGUAGE_CONFIG["default_language"], str)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(saved_lang)))

        self.theme_combo = QComboBox()
        for theme, label in THEME_LABELS.items():
            self.theme_combo.addItem(self._tr(label), theme)
        saved_theme = self.settings.value("ui/theme", THEME_CONFIG["default_theme"], str)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(saved_theme)))

        self.startup_tab_combo = QComboBox()
        self.startup_tab_combo.addItem(self._tr("Weapon Control (default)"), STARTUP_TAB_MODE_CONTROL)
        self.startup_tab_combo.addItem(self._tr("Last opened tab"), STARTUP_TAB_MODE_LAST)
        saved_startup = self.settings.value(STARTUP_TAB_MODE_KEY, STARTUP_TAB_MODE_CONTROL, str)
        self.startup_tab_combo.setCurrentIndex(max(0, self.startup_tab_combo.findData(saved_startup)))

        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(int(self.settings.value("ui/font_size", 10)))

        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.color_btn = QPushButton(self._tr("Choose Font Color"))
        self.color_btn.clicked.connect(self._pick_color)
        self.color_preview = QLabel(self._font_color)
        self.color_preview.setStyleSheet(f"color:{self._font_color};")
        color_layout.addWidget(self.color_btn)
        color_layout.addWidget(self.color_preview, 1)

        self._form_row(form, "Language", self.language_combo)
        self._form_row(form, "Theme", self.theme_combo)
        self._form_row(form, "Startup tab", self.startup_tab_combo)
        self._form_row(form, "Font Size", self.font_size)
        self._form_row(form, "Font color", color_row)
        return self._general_group

    def _build_map_group(self) -> QGroupBox:
        self._map_group = QGroupBox(self._tr("Map"))
        layout = QVBoxLayout(self._map_group)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.tile_mode_combo = QComboBox()
        self.tile_mode_combo.addItem(self._tr("Offline (local tiles only)"), TILE_MODE_OFFLINE)
        self.tile_mode_combo.setEnabled(False)
        self.tile_mode_combo.setToolTip(self._tr("Maps always use locally cached tiles (offline mode)."))
        self.tile_mode_combo.setCurrentIndex(0)

        self.default_basemap_combo = QComboBox()
        for key, label in BASEMAP_LABELS.items():
            self.default_basemap_combo.addItem(self._tr(label), key)
        saved_basemap = self.settings.value(MAP_BASEMAP_KEY, DEFAULT_BASEMAP, str)
        self.default_basemap_combo.setCurrentIndex(max(0, self.default_basemap_combo.findData(saved_basemap)))

        default_lat, default_lon = APP_CONFIG.get("default_center", (31.5, 34.8))
        self.default_lat = QDoubleSpinBox()
        self.default_lat.setRange(-90, 90)
        self.default_lat.setDecimals(6)
        self.default_lat.setValue(float(self.settings.value(MAP_DEFAULT_LAT_KEY, default_lat, float)))
        self.default_lon = QDoubleSpinBox()
        self.default_lon.setRange(-180, 180)
        self.default_lon.setDecimals(6)
        self.default_lon.setValue(float(self.settings.value(MAP_DEFAULT_LON_KEY, default_lon, float)))

        self._form_row(form, "Map tile mode", self.tile_mode_combo)
        self._form_row(form, "Default basemap", self.default_basemap_combo)
        self._form_row(form, "Default Latitude", self.default_lat)
        self._form_row(form, "Default Longitude", self.default_lon)
        layout.addLayout(form)

        cache_grid = QGridLayout()
        self._cache_hdr_basemap = QLabel(self._tr("Basemap"))
        self._cache_hdr_status = QLabel(self._tr("Status"))
        cache_grid.addWidget(self._cache_hdr_basemap, 0, 0)
        cache_grid.addWidget(self._cache_hdr_status, 0, 1)
        cache_grid.addWidget(QLabel(""), 0, 2)
        for row, basemap in enumerate(BASEMAP_LABELS, start=1):
            name_lbl = QLabel(self._tr(BASEMAP_LABELS[basemap]))
            self._basemap_row_labels[basemap] = name_lbl
            cache_grid.addWidget(name_lbl, row, 0)
            status_lbl = QLabel("—")
            status_lbl.setWordWrap(True)
            self._cache_status_labels[basemap] = status_lbl
            cache_grid.addWidget(status_lbl, row, 1)
            btn = QPushButton(self._tr("Download"))
            btn.clicked.connect(lambda _=False, b=basemap: self.precache_requested.emit([b]))
            self._basemap_download_btns.append(btn)
            cache_grid.addWidget(btn, row, 2)
        layout.addLayout(cache_grid)

        dl_row = QHBoxLayout()
        self._dl_all_btn = QPushButton(self._tr("Download all basemaps (4 types)"))
        self._dl_all_btn.clicked.connect(lambda: self.precache_requested.emit(list(BASEMAP_LABELS.keys())))
        self._world_dl_btn = QPushButton(self._tr("Download world overview (Z0–5, all basemaps)"))
        self._world_dl_btn.setToolTip(
            self._tr("Downloads all world tiles at zoom levels 0–5 for every basemap type (~60–100 MB).")
        )
        self._world_dl_btn.clicked.connect(self.world_precache_requested.emit)
        self._refresh_cache_btn = QPushButton(self._tr("Refresh cache status"))
        self._refresh_cache_btn.clicked.connect(self.refresh_cache_status)
        dl_row.addWidget(self._dl_all_btn)
        dl_row.addWidget(self._world_dl_btn)
        dl_row.addWidget(self._refresh_cache_btn)
        layout.addLayout(dl_row)

        if self.tile_cache is not None:
            path_lbl = QLabel(str(self.tile_cache.cache_dir))
            path_lbl.setWordWrap(True)
            path_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
            layout.addWidget(path_lbl)
        return self._map_group

    def _build_brand_group(self) -> QGroupBox:
        self._brand_group = QGroupBox(self._tr("Company branding"))
        form = QFormLayout(self._brand_group)
        self.company_name_input = QLineEdit(
            self.settings.value(BRAND_COMPANY_NAME_KEY, APP_CONFIG.get("organization", ""), str)
        )
        self.logo_width_spin = QSpinBox()
        self.logo_width_spin.setRange(16, 512)
        self.logo_height_spin = QSpinBox()
        self.logo_height_spin.setRange(16, 512)
        saved_square = int(self.settings.value(BRAND_LOGO_SIZE_KEY, 24, int))
        self.logo_width_spin.setValue(int(self.settings.value(BRAND_LOGO_WIDTH_KEY, saved_square, int)))
        self.logo_height_spin.setValue(int(self.settings.value(BRAND_LOGO_HEIGHT_KEY, saved_square, int)))
        self.logo_scale_spin = QSpinBox()
        self.logo_scale_spin.setRange(10, 300)
        self.logo_scale_spin.setSuffix("%")
        self.logo_scale_spin.setValue(int(self.settings.value(BRAND_LOGO_SCALE_PERCENT_KEY, 100, int)))
        self.logo_path_input = QLineEdit(self.settings.value(BRAND_LOGO_PATH_KEY, "", str))
        logo_row = QWidget()
        logo_layout = QHBoxLayout(logo_row)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.addWidget(self.logo_path_input, 1)
        self._logo_browse_btn = QPushButton(self._tr("Browse company logo"))
        self._logo_browse_btn.clicked.connect(self._browse_logo_file)
        logo_layout.addWidget(self._logo_browse_btn)
        self._form_row(form, "Company name", self.company_name_input)
        self._form_row(form, "Company logo width", self.logo_width_spin)
        self._form_row(form, "Company logo height", self.logo_height_spin)
        self._form_row(form, "Company logo scale", self.logo_scale_spin)
        self._form_row(form, "Company logo", logo_row)
        return self._brand_group

    def _build_files_group(self) -> QGroupBox:
        self._files_group = QGroupBox(self._tr("Files & media"))
        form = QFormLayout(self._files_group)
        self.gmdb_dir_input = QLineEdit(self.settings.value(GMDB_DIR_KEY, "", str))
        gmdb_row = QWidget()
        gmdb_layout = QHBoxLayout(gmdb_row)
        gmdb_layout.setContentsMargins(0, 0, 0, 0)
        gmdb_layout.addWidget(self.gmdb_dir_input, 1)
        self._gmdb_browse_btn = QPushButton(self._tr("Browse .gmdb folder"))
        self._gmdb_browse_btn.clicked.connect(self._browse_gmdb_dir)
        gmdb_layout.addWidget(self._gmdb_browse_btn)
        self.gallery_exts_input = QLineEdit(
            self.settings.value(GALLERY_2D_EXTENSIONS_KEY, DEFAULT_GALLERY_2D_EXTENSIONS, str)
        )
        self.gallery_exts_input.setPlaceholderText(".png,.jpg,.jpeg,.tif,.tiff,.webp")
        self._form_row(form, "Offline .gmdb maps folder", gmdb_row)
        self._form_row(form, "2D gallery preview extensions (comma-separated)", self.gallery_exts_input)
        return self._files_group

    def _build_ai_group(self) -> QGroupBox:
        self._ai_group = QGroupBox(self._tr("Local AI (Ollama)"))
        form = QFormLayout(self._ai_group)
        self.ai_enable_chk = QCheckBox(self._tr("Enable local AI (Ollama)"))
        self.ai_enable_chk.setChecked(bool(self.settings.value(AI_ENABLED_KEY, False, bool)))
        self.ai_url_input = QLineEdit(self.settings.value(AI_BASE_URL_KEY, "http://localhost:11434", str))
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setEditable(True)
        for name in [
            "llama3.3:70b-instruct-q4_K_M", "qwen2.5:32b-instruct", "qwen2.5:14b-instruct",
            "llama3.1:8b-instruct-q4_K_M", "llama3.1", "llama3.2:3b", "mistral:7b-instruct",
        ]:
            self.ai_model_combo.addItem(name)
        saved_model = str(self.settings.value(AI_MODEL_KEY, "llama3.1", str) or "").strip()
        idx = self.ai_model_combo.findText(saved_model)
        if idx >= 0:
            self.ai_model_combo.setCurrentIndex(idx)
        else:
            self.ai_model_combo.setCurrentText(saved_model or "llama3.1")
        self.ai_temp_spin = QDoubleSpinBox()
        self.ai_temp_spin.setRange(0.0, 2.0)
        self.ai_temp_spin.setDecimals(2)
        self.ai_temp_spin.setSingleStep(0.05)
        self.ai_temp_spin.setValue(float(self.settings.value(AI_TEMPERATURE_KEY, 0.3, float)))
        self.ai_timeout_spin = QSpinBox()
        self.ai_timeout_spin.setRange(5, 600)
        self.ai_timeout_spin.setSuffix(" s")
        self.ai_timeout_spin.setValue(int(self.settings.value(AI_TIMEOUT_S_KEY, 180, int)))
        self._ai_hint_lbl = QLabel(self._tr(_AI_SWOT_MODEL_TIP))
        self._ai_hint_lbl.setWordWrap(True)
        self._ai_hint_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
        form.addRow(self.ai_enable_chk)
        self._form_row(form, "Ollama URL", self.ai_url_input)
        self._form_row(form, "Ollama model", self.ai_model_combo)
        form.addRow("", self._ai_hint_lbl)
        self._form_row(form, "AI temperature", self.ai_temp_spin)
        self._form_row(form, "AI timeout", self.ai_timeout_spin)
        return self._ai_group

    def _build_database_group(self) -> QGroupBox:
        self._database_group = QGroupBox(self._tr("Database"))
        row = QHBoxLayout(self._database_group)
        self.backup_btn = QPushButton(self._tr("Backup Database"))
        self.import_btn = QPushButton(self._tr("Import SQLite Database"))
        self.export_btn = QPushButton(self._tr("Export Database"))
        self.backup_btn.clicked.connect(self._backup_database)
        self.import_btn.clicked.connect(self._import_database)
        self.export_btn.clicked.connect(self._export_database)
        row.addWidget(self.backup_btn)
        row.addWidget(self.import_btn)
        row.addWidget(self.export_btn)
        return self._database_group

    def retranslate_ui(self):
        for group, title in (
            (self._general_group, "General"),
            (self._map_group, "Map"),
            (self._brand_group, "Company branding"),
            (self._files_group, "Files & media"),
            (self._ai_group, "Local AI (Ollama)"),
            (self._database_group, "Database"),
        ):
            if group is not None:
                group.setTitle(self._tr(title))
        for lbl, key in self._row_labels:
            lbl.setText(self._tr(key))
        self._rebuild_combo(self.language_combo, [("English", "en"), ("Arabic", "ar")])
        self._rebuild_combo(
            self.theme_combo,
            [(THEME_LABELS[k], k) for k in ("dark", "light", "orange_black", "cyber_neon")],
        )
        self._rebuild_combo(
            self.startup_tab_combo,
            [("Weapon Control (default)", STARTUP_TAB_MODE_CONTROL), ("Last opened tab", STARTUP_TAB_MODE_LAST)],
        )
        self._rebuild_combo(
            self.tile_mode_combo,
            [("Offline (local tiles only)", TILE_MODE_OFFLINE)],
        )
        self.tile_mode_combo.setToolTip(self._tr("Maps always use locally cached tiles (offline mode)."))
        self._rebuild_combo(
            self.default_basemap_combo,
            [(BASEMAP_LABELS[k], k) for k in BASEMAP_LABELS],
        )
        self.color_btn.setText(self._tr("Choose Font Color"))
        if self._cache_hdr_basemap is not None:
            self._cache_hdr_basemap.setText(self._tr("Basemap"))
        if self._cache_hdr_status is not None:
            self._cache_hdr_status.setText(self._tr("Status"))
        for basemap, lbl in self._basemap_row_labels.items():
            lbl.setText(self._tr(BASEMAP_LABELS[basemap]))
        for btn in self._basemap_download_btns:
            btn.setText(self._tr("Download"))
        if self._dl_all_btn is not None:
            self._dl_all_btn.setText(self._tr("Download all basemaps (4 types)"))
        if self._world_dl_btn is not None:
            self._world_dl_btn.setText(self._tr("Download world overview (Z0–5, all basemaps)"))
            self._world_dl_btn.setToolTip(
                self._tr("Downloads all world tiles at zoom levels 0–5 for every basemap type (~60–100 MB).")
            )
        if self._refresh_cache_btn is not None:
            self._refresh_cache_btn.setText(self._tr("Refresh cache status"))
        if self._logo_browse_btn is not None:
            self._logo_browse_btn.setText(self._tr("Browse company logo"))
        if self._gmdb_browse_btn is not None:
            self._gmdb_browse_btn.setText(self._tr("Browse .gmdb folder"))
        if self.include_ai and self.ai_enable_chk is not None:
            self.ai_enable_chk.setText(self._tr("Enable local AI (Ollama)"))
        if self._ai_hint_lbl is not None:
            self._ai_hint_lbl.setText(self._tr(_AI_SWOT_MODEL_TIP))
        self.backup_btn.setText(self._tr("Backup Database"))
        self.import_btn.setText(self._tr("Import SQLite Database"))
        self.export_btn.setText(self._tr("Export Database"))
        self.refresh_cache_status()

    def refresh_cache_status(self):
        if not self.tile_cache:
            return
        stats = self.tile_cache.get_basemap_cache_status()
        for basemap, lbl in self._cache_status_labels.items():
            info = stats.get(basemap, {})
            count = int(info.get("tile_count", 0))
            size_mb = float(info.get("size_mb", 0))
            if count > 0:
                lbl.setText(f"{count:,} {self._tr('tiles')} — {size_mb:.1f} MB")
            else:
                lbl.setText(self._tr("Not downloaded"))

    def apply_settings(self, show_message: bool = True):
        lang = self.language_combo.currentData()
        theme = self.theme_combo.currentData()
        font_size = self.font_size.value()
        self.settings.setValue("language", lang)
        self.settings.setValue("ui/theme", theme)
        self.settings.setValue(STARTUP_TAB_MODE_KEY, self.startup_tab_combo.currentData())
        self.settings.setValue("ui/font_size", font_size)
        self.settings.setValue("ui/font_color", self._font_color)
        self.settings.setValue(MAP_TILE_MODE_KEY, TILE_MODE_OFFLINE)
        self.settings.setValue(MAP_BASEMAP_KEY, self.default_basemap_combo.currentData())
        self.settings.setValue(MAP_DEFAULT_LAT_KEY, float(self.default_lat.value()))
        self.settings.setValue(MAP_DEFAULT_LON_KEY, float(self.default_lon.value()))
        self.settings.setValue(GMDB_DIR_KEY, self.gmdb_dir_input.text().strip())
        exts = self.gallery_exts_input.text().strip() or DEFAULT_GALLERY_2D_EXTENSIONS
        self.settings.setValue(GALLERY_2D_EXTENSIONS_KEY, exts)
        self.settings.setValue(
            BRAND_COMPANY_NAME_KEY,
            self.company_name_input.text().strip() or APP_CONFIG.get("organization", ""),
        )
        self.settings.setValue(BRAND_LOGO_WIDTH_KEY, int(self.logo_width_spin.value()))
        self.settings.setValue(BRAND_LOGO_HEIGHT_KEY, int(self.logo_height_spin.value()))
        self.settings.setValue(BRAND_LOGO_SCALE_PERCENT_KEY, int(self.logo_scale_spin.value()))
        self.settings.setValue(BRAND_LOGO_PATH_KEY, self.logo_path_input.text().strip())
        if self.include_ai:
            self.settings.setValue(AI_ENABLED_KEY, bool(self.ai_enable_chk.isChecked()))
            self.settings.setValue(AI_BASE_URL_KEY, self.ai_url_input.text().strip() or "http://localhost:11434")
            self.settings.setValue(AI_MODEL_KEY, self.ai_model_combo.currentText().strip() or "llama3.1")
            self.settings.setValue(AI_TEMPERATURE_KEY, float(self.ai_temp_spin.value()))
            self.settings.setValue(AI_TIMEOUT_S_KEY, int(self.ai_timeout_spin.value()))

        if self.theme_manager:
            self.theme_manager.apply_theme(theme)
        if self.lang_manager:
            self.lang_manager.load_language(lang)
        from utils.ui_helpers import apply_app_typography
        apply_app_typography(QApplication.instance(), bold=True, point_size=font_size)
        app = QApplication.instance()
        if app:
            font = app.font()
            font.setPointSize(font_size)
            app.setFont(font)
            base_style = app.styleSheet()
            if _FONT_OVERRIDE_START in base_style and _FONT_OVERRIDE_END in base_style:
                pattern = re.escape(_FONT_OVERRIDE_START) + r".*?" + re.escape(_FONT_OVERRIDE_END)
                base_style = re.sub(pattern, "", base_style, flags=re.DOTALL)
            override = (
                f"\n{_FONT_OVERRIDE_START}\n"
                f"QWidget{{font-size:{font_size}pt;color:{self._font_color};}}\n"
                f"{_FONT_OVERRIDE_END}\n"
            )
            app.setStyleSheet(base_style + override)
        if show_message:
            QMessageBox.information(self, self._tr("Settings"), self._tr("Settings applied."))
        self.settings_applied.emit()

    def _pick_color(self):
        color = QColorDialog.getColor(parent=self.window())
        if color.isValid():
            self._font_color = color.name()
            self.color_preview.setText(self._font_color)
            self.color_preview.setStyleSheet(f"color:{self._font_color};")

    def _active_db_url(self) -> str:
        if self.db_manager is not None and hasattr(self.db_manager, "database_url"):
            return str(self.db_manager.database_url)
        return str(APP_CONFIG["database_url"])

    def _backup_database(self):
        output, _ = QFileDialog.getSaveFileName(self, self._tr("Backup Database"), "armory_backup.db", "SQLite Database (*.db)")
        if not output:
            return
        try:
            path = backup_sqlite(self._active_db_url(), output)
            QMessageBox.information(self, self._tr("Backup Complete"), f"{self._tr('Backup saved to:')}\n{path}")
        except Exception as e:
            QMessageBox.warning(self, self._tr("Backup Failed"), str(e))

    def _import_database(self):
        source, _ = QFileDialog.getOpenFileName(self, self._tr("Import SQLite Database"), "", "SQLite Database (*.db *.sqlite *.sqlite3)")
        if not source:
            return
        confirm = QMessageBox.question(
            self, self._tr("Confirm Import"),
            self._tr("This will replace current local data with selected database.\nContinue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            target = import_sqlite_into_active(self._active_db_url(), source)
            QMessageBox.information(self, self._tr("Import Complete"), f"{target}")
            self.settings_applied.emit()
        except Exception as e:
            QMessageBox.warning(self, self._tr("Import Failed"), str(e))

    def _export_database(self):
        output, selected_filter = QFileDialog.getSaveFileName(
            self, self._tr("Export Database"), "armory_export",
            "SQLite Database (*.db);;SQL Dump (*.sql);;JSON (*.json);;CSV (*.csv)",
        )
        if not output:
            return
        export_format = "sqlite"
        if "SQL Dump" in selected_filter:
            export_format = "sql"
        elif "JSON" in selected_filter:
            export_format = "json"
        elif "CSV" in selected_filter:
            export_format = "csv"
        try:
            path = export_database(self._active_db_url(), output, export_format)
            QMessageBox.information(self, self._tr("Export Complete"), f"{path}")
        except Exception as e:
            QMessageBox.warning(self, self._tr("Export Failed"), str(e))

    def _browse_gmdb_dir(self):
        folder = QFileDialog.getExistingDirectory(self, self._tr("Select .gmdb maps folder"), self.gmdb_dir_input.text().strip() or "")
        if folder:
            self.gmdb_dir_input.setText(folder)

    def _browse_logo_file(self):
        logo_path, _ = QFileDialog.getOpenFileName(
            self, self._tr("Select company logo"), self.logo_path_input.text().strip() or "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All files (*.*)",
        )
        if logo_path:
            self.logo_path_input.setText(logo_path)
            pix = QPixmap(logo_path)
            if not pix.isNull():
                self.logo_width_spin.setValue(max(16, min(512, pix.width())))
                self.logo_height_spin.setValue(max(16, min(512, pix.height())))
