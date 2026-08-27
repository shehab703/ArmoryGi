import logging

from utils.map_settings import (
    DEFAULT_BASEMAP,
    DEFAULT_TILE_MODE,
    MAP_BASEMAP_KEY,
    MAP_TILE_MODE_KEY,
    resolve_get_tile_offline_only,
)

from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
import os
import json
import base64

logger = logging.getLogger(__name__)


class MapWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        logger.info(f"[MapJS] {message} ({source_id}:{line_number})")
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class MapController(QObject):
    """Bridge object exposed to JavaScript"""
    tile_requested = pyqtSignal(str, int, int, int) # basemap, z, x, y
    target_point_selected = pyqtSignal(float, float)
    weapon_origin_moved = pyqtSignal(float, float)
    compare_point_selected = pyqtSignal(float, float)
    compare_weapon_moved = pyqtSignal(int, float, float)
    compare_weapon_focus = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._tile_fetcher = None

    @pyqtSlot(str, int, int, int)
    def request_tile(self, basemap, z, x, y):
        self.tile_requested.emit(basemap, z, x, y)

    @pyqtSlot(float, float)
    def report_target_point(self, lat, lon):
        self.target_point_selected.emit(lat, lon)

    @pyqtSlot(float, float)
    def report_weapon_origin(self, lat, lon):
        self.weapon_origin_moved.emit(lat, lon)

    @pyqtSlot(float, float)
    def report_compare_point(self, lat, lon):
        self.compare_point_selected.emit(lat, lon)

    @pyqtSlot(int, float, float)
    def report_compare_weapon_moved(self, weapon_id, lat, lon):
        self.compare_weapon_moved.emit(int(weapon_id), float(lat), float(lon))

    @pyqtSlot(int)
    def report_compare_weapon_focus(self, weapon_id):
        self.compare_weapon_focus.emit(int(weapon_id))

    @pyqtSlot(str, int, int, int, result=str)
    def get_tile_data_uri(self, basemap, z, x, y):
        if not callable(self._tile_fetcher):
            return ""
        try:
            return str(self._tile_fetcher(str(basemap), int(z), int(x), int(y)))
        except Exception:
            return ""

class MapView(QWebEngineView):
    weapon_dropped_on_map = pyqtSignal(dict, float, float)
    weapon_origin_changed = pyqtSignal(dict, float, float)
    compare_point_selected = pyqtSignal(float, float)
    compare_weapon_moved = pyqtSignal(int, float, float)
    compare_weapon_focus = pyqtSignal(int)

    def __init__(self, tile_cache, db_manager, offline_only_tiles: bool = True, qsettings=None, compare_mode: bool = False):
        super().__init__()
        self.setPage(MapWebPage(self))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._qsettings = qsettings
        web_settings = self.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.tile_cache = tile_cache
        self.db = db_manager
        self._tile_mode = DEFAULT_TILE_MODE
        self._fallback_online = False
        if qsettings is not None:
            self._tile_mode = str(
                qsettings.value(MAP_TILE_MODE_KEY, DEFAULT_TILE_MODE, str) or DEFAULT_TILE_MODE
            )
        elif not offline_only_tiles:
            from utils.map_settings import TILE_MODE_ONLINE
            self._tile_mode = TILE_MODE_ONLINE
        self.offline_only_tiles = resolve_get_tile_offline_only(
            self._tile_mode, self._fallback_online
        )
        self._map_ready = False
        self._pending_js = []
        self._weapon_provider = None
        self._active_weapon = None
        self._main_map_locale: dict | None = None
        self._compare_mode = bool(compare_mode)
        self._compare_place_mode = False
        self.setAcceptDrops(True)
        
        self.channel = QWebChannel(self)
        self.controller = MapController()
        self.channel.registerObject("pyController", self.controller)
        self.page().setWebChannel(self.channel)
        self.controller._tile_fetcher = self._tile_data_uri
        
        # Connect tile request from JS to Python cache logic
        self.controller.tile_requested.connect(self._serve_tile)
        self.controller.target_point_selected.connect(self._on_target_selected)
        self.controller.weapon_origin_moved.connect(self._on_weapon_origin_moved)
        self.controller.compare_point_selected.connect(self._on_compare_point_selected)
        self.controller.compare_weapon_moved.connect(self._on_compare_weapon_moved)
        self.controller.compare_weapon_focus.connect(self._on_compare_weapon_focus)
        self.loadFinished.connect(self._on_load_finished)
        
        # Load HTML
        html_path = os.path.join(os.path.dirname(__file__), '..', 'resources', 'html', 'map.html')
        if os.path.exists(html_path):
            self.setUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))
        else:
            self.setHtml("<html><body><h3>Map resource not found</h3></body></html>")
    
    def _run_js(self, js: str):
        if self._map_ready:
            self.page().runJavaScript(
                js,
                lambda result: logger.debug(f"[MapJS result] {str(result)[:120]}")
            )
        else:
            self._pending_js.append(js)

    def _sync_range_azimuth_preference(self):
        if not self._qsettings:
            return
        try:
            v = bool(self._qsettings.value("map/range_ring_azimuth", False))
        except Exception:
            v = False
        self._run_js(f"setRangeRingAzimuthEnabled({str(v).lower()});")

    def set_range_ring_azimuth_enabled(self, enabled: bool):
        if self._qsettings:
            self._qsettings.setValue("map/range_ring_azimuth", bool(enabled))
        self._run_js(f"setRangeRingAzimuthEnabled({str(bool(enabled)).lower()});")

    def apply_main_map_locale(self, strings: dict | None):
        if strings:
            self._main_map_locale = dict(strings)
            payload = json.dumps(self._main_map_locale, ensure_ascii=False)
            self._run_js(f"applyMainMapLocaleStrings({payload});")
        else:
            self._main_map_locale = None

    def _on_load_finished(self, ok: bool):
        self._map_ready = bool(ok)
        if not ok:
            logger.error("Map HTML failed to load")
        self._run_js(f"setDebugStatus('Map loaded: {self._map_ready}')")
        self._run_js("window.__armoryMapPing && window.__armoryMapPing();")
        self._sync_range_azimuth_preference()
        if self._map_ready and self._pending_js:
            for cmd in self._pending_js:
                self.page().runJavaScript(cmd)
            self._pending_js.clear()
        if ok and self._main_map_locale:
            payload = json.dumps(self._main_map_locale, ensure_ascii=False)
            self.page().runJavaScript(f"applyMainMapLocaleStrings({payload});")
        if ok and self._compare_mode:
            self._run_js(f"setCompareMode({str(self._compare_mode).lower()});")

    def _on_target_selected(self, lat: float, lon: float):
        self._run_js(f"setDebugStatus('Target selected: {lat:.4f}, {lon:.4f}')")
        selected = self._weapon_provider() if callable(self._weapon_provider) else None
        if not selected:
            selected = self._active_weapon
        if selected:
            self.weapon_dropped_on_map.emit(selected, lat, lon)

    def _on_weapon_origin_moved(self, lat: float, lon: float):
        selected = self._weapon_provider() if callable(self._weapon_provider) else None
        if not selected:
            selected = self._active_weapon
        if selected:
            self.weapon_origin_changed.emit(selected, lat, lon)

    def _on_compare_point_selected(self, lat: float, lon: float):
        if self._compare_place_mode:
            self.compare_point_selected.emit(lat, lon)

    def _on_compare_weapon_moved(self, weapon_id: int, lat: float, lon: float):
        self.compare_weapon_moved.emit(int(weapon_id), float(lat), float(lon))

    def _on_compare_weapon_focus(self, weapon_id: int):
        self.compare_weapon_focus.emit(int(weapon_id))

    def set_compare_mode(self, enabled: bool):
        self._compare_mode = bool(enabled)
        self._run_js(f"setCompareMode({str(bool(enabled)).lower()});")

    def set_compare_place_mode(self, enabled: bool):
        self._compare_place_mode = bool(enabled)
        self._run_js(f"setComparePlaceMode({str(bool(enabled)).lower()});")

    def set_compare_weapons(self, weapons: list):
        payload = json.dumps(weapons or [], ensure_ascii=False)
        self._run_js(f"setCompareWeapons({payload});")

    def clear_compare_weapons(self):
        self._run_js("clearCompareWeapons();")

    def fit_compare_bounds(self):
        self._run_js("fitCompareBounds();")

    def bring_compare_weapon_front(self, weapon_id: int):
        self._run_js(f"bringCompareWeaponFront({int(weapon_id)});")

    def send_compare_weapon_back(self, weapon_id: int):
        self._run_js(f"sendCompareWeaponBack({int(weapon_id)});")

    def set_tile_mode(self, mode: str, fallback_online: bool = False):
        """Apply offline / online / auto tile loading policy."""
        self._tile_mode = (mode or DEFAULT_TILE_MODE).strip().lower()
        self._fallback_online = bool(fallback_online)
        self.offline_only_tiles = resolve_get_tile_offline_only(
            self._tile_mode, self._fallback_online
        )

    def reload_basemap(self, basemap_name: str | None = None):
        if basemap_name is None and self._qsettings is not None:
            basemap_name = str(
                self._qsettings.value(MAP_BASEMAP_KEY, DEFAULT_BASEMAP, str) or DEFAULT_BASEMAP
            )
        if basemap_name:
            self.set_basemap(basemap_name)

    def set_weapon_provider(self, provider):
        self._weapon_provider = provider
        self._run_js("setDebugStatus('Weapon provider attached')")

    def set_active_weapon(self, weapon: dict):
        self._active_weapon = weapon
        name = weapon.get("weapon_name", "Unknown")
        self._run_js(f"setDebugStatus('Active weapon: {json.dumps(str(name))}')")

    def _serve_tile(self, basemap, z, x, y):
        # Request tile data (cache-first in TileCacheManager).
        tile_data = self.tile_cache.get_tile(
            basemap, z, x, y, offline_only=self.offline_only_tiles
        )
        if tile_data:
            b64 = base64.b64encode(tile_data).decode("ascii")
            js = f"loadTileFromPath({x}, {y}, {z}, 'data:image/png;base64,{b64}');"
            self._run_js(js)

    def _tile_data_uri(self, basemap: str, z: int, x: int, y: int) -> str:
        tile_data = self.tile_cache.get_tile(
            basemap, z, x, y, offline_only=self.offline_only_tiles
        )
        if not tile_data:
            return ""
        b64 = base64.b64encode(tile_data).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def add_weapon_marker(self, weapon_data):
        lat = weapon_data.get('origin_lat', 0)
        lon = weapon_data.get('origin_lon', 0)
        name = weapon_data.get('weapon_name', 'Weapon')
        range_km = weapon_data.get('range_km', 0)

        safe_name = json.dumps(str(name))
        js = f"addMarker({float(lat)}, {float(lon)}, {safe_name}, {float(range_km or 0)});"
        self._run_js(js)

    def center_on_weapon(self, weapon_data):
        if not weapon_data:
            return
        self.center_on_coordinates(
            weapon_data.get('origin_lat', 0),
            weapon_data.get('origin_lon', 0),
            zoom=8
        )

    def center_on_coordinates(self, lat, lon, zoom=6):
        self._run_js(f"setDebugStatus('Center map: {lat:.3f},{lon:.3f} z{zoom}')")
        js = f"centerMap({float(lat)}, {float(lon)}, {int(zoom)});"
        self._run_js(js)

    def set_basemap(self, basemap_name):
        self._run_js(f"setDebugStatus('Basemap: {json.dumps(str(basemap_name))}')")
        js = f"setBasemap({json.dumps(str(basemap_name))});"
        self._run_js(js)

    def zoom_in(self):
        self._run_js("zoomInMap();")

    def zoom_out(self):
        self._run_js("zoomOutMap();")

    def draw_range_ring(self, lat, lon, range_km, weapon_name="Weapon"):
        self._run_js("setDebugStatus('Draw range ring requested')")
        js = (
            f"drawRangeRing({float(lat)}, {float(lon)}, {float(range_km)}, "
            f"{json.dumps(str(weapon_name))});"
        )
        self._run_js(js)

    def draw_weapon_effects(
        self,
        lat: float,
        lon: float,
        min_range_km: float,
        max_range_km: float,
        blast_radius_m: float,
        weapon_name: str,
        target_lat: float = None,
        target_lon: float = None,
    ):
        self._run_js("setDebugStatus('Draw weapon effects requested')")
        js = (
            "drawWeaponEffects("
            f"{float(lat)}, {float(lon)}, {float(min_range_km)}, {float(max_range_km)}, "
            f"{float(blast_radius_m)}, {json.dumps(str(weapon_name))}, "
            f"{'null' if target_lat is None else float(target_lat)}, "
            f"{'null' if target_lon is None else float(target_lon)}"
            ");"
        )
        self._run_js(js)

    def append_simulator_trajectory(self, path_points: list):
        if not path_points or len(path_points) < 2:
            return
        js = "appendSimulatorTrajectory(" + json.dumps(path_points) + ");"
        self._run_js(js)

    def append_defense_circle(self, lat: float, lon: float, radius_m: float):
        js = f"appendDefenseCircle({float(lat)}, {float(lon)}, {float(radius_m)});"
        self._run_js(js)

    def append_simulator_measure(self, points: list):
        """Draw simulator ruler segment on the main map (two {lat,lng} points)."""
        if not points or len(points) < 2:
            return
        js = "appendSimulatorMeasure(" + json.dumps(points) + ");"
        self._run_js(js)

    def update_sim_transfer_legend(self, sim: dict | None):
        """Show simulator-style legend on the main map after transfer; hide when not from simulator."""
        if not sim:
            self._run_js("hideSimTransferLegend();")
            return
        defense = (
            isinstance(sim.get("defense"), dict)
            and sim["defense"].get("lat") is not None
            and sim["defense"].get("lon") is not None
        )
        measure = isinstance(sim.get("measure"), list) and len(sim.get("measure") or []) >= 2
        payload = json.dumps({"defense": defense, "measure": measure})
        self._run_js(f"showSimTransferLegend({payload});")

    def show_transfer_info_panel(self, payload: dict):
        """Fill scenario info box after simulator → main map transfer."""
        if not payload:
            self.hide_transfer_info_panel()
            return
        self._run_js("showTransferInfoPanel(" + json.dumps(payload, ensure_ascii=False) + ");")

    def hide_transfer_info_panel(self):
        self._run_js("hideTransferInfoPanel();")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat("application/x-armory-weapon") or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        payload = None
        if event.mimeData().hasFormat("application/x-armory-weapon"):
            payload = bytes(event.mimeData().data("application/x-armory-weapon")).decode("utf-8")
        elif event.mimeData().hasText():
            payload = event.mimeData().text()
        try:
            weapon = json.loads(payload) if payload else None
        except Exception:
            weapon = None
        if weapon:
            self._active_weapon = weapon
            x = event.position().x()
            y = event.position().y()
            self._run_js(f"onExternalWeaponDrop({float(x)}, {float(y)});")
            event.acceptProposedAction()
            return
        super().dropEvent(event)