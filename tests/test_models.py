from PyQt6.QtWidgets import QApplication
from models.weapon_model import WeaponTableModel

def test_model_loads_data():
    data = [{"id": 1, "weapon_name": "Test", "range_km": 100}]
    model = WeaponTableModel(data)
    assert model.rowCount() == 1
    assert model.columnCount() > 0

def test_model_header():
    model = WeaponTableModel([])
    assert model.headerData(0, 0) == "ID"
    assert model.headerData(2, 0) == "Name"