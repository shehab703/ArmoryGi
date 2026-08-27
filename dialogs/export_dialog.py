from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QAbstractItemView,
    QWidget,
)
from PyQt6.QtCore import Qt

from utils.exporters import Exporter
from utils import weapon_reports
from utils.report_preview import (
    REPORT_KIND_DATA_EXPORT,
    REPORT_KIND_INDIVIDUAL,
    REPORT_KIND_MULTI_COMPARE,
    REPORT_KIND_BY_CATEGORY,
    REPORT_KIND_FULL_SPECS,
)
from utils.ui_helpers import fit_dialog_to_screen, make_scroll_content


class ExportDialog(QDialog):
    """Export raw data or generate rich weapon reports (DOCX/PDF)."""

    REPORT_DATA = REPORT_KIND_DATA_EXPORT
    REPORT_INDIVIDUAL = REPORT_KIND_INDIVIDUAL
    REPORT_MULTI = REPORT_KIND_MULTI_COMPARE
    REPORT_BY_CATEGORY = REPORT_KIND_BY_CATEGORY
    REPORT_FULL_SPECS = REPORT_KIND_FULL_SPECS

    def __init__(self, parent=None, db_manager=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("Export & reports")

        outer = QVBoxLayout(self)
        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()

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

        self.include_map_cb = QCheckBox(
            "Include range & effects map diagram (individual report only)"
        )
        self.include_map_cb.setChecked(True)

        self.format_combo = QComboBox()

        self.hint_lbl = QLabel()
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setStyleSheet("color: #aaa;")

        self.weapon_list = QListWidget()
        self.weapon_list.setMinimumHeight(220)
        self.weapon_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.count_lbl = QLabel("Records: loading...")

        form.addRow("Output type", self.report_combo)
        form.addRow("", self.include_map_cb)
        form.addRow("File format", self.format_combo)
        form.addRow("", self.hint_lbl)
        form.addRow("Weapons (select as needed)", self.weapon_list)
        form.addRow("Dataset", self.count_lbl)
        layout.addLayout(form)

        scroll = make_scroll_content(content, self)
        outer.addWidget(scroll, 1)

        export_btn = QPushButton("Export / generate")
        export_btn.clicked.connect(self._do_export)
        outer.addWidget(export_btn)
        fit_dialog_to_screen(self, width=540, height=640)

        self._all_weapons: list = []
        self._reload_weapons()
        total = self.db_manager.get_weapon_count()
        self.count_lbl.setText(f"Total weapons in database: {total}")
        self._on_report_type_changed()

    def _reload_weapons(self):
        self._all_weapons = self.db_manager.get_weapons_paginated(0, 100_000, filters={})
        self.weapon_list.clear()
        for w in self._all_weapons:
            label = f"{w.get('weapon_name', '?')}  —  {w.get('model', '-')}"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, w)
            self.weapon_list.addItem(it)

    def _current_report_kind(self) -> str:
        return self.report_combo.currentData()

    def _on_report_type_changed(self):
        kind = self._current_report_kind()
        self.include_map_cb.setVisible(kind == self.REPORT_INDIVIDUAL)
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        if kind == self.REPORT_DATA:
            self.format_combo.addItems(["xlsx", "csv", "json", "docx", "pdf"])
            self.weapon_list.setEnabled(False)
            self.hint_lbl.setText(
                "Exports the current dataset as a flat table (all weapons, all columns)."
            )
        else:
            self.format_combo.addItems(["docx", "pdf"])
            self.weapon_list.setEnabled(True)
            if kind == self.REPORT_INDIVIDUAL:
                self.weapon_list.setSelectionMode(
                    QAbstractItemView.SelectionMode.SingleSelection
                )
                self.hint_lbl.setText(
                    "Select exactly one weapon. Pictures are embedded; optionally add a "
                    "schematic range / effects map from origin and range (km)."
                )
            elif kind == self.REPORT_MULTI:
                self.weapon_list.setSelectionMode(
                    QAbstractItemView.SelectionMode.ExtendedSelection
                )
                self.hint_lbl.setText(
                    "Select two or more weapons to compare. Each section includes photos and key stats."
                )
            elif kind == self.REPORT_BY_CATEGORY:
                self.weapon_list.setSelectionMode(
                    QAbstractItemView.SelectionMode.NoSelection
                )
                self.weapon_list.setEnabled(False)
                self.hint_lbl.setText(
                    "All weapons are grouped by category in a grid-style list (no selection needed)."
                )
            else:
                self.weapon_list.setSelectionMode(
                    QAbstractItemView.SelectionMode.NoSelection
                )
                self.weapon_list.setEnabled(False)
                self.hint_lbl.setText(
                    "Every weapon is listed with full specifications and gallery images (catalog)."
                )
        self.format_combo.blockSignals(False)

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
        loaded = self.db_manager.get_weapon_by_id(int(wid), eager_load=True)
        if loaded:
            return loaded.to_dict(include_images=True, include_variants=True)
        return w

    def _do_export(self):
        kind = self._current_report_kind()
        fmt = self.format_combo.currentText()
        data = self._all_weapons
        if not data and kind != self.REPORT_DATA:
            QMessageBox.warning(self, "No Data", "There is no data to export.")
            return

        if kind == self.REPORT_DATA:
            if not data:
                QMessageBox.warning(self, "No Data", "There is no data to export.")
                return
            suggested = f"weapons_export.{fmt}"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save export file",
                str(Path.home() / suggested),
                f"{fmt.upper()} (*.{fmt})",
            )
            if not path:
                return
            exporter = Exporter(data)
            try:
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

        # Rich reports: reload full rows with images for selected / all
        if kind == self.REPORT_INDIVIDUAL:
            sel = self._selected_weapons()
            if len(sel) != 1:
                QMessageBox.warning(
                    self, "Selection",
                    "Please select exactly one weapon for an individual report.",
                )
                return
            weapon = self._ensure_full_weapon(sel[0])
            ext = "docx" if fmt == "docx" else "pdf"
            suggested = f"weapon_report_{weapon.get('id', 'x')}.{ext}"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / suggested),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                inc_map = self.include_map_cb.isChecked()
                if fmt == "docx":
                    weapon_reports.write_individual_weapon_docx(
                        weapon, path, include_map=inc_map
                    )
                else:
                    weapon_reports.write_individual_weapon_pdf(
                        weapon, path, include_map=inc_map
                    )
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return

        if kind == self.REPORT_MULTI:
            sel = self._selected_weapons()
            if len(sel) < 2:
                QMessageBox.warning(
                    self, "Selection",
                    "Select at least two weapons for a comparison report.",
                )
                return
            weapons = [self._ensure_full_weapon(w) for w in sel]
            ext = "docx" if fmt == "docx" else "pdf"
            suggested = f"weapon_comparison.{ext}"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / suggested),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                if fmt == "docx":
                    weapon_reports.write_multi_comparison_docx(weapons, path)
                else:
                    weapon_reports.write_multi_comparison_pdf(weapons, path)
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return

        if kind == self.REPORT_BY_CATEGORY:
            weapons = [self._ensure_full_weapon(w) for w in data]
            ext = "docx" if fmt == "docx" else "pdf"
            suggested = f"weapons_by_category.{ext}"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / suggested),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                if fmt == "docx":
                    weapon_reports.write_category_grid_docx(weapons, path)
                else:
                    weapon_reports.write_category_grid_pdf(weapons, path)
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return

        if kind == self.REPORT_FULL_SPECS:
            weapons = [self._ensure_full_weapon(w) for w in data]
            ext = "docx" if fmt == "docx" else "pdf"
            suggested = f"weapons_full_specs.{ext}"
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save report",
                str(Path.home() / suggested),
                f"{ext.upper()} (*.{ext})",
            )
            if not path:
                return
            try:
                if fmt == "docx":
                    weapon_reports.write_full_specs_docx(weapons, path)
                else:
                    weapon_reports.write_full_specs_catalog_pdf(weapons, path)
                QMessageBox.information(self, "Complete", f"Saved:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Report failed", str(exc))
            return
