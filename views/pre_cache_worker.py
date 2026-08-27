"""Background worker for offline map tile pre-caching."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class PreCacheWorker(QThread):
    finished_with_stats = pyqtSignal(dict)
    progress_update = pyqtSignal(int, str)
    failed_with_error = pyqtSignal(str)

    def __init__(self, tile_cache, cfg, cancel_flag, parent=None):
        super().__init__(parent)
        self.tile_cache = tile_cache
        self.cfg = cfg
        self.cancel_flag = cancel_flag
        self._last_pct = -1

    def run(self):
        try:
            basemaps = self.cfg.get("basemaps") or [self.cfg.get("basemap", "dark")]
            basemaps = [b for b in basemaps if b]
            use_multi = len(basemaps) > 1

            def progress_callback(*args, **kwargs):
                basemap = kwargs.get("basemap", "")
                basemap_index = int(kwargs.get("basemap_index", 0) or 0)
                basemap_count = int(kwargs.get("basemap_count", 0) or 0)

                if len(args) >= 5 and basemap_count > 0:
                    pct = int(args[0])
                    downloaded, failed, skipped = int(args[2]), int(args[3]), int(args[4])
                    done = pct
                    total = 100
                elif len(args) >= 5:
                    done, total, downloaded, failed, skipped = (
                        int(args[0]),
                        int(args[1]),
                        int(args[2]),
                        int(args[3]),
                        int(args[4]),
                    )
                    pct = int((done / max(total, 1)) * 100)
                else:
                    return

                if pct == self._last_pct:
                    return
                self._last_pct = pct

                prefix = ""
                if basemap and basemap_count:
                    prefix = f"[{basemap} {basemap_index}/{basemap_count}] "
                text = (
                    f"{prefix}"
                    f"تم: {done}/{total} | "
                    f"جديد: {downloaded} | "
                    f"فشل: {failed} | "
                    f"موجود: {skipped}"
                )
                self.progress_update.emit(pct, text)

            cancel_check = lambda: bool(self.cancel_flag.get("value"))

            if self.cfg.get("mode") == "world":
                stats = self.tile_cache.pre_cache_world(
                    zoom_levels=self.cfg["zooms"],
                    basemaps=basemaps,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            else:
                common = {
                    "center_lat": float(self.cfg.get("lat", 0)),
                    "center_lon": float(self.cfg.get("lon", 0)),
                    "zoom_levels": self.cfg["zooms"],
                    "radius_km": float(self.cfg.get("radius", 1500)),
                    "progress_callback": progress_callback,
                    "cancel_check": cancel_check,
                }
                if use_multi:
                    stats = self.tile_cache.pre_cache_basemaps(basemaps=basemaps, **common)
                else:
                    stats = self.tile_cache.pre_cache_region(basemap=basemaps[0], **common)

            self.finished_with_stats.emit(stats or {})
        except Exception as exc:
            logger.exception("Pre-cache worker failed")
            self.finished_with_stats.emit(
                {
                    "downloaded": 0,
                    "failed": 0,
                    "skipped": 0,
                    "total": 0,
                    "error": str(exc),
                }
            )
