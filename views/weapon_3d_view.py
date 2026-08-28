#!/usr/bin/env python3
"""
Professional 3D Weapon Viewer — Dedicated tab for immersive weapon presentation.
Uses model-viewer (glTF/GLB/USDZ) and Three.js preview for CAD meshes.
"""
from pathlib import Path
import base64
import io

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QFrame, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

from utils.weapon_media_library import (
    ensure_weapon_media_dirs, discover_models,
    weapon_media_root
)


class Weapon3DView(QWidget):
    """Dedicated professional 3D weapon presentation tab."""

    def __init__(self, db_manager, tile_cache=None, lang_manager=None, settings=None, parent=None):
        super().__init__(parent)
        self.db = db_manager
        self.tile_cache = tile_cache
        self.lang_manager = lang_manager
        self.settings = settings
        self.weapon = None
        self._last_loaded_model_path = None
        self._last_auto_rotate = True
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Professional header bar
        header_frame = QFrame()
        header_frame.setObjectName("weapon3dHeader")
        header_frame.setStyleSheet("QFrame{background:#081221;border:1px solid #1e3652;border-radius:10px;padding:10px 14px;}")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("عرض ثلاثي الأبعاد — 3D Weapon Viewer")
        self.title_label.setStyleSheet("font-size:18pt;font-weight:700;color:#e0edff;")
        header.addWidget(self.title_label, 1)

        self.info_label = QLabel("اختر سلاحًا من القائمة لعرضه ثلاثي الأبعاد")
        self.info_label.setStyleSheet("font-size:11pt;color:#7aa8d4;")
        header.addWidget(self.info_label, 0)
        root.addWidget(header_frame)

        # Main split layout
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet("QSplitter::handle{background:#15273f;border-radius:4px;}")

        # Left panel: model info + controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)

        # Weapon info card
        info_card = QFrame()
        info_card.setStyleSheet("QFrame{background:#0e1b2e;border:1px solid #1e3652;border-radius:10px;padding:10px;}")
        info_grid = QVBoxLayout(info_card)
        info_grid.setContentsMargins(4, 4, 4, 4)
        info_title = QLabel("معلومات السلاح")
        info_title.setStyleSheet("font-size:12pt;font-weight:700;color:#7fd4ff;padding-bottom:6px;border-bottom:1px solid #1e3652;")
        info_grid.addWidget(info_title)

        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["المواصفة", "القيمة"])
        self.info_table.horizontalHeader().setStretchLastSection(True)
        self.info_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.info_table.setMinimumHeight(200)
        self.info_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.info_table.setStyleSheet("QTableWidget{background:#0a1525;border:1px solid #1e3652;border-radius:8px;gridline-color:#1e3652;alternate-background-color:#0b182b;color:#d0e6ff;}"
                                   "QHeaderView::section{background:#15273f;color:#8ad8ff;font-weight:600;padding:6px;border:none;border-bottom:1px solid #1e3652;border-right:1px solid #1e3652;}")
        info_grid.addWidget(self.info_table)
        left_layout.addWidget(info_card, 1)

        # Professional controls
        controls_frame = QFrame()
        controls_frame.setStyleSheet("QFrame{background:#081221;border:1px solid #1e3652;border-radius:10px;padding:10px;}")
        controls_grid = QVBoxLayout(controls_frame)
        controls_grid.setContentsMargins(4, 4, 4, 4)
        controls_title = QLabel("عناصر التحكم")
        controls_title.setStyleSheet("font-size:11pt;font-weight:700;color:#7fd4ff;padding-bottom:6px;border-bottom:1px solid #1e3652;")
        controls_grid.addWidget(controls_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.load_btn = QPushButton("تحميل نموذج 3D")
        self.load_btn.clicked.connect(self._load_3d_model)
        self.load_btn.setStyleSheet("QPushButton{font-weight:700;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #13458a,stop:1 #0a2545);color:#cce8ff;border:none;border-radius:8px;padding:8px 14px;min-height:36px;}"
                                   "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1a5fa8,stop:1 #0b3566);}")
        btn_row.addWidget(self.load_btn)

        self.rotate_btn = QPushButton("دوران تلقائي")
        self.rotate_btn.setCheckable(True)
        self.rotate_btn.setChecked(True)
        self.rotate_btn.clicked.connect(self._toggle_rotate)
        self.rotate_btn.setStyleSheet("QPushButton{font-weight:600;background:#142b45;color:#aaddff;border:1px solid #2a4f75;border-radius:8px;padding:8px 14px;min-height:36px;}"
                                  "QPushButton:checked{background:#0d3a6e;color:#7fd4ff;border:1px solid #58a8ff;}"
                                  "QPushButton:hover{border:1px solid #58a8ff;}")
        btn_row.addWidget(self.rotate_btn)
        btn_row.addStretch(1)
        controls_grid.addLayout(btn_row)

        # Status label
        self.status_label = QLabel("جاهز — اختر سلاحًا للعرض")
        self.status_label.setStyleSheet("font-size:10pt;color:#7aa8d4;padding-top:6px;")
        controls_grid.addWidget(self.status_label)

        left_layout.addWidget(controls_frame, 0)
        splitter.addWidget(left_panel)

        # Right panel: 3D viewer
        right_frame = QFrame()
        right_frame.setStyleSheet("QFrame{background:#060e1a;border:1px solid #1e3652;border-radius:10px;}")
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(4, 4, 4, 4)

        # Viewer header
        viewer_header = QHBoxLayout()
        viewer_header.addWidget(QLabel("عرض ثلاثي الأبعاد"))
        viewer_header.addStretch(1)
        right_layout.addLayout(viewer_header)

        # 3D WebEngine viewer
        self.viewer = QWebEngineView()
        web_settings = self.viewer.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)

        # Default content (professional placeholder)
        self.viewer.setHtml(self._build_placeholder_html())
        right_layout.addWidget(self.viewer, 1)

        splitter.addWidget(right_frame)
        splitter.setSizes([360, 640])
        root.addWidget(splitter, 1)

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
    <div>◉ عرض السلاح ثلاثي الأبعاد</div>
    <div class="placeholder-sub">اضغط "تحميل نموذج 3D" لعرض نموذج السلاح</div>
  </div>
</body>
</html>"""

    def load_weapon(self, weapon: dict):
        if not weapon:
            self.weapon = None
            self.title_label.setText("عرض ثلاثي الأبعاد — 3D Weapon Viewer")
            self.info_table.setRowCount(0)
            self.status_label.setText("جاهز — اختر سلاحًا للعرض")
            self.viewer.setHtml(self._build_placeholder_html())
            return
        self.weapon = dict(weapon) if isinstance(weapon, dict) else weapon
        name = self.weapon.get("weapon_name", "سلاح غير معروف")
        model_name = self.weapon.get("model", "—")
        self.title_label.setText(f"◉ {name}")
        self.info_label.setText(f"{self._tr('الموديل')}: {model_name}")
        self.status_label.setText("سلاح محمّل — اضغط تحميل نموذج 3D")
        self._update_info_table()
        # Auto-load 3D if a primary model exists
        primary_model = self.weapon.get("primary_model")
        if not primary_model and self.weapon.get("models"):
            primary_model = (self.weapon.get("models") or [{}])[0].get("model_path")
        if primary_model and Path(str(primary_model)).exists():
            self._load_model_file(str(primary_model))

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

    def _build_3d_viewer_html(self, file_path: str, file_name: str, ext: str) -> str:
        safe_path = QUrl.fromLocalFile(file_path).toString()
        is_model_viewer_compatible = ext in (".glb", ".gltf", ".usdz")
        if is_model_viewer_compatible:
            return self._build_model_viewer_page(safe_path, file_name)
        else:
            return self._build_threejs_fallback_page(file_path, file_name, ext)

    def _build_model_viewer_page(self, url: str, name: str) -> str:
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
<script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
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
