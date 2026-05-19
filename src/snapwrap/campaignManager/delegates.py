"""Custom delegates for the Campaign Manager tables."""

from __future__ import annotations

from qtpy.QtCore import QModelIndex, Qt  # type: ignore
from qtpy.QtGui import QBrush, QColor, QPainter, QPen  # type: ignore
from qtpy.QtWidgets import QStyle, QStyledItemDelegate, QApplication  # type: ignore

from snapwrap.campaignManager.constants import (
    STATUS_COLOUR,
    STATUS_LABEL,
    ArtefactStatus,
)


_QCOLOURS = {
    "green": QColor(0x2E, 0xCC, 0x40),
    "amber": QColor(0xFF, 0xA5, 0x00),
    "red":   QColor(0xFF, 0x41, 0x36),
    "grey":  QColor(0xAA, 0xAA, 0xAA),
}


class StatusPillDelegate(QStyledItemDelegate):
    """Paint a coloured pill with the status label inside.

    Reads :class:`ArtefactStatus` from ``Qt.UserRole``.  Falls back to
    plain text rendering when the cell does not carry a status.
    """

    _PILL_RADIUS = 8
    _PILL_PAD_X = 8
    _PILL_PAD_Y = 2

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        # Background / selection highlight first.
        self.initStyleOption(option, index)
        QApplication.style().drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter)

        status = index.data(Qt.UserRole)
        if not isinstance(status, ArtefactStatus):
            super().paint(painter, option, index)
            return

        label = STATUS_LABEL.get(status, "?")
        colour = _QCOLOURS.get(STATUS_COLOUR.get(status, ""), _QCOLOURS["grey"])

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # Measure the label so the pill hugs the text.
        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(label)
        text_h = fm.height()
        pill_w = text_w + 2 * self._PILL_PAD_X
        pill_h = text_h + 2 * self._PILL_PAD_Y

        rect = option.rect
        x = rect.left() + 6
        y = rect.center().y() - pill_h // 2

        # Pill background.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(colour))
        painter.drawRoundedRect(
            x, y, pill_w, pill_h, self._PILL_RADIUS, self._PILL_RADIUS
        )

        # Label.
        painter.setPen(QPen(Qt.white))
        painter.drawText(
            x + self._PILL_PAD_X,
            y + self._PILL_PAD_Y + fm.ascent(),
            label,
        )
        painter.restore()
