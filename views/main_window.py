"""
Main Application Window with integrated map, grid, and dashboard
"""
from pathlib import Path
import copy
import os

from PyQt6.QtWidgets import (QMainWindow, QMenuBar, QToolBar, QSplitter,
                             QTabWidget, QStatusBar, QFileDialog, QMessageBox,
                             QProgressDialog, QLabel, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QToolButton, QStyle, QCheckBox, QApplication, QStackedWidget)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QUrl, QSize, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QShortcut, QKeySequence, QPixmap

from config import APP_CONFIG, TILE_CACHE_CONFIG, THEME_CONFIG, LANGUAGE_CONFIG

from views.data_grid_view import DataGridView
from views.dashboard_view import DashboardView
from views.favorites_dashboard_view import FavoritesDashboardView
from views.weapon_detail_view import WeaponDetailView
from views.map_view import MapView
from views.range_compare_tab import RangeCompareTab
from views.settings_panel import SettingsPanel
from views.single_weapon_view import SingleWeaponView
from views.report_workspace_view import ReportWorkspaceView
from views.swot_analysis_view import SWOTAnalysisView
from views.simulator_view import SimulatorView
from views.weapon_3d_view import Weapon3DView
from dialogs.export_dialog import ExportDialog
from dialogs.settings_dialog import SettingsDialog
from dialogs.add_weapon_dialog import AddWeaponDialog
from utils.gmdb_sources import get_gmdb_options
from utils.map_settings import (
    DEFAULT_BASEMAP,
    DEFAULT_TILE_MODE,
    MAP_BASEMAP_KEY,
    MAP_TILE_MODE_KEY,
    TILE_MODE_OFFLINE,
)
from utils.geo_bearing import haversine_km, initial_bearing_deg

import logging
logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window with multi-panel layout"""
    
    # Signals for inter-component communication
    weapon_selected = pyqtSignal(dict)
    weapon_updated = pyqtSignal(dict)
    map_weapon_dropped = pyqtSignal(dict, float, float)
    STARTUP_TAB_MODE_KEY = "ui/startup_tab_mode"
    STARTUP_TAB_MODE_CONTROL = "control_panel"
    STARTUP_TAB_MODE_LAST = "last_tab"
    LAST_TAB_INDEX_KEY = "ui/last_tab_index"
    BRAND_COMPANY_NAME_KEY = "ui/company_name"
    BRAND_LOGO_PATH_KEY = "ui/company_logo_path"
    BRAND_LOGO_SIZE_KEY = "ui/company_logo_size"
    BRAND_LOGO_WIDTH_KEY = "ui/company_logo_width"
    BRAND_LOGO_HEIGHT_KEY = "ui/company_logo_height"
    BRAND_LOGO_SCALE_PERCENT_KEY = "ui/company_logo_scale_percent"
    
    def __init__(
        self,
        db_manager,
        tile_cache,
        theme_manager,
        lang_manager,
        settings,
        embedded=False,
        username="analyst",
    ):
        super().__init__()
        
        # Store dependencies
        self.db = db_manager
        self.tile_cache = tile_cache
        self.theme_manager = theme_manager
        self.lang_manager = lang_manager
        self.settings = settings
        self.embedded_mode = embedded
        self.username = username
        self._refresh_pending = False
        self._last_main_map_transfer: tuple[dict, dict] | None = None
        self._status_refresh_pending = False
        self.range_compare_tab = None
        self.map_view = None
        self.single_weapon_view = None
        self.simulator_view = None
        self._map_tab_index = 1
        self._single_weapon_tab_index = 2
        self._simulator_tab_index = 6
        self._weapon_3d_tab_index = 7
        
        # Initialize UI
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
            self.setMinimumSize(320, 240)
            self.setWindowTitle("")
            embed_w = int(os.environ.get("ORBAT_EMBED_WIDTH", "0") or "0")
            embed_h = int(os.environ.get("ORBAT_EMBED_HEIGHT", "0") or "0")
            if embed_w > 100 and embed_h > 100:
                self.resize(embed_w, embed_h)
        else:
            self.setWindowTitle(f"{APP_CONFIG['app_name']} v{APP_CONFIG['version']}")
            self.setMinimumSize(1400, 900)
            self._load_geometry()
        
        # Build UI components
        self._create_menu_bar()
        self._create_central_widget()
        self._create_status_bar()
        
        # Connect signals
        self._connect_signals()
        
        # Load initial data
        self._load_initial_data()
        self._apply_runtime_settings()
        
        logger.info("Main window initialized")

    def embedded_warmup(self):
        """Fast startup path when embedded inside C# host."""
        try:
            self._load_initial_data()
        except Exception as exc:
            logger.warning("Embedded warmup failed: %s", exc)
        QApplication.processEvents()

    def _load_geometry(self):
        """Restore window position/size from settings"""
        geom = self.settings.value('window/geometry')
        if geom:
            self.restoreGeometry(geom)
    
    def _save_geometry(self):
        """Save window position/size to settings"""
        self.settings.setValue('window/geometry', self.saveGeometry())
    
    def _create_menu_bar(self):
        """Create application menu bar"""
        menubar = self.menuBar()
        
        # File Menu
        file_menu = menubar.addMenu("&File")
        self._menu_file = file_menu
        
        new_action = QAction("&New Database", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_database)
        file_menu.addAction(new_action)
        
        open_action = QAction("&Open Database...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_database)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        export_action = QAction("Reports &workspace...", self)
        export_action.setShortcut("Ctrl+Shift+R")
        export_action.triggered.connect(self._open_reports_workspace)
        file_menu.addAction(export_action)

        quick_export_action = QAction("Spreadsheet export (dialog)…", self)
        quick_export_action.triggered.connect(self._show_export_dialog)
        file_menu.addAction(quick_export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit Menu
        edit_menu = menubar.addMenu("&Edit")
        self._menu_edit = edit_menu
        
        add_action = QAction("&Add Weapon...", self)
        add_action.setShortcut("Ctrl+A")
        add_action.triggered.connect(self._show_add_weapon_dialog)
        edit_menu.addAction(add_action)
        
        edit_action = QAction("&Edit Selected", self)
        edit_action.setShortcut("Ctrl+E")
        edit_action.triggered.connect(self._edit_selected_weapon)
        edit_menu.addAction(edit_action)
        
        delete_action = QAction("&Delete Selected", self)
        delete_action.setShortcut("Del")
        delete_action.triggered.connect(self._delete_selected_weapon)
        edit_menu.addAction(delete_action)
        
        # View Menu
        view_menu = menubar.addMenu("&View")
        self._menu_view = view_menu
        
        # Basemap switcher
        basemap_group = QActionGroup(self)
        basemap_options = [(name.title(), name) for name in TILE_CACHE_CONFIG['basemaps']]
        basemap_options.extend(get_gmdb_options(self.settings))
        for label, basemap_data in basemap_options:
            action = QAction(label, self, checkable=True)
            action.setData(basemap_data)
            action.triggered.connect(self._change_basemap)
            basemap_group.addAction(action)
            view_menu.addAction(action)
            if basemap_data == APP_CONFIG['default_basemap']:
                action.setChecked(True)
        
        view_menu.addSeparator()
        
        # Theme switcher
        theme_group = QActionGroup(self)
        for theme_name in THEME_CONFIG['themes'].keys():
            action = QAction(theme_name.replace('_', ' ').title(), self, checkable=True)
            action.setData(theme_name)
            action.triggered.connect(self._change_theme)
            theme_group.addAction(action)
            view_menu.addAction(action)
            if theme_name == THEME_CONFIG['default_theme']:
                action.setChecked(True)

        view_menu.addSeparator()
        zoom_in_action = QAction("Zoom +", self)
        zoom_out_action = QAction("Zoom -", self)
        zoom_in_action.triggered.connect(self._zoom_main_map_in)
        zoom_out_action.triggered.connect(self._zoom_main_map_out)
        view_menu.addAction(zoom_in_action)
        view_menu.addAction(zoom_out_action)
        self._zoom_in_action = zoom_in_action
        self._zoom_out_action = zoom_out_action
        
        # Tools Menu
        tools_menu = menubar.addMenu("&Tools")
        self._menu_tools = tools_menu
        
        pre_cache_action = QAction("تحميل الخريطة للعمل بدون إنترنت...", self)
        pre_cache_action.triggered.connect(self._show_pre_cache_dialog)
        tools_menu.addAction(pre_cache_action)
        
        cache_stats_action = QAction("View Cache Statistics", self)
        cache_stats_action.triggered.connect(self._show_cache_stats)
        tools_menu.addAction(cache_stats_action)
        
        tools_menu.addSeparator()
        
        cleanup_action = QAction("Cleanup Old Cache", self)
        cleanup_action.triggered.connect(self._cleanup_cache)
        tools_menu.addAction(cleanup_action)
        
        # Settings Menu
        settings_menu = menubar.addMenu("&Settings")
        self._menu_settings = settings_menu
        
        prefs_action = QAction("&Preferences...", self)
        prefs_action.setShortcut("Ctrl+,")
        prefs_action.triggered.connect(self._show_settings)
        settings_menu.addAction(prefs_action)
        
        # Help Menu
        help_menu = menubar.addMenu("&Help")
        self._menu_help = help_menu
        
        about_action = QAction("&About ArmoryGIS Pro", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        self._export_action = export_action
        self._quick_export_action = quick_export_action
        self._add_action = add_action
        self._edit_action = edit_action
        self._delete_action = delete_action
        self._prefs_action = prefs_action
        self._about_action = about_action
    
    def _create_central_widget(self):
        """Create full-screen tabbed interfaces."""
        self.main_tabs = QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.main_tabs.setMovable(False)
        self.report_workspace = None
        self.settings_panel = None

        # 1) Data grid interface
        self.data_grid = DataGridView(self.db, lang_manager=self.lang_manager)
        self.data_grid.set_action_handlers(
            self._show_add_weapon_dialog,
            self._edit_selected_weapon,
            self._delete_selected_weapon,
            self._open_reports_workspace,
        )
        self.main_tabs.addTab(self.data_grid, self._safe_tab_icon("grid.svg"), "Data Grid")

        # 2) Map — lazy-loaded range comparison (stack avoids tab remove/insert flicker)
        self._map_stack = QStackedWidget()
        self._map_loading = QLabel("…")
        self._map_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._map_stack.addWidget(self._map_loading)
        self.main_tabs.addTab(self._map_stack, self._safe_tab_icon("map.svg"), "Map")

        # 3) Single weapon — lazy-loaded (WebEngine)
        self._single_weapon_placeholder = QWidget()
        self.main_tabs.addTab(
            self._single_weapon_placeholder, self._safe_tab_icon("detail.svg"), "Single Weapon View"
        )

        # 4) Control panel interface (dashboard + detail)
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        self.control_split = QSplitter(Qt.Orientation.Horizontal)
        self.dashboard = DashboardView(self.db, lang_manager=self.lang_manager)
        self.detail_view = WeaponDetailView(self.db, self.tile_cache, lang_manager=self.lang_manager, settings=self.settings)
        self.control_split.addWidget(self.dashboard)
        self.control_split.addWidget(self.detail_view)
        self.control_split.setStretchFactor(0, 1)
        self.control_split.setStretchFactor(1, 1)
        # Default to expanded left panel (dashboard) per workflow request.
        self.control_split.setSizes([1, 0])
        control_layout.addWidget(self.control_split)
        self.main_tabs.addTab(control_panel, self._safe_tab_icon("dashboard.svg"), "Control Panel")

        # Favorites dashboard (same cards as Control Panel; weapons flagged favorite only)
        self.favorites_dashboard = FavoritesDashboardView(self.db, lang_manager=self.lang_manager)
        self.main_tabs.addTab(self.favorites_dashboard, self._safe_tab_icon("dashboard.svg"), "Favorites")

        # SWOT analysis interface
        self.swot_analysis = SWOTAnalysisView(self.db, lang_manager=self.lang_manager, settings=self.settings)
        self.main_tabs.addTab(self.swot_analysis, self._safe_tab_icon("detail.svg"), "SWOT Analysis")

        # Tactical range simulator — lazy-loaded (WebEngine)
        self._simulator_placeholder = QWidget()
        self.main_tabs.addTab(self._simulator_placeholder, self._safe_tab_icon("map.svg"), "Simulator")

        # 6) 3D Weapon Viewer — dedicated immersive 3D presentation tab
        self._weapon_3d_view = Weapon3DView(
            self.db,
            tile_cache=self.tile_cache,
            lang_manager=self.lang_manager,
            settings=self.settings,
        )
        self.main_tabs.addTab(
            self._weapon_3d_view,
            self._safe_tab_icon("map.svg"),
            "3D Viewer"
        )
        self._weapon_3d_tab_index = 7

        # 7) Reports workspace (preview + edit + export) - lazy loaded
        self._reports_placeholder = QWidget()
        self._reports_tab_index = self.main_tabs.addTab(
            self._reports_placeholder, self._safe_tab_icon("detail.svg"), "Reports"
        )

        # 6) Settings interface - lazy loaded
        self._settings_placeholder = QWidget()
        self._settings_tab_index = self.main_tabs.addTab(
            self._settings_placeholder, self._safe_tab_icon("settings.svg"), "Settings"
        )

        self.setCentralWidget(self.main_tabs)
        self._setup_tabs_branding()
        self._setup_tab_navigation()
        self.main_tabs.currentChanged.connect(self._on_tab_changed)
        start_idx = self._startup_tab_index()
        self.main_tabs.setCurrentIndex(start_idx)

    def _on_tab_changed(self, index: int):
        self.settings.setValue(self.LAST_TAB_INDEX_KEY, int(index))
        if index == self._map_tab_index:
            self._ensure_range_compare_tab()
        elif index == self._single_weapon_tab_index:
            self._ensure_single_weapon_view()
        elif index == self._weapon_3d_tab_index:
            # Refresh 3D viewer with current selection
            weapon = self._get_active_weapon_for_map_tools()
            if weapon:
                self._weapon_3d_view.load_weapon(weapon)
        elif index == self._simulator_tab_index:
            self._ensure_simulator_view()
        elif index == self._reports_tab_index:
            self._ensure_report_workspace()
        elif index == self._settings_tab_index:
            panel = self._ensure_settings_panel()
            if panel is not None:
                panel.refresh_cache_status()

    def _startup_tab_index(self) -> int:
        mode = self.settings.value(self.STARTUP_TAB_MODE_KEY, self.STARTUP_TAB_MODE_CONTROL, str)
        if mode == self.STARTUP_TAB_MODE_LAST:
            idx = int(self.settings.value(self.LAST_TAB_INDEX_KEY, 3, int))
            if 0 <= idx < self.main_tabs.count():
                return idx
        return 3

    def _ensure_report_workspace(self):
        if self.report_workspace is not None:
            return self.report_workspace
        self.report_workspace = ReportWorkspaceView(
            self.db, self.tile_cache, lang_manager=self.lang_manager, settings=self.settings
        )
        self.main_tabs.removeTab(self._reports_tab_index)
        self.main_tabs.insertTab(self._reports_tab_index, self.report_workspace, self._safe_tab_icon("detail.svg"), "Reports")
        return self.report_workspace

    def _ensure_settings_panel(self):
        if self.settings_panel is not None:
            return self.settings_panel
        self.settings_panel = SettingsPanel(
            self.settings, self.theme_manager, self.lang_manager,
            db_manager=self.db, tile_cache=self.tile_cache,
        )
        self.settings_panel.settings_applied.connect(self._apply_runtime_settings)
        self.settings_panel.precache_requested.connect(self._on_precache_requested)
        self.settings_panel.world_precache_requested.connect(self._on_world_precache_requested)
        self.main_tabs.removeTab(self._settings_tab_index)
        self.main_tabs.insertTab(self._settings_tab_index, self.settings_panel, self._safe_tab_icon("settings.svg"), "Settings")
        self.settings_panel.retranslate_ui()
        return self.settings_panel

    def _ensure_range_compare_tab(self) -> RangeCompareTab:
        if self.range_compare_tab is not None:
            self._map_stack.setCurrentWidget(self.range_compare_tab)
            self.range_compare_tab.on_tab_activated()
            return self.range_compare_tab
        self._map_loading.setText(self.lang_manager.tr("Loading map…"))
        self._map_stack.setCurrentWidget(self._map_loading)
        QApplication.processEvents()
        self.range_compare_tab = RangeCompareTab(
            self.db,
            self.tile_cache,
            settings=self.settings,
            lang_manager=self.lang_manager,
        )
        self.map_view = self.range_compare_tab.map_view
        self.map_view.set_weapon_provider(self._get_active_weapon_for_map_tools)
        self.map_view.weapon_dropped_on_map.connect(self._handle_map_drop)
        self.map_view.weapon_origin_changed.connect(self._handle_weapon_origin_change)
        self.map_view.apply_main_map_locale(self._main_map_embed_locale())
        if self._last_main_map_transfer:
            w, s = self._last_main_map_transfer
            self.map_view.show_transfer_info_panel(self._build_transfer_info_panel_payload(w, s))
        self._map_stack.addWidget(self.range_compare_tab)
        self._map_stack.setCurrentWidget(self.range_compare_tab)
        self.range_compare_tab.retranslate()
        return self.range_compare_tab

    def _ensure_single_weapon_view(self) -> SingleWeaponView:
        if self.single_weapon_view is not None:
            return self.single_weapon_view
        self.single_weapon_view = SingleWeaponView(
            self.db,
            self.tile_cache,
            lang_manager=self.lang_manager,
            settings=self.settings,
        )
        self.main_tabs.removeTab(self._single_weapon_tab_index)
        self.main_tabs.insertTab(
            self._single_weapon_tab_index,
            self.single_weapon_view,
            self._safe_tab_icon("detail.svg"),
            self.lang_manager.tr("Single Weapon View"),
        )
        return self.single_weapon_view

    def _ensure_simulator_view(self) -> SimulatorView:
        if self.simulator_view is not None:
            return self.simulator_view
        self.simulator_view = SimulatorView(
            self.db,
            self.tile_cache,
            lang_manager=self.lang_manager,
            settings=self.settings,
        )
        self.simulator_view.weapon_origin_changed.connect(self._handle_weapon_origin_change)
        self.simulator_view.open_main_map_requested.connect(self._show_weapon_on_main_map)
        self.data_grid.weapon_selected.connect(self.simulator_view.apply_weapon)
        self.dashboard.weapon_selected.connect(self.simulator_view.apply_weapon)
        self.favorites_dashboard.weapon_selected.connect(self.simulator_view.apply_weapon)
        self.swot_analysis.swot_text_changed.connect(self.simulator_view.apply_swot_editor_text)
        self.main_tabs.removeTab(self._simulator_tab_index)
        self.main_tabs.insertTab(
            self._simulator_tab_index,
            self.simulator_view,
            self._safe_tab_icon("map.svg"),
            self.lang_manager.tr("Simulator"),
        )
        return self.simulator_view

    def _safe_tab_icon(self, icon_filename: str) -> QIcon:
        icon_path = Path("resources") / "icons" / icon_filename
        if icon_path.exists():
            return QIcon(str(icon_path))
        return QIcon()

    def _setup_tabs_branding(self):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(8)
        self.tabs_brand_logo = QLabel()
        width, height = self._branding_logo_dimensions()
        self.tabs_brand_logo.setFixedSize(width, height)
        self.tabs_brand_logo.setScaledContents(True)
        self.tabs_brand_name = QLabel()
        self.tabs_brand_name.setStyleSheet("font-weight:700;")
        row.addWidget(self.tabs_brand_name)
        row.addWidget(self.tabs_brand_logo)
        self.main_tabs.setCornerWidget(container, Qt.Corner.TopRightCorner)
        self._refresh_tabs_branding()

    def _branding_logo_dimensions(self) -> tuple[int, int]:
        square = max(16, min(96, int(self.settings.value(self.BRAND_LOGO_SIZE_KEY, 24, int))))
        base_w = int(self.settings.value(self.BRAND_LOGO_WIDTH_KEY, square, int))
        base_h = int(self.settings.value(self.BRAND_LOGO_HEIGHT_KEY, square, int))
        scale_percent = max(10, min(300, int(self.settings.value(self.BRAND_LOGO_SCALE_PERCENT_KEY, 100, int))))
        width = max(16, min(512, int(base_w * (scale_percent / 100.0))))
        height = max(16, min(512, int(base_h * (scale_percent / 100.0))))
        return width, height

    def _refresh_tabs_branding(self):
        company = self.settings.value(
            self.BRAND_COMPANY_NAME_KEY, APP_CONFIG.get("organization", ""), str
        ).strip() or APP_CONFIG.get("organization", "")
        logo_path = self.settings.value(self.BRAND_LOGO_PATH_KEY, "", str).strip()
        self.tabs_brand_name.setText(company)
        logo_width, logo_height = self._branding_logo_dimensions()
        self.tabs_brand_logo.setFixedSize(logo_width, logo_height)
        logo_pix = QPixmap(logo_path) if logo_path else QPixmap()
        if logo_pix.isNull():
            self.tabs_brand_logo.setPixmap(QPixmap())
            self.tabs_brand_logo.setText("◉")
            self.tabs_brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.tabs_brand_logo.setText("")
            self.tabs_brand_logo.setPixmap(
                logo_pix.scaled(
                    self.tabs_brand_logo.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _setup_tab_navigation(self):
        """Use Tab/Shift+Tab to navigate main interfaces."""
        self.next_tab_shortcut = QShortcut(QKeySequence("Tab"), self)
        self.next_tab_shortcut.activated.connect(self._goto_next_tab)
        self.prev_tab_shortcut = QShortcut(QKeySequence("Shift+Tab"), self)
        self.prev_tab_shortcut.activated.connect(self._goto_prev_tab)

    def _goto_next_tab(self):
        idx = self.main_tabs.currentIndex()
        self.main_tabs.setCurrentIndex((idx + 1) % self.main_tabs.count())

    def _goto_prev_tab(self):
        idx = self.main_tabs.currentIndex()
        self.main_tabs.setCurrentIndex((idx - 1) % self.main_tabs.count())
    
    def _create_status_bar(self):
        """Create status bar with live information"""
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        
        # Status labels
        self.status_weapon_count = QLabel("0 weapons")
        self.status_filter = QLabel("No filters")
        self.status_cache = QLabel("Cache: 0MB")
        self.status_last_update = QLabel("Last sync: --")
        
        status_bar.addPermanentWidget(self.status_weapon_count)
        status_bar.addPermanentWidget(self.status_filter)
        status_bar.addPermanentWidget(self.status_cache)
        status_bar.addPermanentWidget(self.status_last_update)
        
        # Initial status
        status_bar.showMessage("Ready")
    
    def _connect_signals(self):
        """Connect component signals"""
        # Grid/Dashboard → Detail View
        self.data_grid.weapon_selected.connect(self.detail_view.load_weapon)
        self.dashboard.weapon_selected.connect(self.detail_view.load_weapon)
        self.dashboard.toggle_detail_pane_requested.connect(self._toggle_control_panel_detail_pane)
        self.data_grid.weapon_selected.connect(self._open_single_weapon_view)
        self.dashboard.weapon_open_requested.connect(self._open_single_weapon_view)
        self.favorites_dashboard.weapon_selected.connect(self.detail_view.load_weapon)
        self.favorites_dashboard.weapon_open_requested.connect(self._open_single_weapon_view)
        self.dashboard.favorites_changed.connect(self.favorites_dashboard.refresh)
        self.data_grid.weapon_selected.connect(self.swot_analysis.load_weapon)
        self.dashboard.weapon_selected.connect(self.swot_analysis.load_weapon)
        self.favorites_dashboard.weapon_selected.connect(self.swot_analysis.load_weapon)
        self.swot_analysis.weapon_selected.connect(self.detail_view.load_weapon)

        # 3D Viewer — load weapon when selected
        self.data_grid.weapon_selected.connect(self._weapon_3d_view.load_weapon)
        self.dashboard.weapon_selected.connect(self._weapon_3d_view.load_weapon)
        self.favorites_dashboard.weapon_selected.connect(self._weapon_3d_view.load_weapon)
        self.swot_analysis.weapon_selected.connect(self._weapon_3d_view.load_weapon)

        # 3D Viewer / 2D gallery — a primary image chosen there must reach cards & previews
        self._weapon_3d_view.primary_image_changed.connect(self._on_gallery_primary_changed)

        # Detail View → Map (lazy)
        self.detail_view.show_on_map_requested.connect(self._show_weapon_on_main_map)

        # Data changes → Status bar updates
        self.data_grid.data_changed.connect(self._schedule_status_counts_refresh)
        self.data_grid.data_changed.connect(self._refresh_reports_if_ready)
        
        # Cache updates → Status bar
        # (Would connect to tile_cache events in production)
    
    def _load_initial_data(self):
        """Load initial weapon data — defer heavy views for faster startup."""
        self._update_status_counts()
        self._update_cache_status()
        QTimer.singleShot(30, self._deferred_initial_hydration)

    def _deferred_initial_hydration(self):
        self.data_grid.load_weapons()
        self.dashboard.refresh()
        self.favorites_dashboard.refresh()

    def _schedule_main_refresh(self, include_reports: bool = True):
        if self._refresh_pending:
            return
        self._refresh_pending = True

        def _run():
            self._refresh_pending = False
            self.data_grid.refresh()
            self.dashboard.refresh()
            self.favorites_dashboard.refresh()
            if self.simulator_view is not None:
                self.simulator_view.refresh_catalog()
            if self.range_compare_tab is not None:
                self.range_compare_tab.refresh_catalog()
            self._schedule_status_counts_refresh()
            if include_reports:
                self._refresh_reports_if_ready()

        QTimer.singleShot(0, _run)

    def _on_gallery_primary_changed(self, weapon_id: int):
        """Debounced refresh after the 2D gallery changes a weapon's primary image."""
        self._schedule_main_refresh()
        weapon = self._weapon_3d_view.weapon
        if not weapon:
            return
        if self.single_weapon_view is not None:
            self.single_weapon_view.load_weapon(weapon)
        self.detail_view.load_weapon(weapon)

    def _schedule_status_counts_refresh(self):
        if self._status_refresh_pending:
            return
        self._status_refresh_pending = True

        def _run():
            self._status_refresh_pending = False
            self._update_status_counts()

        QTimer.singleShot(80, _run)
    
    def _update_status_counts(self):
        """Update status bar with current data counts"""
        count = self.db.get_weapon_count()
        self.status_weapon_count.setText(f"{count:,} weapons")
        self.status_filter.setText(self.data_grid.active_filters_text())
    
    def _update_cache_status(self):
        """Update status bar with cache statistics"""
        stats = self.tile_cache.get_cache_stats()
        self.status_cache.setText(f"Cache: {stats['total_size_mb']:.0f}MB")
    
    def _change_basemap(self, checked: bool):
        """Handle basemap switch from menu"""
        if not checked:
            return
        action = self.sender()
        basemap_name = action.data()
        mode = self.settings.value(MAP_TILE_MODE_KEY, DEFAULT_TILE_MODE, str)
        if mode == TILE_MODE_OFFLINE:
            info = self.tile_cache.get_basemap_cache_status().get(basemap_name, {})
            if int(info.get("tile_count", 0)) <= 0:
                QMessageBox.warning(
                    self,
                    self.lang_manager.tr("Map"),
                    self.lang_manager.tr(
                        "This basemap is not downloaded yet. "
                        "Download it from Settings → Map or switch to Online/Auto mode."
                    ),
                )
                return
        self.map_view.set_basemap(basemap_name)
        self.settings.setValue(MAP_BASEMAP_KEY, basemap_name)
    
    def _change_theme(self, checked: bool):
        """Handle theme switch from menu"""
        if not checked:
            return
        action = self.sender()
        theme_name = action.data()
        self.theme_manager.apply_theme(theme_name)
        self.settings.setValue('ui/theme', theme_name)
    
    def _show_add_weapon_dialog(self):
        """Show dialog to add new weapon"""
        dialog = AddWeaponDialog(self, self.db)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            weapon_data = dialog.get_weapon_data()
            new_weapon = self.db.add_weapon(weapon_data)
            if new_weapon:
                self._schedule_main_refresh(include_reports=True)
                QMessageBox.information(self, "Success", f"Added: {new_weapon.weapon_name}")
    
    def _edit_selected_weapon(self):
        """Edit currently selected weapon"""
        weapon = self.data_grid.get_selected_weapon()
        if not weapon:
            QMessageBox.warning(self, "No Selection", "Please select a weapon to edit")
            return
        
        dialog = AddWeaponDialog(self, self.db, weapon)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updates = dialog.get_weapon_data()
            updated = self.db.update_weapon(weapon['id'], updates)
            if updated:
                self._schedule_main_refresh(include_reports=True)
                self.detail_view.load_weapon(updated.id)
                self.weapon_updated.emit(updated.to_dict())
    
    def _delete_selected_weapon(self):
        """Delete currently selected weapon"""
        weapon = self.data_grid.get_selected_weapon()
        if not weapon:
            QMessageBox.warning(self, "No Selection", "Please select a weapon to delete")
            return
        
        confirm = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete '{weapon['weapon_name']}'?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            if self.db.delete_weapon(weapon['id']):
                self._schedule_main_refresh(include_reports=True)
                self.detail_view.clear()
    
    def _open_reports_workspace(self):
        """Switch to the Reports tab (preview + edit + export)."""
        workspace = self._ensure_report_workspace()
        workspace.reload_weapons()
        self.main_tabs.setCurrentWidget(workspace)

    def _toggle_control_panel_detail_pane(self):
        if not hasattr(self, "control_split"):
            return
        sizes = self.control_split.sizes()
        if len(sizes) < 2:
            return
        if sizes[1] > 0:
            self.control_split.setSizes([1, 0])
        else:
            self.control_split.setSizes([1, 1])

    def _show_export_dialog(self):
        """Quick spreadsheet-oriented export dialog."""
        dialog = ExportDialog(self, self.db)
        dialog.exec()
    
    def _show_settings(self):
        """Show settings menu dialog with immediate Apply support."""
        dialog = SettingsDialog(
            self, self.settings, self.theme_manager, self.lang_manager,
            db_manager=self.db, tile_cache=self.tile_cache,
        )
        dialog.settings_applied.connect(self._apply_runtime_settings)
        dialog.precache_requested.connect(self._on_precache_requested)
        dialog.world_precache_requested.connect(self._on_world_precache_requested)
        dialog.exec()

    def _on_precache_requested(self, basemaps: list):
        self._show_pre_cache_dialog(preselected_basemaps=basemaps)

    def _on_world_precache_requested(self):
        from views.pre_cache_dialog import BASEMAP_KEYS, WORLD_ZOOM_LEVELS

        reply = QMessageBox.question(
            self,
            self.lang_manager.tr("Download world overview"),
            self.lang_manager.tr(
                "Download all world map tiles for zoom levels 0–5\n"
                "for all four basemap types (Dark, Satellite, OSM, Topo)?\n\n"
                "Approximate size: 60–100 MB."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_precache_worker(
            {
                "mode": "world",
                "zooms": list(WORLD_ZOOM_LEVELS),
                "basemaps": list(BASEMAP_KEYS),
                "basemap": "dark",
                "lat": self._default_map_center()[0],
                "lon": self._default_map_center()[1],
                "radius": 0,
            }
        )

    def _run_precache_worker(self, config: dict):
        from views.pre_cache_worker import PreCacheWorker

        if getattr(self, "_precache_worker", None) is not None:
            QMessageBox.information(
                self,
                "ArmoryGIS",
                "يوجد تحميل للخريطة قيد التشغيل بالفعل.",
            )
            return

        title = "تحميل العالم (Z0–5)..." if config.get("mode") == "world" else "جاري تحميل بلاطات الخريطة..."
        progress = QProgressDialog(title, "إلغاء", 0, 100, self)
        progress.setWindowTitle("ArmoryGIS Pro")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()

        cancelled = {"value": False}
        progress.canceled.connect(lambda: cancelled.__setitem__("value", True))

        worker = PreCacheWorker(self.tile_cache, config, cancelled, parent=self)
        self._precache_worker = worker

        def cleanup_worker():
            if getattr(self, "_precache_worker", None) is worker:
                self._precache_worker = None
            worker.deleteLater()

        @pyqtSlot(int, str)
        def on_progress(pct, text):
            progress.setValue(max(0, min(100, pct)))
            progress.setLabelText(text)

        @pyqtSlot(dict)
        def on_finished(stats):
            progress.close()
            cleanup_worker()
            self._update_cache_status()
            if self.settings_panel is not None:
                self.settings_panel.refresh_cache_status()
            try:
                self.tile_cache.save_cache_index()
            except Exception:
                pass

            if stats.get("error"):
                QMessageBox.warning(
                    self,
                    "فشل التحميل",
                    f"تعذّر تحميل بلاطات الخريطة.\n\n{stats['error']}",
                )
                return

            downloaded = int(stats.get("downloaded", 0))
            failed = int(stats.get("failed", 0))
            skipped = int(stats.get("skipped", 0))
            total = int(stats.get("total", 0))
            if cancelled["value"]:
                QMessageBox.information(
                    self,
                    "تم الإلغاء",
                    f"توقّف التحميل.\n\n"
                    f"جديد: {downloaded}\n"
                    f"فشل: {failed}\n"
                    f"موجود مسبقاً: {skipped}\n"
                    f"المجموع: {total}",
                )
                return
            QMessageBox.information(
                self,
                "اكتمل التحميل",
                f"تم تخزين بلاطات الخريطة محلياً.\n\n"
                f"جديد: {downloaded}\n"
                f"فشل: {failed}\n"
                f"موجود مسبقاً: {skipped}\n"
                f"المجموع: {total}\n\n"
                f"المجلد:\n{self.tile_cache.cache_dir}",
            )

        worker.progress_update.connect(on_progress, Qt.ConnectionType.QueuedConnection)
        worker.finished_with_stats.connect(on_finished, Qt.ConnectionType.QueuedConnection)
        worker.start()

    def _open_single_weapon_view(self, weapon: dict):
        if not weapon:
            return
        view = self._ensure_single_weapon_view()
        view.load_weapon(weapon)
        self.main_tabs.setCurrentIndex(self._single_weapon_tab_index)
    
    def _show_pre_cache_dialog(self, preselected_basemaps=None):
        """Show dialog to pre-cache region for offline use."""
        from views.pre_cache_dialog import PreCacheDialog

        if getattr(self, "_precache_worker", None) is not None:
            QMessageBox.information(
                self,
                "ArmoryGIS",
                "يوجد تحميل للخريطة قيد التشغيل بالفعل.",
            )
            return

        dialog = PreCacheDialog(self, self.tile_cache)
        if preselected_basemaps:
            dialog.set_preselected_basemaps(preselected_basemaps)
        default_lat, default_lon = self._default_map_center()
        dialog.lat_spin.setValue(default_lat)
        dialog.lon_spin.setValue(default_lon)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._run_precache_worker(dialog.get_pre_cache_config())
    
    def _show_cache_stats(self):
        """Show detailed cache statistics"""
        stats = self.tile_cache.get_cache_stats()
        message = f"""Cache Statistics:
        
Total Tiles: {stats['total_tiles']:,}
Total Size: {stats['total_size_mb']:.2f} MB
Cache Directory: {stats['cache_dir']}

Basemaps:
"""
        for name, data in stats['basemaps'].items():
            message += f"  • {name}: {data['tile_count']:,} tiles ({data['size_mb']:.1f} MB)\n"
        
        QMessageBox.information(self, "Cache Statistics", message)
    
    def _cleanup_cache(self):
        """Cleanup old cache entries"""
        confirm = QMessageBox.question(
            self, "Cleanup Cache",
            f"Remove cache entries older than {TILE_CACHE_CONFIG['auto_cleanup_days']} days?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            deleted = self.tile_cache.cleanup_old_cache(TILE_CACHE_CONFIG['auto_cleanup_days'])
            self._update_cache_status()
            QMessageBox.information(self, "Cleanup Complete", f"Removed {deleted} old cache entries")
    
    def _handle_map_drop(self, weapon: dict, lat: float, lon: float):
        """Handle weapon dropped on map"""
        logger.info(f"Weapon dropped on map: {weapon['weapon_name']} at ({lat}, {lon})")
        self.map_weapon_dropped.emit(weapon, lat, lon)
        # Could trigger range ring drawing, analysis, etc.

    def _handle_weapon_origin_change(self, weapon: dict, lat: float, lon: float):
        """Persist dragged weapon origin point from map marker."""
        if not weapon or not weapon.get("id"):
            return
        updated = self.db.update_weapon(int(weapon["id"]), {"origin_lat": float(lat), "origin_lon": float(lon)})
        if not updated:
            return
        updated_dict = updated.to_dict(include_images=True, include_variants=False)
        self._schedule_main_refresh(include_reports=False)
        self.detail_view.load_weapon(updated_dict)
        if self.single_weapon_view is not None:
            self.single_weapon_view.load_weapon(updated_dict)
        if self.map_view is not None:
            self.map_view.set_active_weapon(updated_dict)
            if updated_dict.get("range_km"):
                self.map_view.draw_range_ring(
                    float(updated_dict.get("origin_lat") or lat),
                    float(updated_dict.get("origin_lon") or lon),
                    float(updated_dict.get("range_km") or 0),
                    updated_dict.get("weapon_name", "Weapon"),
                )
        self.statusBar().showMessage(
            f"Saved new location for {updated_dict.get('weapon_name', 'weapon')} "
            f"({float(lat):.4f}, {float(lon):.4f})",
            3500,
        )

    def _get_active_weapon_for_map_tools(self):
        """Resolve selected weapon from any active interface."""
        weapon = self.data_grid.get_selected_weapon()
        if weapon:
            return weapon
        weapon = getattr(self.dashboard, "_selected_weapon", None)
        if weapon:
            return weapon
        weapon = getattr(self.detail_view, "_current_weapon", None)
        if weapon:
            return weapon
        return getattr(self.single_weapon_view, "weapon", None) if self.single_weapon_view else None
    
    def _center_map_on_selection(self):
        """Open map tab and center on selected weapon."""
        weapon = self._get_active_weapon_for_map_tools()
        tab = self._ensure_range_compare_tab()
        self.main_tabs.setCurrentIndex(self._map_tab_index)
        if weapon and weapon.get("origin_lat") and weapon.get("origin_lon"):
            tab.map_view.center_on_coordinates(
                weapon["origin_lat"],
                weapon["origin_lon"],
                zoom=8,
            )
        else:
            tab._center_default()
    
    def _draw_range_ring(self):
        """Add selected weapon range ring on compare map."""
        weapon = self._get_active_weapon_for_map_tools()
        if not weapon or not weapon.get("range_km"):
            QMessageBox.information(
                self,
                self.lang_manager.tr("Map Tool"),
                self.lang_manager.tr("Select a weapon with valid range."),
            )
            return
        tab = self._ensure_range_compare_tab()
        tab.add_weapon(weapon)
        self.main_tabs.setCurrentIndex(self._map_tab_index)
    
    def _new_database(self):
        """Create new empty database"""
        confirm = QMessageBox.question(
            self, "New Database",
            "Create new empty database? Current data will not be saved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save New Database", "armory_new.db", "SQLite Database (*.db)"
            )
            if path:
                # Would initialize new database here
                QMessageBox.information(self, "New Database", f"Created: {path}")
    
    def _open_database(self):
        """Open existing database file"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Database", str(Path.home()), "SQLite Database (*.db)"
        )
        if path:
            # Would reconnect to new database here
            QMessageBox.information(self, "Database Opened", f"Loaded: {path}")
    
    def _show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            f"About {APP_CONFIG['app_name']}",
            f"""<h3>{APP_CONFIG['app_name']} v{APP_CONFIG['version']}</h3>
            <p>Weapons Database Management with Geospatial Intelligence</p>
            <p><b>Organization:</b> {APP_CONFIG['organization']}</p>
            <p><b>Python/PyQt6</b> • Offline Map Support • Multi-language</p>
            <p>© 2026 Defense Systems Architecture Team</p>"""
        )

    def _effective_range_km_for_sim_transfer(self, weapon: dict, sim: dict) -> float:
        """Range used when drawing simulator→main transfer. DB may omit/zero range_km while the sim UI uses defaults."""
        sim = sim if isinstance(sim, dict) else {}
        er = sim.get("effectiveRangeKm")
        if er is not None:
            try:
                v = float(er)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
        wk = weapon.get("range_km")
        if wk is not None:
            try:
                v = float(wk)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
        has_geometry = bool(
            (sim.get("launch") and sim.get("target"))
            or (isinstance(sim.get("path"), list) and len(sim.get("path") or []) >= 2)
            or sim.get("launch")
        )
        if has_geometry:
            return 100.0
        return 0.0

    def _format_coord_pair_text(self, lat, lon) -> str:
        try:
            if lat is None or lon is None:
                return "—"
            return f"{float(lat):.6f}, {float(lon):.6f}"
        except (TypeError, ValueError):
            return "—"

    def _transfer_panel_field_text(self, value) -> str:
        if value is None:
            return "—"
        text = str(value).strip()
        if not text:
            return "—"
        if self.lang_manager.is_arabic():
            return str(self.lang_manager.tr_data(text))
        return text

    def _build_transfer_info_panel_payload(self, weapon: dict, sim: dict) -> dict:
        lm = self.lang_manager
        title = lm.tr("Transfer scenario")

        wname = weapon.get("weapon_name") or "—"
        model = weapon.get("model") or "—"
        weapon_model_line = f"{wname} · {model}"

        country = self._transfer_panel_field_text(weapon.get("country"))

        guidance_raw = weapon.get("guidance")
        guidance_s = self._transfer_panel_field_text(guidance_raw)

        def _join_nonempty_parts_localized(*parts):
            out = []
            for p in parts:
                t = self._transfer_panel_field_text(p)
                if t != "—":
                    out.append(t)
            return " · ".join(out) if out else "—"

        target_types_val = _join_nonempty_parts_localized(weapon.get("category"), weapon.get("warhead_type"))

        delivery_raw = weapon.get("platform") or weapon.get("propulsion")
        delivery_s = self._transfer_panel_field_text(delivery_raw)

        launch = sim.get("launch") if isinstance(sim.get("launch"), dict) else None
        target = sim.get("target") if isinstance(sim.get("target"), dict) else None

        if launch and launch.get("lat") is not None and launch.get("lon") is not None:
            weapon_coords = self._format_coord_pair_text(launch.get("lat"), launch.get("lon"))
        else:
            weapon_coords = self._format_coord_pair_text(weapon.get("origin_lat"), weapon.get("origin_lon"))

        target_coords = "—"
        if target and target.get("lat") is not None and target.get("lon") is not None:
            target_coords = self._format_coord_pair_text(target.get("lat"), target.get("lon"))

        measured = "—"
        meas = sim.get("measure")
        if isinstance(meas, list) and len(meas) >= 2:
            a, b = meas[0], meas[1]
            try:
                la = float(a.get("lat"))
                lo_a = float(a.get("lng"))
                lb = float(b.get("lat"))
                lo_b = float(b.get("lng"))
                dkm = haversine_km(la, lo_a, lb, lo_b)
                measured = f"{dkm:.2f} km"
            except (TypeError, ValueError):
                pass

        azimuth = "—"
        rev_lat = None
        rev_lon = None
        if (
            launch
            and target
            and launch.get("lat") is not None
            and launch.get("lon") is not None
            and target.get("lat") is not None
            and target.get("lon") is not None
        ):
            try:
                az = initial_bearing_deg(
                    float(launch["lat"]),
                    float(launch["lon"]),
                    float(target["lat"]),
                    float(target["lon"]),
                )
                azimuth = f"{az:.1f}°"
                rev_lat = float(target["lat"])
                rev_lon = float(target["lon"])
            except (TypeError, ValueError):
                pass

        fp = str(sim.get("flightProfile") or "").strip().lower()
        ar = str(sim.get("arcStyle") or "").strip().lower()
        fp_labels = {"low": lm.tr("Low (faster TOF)"), "high": lm.tr("High (slower)")}
        ar_labels = {
            "ballistic": lm.tr("Ballistic"),
            "cruise": lm.tr("Cruise"),
            "direct": lm.tr("Direct"),
        }
        fp_disp = fp_labels.get(fp, fp or "—")
        ar_disp = ar_labels.get(ar, ar.title() if ar else "—")
        launch_profile = f"{fp_disp} · {ar_disp}"

        rows = [
            {"label": lm.tr("Weapon & model"), "value": weapon_model_line},
            {"label": lm.tr("Country"), "value": country},
            {"label": lm.tr("Guidance type"), "value": guidance_s},
            {"label": lm.tr("Target types"), "value": target_types_val},
            {"label": lm.tr("Delivery method"), "value": delivery_s},
            {"label": lm.tr("Weapon coordinates"), "value": weapon_coords},
            {"label": lm.tr("Target coordinates"), "value": target_coords},
            {"label": lm.tr("Measured distance"), "value": measured},
            {"label": lm.tr("Azimuth"), "value": azimuth},
            {"label": lm.tr("Launch profile"), "value": launch_profile},
            {"label": lm.tr("Target location name"), "value": "…", "isTargetName": True},
        ]

        payload = {
            "title": title,
            "rows": rows,
            "reverseGeocode": None,
        }
        if rev_lat is not None and rev_lon is not None:
            payload["reverseGeocode"] = {"lat": rev_lat, "lon": rev_lon}
        return payload

    def _main_map_embed_locale(self) -> dict:
        lm = self.lang_manager
        return {
            "rtl": bool(lm.is_arabic()),
            "legendTitle": lm.tr("Legend"),
            "legLaunch": lm.tr("Launch / range"),
            "legTarget": lm.tr("Target"),
            "legPath": lm.tr("Path"),
            "legDefense": lm.tr("Defense"),
            "legMeasure": lm.tr("Measure"),
            "copyCoords": lm.tr("Copy coordinates"),
            "nominatimLang": "ar" if lm.is_arabic() else "en",
        }

    def _show_weapon_on_main_map(self, payload):
        if not payload:
            return
        self._ensure_range_compare_tab()
        if isinstance(payload, dict) and payload.get("weapon") is not None:
            weapon = payload["weapon"]
            sim = payload.get("sim") or {}
        else:
            weapon = payload
            sim = {}
        if not weapon:
            return

        basemap_key = sim.get("basemap") if isinstance(sim, dict) else None
        if basemap_key:
            mapped = {"dark": "dark", "osm": "osm", "sat": "satellite"}.get(str(basemap_key), str(basemap_key))
            self.map_view.set_basemap(mapped)

        self.map_view.set_active_weapon(weapon)
        name = weapon.get("weapon_name", "Weapon")
        rk = self._effective_range_km_for_sim_transfer(weapon, sim if isinstance(sim, dict) else {})

        launch = sim.get("launch") if isinstance(sim, dict) else None
        target = sim.get("target") if isinstance(sim, dict) else None
        mv = sim.get("mapView") if isinstance(sim, dict) else None

        if (
            launch
            and target
            and isinstance(launch, dict)
            and isinstance(target, dict)
            and rk > 0
            and launch.get("lat") is not None
            and launch.get("lon") is not None
            and target.get("lat") is not None
            and target.get("lon") is not None
        ):
            lat0 = float(launch["lat"])
            lon0 = float(launch["lon"])
            lat1 = float(target["lat"])
            lon1 = float(target["lon"])
            min_km = 0.01 if rk > 0.02 else 0.0
            self.map_view.draw_weapon_effects(lat0, lon0, min_km, rk, 0.0, name, lat1, lon1)
            path = sim.get("path") if isinstance(sim, dict) else None
            if path and isinstance(path, list) and len(path) >= 2:
                self.map_view.append_simulator_trajectory(path)
            defc = sim.get("defense") if isinstance(sim, dict) else None
            if defc and isinstance(defc, dict) and defc.get("lat") is not None and defc.get("lon") is not None:
                self.map_view.append_defense_circle(
                    float(defc["lat"]),
                    float(defc["lon"]),
                    float(defc.get("radiusM") or 55000),
                )
            if mv and mv.get("lat") is not None and mv.get("lng") is not None:
                z = int(mv.get("zoom") or 8)
                self.map_view.center_on_coordinates(float(mv["lat"]), float(mv["lng"]), zoom=z)
            else:
                self.map_view.center_on_coordinates(lat0, lon0, zoom=8)
        elif (
            rk > 0
            and launch
            and isinstance(launch, dict)
            and launch.get("lat") is not None
            and launch.get("lon") is not None
        ):
            lat0 = float(launch["lat"])
            lon0 = float(launch["lon"])
            self.map_view.draw_range_ring(lat=lat0, lon=lon0, range_km=rk, weapon_name=name)
            if mv and mv.get("lat") is not None and mv.get("lng") is not None:
                self.map_view.center_on_coordinates(float(mv["lat"]), float(mv["lng"]), int(mv.get("zoom") or 8))
            else:
                self.map_view.center_on_coordinates(lat0, lon0, zoom=8)
        elif rk > 0 and weapon.get("origin_lat") is not None and weapon.get("origin_lon") is not None:
            self.map_view.center_on_weapon(weapon)
            self.map_view.draw_range_ring(
                lat=weapon["origin_lat"],
                lon=weapon["origin_lon"],
                range_km=rk,
                weapon_name=name,
            )
            if mv and mv.get("lat") is not None and mv.get("lng") is not None:
                self.map_view.center_on_coordinates(float(mv["lat"]), float(mv["lng"]), int(mv.get("zoom") or 8))
        else:
            self.map_view.center_on_weapon(weapon)

        meas = sim.get("measure") if isinstance(sim, dict) else None
        if meas and isinstance(meas, list) and len(meas) >= 2:
            self.map_view.append_simulator_measure(meas)

        sim_for_legend = sim if isinstance(sim, dict) else {}
        if sim_for_legend:
            self._last_main_map_transfer = (copy.deepcopy(weapon), copy.deepcopy(sim_for_legend))
            self.map_view.update_sim_transfer_legend(sim_for_legend)
            self.map_view.show_transfer_info_panel(self._build_transfer_info_panel_payload(weapon, sim_for_legend))
        else:
            self._last_main_map_transfer = None
            self.map_view.update_sim_transfer_legend(None)
            self.map_view.hide_transfer_info_panel()

        self.main_tabs.setCurrentIndex(self._map_tab_index)

    def _zoom_main_map_in(self):
        if self.map_view is not None:
            self.map_view.zoom_in()
        else:
            self._ensure_range_compare_tab().map_view.zoom_in()

    def _zoom_main_map_out(self):
        if self.map_view is not None:
            self.map_view.zoom_out()
        else:
            self._ensure_range_compare_tab().map_view.zoom_out()

    def _on_map_range_azimuth_toggled(self, checked: bool):
        if self.map_view is not None:
            self.map_view.set_range_ring_azimuth_enabled(bool(checked))

    def _export_main_map_png(self):
        tab = self._ensure_range_compare_tab()
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.lang_manager.tr("Export map as PNG"),
            "",
            self.lang_manager.tr("PNG images (*.png);;All files (*.*)"),
        )
        if not path:
            return
        pix = tab.map_view.grab()
        if not pix.save(path, "PNG"):
            QMessageBox.warning(
                self,
                self.lang_manager.tr("Export failed"),
                self.lang_manager.tr("Could not save the map image."),
            )

    def _apply_map_settings(self):
        mode = self.settings.value(MAP_TILE_MODE_KEY, DEFAULT_TILE_MODE, str)
        basemap = self.settings.value(MAP_BASEMAP_KEY, DEFAULT_BASEMAP, str)
        if hasattr(self, "map_view") and self.map_view is not None:
            self.map_view.set_tile_mode(mode)
            self.map_view.reload_basemap(basemap)
            lat, lon = self._default_map_center()
            self.map_view.center_on_coordinates(lat, lon)

    def _apply_runtime_settings(self):
        saved_lang = self.settings.value('language', LANGUAGE_CONFIG['default_language'], str)
        self.lang_manager.load_language(saved_lang)
        self.data_grid.set_language_manager(self.lang_manager)
        self.dashboard.set_language_manager(self.lang_manager)
        self.favorites_dashboard.set_language_manager(self.lang_manager)
        self.swot_analysis.set_language_manager(self.lang_manager)
        if self.simulator_view is not None:
            self.simulator_view.set_language_manager(self.lang_manager)
        self.detail_view.set_language_manager(self.lang_manager)
        if self.single_weapon_view is not None:
            self.single_weapon_view.set_language_manager(self.lang_manager)
        if self.range_compare_tab is not None:
            self.range_compare_tab.retranslate()
        if self.report_workspace is not None:
            self.report_workspace.set_language_manager(self.lang_manager)
        if self.settings_panel is not None:
            self.settings_panel.set_language_manager(self.lang_manager)
        self._apply_map_settings()
        lat, lon = self._default_map_center()
        if self.report_workspace is not None and hasattr(self.report_workspace, "set_default_center"):
            self.report_workspace.set_default_center(lat, lon)
        self._refresh_tabs_branding()
        self._retranslate_ui()

    def _refresh_reports_if_ready(self):
        if self.report_workspace is not None:
            self.report_workspace.reload_weapons()

    def _default_map_center(self) -> tuple[float, float]:
        cfg_lat, cfg_lon = APP_CONFIG.get("default_center", (31.5, 34.8))
        lat = float(self.settings.value("map/default_lat", cfg_lat, float))
        lon = float(self.settings.value("map/default_lon", cfg_lon, float))
        return lat, lon

    def _retranslate_ui(self):
        self._menu_file.setTitle(self.lang_manager.tr("File"))
        self._menu_edit.setTitle(self.lang_manager.tr("Edit"))
        self._menu_view.setTitle(self.lang_manager.tr("View"))
        self._menu_tools.setTitle(self.lang_manager.tr("Tools"))
        self._menu_settings.setTitle(self.lang_manager.tr("Settings"))
        self._menu_help.setTitle(self.lang_manager.tr("Help"))
        self.main_tabs.setTabText(0, self.lang_manager.tr("Data Grid"))
        self.main_tabs.setTabText(1, self.lang_manager.tr("Map"))
        self.main_tabs.setTabText(2, self.lang_manager.tr("Single Weapon View"))
        self.main_tabs.setTabText(3, self.lang_manager.tr("Control Panel"))
        self.main_tabs.setTabText(4, self.lang_manager.tr("Favorites"))
        self.main_tabs.setTabText(5, self.lang_manager.tr("SWOT Analysis"))
        self.main_tabs.setTabText(6, self.lang_manager.tr("Simulator"))
        self.main_tabs.setTabText(7, self.lang_manager.tr("3D Viewer"))
        self.main_tabs.setTabText(8, self.lang_manager.tr("Reports"))
        self.main_tabs.setTabText(9, self.lang_manager.tr("Settings"))
        self._zoom_in_action.setText(self.lang_manager.tr("Zoom +"))
        self._zoom_out_action.setText(self.lang_manager.tr("Zoom -"))
        self._add_action.setText(self.lang_manager.tr("Add"))
        self._edit_action.setText(self.lang_manager.tr("Edit"))
        self._delete_action.setText(self.lang_manager.tr("Delete"))
        self._export_action.setText(self.lang_manager.tr("Reports workspace"))
        self._quick_export_action.setText(self.lang_manager.tr("Spreadsheet export (dialog)…"))
        if self.settings_panel is not None:
            self.settings_panel.retranslate_ui()
        if self.map_view is not None:
            self.map_view.apply_main_map_locale(self._main_map_embed_locale())
            if self._last_main_map_transfer:
                w, s = self._last_main_map_transfer
                self.map_view.show_transfer_info_panel(self._build_transfer_info_panel_payload(w, s))

    def closeEvent(self, event):
        """Handle application close"""
        self._save_geometry()
        self.tile_cache.save_cache_index()
        event.accept()

    def save_window_state(self):
        """Used by application shutdown to persist geometry/settings."""
        self._save_geometry()