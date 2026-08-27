"""Map-related QSettings keys and helpers."""
from __future__ import annotations

MAP_TILE_MODE_KEY = "map/tile_mode"
MAP_BASEMAP_KEY = "map/basemap"
MAP_DEFAULT_LAT_KEY = "map/default_lat"
MAP_DEFAULT_LON_KEY = "map/default_lon"
MAP_FALLBACK_ONLINE_KEY = "map/fallback_online_when_missing"

TILE_MODE_OFFLINE = "offline"
TILE_MODE_ONLINE = "online"
TILE_MODE_AUTO = "auto"

DEFAULT_BASEMAP = "dark"
DEFAULT_TILE_MODE = TILE_MODE_OFFLINE


def resolve_offline_only(mode: str, fallback_online: bool = False) -> bool:
    """Return whether MapView should pass offline_only=True to get_tile for normal fetches."""
    mode = (mode or DEFAULT_TILE_MODE).strip().lower()
    if mode == TILE_MODE_ONLINE:
        return False
    if mode == TILE_MODE_AUTO:
        return not fallback_online
    return True


def resolve_get_tile_offline_only(mode: str, fallback_online: bool = False) -> bool:
    """For get_tile: auto mode tries cache first then downloads if allowed."""
    mode = (mode or DEFAULT_TILE_MODE).strip().lower()
    if mode == TILE_MODE_ONLINE:
        return False
    if mode == TILE_MODE_AUTO:
        return False
    return True
