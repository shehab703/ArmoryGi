from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QListWidget,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot
from PyQt6.QtGui import QPixmap
from utils.weapon_media_library import stage_gallery_image
from utils.ai_prompts import build_weapon_notes_prompt
from utils.ai_service import get_ollama_client, is_ai_enabled

class WeaponDetailView(QWidget):
    show_on_map_requested = pyqtSignal(dict)

    def __init__(self, db_manager=None, tile_cache=None, lang_manager=None, settings=None):
        super().__init__()
        self.db = db_manager
        self.tile_cache = tile_cache
        self.lang_manager = lang_manager
        self.settings = settings
        self._current_weapon = None
        self._ai_thread: QThread | None = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        self.title_lbl = QLabel("Select a weapon to view details")
        self.title_lbl.setStyleSheet("font-size: 16pt; font-weight: 700; color: #1e3a5f;")
        layout.addWidget(self.title_lbl)
        self.subtitle_lbl = QLabel("")
        self.subtitle_lbl.setStyleSheet("font-size: 11pt; font-weight: 600; color: #475569;")
        layout.addWidget(self.subtitle_lbl)
        
        # Content
        content = QHBoxLayout()
        
        # Specs
        self.specs_box = QFormLayout()
        self.specs_box.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.specs_box.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.fields = {}
        fields = ['weapon_name', 'model', 'country', 'range_km', 'speed_mach', 'status', 'notes']
        field_align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        for f in fields:
            val = QLineEdit()
            val.setReadOnly(True)
            val.setAlignment(field_align)
            val.setMinimumHeight(34)
            val.setStyleSheet(
                "QLineEdit { background:#ffffff; border:1px solid #c8d7ed; border-radius:6px; "
                "padding:6px 10px; font-weight:600; color:#1f2937; }"
            )
            self.fields[f] = val
            self.specs_box.addRow(f.replace('_', ' ').title() + ":", val)
            
        specs_widget = QWidget()
        specs_widget.setLayout(self.specs_box)
        content.addWidget(specs_widget)
        
        # Gallery/Notes
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Operational Notes...")
        self.notes_edit.setReadOnly(True)
        self.notes_edit.setStyleSheet(
            "QTextEdit { background:#ffffff; border:1px solid #c8d7ed; border-radius:6px; "
            "padding:8px; font-weight:600; color:#1f2937; }"
        )
        right_panel = QVBoxLayout()
        right_panel.addWidget(self.notes_edit)
        notes_btns = QHBoxLayout()
        self.ai_notes_btn = QPushButton("AI Generate Notes")
        self.ai_notes_btn.clicked.connect(self._ai_generate_notes)
        self.save_notes_btn = QPushButton("Save Notes")
        self.save_notes_btn.clicked.connect(self._save_notes_to_db)
        notes_btns.addWidget(self.ai_notes_btn)
        notes_btns.addWidget(self.save_notes_btn)
        notes_btns.addStretch(1)
        right_panel.addLayout(notes_btns)
        self.gallery_list = QListWidget()
        self.gallery_list.setMinimumHeight(120)
        self.gallery_list.addItem("Gallery: no images")
        right_panel.addWidget(self.gallery_list)
        gal_btns = QHBoxLayout()
        self.add_gallery_btn = QPushButton("Add gallery images…")
        self.add_gallery_btn.clicked.connect(self._add_gallery_images)
        gal_btns.addWidget(self.add_gallery_btn)
        gal_btns.addStretch(1)
        right_panel.addLayout(gal_btns)
        self.show_map_btn = QPushButton("Show Weapon on Map")
        self.show_map_btn.clicked.connect(self._emit_show_on_map)
        right_panel.addWidget(self.show_map_btn)
        content.addLayout(right_panel)
        
        layout.addLayout(content)
        self.retranslate_ui()
        self._refresh_notes_buttons()

    def populate(self, data: dict):
        if not data: return
        self._current_weapon = data
        
        self.title_lbl.setText(f"{data.get('weapon_name', 'Unknown')}")
        self.subtitle_lbl.setText(
            f"{self._tr('Category')}: {self._tr_data(data.get('category', 'N/A'))} | Model: {data.get('model', '-')}"
        )
        
        for key, widget in self.fields.items():
            val = data.get(key)
            widget.setText(str(val) if val is not None else "--")
        
        self.notes_edit.setPlainText(data.get('notes', ''))
        self._refresh_notes_buttons()
        self.gallery_list.clear()
        images = data.get("images") or []
        if images:
            for img in images:
                self.gallery_list.addItem(img.get("image_path", "image"))
        else:
            self.gallery_list.addItem("Gallery: no images")

    def load_weapon(self, weapon):
        if isinstance(weapon, dict):
            self.populate(weapon)
        elif self.db and isinstance(weapon, int):
            loaded = self.db.get_weapon_by_id(weapon, eager_load=True)
            if loaded:
                self.populate(loaded.to_dict(include_images=True, include_variants=False))

    def clear(self):
        self.title_lbl.setText(self._tr("Select a weapon to view details"))
        self.subtitle_lbl.setText("")
        for widget in self.fields.values():
            widget.setText("")
        self.notes_edit.clear()
        self._refresh_notes_buttons()
        self.gallery_list.clear()
        self.gallery_list.addItem("Gallery: no images")

    def _emit_show_on_map(self):
        if self._current_weapon:
            self.show_on_map_requested.emit(self._current_weapon)

    def _add_gallery_images(self):
        if not self._current_weapon or not self.db:
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("Select a weapon first."))
            return
        wid = self._current_weapon.get("id")
        if not wid:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self._tr("Select images for gallery"),
            str(Path.home()),
            self._tr("Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp);;All files (*.*)"),
        )
        if not paths:
            return
        staged_paths = [stage_gallery_image(self._current_weapon or {}, p) for p in paths]
        added, skipped = self.db.add_weapon_images_batch(int(wid), staged_paths, set_first_as_primary=False)
        if added == 0 and skipped == 0:
            QMessageBox.warning(self, self._tr("Gallery"), self._tr("No images were added."))
            return
        self.load_weapon(int(wid))
        QMessageBox.information(
            self,
            self._tr("Gallery"),
            f"Added {added} image(s). Skipped or duplicates: {skipped}.",
        )

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.retranslate_ui()
        self._refresh_notes_buttons()

    def retranslate_ui(self):
        if not self._current_weapon:
            self.title_lbl.setText(self._tr("Select a weapon to view details"))
        self.show_map_btn.setText(self._tr("Show Weapon on Map"))
        self.add_gallery_btn.setText(self._tr("Add gallery images…"))
        self.ai_notes_btn.setText(self._tr("AI Generate Notes"))
        self.save_notes_btn.setText(self._tr("Save Notes"))
        if self.gallery_list.count() == 1 and self.gallery_list.item(0).text() == "Gallery: no images":
            self.gallery_list.item(0).setText(self._tr("Gallery: no images"))

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def _tr_data(self, value):
        if self.lang_manager:
            return self.lang_manager.tr_data(value)
        return value

    def _refresh_notes_buttons(self):
        can_ai = bool(self.settings and is_ai_enabled(self.settings) and self._current_weapon)
        self.ai_notes_btn.setEnabled(can_ai and self._ai_thread is None)
        self.save_notes_btn.setEnabled(bool(self.db and self._current_weapon and self._current_weapon.get("id")))

    class _AiWorker(QObject):
        finished = pyqtSignal(str)
        failed = pyqtSignal(str)

        def __init__(self, settings, weapon: dict, is_ar: bool, existing_notes: str):
            super().__init__()
            self._settings = settings
            self._weapon = weapon
            self._is_ar = is_ar
            self._existing = existing_notes

        @pyqtSlot()
        def run(self):
            try:
                client = get_ollama_client(self._settings)
                system, user = build_weapon_notes_prompt(
                    weapon=self._weapon,
                    is_ar=self._is_ar,
                    existing_notes=self._existing,
                )
                out = client.chat(system=system, user=user)
                self.finished.emit(str(out or "").strip())
            except Exception as e:
                self.failed.emit(str(e))

    def _ai_generate_notes(self):
        if not (self.settings and is_ai_enabled(self.settings)):
            QMessageBox.information(self, self._tr("AI"), self._tr("Enable local AI (Ollama) in Preferences first."))
            return
        if not self._current_weapon:
            return
        if self._ai_thread is not None:
            return

        self._refresh_notes_buttons()
        self.ai_notes_btn.setEnabled(False)

        is_ar = bool(self.lang_manager and hasattr(self.lang_manager, "is_arabic") and self.lang_manager.is_arabic())
        existing = self.notes_edit.toPlainText().strip()
        thread = QThread(self)
        worker = self._AiWorker(self.settings, dict(self._current_weapon), is_ar, existing)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _cleanup():
            try:
                thread.quit()
                thread.wait(1500)
            except Exception:
                pass
            self._ai_thread = None
            self._refresh_notes_buttons()
            worker.deleteLater()
            thread.deleteLater()

        def _ok(text: str):
            try:
                # show generated notes; allow saving with Save Notes
                self.notes_edit.setReadOnly(False)
                self.notes_edit.setPlainText(text)
                self.notes_edit.setReadOnly(True)
                wid = int(self._current_weapon.get("id") or 0) if self._current_weapon else 0
                if wid and self.db:
                    # Persist per-weapon generated AI notes for future recall.
                    self.db.update_weapon(wid, {"notes": text})
                    try:
                        self._current_weapon["notes"] = text
                    except Exception:
                        pass
            finally:
                _cleanup()

        def _fail(msg: str):
            try:
                QMessageBox.warning(self, self._tr("AI"), self._tr("AI notes generation failed."))
            finally:
                _cleanup()

        worker.finished.connect(_ok)
        worker.failed.connect(_fail)
        self._ai_thread = thread
        thread.start()

    def _save_notes_to_db(self):
        if not (self.db and self._current_weapon and self._current_weapon.get("id")):
            return
        wid = int(self._current_weapon.get("id"))
        notes = self.notes_edit.toPlainText()
        updated = self.db.update_weapon(wid, {"notes": notes})
        if not updated:
            QMessageBox.warning(self, self._tr("Notes"), self._tr("Failed to save notes."))
            return
        # refresh local weapon dict
        try:
            self._current_weapon["notes"] = notes
        except Exception:
            pass
        QMessageBox.information(self, self._tr("Notes"), self._tr("Notes saved."))