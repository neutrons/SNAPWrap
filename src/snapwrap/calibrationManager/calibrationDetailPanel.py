"""Bottom panel: tabbed detail view showing difcal and normcal index entries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from dateutil import parser as dtparser

from qtpy.QtCore import (  # type: ignore
    QAbstractTableModel,
    QModelIndex,
    Qt,
    Signal,
)
from qtpy.QtGui import QFont  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from snapwrap.calibrationManager.constants import DETAIL_COLUMNS, CalStatus, STATUS_LABEL


# ═══════════════════════════════════════════════════════════════════════
# Table model for index entries
# ═══════════════════════════════════════════════════════════════════════

class DetailTableModel(QAbstractTableModel):
    """Flat table model backed by a list of index-entry dicts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []

    def setEntries(self, entries: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._data = entries
        self.endResetModel()

    def entryForRow(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    # ── QAbstractTableModel interface ────────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(DETAIL_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return DETAIL_COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        entry = self._data[index.row()]
        _, key, _ = DETAIL_COLUMNS[index.column()]
        value = entry.get(key)
        isPropagated = entry.get("isPropagated", False)
        isDoublePropagated = entry.get("isDoublePropagated", False)

        if role == Qt.DisplayRole:
            if value is None:
                return ""
            # Format timestamp to local time, truncated to the minute
            if key == "timestamp" and isinstance(value, str) and value:
                try:
                    dt = dtparser.parse(value)
                    # Convert to local time if timezone-aware
                    if dt.tzinfo is not None:
                        dt = dt.astimezone()
                    return dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, OverflowError):
                    return str(value)
            # Run column: prefix with arrow for propagated entries
            if key == "effectiveRun" and isPropagated:
                return f"⇐ {value}"
            return str(value)

        # Italic font for entire row when propagated;
        # bold-italic for double-propagated rows
        if role == Qt.FontRole and (isPropagated or isDoublePropagated):
            font = QFont()
            font.setItalic(True)
            if isDoublePropagated:
                font.setBold(True)
            return font

        # Yellow foreground for double-propagated rows
        if role == Qt.ForegroundRole and isDoublePropagated:
            from qtpy.QtGui import QColor  # type: ignore
            return QColor(0xCC, 0xAA, 0x00)  # darker yellow for readability on white

        # Tooltip on the Run column explaining the propagation
        if role == Qt.ToolTipRole and key == "effectiveRun" and isPropagated:
            if isDoublePropagated:
                return (
                    f"⚠ Double-propagated: this entry was copied from run {value}, "
                    f"which was itself a propagated calibration.\n"
                    f"This entry should be removed and re-propagated from the original "
                    f"measured calibration."
                )
            return (
                f"Propagated from run {value} (donor).\n"
                f"Index runNumber is {entry.get('runNumber', '?')} (seed run of this state)."
            )

        return None


# ═══════════════════════════════════════════════════════════════════════
# Single-calType tab
# ═══════════════════════════════════════════════════════════════════════

class _DetailTab(QWidget):
    """One tab inside the detail panel (either difcal or normcal).

    Signals
    -------
    deleteRequested(int)
        Emitted with the version number when the user clicks Delete.
    """

    deleteRequested = Signal(int)

    def __init__(self, calType: str, parent=None):
        super().__init__(parent)
        self.calType = calType

        layout = QVBoxLayout(self)

        self.tableModel = DetailTableModel(self)
        self.tableView = QTableView()
        self.tableView.setModel(self.tableModel)
        self.tableView.setSelectionBehavior(QTableView.SelectRows)
        self.tableView.setSelectionMode(QTableView.SingleSelection)
        self.tableView.setAlternatingRowColors(True)
        self.tableView.verticalHeader().setVisible(False)
        self.tableView.setSortingEnabled(False)

        header = self.tableView.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # Comments column stretches
        comments_col = next(
            i for i, (_, k, _) in enumerate(DETAIL_COLUMNS) if k == "comments"
        )
        header.setSectionResizeMode(comments_col, QHeaderView.Stretch)

        layout.addWidget(self.tableView)

        # ── action buttons ────────────────────────────────────────
        btnLayout = QHBoxLayout()
        btnLayout.addStretch()
        self.deleteBtn = QPushButton("Delete Selected Version")
        self.deleteBtn.setEnabled(False)
        btnLayout.addWidget(self.deleteBtn)
        layout.addLayout(btnLayout)

        # ── wiring ────────────────────────────────────────────────
        self.tableView.selectionModel().selectionChanged.connect(
            self._onSelectionChanged
        )
        self.deleteBtn.clicked.connect(self._onDelete)

    def setEntries(self, entries: List[Dict[str, Any]]) -> None:
        self.tableModel.setEntries(entries)
        self.deleteBtn.setEnabled(False)

    def _onSelectionChanged(self, selected, _deselected):
        rows = selected.indexes()
        if not rows:
            self.deleteBtn.setEnabled(False)
            return
        entry = self.tableModel.entryForRow(rows[0].row())
        if entry is None:
            self.deleteBtn.setEnabled(False)
            return
        # Cannot delete version 0 for difcal
        ver = int(entry.get("version", -1))
        can_delete = not (self.calType == "difcal" and ver == 0)
        self.deleteBtn.setEnabled(can_delete)

    def _onDelete(self):
        rows = self.tableView.selectionModel().selectedRows()
        if not rows:
            return
        entry = self.tableModel.entryForRow(rows[0].row())
        if entry is not None:
            self.deleteRequested.emit(int(entry["version"]))


# ═══════════════════════════════════════════════════════════════════════
# Panel widget
# ═══════════════════════════════════════════════════════════════════════

class CalibrationDetailPanel(QWidget):
    """Bottom panel: state header bar + tabbed difcal / normcal detail.

    Signals
    -------
    deleteVersionRequested(str, str, int)
        (stateID, calType, version) — emitted when the user requests deletion.
    """

    deleteVersionRequested = Signal(str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # ── header bar ────────────────────────────────────────────
        self.headerLabel = QLabel("Select a state above to view calibration details.")
        self.headerLabel.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self.headerLabel)

        # ── tabs ──────────────────────────────────────────────────
        self.tabs = QTabWidget()

        self.difcalTab = _DetailTab("difcal", self)
        self.normcalTab = _DetailTab("normcal", self)

        self.tabs.addTab(self.difcalTab, "Diffraction Calibration (difcal)")
        self.tabs.addTab(self.normcalTab, "Normalization Calibration (normcal)")

        layout.addWidget(self.tabs)

        # ── signal forwarding ─────────────────────────────────────
        self._currentStateID: Optional[str] = None
        self.difcalTab.deleteRequested.connect(
            lambda ver: self._emitDelete("difcal", ver)
        )
        self.normcalTab.deleteRequested.connect(
            lambda ver: self._emitDelete("normcal", ver)
        )

    # ── public API ────────────────────────────────────────────────

    def showState(
        self,
        stateID: str,
        description: str,
        status: CalStatus,
        difcalEntries: List[Dict[str, Any]],
        normcalEntries: List[Dict[str, Any]],
        nDifcal: int,
        nNormcal: int,
    ) -> None:
        """Populate the panel for the given state."""
        self._currentStateID = stateID

        status_text = STATUS_LABEL.get(status, "Unknown")
        self.headerLabel.setText(
            f"{stateID}  —  {description.strip()}  [{status_text}]  "
            f"| difcal: {nDifcal}  | normcal: {nNormcal}"
        )

        self.difcalTab.setEntries(difcalEntries)
        self.normcalTab.setEntries(normcalEntries)

    def clear(self) -> None:
        self._currentStateID = None
        self.headerLabel.setText("Select a state above to view calibration details.")
        self.difcalTab.setEntries([])
        self.normcalTab.setEntries([])

    # ── internal ──────────────────────────────────────────────────

    def _emitDelete(self, calType: str, version: int) -> None:
        if self._currentStateID:
            self.deleteVersionRequested.emit(self._currentStateID, calType, version)
