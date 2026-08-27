#!/usr/bin/env python3
"""
Seed initial weapon data for ArmoryGIS Pro
Run after database initialization to populate with sample data
"""
import logging
from pathlib import Path
from typing import List, Dict

from sqlalchemy.orm import Session

from config import APP_CONFIG
from database.db_manager import DatabaseManager, Weapon, Category, Country, GuidanceType, PropulsionType

logger = logging.getLogger(__name__)

# Sample weapon data (US and Israel as per requirements)
SAMPLE_WEAPONS: List[Dict] = [
    # US Air-to-Air Missiles
    {
        'model': 'AIM-9X', 'weapon_name': 'Sidewinder Block II',
        'category': 'Air-to-Air Missile', 'country': 'United States',
        'length_m': 3.02, 'diameter_m': 0.127, 'weight_kg': 85,
        'warhead_type': 'Blast-fragmentation', 'warhead_weight_kg': 4.5,
        'range_km': 35, 'speed_mach': 3.1,
        'guidance': 'Imaging Infrared', 'propulsion': 'Solid Rocket',
        'platform': 'F-15, F-16, F-22, F-35', 'status': 'operational',
        'manufacturer': 'Raytheon', 'intro_year': 2003,
        'origin_lat': 38.8977, 'origin_lon': -77.0365,
        'notes': 'All-aspect engagement, helmet-mounted cueing compatible'
    },
    {
        'model': 'AIM-120D', 'weapon_name': 'AMRAAM',
        'category': 'Air-to-Air Missile', 'country': 'United States',
        'length_m': 3.66, 'diameter_m': 0.178, 'weight_kg': 157,
        'warhead_type': 'Blast-fragmentation', 'warhead_weight_kg': 18,
        'range_km': 105, 'speed_mach': 4.9,
        'guidance': 'Active Radar + INS + Datalink', 'propulsion': 'Solid Rocket',
        'platform': 'F-15, F-16, F-22, F-35', 'status': 'operational',
        'manufacturer': 'Raytheon', 'intro_year': 2014,
        'origin_lat': 38.8977, 'origin_lon': -77.0365,
        'notes': 'Beyond-visual-range, fire-and-forget capability'
    },
    # US Guided Bombs
    {
        'model': 'GBU-12', 'weapon_name': 'Paveway II',
        'category': 'Guided Bomb Unit', 'country': 'United States',
        'length_m': 3.3, 'diameter_m': 0.273, 'weight_kg': 250,
        'warhead_type': 'Mk 82 GP', 'warhead_weight_kg': 89,
        'range_km': 11, 'speed_mach': None,
        'guidance': 'Semi-Active Laser', 'propulsion': 'None (Glide)',
        'platform': 'F-16, F/A-18, A-10', 'status': 'operational',
        'manufacturer': 'Lockheed Martin/Raytheon', 'intro_year': 1976,
        'origin_lat': 38.8977, 'origin_lon': -77.0365,
        'notes': 'Laser-guided variant of Mk 82 general purpose bomb'
    },
    {
        'model': 'GBU-31', 'weapon_name': 'JDAM Mk 84',
        'category': 'Guided Bomb Unit', 'country': 'United States',
        'length_m': 3.88, 'diameter_m': 0.457, 'weight_kg': 907,
        'warhead_type': 'Mk 84 GP', 'warhead_weight_kg': 429,
        'range_km': 24, 'speed_mach': None,
        'guidance': 'GPS/INS', 'propulsion': 'None (Glide)',
        'platform': 'B-2, B-52, F-15E, F-16, F-35', 'status': 'operational',
        'manufacturer': 'Boeing', 'intro_year': 1999,
        'origin_lat': 38.8977, 'origin_lon': -77.0365,
        'notes': 'All-weather precision guidance kit for existing munitions'
    },
    # US Anti-Ship/Cruise Missiles
    {
        'model': 'AGM-84D', 'weapon_name': 'Harpoon',
        'category': 'Anti-Ship Missile', 'country': 'United States',
        'length_m': 4.6, 'diameter_m': 0.343, 'weight_kg': 628,
        'warhead_type': 'Blast-fragmentation', 'warhead_weight_kg': 221,
        'range_km': 120, 'speed_mach': 0.85,
        'guidance': 'Active Radar + INS', 'propulsion': 'Turbojet',
        'platform': 'F/A-18, P-8, ships', 'status': 'operational',
        'manufacturer': 'Boeing', 'intro_year': 1977,
        'origin_lat': 38.8977, 'origin_lon': -77.0365,
        'notes': 'Sea-skimming anti-ship missile with active radar terminal guidance'
    },
    {
        'model': 'AGM-158C', 'weapon_name': 'LRASM',
        'category': 'Anti-Ship Missile', 'country': 'United States',
        'length_m': 4.27, 'diameter_m': 0.457, 'weight_kg': 1250,
        'warhead_type': 'Penetrating blast-fragmentation', 'warhead_weight_kg': 450,
        'range_km': 560, 'speed_mach': 0.9,
        'guidance': 'GPS/INS + MMW Radar + IR + ESM', 'propulsion': 'Turbofan',
        'platform': 'B-1B, F/A-18, F-35', 'status': 'operational',
        'manufacturer': 'Lockheed Martin', 'intro_year': 2014,
        'origin_lat': 38.8977, 'origin_lon': -77.0365,
        'notes': 'Long-Range Anti-Ship Missile with advanced autonomous targeting'
    },
    # Israel Air-to-Air Missiles
    {
        'model': 'Python-5', 'weapon_name': 'Python-5',
        'category': 'Air-to-Air Missile', 'country': 'Israel',
        'length_m': 3.10, 'diameter_m': 0.160, 'weight_kg': 105,
        'warhead_type': 'Blast-fragmentation', 'warhead_weight_kg': 11,
        'range_km': 20, 'speed_mach': 4.0,
        'guidance': 'IIR + EO imaging + LOAL', 'propulsion': 'Solid Rocket',
        'platform': 'F-15, F-16, F-35I', 'status': 'operational',
        'manufacturer': 'RAFAEL', 'intro_year': 2005,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Full-sphere engagement with lock-on after launch capability'
    },
    {
        'model': 'Derby', 'weapon_name': 'Derby BVR',
        'category': 'Air-to-Air Missile', 'country': 'Israel',
        'length_m': 3.62, 'diameter_m': 0.160, 'weight_kg': 118,
        'warhead_type': 'Blast-fragmentation', 'warhead_weight_kg': 23,
        'range_km': 50, 'speed_mach': 4.0,
        'guidance': 'Active Radar + INS', 'propulsion': 'Solid Rocket',
        'platform': 'F-15, F-16, Gripen', 'status': 'operational',
        'manufacturer': 'RAFAEL', 'intro_year': 1996,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Beyond-visual-range missile with active radar homing'
    },
    # Israel Anti-Tank Missiles
    {
        'model': 'Spike-LR', 'weapon_name': 'Spike Long-Range',
        'category': 'Anti-Tank Guided Missile', 'country': 'Israel',
        'length_m': 1.4, 'diameter_m': 0.100, 'weight_kg': 14,
        'warhead_type': 'Tandem HEAT', 'warhead_weight_kg': 3.5,
        'range_km': 5.5, 'speed_mach': None,
        'guidance': 'EO/CCD + Fiber optic/RF', 'propulsion': 'Solid Rocket',
        'platform': 'Infantry, vehicles, helicopters', 'status': 'operational',
        'manufacturer': 'RAFAEL', 'intro_year': 2003,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Fire-and-forget or man-in-the-loop guidance options'
    },
    {
        'model': 'Spike-NLOS', 'weapon_name': 'Spike Non-Line-of-Sight',
        'category': 'Anti-Tank Guided Missile', 'country': 'Israel',
        'length_m': 1.6, 'diameter_m': 0.160, 'weight_kg': 70,
        'warhead_type': 'Tandem HEAT/PBF', 'warhead_weight_kg': 35,
        'range_km': 25, 'speed_mach': 0.8,
        'guidance': 'EO/CCD + RF + GPS', 'propulsion': 'Solid Rocket',
        'platform': 'Ground, helicopters, ships', 'status': 'operational',
        'manufacturer': 'RAFAEL', 'intro_year': 2010,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Extended range with real-time video datalink for target selection'
    },
    # Israel Precision Bombs
    {
        'model': 'Spice 2000', 'weapon_name': 'SPICE 2000',
        'category': 'Guided Bomb Unit', 'country': 'Israel',
        'length_m': 4.3, 'diameter_m': 0.460, 'weight_kg': 907,
        'warhead_type': 'Mk-84/BLU-109', 'warhead_weight_kg': 429,
        'range_km': 60, 'speed_mach': None,
        'guidance': 'GPS/INS + EO/IR', 'propulsion': 'None (Glide)',
        'platform': 'F-15, F-16, F-35I', 'status': 'operational',
        'manufacturer': 'RAFAEL', 'intro_year': 2005,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Electro-optical terminal guidance for GPS-denied environments'
    },
    {
        'model': 'Spice 250', 'weapon_name': 'SPICE 250',
        'category': 'Guided Bomb Unit', 'country': 'Israel',
        'length_m': 1.8, 'diameter_m': 0.178, 'weight_kg': 113,
        'warhead_type': 'BLU-109-style penetrator', 'warhead_weight_kg': 17,
        'range_km': 100, 'speed_mach': None,
        'guidance': 'GPS/INS + EO/IR', 'propulsion': 'None (Glide)',
        'platform': 'F-15, F-16, F-35I', 'status': 'operational',
        'manufacturer': 'RAFAEL', 'intro_year': 2015,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Small diameter bomb with extended standoff range'
    },
    # Israel Ballistic Missiles
    {
        'model': 'Jericho-3', 'weapon_name': 'Jericho-3',
        'category': 'Ballistic Missile', 'country': 'Israel',
        'length_m': 15.5, 'diameter_m': 1.2, 'weight_kg': 15000,
        'warhead_type': 'Nuclear MIRV/Conventional', 'warhead_weight_kg': None,
        'range_km': 4000, 'speed_mach': 24,
        'guidance': 'Advanced inertial + GPS/stellar', 'propulsion': 'Solid Rocket (3-stage)',
        'platform': 'Ground mobile/silo', 'status': 'operational',
        'manufacturer': 'IAI', 'intro_year': 2000,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Intermediate-range ballistic missile for strategic deterrence'
    },
    {
        'model': 'LORA', 'weapon_name': 'LORA',
        'category': 'Ballistic Missile', 'country': 'Israel',
        'length_m': 5.2, 'diameter_m': 0.625, 'weight_kg': 1600,
        'warhead_type': 'Unitary HE/penetrator', 'warhead_weight_kg': 500,
        'range_km': 430, 'speed_mach': 6,
        'guidance': 'GPS/INS + Terminal IIR', 'propulsion': 'Solid Rocket',
        'platform': 'Ground, naval, air-launched', 'status': 'operational',
        'manufacturer': 'IAI', 'intro_year': 2010,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Quasi-ballistic missile with high precision terminal guidance'
    },
    # Israel Loitering Munitions
    {
        'model': 'Harop', 'weapon_name': 'Harop',
        'category': 'Loitering Munition', 'country': 'Israel',
        'length_m': 2.5, 'diameter_m': 0.210, 'weight_kg': 135,
        'warhead_type': 'Blast-fragmentation', 'warhead_weight_kg': 16,
        'range_km': 1000, 'speed_mach': None,
        'guidance': 'GPS/INS + Passive RF + EO', 'propulsion': 'Electric/Pusher',
        'platform': 'Ground, ships, UAV launch', 'status': 'operational',
        'manufacturer': 'IAI', 'intro_year': 2005,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Anti-radiation loitering munition with autonomous target acquisition'
    },
    {
        'model': 'SkyStriker', 'weapon_name': 'SkyStriker',
        'category': 'Loitering Munition', 'country': 'Israel',
        'length_m': 2.0, 'diameter_m': 0.150, 'weight_kg': 45,
        'warhead_type': 'Tandem HEAT/MP', 'warhead_weight_kg': 10,
        'range_km': 60, 'speed_mach': None,
        'guidance': 'EO/CCD + GPS/INS + RF', 'propulsion': 'Electric pusher',
        'platform': 'Ground, light vehicles, ships', 'status': 'operational',
        'manufacturer': 'Elbit Systems', 'intro_year': 2018,
        'origin_lat': 31.5, 'origin_lon': 34.8,
        'notes': 'Tactical loitering munition with man-in-the-loop control'
    },
]


def seed_database(db_manager: DatabaseManager, overwrite: bool = False) -> int:
    """
    Populate database with sample weapon data
    
    Args:
        db_manager: Initialized DatabaseManager instance
        overwrite: If True, clear existing data first
        
    Returns:
        Number of weapons inserted
    """
    session: Session = db_manager.get_session()
    inserted_count = 0
    
    try:
        # Optionally clear existing data
        if overwrite:
            logger.info("Clearing existing weapon data...")
            session.query(Weapon).delete()
            session.commit()
        
        # Ensure lookup tables have required entries
        _ensure_lookup_data(session)
        
        # Insert sample weapons
        for weapon_data in SAMPLE_WEAPONS:
            # Check if weapon already exists
            existing = session.query(Weapon).filter(
                Weapon.model == weapon_data['model'],
                Weapon.country_id == session.query(Country.id).filter(
                    Country.name == weapon_data['country']
                ).scalar()
            ).first()
            
            if existing and not overwrite:
                continue
            
            # Resolve foreign keys
            category = session.query(Category).filter(
                Category.name == weapon_data['category']
            ).first()
            country = session.query(Country).filter(
                Country.name == weapon_data['country']
            ).first()
            guidance = session.query(GuidanceType).filter(
                GuidanceType.name == weapon_data['guidance']
            ).first()
            propulsion = session.query(PropulsionType).filter(
                PropulsionType.name == weapon_data['propulsion']
            ).first()
            
            weapon = Weapon(
                model=weapon_data['model'],
                weapon_name=weapon_data['weapon_name'],
                category_id=category.id if category else None,
                country_id=country.id if country else None,
                length_m=weapon_data.get('length_m'),
                diameter_m=weapon_data.get('diameter_m'),
                weight_kg=weapon_data.get('weight_kg'),
                warhead_type=weapon_data.get('warhead_type'),
                warhead_weight_kg=weapon_data.get('warhead_weight_kg'),
                range_km=weapon_data.get('range_km'),
                speed_mach=weapon_data.get('speed_mach'),
                guidance_id=guidance.id if guidance else None,
                propulsion_id=propulsion.id if propulsion else None,
                platform=weapon_data.get('platform'),
                status=weapon_data.get('status'),
                manufacturer=weapon_data.get('manufacturer'),
                intro_year=weapon_data.get('intro_year'),
                origin_lat=weapon_data.get('origin_lat'),
                origin_lon=weapon_data.get('origin_lon'),
                notes=weapon_data.get('notes'),
            )
            
            session.add(weapon)
            inserted_count += 1
        
        session.commit()
        logger.info(f"Seeded {inserted_count} weapons into database")
        return inserted_count
        
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to seed database: {e}")
        raise
    finally:
        db_manager.close_session()


def _ensure_lookup_data(session: Session):
    """Ensure required lookup table entries exist"""
    
    # Categories
    required_categories = [
        ('Air-to-Air Missile', 'Missiles launched from aircraft to engage aerial targets', 'aam'),
        ('Surface-to-Air Missile', 'Ground or ship-launched missiles for air defense', 'sam'),
        ('Air-to-Surface Missile', 'Aircraft-launched missiles for ground/naval targets', 'asm'),
        ('Anti-Ship Missile', 'Missiles designed to engage surface vessels', 'ashm'),
        ('Anti-Tank Guided Missile', 'Portable or vehicle-mounted anti-armor weapons', 'atgm'),
        ('Guided Bomb Unit', 'Precision-guided unpowered munitions', 'gbu'),
        ('Cruise Missile', 'Long-range, low-altitude guided missiles', 'cruise'),
        ('Ballistic Missile', 'High-speed, high-altitude ballistic trajectory weapons', 'ballistic'),
        ('Loitering Munition', 'Drone-based precision strike weapons', 'loitering'),
    ]
    
    for name, desc, icon in required_categories:
        if not session.query(Category).filter(Category.name == name).first():
            session.add(Category(name=name, description=desc, icon_name=icon))
    
    # Countries
    required_countries = [
        ('United States', 'US', 'North America'),
        ('Israel', 'IL', 'Middle East'),
        ('Russia', 'RU', 'Europe/Asia'),
        ('China', 'CN', 'Asia'),
        ('United Kingdom', 'GB', 'Europe'),
    ]
    
    for name, iso, region in required_countries:
        if not session.query(Country).filter(Country.name == name).first():
            session.add(Country(name=name, iso_code=iso, region=region))
    
    # Guidance types
    required_guidance = [
        ('Semi-Active Laser', 'Guidance via laser designator reflection'),
        ('GPS/INS', 'Global Positioning System + Inertial Navigation'),
        ('Imaging Infrared', 'Infrared seeker with imaging capability'),
        ('Active Radar', 'Missile-mounted radar for terminal guidance'),
        ('Command Guidance', 'Remote control via datalink'),
        ('Wire-Guided', 'Physical wire connection for control'),
        ('Millimeter Wave Radar', 'High-frequency radar for all-weather operation'),
        ('EO/CCD + Fiber optic/RF', 'Electro-optical with fiber optic or RF datalink'),
    ]
    
    for name, desc in required_guidance:
        if not session.query(GuidanceType).filter(GuidanceType.name == name).first():
            session.add(GuidanceType(name=name, description=desc))
    
    # Propulsion types
    required_propulsion = [
        ('Solid Rocket', 'Single-use solid propellant motor'),
        ('Liquid Rocket', 'Liquid propellant with throttling capability'),
        ('Turbojet', 'Air-breathing jet engine for cruise missiles'),
        ('Ramjet', 'High-speed air-breathing propulsion'),
        ('None (Glide)', 'Unpowered glide from release altitude'),
        ('Electric Motor', 'Battery-powered for loitering munitions'),
    ]
    
    for name, desc in required_propulsion:
        if not session.query(PropulsionType).filter(PropulsionType.name == name).first():
            session.add(PropulsionType(name=name, description=desc))
    
    session.commit()


if __name__ == '__main__':
    # Standalone execution for seeding
    import sys
    
    db_url = sys.argv[1] if len(sys.argv) > 1 else APP_CONFIG['database_url']
    overwrite = '--overwrite' in sys.argv
    
    print(f"ArmoryGIS Pro - Database Seeder")
    print(f"Database: {db_url}")
    print(f"Overwrite existing: {overwrite}")
    print("-" * 50)
    
    db_manager = DatabaseManager(db_url)
    db_manager.init_tables()
    
    count = seed_database(db_manager, overwrite=overwrite)
    
    print(f"\n✅ Successfully seeded {count} weapons")
    print("Run 'python main.py' to launch ArmoryGIS Pro")