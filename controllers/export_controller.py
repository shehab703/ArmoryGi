from utils.exporters import Exporter

class ExportController:
    def __init__(self, db_manager):
        self.db = db_manager

    def export_data(self, file_path, fmt, data=None):
        if data is None:
            data = self.db.get_weapons_paginated(0, 5000)
            
        exp = Exporter(data)
        if fmt == "csv":
            exp.to_csv(file_path)
        elif fmt == "xlsx":
            exp.to_excel(file_path)
        elif fmt == "json":
            exp.to_json(file_path)
        return True