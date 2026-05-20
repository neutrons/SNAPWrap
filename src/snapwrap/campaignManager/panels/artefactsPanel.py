"""Artefacts panel — filterable table of campaign artefacts with mutations.

Phase 1 deliverable: read-only display.
Phase 2 deliverable: right-click context menu for Retire / Copy / Open file
and a clipboard copy of the artefact id.  Mutations are *announced* via
signals; the host (main window) performs the actual backend call on a
background worker thread and triggers a reload on completion.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from qtpy.QtCore import (  # type: ignore
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from qtpy.QtGui import QGuiApplication, QPixmap  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
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


# ── CIF preview helper (mirrors setupPanel._cif_preview_text) ─────────────────

def _cif_preview_text(path: str) -> str:
    """Return a brief crystal summary from a CIF file (regex, no Mantid)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    def _get(*keys: str) -> str:
        for key in keys:
            m = re.search(
                rf"^{re.escape(key)}\s+['\"]?([^'\"\n]+)['\"]?",
                text, re.MULTILINE | re.IGNORECASE,
            )
            if m:
                return m.group(1).strip()
        return "?"

    sg = _get("_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt",
               "_symmetry_space_group_name_h-m")
    formula = _get("_chemical_formula_sum", "_chemical_name_mineral",
                   "_chemical_formula_structural")
    a = _get("_cell_length_a")
    b = _get("_cell_length_b")
    c = _get("_cell_length_c")
    alpha = _get("_cell_angle_alpha")
    beta  = _get("_cell_angle_beta")
    gamma = _get("_cell_angle_gamma")

    lines: list[str] = []
    if formula != "?":
        lines.append(f"Formula: {formula}")
    lines.append(f"Space group: {sg}")
    lines.append(f"a={a}  b={b}  c={c} Å")
    lines.append(f"α={alpha}  β={beta}  γ={gamma}°")
    return "\n".join(lines)


# ── Detail panel ──────────────────────────────────────────────────────────────

class _DetailPanel(QGroupBox):
    """Type-specific artefact inspector shown below the artefacts table.

    Populated by :meth:`showRecord` when a table row is selected.  Each
    artefact type gets its own rendering:

    * **pixel_mask** — thumbnail PNG (if generated at registration) + metadata
    * **crystal_species** — unit cell summary from the CIF + EOS parameters
    * **other** — generic metadata summary
    """

    _THUMB_W, _THUMB_H = 192, 96  # display size — 1:1 with the 192×96 detector grid

    def __init__(self, parent=None) -> None:
        super().__init__("Detail", parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        # Thumbnail area — only visible for pixel_mask records with a PNG.
        self._thumbLabel = QLabel()
        self._thumbLabel.setFixedSize(self._THUMB_W, self._THUMB_H)
        self._thumbLabel.setAlignment(Qt.AlignCenter)
        self._thumbLabel.setStyleSheet(
            "background: #1a1a1a; border: 1px solid #555; color: #888;"
        )
        self._thumbLabel.setText("no thumbnail")
        self._thumbLabel.hide()
        layout.addWidget(self._thumbLabel)

        self._text = QTextBrowser()
        self._text.setReadOnly(True)
        self._text.setOpenLinks(False)
        layout.addWidget(self._text, stretch=1)

        self.clear()

    # ── Public API ─────────────────────────────────────────────────────

    def clear(self) -> None:
        self._thumbLabel.hide()
        self._text.setHtml("<i style='color:gray'>Select a row to inspect the artefact.</i>")

    def showRecord(self, record: dict[str, Any]) -> None:
        atype = record.get("artefact_type", "")
        if atype == "pixel_mask":
            self._showPixelMask(record)
        elif atype == "bin_mask":
            self._showBinMask(record)
        elif atype == "crystal_species":
            self._showCrystalSpecies(record)
        else:
            self._showGeneric(record)

    # ── Type-specific renderers ────────────────────────────────────────

    def _showPixelMask(self, record: dict[str, Any]) -> None:
        thumb_path = record.get("thumbnail_path", "")
        if thumb_path:
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                self._thumbLabel.setPixmap(
                    pix.scaled(self._THUMB_W, self._THUMB_H,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self._thumbLabel.setText("")
                self._thumbLabel.show()
            else:
                self._thumbLabel.setText("thumbnail\nnot found")
                self._thumbLabel.show()
        else:
            self._thumbLabel.hide()

        aid = record.get("artefact_id", "—")
        mode = "lite" if "lite" in aid else ("native" if "native" in aid else "—")
        method = record.get("method", "—").replace("pixel_mask.", "")
        ws = (record.get("metadata") or {}).get("ws_name", "—")
        path = record.get("path", "—")
        created = record.get("timestamp", record.get("created_at", "—"))

        self._text.setHtml(
            f"<b>Pixel mask</b>: {aid}<br>"
            f"Mode: <b>{mode}</b> &nbsp;&nbsp; Method: {method}<br>"
            f"Workspace name: <tt>{ws}</tt><br>"
            f"File: <tt>{path}</tt><br>"
            f"Registered: {created}"
        )

    def _showBinMask(self, record: dict[str, Any]) -> None:
        thumb_path = record.get("thumbnail_path", "")
        if thumb_path:
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                self._thumbLabel.setPixmap(
                    pix.scaled(self._THUMB_W, self._THUMB_H,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                self._thumbLabel.setText("")
                self._thumbLabel.show()
            else:
                self._thumbLabel.setText("diagnostic\nnot found")
                self._thumbLabel.show()
        else:
            self._thumbLabel.hide()

        aid = record.get("artefact_id", "—")
        method = record.get("method", "—").replace("bin_mask.", "")
        path = record.get("path", "—")
        rc = record.get("run_context") or {}
        rn = rc.get("run_number")
        scope = f"run {rn}" if rn is not None else "campaign-wide"
        created = record.get("timestamp", record.get("created_at", "—"))
        notes = (record.get("provenance") or {}).get("notes", "") or record.get("notes", "")

        # Parse the JSON mask file for units and row count.
        units = "—"
        n_rows = "—"
        is_lite = "—"
        if path and path != "—":
            try:
                import json as _json
                mask_data = _json.loads(Path(path).read_text(encoding="utf-8"))
                units = mask_data.get("units", "—")
                xmins = mask_data.get("xmins", [])
                n_rows = str(len(xmins))
                lite_val = mask_data.get("isLite")
                if lite_val is True:
                    is_lite = "lite"
                elif lite_val is False:
                    is_lite = "native"
            except Exception:
                pass

        meta = record.get("metadata") or {}
        l2_override = meta.get("monitor2_l2_override")
        l2_note = f" &nbsp;&nbsp; <span style='color:#f90'>L2 override: {l2_override} m</span>" if l2_override is not None else ""

        parts = [
            f"<b>Bin mask</b>: {aid}",
            f"Units: <b>{units}</b> &nbsp;&nbsp; Rows: <b>{n_rows}</b> &nbsp;&nbsp; Mode: {is_lite}",
            f"Method: {method} &nbsp;&nbsp; Scope: {scope}{l2_note}",
            f"JSON: <tt>{path}</tt>",
            f"Registered: {created}",
        ]

        notches = meta.get("notches")
        if notches:
            rows_html = "".join(
                f"<tr><td align='right'>{lo:.4f}</td><td align='right'>{hi:.4f}</td>"
                f"<td align='right'>{hi - lo:.4f}</td></tr>"
                for lo, hi in notches
            )
            parts.append(
                "<br><b>Detected notches</b> (Å):"
                "<table style='font-size:small; margin-top:2px'>"
                "<tr><th align='right'>λ_min</th><th align='right'>λ_max</th>"
                "<th align='right'>width</th></tr>"
                f"{rows_html}</table>"
            )

        if notes:
            parts.append(f"Notes: {notes}")
        self._text.setHtml("<br>".join(parts))

    def _showCrystalSpecies(self, record: dict[str, Any]) -> None:
        self._thumbLabel.hide()
        cs = record.get("_crystal_species", {})
        species = cs.get("species_name") or record.get("notes", "?")
        role = cs.get("role", "?")

        parts = [f"<b>Crystal species</b>: {species} &nbsp;({role})"]

        cif_path = cs.get("cifPath", "")
        if cif_path:
            preview = _cif_preview_text(cif_path)
            if preview:
                parts.append(preview.replace("\n", "<br>"))

        eos_path = cs.get("eosPath", "")
        if eos_path:
            try:
                import json as _json
                eos = _json.loads(Path(eos_path).read_text(encoding="utf-8"))
                parts.append("<br><b>EOS</b>: " + eos.get("eos_type", "?"))
                v0 = eos.get("V_0")
                if v0 is not None:
                    parts.append(f"V₀ = {v0:.5g} Å³/unit cell")
                k0 = eos.get("K_0")
                if k0 is not None:
                    parts.append(f"K₀ = {k0:.5g} GPa")
                kp = eos.get("K_prime")
                if kp is not None:
                    parts.append(f"K′ = {kp:.4g}")
                src = eos.get("source", "")
                if src:
                    parts.append(f"Ref: {src}")
                sp = eos.get("stability_pressure")
                if sp:
                    p0, p1 = sp[0], sp[1]
                    bounds = f"{p0 if p0 is not None else '∞−'} – {p1 if p1 is not None else '∞'} GPa"
                    parts.append(f"Stability P: {bounds}")
            except Exception:
                parts.append("<i>(EOS file not readable)</i>")
        else:
            parts.append("<i>No EOS data</i>")

        self._text.setHtml("<br>".join(parts))

    def _showGeneric(self, record: dict[str, Any]) -> None:
        self._thumbLabel.hide()
        atype = record.get("artefact_type", "?")
        aid = record.get("artefact_id", "?")
        method = record.get("method", "")
        notes = (record.get("provenance") or {}).get("notes", "") or record.get("notes", "")
        parts = [f"<b>{atype}</b>: {aid}"]
        if method:
            parts.append(f"Method: {method}")
        if notes:
            parts.append(f"Notes: {notes}")
        self._text.setHtml("<br>".join(parts))


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
            if key == "run_context.run_number":
                return str(value) if value != "" else "all"
            return str(value) if value != "" else ""
        if role == Qt.ToolTipRole:
            return ARTEFACT_COLUMNS[index.column()][2]
        return None


# ═══════════════════════════════════════════════════════════════════════
# Panel widget
# ═══════════════════════════════════════════════════════════════════════


class ArtefactsPanel(QWidget):
    """Filterable artefact table with row-action context menu.

    Signals (the host wires these to backend calls on background workers):

    * :pyattr:`refreshRequested` — operator clicked Refresh.
    * :pyattr:`retireRequested(record)` — operator chose Retire on a row.
    * :pyattr:`copyRequested(record)` — operator chose Copy on a row.
    * :pyattr:`openFileRequested(record)` — operator chose Open file location.
    """

    refreshRequested = Signal()
    retireRequested = Signal(dict)
    copyRequested = Signal(dict)
    copyCrystalSpeciesRequested = Signal(dict)
    openFileRequested = Signal(dict)

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
        self._statusCombo.setCurrentText("active")
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
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._onContextMenu)
        self._table.selectionModel().currentChanged.connect(self._onCurrentChanged)

        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.addWidget(self._table)
        self._detailPanel = _DetailPanel()
        self._detailPanel.setMinimumHeight(100)
        self._splitter.addWidget(self._detailPanel)
        self._splitter.setStretchFactor(0, 5)
        self._splitter.setStretchFactor(1, 1)
        layout.addWidget(self._splitter, stretch=1)

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

    # ── Context menu / row actions ─────────────────────────────────

    def _recordAtPoint(self, pos) -> dict[str, Any] | None:
        """Resolve the artefact record under the given viewport point."""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return None
        # Map proxy → source row.
        src_index = self._proxy.mapToSource(index)
        return self._model.recordAt(src_index.row())

    def _onContextMenu(self, pos) -> None:
        record = self._recordAtPoint(pos)
        if record is None:
            return

        is_active = str(record.get("status", "")).lower() == "active"
        is_crystal_species = record.get("artefact_type") == "crystal_species"
        cs_path = (record.get("_crystal_species") or {}).get("cifPath")
        has_path = bool(
            record.get("path") or record.get("file_path") or record.get("mask_json_path") or cs_path
        )

        menu = QMenu(self._table)

        retire_action = menu.addAction("Retire…" if not is_crystal_species else "Delete…")
        retire_action.setEnabled(is_active)

        if is_crystal_species:
            copy_action = menu.addAction("Copy to campaign…")
            copy_action.setEnabled(is_active)
            copy_action.setToolTip("Copy this species (and its EOS) into another campaign.")
        else:
            copy_action = menu.addAction("Copy…")
            copy_action.setEnabled(is_active)
            copy_action.setToolTip(
                "Register a new artefact pointing at this one."
                if is_active
                else "Cannot copy a retired artefact."
            )

        menu.addSeparator()

        open_action = menu.addAction("Show file location")
        open_action.setEnabled(has_path)

        copyid_action = menu.addAction("Copy artefact id to clipboard")

        chosen = menu.exec_(self._table.viewport().mapToGlobal(pos))
        if chosen is retire_action:
            self.retireRequested.emit(record)
        elif chosen is copy_action:
            if is_crystal_species:
                self.copyCrystalSpeciesRequested.emit(record)
            else:
                self.copyRequested.emit(record)
        elif chosen is open_action:
            self.openFileRequested.emit(record)
        elif chosen is copyid_action:
            QGuiApplication.clipboard().setText(str(record.get("artefact_id", "")))

    # ── Detail panel wiring ────────────────────────────────────────

    def _onCurrentChanged(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._detailPanel.clear()
            return
        src = self._proxy.mapToSource(current)
        record = self._model.recordAt(src.row())
        if record:
            self._detailPanel.showRecord(record)
        else:
            self._detailPanel.clear()
