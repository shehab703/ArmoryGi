"""
Tile Cache Manager for Offline Map Operations
Downloads, stores, and serves map tiles locally for offline use
"""
import os
import io
import time
import hashlib
import logging
import threading
import requests
import sqlite3
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import TILE_CACHE_CONFIG

logger = logging.getLogger(__name__)


class TileCacheManager:
    """
    Manages local caching of map tiles for offline operations.
    Supports multiple basemaps, LRU eviction, and pre-caching regions.
    """
    
    # Tile URL templates for supported basemaps
    BASEMAP_TEMPLATES = {
        'dark': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        'satellite': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'osm': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'topo': 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png'
    }
    
    # Subdomains for load balancing (where supported)
    SUBDOMAINS = {
        'dark': ['a', 'b', 'c'],
        'osm': ['a', 'b', 'c'],
        'topo': ['a', 'b', 'c'],
        'satellite': ['']  # No subdomains for ESRI
    }
    
    def __init__(self, cache_dir: str, max_cache_size_gb: float = 5.0,
                 basemaps: Optional[List[str]] = None,
                 user_agent: str = "ArmoryGIS/1.0"):
        """
        Initialize tile cache manager
        
        Args:
            cache_dir: Directory to store cached tiles
            max_cache_size_gb: Maximum cache size before LRU eviction
            basemaps: List of basemap names to support (default: all)
            user_agent: User-Agent header for tile requests
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_bytes = int(max_cache_size_gb * 1024 * 1024 * 1024)
        self.basemaps = basemaps or list(self.BASEMAP_TEMPLATES.keys())
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})
        self._gmdb_connections: Dict[str, sqlite3.Connection] = {}
        self._cache_lock = threading.Lock()
        
        # Create subdirectories for each basemap
        for basemap in self.basemaps:
            (self.cache_dir / basemap).mkdir(exist_ok=True)
        
        logger.info(f"Tile cache initialized: {self.cache_dir} (max {max_cache_size_gb}GB)")
    
    def _tile_to_path(self, basemap: str, z: int, x: int, y: int) -> Path:
        """Convert tile coordinates to local file path"""
        return self.cache_dir / basemap / str(z) / str(x) / f"{y}.png"
    
    def _get_tile_url(self, basemap: str, z: int, x: int, y: int) -> str:
        """Generate tile URL with subdomain rotation"""
        template = self.BASEMAP_TEMPLATES.get(basemap)
        if not template:
            raise ValueError(f"Unknown basemap: {basemap}")
        
        # Rotate subdomains for load balancing
        subdomains = self.SUBDOMAINS.get(basemap, [''])
        subdomain = subdomains[(x + y) % len(subdomains)] if subdomains else ''
        
        # Handle {r} for retina displays (optional)
        retina = '@2x' if TILE_CACHE_CONFIG.get('retina', False) else ''
        
        return template.format(s=subdomain, z=z, x=x, y=y, r=retina)
    
    def get_tile(self, basemap: str, z: int, x: int, y: int, 
                 offline_only: bool = False) -> Optional[bytes]:
        """
        Get tile image data, from cache or download if allowed
        
        Args:
            basemap: Basemap name
            z, x, y: Tile coordinates
            offline_only: If True, only return cached tiles (no download)
            
        Returns:
            PNG image bytes or None if not available
        """
        if isinstance(basemap, str) and basemap.startswith("gmdb|"):
            return self._get_tile_from_gmdb_token(basemap, z, x, y)

        if basemap not in self.basemaps:
            logger.warning(f"Basemap not enabled: {basemap}")
            return None
        
        # Check cache first
        tile_path = self._tile_to_path(basemap, z, x, y)
        if tile_path.exists():
            try:
                with open(tile_path, 'rb') as f:
                    return f.read()
            except IOError as e:
                logger.error(f"Failed to read cached tile {tile_path}: {e}")
                # Delete corrupted file
                try:
                    tile_path.unlink()
                except:
                    pass
        
        # If offline-only or cache miss with no download allowed
        if offline_only:
            return None

        return self._download_tile(basemap, z, x, y, tile_path)

    def _download_tile(
        self,
        basemap: str,
        z: int,
        x: int,
        y: int,
        tile_path: Optional[Path] = None,
        enforce_limit: bool = True,
    ) -> Optional[bytes]:
        """Download a tile from the remote provider and save it locally."""
        tile_path = tile_path or self._tile_to_path(basemap, z, x, y)

        if tile_path.exists():
            try:
                return tile_path.read_bytes()
            except OSError:
                pass

        url = ""
        try:
            url = self._get_tile_url(basemap, z, x, y)
            logger.debug("Downloading tile: %s", url)

            timeout = int(TILE_CACHE_CONFIG.get("request_timeout", 30))
            max_retries = int(TILE_CACHE_CONFIG.get("max_retries", 3))
            response = None
            last_error = None

            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent})
            try:
                for attempt in range(max_retries):
                    try:
                        response = session.get(url, timeout=timeout)
                        response.raise_for_status()
                        break
                    except requests.RequestException as exc:
                        last_error = exc
                        if attempt + 1 < max_retries:
                            time.sleep(min(2 ** attempt, 4))
            finally:
                session.close()

            if response is None:
                raise last_error or requests.RequestException("download failed")

            content_type = response.headers.get("Content-Type", "")
            if content_type and "image" not in content_type.lower():
                logger.warning("Non-image response for tile: %s (%s)", url, content_type)
                return None

            tile_data = response.content
            if not tile_data:
                logger.warning("Empty tile response: %s", url)
                return None

            tile_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_lock:
                with open(tile_path, "wb") as f:
                    f.write(tile_data)
                self._update_cache_index(basemap, z, x, y, tile_path, len(tile_data))
                if enforce_limit:
                    self._enforce_cache_limit()
            return tile_data

        except requests.RequestException as e:
            logger.warning("Failed to download tile %s: %s", url or basemap, e)
            return None
        except Exception as e:
            logger.error("Unexpected error downloading tile %s/%s/%s: %s", z, x, y, e)
            return None

    def _get_tile_from_gmdb_token(self, token: str, z: int, x: int, y: int) -> Optional[bytes]:
        """
        Read tile bytes from a .gmdb SQLite-like container.
        Supports common tile table variants.
        """
        try:
            gmdb_path = token.split("|", 1)[1]
        except Exception:
            return None
        file_path = Path(gmdb_path).expanduser().resolve(strict=False)
        if not file_path.exists():
            return None
        try:
            conn = self._gmdb_connections.get(str(file_path))
            if conn is None:
                conn = sqlite3.connect(str(file_path))
                conn.row_factory = sqlite3.Row
                self._gmdb_connections[str(file_path)] = conn
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            # MBTiles-like schema
            if "tiles" in tables:
                cols = {
                    r["name"]
                    for r in conn.execute("PRAGMA table_info(tiles)").fetchall()
                }
                if {"zoom_level", "tile_column", "tile_row", "tile_data"}.issubset(cols):
                    tms_y = (2 ** int(z) - 1 - int(y))
                    row = conn.execute(
                        """
                        SELECT tile_data FROM tiles
                        WHERE zoom_level=? AND tile_column=? AND tile_row IN (?, ?)
                        LIMIT 1
                        """,
                        (int(z), int(x), int(y), int(tms_y)),
                    ).fetchone()
                    if row:
                        return bytes(row["tile_data"])
                # alternate naming
                if {"z", "x", "y", "image"}.issubset(cols):
                    row = conn.execute(
                        "SELECT image FROM tiles WHERE z=? AND x=? AND y=? LIMIT 1",
                        (int(z), int(x), int(y)),
                    ).fetchone()
                    if row:
                        return bytes(row["image"])
            if "map_tiles" in tables:
                cols = {
                    r["name"]
                    for r in conn.execute("PRAGMA table_info(map_tiles)").fetchall()
                }
                if {"z", "x", "y", "tile_data"}.issubset(cols):
                    row = conn.execute(
                        "SELECT tile_data FROM map_tiles WHERE z=? AND x=? AND y=? LIMIT 1",
                        (int(z), int(x), int(y)),
                    ).fetchone()
                    if row:
                        return bytes(row["tile_data"])
        except Exception as e:
            logger.warning(f"Failed reading GMDB tile from {file_path}: {e}")
        return None
    
    def _update_cache_index(self, basemap: str, z: int, x: int, y: int,
                           file_path: Path, file_size: int):
        """Update database cache index (called by DatabaseManager)"""
        # This is a placeholder - actual implementation requires db_manager import
        # To avoid circular imports, we use a callback pattern or event system
        # For now, log the action
        logger.debug(f"Cache index update: {basemap}/{z}/{x}/{y} -> {file_path}")
    
    def _enforce_cache_limit(self):
        """Enforce maximum cache size using LRU eviction"""
        with self._cache_lock:
            cache_files = []
            for basemap in self.basemaps:
                basemap_dir = self.cache_dir / basemap
                if not basemap_dir.exists():
                    continue
                for tile_file in basemap_dir.rglob('*.png'):
                    try:
                        stat = tile_file.stat()
                        cache_files.append({
                            'path': tile_file,
                            'size': stat.st_size,
                            'accessed': stat.st_atime
                        })
                    except OSError:
                        continue

            total_size = sum(f['size'] for f in cache_files)

            if total_size > self.max_cache_bytes:
                cache_files.sort(key=lambda f: f['accessed'])
                bytes_to_free = total_size - self.max_cache_bytes
                bytes_freed = 0

                for tile in cache_files:
                    if bytes_freed >= bytes_to_free:
                        break
                    try:
                        tile['path'].unlink()
                        bytes_freed += tile['size']
                        logger.debug(f"Evicted cache tile: {tile['path']}")
                    except OSError as e:
                        logger.warning(f"Failed to evict {tile['path']}: {e}")

                logger.info(f"Cache eviction: freed {bytes_freed / (1024*1024):.2f}MB")

    def _iter_world_tiles(self, zoom_levels: List[int]) -> List[Tuple[int, int, int]]:
        """All Web Mercator tiles for the given zoom levels (full world)."""
        tiles: List[Tuple[int, int, int]] = []
        for z in zoom_levels:
            n = 2 ** int(z)
            for x in range(n):
                for y in range(n):
                    tiles.append((int(z), int(x), int(y)))
        return tiles

    def _pre_cache_tiles(
        self,
        basemap: str,
        tiles_to_download: List[Tuple[int, int, int]],
        max_workers: int = 2,
        progress_callback=None,
        cancel_check=None,
        enforce_limit: bool = True,
    ) -> Dict:
        """Download a explicit list of tiles for one basemap."""
        if basemap not in self.basemaps:
            logger.error("Cannot pre-cache: basemap '%s' not enabled", basemap)
            return {"downloaded": 0, "failed": 0, "skipped": 0, "total": 0}

        downloaded = 0
        failed = 0
        skipped = 0
        total = len(tiles_to_download)
        last_progress_emit = 0.0

        def emit_progress(force: bool = False):
            nonlocal last_progress_emit
            if not progress_callback:
                return
            now = time.monotonic()
            if not force and (now - last_progress_emit) < 0.25:
                return
            last_progress_emit = now
            done = downloaded + failed + skipped
            progress_callback(done, total, downloaded, failed, skipped)

        pending_tiles = []
        for z, x, y in tiles_to_download:
            tile_path = self._tile_to_path(basemap, z, x, y)
            if tile_path.exists():
                skipped += 1
            else:
                pending_tiles.append((z, x, y, tile_path))
        emit_progress(force=True)

        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4))) as executor:
            future_to_tile = {
                executor.submit(
                    self._download_tile,
                    basemap,
                    z,
                    x,
                    y,
                    tile_path,
                    enforce_limit,
                ): (z, x, y)
                for z, x, y, tile_path in pending_tiles
            }

            for future in as_completed(future_to_tile):
                if cancel_check and cancel_check():
                    logger.info("Pre-caching cancelled by user")
                    for pending_future in future_to_tile:
                        pending_future.cancel()
                    break
                z, x, y = future_to_tile[future]
                try:
                    result = future.result()
                    if result:
                        downloaded += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error("Error downloading tile %s/%s/%s: %s", z, x, y, e)
                    failed += 1
                emit_progress()

        if enforce_limit:
            with self._cache_lock:
                self._enforce_cache_limit()
        return {
            "downloaded": downloaded,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        }

    def pre_cache_world(
        self,
        zoom_levels: List[int],
        basemaps: List[str],
        max_workers: int = 2,
        progress_callback=None,
        cancel_check=None,
    ) -> Dict:
        """Pre-download full-world tiles for low zoom levels (e.g. Z0–Z5)."""
        tiles = self._iter_world_tiles(zoom_levels)
        logger.info(
            "Pre-caching world tiles: zooms %s, %s tiles/basemap, basemaps=%s",
            zoom_levels,
            len(tiles),
            basemaps,
        )
        combined = {
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "basemaps": {},
            "mode": "world",
        }
        basemap_list = [b for b in basemaps if b in self.basemaps]
        if not basemap_list:
            return combined

        for idx, basemap in enumerate(basemap_list):
            if cancel_check and cancel_check():
                break

            def wrapped_progress(done, total, downloaded, failed, skipped, _bm=basemap, _i=idx, _n=len(basemap_list)):
                if progress_callback:
                    pct_base = int((_i / _n) * 100)
                    pct_step = int((done / max(total, 1)) * (100 / _n))
                    progress_callback(
                        min(99, pct_base + pct_step),
                        total,
                        downloaded,
                        failed,
                        skipped,
                        basemap=_bm,
                        basemap_index=_i + 1,
                        basemap_count=_n,
                    )

            result = self._pre_cache_tiles(
                basemap=basemap,
                tiles_to_download=tiles,
                max_workers=max_workers,
                progress_callback=wrapped_progress if progress_callback else None,
                cancel_check=cancel_check,
                enforce_limit=False,
            )
            combined["basemaps"][basemap] = result
            combined["downloaded"] += int(result.get("downloaded", 0))
            combined["failed"] += int(result.get("failed", 0))
            combined["skipped"] += int(result.get("skipped", 0))
            combined["total"] += int(result.get("total", 0))

        with self._cache_lock:
            self._enforce_cache_limit()
        self.save_cache_index()
        return combined
    
    def pre_cache_region(self, center_lat: float, center_lon: float, 
                        zoom_levels: List[int], radius_km: float,
                        basemap: str = 'dark', max_workers: int = 2,
                        progress_callback=None, cancel_check=None):
        """
        Pre-download tiles for a geographic region for offline use
        
        Args:
            center_lat, center_lon: Center point of region
            zoom_levels: List of zoom levels to cache
            radius_km: Radius around center to cache
            basemap: Basemap to cache
            max_workers: Parallel download threads
        """
        from geopy.distance import geodesic
        
        if basemap not in self.basemaps:
            logger.error(f"Cannot pre-cache: basemap '{basemap}' not enabled")
            return {"downloaded": 0, "failed": 0, "skipped": 0, "total": 0}
        
        logger.info(f"Pre-caching {basemap} tiles for region: "
                   f"({center_lat}, {center_lon}) ±{radius_km}km, zooms {zoom_levels}")
        
        # Convert lat/lon to tile coordinates at each zoom level
        tiles_to_download = []
        
        for z in zoom_levels:
            # Calculate tile at center
            center_x, center_y = self._lat_lon_to_tile(center_lat, center_lon, z)
            
            # Estimate tile radius at this zoom level
            # At equator, 1 tile at zoom z ≈ 156km / 2^z
            km_per_tile = 156543.03392 * 0.703125 / (2 ** z)  # Approximate
            tile_radius = max(1, int(radius_km / km_per_tile) + 1)
            
            # Generate tile coordinates in bounding box
            for dx in range(-tile_radius, tile_radius + 1):
                for dy in range(-tile_radius, tile_radius + 1):
                    x = center_x + dx
                    y = center_y + dy
                    
                    # Validate tile coordinates
                    max_tiles = 2 ** z
                    if 0 <= x < max_tiles and 0 <= y < max_tiles:
                        # Optional: verify tile is within radius using reverse projection
                        tiles_to_download.append((z, x, y))
        
        logger.info(f"Queued {len(tiles_to_download)} tiles for download")
        result = self._pre_cache_tiles(
            basemap=basemap,
            tiles_to_download=tiles_to_download,
            max_workers=max_workers,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            enforce_limit=False,
        )
        self.save_cache_index()
        logger.info(
            "Pre-caching complete: %s downloaded, %s failed, %s already cached",
            result.get("downloaded", 0),
            result.get("failed", 0),
            result.get("skipped", 0),
        )
        return result
    
    def _lat_lon_to_tile(self, lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """Convert lat/lon to tile x/y at given zoom (Web Mercator)"""
        import math
        
        n = 2.0 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        
        return x, y
    
    def _tile_to_lat_lon(self, x: int, y: int, zoom: int) -> Tuple[float, float]:
        """Convert tile x/y to center lat/lon (Web Mercator)"""
        import math
        
        n = 2.0 ** zoom
        lon = x / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat = math.degrees(lat_rad)
        
        return lat, lon
    
    def get_basemap_cache_status(self) -> Dict[str, Dict]:
        """Per-basemap cache stats (uses index file when fresh)."""
        stats = self.get_cache_stats()
        return dict(stats.get("basemaps", {}))

    def get_cache_stats(self, force_scan: bool = False) -> Dict:
        """Get cache statistics — prefers cache_index.json unless force_scan."""
        index_file = self.cache_dir / "cache_index.json"
        if not force_scan and index_file.is_file():
            try:
                import json
                cached = json.loads(index_file.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and "basemaps" in cached:
                    cached["cache_dir"] = str(self.cache_dir)
                    return cached
            except Exception:
                pass
        return self._scan_cache_stats()

    def _scan_cache_stats(self) -> Dict:
        stats = {
            "cache_dir": str(self.cache_dir),
            "basemaps": {},
            "total_size_mb": 0,
            "total_tiles": 0,
        }
        for basemap in self.basemaps:
            basemap_dir = self.cache_dir / basemap
            if not basemap_dir.exists():
                stats["basemaps"][basemap] = {"tile_count": 0, "size_mb": 0.0}
                continue
            tiles = list(basemap_dir.rglob("*.png"))
            total_size = sum(t.stat().st_size for t in tiles if t.exists())
            stats["basemaps"][basemap] = {
                "tile_count": len(tiles),
                "size_mb": round(total_size / (1024 * 1024), 2),
            }
            stats["total_tiles"] += len(tiles)
            stats["total_size_mb"] += total_size / (1024 * 1024)
        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        return stats

    def pre_cache_basemaps(
        self,
        center_lat: float,
        center_lon: float,
        zoom_levels: List[int],
        radius_km: float,
        basemaps: List[str],
        max_workers: int = 2,
        progress_callback=None,
        cancel_check=None,
    ) -> Dict:
        """Download multiple basemap layers sequentially (separate folders)."""
        combined = {
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "basemaps": {},
        }
        basemap_list = [b for b in basemaps if b in self.basemaps]
        if not basemap_list:
            return combined

        for idx, basemap in enumerate(basemap_list):
            if cancel_check and cancel_check():
                break

            def wrapped_progress(done, total, downloaded, failed, skipped, _bm=basemap, _i=idx, _n=len(basemap_list)):
                if progress_callback:
                    overall_total = max(combined["total"], 1)
                    overall_done = sum(
                        int(combined["basemaps"].get(b, {}).get("downloaded", 0))
                        + int(combined["basemaps"].get(b, {}).get("failed", 0))
                        + int(combined["basemaps"].get(b, {}).get("skipped", 0))
                        for b in combined["basemaps"]
                    ) + done
                    pct_base = int((_i / _n) * 100)
                    pct_step = int((done / max(total, 1)) * (100 / _n))
                    progress_callback(
                        min(99, pct_base + pct_step),
                        overall_total,
                        downloaded,
                        failed,
                        skipped,
                        basemap=_bm,
                        basemap_index=_i + 1,
                        basemap_count=_n,
                    )

            result = self.pre_cache_region(
                center_lat=center_lat,
                center_lon=center_lon,
                zoom_levels=zoom_levels,
                radius_km=radius_km,
                basemap=basemap,
                max_workers=max_workers,
                progress_callback=wrapped_progress if progress_callback else None,
                cancel_check=cancel_check,
            ) or {}
            combined["basemaps"][basemap] = result
            combined["downloaded"] += int(result.get("downloaded", 0))
            combined["failed"] += int(result.get("failed", 0))
            combined["skipped"] += int(result.get("skipped", 0))
            combined["total"] += int(result.get("total", 0))

        self.save_cache_index()
        return combined

    def has_cached_tiles(self, basemap: Optional[str] = None) -> bool:
        """Check if any tiles are cached (uses index when available)."""
        stats = self.get_cache_stats(force_scan=False)
        if basemap:
            bm = stats.get("basemaps", {}).get(basemap, {})
            return int(bm.get("tile_count", 0) or 0) > 0
        return int(stats.get("total_tiles", 0) or 0) > 0

    def clear_cache(self, basemap: Optional[str] = None):
        """Clear cached tiles"""
        if basemap:
            target = self.cache_dir / basemap
        else:
            target = self.cache_dir

        if target.exists():
            import shutil
            shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
            logger.info(f"Cleared cache: {target}")
        self.save_cache_index()

    def cleanup_old_cache(self, max_age_days: int = 90) -> int:
        """Remove cached tile files older than max_age_days."""
        cutoff = time.time() - (max_age_days * 86400)
        deleted = 0
        for basemap in self.basemaps:
            basemap_dir = self.cache_dir / basemap
            if not basemap_dir.exists():
                continue
            for tile_file in basemap_dir.rglob("*.png"):
                try:
                    if tile_file.stat().st_mtime < cutoff:
                        tile_file.unlink()
                        deleted += 1
                except OSError as e:
                    logger.warning("Failed to delete old cache tile %s: %s", tile_file, e)
        if deleted:
            self.save_cache_index()
        return deleted

    def export_cache(self, export_path: str, basemaps: Optional[List[str]] = None):
        """Export cache to portable format for offline deployment"""
        from zipfile import ZipFile, ZIP_DEFLATED
        
        export_file = Path(export_path)
        export_file.parent.mkdir(parents=True, exist_ok=True)
        
        basemaps_to_export = basemaps or self.basemaps
        
        logger.info(f"Exporting cache to {export_file}...")
        
        with ZipFile(export_file, 'w', compression=ZIP_DEFLATED) as zipf:
            for basemap in basemaps_to_export:
                basemap_dir = self.cache_dir / basemap
                if not basemap_dir.exists():
                    continue
                
                for tile_file in basemap_dir.rglob('*.png'):
                    # Add to zip with relative path
                    arcname = tile_file.relative_to(self.cache_dir)
                    zipf.write(tile_file, arcname)
        
        logger.info(f"Cache exported: {export_file.stat().st_size / (1024*1024):.2f}MB")
    
    def import_cache(self, import_path: str):
        """Import cache from exported zip file"""
        from zipfile import ZipFile
        
        import_file = Path(import_path)
        if not import_file.exists():
            logger.error(f"Import file not found: {import_file}")
            return
        
        logger.info(f"Importing cache from {import_file}...")
        
        with ZipFile(import_file, 'r') as zipf:
            zipf.extractall(self.cache_dir)
        
        logger.info("Cache import complete")
    
    def save_cache_index(self):
        """Save cache metadata to JSON for quick loading"""
        index_file = self.cache_dir / 'cache_index.json'
        stats = self._scan_cache_stats()
        stats['exported_at'] = time.time()

        with open(index_file, 'w') as f:
            import json
            json.dump(stats, f, indent=2)
    
    def get_tile_metadata(self, basemap: str, z: int, x: int, y: int) -> Optional[Dict]:
        """Get metadata for a specific cached tile"""
        tile_path = self._tile_to_path(basemap, z, x, y)
        if not tile_path.exists():
            return None
        
        stat = tile_path.stat()
        return {
            'path': str(tile_path),
            'size_bytes': stat.st_size,
            'created': stat.st_ctime,
            'accessed': stat.st_atime,
            'modified': stat.st_mtime
        }