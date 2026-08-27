class MapController:
    def __init__(self, db_manager, tile_cache):
        self.db = db_manager
        self.tile_cache = tile_cache

    def get_cache_stats(self):
        return self.db.get_cache_stats()

    def pre_cache_area(self, lat, lon, radius_km):
        # Delegate to TileCacheManager
        self.tile_cache.pre_cache_region(lat, lon, radius_km=radius_km)