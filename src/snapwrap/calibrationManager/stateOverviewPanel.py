"""Top panel: table of all states with status LEDs, context bar, and repair buttons.

Implements the two-mode UX described in the calibration manager plan:

**Mode A** — no cycle/run context selected (startup default).
    LED column header reads "Exists"; only existence-based statuses
    (FULL / PARTIAL / UNCALIBRATED / CORRUPT) are shown.  Tooltip on
    each LED prompts the user to select a cycle or run.

**Mode B** — a cycle or run number is selected.
    LED column header reads "Valid"; all six CalStatus values apply.
    Tooltip on each LED shows the per-calType detail strings from
    ``checkCalibrationStatus``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from qtpy.QtCore import (  # type: ignore
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from qtpy.QtGui import QColor  # type: ignore
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
    MODE_A_TOOLTIP,
    STATE_COLUMNS,
    STATUS_LABEL,
    STATUS_TOOLTIP,
    CalStatus,
)
from snapwrap.calibrationManager.delegates import (
    RepairButtonDelegate,
    StatusLEDDelegate,
)

# Sentinel value for "no cycle filter" in the combo box
_ALL_CYCLES = "All"

# Header text for the LED column in each mode
_HEADER_MODE_A = "Exists"
_HEADER_MODE_B = "Valid"


def _build_status_tooltip(hasContext: bool, row_dict: dict, status) -> str:
    """Build tooltip text for a status LED cell.

    Extracted as a module-level function so it can be tested without
    instantiating a QAbstractTableModel subclass.

    Parameters
    ----------
    hasContext : bool
        ``True`` when a cycle or run is selected (Mode B).
    row_dict : dict
        The full state-summary dict for the row.
    status : CalStatus
        The overall calibration status for this row.
    """
    if not hasContext:
        return MODE_A_TOOLTIP

    # Mode B: rich per-calType detail
    label = STATUS_LABEL.get(status, "Unknown")
    difDetail = row_dict.get("difcalDetail", "")
    nrmDetail = row_dict.get("normcalDetail", "")

    lines = [f"Status: {label}"]
    if difDetail:
        lines.append(f"difcal: {difDetail}")
    if nrmDetail:
        lines.append(f"normcal: {nrmDetail}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Table model
# ═══════════════════════════════════════════════════════════════════════

class StateTableModel(QAbstractTableModel):
    """Flat table model backed by a list of state-summary dicts.

    The dicts are produced by
    :meth:`~model.CalibrationManagerModel.getAllStates`.

    The model tracks whether a run/cycle context is active (Mode B) or
    not (Mode A).  This affects:

    * The header text for the status column ("Exists" vs "Valid").
    * The tooltip returned for the status column (generic prompt vs
      per-calType detail strings).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []
        self._hasContext: bool = False  # Mode A by default

    # ── public helpers ───────────────────────────────────────────

    def setStateData(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._data = rows
        self.endResetModel()

    def setHasContext(self, hasContext: bool) -> None:
        """Switch between Mode A (False) and Mode B (True).

        Triggers a header-data refresh so the LED column header updates.
        """
        if self._hasContext != hasContext:
            self._hasContext = hasContext
            self.headerDataChanged.emit(Qt.Horizontal, 0, 0)

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
            _, key, _ = STATE_COLUMNS[section]
            if key == "status":
                return _HEADER_MODE_B if self._hasContext else _HEADER_MODE_A
            return STATE_COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row_dict = self._data[index.row()]
        _, key, _ = STATE_COLUMNS[index.column()]

        value = row_dict.get(key)

        # Status column: LED delegate reads UserRole for CalStatus,
        # and ToolTipRole for the hover text
        if key == "status":
            if role == Qt.UserRole:
                return value
            if role == Qt.DisplayRole:
                return STATUS_LABEL.get(value, "")
            if role == Qt.ToolTipRole:
                return _build_status_tooltip(self._hasContext, row_dict, value)
            return None

        # Corrupt column: button delegate reads UserRole
        if key == "isCorrupt":
            if role == Qt.UserRole:
                return bool(value)
            if role == Qt.DisplayRole:
                return "Yes" if value else ""
            if role == Qt.ToolTipRole and value:
                details = row_dict.get("corruptDetails", "")
                return details if details else "Index validation failed"
            return None

        # Everything else
        if role == Qt.DisplayRole:
            if value is None:
                return ""
            if isinstance(value, float):
                return f"{value:.1f}"
            return str(value)

        # Red text for corrupt rows (all columns)
        if role == Qt.ForegroundRole:
            if row_dict.get("isCorrupt"):
                return QColor(0xFF, 0x41, 0x36)

        return None

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        _, key, _ = STATE_COLUMNS[index.column()]
        if key == "isCorrupt":
            return base | Qt.ItemIsEditable  # needed for delegate editorEvent
        return base

    # ── internal helpers ─────────────────────────────────────────
    # Tooltip logic is in the module-level _build_status_tooltip()
    # function so it can be tested without a real Qt environment.


# ═══════════════════════════════════════════════════════════════════════
# Panel widget
# ═══════════════════════════════════════════════════════════════════════

class StateOverviewPanel(QWidget):
    """Top panel containing the context bar, state table, and repair buttons.

    Implements the two-mode UX:

    **Mode A** (default) — no cycle or run selected.
        LED column header: "Exists".  Status reflects whether the
        state has *any* calibrations.

    **Mode B** — a cycle or run number is selected.
        LED column header: "Valid".  Status is scoped to the
        selected context; all six CalStatus values are possible.

    Signals
    -------
    stateSelected(str)
        Emitted when the user selects a row, carrying the stateID.
    repairRequested(str)
        Emitted when the Repair button is clicked, carrying the stateID.
    contextChanged(str)
        Emitted when the cycle/run context changes, carrying either
        a run number string (if the run field is filled) or an empty
        string (Mode A).  The mainWindow uses this to re-query the
        model with the appropriate ``runNumber`` parameter.
    """

    stateSelected = Signal(str)
    repairRequested = Signal(str)
    contextChanged = Signal(str)  # run number or ""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # ── context bar ───────────────────────────────────────────
        contextBar = QHBoxLayout()

        self.contextLabel = QLabel("All states")
        self.contextLabel.setStyleSheet(
            "font-weight: bold; padding: 2px 6px; color: #555;"
        )
        contextBar.addWidget(self.contextLabel)

        contextBar.addWidget(QLabel("Cycle:"))
        self.cycleCombo = QComboBox()
        self.cycleCombo.setMinimumWidth(120)
        contextBar.addWidget(self.cycleCombo)

        contextBar.addWidget(QLabel("Run #:"))
        self.runEdit = QLineEdit()
        self.runEdit.setPlaceholderText("enter run number")
        self.runEdit.setMaximumWidth(120)
        contextBar.addWidget(self.runEdit)

        self.clearBtn = QPushButton("Clear")
        self.clearBtn.setToolTip("Return to Mode A (no context)")
        contextBar.addWidget(self.clearBtn)

        # Track the last run number we emitted so that editingFinished
        # (which fires on every focus-loss) doesn't trigger redundant
        # reloads when the user simply clicks the table.
        self._lastEmittedRun: str = ""

        contextBar.addStretch()

        self.refreshBtn = QPushButton("Refresh")
        contextBar.addWidget(self.refreshBtn)

        layout.addLayout(contextBar)

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
        self.cycleCombo.currentTextChanged.connect(self._onCycleChanged)
        self.runEdit.editingFinished.connect(self._onRunEdited)
        self.clearBtn.clicked.connect(self._onClear)

    # ── public API ────────────────────────────────────────────────

    def setCycles(self, cycleIDs: List[str]) -> None:
        """Populate the cycle combo box (adds 'All' at the top)."""
        self.cycleCombo.blockSignals(True)
        self.cycleCombo.clear()
        self.cycleCombo.addItem(_ALL_CYCLES)
        self.cycleCombo.addItems(cycleIDs)
        self.cycleCombo.blockSignals(False)

    def setData(self, rows: List[Dict[str, Any]]) -> None:
        self.tableModel.setStateData(rows)

    def updateRow(self, stateID: str, row_data: Dict[str, Any]) -> None:
        self.tableModel.updateRow(stateID, row_data)

    def setContextInfo(
        self,
        runNumber: str = "",
        cycleID: str = "",
        stateID: str = "",
    ) -> None:
        """Update the context label and the model's Mode A/B state.

        Called by mainWindow after it resolves cycle/state from the run.
        """
        if runNumber:
            parts = [f"Run: {runNumber}"]
            if cycleID:
                parts.append(f"({cycleID})")
            if stateID:
                parts.append(f"— state {stateID}")
            self.contextLabel.setText(" ".join(parts))
            self.tableModel.setHasContext(True)
        elif cycleID and cycleID != _ALL_CYCLES:
            self.contextLabel.setText(f"Cycle: {cycleID}")
            self.tableModel.setHasContext(True)
        else:
            self.contextLabel.setText("All states")
            self.tableModel.setHasContext(False)

    def currentRunNumber(self) -> str:
        """Return the run number from the text field (may be empty)."""
        return self.runEdit.text().strip()

    def currentCycle(self) -> str:
        """Return the selected cycle or empty string if 'All'."""
        text = self.cycleCombo.currentText()
        return "" if text == _ALL_CYCLES else text

    # ── slots ─────────────────────────────────────────────────────

    def _onSelectionChanged(self, selected, _deselected) -> None:
        indexes = selected.indexes()
        if not indexes:
            return
        source_row = self.proxyModel.mapToSource(indexes[0]).row()
        stateID = self.tableModel.stateIDForRow(source_row)
        if stateID:
            self.stateSelected.emit(stateID)

    def _onCycleChanged(self, _text: str) -> None:
        """Cycle combo changed — emit contextChanged (run field takes precedence)."""
        run = self.runEdit.text().strip()
        if run:
            # Run field overrides; no need to re-emit
            return
        self.contextChanged.emit("")  # empty = no run, mainWindow reads cycle from combo

    def _onRunEdited(self) -> None:
        """Run number field editing finished — emit contextChanged.

        ``editingFinished`` fires on every focus-loss, not just Enter.
        Guard against redundant emissions so that clicking the table
        (which steals focus from runEdit) doesn't trigger a reload.
        """
        run = self.runEdit.text().strip()
        if run == self._lastEmittedRun:
            return
        self._lastEmittedRun = run
        self.contextChanged.emit(run)

    def _onClear(self) -> None:
        """Clear button — return to Mode A."""
        self.runEdit.clear()
        self._lastEmittedRun = ""
        self.cycleCombo.blockSignals(True)
        self.cycleCombo.setCurrentText(_ALL_CYCLES)
        self.cycleCombo.blockSignals(False)
        self.contextChanged.emit("")
