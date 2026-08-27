from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QDialogButtonBox,
    QMessageBox,
    QWidget,
)
from database.db_manager import Category, Country, GuidanceType, PropulsionType
from utils.ui_helpers import fit_dialog_to_screen, make_scroll_content


class AddWeaponDialog(QDialog):
    def __init__(self, parent=None, db_manager=None, weapon=None):
        super().__init__(parent)
        self.db = db_manager
        self._weapon = weapon or {}
        self.setWindowTitle("Add Weapon" if not weapon else "Edit Weapon")
        outer = QVBoxLayout(self)
        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()

        self.weapon_name = QLineEdit(str(self._weapon.get("weapon_name", "")))
        self.model = QLineEdit(str(self._weapon.get("model", "")))
        self.category = QComboBox()
        self.country = QComboBox()
        self.range_km = QLineEdit(str(self._weapon.get("range_km", "")))
        self.speed_mach = QLineEdit(str(self._weapon.get("speed_mach", "")))
        self.weight_kg = QLineEdit(str(self._weapon.get("weight_kg", "")))
        self.manufacturer = QLineEdit(str(self._weapon.get("manufacturer", "")))
        self.status = QComboBox()
        self.status.addItems(["operational", "development", "testing", "retired", "export-only"])
        self.guidance = QComboBox()
        self.propulsion = QComboBox()
        self.platform = QLineEdit(str(self._weapon.get("platform", "")))
        self.notes = QTextEdit(str(self._weapon.get("notes", "")))

        self._fill_lookups()

        form.addRow("Weapon Name*", self.weapon_name)
        form.addRow("Model*", self.model)
        form.addRow("Category", self.category)
        form.addRow("Country", self.country)
        form.addRow("Range (km)", self.range_km)
        form.addRow("Speed (Mach)", self.speed_mach)
        form.addRow("Weight (kg)", self.weight_kg)
        form.addRow("Manufacturer", self.manufacturer)
        form.addRow("Status", self.status)
        form.addRow("Guidance", self.guidance)
        form.addRow("Propulsion", self.propulsion)
        form.addRow("Platform", self.platform)
        form.addRow("Notes", self.notes)

        layout.addLayout(form)
        scroll = make_scroll_content(content, self)
        outer.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        fit_dialog_to_screen(self, width=540, height=620)

    def _fill_lookups(self):
        self.category.addItem("Uncategorized", None)
        self.country.addItem("", None)
        self.guidance.addItem("", None)
        self.propulsion.addItem("", None)
        with self.db.get_session() as session:
            for item in session.query(Category).order_by(Category.name.asc()).all():
                self.category.addItem(item.name, item.id)
            for item in session.query(Country).order_by(Country.name.asc()).all():
                self.country.addItem(item.name, item.id)
            for item in session.query(GuidanceType).order_by(GuidanceType.name.asc()).all():
                self.guidance.addItem(item.name, item.id)
            for item in session.query(PropulsionType).order_by(PropulsionType.name.asc()).all():
                self.propulsion.addItem(item.name, item.id)

        self._set_combo_by_text(self.category, self._weapon.get("category"))
        self._set_combo_by_text(self.country, self._weapon.get("country"))
        self._set_combo_by_text(self.guidance, self._weapon.get("guidance"))
        self._set_combo_by_text(self.propulsion, self._weapon.get("propulsion"))
        status = str(self._weapon.get("status", "operational"))
        idx = self.status.findText(status)
        self.status.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _set_combo_by_text(combo: QComboBox, text):
        if not text:
            return
        idx = combo.findText(str(text))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _to_float(self, val):
        t = val.strip()
        if not t:
            return None
        return float(t)

    def _validate_and_accept(self):
        if not self.weapon_name.text().strip() or not self.model.text().strip():
            QMessageBox.warning(self, "Required Fields", "Weapon Name and Model are required.")
            return
        try:
            self.get_weapon_data()
        except ValueError:
            QMessageBox.warning(self, "Invalid Number", "Range/Speed/Weight must be numeric.")
            return
        self.accept()

    def get_weapon_data(self):
        return {
            "weapon_name": self.weapon_name.text().strip(),
            "model": self.model.text().strip(),
            "category_id": self.category.currentData(),
            "country_id": self.country.currentData(),
            "range_km": self._to_float(self.range_km.text()),
            "speed_mach": self._to_float(self.speed_mach.text()),
            "weight_kg": self._to_float(self.weight_kg.text()),
            "manufacturer": self.manufacturer.text().strip() or None,
            "status": self.status.currentText(),
            "guidance_id": self.guidance.currentData(),
            "propulsion_id": self.propulsion.currentData(),
            "platform": self.platform.text().strip() or None,
            "notes": self.notes.toPlainText().strip() or None,
        }

