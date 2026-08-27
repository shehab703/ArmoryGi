from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from typing import List, Any, Dict

HEADERS = [
    "ID", "Model", "Name", "Category", "Country", 
    "Length (m)", "Diameter (m)", "Weight (kg)", "Warhead Type", "Warhead Wt (kg)",
    "Range (km)", "Speed (Mach)", "Guidance", "Propulsion", 
    "Platform", "Status", "Manufacturer", "Year", "Notes", "Lat", "Lon"
]

class WeaponTableModel(QAbstractTableModel):
    def __init__(self, data: List[Dict[str, Any]] = None):
        super().__init__()
        self._data = data or []

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        
        item = self._data[index.row()]
        col = index.column()
        key = HEADERS[col].lower().replace(" ", "_").replace("(m)", "m").replace("(kg)", "kg").replace("(km)", "km").replace("(mach)", "mach")
        # Simple mapping fallback if keys don't match perfectly
        if key not in item and col == 2: key = "weapon_name"
        
        val = item.get(key)
        return val if val is not None else "--"

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(HEADERS)

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.EditRole:
            row = index.row()
            col = index.column()
            key = HEADERS[col].lower().replace(" ", "_").replace("(m)", "m").replace("(kg)", "kg").replace("(km)", "km").replace("(mach)", "mach")
            if key in self._data[row]:
                self._data[row][key] = value
                self.dataChanged.emit(index, index)
                return True
        return False

    def get_weapon_dict(self, row: int) -> Dict[str, Any]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return {}