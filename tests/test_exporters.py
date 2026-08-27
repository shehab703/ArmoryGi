import os
import json
from utils.exporters import Exporter

def test_export_json(tmp_path):
    data = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    exp = Exporter(data)
    path = str(tmp_path / "test.json")
    exp.to_json(path)
    
    assert os.path.exists(path)
    with open(path) as f:
        loaded = json.load(f)
    assert len(loaded) == 2
    assert loaded[0]["name"] == "A"