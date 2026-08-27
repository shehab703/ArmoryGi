from __future__ import annotations

from datetime import datetime

import json
import re

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QGridLayout,
    QSizePolicy,
    QTabWidget,
)

from utils.ai_prompts import build_swot_draft_prompt
from utils.ai_service import (
    OllamaError,
    get_ollama_client,
    is_ai_enabled,
    parse_strict_json,
    model_is_available,
    AI_MODEL_KEY,
)


class SWOTAnalysisView(QWidget):
    weapon_selected = pyqtSignal(dict)
    swot_text_changed = pyqtSignal(dict)

    def __init__(self, db_manager, lang_manager=None, settings=None):
        super().__init__()
        self.db = db_manager
        self.lang_manager = lang_manager
        self.settings = settings
        self.weapon: dict | None = None
        self._weapons_cache: list[dict] = []
        self._ai_thread: QThread | None = None
        self._ai_stream_buffer = ""
        self._ai_stream_timer = QTimer(self)
        self._ai_stream_timer.setSingleShot(True)
        self._ai_stream_timer.timeout.connect(self._apply_streamed_swot_preview)
        self._build_ui()
        self._refresh_weapon_options()
        self._set_workflow_enabled(False)
        self.retranslate_ui()
        self._apply_directional_layout()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.title_lbl = QLabel("SWOT Analysis")
        self.title_lbl.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(self.title_lbl)

        self.status_lbl = QLabel("Status: select a weapon to start.")
        self.status_lbl.setStyleSheet("color:#d8c58f;")
        root.addWidget(self.status_lbl)

        top = QHBoxLayout()
        self.weapon_lbl = QLabel("No weapon selected")
        self.compare_combo = QComboBox()
        self.compare_combo.addItem("Compare with weapon...", "")
        self.compare_combo.setMinimumHeight(34)
        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setMinimumHeight(34)
        self.compare_btn.clicked.connect(self._compare_with_selected_weapon)
        top.addWidget(self.weapon_lbl, 2)
        top.addWidget(self.compare_combo, 2)
        top.addWidget(self.compare_btn, 0)
        root.addLayout(top)

        self.subtabs = QTabWidget()
        root.addWidget(self.subtabs, 1)

        self._build_overview_tab()
        self._build_editor_tab()
        self._build_scoring_tab()
        self._build_compare_tab()
        self._build_history_tab()
        self._bind_text_change_signals()

    def _build_overview_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.meta_group = QGroupBox("Analysis Context")
        meta_group = self.meta_group
        form = QFormLayout(meta_group)
        self.analyst_input = QLineEdit()
        self.analyst_input.setMinimumHeight(34)
        self.scenario_input = QLineEdit()
        self.scenario_input.setMinimumHeight(34)
        self.analyst_label = QLabel("Analyst")
        self.scenario_label = QLabel("Scenario / Theater")
        form.addRow(self.analyst_label, self.analyst_input)
        form.addRow(self.scenario_label, self.scenario_input)
        layout.addWidget(meta_group)

        self.map_context_lbl = QLabel("Map context: n/a")
        self.map_context_lbl.setWordWrap(True)
        self.map_context_lbl.setStyleSheet("color:#8bb6d8;")
        layout.addWidget(self.map_context_lbl)

        actions = QHBoxLayout()
        self.save_btn = QPushButton("Save Version")
        self.save_btn.setMinimumHeight(34)
        self.save_btn.clicked.connect(self._save_report)
        self.load_latest_btn = QPushButton("Load Latest")
        self.load_latest_btn.setMinimumHeight(34)
        self.load_latest_btn.clicked.connect(self._load_latest_report)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.load_latest_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        self.overview_tab_idx = self.subtabs.addTab(tab, "Overview")

    def _build_editor_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.strengths_edit = QTextEdit()
        self.weaknesses_edit = QTextEdit()
        self.opportunities_edit = QTextEdit()
        self.threats_edit = QTextEdit()
        self._set_editor_style(self.strengths_edit, "Strengths")
        self._set_editor_style(self.weaknesses_edit, "Weaknesses")
        self._set_editor_style(self.opportunities_edit, "Opportunities")
        self._set_editor_style(self.threats_edit, "Threats")
        self.lbl_strengths = QLabel("Strengths")
        self.lbl_weaknesses = QLabel("Weaknesses")
        self.lbl_opportunities = QLabel("Opportunities")
        self.lbl_threats = QLabel("Threats")
        grid.addWidget(self.lbl_strengths, 0, 0)
        grid.addWidget(self.lbl_weaknesses, 0, 1)
        grid.addWidget(self.strengths_edit, 1, 0)
        grid.addWidget(self.weaknesses_edit, 1, 1)
        grid.addWidget(self.lbl_opportunities, 2, 0)
        grid.addWidget(self.lbl_threats, 2, 1)
        grid.addWidget(self.opportunities_edit, 3, 0)
        grid.addWidget(self.threats_edit, 3, 1)
        layout.addLayout(grid, 1)

        self.recommendations_edit = QTextEdit()
        self.recommendations_edit.setPlaceholderText("Recommendations and mitigations...")
        self.recommendations_edit.setMinimumHeight(110)
        self.lbl_recommendations = QLabel("Recommendations")
        layout.addWidget(self.lbl_recommendations)
        layout.addWidget(self.recommendations_edit)

        controls = QHBoxLayout()
        self.auto_btn = QPushButton("AI-assisted Draft")
        self.auto_btn.setMinimumHeight(34)
        self.auto_btn.clicked.connect(self._generate_auto_draft)
        self.clear_btn = QPushButton("Clear Draft")
        self.clear_btn.setMinimumHeight(34)
        self.clear_btn.clicked.connect(lambda: self._clear_inputs(keep_meta=True))
        controls.addWidget(self.auto_btn)
        controls.addWidget(self.clear_btn)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.editor_tab_idx = self.subtabs.addTab(tab, "SWOT Editor")

    def _build_scoring_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        matrix = QGridLayout()
        matrix.setColumnMinimumWidth(0, 140)
        matrix.setColumnMinimumWidth(1, 96)
        matrix.setColumnMinimumWidth(2, 110)
        self.lbl_quadrant = QLabel("Quadrant")
        self.lbl_impact = QLabel("Impact")
        self.lbl_confidence = QLabel("Confidence")
        matrix.addWidget(self.lbl_quadrant, 0, 0)
        matrix.addWidget(self.lbl_impact, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.lbl_confidence, 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        self.s_impact = QSpinBox()
        self.s_conf = QSpinBox()
        self.w_impact = QSpinBox()
        self.w_conf = QSpinBox()
        self.o_impact = QSpinBox()
        self.o_conf = QSpinBox()
        self.t_impact = QSpinBox()
        self.t_conf = QSpinBox()
        for spin in (self.s_impact, self.w_impact, self.o_impact, self.t_impact):
            spin.setRange(1, 5)
            spin.setValue(3)
            spin.setFixedSize(70, 40)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.valueChanged.connect(self._refresh_score_preview)
        for spin in (self.s_conf, self.w_conf, self.o_conf, self.t_conf):
            spin.setRange(20, 100)
            spin.setSingleStep(5)
            spin.setValue(70)
            spin.setSuffix("%")
            spin.setFixedSize(84, 40)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.valueChanged.connect(self._refresh_score_preview)
        self.lbl_score_strengths = QLabel("Strengths")
        self.lbl_score_weaknesses = QLabel("Weaknesses")
        self.lbl_score_opportunities = QLabel("Opportunities")
        self.lbl_score_threats = QLabel("Threats")
        matrix.addWidget(self.lbl_score_strengths, 1, 0)
        matrix.addWidget(self.s_impact, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.s_conf, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.lbl_score_weaknesses, 2, 0)
        matrix.addWidget(self.w_impact, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.w_conf, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.lbl_score_opportunities, 3, 0)
        matrix.addWidget(self.o_impact, 3, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.o_conf, 3, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.lbl_score_threats, 4, 0)
        matrix.addWidget(self.t_impact, 4, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.addWidget(self.t_conf, 4, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(matrix)

        self.score_preview_lbl = QLabel("Live score preview: n/a")
        self.score_preview_lbl.setStyleSheet("color:#9ed39e;")
        self.score_preview_lbl.setWordWrap(True)
        layout.addWidget(self.score_preview_lbl)
        layout.addStretch(1)
        self.scoring_tab_idx = self.subtabs.addTab(tab, "Scoring")

    def _build_compare_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        grid = QGridLayout()
        grid.setColumnMinimumWidth(0, 130)
        grid.setColumnMinimumWidth(1, 340)
        grid.setColumnMinimumWidth(2, 340)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self.compare_header_current = QLabel("Current weapon")
        self.compare_header_target = QLabel("Comparison weapon")
        self.compare_header_current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.compare_header_target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.compare_header_current.setStyleSheet("font-weight:700;")
        self.compare_header_target.setStyleSheet("font-weight:700;")
        self.lbl_compare_quadrant = QLabel("Quadrant")
        grid.addWidget(self.lbl_compare_quadrant, 0, 0)
        grid.addWidget(self.compare_header_current, 0, 1)
        grid.addWidget(self.compare_header_target, 0, 2)
        self.compare_s_left = QTextEdit()
        self.compare_s_right = QTextEdit()
        self.compare_w_left = QTextEdit()
        self.compare_w_right = QTextEdit()
        self.compare_o_left = QTextEdit()
        self.compare_o_right = QTextEdit()
        self.compare_t_left = QTextEdit()
        self.compare_t_right = QTextEdit()
        for editor in (
            self.compare_s_left, self.compare_s_right, self.compare_w_left, self.compare_w_right,
            self.compare_o_left, self.compare_o_right, self.compare_t_left, self.compare_t_right
        ):
            editor.setReadOnly(True)
            editor.setMinimumHeight(90)
            editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl_compare_strengths = QLabel("Strengths")
        self.lbl_compare_weaknesses = QLabel("Weaknesses")
        self.lbl_compare_opportunities = QLabel("Opportunities")
        self.lbl_compare_threats = QLabel("Threats")
        grid.addWidget(self.lbl_compare_strengths, 1, 0)
        grid.addWidget(self.compare_s_left, 1, 1)
        grid.addWidget(self.compare_s_right, 1, 2)
        grid.addWidget(self.lbl_compare_weaknesses, 2, 0)
        grid.addWidget(self.compare_w_left, 2, 1)
        grid.addWidget(self.compare_w_right, 2, 2)
        grid.addWidget(self.lbl_compare_opportunities, 3, 0)
        grid.addWidget(self.compare_o_left, 3, 1)
        grid.addWidget(self.compare_o_right, 3, 2)
        grid.addWidget(self.lbl_compare_threats, 4, 0)
        grid.addWidget(self.compare_t_left, 4, 1)
        grid.addWidget(self.compare_t_right, 4, 2)
        layout.addLayout(grid, 1)
        self.compare_info_lbl = QLabel("Compare legend: green=shared, red=only current, blue=only comparison.")
        self.compare_info_lbl.setWordWrap(True)
        self.compare_info_lbl.setStyleSheet("color:#c8d69f;")
        layout.addWidget(self.compare_info_lbl)
        self.compare_tab_idx = self.subtabs.addTab(tab, "Compare")

    def _build_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self._load_from_history_item)
        self.trend_lbl = QLabel("Trend: n/a")
        self.trend_lbl.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.history_list, 2)
        row.addWidget(self.trend_lbl, 1)
        layout.addLayout(row, 1)
        self.history_tab_idx = self.subtabs.addTab(tab, "History")

    def _set_editor_style(self, editor: QTextEdit, placeholder: str):
        editor.setPlaceholderText(self._tr(f"One item per line: {placeholder}"))
        editor.setMinimumHeight(140)

    def _bind_text_change_signals(self):
        for edit in (self.strengths_edit, self.weaknesses_edit, self.opportunities_edit, self.threats_edit):
            edit.textChanged.connect(self._refresh_score_preview)
            edit.textChanged.connect(self._emit_swot_text_changed)
        self.recommendations_edit.textChanged.connect(self._emit_swot_text_changed)
        self.analyst_input.textChanged.connect(self._emit_swot_text_changed)
        self.scenario_input.textChanged.connect(self._emit_swot_text_changed)

    def _emit_swot_text_changed(self):
        if not self.weapon or not self.weapon.get("id"):
            return
        payload = {
            "weapon_id": int(self.weapon.get("id") or 0),
            "analyst": self.analyst_input.text().strip(),
            "scenario": self.scenario_input.text().strip(),
            "strengths": self._split_lines(self.strengths_edit),
            "weaknesses": self._split_lines(self.weaknesses_edit),
            "opportunities": self._split_lines(self.opportunities_edit),
            "threats": self._split_lines(self.threats_edit),
            "recommendations": self.recommendations_edit.toPlainText().strip(),
        }
        self.swot_text_changed.emit(payload)

    def _set_workflow_enabled(self, enabled: bool):
        for widget in (
            self.compare_combo, self.compare_btn, self.analyst_input, self.scenario_input,
            self.strengths_edit, self.weaknesses_edit, self.opportunities_edit, self.threats_edit,
            self.recommendations_edit, self.s_impact, self.s_conf, self.w_impact, self.w_conf,
            self.o_impact, self.o_conf, self.t_impact, self.t_conf, self.auto_btn, self.clear_btn,
            self.save_btn, self.load_latest_btn, self.history_list
        ):
            widget.setEnabled(enabled)

    def _tr(self, text: str) -> str:
        return self.lang_manager.tr(text) if self.lang_manager else text

    def _lang_code(self) -> str:
        if self.lang_manager and getattr(self.lang_manager, "current_code", None):
            return str(self.lang_manager.current_code).strip().lower() or "en"
        return "en"

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        self.retranslate_ui()
        self._apply_directional_layout()

    def retranslate_ui(self):
        self.title_lbl.setText(self._tr("SWOT Analysis"))
        if not self.weapon:
            self.status_lbl.setText(self._tr("Status: select a weapon to start."))
            self.weapon_lbl.setText(self._tr("No weapon selected"))
        self.compare_combo.setItemText(0, self._tr("Compare with weapon..."))
        self.compare_btn.setText(self._tr("Compare"))
        self.save_btn.setText(self._tr("Save Version"))
        self.load_latest_btn.setText(self._tr("Load Latest"))
        self.auto_btn.setText(self._tr("AI-assisted Draft"))
        self.clear_btn.setText(self._tr("Clear Draft"))
        self.meta_group.setTitle(self._tr("Analysis Context"))
        self.analyst_label.setText(self._tr("Analyst"))
        self.scenario_label.setText(self._tr("Scenario / Theater"))
        self.analyst_input.setPlaceholderText(self._tr("Analyst"))
        self.scenario_input.setPlaceholderText(self._tr("Scenario / theater"))
        self.lbl_strengths.setText(self._tr("Strengths"))
        self.lbl_weaknesses.setText(self._tr("Weaknesses"))
        self.lbl_opportunities.setText(self._tr("Opportunities"))
        self.lbl_threats.setText(self._tr("Threats"))
        self.lbl_recommendations.setText(self._tr("Recommendations"))
        self.recommendations_edit.setPlaceholderText(self._tr("Recommendations and mitigations..."))
        self.strengths_edit.setPlaceholderText(self._tr("One item per line: Strengths"))
        self.weaknesses_edit.setPlaceholderText(self._tr("One item per line: Weaknesses"))
        self.opportunities_edit.setPlaceholderText(self._tr("One item per line: Opportunities"))
        self.threats_edit.setPlaceholderText(self._tr("One item per line: Threats"))
        self.lbl_quadrant.setText(self._tr("Quadrant"))
        self.lbl_impact.setText(self._tr("Impact"))
        self.lbl_confidence.setText(self._tr("Confidence"))
        self.lbl_score_strengths.setText(self._tr("Strengths"))
        self.lbl_score_weaknesses.setText(self._tr("Weaknesses"))
        self.lbl_score_opportunities.setText(self._tr("Opportunities"))
        self.lbl_score_threats.setText(self._tr("Threats"))
        self.lbl_compare_quadrant.setText(self._tr("Quadrant"))
        self.lbl_compare_strengths.setText(self._tr("Strengths"))
        self.lbl_compare_weaknesses.setText(self._tr("Weaknesses"))
        self.lbl_compare_opportunities.setText(self._tr("Opportunities"))
        self.lbl_compare_threats.setText(self._tr("Threats"))
        self.compare_header_current.setText(self._tr("Current weapon") if not self.weapon else self.compare_header_current.text())
        self.compare_header_target.setText(self._tr("Comparison weapon") if not self.weapon else self.compare_header_target.text())
        self.compare_info_lbl.setText(self._tr("Compare legend: green=shared, red=only current, blue=only comparison."))
        self.subtabs.setTabText(self.overview_tab_idx, self._tr("Overview"))
        self.subtabs.setTabText(self.editor_tab_idx, self._tr("SWOT Editor"))
        self.subtabs.setTabText(self.scoring_tab_idx, self._tr("Scoring"))
        self.subtabs.setTabText(self.compare_tab_idx, self._tr("Compare"))
        self.subtabs.setTabText(self.history_tab_idx, self._tr("History"))
        self._refresh_weapon_options(selected_weapon_id=int(self.weapon.get("id", -1)) if self.weapon else None)

    def _apply_directional_layout(self):
        is_ar = bool(self.lang_manager and hasattr(self.lang_manager, "is_arabic") and self.lang_manager.is_arabic())
        direction = Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight
        self.setLayoutDirection(direction)
        self.subtabs.setLayoutDirection(direction)
        for widget in (
            self.analyst_input,
            self.scenario_input,
            self.recommendations_edit,
            self.strengths_edit,
            self.weaknesses_edit,
            self.opportunities_edit,
            self.threats_edit,
        ):
            widget.setLayoutDirection(direction)
            widget.setAlignment(Qt.AlignmentFlag.AlignRight if is_ar else Qt.AlignmentFlag.AlignLeft)
        align = Qt.AlignmentFlag.AlignRight if is_ar else Qt.AlignmentFlag.AlignLeft
        for label in (
            self.title_lbl,
            self.status_lbl,
            self.weapon_lbl,
            self.map_context_lbl,
            self.score_preview_lbl,
            self.trend_lbl,
            self.compare_info_lbl,
            self.analyst_label,
            self.scenario_label,
            self.lbl_strengths,
            self.lbl_weaknesses,
            self.lbl_opportunities,
            self.lbl_threats,
            self.lbl_recommendations,
            self.lbl_quadrant,
            self.lbl_impact,
            self.lbl_confidence,
            self.lbl_score_strengths,
            self.lbl_score_weaknesses,
            self.lbl_score_opportunities,
            self.lbl_score_threats,
            self.lbl_compare_quadrant,
            self.lbl_compare_strengths,
            self.lbl_compare_weaknesses,
            self.lbl_compare_opportunities,
            self.lbl_compare_threats,
        ):
            label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)

    def load_weapon(self, weapon: dict):
        if not weapon:
            return
        self.weapon = weapon
        self._set_workflow_enabled(True)
        self.weapon_lbl.setText(f"{weapon.get('weapon_name', 'Unknown')} ({weapon.get('model', '-')})")
        self.status_lbl.setText(self._tr("Status: weapon selected. Fill SWOT, then save and compare."))
        self._refresh_weapon_options(selected_weapon_id=int(weapon.get("id", -1)))
        self._apply_map_context_hints()
        self._load_latest_report()

    def _refresh_weapon_options(self, selected_weapon_id: int | None = None):
        current = self.compare_combo.currentData()
        self.compare_combo.blockSignals(True)
        try:
            self.compare_combo.clear()
            self.compare_combo.addItem(self._tr("Compare with weapon..."), "")
            self._weapons_cache = self.db.get_weapons_paginated(0, 1000, filters={})
            for row in self._weapons_cache:
                wid = int(row.get("id", -1))
                if selected_weapon_id and wid == selected_weapon_id:
                    continue
                self.compare_combo.addItem(f"{row.get('weapon_name', 'Unknown')} ({row.get('model', '-')})", wid)
            idx = self.compare_combo.findData(current)
            if idx >= 0:
                self.compare_combo.setCurrentIndex(idx)
        finally:
            self.compare_combo.blockSignals(False)

    def _split_lines(self, edit: QTextEdit) -> list[str]:
        return [ln.strip("-* \t") for ln in edit.toPlainText().splitlines() if ln.strip()]

    def _set_lines(self, edit: QTextEdit, values: list[str]):
        edit.setPlainText("\n".join([str(v).strip() for v in values if str(v).strip()]))

    def _score_summary(self) -> dict:
        s = len(self._split_lines(self.strengths_edit))
        w = len(self._split_lines(self.weaknesses_edit))
        o = len(self._split_lines(self.opportunities_edit))
        t = len(self._split_lines(self.threats_edit))
        s_w = s * self.s_impact.value() * (self.s_conf.value() / 100.0)
        w_w = w * self.w_impact.value() * (self.w_conf.value() / 100.0)
        o_w = o * self.o_impact.value() * (self.o_conf.value() / 100.0)
        t_w = t * self.t_impact.value() * (self.t_conf.value() / 100.0)
        return {
            "strengths": s,
            "weaknesses": w,
            "opportunities": o,
            "threats": t,
            "net_score": (s + o) - (w + t),
            "weighted_net_score": round((s_w + o_w) - (w_w + t_w), 2),
            "weights": {
                "s_impact": self.s_impact.value(), "s_conf": self.s_conf.value(),
                "w_impact": self.w_impact.value(), "w_conf": self.w_conf.value(),
                "o_impact": self.o_impact.value(), "o_conf": self.o_conf.value(),
                "t_impact": self.t_impact.value(), "t_conf": self.t_conf.value(),
            },
        }

    def _refresh_score_preview(self):
        summary = self._score_summary()
        self.score_preview_lbl.setText(
            f"{self._tr('Live score preview')}: "
            f"{self._tr('Raw net')} {summary.get('net_score', 0):+}, "
            f"{self._tr('Weighted net')} {float(summary.get('weighted_net_score', 0.0)):+.2f}."
        )

    def _save_report(self):
        if not self.weapon or not self.weapon.get("id"):
            QMessageBox.warning(self, self._tr("SWOT"), self._tr("Please select a weapon first."))
            return
        payload = {
            "analyst": self.analyst_input.text().strip(),
            "scenario": self.scenario_input.text().strip(),
            "strengths": self._split_lines(self.strengths_edit),
            "weaknesses": self._split_lines(self.weaknesses_edit),
            "opportunities": self._split_lines(self.opportunities_edit),
            "threats": self._split_lines(self.threats_edit),
            "recommendations": self.recommendations_edit.toPlainText().strip(),
            "score_summary": self._score_summary(),
        }
        saved = self.db.save_weapon_swot_report(int(self.weapon["id"]), payload)
        if not saved:
            QMessageBox.critical(self, self._tr("SWOT"), self._tr("Failed to save SWOT report."))
            return
        self._load_history()
        self.status_lbl.setText(self._tr("Status: SWOT version saved."))
        QMessageBox.information(self, self._tr("SWOT"), self._tr("Saved SWOT version."))

    def _load_latest_report(self):
        if not self.weapon or not self.weapon.get("id"):
            return
        report = self.db.get_latest_weapon_swot_report(int(self.weapon["id"]))
        if report:
            self._apply_report(report)
            self.status_lbl.setText(self._tr("Status: latest SWOT loaded."))
        else:
            self._clear_inputs(keep_meta=False)
            if self.db and self.weapon and self.weapon.get("id"):
                cached = self.db.get_weapon_ai_cache(
                    int(self.weapon["id"]),
                    "swot_ai_draft",
                    self._lang_code(),
                )
                if cached:
                    payload = cached.get("content_json") or {}
                    if isinstance(payload, dict):
                        self._apply_swot_fields(payload, only_non_empty=False)
            self.status_lbl.setText(self._tr("Status: no saved SWOT yet."))
        self._load_history()
        self._clear_compare_board()

    def _load_history(self):
        self.history_list.clear()
        if not self.weapon or not self.weapon.get("id"):
            self.trend_lbl.setText(self._tr("Trend: n/a"))
            return
        reports = self.db.get_weapon_swot_reports(int(self.weapon["id"]), limit=30)
        for rep in reports:
            score_data = rep.get("score_summary") or {}
            label = f"{rep.get('created_at') or ''} | net={score_data.get('net_score', 0)} | w={float(score_data.get('weighted_net_score', 0.0)):+.2f}"
            item = QListWidgetItem(label)
            item.setData(256, rep)
            self.history_list.addItem(item)
        self._update_trend_label(reports)

    def _update_trend_label(self, reports: list[dict]):
        if len(reports) < 2:
            self.trend_lbl.setText(self._tr("Trend: need at least 2 saved versions."))
            return
        newest = reports[0].get("score_summary") or {}
        oldest = reports[-1].get("score_summary") or {}
        delta = int(newest.get("net_score", 0)) - int(oldest.get("net_score", 0))
        delta_w = float(newest.get("weighted_net_score", 0.0)) - float(oldest.get("weighted_net_score", 0.0))
        self.trend_lbl.setText(
            f"{self._tr('Trend')}: {self._tr('Raw')} {delta:+}, {self._tr('Weighted')} {delta_w:+.2f} "
            f"{self._tr('across')} {len(reports)} {self._tr('versions')}."
        )

    def _apply_report(self, report: dict):
        self.analyst_input.setText(str(report.get("analyst", "")))
        self.scenario_input.setText(str(report.get("scenario", "")))
        self._set_lines(self.strengths_edit, report.get("strengths") or [])
        self._set_lines(self.weaknesses_edit, report.get("weaknesses") or [])
        self._set_lines(self.opportunities_edit, report.get("opportunities") or [])
        self._set_lines(self.threats_edit, report.get("threats") or [])
        self.recommendations_edit.setPlainText(str(report.get("recommendations", "")))
        weights = (report.get("score_summary") or {}).get("weights") or {}
        self.s_impact.setValue(int(weights.get("s_impact", 3)))
        self.s_conf.setValue(int(weights.get("s_conf", 70)))
        self.w_impact.setValue(int(weights.get("w_impact", 3)))
        self.w_conf.setValue(int(weights.get("w_conf", 70)))
        self.o_impact.setValue(int(weights.get("o_impact", 3)))
        self.o_conf.setValue(int(weights.get("o_conf", 70)))
        self.t_impact.setValue(int(weights.get("t_impact", 3)))
        self.t_conf.setValue(int(weights.get("t_conf", 70)))
        self._refresh_score_preview()

    def _clear_inputs(self, keep_meta: bool = True):
        if not keep_meta:
            self.analyst_input.clear()
            self.scenario_input.clear()
        self.strengths_edit.clear()
        self.weaknesses_edit.clear()
        self.opportunities_edit.clear()
        self.threats_edit.clear()
        self.recommendations_edit.clear()
        self._refresh_score_preview()

    def _clear_compare_board(self):
        self.compare_header_current.setText(self._tr("Current weapon"))
        self.compare_header_target.setText(self._tr("Comparison weapon"))
        for editor in (
            self.compare_s_left, self.compare_s_right, self.compare_w_left, self.compare_w_right,
            self.compare_o_left, self.compare_o_right, self.compare_t_left, self.compare_t_right
        ):
            editor.clear()

    def _render_diff_html(self, items: list[str], other_items: list[str], left_side: bool) -> str:
        own = [x.strip() for x in items if str(x).strip()]
        other_set = {x.strip().lower() for x in other_items if str(x).strip()}
        rows = []
        for row in own:
            if row.strip().lower() in other_set:
                bg = "#1f3b2d"
            else:
                bg = "#3a2525" if left_side else "#24354a"
            rows.append(f"<div style='margin:2px 0;padding:4px 6px;background:{bg};border-radius:4px;'>- {row}</div>")
        if not rows:
            rows.append("<div style='opacity:0.7;'>No items</div>")
        return "<html><body style='font-family:Segoe UI;font-size:12px;'>" + "".join(rows) + "</body></html>"

    def _load_from_history_item(self, item: QListWidgetItem):
        report = item.data(256) or {}
        if report:
            self._apply_report(report)
            self.status_lbl.setText(self._tr("Status: historical version loaded."))

    def _generate_auto_draft(self):
        if not self.weapon:
            QMessageBox.warning(self, self._tr("SWOT"), self._tr("Please select a weapon first."))
            return
        if self.settings and is_ai_enabled(self.settings):
            self._generate_auto_draft_via_ollama()
            return
        self._generate_offline_draft()

    def _generate_offline_draft(self):
        """Heuristic SWOT from the defender / targeted opponent viewpoint (offline, no AI)."""
        def fmt(template: str, **kwargs) -> str:
            return self._tr(template).format(**kwargs)
        w = self.weapon
        strengths: list[str] = []
        weaknesses: list[str] = []
        opportunities: list[str] = []
        threats: list[str] = []
        range_km = float(w.get("range_km") or 0.0)
        speed = float(w.get("speed_mach") or 0.0)
        warhead = float(w.get("warhead_weight_kg") or 0.0)
        status = str(w.get("status") or "").lower()
        intro_year = int(w.get("intro_year") or 0)
        guidance = str(w.get("guidance") or "Unknown")
        platform = str(w.get("platform") or "N/A")
        category = str(w.get("category") or "").lower()

        # Keep bullets tightly tied to weapon spec fields available in `self.weapon`;
        # offline mode is intentionally conservative and conditional.
        strengths.append(fmt("Defense can exploit the weapon's range_km ({rk} km) via layered detection and standoff intercept planning.", rk=f"{range_km:.0f}"))
        weaknesses.append(fmt("If the defender lacks coverage for the weapon's speed_mach ({sp} Mach), reaction latency becomes a gap.", sp=f"{speed:.1f}" if speed else "unknown"))
        opportunities.append(fmt("Guidance ({guidance}) suggests specific EW/decoy counter-moves; rehearse the exact EW lanes implied by guidance.", guidance=guidance))
        threats.append(fmt("Weapon guidance ({guidance}) can pressure the defender's EMCON/EW if not planned for.", guidance=guidance))
        weaknesses.append(fmt("Warhead consequences depend on warhead_weight_kg ({wh} kg); insufficient hardening/dispersal is a vulnerability.", wh=f"{warhead:.0f}" if warhead else "unknown"))

        if range_km >= 300:
            threats.append(fmt("Stand-off reach (~{rk} km) holds defender depth and repositioning timelines at risk.", rk=f"{range_km:.0f}"))
            weaknesses.append(self._tr("Compressed warning/engagement timelines if ISR gaps exist against distant launches."))
            opportunities.append(self._tr("Passive sensing, dispersion, deception, and counter-fire on launch architecture can blunt long-range raids."))
        elif range_km > 0:
            threats.append(fmt("Engagement footprint (~{rk} km) constrains defender movement and bastion layouts.", rk=f"{range_km:.0f}"))

        if speed >= 2.0:
            threats.append(fmt("High-speed kinematics (~{sp} Mach) shorten defender intercept windows.", sp=f"{speed:.1f}"))
            opportunities.append(self._tr("Layered shooters, cueing relays, and pre-briefed fire baskets can reclaim engagement time."))
        elif speed > 0:
            threats.append(fmt("Threat speed (~{sp} Mach) still shapes defender geometry and interceptor selection.", sp=f"{speed:.1f}"))

        if warhead >= 250:
            threats.append(fmt("Heavy warhead mass (~{wh} kg) raises consequences of leakers against defender assets.", wh=f"{warhead:.0f}"))
        elif warhead > 0:
            threats.append(fmt("Even moderate warheads (~{wh} kg) demand hardening or dispersal for defended assets.", wh=f"{warhead:.0f}"))

        if status in {"active", "operational", "in service", "operative"}:
            threats.append(self._tr("Operational adversary inventories imply repeatable, exercised threat against the defender."))
        elif status:
            weaknesses.append(fmt("Declared status '{status}' may reduce near-term readiness—monitor reactivation timelines.", status=status))

        if intro_year and intro_year < datetime.utcnow().year - 25:
            opportunities.append(self._tr("Older seeker/front-end generations may yield exploitable EW and signature gaps for today's defender toolkit."))

        if "cruise" in category:
            weaknesses.append(self._tr("Low-altitude cruise routing stresses radar horizons and mutual support for the defender."))
            strengths.append(self._tr("Integrated air picture with low-level gap-fill sensors is a doctrinal strength when funded."))
            opportunities.append(self._tr("Barrier CAP, SAM belts on approach axes, and shoot-look-shoot doctrines counter cruise threats."))

        if "anti-tank" in category or "atgm" in category:
            threats.append(self._tr("Top-attack/heavy ATGW profiles endanger defended armor concentrations if LOS is conceded."))
            strengths.append(self._tr("Terrain masking, concealment discipline, overwatch UAVs, and quick smoke can favor the defender."))
            opportunities.append(self._tr("Active protection, hard-kill interceptors at short range, and dismounted overwatch degrade ATGM lethality."))

        if "air-to-air" in category or "aam" in category:
            threats.append(self._tr("Contestable airspace and long burn AAMs pressure defender fighters and AEW arcs."))
            opportunities.append(self._tr("Electronic attack, kinematic defeats, staggered shooters, and chaff/expendables counter AAM kinematics."))

        if "surface" in category:
            threats.append(self._tr("Sea/littoral shooters may deny maritime maneuver if coastal ISR is asymmetric."))

        weaknesses.append(self._tr("Doctrine and readiness drift are defender weaknesses unrelated to specs—scenario dependent."))

        self._set_lines(self.strengths_edit, self._coerce_numbered_list(strengths[:3]))
        self._set_lines(self.weaknesses_edit, self._coerce_numbered_list(weaknesses[:3]))
        self._set_lines(self.opportunities_edit, self._coerce_numbered_list(opportunities[:3]))
        self._set_lines(self.threats_edit, self._coerce_numbered_list(threats[:3]))
        rec_chunks = [
            self._tr(
                "Classify adversary seeker or guidance mode implied by stored fields and rehearse EW, decoys, "
                "and emissions control tailored to that class."
            ),
            self._tr(
                "Tighten layered detection-to-engagement handoffs—no single sensor or shooter may carry the intercept alone."
            ),
            self._tr(
                "Rehearse passive cueing and dispersal timelines so salvos cannot collapse defender depth in one strike."
            ),
            self._tr(
                "Table high-value defended assets vs. credible leaker scenarios and allocate hardening or relocation first."
            ),
            self._tr(
                "Exercise logistics and reload under repeated fires; stale magazines nullify technically sound defenses."
            ),
        ]
        self.recommendations_edit.setPlainText("\n".join(self._coerce_numbered_list(rec_chunks[:3])))
        self.status_lbl.setText(self._tr("Status: AI-assisted draft generated.") + self._tr(" (offline)"))
        self._refresh_score_preview()

    class _AiWorker(QObject):
        progress = pyqtSignal(str)
        finished = pyqtSignal(dict)
        failed = pyqtSignal(str)

        def __init__(self, settings, weapon: dict, is_ar: bool, analyst: str, scenario: str):
            super().__init__()
            self._settings = settings
            self._weapon = weapon
            self._is_ar = is_ar
            self._analyst = analyst
            self._scenario = scenario

        @pyqtSlot()
        def run(self):
            try:
                client = get_ollama_client(self._settings)
                system, user = build_swot_draft_prompt(
                    weapon=self._weapon,
                    is_ar=self._is_ar,
                    analyst=self._analyst,
                    scenario=self._scenario,
                )
                buf = []
                for chunk in client.chat_stream(system=system, user=user):
                    if chunk:
                        buf.append(str(chunk))
                        self.progress.emit("".join(buf))
                out = "".join(buf).strip()
                obj = SWOTAnalysisView._parse_swot_ai_output(out)
                if not obj:
                    # Fallback for non-stream-compatible backends.
                    out = client.chat(system=system, user=user)
                    obj = SWOTAnalysisView._parse_swot_ai_output(out)
                if not obj:
                    raise OllamaError("Model did not return usable SWOT output.")
                self.finished.emit(obj)
            except Exception as e:
                self.failed.emit(str(e))

    @staticmethod
    def _strip_ai_swot_line_prefix(line: str) -> str:
        """Trim leading hyphen/bullet only (keep numbering for downstream normalization)."""
        return re.sub(r"^[-*•●◦○\u2022]\s*", "", str(line).strip()).strip()

    @staticmethod
    def _strip_leading_swot_marker(s: str) -> str:
        """Remove bullet and any existing numeric ordinal so caller can assign fresh 1..n."""
        t = SWOTAnalysisView._strip_ai_swot_line_prefix(s)
        t = re.sub(r"^[(]?\s*[\d\u0660-\u0669\u06F0-\u06F9]{1,2}\s*[).、]\s*", "", t).strip()
        return t

    @classmethod
    def _coerce_numbered_list(cls, items: list[str]) -> list[str]:
        out: list[str] = []
        n = 1
        for raw in items:
            body = cls._strip_leading_swot_marker(raw)
            if not body:
                continue
            out.append(f"{n}. {body}")
            n += 1
        return out

    @staticmethod
    def _parse_swot_ai_output(text: str) -> dict:
        s = (text or "").strip()
        if not s:
            return {}
        obj = parse_strict_json(s)
        if obj:
            return obj
        section_map = {
            "[strengths]": "strengths",
            "[weaknesses]": "weaknesses",
            "[opportunities]": "opportunities",
            "[threats]": "threats",
            "[recommendations]": "recommendations",
        }
        # Arabic UI / model-variation headers (no brackets).
        arabic_headers = {
            "نقاط القوة": "strengths",
            "[نقاط القوة]": "strengths",
            "نقاط الضعف": "weaknesses",
            "[نقاط الضعف]": "weaknesses",
            "الفرص": "opportunities",
            "[الفرص]": "opportunities",
            "التهديدات": "threats",
            "[التهديدات]": "threats",
            "التوصيات": "recommendations",
            "[التوصيات]": "recommendations",
        }
        out = {"strengths": [], "weaknesses": [], "opportunities": [], "threats": [], "recommendations": ""}
        current = None
        rec_lines: list[str] = []
        for raw in s.splitlines():
            ln = raw.strip()
            if not ln:
                continue
            low_line = ln.lower()
            key = arabic_headers.get(ln) or section_map.get(low_line)
            if key is None and ln.startswith("[") and ln.endswith("]"):
                inner = ln[1:-1].strip().lower()
                key = section_map.get("[" + inner + "]")
            if key:
                current = key
                continue
            if current is None:
                continue
            item = SWOTAnalysisView._strip_ai_swot_line_prefix(ln)
            if not item:
                continue
            if current == "recommendations":
                rec_lines.append(item)
            else:
                out[current].append(item)
        out["recommendations"] = "\n".join(rec_lines).strip()
        has_content = any(out[k] for k in ("strengths", "weaknesses", "opportunities", "threats")) or bool(out["recommendations"])
        return out if has_content else {}

    def _apply_swot_fields(self, obj: dict, *, only_non_empty: bool = True):
        strengths = [str(x).strip() for x in (obj.get("strengths") or []) if str(x).strip()]
        weaknesses = [str(x).strip() for x in (obj.get("weaknesses") or []) if str(x).strip()]
        opportunities = [str(x).strip() for x in (obj.get("opportunities") or []) if str(x).strip()]
        threats = [str(x).strip() for x in (obj.get("threats") or []) if str(x).strip()]
        recommendations = str(obj.get("recommendations") or "").strip()

        if strengths or not only_non_empty:
            self.strengths_edit.blockSignals(True)
            self._set_lines(self.strengths_edit, self._coerce_numbered_list(strengths))
            self.strengths_edit.blockSignals(False)
        if weaknesses or not only_non_empty:
            self.weaknesses_edit.blockSignals(True)
            self._set_lines(self.weaknesses_edit, self._coerce_numbered_list(weaknesses))
            self.weaknesses_edit.blockSignals(False)
        if opportunities or not only_non_empty:
            self.opportunities_edit.blockSignals(True)
            self._set_lines(self.opportunities_edit, self._coerce_numbered_list(opportunities))
            self.opportunities_edit.blockSignals(False)
        if threats or not only_non_empty:
            self.threats_edit.blockSignals(True)
            self._set_lines(self.threats_edit, self._coerce_numbered_list(threats))
            self.threats_edit.blockSignals(False)
        if recommendations or not only_non_empty:
            self.recommendations_edit.blockSignals(True)
            rec_lines = [ln for ln in recommendations.splitlines() if str(ln).strip()]
            self.recommendations_edit.setPlainText("\n".join(self._coerce_numbered_list(rec_lines)))
            self.recommendations_edit.blockSignals(False)
        self._refresh_score_preview()

    def _apply_streamed_swot_preview(self):
        parsed = self._parse_swot_ai_output(self._ai_stream_buffer)
        if parsed:
            self._apply_swot_fields(parsed, only_non_empty=True)

    def _generate_auto_draft_via_ollama(self):
        if not self.settings or not self.weapon:
            return
        if self._ai_thread is not None:
            return
        ok, msg = model_is_available(self.settings)
        if not ok and msg:
            QMessageBox.warning(self, self._tr("SWOT"), msg)
            # still allow attempt (maybe remote model/host), but give user signal.
        is_ar = bool(self.lang_manager and hasattr(self.lang_manager, "is_arabic") and self.lang_manager.is_arabic())
        analyst = self.analyst_input.text().strip()
        scenario = self.scenario_input.text().strip()
        model_name = str(self.settings.value(AI_MODEL_KEY, "llama3.1", str) or "").strip() or "llama3.1"

        self.status_lbl.setText(self._tr("Status: generating AI draft…") + f" ({model_name})")
        self.auto_btn.setEnabled(False)
        self._ai_stream_buffer = ""
        self._ai_stream_timer.stop()

        thread = QThread(self)
        worker = self._AiWorker(self.settings, dict(self.weapon), is_ar, analyst, scenario)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _cleanup():
            try:
                thread.quit()
                thread.wait(1500)
            except Exception:
                pass
            self._ai_thread = None
            self.auto_btn.setEnabled(True)
            worker.deleteLater()
            thread.deleteLater()

        def _apply(obj: dict):
            try:
                self._apply_swot_fields(obj, only_non_empty=False)
                if self.db and self.weapon and self.weapon.get("id"):
                    self.db.save_weapon_ai_cache(
                        int(self.weapon["id"]),
                        "swot_ai_draft",
                        self._lang_code(),
                        content_text=json.dumps(obj or {}, ensure_ascii=False),
                        content_json=obj if isinstance(obj, dict) else {},
                    )
                self.status_lbl.setText(self._tr("Status: AI-assisted draft generated.") + f" ({model_name})")
            finally:
                _cleanup()

        def _progress(text: str):
            self._ai_stream_buffer = text or ""
            self._ai_stream_timer.start(120)
            self.status_lbl.setText(self._tr("Status: generating AI draft…") + f" ({model_name})")

        def _fail(msg: str):
            try:
                # Make timeout/host issues actionable for the user.
                base_url = str(self.settings.value("ai/ollama_base_url", "http://localhost:11434", str) or "").strip()
                timeout_s = str(self.settings.value("ai/ollama_timeout_s", 180))
                QMessageBox.warning(
                    self,
                    self._tr("SWOT"),
                    self._tr("AI draft failed. Falling back to offline draft.")
                    + "\n\n"
                    + f"Ollama: {base_url}\nModel: {model_name}\nTimeout: {timeout_s}s\n\n"
                    + str(msg),
                )
                # fallback to current heuristic
                self._generate_offline_draft()
            finally:
                _cleanup()

        worker.progress.connect(_progress)
        worker.finished.connect(_apply)
        worker.failed.connect(_fail)
        self._ai_thread = thread
        thread.start()

    def _apply_map_context_hints(self):
        if not self.weapon:
            self.map_context_lbl.setText(self._tr("Map context: n/a"))
            return
        lat = self.weapon.get("origin_lat")
        lon = self.weapon.get("origin_lon")
        rng = float(self.weapon.get("range_km") or 0.0)
        hints = []
        if lat is not None and lon is not None:
            hints.append(f"Launch area near ({float(lat):.3f}, {float(lon):.3f}).")
        if rng >= 500:
            hints.append(f"Very large footprint (~{rng:.0f} km).")
        elif rng >= 150:
            hints.append(f"Medium-long footprint (~{rng:.0f} km).")
        elif rng > 0:
            hints.append(f"Short footprint (~{rng:.0f} km).")
        self.map_context_lbl.setText(f"{self._tr('Map context')}: " + (" ".join(hints) if hints else self._tr("n/a")))

    def _compare_with_selected_weapon(self):
        if not self.weapon:
            QMessageBox.warning(self, self._tr("SWOT"), self._tr("Please select a base weapon first."))
            return
        compare_id = self.compare_combo.currentData()
        if not compare_id:
            return
        target = next((x for x in self._weapons_cache if int(x.get("id", -1)) == int(compare_id)), None)
        if not target:
            return
        self.subtabs.setCurrentIndex(3)
        base = self.weapon
        self.compare_header_current.setText(f"{base.get('weapon_name', 'Current')} ({base.get('model', '-')})")
        self.compare_header_target.setText(f"{target.get('weapon_name', 'Compare')} ({target.get('model', '-')})")
        left_s = self._split_lines(self.strengths_edit)
        left_w = self._split_lines(self.weaknesses_edit)
        left_o = self._split_lines(self.opportunities_edit)
        left_t = self._split_lines(self.threats_edit)
        target_report = self.db.get_latest_weapon_swot_report(int(compare_id))
        right_s = target_report.get("strengths", []) if target_report else []
        right_w = target_report.get("weaknesses", []) if target_report else []
        right_o = target_report.get("opportunities", []) if target_report else []
        right_t = target_report.get("threats", []) if target_report else []
        self.compare_s_left.setHtml(self._render_diff_html(left_s, right_s, left_side=True))
        self.compare_s_right.setHtml(self._render_diff_html(right_s, left_s, left_side=False))
        self.compare_w_left.setHtml(self._render_diff_html(left_w, right_w, left_side=True))
        self.compare_w_right.setHtml(self._render_diff_html(right_w, left_w, left_side=False))
        self.compare_o_left.setHtml(self._render_diff_html(left_o, right_o, left_side=True))
        self.compare_o_right.setHtml(self._render_diff_html(right_o, left_o, left_side=False))
        self.compare_t_left.setHtml(self._render_diff_html(left_t, right_t, left_side=True))
        self.compare_t_right.setHtml(self._render_diff_html(right_t, left_t, left_side=False))
        self.status_lbl.setText(self._tr("Status: compare view updated."))
