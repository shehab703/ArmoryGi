# views/pre_cache_dialog.py
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QDoubleSpinBox,
    QComboBox,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QFileDialog,
    QCheckBox,
    QWidget,
    QGroupBox,
    QMessageBox,
)
from config import TILE_CACHE_CONFIG
from utils.ui_helpers import fit_dialog_to_screen, make_scroll_content


BASEMAP_KEYS = ["dark", "satellite", "osm", "topo"]
WORLD_ZOOM_LEVELS = [0, 1, 2, 3, 4, 5]


class PreCacheDialog(QDialog):
    def __init__(self, parent=None, tile_cache=None):
        super().__init__(parent)
        self.tile_cache = tile_cache
        self.setWindowTitle("تحميل الخريطة للعمل بدون إنترنت")
        self._basemap_checks: dict[str, QCheckBox] = {}
        self._download_world = False
        self._init_ui()
        fit_dialog_to_screen(self, width=540, height=700)

    def _init_ui(self):
        outer = QVBoxLayout(self)
        content = QWidget()
        layout = QVBoxLayout(content)

        info = QLabel(
            "حمّل بلاطات الخريطة إلى مجلد محلي داخل البرنامج.\n"
            "بعد اكتمال التحميل ستعمل الخريطة بدون اتصال.\n"
            "يمكنك اختيار أكثر من نوع خريطة — كل نوع يُخزَّن في مجلد منفصل.\n"
            "كلما زاد نطاق التكبير أو المسافة، زاد حجم الملفات والوقت."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: palette(mid); margin-bottom: 10px;")
        layout.addWidget(info)

        cache_dir = getattr(self.tile_cache, "cache_dir", TILE_CACHE_CONFIG.get("cache_dir", ""))
        self.cache_path_lbl = QLabel(f"مجلد التخزين:\n{cache_dir}")
        self.cache_path_lbl.setWordWrap(True)
        self.cache_path_lbl.setStyleSheet("color: #7fdfff; font-size: 11px;")
        layout.addWidget(self.cache_path_lbl)

        form = QFormLayout()

        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90, 90)
        self.lat_spin.setValue(float(TILE_CACHE_CONFIG["pre_cache_config"]["center_lat"]))
        self.lat_spin.setSuffix(" °")

        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180, 180)
        self.lon_spin.setValue(float(TILE_CACHE_CONFIG["pre_cache_config"]["center_lon"]))
        self.lon_spin.setSuffix(" °")

        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(50, 25000)
        self.radius_spin.setValue(float(TILE_CACHE_CONFIG["pre_cache_config"]["radius_km"]))
        self.radius_spin.setSingleStep(250)
        self.radius_spin.setSuffix(" km")
        self.radius_spin.setToolTip("نصف القطر بالكيلومتر — حتى ~25000 كم (نصف محيط الأرض تقريباً)")

        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems([
            "Zoom 6-10 (موصى به / ~500MB)",
            "Zoom 5-9 (أسرع / ~200MB)",
            "Zoom 7-11 (تفاصيل عالية / ~1.2GB)",
            "Zoom 0-5 (نظرة عالم — منطقة محددة)",
        ])

        form.addRow("خط العرض:", self.lat_spin)
        form.addRow("خط الطول:", self.lon_spin)
        form.addRow("نصف القطر:", self.radius_spin)
        form.addRow("مستويات التكبير:", self.zoom_combo)
        layout.addLayout(form)

        basemap_box = QGroupBox("أنواع الخريطة للتحميل")
        basemap_layout = QVBoxLayout(basemap_box)
        labels = {
            "dark": "Dark (Carto)",
            "satellite": "Satellite (Esri)",
            "osm": "OpenStreetMap",
            "topo": "OpenTopoMap",
        }
        for key in BASEMAP_KEYS:
            chk = QCheckBox(labels.get(key, key))
            chk.setChecked(key == "dark")
            self._basemap_checks[key] = chk
            basemap_layout.addWidget(chk)
        select_row = QHBoxLayout()
        all_btn = QPushButton("تحديد الكل")
        none_btn = QPushButton("إلغاء الكل")
        all_btn.clicked.connect(lambda: self._set_all_basemaps(True))
        none_btn.clicked.connect(lambda: self._set_all_basemaps(False))
        select_row.addWidget(all_btn)
        select_row.addWidget(none_btn)
        basemap_layout.addLayout(select_row)
        layout.addWidget(basemap_box)

        world_info = QLabel(
            "تحميل العالم (Z0–Z5): ~1365 بلاطة لكل نوع خريطة (~15–25 MB).\n"
            "مناسب للتنقل العالمي بدون إنترنت بمستوى تفاصيل منخفض."
        )
        world_info.setWordWrap(True)
        world_info.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(world_info)

        self.world_btn = QPushButton("🌍 تحميل العالم — طبقات 0–5 (كل الأنواع)")
        self.world_btn.setStyleSheet("padding: 10px; font-weight: bold;")
        self.world_btn.setToolTip("يحمّل كل بلاطات العالم من الطبقة 0 إلى 5 لجميع أنواع الخرائط الأربعة")
        self.world_btn.clicked.connect(self._confirm_world_download)
        layout.addWidget(self.world_btn)

        tools_layout = QHBoxLayout()
        export_btn = QPushButton("تصدير الحزمة...")
        export_btn.clicked.connect(self._export_cache)
        import_btn = QPushButton("استيراد حزمة...")
        import_btn.clicked.connect(self._import_cache)
        tools_layout.addWidget(export_btn)
        tools_layout.addWidget(import_btn)
        layout.addLayout(tools_layout)
        layout.addStretch(1)

        scroll = make_scroll_content(content, self)
        outer.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("بدء التحميل (منطقة)")
        self.start_btn.setStyleSheet("padding: 8px 16px; font-weight: bold;")
        self.start_btn.clicked.connect(self._validate_and_accept)

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(cancel_btn)
        outer.addLayout(btn_layout)

    def _set_all_basemaps(self, checked: bool):
        for chk in self._basemap_checks.values():
            chk.setChecked(checked)

    def set_preselected_basemaps(self, basemaps: list[str]):
        if not basemaps:
            return
        for key, chk in self._basemap_checks.items():
            chk.setChecked(key in basemaps)

    def _selected_basemaps(self) -> list[str]:
        return [k for k, chk in self._basemap_checks.items() if chk.isChecked()]

    def _validate_and_accept(self):
        self._download_world = False
        if not self._selected_basemaps():
            QMessageBox.warning(self, "تحميل الخريطة", "اختر نوع خريطة واحداً على الأقل.")
            return
        self.accept()

    def _confirm_world_download(self):
        reply = QMessageBox.question(
            self,
            "تحميل العالم",
            "سيتم تحميل كل بلاطات العالم للطبقات 0–5\n"
            "لجميع أنواع الخرائط الأربعة (Dark, Satellite, OSM, Topo).\n\n"
            "الحجم التقريبي: 60–100 MB.\n"
            "هل تريد المتابعة؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_all_basemaps(True)
        self._download_world = True
        self.accept()

    def _export_cache(self):
        if not self.tile_cache:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "تصدير بلاطات الخريطة",
            "armorygis_map_cache.zip",
            "Zip Files (*.zip)",
        )
        if not path:
            return
        basemaps = self.get_config().get("basemaps") or ["dark"]
        self.tile_cache.export_cache(path, basemaps=basemaps)

    def _import_cache(self):
        if not self.tile_cache:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "استيراد بلاطات الخريطة",
            "",
            "Zip Files (*.zip)",
        )
        if not path:
            return
        self.tile_cache.import_cache(path)
        self.tile_cache.save_cache_index()

    def get_config(self) -> dict:
        if self._download_world:
            return {
                "mode": "world",
                "zooms": list(WORLD_ZOOM_LEVELS),
                "basemaps": list(BASEMAP_KEYS),
                "basemap": "dark",
                "lat": self.lat_spin.value(),
                "lon": self.lon_spin.value(),
                "radius": self.radius_spin.value(),
            }

        zoom_map = {
            "Zoom 6-10 (موصى به / ~500MB)": [6, 7, 8, 9, 10],
            "Zoom 5-9 (أسرع / ~200MB)": [5, 6, 7, 8, 9],
            "Zoom 7-11 (تفاصيل عالية / ~1.2GB)": [7, 8, 9, 10, 11],
            "Zoom 0-5 (نظرة عالم — منطقة محددة)": [0, 1, 2, 3, 4, 5],
            "Zoom 6-10 (Recommended / ~500MB)": [6, 7, 8, 9, 10],
            "Zoom 5-9 (Faster / ~200MB)": [5, 6, 7, 8, 9],
            "Zoom 7-11 (High Detail / ~1.2GB)": [7, 8, 9, 10, 11],
        }
        zoom_text = self.zoom_combo.currentText()
        basemaps = self._selected_basemaps()
        return {
            "mode": "region",
            "lat": self.lat_spin.value(),
            "lon": self.lon_spin.value(),
            "radius": self.radius_spin.value(),
            "zooms": zoom_map.get(zoom_text, [6, 7, 8, 9, 10]),
            "basemaps": basemaps,
            "basemap": basemaps[0] if basemaps else "dark",
        }

    def get_pre_cache_config(self) -> dict:
        return self.get_config()

    def set_world_download_mode(self):
        """Skip dialog — caller will accept after showing this dialog or use direct config."""
        self._download_world = True
        self._set_all_basemaps(True)
