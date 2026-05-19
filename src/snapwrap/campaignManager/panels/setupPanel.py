"""Setup panel for the Campaign Manager.

Phase 4a: Assets table (read-only view of registered assets) with an
Ingest button to copy a file into the managed asset store.

Phase 4b/4c (pending): Artefact creation forms (pixel mask registration,
swiss-cheese from UB files / transmission monitor).
"""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)


_ASSET_COLUMNS = ["Asset ID", "Type", "Scope", "Status"]


class _AssetTableModel(QAbstractTableModel):
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
        return 0 if parent.isValid() else len(_ASSET_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _ASSET_COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        col = index.column()
        if col == 0:
            return row.get("asset_id", "")
        if col == 1:
            return row.get("asset_type", "")
        if col == 2:
            app = row.get("applicability") or {}
            scope = app.get("scope", "campaign")
            rn = app.get("run_number")
            return f"run {rn}" if scope == "run" and rn is not None else "campaign"
        if col == 3:
            return row.get("status", "")
        return None


class SetupPanel(QWidget):
    """Setup tab: assets table and artefact-creation controls.

    Signals
    -------
    ingestRequested()
        Emitted when the operator clicks "Ingest asset…".
    refreshRequested()
        Emitted when the operator clicks Refresh.
    """

    ingestRequested = Signal()
    refreshRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # ── Assets group ───────────────────────────────────────────────
        assets_group = QGroupBox("Assets")
        ag_layout = QVBoxLayout(assets_group)

        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self._ingestBtn = QPushButton("Ingest asset…")
        self._ingestBtn.setToolTip("Copy a file into the managed asset store")
        self._ingestBtn.clicked.connect(self.ingestRequested)
        toolbar.addWidget(self._ingestBtn)
        self._refreshBtn = QPushButton("Refresh")
        self._refreshBtn.clicked.connect(self.refreshRequested)
        toolbar.addWidget(self._refreshBtn)
        ag_layout.addLayout(toolbar)

        self._assetModel = _AssetTableModel([])
        self._assetView = QTableView()
        self._assetView.setModel(self._assetModel)
        self._assetView.setSelectionBehavior(QTableView.SelectRows)
        self._assetView.setSelectionMode(QTableView.SingleSelection)
        self._assetView.setEditTriggers(QTableView.NoEditTriggers)
        self._assetView.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._assetView.verticalHeader().setVisible(False)
        ag_layout.addWidget(self._assetView)

        layout.addWidget(assets_group)

        # ── Artefact creation group (placeholder — Phase 4b/4c) ────────
        creation_group = QGroupBox("Artefact creation")
        cg_layout = QVBoxLayout(creation_group)
        placeholder = QLabel(
            "Pixel-mask registration and swiss-cheese creation coming in Phase 4b/4c."
        )
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: gray; font-style: italic;")
        cg_layout.addWidget(placeholder)
        layout.addWidget(creation_group)

    # ── Public API ─────────────────────────────────────────────────────

    def setRows(self, rows: list[dict[str, Any]]) -> None:
        self._assetModel.setRows(rows)
