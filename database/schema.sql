-- ArmoryGIS Pro Database Schema
-- Supports SQLite (default) and PostgreSQL (via SQLAlchemy)
-- Version: 1.0.0

-- ============================================================================
-- LOOKUP TABLES (Normalized Reference Data)
-- ============================================================================

CREATE TABLE IF NOT EXISTS countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    iso_code TEXT(2),
    region TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    icon_name TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS guidance_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS propulsion_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- MAIN WEAPONS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS weapons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Core Identification
    model TEXT NOT NULL,
    weapon_name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    country_id INTEGER REFERENCES countries(id) ON DELETE SET NULL,
    
    -- Physical Specifications (metric units)
    length_m REAL,
    diameter_m REAL,
    weight_kg REAL,
    
    -- Warhead Information
    warhead_type TEXT,
    warhead_weight_kg REAL,
    
    -- Performance Characteristics
    range_km REAL,
    speed_mach REAL,
    
    -- Technical Specifications
    guidance_id INTEGER REFERENCES guidance_types(id) ON DELETE SET NULL,
    propulsion_id INTEGER REFERENCES propulsion_types(id) ON DELETE SET NULL,
    platform TEXT,
    status TEXT CHECK(status IN ('operational', 'development', 'testing', 'retired', 'export-only')),
    
    -- Metadata & Administrative
    manufacturer TEXT,
    intro_year INTEGER,
    unit_cost_usd REAL,
    notes TEXT,
    is_favorite INTEGER DEFAULT 0,
    
    -- Geospatial Coordinates (for map features)
    origin_lat REAL DEFAULT 31.5,
    origin_lon REAL DEFAULT 34.8,
    
    -- System Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    UNIQUE(model, country_id)
);

-- ============================================================================
-- WEAPON IMAGES (One-to-Many Relationship)
-- ============================================================================

CREATE TABLE IF NOT EXISTS weapon_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weapon_id INTEGER NOT NULL REFERENCES weapons(id) ON DELETE CASCADE,
    image_path TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT 0,
    caption TEXT,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(weapon_id, image_path)
);

-- ============================================================================
-- WEAPON VARIANTS (e.g., AGM-114K, AGM-114R, AGM-114L)
-- ============================================================================

CREATE TABLE IF NOT EXISTS weapon_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_weapon_id INTEGER NOT NULL REFERENCES weapons(id) ON DELETE CASCADE,
    variant_name TEXT NOT NULL,
    range_km_override REAL,
    warhead_override TEXT,
    guidance_override TEXT,
    propulsion_override TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_weapon_id, variant_name)
);

-- ============================================================================
-- AI CACHE (Per Weapon + Context + Language)
-- ============================================================================

CREATE TABLE IF NOT EXISTS weapon_ai_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weapon_id INTEGER NOT NULL REFERENCES weapons(id) ON DELETE CASCADE,
    cache_key TEXT NOT NULL,
    language_code TEXT NOT NULL DEFAULT 'en',
    content_text TEXT DEFAULT '',
    content_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(weapon_id, cache_key, language_code)
);

-- ============================================================================
-- TILE CACHE INDEX (For Offline Map Operations)
-- ============================================================================

CREATE TABLE IF NOT EXISTS tile_cache_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    basemap_name TEXT NOT NULL,
    zoom_level INTEGER NOT NULL,
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 1,
    checksum_sha256 TEXT,
    UNIQUE(basemap_name, zoom_level, tile_x, tile_y)
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE OPTIMIZATION
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_weapons_category ON weapons(category_id);
CREATE INDEX IF NOT EXISTS idx_weapons_country ON weapons(country_id);
CREATE INDEX IF NOT EXISTS idx_weapons_range ON weapons(range_km);
CREATE INDEX IF NOT EXISTS idx_weapons_status ON weapons(status);
CREATE INDEX IF NOT EXISTS idx_weapons_search ON weapons(weapon_name, model, manufacturer);
CREATE INDEX IF NOT EXISTS idx_weapons_geo ON weapons(origin_lat, origin_lon);

CREATE INDEX IF NOT EXISTS idx_images_weapon ON weapon_images(weapon_id);
CREATE INDEX IF NOT EXISTS idx_variants_parent ON weapon_variants(parent_weapon_id);
CREATE INDEX IF NOT EXISTS idx_weapon_ai_cache_weapon ON weapon_ai_cache(weapon_id);
CREATE INDEX IF NOT EXISTS idx_weapon_ai_cache_key ON weapon_ai_cache(cache_key);

CREATE INDEX IF NOT EXISTS idx_tiles_basemap ON tile_cache_index(basemap_name, zoom_level);
CREATE INDEX IF NOT EXISTS idx_tiles_access ON tile_cache_index(last_accessed);
CREATE INDEX IF NOT EXISTS idx_tiles_coords ON tile_cache_index(tile_x, tile_y, zoom_level);

-- ============================================================================
-- FULL-TEXT SEARCH VIRTUAL TABLE (SQLite FTS5)
-- ============================================================================

CREATE VIRTUAL TABLE IF NOT EXISTS weapons_fts USING fts5(
    weapon_name, model, manufacturer, notes, platform,
    content='weapons', content_rowid='id'
);

-- FTS Triggers for Automatic Index Maintenance
CREATE TRIGGER IF NOT EXISTS weapons_ai AFTER INSERT ON weapons BEGIN
  INSERT INTO weapons_fts(rowid, weapon_name, model, manufacturer, notes, platform)
  VALUES (new.id, new.weapon_name, new.model, new.manufacturer, new.notes, new.platform);
END;

CREATE TRIGGER IF NOT EXISTS weapons_ad AFTER DELETE ON weapons BEGIN
  INSERT INTO weapons_fts(weapons_fts, rowid, weapon_name, model, manufacturer, notes, platform) 
  VALUES('delete', old.id, old.weapon_name, old.model, old.manufacturer, old.notes, old.platform);
END;

CREATE TRIGGER IF NOT EXISTS weapons_au AFTER UPDATE ON weapons BEGIN
  INSERT INTO weapons_fts(weapons_fts, rowid, weapon_name, model, manufacturer, notes, platform) 
  VALUES('delete', old.id, old.weapon_name, old.model, old.manufacturer, old.notes, old.platform);
  INSERT INTO weapons_fts(rowid, weapon_name, model, manufacturer, notes, platform) 
  VALUES (new.id, new.weapon_name, new.model, new.manufacturer, new.notes, new.platform);
END;

-- ============================================================================
-- SEED DATA (Optional - Run via seed_data.py)
-- ============================================================================

-- Sample Countries
INSERT OR IGNORE INTO countries (name, iso_code, region) VALUES 
('United States', 'US', 'North America'),
('Israel', 'IL', 'Middle East'),
('Russia', 'RU', 'Europe/Asia'),
('China', 'CN', 'Asia'),
('United Kingdom', 'GB', 'Europe');

-- Sample Categories
INSERT OR IGNORE INTO categories (name, description, icon_name, sort_order) VALUES
('Air-to-Air Missile', 'Missiles launched from aircraft to engage aerial targets', 'aam', 1),
('Surface-to-Air Missile', 'Ground or ship-launched missiles for air defense', 'sam', 2),
('Air-to-Surface Missile', 'Aircraft-launched missiles for ground/naval targets', 'asm', 3),
('Anti-Ship Missile', 'Missiles designed to engage surface vessels', 'ashm', 4),
('Anti-Tank Guided Missile', 'Portable or vehicle-mounted anti-armor weapons', 'atgm', 5),
('Guided Bomb Unit', 'Precision-guided unpowered munitions', 'gbu', 6),
('Cruise Missile', 'Long-range, low-altitude guided missiles', 'cruise', 7),
('Ballistic Missile', 'High-speed, high-altitude ballistic trajectory weapons', 'ballistic', 8),
('Loitering Munition', 'Drone-based precision strike weapons', 'loitering', 9);

-- Sample Guidance Types
INSERT OR IGNORE INTO guidance_types (name, description) VALUES
('Semi-Active Laser', 'Guidance via laser designator reflection'),
('GPS/INS', 'Global Positioning System + Inertial Navigation'),
('Imaging Infrared', 'Infrared seeker with imaging capability'),
('Active Radar', 'Missile-mounted radar for terminal guidance'),
('Command Guidance', 'Remote control via datalink'),
('Wire-Guided', 'Physical wire connection for control'),
('Millimeter Wave Radar', 'High-frequency radar for all-weather operation'),
('TV Guidance', 'Optical TV camera for manual or auto tracking');

-- Sample Propulsion Types
INSERT OR IGNORE INTO propulsion_types (name, description) VALUES
('Solid Rocket', 'Single-use solid propellant motor'),
('Liquid Rocket', 'Liquid propellant with throttling capability'),
('Turbojet', 'Air-breathing jet engine for cruise missiles'),
('Ramjet', 'High-speed air-breathing propulsion'),
('None (Glide)', 'Unpowered glide from release altitude'),
('Electric Motor', 'Battery-powered for loitering munitions');