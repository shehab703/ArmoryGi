from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Weapon(Base):
    __tablename__ = 'weapons'
    
    id = Column(Integer, primary_key=True)
    model = Column(String, nullable=False)
    weapon_name = Column(String, nullable=False)
    category = Column(String)
    country = Column(String)
    
    length_m = Column(Float)
    diameter_m = Column(Float)
    weight_kg = Column(Float)
    
    warhead_type = Column(String)
    warhead_weight_kg = Column(Float)
    
    range_km = Column(Float)
    speed_mach = Column(Float)
    
    guidance = Column(String)
    propulsion = Column(String)
    platform = Column(String)
    status = Column(String)
    
    manufacturer = Column(String)
    intro_year = Column(Integer)
    unit_cost_usd = Column(Float)
    notes = Column(Text)
    
    origin_lat = Column(Float, default=31.5)
    origin_lon = Column(Float, default=34.8)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}