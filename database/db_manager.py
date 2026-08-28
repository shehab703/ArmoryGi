"""
Database Manager with SQLAlchemy ORM and offline tile cache support
Handles all CRUD operations for weapons data and tile cache indexing
"""
import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Callable, Tuple

from sqlalchemy import (
    create_engine,
    text,
    event,
    func,
    delete,
    select,
    update,
    inspect,
    Column,
    ForeignKey,
    UniqueConstraint,
    Integer,
    Text,
    Float,
    Boolean,
    DateTime,
)
from sqlalchemy.orm import (
    sessionmaker, Session, declarative_base, relationship, 
    Session as SessionType, scoped_session, joinedload, selectinload
)
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import SQLAlchemyError

from config import APP_CONFIG, TILE_CACHE_CONFIG
from utils.weapon_media_library import ensure_weapon_media_dirs

Base = declarative_base()
logger = logging.getLogger(__name__)


# Backwards-compatible aliases used throughout model declarations.
# The model code currently references Base.column/ForeignKey/UniqueConstraint.
Base.column = staticmethod(Column)
Base.ForeignKey = staticmethod(ForeignKey)
Base.UniqueConstraint = staticmethod(UniqueConstraint)


def _to_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ============================================================================
# SQLALCHEMY ORM MODELS
# ============================================================================

class Country(Base):
    """Country lookup table"""
    __tablename__ = 'countries'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    name = Base.column('name', Text, unique=True, nullable=False)
    iso_code = Base.column('iso_code', Text)
    region = Base.column('region', Text)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    updated_at = Base.column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    weapons = relationship('Weapon', back_populates='country', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f"<Country(id={self.id}, name='{self.name}', iso='{self.iso_code}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'iso_code': self.iso_code,
            'region': self.region,
        }


class Category(Base):
    """Weapon category lookup table"""
    __tablename__ = 'categories'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    name = Base.column('name', Text, unique=True, nullable=False)
    description = Base.column('description', Text)
    icon_name = Base.column('icon_name', Text)
    sort_order = Base.column('sort_order', Integer, default=0)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    updated_at = Base.column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    weapons = relationship('Weapon', back_populates='category', lazy='dynamic')
    
    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'icon_name': self.icon_name,
        }


class GuidanceType(Base):
    """Guidance system type lookup"""
    __tablename__ = 'guidance_types'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    name = Base.column('name', Text, unique=True, nullable=False)
    description = Base.column('description', Text)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<GuidanceType(id={self.id}, name='{self.name}')>"


class PropulsionType(Base):
    """Propulsion system type lookup"""
    __tablename__ = 'propulsion_types'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    name = Base.column('name', Text, unique=True, nullable=False)
    description = Base.column('description', Text)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<PropulsionType(id={self.id}, name='{self.name}')>"


class Weapon(Base):
    """Main weapons table - core entity"""
    __tablename__ = 'weapons'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    
    # Core Identification
    model = Base.column('model', Text, nullable=False)
    weapon_name = Base.column('weapon_name', Text, nullable=False)
    category_id = Base.column('category_id', Integer, Base.ForeignKey('categories.id'))
    country_id = Base.column('country_id', Integer, Base.ForeignKey('countries.id'))
    
    # Physical Specifications
    length_m = Base.column('length_m', Float)
    diameter_m = Base.column('diameter_m', Float)
    weight_kg = Base.column('weight_kg', Float)
    
    # Warhead
    warhead_type = Base.column('warhead_type', Text)
    warhead_weight_kg = Base.column('warhead_weight_kg', Float)
    
    # Performance
    range_km = Base.column('range_km', Float)
    speed_mach = Base.column('speed_mach', Float)
    
    # Technical
    guidance_id = Base.column('guidance_id', Integer, Base.ForeignKey('guidance_types.id'))
    propulsion_id = Base.column('propulsion_id', Integer, Base.ForeignKey('propulsion_types.id'))
    platform = Base.column('platform', Text)
    status = Base.column('status', Text)
    
    # Metadata
    manufacturer = Base.column('manufacturer', Text)
    intro_year = Base.column('intro_year', Integer)
    unit_cost_usd = Base.column('unit_cost_usd', Float)
    notes = Base.column('notes', Text)
    is_favorite = Base.column('is_favorite', Boolean, default=False)
    
    # Geospatial
    origin_lat = Base.column('origin_lat', Float, default=31.5)
    origin_lon = Base.column('origin_lon', Float, default=34.8)
    
    # System
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    updated_at = Base.column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    category = relationship('Category', back_populates='weapons')
    country = relationship('Country', back_populates='weapons')
    guidance = relationship('GuidanceType')
    propulsion = relationship('PropulsionType')
    images = relationship('WeaponImage', back_populates='weapon', cascade='all, delete-orphan', lazy='select')
    models = relationship('WeaponModel', back_populates='weapon', cascade='all, delete-orphan', lazy='select')
    variants = relationship('WeaponVariant', back_populates='parent_weapon', cascade='all, delete-orphan', lazy='select')
    
    __table_args__ = (
        Base.UniqueConstraint('model', 'country_id'),
    )
    
    def __repr__(self) -> str:
        return f"<Weapon(id={self.id}, model='{self.model}', name='{self.weapon_name}')>"
    
    def to_dict(self, include_images: bool = True, include_variants: bool = False, include_models: bool = True) -> Dict[str, Any]:
        """Convert weapon to dictionary for JSON/JS bridge or API"""
        # Avoid triggering lazy-loads on detached instances by only using
        # relationships that are already present in the instance dict.
        category = self.__dict__.get('category')
        country = self.__dict__.get('country')
        guidance = self.__dict__.get('guidance')
        propulsion = self.__dict__.get('propulsion')
        data = {
            'id': self.id,
            'model': self.model,
            'weapon_name': self.weapon_name,
            'category': category.name if category else None,
            'category_id': self.category_id,
            'country': country.name if country else None,
            'country_id': self.country_id,
            'length_m': self.length_m,
            'diameter_m': self.diameter_m,
            'weight_kg': self.weight_kg,
            'warhead_type': self.warhead_type,
            'warhead_weight_kg': self.warhead_weight_kg,
            'range_km': self.range_km,
            'speed_mach': self.speed_mach,
            'guidance': guidance.name if guidance else None,
            'propulsion': propulsion.name if propulsion else None,
            'platform': self.platform,
            'status': self.status,
            'manufacturer': self.manufacturer,
            'intro_year': self.intro_year,
            'unit_cost_usd': self.unit_cost_usd,
            'notes': self.notes,
            'is_favorite': bool(self.is_favorite) if self.is_favorite is not None else False,
            'origin_lat': self.origin_lat,
            'origin_lon': self.origin_lon,
            'created_at': _to_iso(self.created_at),
            'updated_at': _to_iso(self.updated_at),
        }
        
        images = self.__dict__.get('images')
        if include_images and images:
            data['images'] = [img.to_dict() for img in images]
            # Set primary image for convenience
            primary = next((img for img in images if img.is_primary), None)
            data['primary_image'] = primary.image_path if primary else None
        
        variants = self.__dict__.get('variants')
        if include_variants and variants:
            data['variants'] = [v.to_dict() for v in variants]
        models = self.__dict__.get('models')
        if include_models and models:
            data['models'] = [m.to_dict() for m in models]
            primary_model = next((m for m in models if m.is_primary), None)
            data['primary_model'] = primary_model.model_path if primary_model else None
        
        return data
    
    def get_range_ring_coords(self, num_points: int = 64) -> List[tuple]:
        """Generate coordinates for drawing range ring on map"""
        import math
        
        if not self.range_km or not self.origin_lat or not self.origin_lon:
            return []
        
        coords = []
        earth_radius_km = 6371.0
        
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points
            # Simple equirectangular projection (sufficient for visualization)
            lat_offset = (self.range_km / earth_radius_km) * math.cos(angle) * (180 / math.pi)
            lon_offset = (self.range_km / earth_radius_km) * math.sin(angle) * (180 / math.pi) / math.cos(math.radians(self.origin_lat))
            
            coords.append((
                round(self.origin_lat + lat_offset, 6),
                round(self.origin_lon + lon_offset, 6)
            ))
        
        return coords


class WeaponImage(Base):
    """Weapon image gallery (one-to-many)"""
    __tablename__ = 'weapon_images'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    weapon_id = Base.column('weapon_id', Integer, Base.ForeignKey('weapons.id'), nullable=False)
    image_path = Base.column('image_path', Text, nullable=False)
    is_primary = Base.column('is_primary', Boolean, default=False)
    caption = Base.column('caption', Text)
    display_order = Base.column('display_order', Integer, default=0)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    
    weapon = relationship('Weapon', back_populates='images')
    
    __table_args__ = (
        Base.UniqueConstraint('weapon_id', 'image_path'),
    )
    
    def __repr__(self) -> str:
        return f"<WeaponImage(id={self.id}, weapon_id={self.weapon_id}, path='{self.image_path}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'weapon_id': self.weapon_id,
            'image_path': self.image_path,
            'is_primary': self.is_primary,
            'caption': self.caption,
            'display_order': self.display_order,
        }


class WeaponModel(Base):
    """Weapon 3D model library (one-to-many)."""
    __tablename__ = 'weapon_models'

    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    weapon_id = Base.column('weapon_id', Integer, Base.ForeignKey('weapons.id'), nullable=False)
    model_path = Base.column('model_path', Text, nullable=False)
    model_format = Base.column('model_format', Text)
    is_primary = Base.column('is_primary', Boolean, default=False)
    caption = Base.column('caption', Text)
    display_order = Base.column('display_order', Integer, default=0)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)

    weapon = relationship('Weapon', back_populates='models')

    __table_args__ = (
        Base.UniqueConstraint('weapon_id', 'model_path'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'weapon_id': self.weapon_id,
            'model_path': self.model_path,
            'model_format': self.model_format,
            'is_primary': self.is_primary,
            'caption': self.caption,
            'display_order': self.display_order,
        }


class WeaponVariant(Base):
    """Weapon variant/sub-model (e.g., AGM-114K vs AGM-114R)"""
    __tablename__ = 'weapon_variants'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    parent_weapon_id = Base.column('parent_weapon_id', Integer, Base.ForeignKey('weapons.id'), nullable=False)
    variant_name = Base.column('variant_name', Text, nullable=False)
    range_km_override = Base.column('range_km_override', Float)
    warhead_override = Base.column('warhead_override', Text)
    guidance_override = Base.column('guidance_override', Text)
    propulsion_override = Base.column('propulsion_override', Text)
    notes = Base.column('notes', Text)
    created_at = Base.column('created_at', DateTime, default=datetime.utcnow)
    
    parent_weapon = relationship('Weapon', back_populates='variants')
    
    __table_args__ = (
        Base.UniqueConstraint('parent_weapon_id', 'variant_name'),
    )
    
    def __repr__(self) -> str:
        return f"<WeaponVariant(id={self.id}, name='{self.variant_name}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'parent_weapon_id': self.parent_weapon_id,
            'variant_name': self.variant_name,
            'range_km_override': self.range_km_override,
            'warhead_override': self.warhead_override,
            'guidance_override': self.guidance_override,
            'propulsion_override': self.propulsion_override,
            'notes': self.notes,
        }


class WeaponSwotReport(Base):
    """Versioned SWOT analysis snapshots per weapon."""
    __tablename__ = "weapon_swot_reports"

    id = Base.column("id", Integer, primary_key=True, autoincrement=True)
    weapon_id = Base.column("weapon_id", Integer, Base.ForeignKey("weapons.id"), nullable=False, index=True)
    analyst = Base.column("analyst", Text)
    scenario = Base.column("scenario", Text)
    strengths = Base.column("strengths", Text, default="[]")
    weaknesses = Base.column("weaknesses", Text, default="[]")
    opportunities = Base.column("opportunities", Text, default="[]")
    threats = Base.column("threats", Text, default="[]")
    recommendations = Base.column("recommendations", Text, default="")
    score_summary = Base.column("score_summary", Text, default="{}")
    created_at = Base.column("created_at", DateTime, default=datetime.utcnow)
    updated_at = Base.column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    weapon = relationship("Weapon")

    def to_dict(self) -> Dict[str, Any]:
        def _load_list(raw: Optional[str]) -> List[str]:
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
            return [ln.strip() for ln in str(raw).splitlines() if ln.strip()]

        def _load_obj(raw: Optional[str]) -> Dict[str, Any]:
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            return {}

        return {
            "id": self.id,
            "weapon_id": self.weapon_id,
            "analyst": self.analyst or "",
            "scenario": self.scenario or "",
            "strengths": _load_list(self.strengths),
            "weaknesses": _load_list(self.weaknesses),
            "opportunities": _load_list(self.opportunities),
            "threats": _load_list(self.threats),
            "recommendations": self.recommendations or "",
            "score_summary": _load_obj(self.score_summary),
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
        }


class WeaponAiCache(Base):
    """Latest AI-generated content per weapon/context/language."""
    __tablename__ = "weapon_ai_cache"

    id = Base.column("id", Integer, primary_key=True, autoincrement=True)
    weapon_id = Base.column("weapon_id", Integer, Base.ForeignKey("weapons.id"), nullable=False, index=True)
    cache_key = Base.column("cache_key", Text, nullable=False)
    language_code = Base.column("language_code", Text, nullable=False, default="en")
    content_text = Base.column("content_text", Text, default="")
    content_json = Base.column("content_json", Text, default="{}")
    created_at = Base.column("created_at", DateTime, default=datetime.utcnow)
    updated_at = Base.column("updated_at", DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    weapon = relationship("Weapon")

    __table_args__ = (
        Base.UniqueConstraint("weapon_id", "cache_key", "language_code"),
    )

    def to_dict(self) -> Dict[str, Any]:
        parsed = {}
        try:
            parsed = json.loads(self.content_json or "{}")
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception:
            parsed = {}
        return {
            "id": self.id,
            "weapon_id": self.weapon_id,
            "cache_key": self.cache_key,
            "language_code": self.language_code,
            "content_text": self.content_text or "",
            "content_json": parsed,
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
        }


class TileCacheIndex(Base):
    """Tracks locally cached map tiles for offline operations"""
    __tablename__ = 'tile_cache_index'
    
    id = Base.column('id', Integer, primary_key=True, autoincrement=True)
    basemap_name = Base.column('basemap_name', Text, nullable=False)
    zoom_level = Base.column('zoom_level', Integer, nullable=False)
    tile_x = Base.column('tile_x', Integer, nullable=False)
    tile_y = Base.column('tile_y', Integer, nullable=False)
    file_path = Base.column('file_path', Text, nullable=False)
    file_size_bytes = Base.column('file_size_bytes', Integer)
    downloaded_at = Base.column('downloaded_at', DateTime, default=datetime.utcnow)
    last_accessed = Base.column('last_accessed', DateTime, default=datetime.utcnow)
    access_count = Base.column('access_count', Integer, default=1)
    checksum_sha256 = Base.column('checksum_sha256', Text)
    
    __table_args__ = (
        Base.UniqueConstraint('basemap_name', 'zoom_level', 'tile_x', 'tile_y'),
    )
    
    def __repr__(self) -> str:
        return f"<TileCacheIndex(basemap='{self.basemap_name}', z={self.zoom_level}, x={self.tile_x}, y={self.tile_y})>"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'basemap_name': self.basemap_name,
            'zoom_level': self.zoom_level,
            'tile_x': self.tile_x,
            'tile_y': self.tile_y,
            'file_path': self.file_path,
            'file_size_bytes': self.file_size_bytes,
            'downloaded_at': _to_iso(self.downloaded_at),
            'last_accessed': _to_iso(self.last_accessed),
            'access_count': self.access_count,
        }


# ============================================================================
# DATABASE MANAGER CLASS
# ============================================================================

class DatabaseManager:
    """
    Manages database connections, sessions, and CRUD operations.
    Thread-safe with scoped sessions for PyQt6 integration.
    """
    
    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database manager
        
        Args:
            database_url: SQLAlchemy connection URL (default from config)
        """
        self.database_url = database_url or APP_CONFIG['database_url']
        self._ensure_sqlite_parent_dir()
        self._engine = None
        self._session_factory = None
        
        self._create_engine()
        self._setup_events()
        
        logger.info(f"DatabaseManager initialized: {self.database_url}")

    def _ensure_sqlite_parent_dir(self) -> None:
        """Create parent folder for local SQLite database file if needed."""
        if not self.database_url.startswith("sqlite:///"):
            return
        db_path = self.database_url.replace("sqlite:///", "", 1)
        if not db_path or db_path == ":memory:":
            return
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    def _create_engine(self):
        """Create SQLAlchemy engine with appropriate settings"""
        connect_args = {}
        
        if 'sqlite' in self.database_url:
            # SQLite-specific settings
            connect_args = {
                'check_same_thread': False,
                'timeout': 30,
            }
            pool_class = StaticPool
        else:
            # PostgreSQL/other settings
            pool_class = None
        
        engine_kwargs = {
            'connect_args': connect_args,
            'echo': APP_CONFIG['debug'] or APP_CONFIG['db_echo'],
            'future': True,
        }
        if pool_class:
            engine_kwargs['poolclass'] = pool_class
        else:
            engine_kwargs['pool_size'] = APP_CONFIG['db_pool_size']
            engine_kwargs['max_overflow'] = APP_CONFIG['db_max_overflow']

        self._engine = create_engine(self.database_url, **engine_kwargs)
        
        # Create scoped session factory for thread safety with Qt
        self._session_factory = scoped_session(
            sessionmaker(bind=self._engine, autocommit=False, autoflush=False, future=True)
        )
    
    def _setup_events(self):
        """Register SQLAlchemy event listeners"""
        
        @event.listens_for(Weapon, 'before_insert')
        def receive_before_insert(mapper, connection, target):
            target.created_at = datetime.utcnow()
            target.updated_at = datetime.utcnow()
        
        @event.listens_for(Weapon, 'before_update')
        def receive_before_update(mapper, connection, target):
            target.updated_at = datetime.utcnow()
        
        @event.listens_for(TileCacheIndex, 'before_update')
        def update_tile_access(mapper, connection, target):
            target.last_accessed = datetime.utcnow()
            target.access_count = (target.access_count or 1) + 1
    
    @property
    def engine(self):
        """Get SQLAlchemy engine"""
        return self._engine
    
    def get_session(self) -> SessionType:
        """Get a new database session (thread-safe)"""
        return self._session_factory()
    
    def close_session(self):
        """Close current session"""
        self._session_factory.remove()
    
    def init_tables(self):
        """Create all tables if they don't exist"""
        Base.metadata.create_all(bind=self._engine)
        logger.info("Database tables created/verified")
        self.ensure_schema_patches()

    def ensure_schema_patches(self) -> None:
        """Lightweight migrations for existing SQLite databases."""
        if "sqlite" not in self.database_url:
            return
        try:
            db_path = self.database_url.replace("sqlite:///", "", 1)
            if not db_path or db_path == ":memory:":
                return
            insp = inspect(self._engine)
            if not insp.has_table("weapons"):
                return
            cols = {c["name"] for c in insp.get_columns("weapons")}
            if "is_favorite" not in cols:
                with self._engine.connect() as conn:
                    conn.execute(text("ALTER TABLE weapons ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0"))
                    conn.commit()
                logger.info("Schema patch: added weapons.is_favorite")
            if not insp.has_table("weapon_swot_reports"):
                with self._engine.connect() as conn:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE weapon_swot_reports (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                weapon_id INTEGER NOT NULL,
                                analyst TEXT,
                                scenario TEXT,
                                strengths TEXT DEFAULT '[]',
                                weaknesses TEXT DEFAULT '[]',
                                opportunities TEXT DEFAULT '[]',
                                threats TEXT DEFAULT '[]',
                                recommendations TEXT DEFAULT '',
                                score_summary TEXT DEFAULT '{}',
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY(weapon_id) REFERENCES weapons(id) ON DELETE CASCADE
                            )
                            """
                        )
                    )
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weapon_swot_reports_weapon_id ON weapon_swot_reports(weapon_id)"))
                    conn.commit()
                logger.info("Schema patch: created weapon_swot_reports")
            if not insp.has_table("weapon_ai_cache"):
                with self._engine.connect() as conn:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE weapon_ai_cache (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                weapon_id INTEGER NOT NULL,
                                cache_key TEXT NOT NULL,
                                language_code TEXT NOT NULL DEFAULT 'en',
                                content_text TEXT DEFAULT '',
                                content_json TEXT DEFAULT '{}',
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY(weapon_id) REFERENCES weapons(id) ON DELETE CASCADE,
                                UNIQUE(weapon_id, cache_key, language_code)
                            )
                            """
                        )
                    )
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weapon_ai_cache_weapon_id ON weapon_ai_cache(weapon_id)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_weapon_ai_cache_key ON weapon_ai_cache(cache_key)"))
                    conn.commit()
                logger.info("Schema patch: created weapon_ai_cache")
        except Exception as e:
            logger.warning(f"ensure_schema_patches: {e}")
    
    def execute_raw_sql(self, sql: str, params: Optional[Dict] = None) -> Any:
        """Execute raw SQL with optional parameters"""
        with self.get_session() as session:
            result = session.execute(text(sql), params or {})
            session.commit()
            return result
    
    # -------------------------------------------------------------------------
    # WEAPON CRUD OPERATIONS
    # -------------------------------------------------------------------------
    
    def get_weapon_by_id(self, weapon_id: int, eager_load: bool = True) -> Optional[Weapon]:
        """Fetch weapon by ID with optional eager loading of relationships"""
        with self.get_session() as session:
            query = session.query(Weapon).filter(Weapon.id == weapon_id)
            
            if eager_load:
                query = query.options(
                    joinedload(Weapon.category),
                    joinedload(Weapon.country),
                    joinedload(Weapon.guidance),
                    joinedload(Weapon.propulsion),
                    joinedload(Weapon.images),
                    selectinload(Weapon.models),
                    joinedload(Weapon.variants)
                )
            
            return query.first()
    
    def get_weapons_paginated(
        self, 
        offset: int, 
        limit: int, 
        filters: Optional[Dict[str, Any]] = None,
        sort_by: str = 'weapon_name',
        sort_order: str = 'asc'
    ) -> List[Dict[str, Any]]:
        """
        Fetch weapons with pagination, filtering, and sorting
        
        Args:
            offset: Starting row index
            limit: Maximum rows to return
            filters: Dict of filter criteria
            sort_by: Column name to sort by
            sort_order: 'asc' or 'desc'
            
        Returns:
            List of weapon dictionaries
        """
        try:
            with self.get_session() as session:
                query = session.query(Weapon)\
                    .outerjoin(Category)\
                    .outerjoin(Country)\
                    .options(
                        joinedload(Weapon.category),
                        joinedload(Weapon.country),
                        joinedload(Weapon.guidance),
                        joinedload(Weapon.propulsion),
                        selectinload(Weapon.images),
                        selectinload(Weapon.models),
                    )
                
                # Apply filters
                if filters:
                    if filters.get('category'):
                        query = query.filter(Category.name == filters['category'])
                    if filters.get('country'):
                        query = query.filter(Country.name == filters['country'])
                    if filters.get('status'):
                        query = query.filter(Weapon.status == filters['status'])
                    if filters.get('min_range') is not None:
                        query = query.filter(Weapon.range_km >= filters['min_range'])
                    if filters.get('max_range') is not None:
                        query = query.filter(Weapon.range_km <= filters['max_range'])
                    if filters.get('search'):
                        search_term = f"%{filters['search']}%"
                        query = query.filter(
                            (Weapon.weapon_name.ilike(search_term)) |
                            (Weapon.model.ilike(search_term)) |
                            (Weapon.manufacturer.ilike(search_term))
                        )
                    if filters.get('favorite') is True:
                        query = query.filter(Weapon.is_favorite.is_(True))
                
                # Apply sorting
                desc = sort_order.lower() == 'desc'
                if sort_by == 'category':
                    order_expr = Category.name.desc() if desc else Category.name.asc()
                elif hasattr(Weapon, sort_by):
                    col = getattr(Weapon, sort_by)
                    order_expr = col.desc() if desc else col.asc()
                else:
                    order_expr = Weapon.weapon_name.asc()
                query = query.order_by(order_expr)
                
                # Execute query with pagination
                weapons = query.offset(offset).limit(limit).all()
                
                return [w.to_dict(include_images=True, include_variants=False, include_models=True) for w in weapons]
        except SQLAlchemyError as e:
            # Auto-heal older SQLite files missing newly added tables (e.g., weapon_models).
            if "no such table" in str(e).lower():
                try:
                    self.init_tables()
                    with self.get_session() as session:
                        query = session.query(Weapon)\
                            .outerjoin(Category)\
                            .outerjoin(Country)\
                            .options(
                                joinedload(Weapon.category),
                                joinedload(Weapon.country),
                                joinedload(Weapon.guidance),
                                joinedload(Weapon.propulsion),
                                selectinload(Weapon.images),
                                selectinload(Weapon.models),
                            )
                        if filters:
                            if filters.get('category'):
                                query = query.filter(Category.name == filters['category'])
                            if filters.get('country'):
                                query = query.filter(Country.name == filters['country'])
                            if filters.get('status'):
                                query = query.filter(Weapon.status == filters['status'])
                            if filters.get('min_range') is not None:
                                query = query.filter(Weapon.range_km >= filters['min_range'])
                            if filters.get('max_range') is not None:
                                query = query.filter(Weapon.range_km <= filters['max_range'])
                            if filters.get('search'):
                                search_term = f"%{filters['search']}%"
                                query = query.filter(
                                    (Weapon.weapon_name.ilike(search_term)) |
                                    (Weapon.model.ilike(search_term)) |
                                    (Weapon.manufacturer.ilike(search_term))
                                )
                            if filters.get('favorite') is True:
                                query = query.filter(Weapon.is_favorite.is_(True))
                        desc = sort_order.lower() == 'desc'
                        if sort_by == 'category':
                            order_expr = Category.name.desc() if desc else Category.name.asc()
                        elif hasattr(Weapon, sort_by):
                            col = getattr(Weapon, sort_by)
                            order_expr = col.desc() if desc else col.asc()
                        else:
                            order_expr = Weapon.weapon_name.asc()
                        query = query.order_by(order_expr)
                        weapons = query.offset(offset).limit(limit).all()
                        return [w.to_dict(include_images=True, include_variants=False, include_models=True) for w in weapons]
                except Exception as repair_error:
                    logger.warning(f"Schema auto-repair failed in get_weapons_paginated: {repair_error}")
            logger.warning(f"get_weapons_paginated fallback to empty list: {e}")
            return []
    
    def get_weapon_count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Get total weapon count with optional filters"""
        try:
            with self.get_session() as session:
                query = session.query(func.count(Weapon.id))
                
                if filters:
                    if filters.get('category'):
                        query = query.join(Category).filter(Category.name == filters['category'])
                    if filters.get('country'):
                        query = query.join(Country).filter(Country.name == filters['country'])
                    if filters.get('status'):
                        query = query.filter(Weapon.status == filters['status'])
                    if filters.get('min_range') is not None:
                        query = query.filter(Weapon.range_km >= filters['min_range'])
                    if filters.get('max_range') is not None:
                        query = query.filter(Weapon.range_km <= filters['max_range'])
                    if filters.get('search'):
                        search_term = f"%{filters['search']}%"
                        query = query.filter(
                            (Weapon.weapon_name.ilike(search_term)) |
                            (Weapon.model.ilike(search_term)) |
                            (Weapon.manufacturer.ilike(search_term))
                        )
                    if filters.get('favorite') is True:
                        query = query.filter(Weapon.is_favorite.is_(True))
                
                return query.scalar() or 0
        except SQLAlchemyError as e:
            logger.warning(f"get_weapon_count fallback to zero: {e}")
            return 0
    
    def search_weapons_fts(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Full-text search using SQLite FTS5"""
        with self.get_session() as session:
            # FTS5 query with ranking
            fts_query = session.execute(
                text("""
                SELECT w.*, bm.score 
                FROM weapons w
                JOIN weapons_fts bm ON w.id = bm.rowid
                WHERE weapons_fts MATCH :search_query
                ORDER BY bm.score DESC
                LIMIT :limit
                """),
                {"search_query": query, "limit": limit}
            ).fetchall()
            
            return [dict(row._mapping) for row in fts_query]
    
    def add_weapon(self, weapon_data: Dict[str, Any]) -> Optional[Weapon]:
        """Add new weapon to database"""
        try:
            with self.get_session() as session:
                # Handle category/country by name lookup or create
                if 'category' in weapon_data and weapon_data['category']:
                    cat = session.query(Category).filter(Category.name == weapon_data['category']).first()
                    if cat:
                        weapon_data['category_id'] = cat.id
                        del weapon_data['category']
                
                if 'country' in weapon_data and weapon_data['country']:
                    country = session.query(Country).filter(Country.name == weapon_data['country']).first()
                    if country:
                        weapon_data['country_id'] = country.id
                        del weapon_data['country']
                
                weapon = Weapon(**{k: v for k, v in weapon_data.items() if hasattr(Weapon, k)})
                session.add(weapon)
                session.commit()
                session.refresh(weapon)
                weapon = session.query(Weapon).options(
                    joinedload(Weapon.category),
                    joinedload(Weapon.country),
                    joinedload(Weapon.guidance),
                    joinedload(Weapon.propulsion),
                    selectinload(Weapon.images),
                    selectinload(Weapon.models),
                    selectinload(Weapon.variants),
                ).filter(Weapon.id == weapon.id).first()
                
                logger.info(f"Added weapon: {weapon.model} - {weapon.weapon_name}")
                try:
                    ensure_weapon_media_dirs(weapon.to_dict(include_images=False, include_models=False))
                except Exception:
                    pass
                return weapon
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to add weapon: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return None
    
    def update_weapon(self, weapon_id: int, updates: Dict[str, Any]) -> Optional[Weapon]:
        """Update existing weapon"""
        try:
            with self.get_session() as session:
                weapon = session.query(Weapon).filter(Weapon.id == weapon_id).first()
                if not weapon:
                    return None
                
                # Update allowed fields only
                allowed_fields = [c.name for c in Weapon.__table__.columns]
                for key, value in updates.items():
                    if key in allowed_fields and key not in ['id', 'created_at']:
                        setattr(weapon, key, value)
                
                session.commit()
                session.refresh(weapon)
                weapon = session.query(Weapon).options(
                    joinedload(Weapon.category),
                    joinedload(Weapon.country),
                    joinedload(Weapon.guidance),
                    joinedload(Weapon.propulsion),
                    selectinload(Weapon.images),
                    selectinload(Weapon.models),
                    selectinload(Weapon.variants),
                ).filter(Weapon.id == weapon.id).first()
                logger.info(f"Updated weapon: {weapon.model}")
                return weapon
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to update weapon: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return None
    
    def delete_weapon(self, weapon_id: int) -> bool:
        """Delete weapon and cascade to images/variants"""
        try:
            with self.get_session() as session:
                weapon = session.query(Weapon).filter(Weapon.id == weapon_id).first()
                if not weapon:
                    return False
                
                session.delete(weapon)
                session.commit()
                logger.info(f"Deleted weapon: {weapon.model} (id={weapon_id})")
                return True
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to delete weapon: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return False

    def add_weapon_image(self, weapon_id: int, image_path: str, is_primary: bool = False, caption: Optional[str] = None) -> bool:
        """Attach image to weapon gallery and optionally set as primary."""
        try:
            with self.get_session() as session:
                weapon = session.query(Weapon).filter(Weapon.id == weapon_id).first()
                if not weapon:
                    return False
                normalized_path = str(Path(image_path).expanduser().resolve(strict=False))
                if is_primary:
                    session.query(WeaponImage).filter(WeaponImage.weapon_id == weapon_id).update(
                        {"is_primary": False}
                    )
                existing = None
                existing_images = session.query(WeaponImage).filter(WeaponImage.weapon_id == weapon_id).all()
                for row in existing_images:
                    row_norm = str(Path(row.image_path).expanduser().resolve(strict=False))
                    if row_norm.lower() == normalized_path.lower():
                        existing = row
                        break
                if existing:
                    existing.is_primary = bool(is_primary) if is_primary else existing.is_primary
                    if caption is not None:
                        existing.caption = caption
                else:
                    img = WeaponImage(
                        weapon_id=weapon_id,
                        image_path=normalized_path,
                        is_primary=bool(is_primary),
                        caption=caption,
                        display_order=len(existing_images),
                    )
                    session.add(img)
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add weapon image: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"Unexpected error in add_weapon_image: {e}", exc_info=True)
            try:
                session.rollback()
            except Exception:
                pass
            return False

    def add_weapon_images_batch(
        self,
        weapon_id: int,
        image_paths: List[str],
        set_first_as_primary: bool = False,
    ) -> Tuple[int, int]:
        """
        Add multiple gallery images in one transaction.
        Returns (added_count, skipped_or_updated_count).
        """
        if not image_paths:
            return (0, 0)
        added = 0
        skipped = 0
        try:
            with self.get_session() as session:
                weapon = session.query(Weapon).filter(Weapon.id == weapon_id).first()
                if not weapon:
                    return (0, 0)
                existing_images = (
                    session.query(WeaponImage).filter(WeaponImage.weapon_id == weapon_id).all()
                )
                for i, raw_path in enumerate(image_paths):
                    normalized_path = str(Path(raw_path).expanduser().resolve(strict=False))
                    if not Path(normalized_path).is_file():
                        skipped += 1
                        continue
                    is_primary = bool(set_first_as_primary and i == 0)
                    if is_primary:
                        session.query(WeaponImage).filter(WeaponImage.weapon_id == weapon_id).update(
                            {"is_primary": False}
                        )
                    existing = None
                    for row in existing_images:
                        row_norm = str(Path(row.image_path).expanduser().resolve(strict=False))
                        if row_norm.lower() == normalized_path.lower():
                            existing = row
                            break
                    if existing:
                        if is_primary:
                            existing.is_primary = True
                        skipped += 1
                        continue
                    img = WeaponImage(
                        weapon_id=weapon_id,
                        image_path=normalized_path,
                        is_primary=is_primary,
                        caption=None,
                        display_order=len(existing_images) + added,
                    )
                    session.add(img)
                    existing_images.append(img)
                    added += 1
                session.commit()
                return (added, skipped)
        except SQLAlchemyError as e:
            logger.error(f"Failed batch add weapon images: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return (added, skipped)

    def add_weapon_model(self, weapon_id: int, model_path: str, is_primary: bool = True, caption: Optional[str] = None) -> bool:
        """Attach a 3D model to weapon and optionally set as primary."""
        try:
            with self.get_session() as session:
                weapon = session.query(Weapon).filter(Weapon.id == weapon_id).first()
                if not weapon:
                    return False
                normalized_path = str(Path(model_path).expanduser().resolve(strict=False))
                model_ext = Path(normalized_path).suffix.lower().lstrip(".")
                if is_primary:
                    session.query(WeaponModel).filter(WeaponModel.weapon_id == weapon_id).update(
                        {"is_primary": False}
                    )
                existing = None
                existing_models = session.query(WeaponModel).filter(WeaponModel.weapon_id == weapon_id).all()
                for row in existing_models:
                    row_norm = str(Path(row.model_path).expanduser().resolve(strict=False))
                    if row_norm.lower() == normalized_path.lower():
                        existing = row
                        break
                if existing:
                    existing.is_primary = bool(is_primary) if is_primary else existing.is_primary
                    existing.model_format = model_ext
                    if caption is not None:
                        existing.caption = caption
                else:
                    mdl = WeaponModel(
                        weapon_id=weapon_id,
                        model_path=normalized_path,
                        model_format=model_ext,
                        is_primary=bool(is_primary),
                        caption=caption,
                        display_order=len(existing_models),
                    )
                    session.add(mdl)
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add weapon model: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"Unexpected error in add_weapon_images_batch: {e}", exc_info=True)
            try:
                session.rollback()
            except Exception:
                pass
            return (added, skipped)

    def save_weapon_swot_report(
        self,
        weapon_id: int,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Persist a new SWOT report version for a weapon."""
        try:
            with self.get_session() as session:
                weapon = session.query(Weapon).filter(Weapon.id == int(weapon_id)).first()
                if not weapon:
                    return None
                report = WeaponSwotReport(
                    weapon_id=int(weapon_id),
                    analyst=str(payload.get("analyst") or "").strip(),
                    scenario=str(payload.get("scenario") or "").strip(),
                    strengths=json.dumps(payload.get("strengths") or []),
                    weaknesses=json.dumps(payload.get("weaknesses") or []),
                    opportunities=json.dumps(payload.get("opportunities") or []),
                    threats=json.dumps(payload.get("threats") or []),
                    recommendations=str(payload.get("recommendations") or "").strip(),
                    score_summary=json.dumps(payload.get("score_summary") or {}),
                )
                session.add(report)
                session.commit()
                session.refresh(report)
                return report.to_dict()
        except Exception as e:
            logger.warning(f"save_weapon_swot_report failed: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return None

    def get_weapon_swot_reports(self, weapon_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Return SWOT report history for weapon, newest first."""
        try:
            with self.get_session() as session:
                rows = (
                    session.query(WeaponSwotReport)
                    .filter(WeaponSwotReport.weapon_id == int(weapon_id))
                    .order_by(WeaponSwotReport.created_at.desc(), WeaponSwotReport.id.desc())
                    .limit(int(limit))
                    .all()
                )
                return [r.to_dict() for r in rows]
        except Exception as e:
            logger.warning(f"get_weapon_swot_reports failed: {e}")
            return []

    def get_latest_weapon_swot_report(self, weapon_id: int) -> Optional[Dict[str, Any]]:
        reports = self.get_weapon_swot_reports(int(weapon_id), limit=1)
        return reports[0] if reports else None

    def save_weapon_ai_cache(
        self,
        weapon_id: int,
        cache_key: str,
        language_code: str,
        content_text: str = "",
        content_json: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Upsert latest AI content snapshot for a weapon/context/language."""
        try:
            with self.get_session() as session:
                wid = int(weapon_id)
                weapon = session.query(Weapon).filter(Weapon.id == wid).first()
                if not weapon:
                    return None
                key = str(cache_key or "").strip()
                if not key:
                    return None
                lang = str(language_code or "en").strip().lower() or "en"
                row = (
                    session.query(WeaponAiCache)
                    .filter(
                        WeaponAiCache.weapon_id == wid,
                        WeaponAiCache.cache_key == key,
                        WeaponAiCache.language_code == lang,
                    )
                    .first()
                )
                if row is None:
                    row = WeaponAiCache(
                        weapon_id=wid,
                        cache_key=key,
                        language_code=lang,
                    )
                    session.add(row)
                row.content_text = str(content_text or "")
                row.content_json = json.dumps(content_json or {}, ensure_ascii=False)
                row.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(row)
                return row.to_dict()
        except Exception as e:
            logger.warning(f"save_weapon_ai_cache failed: {e}")
            try:
                session.rollback()
            except Exception:
                pass
            return None

    def get_weapon_ai_cache(
        self,
        weapon_id: int,
        cache_key: str,
        language_code: str,
    ) -> Optional[Dict[str, Any]]:
        """Get latest AI content snapshot for weapon/context/language."""
        try:
            with self.get_session() as session:
                wid = int(weapon_id)
                key = str(cache_key or "").strip()
                lang = str(language_code or "en").strip().lower() or "en"
                row = (
                    session.query(WeaponAiCache)
                    .filter(
                        WeaponAiCache.weapon_id == wid,
                        WeaponAiCache.cache_key == key,
                        WeaponAiCache.language_code == lang,
                    )
                    .first()
                )
                if row:
                    return row.to_dict()
                if lang != "en":
                    fallback = (
                        session.query(WeaponAiCache)
                        .filter(
                            WeaponAiCache.weapon_id == wid,
                            WeaponAiCache.cache_key == key,
                            WeaponAiCache.language_code == "en",
                        )
                        .first()
                    )
                    if fallback:
                        return fallback.to_dict()
                return None
        except Exception as e:
            logger.warning(f"get_weapon_ai_cache failed: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # TILE CACHE OPERATIONS (Offline Map Support)
    # -------------------------------------------------------------------------
    
    def add_cached_tile(
        self, 
        basemap: str, 
        zoom: int, 
        x: int, 
        y: int,
        file_path: str, 
        file_size: int,
        checksum: Optional[str] = None
    ) -> Optional[TileCacheIndex]:
        """Record a downloaded tile in cache index"""
        try:
            with self.get_session() as session:
                # Check if tile already exists
                existing = session.query(TileCacheIndex).filter(
                    TileCacheIndex.basemap_name == basemap,
                    TileCacheIndex.zoom_level == zoom,
                    TileCacheIndex.tile_x == x,
                    TileCacheIndex.tile_y == y
                ).first()
                
                if existing:
                    # Update access stats only
                    existing.access_count = (existing.access_count or 1) + 1
                    existing.last_accessed = datetime.utcnow()
                    session.commit()
                    return existing
                
                # Add new tile record
                tile = TileCacheIndex(
                    basemap_name=basemap,
                    zoom_level=zoom,
                    tile_x=x,
                    tile_y=y,
                    file_path=file_path,
                    file_size_bytes=file_size,
                    downloaded_at=datetime.utcnow(),
                    last_accessed=datetime.utcnow(),
                    access_count=1,
                    checksum_sha256=checksum
                )
                session.add(tile)
                session.commit()
                return tile
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to index cached tile: {e}")
            return None
    
    def get_cached_tile_path(
        self, 
        basemap: str, 
        zoom: int, 
        x: int, 
        y: int
    ) -> Optional[str]:
        """Get local file path for cached tile, or None if not cached"""
        try:
            with self.get_session() as session:
                tile = session.query(TileCacheIndex).filter(
                    TileCacheIndex.basemap_name == basemap,
                    TileCacheIndex.zoom_level == zoom,
                    TileCacheIndex.tile_x == x,
                    TileCacheIndex.tile_y == y
                ).first()
                
                if tile and Path(tile.file_path).exists():
                    # Update access stats
                    tile.access_count = (tile.access_count or 1) + 1
                    tile.last_accessed = datetime.utcnow()
                    session.commit()
                    return tile.file_path
                return None
                
        except SQLAlchemyError as e:
            logger.error(f"Failed to lookup cached tile: {e}")
            return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get tile cache statistics"""
        with self.get_session() as session:
            total_tiles = session.query(func.count(TileCacheIndex.id)).scalar() or 0
            total_size = session.query(func.sum(TileCacheIndex.file_size_bytes)).scalar() or 0
            
            basemap_stats = session.query(
                TileCacheIndex.basemap_name,
                func.count(TileCacheIndex.id),
                func.sum(TileCacheIndex.file_size_bytes)
            ).group_by(TileCacheIndex.basemap_name).all()
            
            return {
                'total_tiles': total_tiles,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'total_size_gb': round(total_size / (1024 * 1024 * 1024), 3),
                'basemaps_cached': [
                    {
                        'name': row[0],
                        'tile_count': row[1],
                        'size_mb': round((row[2] or 0) / (1024 * 1024), 2)
                    }
                    for row in basemap_stats
                ],
                'cache_dir': TILE_CACHE_CONFIG['cache_dir'],
                'last_updated': datetime.utcnow().isoformat(),
            }
    
    def cleanup_old_cache(self, max_age_days: int = 90) -> int:
        """Remove cache entries older than max_age_days, return count deleted"""
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        deleted_count = 0
        
        try:
            with self.get_session() as session:
                # Get files to delete first
                old_tiles = session.query(TileCacheIndex).filter(
                    TileCacheIndex.last_accessed < cutoff
                ).all()
                
                # Delete files from disk
                for tile in old_tiles:
                    try:
                        tile_path = Path(tile.file_path)
                        if tile_path.exists():
                            tile_path.unlink()
                            deleted_count += 1
                    except OSError as e:
                        logger.warning(f"Failed to delete cache file {tile.file_path}: {e}")
                
                # Delete DB records
                result = session.execute(
                    delete(TileCacheIndex).where(TileCacheIndex.last_accessed < cutoff)
                )
                session.commit()
                
                db_deleted = result.rowcount
                logger.info(f"Cache cleanup: deleted {deleted_count} files, {db_deleted} records")
                return deleted_count
                
        except SQLAlchemyError as e:
            logger.error(f"Cache cleanup failed: {e}")
            return 0
    
    def export_cache_index(self, output_path: str) -> bool:
        """Export cache index to JSON for backup/migration"""
        try:
            with self.get_session() as session:
                tiles = session.query(TileCacheIndex).all()
                export_data = {
                    'exported_at': datetime.utcnow().isoformat(),
                    'total_tiles': len(tiles),
                    'tiles': [t.to_dict() for t in tiles]
                }
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, default=str)
                
                logger.info(f"Exported cache index: {output_path}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to export cache index: {e}")
            return False
    
    def import_cache_index(self, input_path: str) -> int:
        """Import cache index from JSON, return count imported"""
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            imported = 0
            with self.get_session() as session:
                for tile_data in import_data.get('tiles', []):
                    # Skip if already exists
                    existing = session.query(TileCacheIndex).filter(
                        TileCacheIndex.basemap_name == tile_data['basemap_name'],
                        TileCacheIndex.zoom_level == tile_data['zoom_level'],
                        TileCacheIndex.tile_x == tile_data['tile_x'],
                        TileCacheIndex.tile_y == tile_data['tile_y']
                    ).first()
                    
                    if not existing and Path(tile_data['file_path']).exists():
                        tile = TileCacheIndex(**tile_data)
                        session.add(tile)
                        imported += 1
                
                session.commit()
            
            logger.info(f"Imported {imported} cache entries from {input_path}")
            return imported
            
        except Exception as e:
            logger.error(f"Failed to import cache index: {e}")
            return 0


def init_database(engine):
    """
    Initialize database schema from SQL file
    
    Args:
        engine: SQLAlchemy engine instance
    """
    schema_path = Path(__file__).parent / 'schema.sql'
    
    if not schema_path.exists():
        logger.warning(f"Schema file not found: {schema_path}")
        return
    
    try:
        with engine.connect() as conn:
            schema_sql = schema_path.read_text(encoding='utf-8')
            # Keep startup deterministic: initialize schema only, never apply seed data.
            # Seed/import scripts can still be run manually when desired.
            seed_marker = "-- SEED DATA"
            if seed_marker in schema_sql:
                schema_sql = schema_sql.split(seed_marker, 1)[0]
            
            # Split and execute statements (handle SQLite-specific syntax)
            statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
            
            for statement in statements:
                if statement and not statement.startswith('--'):
                    try:
                        conn.execute(text(statement))
                    except Exception as e:
                        # Some statements may fail on PostgreSQL vs SQLite - log and continue
                        if 'VIRTUAL TABLE' not in str(e) and 'fts5' not in str(e).lower():
                            logger.debug(f"Schema statement skipped: {e}")
            
            conn.commit()
        
        # ORM model columns are intentionally lightweight for flexible schema use,
        # so we rely on the SQL schema script as the source of truth.
        logger.info("Database schema initialized")
        
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise