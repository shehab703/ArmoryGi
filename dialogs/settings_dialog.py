from PyQt6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox, QPushButton
from PyQt6.QtCore import pyqtSignal

from utils.ui_helpers import fit_dialog_to_screen, make_scroll_content
from views.settings_form import SettingsForm


class SettingsDialog(QDialog):
    settings_applied = pyqtSignal()
    precache_requested = pyqtSignal(list)
    world_precache_requested = pyqtSignal()

    def __init__(self, parent=None, settings=None, theme_manager=None, lang_manager=None, db_manager=None, tile_cache=None):
        super().__init__(parent)
        self.lang_manager = lang_manager
        self.setWindowTitle(self._tr("Preferences"))
        layout = QVBoxLayout(self)

        self.form = SettingsForm(
            settings=settings,
            theme_manager=theme_manager,
            lang_manager=lang_manager,
            db_manager=db_manager,
            tile_cache=tile_cache,
            include_ai=True,
        )
        scroll = make_scroll_content(self.form, self)
        layout.addWidget(scroll, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_btn = QPushButton(self._tr("Apply"))
        self.buttons.addButton(self.apply_btn, QDialogButtonBox.ButtonRole.ApplyRole)
        self.apply_btn.clicked.connect(lambda: self.form.apply_settings(show_message=True))
        self.buttons.accepted.connect(self._apply_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.form.settings_applied.connect(self.settings_applied.emit)
        self.form.precache_requested.connect(self.precache_requested.emit)
        self.form.world_precache_requested.connect(self.world_precache_requested.emit)
        fit_dialog_to_screen(self)
        self.retranslate_ui()

    def _tr(self, text: str) -> str:
        if self.lang_manager:
            return self.lang_manager.tr(text)
        return text

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.form.lang_manager = lang_manager
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(self._tr("Preferences"))
        self.apply_btn.setText(self._tr("Apply"))
        ok_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn is not None:
            ok_btn.setText(self._tr("OK"))
        if cancel_btn is not None:
            cancel_btn.setText(self._tr("Cancel"))
        self.form.retranslate_ui()

    def _apply_and_accept(self):
        self.form.apply_settings(show_message=True)
        self.accept()

    def refresh_cache_status(self):
        self.form.refresh_cache_status()
