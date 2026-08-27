#!/usr/bin/env python3
"""
ArmoryGIS Pro — Weapons Database Management Desktop Application
Main entry point with offline map tile caching initialization
"""
import sys
import os
import logging
import signal
import shutil
import sqlite3
from pathlib import Path
from typing import Optional
from sqlalchemy import text

from PyQt6.QtWidgets import (
    QApplication, QSplashScreen, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QLocale, QTranslator, QSettings, QTimer
from PyQt6.QtGui import QPixmap, QFont, QIcon

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    APP_CONFIG, TILE_CACHE_CONFIG, THEME_CONFIG, 
    LANGUAGE_CONFIG, PROJECT_ROOT, APP_DATA_DIR
)
from database.db_manager import DatabaseManager, init_database
from views.main_window import MainWindow
from utils.theme_manager import ThemeManager
from utils.language_manager import LanguageManager
from utils.tile_cache import TileCacheManager

# Configure logging
def setup_logging() -> logging.Logger:
    """Configure application logging"""
    from config import get_log_path
    
    log_file = get_log_path()
    
    logging.basicConfig(
        level=getattr(logging, APP_CONFIG['log_level'].upper()),
        format='%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d: %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8', mode='a')],
    )
    if sys.stdout is not None and hasattr(sys.stdout, 'write'):
        logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    
    logger = logging.getLogger('armorygis')
    logger.info(f"ArmoryGIS Pro v{APP_CONFIG['version']} starting...")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Debug mode: {APP_CONFIG['debug']}")
    
    return logger

logger = setup_logging()

def _sqlite_weapon_count(db_path: Path) -> int:
    """Best-effort count of weapons in a SQLite file."""
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM weapons").fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def migrate_legacy_database_if_needed() -> Optional[str]:
    """
    One-time migration from legacy default DB file to the new local DB file.
    """
    db_url = APP_CONFIG.get("database_url", "")
    if not isinstance(db_url, str) or not db_url.startswith("sqlite:///"):
        return None

    target_db = Path(db_url.replace("sqlite:///", "", 1))
    legacy_db = APP_DATA_DIR / "armory.db"

    if not legacy_db.exists() or legacy_db.resolve() == target_db.resolve():
        return None

    try:
        target_db.parent.mkdir(parents=True, exist_ok=True)
        legacy_count = _sqlite_weapon_count(legacy_db)
        target_exists = target_db.exists()
        target_count = _sqlite_weapon_count(target_db) if target_exists else 0

        if not target_exists and legacy_count > 0:
            shutil.copy2(legacy_db, target_db)
            logger.info(
                "Migrated legacy database to local DB: %s -> %s",
                legacy_db,
                target_db,
            )
            return (
                "Database migration completed.\n\n"
                f"Copied existing data from:\n{legacy_db}\n\n"
                f"To new local database:\n{target_db}"
            )

        # If target is present but still empty, use legacy DB once.
        if target_exists and target_count == 0 and legacy_count > 0:
            backup = target_db.with_suffix(target_db.suffix + ".pre-migration.bak")
            shutil.copy2(target_db, backup)
            shutil.copy2(legacy_db, target_db)
            logger.info(
                "Replaced empty local DB from legacy DB and created backup: %s",
                backup,
            )
            return (
                "Database migration completed.\n\n"
                f"Restored local database from legacy data:\n{legacy_db}\n\n"
                f"Previous empty target was backed up to:\n{backup}"
            )
    except Exception as e:
        logger.warning(f"Legacy DB migration skipped due to error: {e}")
    return None


def log_database_startup_summary(db_manager: DatabaseManager) -> None:
    """Log active DB location plus key table counts for persistence checks."""
    db_url = db_manager.database_url
    db_path = db_url
    if db_url.startswith("sqlite:///"):
        db_path = str(Path(db_url.replace("sqlite:///", "", 1)).resolve(strict=False))
    elif db_url.startswith("sqlite://"):
        db_path = db_url.replace("sqlite://", "", 1)

    try:
        with db_manager.get_session() as session:
            weapons_count = session.execute(text("SELECT COUNT(*) FROM weapons")).scalar() or 0
            images_count = session.execute(text("SELECT COUNT(*) FROM weapon_images")).scalar() or 0
        logger.info(f"Database file/path: {db_path}")
        logger.info(f"Persistence check - weapons: {int(weapons_count)}, weapon_images: {int(images_count)}")
    except Exception as e:
        logger.warning(f"Persistence startup check failed: {e}")


def init_offline_map_cache(embedded: bool = False) -> TileCacheManager:
    """Initialize local tile cache for offline map operations"""
    logger.info("Initializing offline map tile cache...")

    cache_dir = os.getenv("ARMORYGIS_CACHE_DIR", TILE_CACHE_CONFIG["cache_dir"])
    
    cache_manager = TileCacheManager(
        cache_dir=cache_dir,
        max_cache_size_gb=TILE_CACHE_CONFIG['max_cache_size_gb'],
        basemaps=list(TILE_CACHE_CONFIG['basemaps'].keys()),
        user_agent=TILE_CACHE_CONFIG['user_agent']
    )
    
    # Pre-cache default region if cache is empty and enabled (skip in embedded mode)
    if (
        not embedded
        and TILE_CACHE_CONFIG['pre_cache_default']
        and not cache_manager.has_cached_tiles()
    ):
        logger.info("Pre-caching default region tiles for offline use...")
        
        # Show progress dialog (non-blocking)
        progress = QProgressDialog("Pre-caching map tiles for offline use...", "Cancel", 0, 100)
        progress.setWindowTitle("ArmoryGIS Pro")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(1000)  # Show after 1 second
        progress.setAutoClose(True)
        progress.show()
        
        config = TILE_CACHE_CONFIG['pre_cache_config']
        
        try:
            cache_manager.pre_cache_region(
                center_lat=config['center_lat'],
                center_lon=config['center_lon'],
                zoom_levels=config['zoom_levels'],
                radius_km=config['radius_km'],
                basemap=config['default_basemap'],
            )
            logger.info("Pre-caching complete")
        except Exception as e:
            logger.warning(f"Pre-caching failed: {e}")
        finally:
            progress.close()
    
    # Auto-cleanup old cache if enabled (deferred — never block startup)
    if TILE_CACHE_CONFIG['cleanup_on_startup'] and hasattr(cache_manager, 'cleanup_old_cache'):
        def _deferred_cleanup():
            try:
                deleted = cache_manager.cleanup_old_cache(
                    max_age_days=TILE_CACHE_CONFIG['auto_cleanup_days']
                )
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old cache entries")
            except Exception as e:
                logger.warning(f"Cache cleanup failed: {e}")

        QTimer.singleShot(8000, _deferred_cleanup)
    
    return cache_manager


def handle_sigint(signum, frame):
    """Handle Ctrl+C gracefully"""
    logger.info("Received SIGINT, shutting down...")
    QApplication.quit()


def _publish_embed_handle(window) -> None:
    """Publish HWND for C# Win32ProcessEmbedHost (ORBAT-compatible markers)."""
    try:
        window.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        QApplication.processEvents()
        wid = int(window.winId())
        print(f"ARMORYGIS_EMBED_HWND={wid}", flush=True)
        print(f"ORBAT_EMBED_HWND={wid}", flush=True)
        for name in ("_armorygis_embed_hwnd.txt", "_orbat_embed_hwnd.txt"):
            marker = PROJECT_ROOT / name
            marker.write_text(str(wid), encoding="utf-8")
    except Exception as exc:
        print(f"ARMORYGIS_EMBED_HWND_ERROR={exc}", file=sys.stderr, flush=True)


def _setup_qt_app() -> QApplication:
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    if hasattr(Qt.ApplicationAttribute, "EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.EnableHighDpiScaling)
    if hasattr(Qt.ApplicationAttribute, "UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.UseHighDpiPixmaps)

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName(APP_CONFIG['app_name'])
    app.setApplicationVersion(APP_CONFIG['version'])
    app.setOrganizationName(APP_CONFIG['organization'])
    icon_path = PROJECT_ROOT / 'resources' / 'icons' / 'app_icon.png'
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def run_app(skip_login: bool = False, embedded: bool = False, username: str = "analyst") -> int:
    """Application entry point — supports C# embed via embed_launcher.py."""
    from utils.runtime_profile import activate_embedded_profile, effective_language, effective_theme

    if embedded:
        activate_embedded_profile()
        skip_login = True
        os.environ.setdefault("ARMORYGIS_EMBEDDED", "1")

    signal.signal(signal.SIGINT, handle_sigint)
    app = _setup_qt_app()

    splash = None
    if not embedded:
        splash_path = PROJECT_ROOT / 'resources' / 'icons' / 'splash.png'
        if splash_path.exists():
            splash_pixmap = QPixmap(str(splash_path))
            splash = QSplashScreen(splash_pixmap, Qt.WindowType.WindowStaysOnTopHint)
            splash.showMessage(
                f"Initializing {APP_CONFIG['app_name']} v{APP_CONFIG['version']}...",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                Qt.GlobalColor.white,
            )
            splash.show()
            app.processEvents()

    try:
        settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            APP_CONFIG['organization'],
            APP_CONFIG['app_name'],
        )

        if not settings.contains('language'):
            settings.setValue('language', LANGUAGE_CONFIG['default_language'])
        if not settings.contains('ui/theme'):
            settings.setValue('ui/theme', THEME_CONFIG['default_theme'])
        if not settings.contains('map/tile_mode'):
            from utils.map_settings import DEFAULT_TILE_MODE, MAP_TILE_MODE_KEY
            settings.setValue(MAP_TILE_MODE_KEY, DEFAULT_TILE_MODE)
        # Always use locally cached map tiles (offline) — user deploys with full tile cache.
        from utils.map_settings import MAP_TILE_MODE_KEY, TILE_MODE_OFFLINE
        settings.setValue(MAP_TILE_MODE_KEY, TILE_MODE_OFFLINE)

        if splash:
            splash.showMessage(
                "Connecting to database...",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                Qt.GlobalColor.white,
            )
            app.processEvents()

        migration_notice = migrate_legacy_database_if_needed()
        logger.info(f"Database URL: {APP_CONFIG['database_url']}")
        db_manager = DatabaseManager(APP_CONFIG['database_url'])
        init_database(db_manager.engine)
        db_manager.init_tables()
        logger.info("Database initialized")
        log_database_startup_summary(db_manager)

        if splash:
            splash.showMessage(
                "Initializing offline map cache...",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                Qt.GlobalColor.white,
            )
            app.processEvents()

        tile_cache = init_offline_map_cache(embedded=embedded)
        logger.info(f"Tile cache ready: {tile_cache.cache_dir}")

        theme_manager = ThemeManager(app)
        saved_theme = settings.value('ui/theme', THEME_CONFIG['default_theme'], str)
        saved_theme = effective_theme(saved_theme)
        if saved_theme not in {'dark', 'cyber_neon', 'light', 'orange_black'}:
            saved_theme = THEME_CONFIG['default_theme']
        if saved_theme == 'orange_black':
            saved_theme = 'dark'
            settings.setValue('ui/theme', saved_theme)
        theme_manager.apply_theme(saved_theme)
        from utils.ui_helpers import apply_app_typography
        font_size = int(settings.value('ui/font_size', 10))
        apply_app_typography(app, bold=True, point_size=font_size)
        logger.info(f"Theme applied: {saved_theme}")

        lang_manager = LanguageManager(app)
        saved_lang = settings.value('language', LANGUAGE_CONFIG['default_language'], str)
        lang_manager.load_language(effective_language(saved_lang))
        logger.info(f"Language loaded: {saved_lang}")

        if splash:
            splash.showMessage(
                "Loading main interface...",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                Qt.GlobalColor.white,
            )
            app.processEvents()

        main_window = MainWindow(
            db_manager=db_manager,
            tile_cache=tile_cache,
            theme_manager=theme_manager,
            lang_manager=lang_manager,
            settings=settings,
            embedded=embedded,
            username=username,
        )
        if embedded:
            main_window.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            main_window.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
            embed_w = int(os.environ.get("ORBAT_EMBED_WIDTH", "0") or "0")
            embed_h = int(os.environ.get("ORBAT_EMBED_HEIGHT", "0") or "0")
            if embed_w > 100 and embed_h > 100:
                main_window.resize(embed_w, embed_h)

        main_window.show()
        QApplication.processEvents()

        if embedded:
            main_window.embedded_warmup()
            _publish_embed_handle(main_window)
        elif migration_notice:
            QMessageBox.information(main_window, "Database Migration", migration_notice)

        if splash:
            splash.finish(main_window)
            splash.deleteLater()

        def update_cache_status():
            if hasattr(main_window, 'status_cache'):
                stats = tile_cache.get_cache_stats()
                main_window.status_cache.setText(f"Cache: {stats['total_size_mb']:.0f}MB")

        cache_timer = QTimer()
        cache_timer.timeout.connect(update_cache_status)
        cache_timer.start(30000)

        logger.info("Application event loop starting")
        exit_code = app.exec()

        logger.info("Shutting down, saving state...")
        tile_cache.save_cache_index()
        main_window.save_window_state()
        return exit_code

    except Exception as e:
        logger.critical(f"Application startup failed: {e}", exc_info=True)
        if splash:
            splash.close()
        if embedded:
            print(f"Startup Error: {e}", file=sys.stderr, flush=True)
            return 1
        QMessageBox.critical(
            None,
            "Startup Error",
            f"{APP_CONFIG['app_name']} failed to start:\n\n{str(e)}\n\nCheck {APP_CONFIG['log_file']} for details.",
        )
        return 1


def main() -> int:
    return run_app(skip_login=False, embedded=False)


if __name__ == '__main__':
    sys.exit(main())