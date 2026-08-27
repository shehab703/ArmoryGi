"""
ArmoryGIS Pro — Centralized Configuration
Global settings for database, caching, UI, and application behavior
"""
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Application Data Directory
APP_DATA_DIR: Path = Path(os.getenv('ARMORYGIS_DATA_DIR', Path.home() / '.armorygis'))
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Application Metadata
APP_CONFIG: Dict[str, Any] = {
    'app_name': 'ArmoryGIS Pro',
    'version': '1.0.0',
    'organization': 'Defense Systems Architecture',
    'copyright': '© 2026 Defense Systems Architecture Team',
    
    # Debug/Logging
    'debug': os.getenv('ARMORYGIS_DEBUG', 'false').lower() == 'true',
    'log_level': os.getenv('ARMORYGIS_LOG_LEVEL', 'INFO'),
    'log_file': os.getenv('ARMORYGIS_LOG_FILE', 'armorygis.log'),
    
    # Database Configuration
    'database_url': os.getenv(
        'ARMORYGIS_DB_URL',
        f"sqlite:///{APP_DATA_DIR / 'armory_local.db'}"
    ),
    'db_pool_size': int(os.getenv('ARMORYGIS_DB_POOL', '5')),
    'db_max_overflow': int(os.getenv('ARMORYGIS_DB_OVERFLOW', '10')),
    'db_echo': os.getenv('ARMORYGIS_DB_ECHO', 'false').lower() == 'true',
    
    # Default Map Settings
    'default_basemap': os.getenv('ARMORYGIS_DEFAULT_BASEMAP', 'dark'),
    'default_zoom': int(os.getenv('ARMORYGIS_DEFAULT_ZOOM', '6')),
    'default_center': (
        float(os.getenv('ARMORYGIS_DEFAULT_LAT', '31.5')),
        float(os.getenv('ARMORYGIS_DEFAULT_LON', '34.8'))
    ),
    
    # Export Defaults
    'export_include_images': os.getenv('ARMORYGIS_EXPORT_IMAGES', 'true').lower() == 'true',
    'export_include_map': os.getenv('ARMORYGIS_EXPORT_MAP', 'true').lower() == 'true',
    'export_default_format': os.getenv('ARMORYGIS_EXPORT_FORMAT', 'xlsx'),
    
    # UI Settings
    'icon_size': (24, 24),
    'thumbnail_size': (80, 60),
    'card_size': (220, 100),
    'animation_enabled': os.getenv('ARMORYGIS_ANIMATIONS', 'true').lower() == 'true',
}

# Tile Cache Configuration (OFFLINE MAP SUPPORT)
TILE_CACHE_CONFIG: Dict[str, Any] = {
    # Cache directory location
    'cache_dir': os.getenv(
        'ARMORYGIS_CACHE_DIR',
        str(Path.home() / '.armorygis' / 'tile_cache')
    ),
    
    # Maximum cache size before LRU eviction (in GB)
    'max_cache_size_gb': float(os.getenv('ARMORYGIS_CACHE_MAX_GB', '5.0')),
    
    # Supported basemaps with tile URL templates
    'basemaps': {
        'dark': {
            'url': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
            'attribution': '&copy; <a href="https://carto.com/">CARTO</a>',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c'],
        },
        'satellite': {
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            'attribution': 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
            'max_zoom': 19,
            'subdomains': [''],
        },
        'osm': {
            'url': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            'attribution': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c'],
        },
        'topo': {
            'url': 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
            'attribution': 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, <a href="https://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>',
            'max_zoom': 17,
            'subdomains': ['a', 'b', 'c'],
        },
    },
    
    # Pre-cache settings for offline deployment
    'pre_cache_default': os.getenv('ARMORYGIS_PRECACHE_DEFAULT', 'false').lower() == 'true',
    'pre_cache_config': {
        'center_lat': float(os.getenv('ARMORYGIS_PRECACHE_LAT', '31.5')),
        'center_lon': float(os.getenv('ARMORYGIS_PRECACHE_LON', '34.8')),
        'radius_km': float(os.getenv('ARMORYGIS_PRECACHE_RADIUS', '1500')),
        'zoom_levels': [int(z) for z in os.getenv('ARMORYGIS_PRECACHE_ZOOMS', '6,7,8,9,10').split(',')],
        'default_basemap': os.getenv('ARMORYGIS_PRECACHE_BASEMAP', 'dark'),
    },
    
    # Retina/HiDPI display support
    'retina': os.getenv('ARMORYGIS_RETINA', 'false').lower() == 'true',
    
    # Cache cleanup policy
    'auto_cleanup_days': int(os.getenv('ARMORYGIS_CACHE_CLEANUP_DAYS', '90')),
    'cleanup_on_startup': os.getenv('ARMORYGIS_CLEANUP_STARTUP', 'false').lower() == 'true',
    
    # HTTP request settings for tile downloads
    'request_timeout': int(os.getenv('ARMORYGIS_REQUEST_TIMEOUT', '30')),
    'max_retries': int(os.getenv('ARMORYGIS_MAX_RETRIES', '3')),
    'user_agent': os.getenv('ARMORYGIS_USER_AGENT', 'ArmoryGIS/1.0'),
}

# Theme Configuration
THEME_CONFIG: Dict[str, Any] = {
    'default_theme': os.getenv('ARMORYGIS_DEFAULT_THEME', 'light'),
    'themes': {
        'dark': 'resources/styles/dark.qss',
        'light': 'resources/styles/light.qss',
        'orange_black': 'resources/styles/orange_black.qss',
        'cyber_neon': 'resources/styles/cyber_neon.qss',
    },
    'theme_colors': {
        'dark': {'bg': '#1e1e1e', 'fg': '#ffffff', 'accent': '#00ffcc'},
        'light': {'bg': '#f5f5f5', 'fg': '#000000', 'accent': '#0066cc'},
        'orange_black': {'bg': '#000000', 'fg': '#ff6600', 'accent': '#ff6600'},
        'cyber_neon': {'bg': '#0a0f1a', 'fg': '#00ffcc', 'accent': '#00ffcc'},
    },
}

# Language/Internationalization Configuration
LANGUAGE_CONFIG: Dict[str, Any] = {
    'default_language': os.getenv('ARMORYGIS_LANGUAGE', 'ar'),
    'supported_languages': ['en', 'ar'],
    'translation_dir': 'resources/translations',
    'rtl_languages': ['ar'],
}

# Path Configuration
PROJECT_ROOT: Path = Path(__file__).parent.resolve()
RESOURCES_DIR: Path = PROJECT_ROOT / 'resources'
DATABASE_DIR: Path = PROJECT_ROOT / 'database'
STYLES_DIR: Path = RESOURCES_DIR / 'styles'
TRANSLATIONS_DIR: Path = RESOURCES_DIR / 'translations'
ICONS_DIR: Path = RESOURCES_DIR / 'icons'
IMAGES_DIR: Path = RESOURCES_DIR / 'images'
HTML_DIR: Path = RESOURCES_DIR / 'html'
JS_DIR: Path = HTML_DIR / 'js'
CSS_DIR: Path = HTML_DIR / 'css'

# Ensure all directories exist
for directory in [
    RESOURCES_DIR, DATABASE_DIR, STYLES_DIR, TRANSLATIONS_DIR,
    ICONS_DIR / 'svg', ICONS_DIR / 'png', IMAGES_DIR,
    HTML_DIR, JS_DIR, CSS_DIR,
    Path(TILE_CACHE_CONFIG['cache_dir']),
]:
    directory.mkdir(parents=True, exist_ok=True)

# Helper Functions
def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    if getattr(sys, 'frozen', False):
        # Running in bundle
        base_path = Path(sys._MEIPASS)  # type: ignore
    else:
        # Running in normal Python
        base_path = PROJECT_ROOT
    return base_path / relative_path

def is_production() -> bool:
    """Check if running in production mode"""
    return not APP_CONFIG['debug']

def get_log_path() -> Path:
    """Get path to log file"""
    log_path = Path(APP_CONFIG['log_file'])
    if not log_path.is_absolute():
        log_path = APP_DATA_DIR / log_path
    return log_path