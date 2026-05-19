"""Runs panel for the Campaign Manager.

Displays a summary table of all runs that have registered artefacts in the
current campaign.  Derived from :func:`list_artefact_records` — no extra
backend state required.

Selecting a row emits :attr:`RunsPanel.runSelected` so the Reduce panel can
pre-fill its run-number field.
"""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QHBoxLayout,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)


_COLUMNS = ["Run", "Artefacts", "Latest date"]


class _RunTableModel(QAbstractTableModel):
    def __init__(self, rows: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self._rows = rows

    def setRows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        col = index.column()
        if col == 0:
            return str(row["run_number"])
        if col == 1:
            return str(row["artefact_count"])
        if col == 2:
            date = row.get("latest_date", "") or ""
            return date[:10]  # ISO date portion only
        return None

    def runNumberAt(self, row_index: int) -> int | None:
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index]["run_number"]
        return None


class RunsPanel(QWidget):
    """Table panel listing runs that have artefacts in the current campaign.

    Signals
    -------
    runSelected(int)
        Emitted when the operator clicks a row; carries the run number.
    refreshRequested()
        Emitted when the operator clicks Refresh.
    """

    runSelected = Signal(int)
    refreshRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self._refreshBtn = QPushButton("Refresh")
        self._refreshBtn.clicked.connect(self.refreshRequested)
        toolbar.addWidget(self._refreshBtn)
        layout.addLayout(toolbar)

        # Table
        self._tableModel = _RunTableModel([])
        self._view = QTableView()
        self._view.setModel(self._tableModel)
        self._view.setSelectionBehavior(QTableView.SelectRows)
        self._view.setSelectionMode(QTableView.SingleSelection)
        self._view.setEditTriggers(QTableView.NoEditTriggers)
        self._view.horizontalHeader().setStretchLastSection(True)
        self._view.verticalHeader().setVisible(False)
        self._view.clicked.connect(self._onRowClicked)
        layout.addWidget(self._view)

    # ── Public API ──────────────────────────────────────────────────────

    def setRows(self, rows: list[dict[str, Any]]) -> None:
        self._tableModel.setRows(rows)

    # ── Internal slots ──────────────────────────────────────────────────

    def _onRowClicked(self, index: QModelIndex) -> None:
        run_number = self._tableModel.runNumberAt(index.row())
        if run_number is not None:
            self.runSelected.emit(run_number)
