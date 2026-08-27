from pathlib import Path
import json

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QStackedWidget,
    QDialog,
    QDialogButtonBox,
    QButtonGroup,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from html import escape
from PyQt6.QtGui import QPixmap, QFont, QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from views.map_view import MapView
from utils.spec_fields import SPEC_FIELDS, SPEC_FIELDS_AR, resolve_spec_keys
from utils.weapon_media_library import (
    DEFAULT_GALLERY_2D_EXTENSIONS,
    GALLERY_2D_EXTENSIONS_KEY,
    discover_gallery_images,
    discover_models,
    ensure_weapon_media_dirs,
    parse_image_extensions_csv,
    weapon_media_root,
)

# 3D preview: model-viewer (glTF family + USDZ) vs Three.js loaders (common CAD meshes)
_MODEL_VIEWER_EXTS = frozenset({".glb", ".gltf", ".usdz"})
_THREE_JS_PREVIEW_EXTS = frozenset({".obj", ".stl", ".dae", ".ply", ".fbx"})
_THREE_JS_VERSION = "0.160.0"


class SingleWeaponView(QWidget):
    def __init__(self, db_manager, tile_cache, parent=None, lang_manager=None, settings=None):
        super().__init__(parent)
        self.db = db_manager
        self.tile_cache = tile_cache
        self.lang_manager = lang_manager
        self.settings = settings
        self.weapon = None
        self.gallery_images = []
        self.gallery_index = 0
        self._map_full_mode = False
        self._model_auto_rotate = True
        self._cinematic_intensity = "medium"
        self._full_map_dialog = None
        self._full_map_view = None
        self._preview_bg_tick = 0
        self._last_loaded_model_signature = None
        self._last_gallery_render_key = None

        root = QVBoxLayout(self)
        self.title = QLabel("Category -> Missile")
        self.title.setStyleSheet("font-size:18px;font-weight:700;")
        title_row = QHBoxLayout()
        title_row.addWidget(self.title, 1)
        self.spec_fields_btn = QPushButton("Spec Fields")
        self.spec_fields_btn.clicked.connect(self._show_spec_fields_dialog)
        title_row.addWidget(self.spec_fields_btn, 0)
        self.open_folder_btn = QPushButton("Open weapon folder")
        self.open_folder_btn.setToolTip("Open media folder (images & models) in File Explorer")
        self.open_folder_btn.clicked.connect(self._open_weapon_media_folder)
        title_row.addWidget(self.open_folder_btn, 0)
        root.addLayout(title_row)

        content = QHBoxLayout()
        root.addLayout(content)

        self.spec_table = QTableWidget(0, 2)
        self.spec_table.setHorizontalHeaderLabels(["Specification", "Value"])
        self.spec_table.horizontalHeader().setStretchLastSection(True)
        content.addWidget(self.spec_table, 2)

        right = QVBoxLayout()
        content.addLayout(right, 3)

        media_mode = QHBoxLayout()
        self.media_2d_btn = QPushButton("2D")
        self.media_3d_btn = QPushButton("3D")
        self.media_2d_btn.clicked.connect(lambda: self.media_stack.setCurrentIndex(0))
        self.media_3d_btn.clicked.connect(lambda: self.media_stack.setCurrentIndex(1))
        media_mode.addWidget(self.media_2d_btn)
        media_mode.addWidget(self.media_3d_btn)
        media_mode.addStretch(1)
        right.addLayout(media_mode)

        self.media_stack = QStackedWidget()
        self.gallery_label = QLabel("No image")
        self.gallery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gallery_label.setMinimumHeight(260)
        self.gallery_label.setStyleSheet("border:1px solid #2b3f63;")
        self.media_stack.addWidget(self.gallery_label)
        self.model3d_view = QWebEngineView()
        web_settings = self.model3d_view.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.media_stack.addWidget(self.model3d_view)
        right.addWidget(self.media_stack, 2)

        self.prev_btn = QPushButton("Prev Image")
        self.next_btn = QPushButton("Next Image")
        self.prev_btn.clicked.connect(self._prev_image)
        self.next_btn.clicked.connect(self._next_image)
        self.map_default_btn = QPushButton("Default Map View")
        self.map_full_btn = QPushButton("⛶ Full Map Layout")
        self.map_zoom_in_btn = QPushButton("Map Zoom +")
        self.map_zoom_out_btn = QPushButton("Map Zoom -")
        self.map_default_btn.clicked.connect(self._set_default_map_layout)
        self.map_full_btn.clicked.connect(self._set_full_map_layout)
        self.map_zoom_in_btn.clicked.connect(self._zoom_map_in)
        self.map_zoom_out_btn.clicked.connect(self._zoom_map_out)
        self.model_rotate_btn = QPushButton("⟳ Auto Rotate")
        self.model_rotate_btn.setCheckable(True)
        self.model_rotate_btn.setChecked(True)
        self.model_rotate_btn.clicked.connect(self._toggle_model_autorotate)
        self.fx_low_btn = QPushButton("◔")
        self.fx_mid_btn = QPushButton("◑")
        self.fx_high_btn = QPushButton("◕")
        for btn in (self.fx_low_btn, self.fx_mid_btn, self.fx_high_btn):
            btn.setCheckable(True)
        self.fx_group = QButtonGroup(self)
        self.fx_group.setExclusive(True)
        self.fx_group.addButton(self.fx_low_btn)
        self.fx_group.addButton(self.fx_mid_btn)
        self.fx_group.addButton(self.fx_high_btn)
        self.fx_mid_btn.setChecked(True)
        self.fx_low_btn.clicked.connect(lambda: self._set_cinematic_intensity("low"))
        self.fx_mid_btn.clicked.connect(lambda: self._set_cinematic_intensity("medium"))
        self.fx_high_btn.clicked.connect(lambda: self._set_cinematic_intensity("high"))
        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        controls_row.addWidget(self.prev_btn)
        controls_row.addWidget(self.next_btn)
        controls_row.addWidget(self.map_default_btn)
        controls_row.addWidget(self.map_full_btn)
        controls_row.addWidget(self.model_rotate_btn)
        controls_row.addWidget(self.map_zoom_in_btn)
        controls_row.addWidget(self.map_zoom_out_btn)
        controls_row.addWidget(self.fx_low_btn)
        controls_row.addWidget(self.fx_mid_btn)
        controls_row.addWidget(self.fx_high_btn)
        controls_row.addStretch(1)
        right.addLayout(controls_row)
        icon_font = QFont()
        icon_font.setPointSize(14)
        icon_font.setBold(True)
        neon_style = (
            "QPushButton{color:#7fffd4;border:1px solid #2a7da8;border-radius:10px;"
            "background:#08131f;padding:4px 10px;font-weight:700;}"
            "QPushButton:hover{border:1px solid #4de2ff;color:#b7ffff;}"
            "QPushButton:checked{border:1px solid #58d8ff;color:#58d8ff;}"
        )
        icon_size_style = "min-height:44px;max-height:44px;min-width:60px;max-width:60px;"
        for btn in (
            self.prev_btn,
            self.next_btn,
            self.map_default_btn,
            self.map_full_btn,
            self.model_rotate_btn,
            self.map_zoom_in_btn,
            self.map_zoom_out_btn,
            self.fx_low_btn,
            self.fx_mid_btn,
            self.fx_high_btn,
        ):
            btn.setStyleSheet(neon_style + icon_size_style)
            btn.setFont(icon_font)

        self.map_view = MapView(self.tile_cache, self.db)
        right.addWidget(self.map_view, 3)
        self.map_view.weapon_dropped_on_map.connect(self._on_target_drop)
        self.map_view.weapon_origin_changed.connect(self._on_origin_dragged)
        self.retranslate_ui()
        self._preview_bg_timer = QTimer(self)
        self._preview_bg_timer.timeout.connect(self._animate_preview_background)
        self._preview_bg_timer.start(220)
        self._animate_preview_background()

    def load_weapon(self, weapon: dict):
        if not weapon:
            return
        weapon_id = weapon.get("id")
        if weapon_id and self.db:
            loaded = self.db.get_weapon_by_id(int(weapon_id), eager_load=True)
            if loaded:
                weapon = loaded.to_dict(include_images=True, include_variants=False, include_models=True)
        self.weapon = weapon
        category = weapon.get("category", "N/A")
        name = weapon.get("weapon_name", "Unknown")
        self.title.setText(f"{category} -> {name}")
        self._load_specs(weapon)
        self._load_gallery(weapon)
        self._load_3d_model(weapon)
        self._draw_weapon_on_map()

    def _load_specs(self, weapon: dict):
        visible_keys = set(resolve_spec_keys(self.settings))
        ar = bool(self.lang_manager and hasattr(self.lang_manager, "is_arabic") and self.lang_manager.is_arabic())
        fields = []
        for key, label_en in SPEC_FIELDS:
            if key not in visible_keys:
                continue
            label = SPEC_FIELDS_AR.get(key, label_en) if ar else label_en
            value = weapon.get(key)
            if key in {"category", "country", "status", "guidance", "propulsion", "warhead_type", "platform", "manufacturer"}:
                value = self._tr_data(value)
            fields.append((label, value))
        self.spec_table.setRowCount(len(fields))
        for row, (k, v) in enumerate(fields):
            self.spec_table.setItem(row, 0, QTableWidgetItem(str(k)))
            self.spec_table.setItem(row, 1, QTableWidgetItem("" if v is None else str(v)))

    def _load_gallery(self, weapon: dict):
        self.gallery_images = []
        ensure_weapon_media_dirs(weapon)
        allowed_exts = self._allowed_2d_extensions()
        if weapon.get("images"):
            for img in weapon["images"]:
                path = img.get("image_path")
                if not path:
                    continue
                if Path(path).suffix.lower() in allowed_exts:
                    self.gallery_images.append(path)
        if (
            weapon.get("primary_image")
            and Path(str(weapon.get("primary_image"))).suffix.lower() in allowed_exts
            and weapon.get("primary_image") not in self.gallery_images
        ):
            self.gallery_images.insert(0, weapon.get("primary_image"))
        # Also include media-library folder images for this weapon model.
        for p in discover_gallery_images(weapon, allowed_exts=allowed_exts):
            if p not in self.gallery_images:
                self.gallery_images.append(p)
        self.gallery_index = 0
        self._render_gallery_image()

    def _allowed_2d_extensions(self) -> set[str]:
        if self.settings is None:
            return parse_image_extensions_csv(DEFAULT_GALLERY_2D_EXTENSIONS)
        raw = self.settings.value(GALLERY_2D_EXTENSIONS_KEY, DEFAULT_GALLERY_2D_EXTENSIONS, str)
        return parse_image_extensions_csv(raw)

    def _render_gallery_image(self):
        if not self.gallery_images:
            self.gallery_label.setText(self._tr("No gallery images"))
            self.gallery_label.setPixmap(QPixmap())
            self._last_gallery_render_key = None
            return
        path = self.gallery_images[self.gallery_index]
        size = self.gallery_label.size()
        render_key = (path, size.width(), size.height())
        if self._last_gallery_render_key == render_key:
            return
        if path and Path(path).exists():
            pix = QPixmap(path)
            if not pix.isNull():
                self.gallery_label.setPixmap(pix.scaled(
                    self.gallery_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                ))
                self._last_gallery_render_key = render_key
                return
        self.gallery_label.setText(self._tr("Image not found"))
        self._last_gallery_render_key = render_key

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_gallery_image()

    def _prev_image(self):
        if self.gallery_images:
            self.gallery_index = (self.gallery_index - 1) % len(self.gallery_images)
            self._render_gallery_image()

    def _next_image(self):
        if self.gallery_images:
            self.gallery_index = (self.gallery_index + 1) % len(self.gallery_images)
            self._render_gallery_image()

    def _draw_weapon_on_map(self, target_lat=None, target_lon=None):
        if not self.weapon:
            return
        lat = float(self.weapon.get("origin_lat") or 31.5)
        lon = float(self.weapon.get("origin_lon") or 34.8)
        max_range = float(self.weapon.get("range_km") or 0)
        min_range = max(max_range * 0.35, 0.0)
        blast_radius = float(self.weapon.get("warhead_weight_kg") or 0) * 12.0
        self.map_view.set_active_weapon(self.weapon)
        self.map_view.draw_weapon_effects(
            lat=lat,
            lon=lon,
            min_range_km=min_range,
            max_range_km=max_range,
            blast_radius_m=blast_radius,
            weapon_name=self.weapon.get("weapon_name", "Weapon"),
            target_lat=target_lat,
            target_lon=target_lon,
        )

    def _on_target_drop(self, weapon, lat, lon):
        if self.weapon and weapon and int(weapon.get("id", -1)) == int(self.weapon.get("id", -2)):
            self._draw_weapon_on_map(target_lat=lat, target_lon=lon)

    def _on_origin_dragged(self, weapon, lat, lon):
        if not self.weapon or not weapon:
            return
        if int(weapon.get("id", -1)) != int(self.weapon.get("id", -2)):
            return
        updated = self.db.update_weapon(int(self.weapon["id"]), {"origin_lat": float(lat), "origin_lon": float(lon)})
        if not updated:
            return
        self.weapon = updated.to_dict(include_images=True, include_variants=False)
        self._draw_weapon_on_map()

    def _zoom_map_in(self):
        self.map_view.zoom_in()

    def _zoom_map_out(self):
        self.map_view.zoom_out()

    def _set_full_map_layout(self):
        self._map_full_mode = True
        if self._full_map_dialog is None:
            self._create_full_map_dialog()
        if self.weapon:
            self._draw_weapon_on_full_map()
        self._full_map_dialog.showMaximized()
        self._full_map_dialog.raise_()
        self._full_map_dialog.activateWindow()

    def _set_default_map_layout(self):
        self._map_full_mode = False
        self.spec_table.setVisible(True)
        self.media_stack.setVisible(True)
        self.prev_btn.setVisible(True)
        self.next_btn.setVisible(True)
        self.model_rotate_btn.setVisible(True)
        if self._full_map_dialog is not None:
            self._full_map_dialog.close()

    def _toggle_model_autorotate(self):
        self._model_auto_rotate = self.model_rotate_btn.isChecked()
        if self.weapon:
            self._load_3d_model(self.weapon)

    def _set_cinematic_intensity(self, level: str):
        self._cinematic_intensity = level if level in {"low", "medium", "high"} else "medium"
        self._animate_preview_background()
        if self.weapon:
            self._load_3d_model(self.weapon)

    def _preview_scene_head_style(self) -> str:
        intensity_scale = {"low": 0.68, "medium": 1.0, "high": 1.35}.get(self._cinematic_intensity, 1.0)
        star_opacity = 0.34 * intensity_scale
        rays_opacity = 0.5 * intensity_scale
        rays2_opacity = 0.34 * intensity_scale
        glow_a = 0.25 * intensity_scale
        glow_b = 0.22 * intensity_scale
        glow_c = 0.08 * intensity_scale
        halogen_mult = 1.0 if self._cinematic_intensity == "medium" else (0.7 if self._cinematic_intensity == "low" else 1.35)
        return f"""    <style>
      html,body{{margin:0;height:100%;background:#0f1720;}}
      #preview-scene{{position:relative;width:100%;height:100%;overflow:hidden;background:#070f1a;}}
      #space-bg{{
        position:absolute;inset:0;z-index:0;
        background:
          radial-gradient(circle at 50% 50%, rgba(8,14,24,0.03) 0%, rgba(8,14,24,0.06) 26%, rgba(4,8,14,0.92) 62%, rgba(3,7,12,1) 100%),
          linear-gradient(115deg, rgba(255,193,94,0.08) 0%, rgba(88,216,255,0.06) 42%, rgba(108,255,227,0.05) 78%, rgba(10,22,36,0.4) 100%),
          repeating-linear-gradient(0deg, rgba(65,200,255,0.09) 0 1px, transparent 1px 26px),
          repeating-linear-gradient(90deg, rgba(88,216,255,0.08) 0 1px, transparent 1px 26px),
          linear-gradient(180deg, #081221 0%, #070f1a 100%);
        animation: gridBreath 16s ease-in-out infinite, huePulse 9s ease-in-out infinite;
      }}
      #space-rays{{
        position:absolute;inset:-12%;z-index:0;opacity:{rays_opacity:.3f};
        background:
          radial-gradient(ellipse at 28% 42%, rgba(126, 220, 255, 0.22) 0%, rgba(126, 220, 255, 0.08) 28%, transparent 62%),
          radial-gradient(ellipse at 74% 58%, rgba(255, 202, 126, 0.16) 0%, rgba(255, 202, 126, 0.07) 25%, transparent 58%);
        filter: blur(12px);
        animation: smokeDriftA 20s ease-in-out infinite;
      }}
      #space-rays-2{{
        position:absolute;inset:-18%;z-index:0;opacity:{rays2_opacity:.3f};
        background:
          radial-gradient(ellipse at 64% 34%, rgba(96, 208, 255, 0.20) 0%, rgba(96, 208, 255, 0.06) 30%, transparent 65%),
          radial-gradient(ellipse at 40% 72%, rgba(255, 186, 105, 0.13) 0%, rgba(255, 186, 105, 0.05) 30%, transparent 64%);
        filter: blur(16px);
        animation: smokeDriftB 24s ease-in-out infinite;
      }}
      #space-halogen{{
        position:absolute;inset:0;z-index:0;pointer-events:none;
        background:
          radial-gradient(ellipse at 50% 50%, rgba(255,196,104,{0.20 * halogen_mult:.3f}) 0%, rgba(255,196,104,{0.08 * halogen_mult:.3f}) 16%, rgba(255,196,104,0.00) 35%),
          radial-gradient(ellipse at 50% 50%, rgba(88,216,255,{0.16 * halogen_mult:.3f}) 0%, rgba(88,216,255,{0.07 * halogen_mult:.3f}) 28%, rgba(88,216,255,0.00) 52%);
        mix-blend-mode: screen;
        animation: halogenPulse 6.5s ease-in-out infinite;
      }}
      #space-stars{{
        position:absolute;inset:-12%;z-index:0;opacity:{star_opacity:.3f};pointer-events:none;
        background:
          radial-gradient(circle at 12% 24%, rgba(180,235,255,0.85) 0 1px, transparent 1.3px),
          radial-gradient(circle at 28% 70%, rgba(165,223,255,0.75) 0 1px, transparent 1.4px),
          radial-gradient(circle at 46% 38%, rgba(255,214,140,0.70) 0 1px, transparent 1.5px),
          radial-gradient(circle at 62% 82%, rgba(170,236,255,0.62) 0 1px, transparent 1.4px),
          radial-gradient(circle at 78% 20%, rgba(255,206,122,0.62) 0 1px, transparent 1.4px),
          radial-gradient(circle at 90% 60%, rgba(173,240,255,0.72) 0 1px, transparent 1.3px);
        animation: starDrift 24s linear infinite;
      }}
      #space-glow{{
        position:absolute;inset:0;z-index:0;pointer-events:none;
        box-shadow:
          inset 0 0 90px rgba(88,216,255,{glow_a:.3f}),
          inset 0 0 170px rgba(28,120,180,{glow_b:.3f}),
          inset 0 0 220px rgba(255,196,104,{glow_c:.3f});
      }}
      model-viewer{{position:relative;z-index:1;width:100%;height:100%;background:transparent;}}
      #three-mount{{position:relative;z-index:1;width:100%;height:100%;}}
      #three-mount canvas{{display:block;outline:none;}}
      #load-status{{position:absolute;left:12px;bottom:12px;color:#ffcf7a;font:12px Segoe UI, sans-serif;max-width:92%;}}
      #fallback-preview{{
        display:none;
        height:100%;
        box-sizing:border-box;
        padding:16px;
        color:#c8d2e6;
        font:13px Segoe UI, sans-serif;
      }}
      #fallback-box{{
        border:1px dashed #3d5477;
        border-radius:8px;
        min-height:170px;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#8ca6cf;
        margin-bottom:12px;
      }}
      #fallback-title{{font-weight:700;margin-bottom:8px;color:#ffcf7a;}}
      #fallback-meta div{{margin:3px 0;}}
      #fallback-hint{{margin-top:10px;color:#91b3ff;}}
      @keyframes gridBreath {{
        0% {{ transform: scale(1.00); }}
        50% {{ transform: scale(1.035); }}
        100% {{ transform: scale(1.00); }}
      }}
      @keyframes smokeDriftA {{
        0% {{ transform: translate3d(0,0,0) scale(1.00); }}
        50% {{ transform: translate3d(-18px, 10px, 0) scale(1.04); }}
        100% {{ transform: translate3d(0,0,0) scale(1.00); }}
      }}
      @keyframes smokeDriftB {{
        0% {{ transform: translate3d(0,0,0) scale(1.00); }}
        50% {{ transform: translate3d(14px, -9px, 0) scale(1.05); }}
        100% {{ transform: translate3d(0,0,0) scale(1.00); }}
      }}
      @keyframes halogenPulse {{
        0% {{ opacity:0.78; }}
        50% {{ opacity:1; }}
        100% {{ opacity:0.78; }}
      }}
      @keyframes huePulse {{
        0% {{ filter:hue-rotate(0deg); }}
        50% {{ filter:hue-rotate(12deg); }}
        100% {{ filter:hue-rotate(0deg); }}
      }}
      @keyframes starDrift {{
        0% {{ transform: translate3d(0,0,0); opacity:0.26; }}
        50% {{ transform: translate3d(-18px, 12px, 0); opacity:0.38; }}
        100% {{ transform: translate3d(-36px, 24px, 0); opacity:0.26; }}
      }}
    </style>"""

    def _build_model_viewer_html(
        self,
        viewer_node: str,
        safe_model_name: str,
        safe_model_ext: str,
        safe_model_dir: str,
        model_size_kb: str,
        safe_bundled_viewer_url: str,
    ) -> str:
        head_style = self._preview_scene_head_style()
        return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
{head_style}
  </head>
  <body>
    <div id="preview-scene">
      <div id="space-bg"></div>
      <div id="space-rays"></div>
      <div id="space-rays-2"></div>
      <div id="space-stars"></div>
      <div id="space-halogen"></div>
      <div id="space-glow"></div>
      {viewer_node}
    </div>
    <div id="fallback-preview">
      <div id="fallback-title">Offline fallback preview</div>
      <div id="fallback-box">3D interactive viewer unavailable</div>
      <div id="fallback-meta">
        <div><b>File:</b> {safe_model_name}</div>
        <div><b>Type:</b> {safe_model_ext}</div>
        <div><b>Size:</b> {model_size_kb} KB</div>
        <div><b>Location:</b> {safe_model_dir}</div>
      </div>
      <div id="fallback-hint">Install resources/html/Js/model-viewer.min.js for guaranteed offline interactive rotation.</div>
    </div>
    <div id="load-status"></div>
    <script>
      const modelViewer = document.getElementById("weapon-model");
      const fallbackNode = document.getElementById("fallback-preview");
      const statusNode = document.getElementById("load-status");
      let scriptReady = false;
      const bundledViewerSrc = "{safe_bundled_viewer_url}";
      const scriptCandidates = [];

      if (bundledViewerSrc) {{
        scriptCandidates.push(bundledViewerSrc);
      }}
      scriptCandidates.push("https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js");
      scriptCandidates.push("https://cdn.jsdelivr.net/npm/@google/model-viewer/dist/model-viewer.min.js");

      function showFallback(message) {{
        if (modelViewer) {{
          modelViewer.style.display = "none";
        }}
        if (fallbackNode) {{
          fallbackNode.style.display = "block";
        }}
        if (statusNode) {{
          statusNode.textContent = message || "";
        }}
      }}

      function loadViewerScript(index) {{
        if (window.customElements.get("model-viewer")) {{
          scriptReady = true;
          return;
        }}
        if (index >= scriptCandidates.length) {{
          showFallback("Model viewer script unavailable. Install local bundle for offline use.");
          return;
        }}
        const scriptNode = document.createElement("script");
        scriptNode.type = "module";
        scriptNode.src = scriptCandidates[index];
        scriptNode.addEventListener("load", () => {{
          scriptReady = true;
        }});
        scriptNode.addEventListener("error", () => {{
          loadViewerScript(index + 1);
        }});
        document.head.appendChild(scriptNode);
      }}

      if (modelViewer) {{
        loadViewerScript(0);
      }}

      window.setTimeout(() => {{
        if (!scriptReady && !window.customElements.get("model-viewer")) {{
          showFallback("Model viewer could not initialize. Showing static metadata preview.");
        }}
      }}, 2200);

      if (modelViewer && statusNode) {{
        modelViewer.addEventListener("load", () => {{
          let hasAnyTexture = false;
          try {{
            const materials = modelViewer.model && modelViewer.model.materials ? modelViewer.model.materials : [];
            for (const mat of materials) {{
              const pbr = mat && mat.pbrMetallicRoughness ? mat.pbrMetallicRoughness : null;
              const baseTex = pbr && pbr.baseColorTexture ? pbr.baseColorTexture : null;
              const normalTex = mat && mat.normalTexture ? mat.normalTexture : null;
              const emissiveTex = mat && mat.emissiveTexture ? mat.emissiveTexture : null;
              if (baseTex || normalTex || emissiveTex) {{
                hasAnyTexture = true;
                break;
              }}
            }}
          }} catch (_) {{}}
          statusNode.textContent = hasAnyTexture ? "" : "Model loaded, but texture maps were not detected.";
        }});
        modelViewer.addEventListener("error", (event) => {{
          const detail = (event && event.detail && event.detail.type) ? event.detail.type : "unknown";
          showFallback("3D load failed (" + detail + "). Check model path/access.");
        }});
      }}
    </script>
  </body>
</html>
"""

    def _three_import_map_html(self) -> str:
        """Prefer vendored Three.js under resources/html/Js/three for offline preview; else CDN."""
        root = Path(__file__).resolve().parents[1] / "resources" / "html" / "Js" / "three"
        mod = root / "build" / "three.module.js"
        jsm = root / "examples" / "jsm"
        if mod.is_file() and jsm.is_dir():
            three_url = QUrl.fromLocalFile(str(mod.resolve(strict=False))).toString()
            addons_url = QUrl.fromLocalFile(str(jsm.resolve(strict=False))).toString()
            if not addons_url.endswith("/"):
                addons_url += "/"
            payload = {"imports": {"three": three_url, "three/addons/": addons_url}}
        else:
            ver = _THREE_JS_VERSION
            payload = {
                "imports": {
                    "three": f"https://cdn.jsdelivr.net/npm/three@{ver}/build/three.module.js",
                    "three/addons/": f"https://cdn.jsdelivr.net/npm/three@{ver}/examples/jsm/",
                }
            }
        return '<script type="importmap">\n' + json.dumps(payload, indent=2) + "\n</script>"

    def _build_three_js_preview_html(self, model_file: Path, model_ext: str, model_size_kb: str, safe_model_dir: str) -> str:
        head_style = self._preview_scene_head_style()
        import_map = self._three_import_map_html()
        url_lit = json.dumps(QUrl.fromLocalFile(str(model_file.resolve(strict=False))).toString())
        ext_lit = json.dumps(model_ext.lower())
        rot_lit = json.dumps(bool(self._model_auto_rotate))
        module_script = f"""<script type="module">
(async function() {{
  const mount = document.getElementById("three-mount");
  const statusNode = document.getElementById("load-status");
  const modelUrl = {url_lit};
  const ext = {ext_lit};
  const autoRotate = {rot_lit};
  try {{
    const THREE = await import("three");
    const {{ OrbitControls }} = await import("three/addons/controls/OrbitControls.js");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      45,
      Math.max(1, mount.clientWidth) / Math.max(1, mount.clientHeight),
      0.01,
      10000000
    );
    const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    if ("outputColorSpace" in renderer) {{
      renderer.outputColorSpace = THREE.SRGBColorSpace;
    }}
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    const hemi = new THREE.HemisphereLight(0xffffff, 0x223344, 1.05);
    scene.add(hemi);
    const dir = new THREE.DirectionalLight(0xffffff, 0.9);
    dir.position.set(60, 120, 80);
    scene.add(dir);

    let root = null;
    if (ext === ".obj") {{
      const {{ OBJLoader }} = await import("three/addons/loaders/OBJLoader.js");
      root = await new OBJLoader().loadAsync(modelUrl);
    }} else if (ext === ".stl") {{
      const {{ STLLoader }} = await import("three/addons/loaders/STLLoader.js");
      const geom = await new STLLoader().loadAsync(modelUrl);
      const mat = new THREE.MeshStandardMaterial({{
        color: 0xb8c5d9,
        metalness: 0.18,
        roughness: 0.52,
      }});
      root = new THREE.Mesh(geom, mat);
    }} else if (ext === ".dae") {{
      const {{ ColladaLoader }} = await import("three/addons/loaders/ColladaLoader.js");
      const collada = await new ColladaLoader().loadAsync(modelUrl);
      root = collada.scene;
    }} else if (ext === ".ply") {{
      const {{ PLYLoader }} = await import("three/addons/loaders/PLYLoader.js");
      const geom = await new PLYLoader().loadAsync(modelUrl);
      const vc = !!(geom && geom.attributes && geom.attributes.color);
      const mat = new THREE.MeshStandardMaterial({{
        color: 0xb8c5d9,
        metalness: 0.15,
        roughness: 0.5,
        vertexColors: vc,
      }});
      root = new THREE.Mesh(geom, mat);
    }} else if (ext === ".fbx") {{
      const {{ FBXLoader }} = await import("three/addons/loaders/FBXLoader.js");
      root = await new FBXLoader().loadAsync(modelUrl);
    }} else {{
      throw new Error("Unsupported mesh format for Three.js preview: " + ext);
    }}

    scene.add(root);

    function frameObject(obj) {{
      const box = new THREE.Box3().setFromObject(obj);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z, 0.0001);
      const dist = maxDim * 2.4;
      camera.position.set(center.x + dist * 0.55, center.y + dist * 0.28, center.z + dist);
      camera.near = Math.max(dist / 5000, 0.01);
      camera.far = Math.max(dist * 80, 5000);
      camera.updateProjectionMatrix();
      camera.lookAt(center);
      controls.target.copy(center);
      controls.update();
    }}
    frameObject(root);

    const clock = new THREE.Clock();
    function animate() {{
      requestAnimationFrame(animate);
      if (autoRotate && root) {{
        root.rotation.y += 0.65 * clock.getDelta();
      }}
      controls.update();
      renderer.render(scene, camera);
    }}
    animate();

    window.addEventListener("resize", () => {{
      const w = mount.clientWidth;
      const h = Math.max(1, mount.clientHeight);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }});

    if (statusNode) statusNode.textContent = "";
  }} catch (err) {{
    const msg = err && err.message ? err.message : String(err);
    if (statusNode) statusNode.textContent = "3D preview (Three.js): " + msg;
  }}
}})();
</script>"""
        return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
{head_style}
{import_map}
  </head>
  <body>
    <div id="preview-scene">
      <div id="space-bg"></div>
      <div id="space-rays"></div>
      <div id="space-rays-2"></div>
      <div id="space-stars"></div>
      <div id="space-halogen"></div>
      <div id="space-glow"></div>
      <div id="three-mount"></div>
    </div>
    <div id="load-status">Loading 3D preview…</div>
{module_script}
  </body>
</html>
"""

    def _load_3d_model(self, weapon: dict):
        ensure_weapon_media_dirs(weapon)
        model_path = weapon.get("primary_model")
        if not model_path and weapon.get("models"):
            model_path = (weapon.get("models") or [{}])[0].get("model_path")
        if not model_path:
            discovered = discover_models(weapon)
            if discovered:
                model_path = discovered[0]
        if not model_path or not Path(model_path).exists():
            self.model3d_view.setHtml("<html><body style='background:#0f1720;color:#9aa;font-family:Segoe UI;display:flex;justify-content:center;align-items:center;height:100%;'>No 3D model</body></html>")
            return
        model_file = Path(model_path)
        model_name = model_file.name
        model_ext = model_file.suffix.lower()
        supported_exts = _MODEL_VIEWER_EXTS | _THREE_JS_PREVIEW_EXTS
        if model_ext not in supported_exts:
            self.model3d_view.setHtml(
                f"<html><body style='background:#0f1720;color:#ffad66;font-family:Segoe UI;display:flex;justify-content:center;align-items:center;height:100%;'>Unsupported model format: {escape(model_ext)}</body></html>"
            )
            return
        model_signature = (str(model_file.resolve(strict=False)), self._model_auto_rotate, self._cinematic_intensity, model_ext)
        if self._last_loaded_model_signature == model_signature:
            return
        model_url = QUrl.fromLocalFile(str(model_file)).toString()
        safe_model_url = escape(model_url, quote=True)
        safe_model_name = escape(model_name)
        safe_model_ext = escape(model_ext)
        safe_model_dir = escape(str(model_file.parent))
        bundled_viewer_script = Path(__file__).resolve().parents[1] / "resources" / "html" / "Js" / "model-viewer.min.js"
        bundled_viewer_url = ""
        if bundled_viewer_script.exists():
            bundled_viewer_url = QUrl.fromLocalFile(str(bundled_viewer_script)).toString()
        safe_bundled_viewer_url = escape(bundled_viewer_url, quote=True)
        model_size_kb = ""
        try:
            model_size_kb = f"{model_file.stat().st_size / 1024.0:.1f}"
        except OSError:
            model_size_kb = "unknown"

        if model_ext in _MODEL_VIEWER_EXTS:
            auto_rotate = "auto-rotate" if self._model_auto_rotate else ""
            viewer_node = (
                f'<model-viewer id="weapon-model" src="{safe_model_url}" alt="{safe_model_name}" '
                f'environment-image="neutral" exposure="1" shadow-intensity="1" '
                f'camera-controls rotation-per-second="24deg" {auto_rotate}></model-viewer>'
            )
            html = self._build_model_viewer_html(
                viewer_node,
                safe_model_name,
                safe_model_ext,
                safe_model_dir,
                model_size_kb,
                safe_bundled_viewer_url,
            )
        else:
            html = self._build_three_js_preview_html(model_file, model_ext, model_size_kb, safe_model_dir)

        self.model3d_view.setHtml(html, QUrl.fromLocalFile(str(model_file.parent) + "/"))
        self._last_loaded_model_signature = model_signature

    def _create_full_map_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(self._tr("Full Map Layout"))
        dlg_layout = QVBoxLayout(dlg)
        self._full_map_view = MapView(self.tile_cache, self.db)
        dlg_layout.addWidget(self._full_map_view, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.close)
        btns.accepted.connect(dlg.close)
        dlg_layout.addWidget(btns)
        self._full_map_dialog = dlg

    def _draw_weapon_on_full_map(self):
        if not self.weapon or self._full_map_view is None:
            return
        lat = float(self.weapon.get("origin_lat") or 31.5)
        lon = float(self.weapon.get("origin_lon") or 34.8)
        max_range = float(self.weapon.get("range_km") or 0)
        min_range = max(max_range * 0.35, 0.0)
        blast_radius = float(self.weapon.get("warhead_weight_kg") or 0) * 12.0
        self._full_map_view.set_active_weapon(self.weapon)
        self._full_map_view.draw_weapon_effects(
            lat=lat,
            lon=lon,
            min_range_km=min_range,
            max_range_km=max_range,
            blast_radius_m=blast_radius,
            weapon_name=self.weapon.get("weapon_name", "Weapon"),
            target_lat=None,
            target_lon=None,
        )

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.retranslate_ui()
        if self.weapon:
            self.load_weapon(self.weapon)

    def retranslate_ui(self):
        self.spec_table.setHorizontalHeaderLabels([self._tr("Specification"), self._tr("Value")])
        if not self.weapon:
            self.title.setText(self._tr("Category -> Missile"))
        self.prev_btn.setText("◀")
        self.prev_btn.setToolTip(self._tr("Prev Image"))
        self.next_btn.setText("▶")
        self.next_btn.setToolTip(self._tr("Next Image"))
        self.media_2d_btn.setText("2D")
        self.media_3d_btn.setText("3D")
        self.map_default_btn.setText("◉")
        self.map_default_btn.setToolTip(self._tr("Default Map View"))
        self.map_full_btn.setText("▣")
        self.map_full_btn.setToolTip(self._tr("Full Map Layout"))
        self.model_rotate_btn.setText("↻")
        self.model_rotate_btn.setToolTip(self._tr("⟳ Auto Rotate"))
        self.map_zoom_in_btn.setText("+")
        self.map_zoom_in_btn.setToolTip(self._tr("Map Zoom +"))
        self.map_zoom_out_btn.setText("−")
        self.map_zoom_out_btn.setToolTip(self._tr("Map Zoom -"))
        self.spec_fields_btn.setText(self._tr("Spec Fields"))
        self.open_folder_btn.setText(self._tr("Open weapon folder"))
        self.open_folder_btn.setToolTip(self._tr("Open media folder (images & models) in File Explorer"))
        self.fx_low_btn.setToolTip(self._tr("Cinematic intensity: low"))
        self.fx_mid_btn.setToolTip(self._tr("Cinematic intensity: medium"))
        self.fx_high_btn.setToolTip(self._tr("Cinematic intensity: high"))
        if self.gallery_label.text() == "No image":
            self.gallery_label.setText(self._tr("No image"))

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def _tr_data(self, value):
        if self.lang_manager:
            return self.lang_manager.tr_data(value)
        return value

    def _animate_preview_background(self):
        if not self.isVisible() or self.media_stack.currentIndex() != 0:
            return
        self._preview_bg_tick = (self._preview_bg_tick + 1) % 360
        phase = self._preview_bg_tick
        bg_mul = {"low": 0.72, "medium": 1.0, "high": 1.36}.get(self._cinematic_intensity, 1.0)
        c1 = min(int((72 + (phase % 36)) * bg_mul), 160)
        c2 = min(int((34 + (phase % 22)) * bg_mul), 120)
        c3 = min(int((24 + (phase % 18)) * bg_mul), 90)
        # Animated techno gradient behind 2D preview while keeping center readable.
        self.gallery_label.setStyleSheet(
            "QLabel{"
            "border:1px solid #2b3f63;"
            "background:"
            "qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, "
            "stop:0 rgba(10, 18, 30, 28), stop:0.28 rgba(10, 18, 30, 45), stop:1 rgba(3, 8, 14, 230)),"
            f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(74, 212, 255, {c1}), stop:0.62 rgba(255, 196, 104, {c2}), stop:1 rgba(6, 15, 28, 180)),"
            f"qlineargradient(x1:1, y1:0, x2:0, y2:1, stop:0 rgba(88, 216, 255, {c3}), stop:1 rgba(5, 10, 18, 0));"
            "}"
        )

    def _show_spec_fields_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(self._tr("Select specification fields"))
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        lst = QListWidget()
        selected = set(resolve_spec_keys(self.settings))
        for key, label_en in SPEC_FIELDS:
            ar = bool(self.lang_manager and hasattr(self.lang_manager, "is_arabic") and self.lang_manager.is_arabic())
            label = SPEC_FIELDS_AR.get(key, label_en) if ar else label_en
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
            lst.addItem(item)
        layout.addWidget(lst)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = []
        for i in range(lst.count()):
            it = lst.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                chosen.append(str(it.data(Qt.ItemDataRole.UserRole)))
        if not chosen:
            return
        from utils.spec_fields import save_spec_keys
        save_spec_keys(self.settings, chosen)
        if self.weapon:
            self._load_specs(self.weapon)

    def _open_weapon_media_folder(self):
        if not self.weapon or not self.weapon.get("id"):
            QMessageBox.information(
                self,
                self._tr("Open weapon folder"),
                self._tr("Load a weapon first."),
            )
            return
        root = weapon_media_root(self.weapon)
        url = QUrl.fromLocalFile(str(root.resolve(strict=False)))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                self._tr("Open weapon folder"),
                self._tr("Could not open folder. Path:\n") + str(root),
            )
