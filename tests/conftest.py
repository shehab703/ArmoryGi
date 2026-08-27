import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import APP_CONFIG

@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    from database.schema import Base
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def sample_weapon_data():
    return {
        "model": "TEST-001",
        "weapon_name": "Test Missile",
        "category": "Air-to-Air",
        "country": "USA",
        "range_km": 150.0,
        "speed_mach": 3.5,
        "status": "operational"
    }