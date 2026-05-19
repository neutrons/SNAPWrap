"""Setup panel for the Campaign Manager.

Phase 4a: Assets table with Ingest button.
Phase 4b: Pixel mask registration form.
Phase 4c (pending): Crystal phase builder.
"""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

_STANDARD_PE_MASK_PATH = "/SNS/SNAP/shared/autoreduce/masks/PEMask.nxs"

_ASSET_COLUMNS = ["Asset ID", "Type", "Scope", "Status"]

# Artefact-type combo indices
_TYPE_PIXEL_MASK = 0
_TYPE_CRYSTAL_PHASE = 1


# ── Assets table ──────────────────────────────────────────────────────────────

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


# ── Pixel mask form ───────────────────────────────────────────────────────────

class _PixelMaskForm(QWidget):
    """Inline form for registering a pixel mask artefact."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Method
        self._methodCombo = QComboBox()
        self._methodCombo.addItem("Standard PE (letterbox)", userData="pixel_mask.letterbox")
        self._methodCombo.addItem("Custom .nxs file", userData="pixel_mask.custom")
        self._methodCombo.currentIndexChanged.connect(self._onMethodChanged)
        layout.addRow("Method:", self._methodCombo)

        # File path (custom only)
        self._fileRow = QWidget()
        file_layout = QHBoxLayout(self._fileRow)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self._fileEdit = QLineEdit()
        self._fileEdit.setPlaceholderText("Path to .nxs pixel mask file")
        file_layout.addWidget(self._fileEdit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._onBrowse)
        file_layout.addWidget(browse_btn)
        self._fileLabel = QLabel("File:")
        layout.addRow(self._fileLabel, self._fileRow)
        self._fileLabel.setVisible(False)
        self._fileRow.setVisible(False)

        # Workspace name
        self._wsEdit = QLineEdit()
        self._wsEdit.setText("pixmask_pe")
        self._wsEdit.setPlaceholderText("Mantid workspace name")
        layout.addRow("Workspace name:", self._wsEdit)

        # Artefact ID
        self._idEdit = QLineEdit()
        self._idEdit.setPlaceholderText("e.g. pixmask-pe-01")
        layout.addRow("Artefact ID:", self._idEdit)

        # Run number (optional)
        self._runEdit = QLineEdit()
        self._runEdit.setPlaceholderText("optional — leave blank for campaign-wide")
        layout.addRow("Run number:", self._runEdit)

        # Notes
        self._notesEdit = QPlainTextEdit()
        self._notesEdit.setPlaceholderText("Optional notes")
        self._notesEdit.setFixedHeight(55)
        layout.addRow("Notes:", self._notesEdit)

    def _onBrowse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select pixel mask file", "", "Nexus files (*.nxs);;All files (*)"
        )
        if path:
            self._fileEdit.setText(path)

    def _onMethodChanged(self, _index: int) -> None:
        is_custom = self._methodCombo.currentData() == "pixel_mask.custom"
        self._fileLabel.setVisible(is_custom)
        self._fileRow.setVisible(is_custom)
        self._wsEdit.setText("pixmask_custom" if is_custom else "pixmask_pe")

    def params(self) -> dict[str, Any]:
        method = self._methodCombo.currentData()
        nxs_path = (
            self._fileEdit.text().strip()
            if method == "pixel_mask.custom"
            else _STANDARD_PE_MASK_PATH
        )
        run_text = self._runEdit.text().strip()
        try:
            run_number: int | None = int(run_text) if run_text else None
        except ValueError:
            run_number = None
        return {
            "nxs_path": nxs_path,
            "method": method,
            "ws_name": self._wsEdit.text().strip(),
            "artefact_id": self._idEdit.text().strip(),
            "run_number": run_number,
            "notes": self._notesEdit.toPlainText().strip() or None,
        }

    def validate(self) -> str | None:
        """Return an error message string, or None if the form is valid."""
        p = self.params()
        if not p["artefact_id"]:
            return "Artefact ID is required."
        if not p["ws_name"]:
            return "Workspace name is required."
        if self._methodCombo.currentData() == "pixel_mask.custom" and not p["nxs_path"]:
            return "A .nxs file path is required for the custom method."
        return None


# ── Setup panel ───────────────────────────────────────────────────────────────

class SetupPanel(QWidget):
    """Setup tab: assets table + artefact creation forms.

    Signals
    -------
    ingestRequested()
        Emitted when the operator clicks "Ingest asset…".
    refreshRequested()
        Emitted when the operator clicks Refresh.
    pixelMaskRegistrationRequested(dict)
        Emitted with the validated form parameters when operator clicks
        Register for a pixel mask.
    """

    ingestRequested = Signal()
    refreshRequested = Signal()
    pixelMaskRegistrationRequested = Signal(dict)

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

        # ── Artefact creation group ────────────────────────────────────
        creation_group = QGroupBox("Artefact creation")
        cg_layout = QVBoxLayout(creation_group)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._typeCombo = QComboBox()
        self._typeCombo.addItem("Pixel mask")
        self._typeCombo.addItem("Crystal phase  (coming in Phase 4c)")
        self._typeCombo.currentIndexChanged.connect(self._onTypeChanged)
        type_row.addWidget(self._typeCombo)
        type_row.addStretch(1)
        cg_layout.addLayout(type_row)

        # Stacked forms — one page per artefact type
        self._stack = QStackedWidget()

        self._pixelMaskForm = _PixelMaskForm()
        self._stack.addWidget(self._pixelMaskForm)  # index 0 = _TYPE_PIXEL_MASK

        phase_placeholder = QLabel("Crystal phase builder — Phase 4c.")
        phase_placeholder.setAlignment(Qt.AlignCenter)
        phase_placeholder.setStyleSheet("color: gray; font-style: italic;")
        self._stack.addWidget(phase_placeholder)     # index 1 = _TYPE_CRYSTAL_PHASE

        cg_layout.addWidget(self._stack)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._createBtn = QPushButton("Register")
        self._createBtn.clicked.connect(self._onRegister)
        btn_row.addWidget(self._createBtn)
        cg_layout.addLayout(btn_row)

        layout.addWidget(creation_group)

    # ── Public API ─────────────────────────────────────────────────────

    def setRows(self, rows: list[dict[str, Any]]) -> None:
        self._assetModel.setRows(rows)

    # ── Internal slots ─────────────────────────────────────────────────

    def _onTypeChanged(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._createBtn.setVisible(index != _TYPE_CRYSTAL_PHASE)

    def _onRegister(self) -> None:
        if self._typeCombo.currentIndex() == _TYPE_PIXEL_MASK:
            error = self._pixelMaskForm.validate()
            if error:
                from qtpy.QtWidgets import QMessageBox  # type: ignore
                QMessageBox.warning(self, "Invalid form", error)
                return
            self.pixelMaskRegistrationRequested.emit(self._pixelMaskForm.params())
