from PyQt6.QtCore import QSortFilterProxyModel, Qt, QModelIndex

class WeaponSortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.filter_values = {} # col_index -> value

    def set_filter(self, col_idx: int, value: str):
        self.filter_values[col_idx] = value
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        for col_idx, value in self.filter_values.items():
            if not value: continue # No filter active
            
            index = self.sourceModel().index(source_row, col_idx, source_parent)
            cell_text = str(self.sourceModel().data(index, Qt.ItemDataRole.DisplayRole)).lower()
            
            if value.lower() not in cell_text:
                return False
        return True