"""Shared Qt UI helpers for scrollable dialogs and forms."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QApplication,
)


def make_scroll_content(inner_widget: QWidget, parent: QWidget | None = None) -> QScrollArea:
    """Wrap *inner_widget* in a vertical scroll area suitable for dialogs/tabs."""
    scroll = QScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(inner_widget)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return scroll


def fit_dialog_to_screen(dialog, width: int = 560, height: int = 680) -> None:
    """Resize dialog to fit within ~85% of available screen height."""
    try:
        screen = dialog.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            height = min(height, int(geo.height() * 0.85))
            width = min(width, geo.width() - 40)
    except Exception:
        pass
    dialog.setMinimumSize(520, 480)
    dialog.resize(width, height)


def apply_app_typography(app=None, bold: bool = True, point_size: int | None = None) -> None:
    """Apply consistent bold typography across the application."""
    app = app or QApplication.instance()
    if app is None:
        return
    font = app.font()
    if point_size is not None:
        font.setPointSize(point_size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    app.setFont(font)


class WrapCenterDelegate(QStyledItemDelegate):
    """Table/list delegate: word-wrap + horizontal/vertical center alignment."""

    def __init__(self, parent=None, min_row_height: int = 36):
        super().__init__(parent)
        self._min_row_height = max(28, int(min_row_height))

    def initStyleOption(self, option: QStyleOptionViewItem, index):
        super().initStyleOption(option, index)
        option.displayAlignment = (
            Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
            | Qt.TextFlag.TextWordWrap
        )
        font = option.font
        font.setWeight(QFont.Weight.DemiBold)
        option.font = font

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        text = str(index.data() or "")
        if not text:
            return QSize(hint.width(), self._min_row_height)
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        width = max(option.rect.width(), 120)
        bounds = option.fontMetrics.boundingRect(
            0, 0, width, 10000,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap),
            text,
        )
        return QSize(hint.width(), max(self._min_row_height, bounds.height() + 10))


def style_data_table(table, min_row_height: int = 38) -> None:
    """Apply professional data-table presentation defaults."""
    table.setWordWrap(True)
    table.setTextElideMode(Qt.TextElideMode.ElideNone)
    table.setAlternatingRowColors(True)
    table.setShowGrid(True)
    table.setGridStyle(Qt.PenStyle.SolidLine)
    table.setItemDelegate(WrapCenterDelegate(table, min_row_height=min_row_height))
    header = table.horizontalHeader()
    if header is not None:
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        hf = header.font()
        hf.setWeight(QFont.Weight.Bold)
        header.setFont(hf)
    vheader = table.verticalHeader()
    if vheader is not None:
        vheader.setDefaultSectionSize(min_row_height)
    table.setStyleSheet(
        (table.styleSheet() or "")
        + """
        QTableView {
            selection-background-color: #dbeafe;
            selection-color: #1e3a8a;
        }
        QTableView::item {
            padding: 6px 8px;
        }
        QHeaderView::section {
            font-weight: 700;
            padding: 8px 6px;
        }
        """
    )
