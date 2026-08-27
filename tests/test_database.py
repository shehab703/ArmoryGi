def test_add_weapon(db_session, sample_weapon_data):
    from database.db_manager import DatabaseManager
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