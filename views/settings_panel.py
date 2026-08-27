from PyQt6.QtWidgets import QVBoxLayout, QPushButton, QWidget
from PyQt6.QtCore import pyqtSignal

from utils.ui_helpers import make_scroll_content
from views.settings_form import SettingsForm


class SettingsPanel(QWidget):
    settings_applied = pyqtSignal()
    precache_requested = pyqtSignal(list)
    world_precache_requested = pyqtSignal()

    def __init__(self, settings=None, theme_manager=None, lang_manager=None, db_manager=None, tile_cache=None, parent=None):
        super().__init__(parent)
        self.lang_manager = lang_manager
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.form = SettingsForm(
            settings=settings,
            theme_manager=theme_manager,
            lang_manager=lang_manager,
            db_manager=db_manager,
            tile_cache=tile_cache,
            include_ai=True,
        )
        scroll = make_scroll_content(self.form, self)
        root.addWidget(scroll, 1)

        self.apply_btn = QPushButton(self._tr("Apply Settings"))
        self.apply_btn.clicked.connect(lambda: self.form.apply_settings(show_message=True))
        root.addWidget(self.apply_btn)

        self.form.settings_applied.connect(self.settings_applied.emit)
        self.form.precache_requested.connect(self.precache_requested.emit)
        self.form.world_precache_requested.connect(self.world_precache_requested.emit)

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.form.lang_manager = lang_manager
        self.retranslate_ui()

    def retranslate_ui(self):
        self.apply_btn.setText(self._tr("Apply Settings"))
        self.form.retranslate_ui()

    def apply_settings(self):
        self.form.apply_settings(show_message=True)

    def refresh_cache_status(self):
        self.form.refresh_cache_status()
