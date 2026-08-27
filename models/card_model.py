from PyQt6.QtCore import QAbstractListModel, Qt, QModelIndex, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap
from typing import List, Dict, Any
from pathlib import Path
from config import APP_CONFIG

class WeaponCardModel(QAbstractListModel):
    ImageLoaded = pyqtSignal(QModelIndex, QPixmap)

    def __init__(self, data: List[Dict[str, Any]] = None):
        super().__init__()
        self._data = data or []
        self._thumbnails = {} # cache

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid(): return None
        weapon = self._data[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return weapon.get('weapon_name', 'Unknown')
        elif role == Qt.ItemDataRole.UserRole:
            return weapon # Full dict
        elif role == Qt.ItemDataRole.DecorationRole:
            return self._get_thumbnail(weapon, index)
        return None

    def _get_thumbnail(self, weapon: Dict, index: QModelIndex) -> QPixmap:
        wid = weapon.get('id')
        if wid in self._thumbnails:
            return self._thumbnails[wid]
        
        # Placeholder logic - in real app, load from path in DB
        pixmap = QPixmap(100, 80)
        pixmap.fill(Qt.GlobalColor.darkGray)
        self._thumbnails[wid] = pixmap
        return pixmap

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def set_data(self, data: List[Dict[str, Any]]):
        self.beginResetModel()
        self._data = data
        self._thumbnails.clear()
        self.endResetModel()