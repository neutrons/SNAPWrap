"""Custom delegates for the Calibration Manager tables.

Delegates
---------
StatusLEDDelegate
    Paints a coloured circle in the Status column based on the
    :class:`~constants.CalStatus` value.  Supports both Mode A (existence)
    and Mode B (validity) — the tooltip changes depending on whether per-
    calType detail strings are present in the model data.

RepairButtonDelegate
    Shows a "Repair" push-button in rows where corruption is detected.
"""

from __future__ import annotations

from qtpy.QtCore import QModelIndex, QRect, QSize, Qt, Signal  # type: ignore
from qtpy.QtGui import QColor, QPainter, QPen  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QStyle,
    QStyleOptionButton,
    QStyledItemDelegate,
    QApplication,
    QWidget,
)

from snapwrap.calibrationManager.constants import (
    CalStatus,
    MODE_A_TOOLTIP,
    STATUS_COLOUR,
    STATUS_LABEL,
    STATUS_TOOLTIP,
)

# Colour map  → QColor
_QCOLOURS = {
    "green": QColor(0x2E, 0xCC, 0x40),
    "amber": QColor(0xFF, 0xA5, 0x00),
    "red": QColor(0xFF, 0x41, 0x36),
    "orange": QColor(0xFF, 0x85, 0x1B),
    "blue": QColor(0x00, 0x74, 0xD9),
    "grey": QColor(0xAA, 0xAA, 0xAA),
    "yellow": QColor(0xFF, 0xDD, 0x00),
}

_LED_RADIUS = 8


class StatusLEDDelegate(QStyledItemDelegate):
    """Paints a solid coloured circle representing calibration status.

    Tooltip behaviour
    -----------------
    The delegate reads ``Qt.UserRole + 1`` for an optional rich tooltip
    string.  When that role returns a non-empty string the delegate uses
    it (Mode B — per-calType detail).  Otherwise it falls back to the
    generic ``STATUS_TOOLTIP`` for Mode A.
    """

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        # Let the default draw the background / selection highlight
        self.initStyleOption(option, index)
        QApplication.style().drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter)

        value = index.data(Qt.UserRole)
        if not isinstance(value, CalStatus):
            return

        colour = _QCOLOURS.get(STATUS_COLOUR.get(value, ""), QColor(Qt.gray))
        centre = option.rect.center()

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if value is CalStatus.CORRUPT:
            # Draw a red ✕ instead of the LED circle
            pen = QPen(colour, 3)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            d = _LED_RADIUS  # half-extent of the cross
            painter.drawLine(
                centre.x() - d, centre.y() - d,
                centre.x() + d, centre.y() + d,
            )
            painter.drawLine(
                centre.x() + d, centre.y() - d,
                centre.x() - d, centre.y() + d,
            )
        else:
            painter.setBrush(colour)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(centre, _LED_RADIUS, _LED_RADIUS)

        painter.restore()

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(_LED_RADIUS * 3, _LED_RADIUS * 3)


class RepairButtonDelegate(QStyledItemDelegate):
    """Renders a clickable action button when the row needs attention.

    The button label is context-dependent:

    * **"Repair…"** — standard corruption that ``fixIndex`` can resolve.
    * **"Delete…"** — cross-state contamination where the only safe
      option is to delete the entire state folder.
    * **"Fix DP…"** — double-propagated entries that need to be removed
      (shown only when the state is not also corrupt).

    Role usage (all on the ``isCorrupt`` column):

    ``Qt.UserRole``     — ``isCorrupt`` bool  
    ``Qt.UserRole + 2`` — ``deleteOnly`` bool (True → "Delete…")  
    ``Qt.UserRole + 3`` — ``hasDoublePropagated`` bool  

    Signals
    -------
    repairRequested(str)
        Emitted with the stateID when "Repair…" is clicked.
    deleteStateRequested(str)
        Emitted with the stateID when "Delete…" is clicked.
    removeDoublePropagatedRequested(str)
        Emitted with the stateID when "Fix DP…" is clicked.
    """

    repairRequested = Signal(str)
    deleteStateRequested = Signal(str)
    removeDoublePropagatedRequested = Signal(str)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        is_corrupt = index.data(Qt.UserRole)
        has_dp = index.data(Qt.UserRole + 3)

        if not is_corrupt and not has_dp:
            return

        delete_only = index.data(Qt.UserRole + 2)

        if is_corrupt:
            label = "Delete…" if delete_only else "Repair…"
        else:
            label = "Fix DP…"

        btn = QStyleOptionButton()
        btn.rect = option.rect.adjusted(4, 4, -4, -4)
        btn.text = label
        btn.state = QStyle.State_Enabled
        QApplication.style().drawControl(QStyle.CE_PushButton, btn, painter)

    def editorEvent(self, event, model, option, index: QModelIndex) -> bool:
        is_corrupt = index.data(Qt.UserRole)
        has_dp = index.data(Qt.UserRole + 3)

        if not is_corrupt and not has_dp:
            return False

        from qtpy.QtCore import QEvent  # type: ignore

        if event.type() == QEvent.MouseButtonRelease:
            # Retrieve the stateID from column 1 of the same row
            state_index = index.sibling(index.row(), 1)
            state_id = state_index.data(Qt.DisplayRole)
            if state_id:
                if is_corrupt:
                    delete_only = index.data(Qt.UserRole + 2)
                    if delete_only:
                        self.deleteStateRequested.emit(str(state_id))
                    else:
                        self.repairRequested.emit(str(state_id))
                else:
                    self.removeDoublePropagatedRequested.emit(str(state_id))
            return True

        return False

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        return QSize(80, 28)
