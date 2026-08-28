from pathlib import Path

from database.db_manager import DatabaseManager


def test_add_weapon(db_session, sample_weapon_data):
    mgr = DatabaseManager("sqlite:///:memory:")
    mgr.init_tables()
    
    weapon = mgr.add_weapon(sample_weapon_data)
    assert weapon is not None
    assert weapon.model == "TEST-001"
    assert weapon.range_km == 150.0

def test_get_weapons(db_session, sample_weapon_data):
    mgr = DatabaseManager("sqlite:///:memory:")
    mgr.init_tables()
    mgr.add_weapon(sample_weapon_data)
    
    results = mgr.get_weapons_paginated(0, 10)
    assert len(results) == 1
    assert results[0]["model"] == "TEST-001"

def test_add_weapon_model_error_path_returns_false():
    """The broad except in add_weapon_model used to raise NameError (`added`, `skipped`
    were copied from add_weapon_images_batch) instead of reporting failure."""
    mgr = DatabaseManager("sqlite:///:memory:")
    mgr.init_tables()
    weapon = mgr.add_weapon({"model": "MODEL-1", "weapon_name": "Model Fixture"})
    assert weapon is not None
    assert mgr.add_weapon_model(weapon.id, None) is False
    assert mgr.add_weapon_model(weapon.id, str(Path(__file__).parent / "does-not-exist.obj")) is True


def test_add_weapon_creates_missing_lookup_rows():
    mgr = DatabaseManager("sqlite:///:memory:")
    mgr.init_tables()
    weapon = mgr.add_weapon({
        "model": "LOOKUP-1",
        "weapon_name": "Lookup Fixture",
        "category": "Ballistic",
        "country": "Testland",
        "guidance": "INS",
    })
    assert weapon is not None
    data = weapon.to_dict(include_images=False, include_models=False)
    assert data["category"] == "Ballistic"
    assert data["country"] == "Testland"
