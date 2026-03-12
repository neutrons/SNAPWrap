"""Top panel: table of all states with status LEDs, filters, and repair buttons."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from qtpy.QtCore import (  # type: ignore
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from qtpy.QtWidgets import (  # type: ignore
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from snapwrap.calibrationManager.constants import (
    STATE_COLUMNS,
    STATUS_LABEL,
    CalStatus,
)
from snapwrap.calibrationManager.delegates import (
    RepairButtonDelegate,
    StatusLEDDelegate,
)


# ═══════════════════════════════════════════════════════════════════════
# Table model
# ═══════════════════════════════════════════════════════════════════════

class StateTableModel(QAbstractTableModel):
    """Flat table model backed by a list of state-summary dicts.

    The dicts are produced by
    :meth:`~model.CalibrationManagerModel.getAllStates`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []

    # ── public helpers ───────────────────────────────────────────

    def setStateData(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._data = rows
        self.endResetModel()

    def updateRow(self, stateID: str, row_data: Dict[str, Any]) -> None:
        """Replace a single row (identified by stateID) in-place."""
        for i, row in enumerate(self._data):
            if row["stateID"] == stateID:
                self._data[i] = row_data
                left = self.index(i, 0)
                right = self.index(i, self.columnCount() - 1)
                self.dataChanged.emit(left, right)
                return

    def stateIDForRow(self, row: int) -> Optional[str]:
        if 0 <= row < len(self._data):
            return self._data[row]["stateID"]
        return None

    # ── QAbstractTableModel interface ────────────────────────────

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(STATE_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return STATE_COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row_dict = self._data[index.row()]
        _, key, _ = STATE_COLUMNS[index.column()]

        value = row_dict.get(key)

        # Status column: LED delegate reads UserRole
        if key == "status":
            if role == Qt.UserRole:
                return value
            if role == Qt.DisplayRole:
                return STATUS_LABEL.get(value, "")
            return None

        # Corrupt column: button delegate reads UserRole
        if key == "isCorrupt":
            if role == Qt.UserRole:
                return bool(value)
            if role == Qt.DisplayRole:
                return "Yes" if value else ""
            return None

        # Everything else
        if role == Qt.DisplayRole:
            if value is None:
                return ""
            if isinstance(value, float):
                return f"{value:.1f}"
            return str(value)

        return None

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        _, key, _ = STATE_COLUMNS[index.column()]
        if key == "isCorrupt":
            return base | Qt.ItemIsEditable  # needed for delegate editorEvent
        return base


# ═══════════════════════════════════════════════════════════════════════
# Panel widget
# ═══════════════════════════════════════════════════════════════════════

class StateOverviewPanel(QWidget):
    """Top panel containing the cycle/run filter bar and the state table.

    Signals
    -------
    stateSelected(str)
        Emitted when the user selects a row, carrying the stateID.
    repairRequested(str)
        Emitted when the Repair button is clicked, carrying the stateID.
    """

    stateSelected = Signal(str)
    repairRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # ── filter bar ────────────────────────────────────────────
        filterBar = QHBoxLayout()

        filterBar.addWidget(QLabel("Cycle:"))
        self.cycleCombo = QComboBox()
        self.cycleCombo.setMinimumWidth(120)
        filterBar.addWidget(self.cycleCombo)

        filterBar.addWidget(QLabel("Run #:"))
        self.runEdit = QLineEdit()
        self.runEdit.setPlaceholderText("override cycle filter")
        self.runEdit.setMaximumWidth(120)
        filterBar.addWidget(self.runEdit)

        filterBar.addStretch()

        self.refreshBtn = QPushButton("Refresh")
        filterBar.addWidget(self.refreshBtn)

        layout.addLayout(filterBar)

        # ── table ─────────────────────────────────────────────────
        self.tableModel = StateTableModel(self)
        self.proxyModel = QSortFilterProxyModel(self)
        self.proxyModel.setSourceModel(self.tableModel)
        self.proxyModel.setSortCaseSensitivity(Qt.CaseInsensitive)

        self.tableView = QTableView()
        self.tableView.setModel(self.proxyModel)
        self.tableView.setSortingEnabled(True)
        self.tableView.setSelectionBehavior(QTableView.SelectRows)
        self.tableView.setSelectionMode(QTableView.SingleSelection)
        self.tableView.setAlternatingRowColors(True)
        self.tableView.verticalHeader().setVisible(False)

        # Stretch the description / stateID columns
        header = self.tableView.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        # State ID column gets extra stretch
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        # ── delegates ─────────────────────────────────────────────
        status_col = next(
            i for i, (_, k, _) in enumerate(STATE_COLUMNS) if k == "status"
        )
        self._ledDelegate = StatusLEDDelegate(self)
        self.tableView.setItemDelegateForColumn(status_col, self._ledDelegate)

        corrupt_col = next(
            i for i, (_, k, _) in enumerate(STATE_COLUMNS) if k == "isCorrupt"
        )
        self._repairDelegate = RepairButtonDelegate(self)
        self._repairDelegate.repairRequested.connect(self.repairRequested)
        self.tableView.setItemDelegateForColumn(corrupt_col, self._repairDelegate)

        layout.addWidget(self.tableView)

        # ── internal signal wiring ────────────────────────────────
        self.tableView.selectionModel().selectionChanged.connect(
            self._onSelectionChanged
        )

    # ── public API ────────────────────────────────────────────────

    def setCycles(self, cycleIDs: List[str]) -> None:
        """Populate the cycle combo box."""
        self.cycleCombo.blockSignals(True)
        self.cycleCombo.clear()
        self.cycleCombo.addItems(cycleIDs)
        self.cycleCombo.blockSignals(False)

    def setData(self, rows: List[Dict[str, Any]]) -> None:
        self.tableModel.setStateData(rows)

    def updateRow(self, stateID: str, row_data: Dict[str, Any]) -> None:
        self.tableModel.updateRow(stateID, row_data)

    # ── slots ─────────────────────────────────────────────────────

    def _onSelectionChanged(self, selected, _deselected) -> None:
        indexes = selected.indexes()
        if not indexes:
            return
        source_row = self.proxyModel.mapToSource(indexes[0]).row()
        stateID = self.tableModel.stateIDForRow(source_row)
        if stateID:
            self.stateSelected.emit(stateID)
