"""Custom delegates for the Calibration Manager tables.

Delegates
---------
StatusLEDDelegate
    Paints a coloured circle (red/amber/green/orange) in the Status column
    based on the :class:`~constants.CalStatus` value.

RepairButtonDelegate
    Shows a "Repair" push-button in rows where corruption is detected.
"""

from __future__ import annotations

from qtpy.QtCore import QModelIndex, QRect, QSize, Qt, Signal  # type: ignore
from qtpy.QtGui import QColor, QPainter  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QStyle,
    QStyleOptionButton,
    QStyledItemDelegate,
    QApplication,
    QWidget,
)

from snapwrap.calibrationManager.constants import CalStatus, STATUS_COLOUR

# Colour map  → QColor
_QCOLOURS = {
    "green": QColor(0x2E, 0xCC, 0x40),
    "amber": QColor(0xFF, 0xA5, 0x00),
    "red": QColor(0xFF, 0x41, 0x36),
    "orange": QColor(0xFF, 0x85, 0x1B),
}

_LED_RADIUS = 8


class StatusLEDDelegate(QStyledItemDelegate):
    """Paints a solid coloured circle representing calibration status."""

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        # Let the default draw the background / selection highlight
        self.initStyleOption(option, index)
        QApplication.style().drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter)

        value = index.data(Qt.UserRole)
        if not isinstance(value, CalStatus):
            return

        colour = _QCOLOURS.get(STATUS_COLOUR.get(value, ""), QColor(Qt.gray))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(colour)
        painter.setPen(Qt.NoPen)

        centre = option.rect.center()
        painter.drawEllipse(centre, _LED_RADIUS, _LED_RADIUS)
        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(_LED_RADIUS * 3, _LED_RADIUS * 3)


class RepairButtonDelegate(QStyledItemDelegate):
    """Renders a clickable "Repair" button when the row is flagged corrupt.

    Emits :pyqtSignal:`repairRequested(str)` with the stateID.
    """

    repairRequested = Signal(str)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        is_corrupt = index.data(Qt.UserRole)
        if not is_corrupt:
            return

        btn = QStyleOptionButton()
        btn.rect = option.rect.adjusted(4, 4, -4, -4)
        btn.text = "Repair…"
        btn.state = QStyle.State_Enabled
        QApplication.style().drawControl(QStyle.CE_PushButton, btn, painter)

    def editorEvent(self, event, model, option, index: QModelIndex) -> bool:
        is_corrupt = index.data(Qt.UserRole)
        if not is_corrupt:
            return False

        from qtpy.QtCore import QEvent  # type: ignore

        if event.type() == QEvent.MouseButtonRelease:
            # Retrieve the stateID from column 1 of the same row
            state_index = index.sibling(index.row(), 1)
            state_id = state_index.data(Qt.DisplayRole)
            if state_id:
                self.repairRequested.emit(str(state_id))
            return True

        return False

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(80, 28)
