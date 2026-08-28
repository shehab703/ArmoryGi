import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Make the project root importable regardless of how pytest is invoked
# (pytest only prepends the test file's directory when there is no package).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine("sqlite:///:memory:")
    # The declarative Base lives with the manager that owns the mappings;
    # ``database.schema`` is a .sql file and has no importable Base.
    from database.db_manager import Base

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
