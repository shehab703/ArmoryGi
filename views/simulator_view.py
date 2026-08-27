"""
Embedded HTML/JS missile range simulator (local bundle under resources/html/simulator).
"""
from __future__ import annotations

import json
import logging
import base64
import io
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtCore import QThread
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from utils.ai_prompts import build_sim_analysis_prompt
from utils.ai_service import get_ollama_client, is_ai_enabled, AI_MODEL_KEY, AI_BASE_URL_KEY, AI_TIMEOUT_S_KEY
from utils.map_settings import DEFAULT_TILE_MODE, MAP_TILE_MODE_KEY, resolve_get_tile_offline_only

logger = logging.getLogger(__name__)

CATALOG_INITIAL_LIMIT = 450
SIMULATOR_LAST_UI_JSON_KEY = "simulator/last_ui_state_json"


class SimulatorWebPage(QWebEnginePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            self.fullScreenRequested.connect(lambda req: req.accept())
        except Exception:
            pass

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        logger.info(f"[SimJS] {message} ({source_id}:{line_number})")
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class SimulatorBridge(QObject):
    """Exposed to simulator page JavaScript as pyBridge."""

    def __init__(self, host: "SimulatorView"):
        super().__init__()
        self._host = host

    @pyqtSlot(int, float, float)
    def report_weapon_origin_moved(self, weapon_id: int, lat: float, lon: float):
        self._host._on_bridge_origin_moved(int(weapon_id), float(lat), float(lon))

    @pyqtSlot(int)
    def request_open_main_map(self, weapon_id: int):
        self._host._on_bridge_transfer_to_main_map(json.dumps({"weapon_id": int(weapon_id), "sim": {}}))

    @pyqtSlot(str)
    def request_transfer_to_main_map(self, payload_json: str):
        self._host._on_bridge_transfer_to_main_map(str(payload_json or ""))

    @pyqtSlot(result=str)
    def fetch_full_catalog(self) -> str:
        return self._host._catalog_json(limit=20_000, offset=0)

    @pyqtSlot(str)
    def save_session(self, state_json: str):
        self._host._save_session_to_file(str(state_json or ""))

    @pyqtSlot()
    def load_session(self):
        self._host._load_session_from_file()

    @pyqtSlot(str, str)
    def save_data_url(self, suggested_name: str, data_url: str):
        self._host._save_data_url_to_file(str(suggested_name or "export"), str(data_url or ""))

    @pyqtSlot(str, str, str)
    def export_pdf(self, suggested_name: str, png_data_url: str, meta_json: str):
        self._host._export_pdf_to_file(str(suggested_name or "simulator.pdf"), str(png_data_url or ""), str(meta_json or ""))

    @pyqtSlot(str, str, str)
    def export_docx(self, suggested_name: str, png_data_url: str, meta_json: str):
        self._host._export_docx_to_file(str(suggested_name or "simulator.docx"), str(png_data_url or ""), str(meta_json or ""))

    @pyqtSlot(str)
    def request_sim_analysis(self, state_json: str):
        self._host._request_sim_analysis(str(state_json or ""))

    @pyqtSlot(result=str)
    def fetch_simulator_ui_state(self) -> str:
        return self._host._read_simulator_ui_prefs_blob()

    @pyqtSlot(str)
    def save_simulator_ui_state(self, blob: str):
        self._host._persist_simulator_ui_prefs_blob(str(blob or ""))

    @pyqtSlot(str, int, int, int, result=str)
    def get_tile_data_uri(self, basemap: str, z: int, x: int, y: int) -> str:
        return self._host._tile_data_uri(str(basemap), int(z), int(x), int(y))


class SimulatorView(QWidget):
    """Tactical range simulator using a local Leaflet-based web page inside QWebEngineView."""

    weapon_origin_changed = pyqtSignal(dict, float, float)
    open_main_map_requested = pyqtSignal(dict)

    def __init__(self, db_manager, tile_cache=None, lang_manager=None, parent=None, settings=None):
        super().__init__(parent)
        self.db = db_manager
        self.tile_cache = tile_cache
        self.lang_manager = lang_manager
        self.settings = settings
        self._loaded = False
        self._pending_weapon: dict | None = None
        self._ai_thread: QThread | None = None
        self._tile_mode = DEFAULT_TILE_MODE
        if settings is not None:
            self._tile_mode = str(
                settings.value(MAP_TILE_MODE_KEY, DEFAULT_TILE_MODE, str) or DEFAULT_TILE_MODE
            )
        self.offline_only_tiles = resolve_get_tile_offline_only(self._tile_mode, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = QWebEngineView(self)
        page = SimulatorWebPage(self._view)
        self._view.setPage(page)
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        try:
            settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        except Exception:
            pass
        layout.addWidget(self._view)

        self._bridge = SimulatorBridge(self)
        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("pyBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)

        root = Path(__file__).resolve().parents[1] / "resources" / "html" / "simulator"
        self._index_path = root / "index.html"
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.load(QUrl.fromLocalFile(str(self._index_path.resolve())))

    def _lang_code(self) -> str:
        if self.lang_manager and getattr(self.lang_manager, "current_code", None):
            return str(self.lang_manager.current_code).strip().lower() or "en"
        return "en"

    def _persist_simulator_ui_prefs_blob(self, blob: str) -> None:
        if self.settings is None:
            return
        try:
            self.settings.setValue(SIMULATOR_LAST_UI_JSON_KEY, blob)
            self.settings.sync()
        except Exception:
            logger.debug("persist simulator prefs failed", exc_info=True)

    def _read_simulator_ui_prefs_blob(self) -> str:
        if self.settings is None:
            return ""
        try:
            v = self.settings.value(SIMULATOR_LAST_UI_JSON_KEY, "", str)
            return v if isinstance(v, str) else str(v or "")
        except Exception:
            return ""

    def _tile_data_uri(self, basemap: str, z: int, x: int, y: int) -> str:
        if not self.tile_cache:
            return ""
        key = str(basemap or "dark").strip().lower()
        if key == "sat":
            key = "satellite"
        try:
            tile_data = self.tile_cache.get_tile(
                key, int(z), int(x), int(y), offline_only=self.offline_only_tiles
            )
        except Exception:
            logger.debug("simulator tile fetch failed", exc_info=True)
            return ""
        if not tile_data:
            return ""
        return f"data:image/png;base64,{base64.b64encode(tile_data).decode('ascii')}"

    def _on_load_finished(self, ok: bool):
        self._loaded = bool(ok)
        if ok:
            self._inject_locale()
            self.refresh_catalog()
            if self._pending_weapon:
                self.apply_weapon(self._pending_weapon)
                self._pending_weapon = None

    def _weapon_payload(self, w: dict) -> dict:
        wid = w.get("id")
        if wid is None:
            return {}
        primary_model = str(w.get("primary_model") or "").strip()
        models = w.get("models") or []
        if not primary_model and isinstance(models, list):
            for row in models:
                if not isinstance(row, dict):
                    continue
                p = str(row.get("model_path") or "").strip()
                if p:
                    primary_model = p
                    break
        return {
            "id": int(wid),
            "weapon_name": w.get("weapon_name") or "",
            "model": w.get("model") or "",
            "range_km": w.get("range_km"),
            "origin_lat": w.get("origin_lat"),
            "origin_lon": w.get("origin_lon"),
            "speed_mach": w.get("speed_mach"),
            "primary_model": primary_model,
        }

    def _catalog_json(self, limit: int, offset: int) -> str:
        if not self.db:
            return "[]"
        rows = self.db.get_weapons_paginated(int(offset), int(limit), filters={})
        catalog = [self._weapon_payload(w) for w in rows if w.get("id") is not None]
        return json.dumps(catalog, ensure_ascii=False)

    def _run_js(self, script: str):
        if self._view.page():
            self._view.page().runJavaScript(script)

    def _inject_locale(self):
        lm = self.lang_manager
        keys = [
            "sim_title",
            "sim_subtitle",
            "sim_style_summary",
            "sim_style_range_ring",
            "sim_style_fill_op",
            "sim_style_fill_color",
            "sim_style_outline_op",
            "sim_style_outline_color",
            "sim_style_path_group",
            "sim_style_path_op",
            "sim_style_path_color",
            "sim_style_path_weight",
            "sim_style_path_dash",
            "sim_style_px",
            "sim_path_dash_solid",
            "sim_path_dash_short",
            "sim_path_dash_long",
            "sim_path_dash_dots",
            "sim_style_reset",
            "sim_weapon_system",
            "sim_search_label",
            "sim_quick_zoom",
            "sim_search_ph",
            "sim_select_weapon",
            "sim_labels_on",
            "sim_labels_off",
            "sim_play",
            "sim_basemap",
            "sim_bm_dark",
            "sim_bm_street",
            "sim_bm_satellite",
            "sim_measure",
            "sim_measure_hint",
            "sim_export_png",
            "sim_open_main_map",
            "sim_transfer_main_map",
            "sim_fullscreen_enter",
            "sim_fullscreen_exit",
            "sim_sidebar_hide_menu",
            "sim_sidebar_show_menu",
            "sim_tools_summary",
            "sim_swot_toggle",
            "sim_save_session",
            "sim_load_session",
            "sim_export_system",
            "sim_components",
            "sim_comp_range_azimuth",
            "sim_comp_legend",
            "sim_comp_hud",
            "sim_comp_status",
            "sim_comp_telemetry",
            "sim_comp_title",
            "sim_comp_zoom",
            "sim_comp_help",
            "sim_comp_ai",
            "sim_comp_swot",
            "sim_comp_model3d",
            "sim_layout_drag_panel",
            "sim_swot_panel_glass",
            "sim_layout_glass_op",
            "sim_swot_title",
            "sim_swot_net",
            "sim_swot_weighted",
            "sim_swot_updated",
            "sim_reset_target",
            "sim_undo_launch",
            "sim_defense_layer",
            "sim_high_contrast",
            "sim_flight_profile",
            "sim_profile_low",
            "sim_profile_high",
            "sim_arc_style",
            "sim_arc_ballistic",
            "sim_arc_cruise",
            "sim_arc_direct",
            "sim_play_speed",
            "sim_load_full_catalog",
            "sim_legend_title",
            "sim_legend_launch",
            "sim_legend_target",
            "sim_legend_path",
            "sim_ctx_copy_coords",
            "sim_ctx_copied_coords",
            "sim_stats",
            "sim_map_hint",
            "sim_tutorial_welcome",
            "sim_tutorial_intro",
            "sim_tutorial_next",
            "sim_tutorial_skip",
            "sim_tutorial_done",
            "sim_tutorial_step1",
            "sim_tutorial_step2",
            "sim_tutorial_step3",
            "sim_help_title",
            "sim_help_keys",
            "sim_status_no_weapon",
            "sim_hud_range",
            "sim_hud_launch",
            "sim_dist",
            "sim_tof_est",
            "sim_inside_range",
            "sim_outside_range",
            "sim_export_busy",
            "sim_export_fail",
            "sim_export_ok",
            "sim_zoom",
            "sim_neon_readiness",
            "sim_neon_time",
            "sim_neon_speed",
            "sim_neon_dist",
            "sim_neon_position",
            "sim_neon_standby",
            "sim_neon_los",
            "sim_neon_ready",
            "sim_neon_tof_preview",
            "sim_neon_nominal",
            "sim_neon_armed",
            "sim_neon_tminus",
            "sim_neon_liftoff",
            "sim_neon_in_flight",
            "sim_neon_elapsed",
            "sim_neon_track",
            "sim_neon_terminal",
            "sim_neon_mission",
        ]
        if lm:
            rtl = "true" if lm.is_arabic() else "false"
            trans = {k: lm.tr(k) for k in keys}
            inj = json.dumps(trans, ensure_ascii=False)
            self._run_js(
                f"window.__SIM_RTL = {rtl}; "
                f"window.__SIM_I18N = {inj}; "
                f"window.armorySimulator && window.armorySimulator.applyLocale && window.armorySimulator.applyLocale();"
            )
        else:
            self._run_js(
                "window.__SIM_RTL = false; "
                "window.__SIM_I18N = {}; "
                "window.armorySimulator && window.armorySimulator.applyLocale && window.armorySimulator.applyLocale();"
            )

    def refresh_catalog(self):
        if not self.db:
            return
        payload = self._catalog_json(CATALOG_INITIAL_LIMIT, 0)
        self._run_js(f"window.armorySimulator && window.armorySimulator.setCatalog({payload});")

    def apply_weapon(self, weapon: dict | None):
        if not weapon or weapon.get("id") is None:
            return
        payload = json.dumps(self._weapon_payload(weapon), ensure_ascii=False)
        if not self._loaded:
            self._pending_weapon = dict(weapon)
            return
        self._run_js(f"window.armorySimulator && window.armorySimulator.setActiveWeapon({payload});")
        try:
            latest = self.db.get_latest_weapon_swot_report(int(weapon["id"])) if self.db else None
        except Exception:
            latest = None
        self._run_js(
            "window.armorySimulator && window.armorySimulator.setSwotReport && "
            f"window.armorySimulator.setSwotReport({json.dumps(latest, ensure_ascii=False)});"
        )
        try:
            cached = self.db.get_weapon_ai_cache(int(weapon["id"]), "simulator_ai_analysis", self._lang_code()) if self.db else None
        except Exception:
            cached = None
        if cached and str(cached.get("content_text") or "").strip():
            safe = json.dumps(str(cached.get("content_text") or ""), ensure_ascii=False)
            self._run_js(
                "window.armorySimulator && window.armorySimulator.showAiSimBox && "
                f"window.armorySimulator.showAiSimBox({safe});"
            )

    def apply_swot_editor_text(self, payload: dict | None):
        """Receive live SWOT editor text and forward to simulator overlay."""
        if not payload:
            return
        js = json.dumps(payload, ensure_ascii=False)
        self._run_js(
            "window.armorySimulator && window.armorySimulator.setSwotEditorText && "
            f"window.armorySimulator.setSwotEditorText({js});"
        )

    class _AiWorker(QObject):
        progress = pyqtSignal(str)
        finished = pyqtSignal(str)
        failed = pyqtSignal(str)

        def __init__(self, settings, lang_manager, sim_state: dict):
            super().__init__()
            self._settings = settings
            self._lang_manager = lang_manager
            self._sim_state = sim_state

        @pyqtSlot()
        def run(self):
            try:
                client = get_ollama_client(self._settings)
                is_ar = bool(self._lang_manager and hasattr(self._lang_manager, "is_arabic") and self._lang_manager.is_arabic())
                weapon = None
                try:
                    weapon = {
                        "weapon_id": self._sim_state.get("weapon_id"),
                        "weapon_name": self._sim_state.get("weapon_name"),
                        "model": self._sim_state.get("model"),
                        "range_km": self._sim_state.get("range_km"),
                    }
                except Exception:
                    weapon = None
                system, user = build_sim_analysis_prompt(sim_state=self._sim_state, weapon=weapon, is_ar=is_ar)
                buf = []
                out_final = ""
                for chunk in client.chat_stream(system=system, user=user):
                    if chunk:
                        buf.append(str(chunk))
                        # send partials occasionally (kept simple; UI can handle frequent updates)
                        self.progress.emit("".join(buf)[-6000:])
                out_final = "".join(buf).strip()
                self.finished.emit(out_final)
            except Exception as e:
                self.failed.emit(str(e))

    def _request_sim_analysis(self, state_json: str):
        settings = self.settings
        if settings is None or not is_ai_enabled(settings):
            self._run_js("window.armorySimulator && window.armorySimulator.showAiSimBox && window.armorySimulator.showAiSimBox('Enable local AI (Ollama) in Preferences first.');")
            return
        if self._ai_thread is not None:
            return
        try:
            sim_state = json.loads(state_json) if state_json else {}
        except Exception:
            sim_state = {"raw": state_json}

        thread = QThread(self)
        worker = self._AiWorker(settings, self.lang_manager, sim_state)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _cleanup():
            try:
                thread.quit()
                thread.wait(1500)
            except Exception:
                pass
            self._ai_thread = None
            worker.deleteLater()
            thread.deleteLater()

        def _ok(text: str):
            safe = json.dumps(str(text or ""), ensure_ascii=False)
            self._run_js(
                "window.armorySimulator && window.armorySimulator.showAiSimBox && "
                f"window.armorySimulator.showAiSimBox({safe});"
            )
            try:
                wid = int(sim_state.get("weapon_id") or 0)
            except Exception:
                wid = 0
            if wid and self.db:
                self.db.save_weapon_ai_cache(
                    wid,
                    "simulator_ai_analysis",
                    self._lang_code(),
                    content_text=str(text or "").strip(),
                    content_json={"analysis": str(text or "").strip()},
                )
            _cleanup()

        def _progress(text: str):
            safe = json.dumps(str(text or ""), ensure_ascii=False)
            self._run_js(
                "window.armorySimulator && window.armorySimulator.showAiSimBox && "
                f"window.armorySimulator.showAiSimBox({safe});"
            )

        def _fail(msg: str):
            base_url = str(settings.value(AI_BASE_URL_KEY, "http://localhost:11434", str) or "").strip()
            model_name = str(settings.value(AI_MODEL_KEY, "llama3.1", str) or "").strip() or "llama3.1"
            timeout_s = str(settings.value(AI_TIMEOUT_S_KEY, 180))
            safe = json.dumps(
                f"AI analysis failed: {msg}\n\nOllama: {base_url}\nModel: {model_name}\nTimeout: {timeout_s}s",
                ensure_ascii=False,
            )
            self._run_js(
                "window.armorySimulator && window.armorySimulator.showAiSimBox && "
                f"window.armorySimulator.showAiSimBox({safe});"
            )
            _cleanup()

        worker.progress.connect(_progress)
        worker.finished.connect(_ok)
        worker.failed.connect(_fail)
        self._ai_thread = thread
        thread.start()

    def set_language_manager(self, lang_manager):
        self.lang_manager = lang_manager
        if self._loaded:
            self._inject_locale()

    def _on_bridge_origin_moved(self, weapon_id: int, lat: float, lon: float):
        self.weapon_origin_changed.emit({"id": weapon_id}, lat, lon)

    def _on_bridge_transfer_to_main_map(self, payload_json: str):
        try:
            data = json.loads(payload_json) if payload_json else {}
        except Exception:
            return
        wid = data.get("weapon_id")
        if wid is None or not self.db:
            return
        w = self.db.get_weapon_by_id(int(wid), eager_load=True)
        if not w:
            return
        weapon_dict = w.to_dict(include_images=True, include_variants=False)
        sim = data.get("sim")
        if sim is not None and not isinstance(sim, dict):
            sim = {}
        self.open_main_map_requested.emit({"weapon": weapon_dict, "sim": sim or {}})

    def _save_session_to_file(self, state_json: str):
        try:
            state = json.loads(state_json) if state_json else {}
        except Exception:
            state = {"raw": state_json}
        default_name = f"armorygis-sim-{int(state.get('weapon_id') or 0)}.armorysim.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save simulator session", default_name, "Simulator Session (*.armorysim.json);;JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save simulator session: {e}")

    def _load_session_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load simulator session", "", "Simulator Session (*.armorysim.json *.json);;All files (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load simulator session: {e}")
            return
        payload = json.dumps(state or {}, ensure_ascii=False)
        self._run_js(f"window.armorySimulator && window.armorySimulator.loadState && window.armorySimulator.loadState({payload});")

    def _save_data_url_to_file(self, suggested_name: str, data_url: str):
        if not data_url.startswith("data:"):
            return
        default_name = suggested_name or "armorygis-export"
        filt = "All files (*.*)"
        lower = default_name.lower()
        if lower.endswith(".png"):
            filt = "PNG (*.png);;All files (*.*)"
        elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
            filt = "JPG (*.jpg *.jpeg);;All files (*.*)"
        elif lower.endswith(".svg"):
            filt = "SVG (*.svg);;All files (*.*)"
        path, _ = QFileDialog.getSaveFileName(self, "Save export", default_name, filt)
        if not path:
            return
        try:
            header, b64 = data_url.split(",", 1)
            raw = base64.b64decode(b64.encode("ascii"))
            mode = "wb"
            with open(path, mode) as f:
                f.write(raw)
        except Exception as e:
            logger.warning(f"Failed to save export: {e}")

    def _export_pdf_to_file(self, suggested_name: str, png_data_url: str, meta_json: str):
        """Export PDF from a captured map image (not the sidebar)."""
        default_name = suggested_name or "armorygis-simulator.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF (map only)", default_name, "PDF (*.pdf)")
        if not path:
            return
        if not png_data_url.startswith("data:image/png;base64,"):
            logger.warning("export_pdf_to_file: missing png data url")
            return
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except Exception:
            meta = {}
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.lib.utils import ImageReader
        except Exception as e:
            logger.warning(f"reportlab unavailable: {e}")
            return
        try:
            b64 = png_data_url.split(",", 1)[1]
            raw = base64.b64decode(b64.encode("ascii"))
            img = ImageReader(io.BytesIO(raw))

            # Landscape letter with margins.
            pagesize = landscape(letter)
            c = canvas.Canvas(path, pagesize=pagesize)
            w, h = pagesize
            margin = 24
            title = str(meta.get("title") or "ArmoryGIS Simulator")
            weapon = str(meta.get("weapon_name") or "")
            ts = str(meta.get("timestamp") or "")

            c.setFillColorRGB(0.7, 0.95, 1.0)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(margin, h - margin - 10, title)
            c.setFont("Helvetica", 10)
            if weapon:
                c.drawString(margin, h - margin - 26, f"Weapon: {weapon}")
            if ts:
                c.drawString(margin, h - margin - 40, f"Exported: {ts}")

            top_reserved = 56
            box_w = w - margin * 2
            box_h = h - margin * 2 - top_reserved
            x0 = margin
            y0 = margin

            # Fit image into box while preserving aspect.
            img_w, img_h = img.getSize()
            scale = min(box_w / img_w, box_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            x = x0 + (box_w - draw_w) / 2
            y = y0 + (box_h - draw_h) / 2
            c.drawImage(img, x, y, width=draw_w, height=draw_h, preserveAspectRatio=True, mask='auto')

            c.showPage()
            c.save()
        except Exception as e:
            logger.warning(f"Failed to export PDF: {e}")

    def _export_docx_to_file(self, suggested_name: str, png_data_url: str, meta_json: str):
        default_name = suggested_name or "armorygis-simulator.docx"
        path, _ = QFileDialog.getSaveFileName(self, "Export DOCX", default_name, "Word Document (*.docx)")
        if not path:
            return
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except Exception:
            meta = {}
        try:
            import docx  # python-docx
            from docx.shared import Inches
        except Exception as e:
            logger.warning(f"python-docx unavailable: {e}")
            return
        try:
            title = str(meta.get("title") or "ArmoryGIS Simulator Export")
            doc = docx.Document()
            doc.add_heading(title, level=1)
            if meta.get("weapon_name"):
                doc.add_paragraph(f"Weapon: {meta.get('weapon_name')}")
            if meta.get("timestamp"):
                doc.add_paragraph(f"Exported: {meta.get('timestamp')}")
            if png_data_url.startswith("data:image/png;base64,"):
                b64 = png_data_url.split(",", 1)[1]
                raw = base64.b64decode(b64.encode("ascii"))
                bio = io.BytesIO(raw)
                doc.add_picture(bio, width=Inches(6.5))
            doc.save(path)
        except Exception as e:
            logger.warning(f"Failed to export DOCX: {e}")
