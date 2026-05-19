"""Artefacts panel — read-only filterable table of campaign artefacts.

Phase 1 deliverable.  Mutations (retire / copy) come in Phase 2.
"""

from __future__ import annotations

from typing import Any

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

from snapwrap.campaignManager.constants import (
    ARTEFACT_COLUMNS,
    STATUS_FROM_STRING,
    ArtefactStatus,
    lookup,
)
from snapwrap.campaignManager.delegates import StatusPillDelegate


# ═══════════════════════════════════════════════════════════════════════
# Table model
# ═══════════════════════════════════════════════════════════════════════


class ArtefactTableModel(QAbstractTableModel):
    """Flat table model backed by a list of artefact-record dicts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    # ── Public API ────────────────────────────────────────────────

    def setRows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def recordAt(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    # ── QAbstractTableModel implementation ─────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(ARTEFACT_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return ARTEFACT_COLUMNS[section][0]

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        header, key, _tooltip = ARTEFACT_COLUMNS[index.column()]

        # Status column — special handling for the pill delegate.
        if key == "status":
            status_str = str(row.get("status", "")).lower()
            status = STATUS_FROM_STRING.get(status_str, ArtefactStatus.UNKNOWN)
            if role == Qt.UserRole:
                return status
            if role == Qt.DisplayRole:
                # Painted by delegate — fall back to text for sorting / a11y.
                return status_str
            return None

        value = lookup(row, key)
        if role == Qt.DisplayRole:
            return str(value) if value != "" else ""
        if role == Qt.ToolTipRole:
            return ARTEFACT_COLUMNS[index.column()][2]
        return None


# ═══════════════════════════════════════════════════════════════════════
# Panel widget
# ═══════════════════════════════════════════════════════════════════════


class ArtefactsPanel(QWidget):
    """Filterable read-only table of artefacts for the current campaign.

    Emits :pyattr:`refreshRequested` when the operator clicks Refresh.
    The host (main window) is responsible for calling :meth:`setRecords`
    with the latest result.
    """

    refreshRequested = Signal()

    _TYPE_ALL = "All types"
    _STATUS_ALL = "All statuses"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._model = ArtefactTableModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # match against all columns

        # The full unfiltered record list (master copy).  Combo filters
        # produce a subset that is fed to the model; the proxy's text
        # filter then runs on top of that subset.
        self._allRecords: list[dict[str, Any]] = []

        self._buildUi()

    # ── UI construction ────────────────────────────────────────────

    def _buildUi(self) -> None:
        layout = QVBoxLayout(self)

        # Filter row.
        filterRow = QHBoxLayout()

        filterRow.addWidget(QLabel("Type:"))
        self._typeCombo = QComboBox()
        self._typeCombo.addItem(self._TYPE_ALL)
        self._typeCombo.currentTextChanged.connect(self._applyFilters)
        filterRow.addWidget(self._typeCombo)

        filterRow.addSpacing(12)
        filterRow.addWidget(QLabel("Status:"))
        self._statusCombo = QComboBox()
        self._statusCombo.addItems([self._STATUS_ALL, "active", "retired"])
        self._statusCombo.currentTextChanged.connect(self._applyFilters)
        filterRow.addWidget(self._statusCombo)

        filterRow.addSpacing(12)
        filterRow.addWidget(QLabel("Search:"))
        self._searchEdit = QLineEdit()
        self._searchEdit.setPlaceholderText("substring match across all columns")
        self._searchEdit.textChanged.connect(self._proxy.setFilterFixedString)
        filterRow.addWidget(self._searchEdit, stretch=1)

        self._refreshBtn = QPushButton("Refresh")
        self._refreshBtn.clicked.connect(self.refreshRequested.emit)
        filterRow.addWidget(self._refreshBtn)

        layout.addLayout(filterRow)

        # Table.
        self._table = QTableView(self)
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.setItemDelegateForColumn(0, StatusPillDelegate(self._table))
        layout.addWidget(self._table, stretch=1)

        # Footer.
        self._countLabel = QLabel("0 records")
        layout.addWidget(self._countLabel)

    # ── Data wiring ────────────────────────────────────────────────

    def setRecords(self, records: list[dict[str, Any]]) -> None:
        """Replace the table contents and refresh the filter combos."""
        self._allRecords = list(records)

        # Rebuild the type filter from the records present.
        types = sorted({str(r.get("artefact_type", "")) for r in records if r.get("artefact_type")})
        current_type = self._typeCombo.currentText()
        self._typeCombo.blockSignals(True)
        self._typeCombo.clear()
        self._typeCombo.addItem(self._TYPE_ALL)
        self._typeCombo.addItems(types)
        # Try to restore the previous selection.
        idx = self._typeCombo.findText(current_type)
        if idx >= 0:
            self._typeCombo.setCurrentIndex(idx)
        self._typeCombo.blockSignals(False)

        self._applyFilters()

        # Resize columns to fit on first load only — let the operator
        # adjust afterwards.
        self._table.resizeColumnsToContents()
        # Reset stretch on the last column after resize.
        self._table.horizontalHeader().setStretchLastSection(True)

    def _applyFilters(self) -> None:
        """Re-feed the model with the combo-filtered subset of the master list."""
        type_filter = self._typeCombo.currentText()
        status_filter = self._statusCombo.currentText()

        visible: list[dict[str, Any]] = []
        for r in self._allRecords:
            if type_filter != self._TYPE_ALL and r.get("artefact_type") != type_filter:
                continue
            if status_filter != self._STATUS_ALL and str(r.get("status", "")).lower() != status_filter:
                continue
            visible.append(r)

        self._model.setRows(visible)
        self._countLabel.setText(
            f"{len(visible)} record(s)"
            + ("" if len(visible) == len(self._allRecords) else f" (of {len(self._allRecords)})")
        )
