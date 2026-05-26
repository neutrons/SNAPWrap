"""Workflow panel for the Campaign Manager.

Replaces the separate Reduce and Post-process tabs with a single unified view.
The operator builds a per-run queue of steps (Reduce → Resample → Crop),
selects artefacts for each step, then executes the queue in order.

The queue is persisted as ``workflow_queue_{run}.json`` in the campaign
directory and reloaded automatically when the run number changes.
"""
from __future__ import annotations

import logging
from typing import Any

from qtpy.QtCore import QThread, Qt, Signal  # type: ignore
from qtpy.QtGui import QFont  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from snapwrap.campaignManager.logHandler import QtLogHandler
from snapwrap.campaignManager.workers import GenericWorker
from snapwrap.campaignManager.workflow import (
    STEP_DEFAULTS,
    STEP_LABELS,
    STEP_REQUIRED_ARTEFACTS,
    STEP_TYPES,
    WorkflowQueue,
    WorkflowStep,
)

_SNAPWRAP_LOGGER = "snapwrap"
_NONE_LABEL = "— none —"


# ── Reusable artefact selector widgets ────────────────────────────────────────


class _BinMaskCheckList(QWidget):
    """Checkable list of bin mask artefacts."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setMaximumHeight(96)
        layout.addWidget(self._list)
        self._records: list[dict[str, Any]] = []

    def populate(self, records: list[dict[str, Any]]) -> None:
        """Rebuild the list from artefact records."""
        self._records = records
        self._list.clear()
        for rec in records:
            aid = rec.get("artefact_id", "")
            atype = rec.get("artefact_type", "")
            rn = (rec.get("run_context") or {}).get("run_number")
            scope = f"run {rn}" if rn is not None else "campaign"
            # Enrich type label with unit
            stem = __import__("pathlib").Path(rec.get("path") or "").stem
            unit = ""
            for u in ("Wavelength", "dSpacing"):
                if stem.endswith(f"_{u}"):
                    unit = f" ({u})"
                    break
            label = f"{aid}{unit}  [{scope}]"
            item = QListWidgetItem(label)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, aid)
            self._list.addItem(item)

    def selectedIds(self) -> list[str]:
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def setSelectedIds(self, ids: list[str]) -> None:
        id_set = set(ids)
        for i in range(self._list.count()):
            item = self._list.item(i)
            aid = item.data(Qt.UserRole)
            # Strip :MISSING suffix when comparing
            clean = aid.removesuffix(":MISSING") if hasattr(aid, "removesuffix") else aid.replace(":MISSING", "")
            state = Qt.Checked if (aid in id_set or clean in id_set) else Qt.Unchecked
            item.setCheckState(state)


class _ArtefactDropdown(QWidget):
    """Single-select dropdown for a non-bin-mask artefact type."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._combo = QComboBox()
        self._combo.setMaximumWidth(380)
        layout.addWidget(self._combo)
        layout.addStretch(1)

    def populate(self, records: list[dict[str, Any]]) -> None:
        self._combo.clear()
        self._combo.addItem(_NONE_LABEL, userData=None)
        for rec in records:
            aid = rec.get("artefact_id", "")
            rn = (rec.get("run_context") or {}).get("run_number")
            scope = f"run {rn}" if rn is not None else "campaign"
            self._combo.addItem(f"{aid}  [{scope}]", userData=aid)

    def selectedId(self) -> str | None:
        return self._combo.currentData()

    def setSelectedId(self, aid: str | None) -> None:
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == aid:
                self._combo.setCurrentIndex(i)
                return
        self._combo.setCurrentIndex(0)


# ── Step cards ─────────────────────────────────────────────────────────────────


class _ReduceCard(QGroupBox):
    removeRequested = Signal(str)  # emits step_type

    def __init__(self, parent=None) -> None:
        super().__init__("Reduce", parent)
        self._expertMode = False
        outer = QVBoxLayout(self)

        # Remove button in header row
        hdr = QHBoxLayout()
        hdr.addStretch(1)
        self._removeBtn = QPushButton("✕ Remove")
        self._removeBtn.setFixedWidth(100)
        self._removeBtn.clicked.connect(lambda: self.removeRequested.emit("reduce"))
        hdr.addWidget(self._removeBtn)
        outer.addLayout(hdr)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._binMaskList = _BinMaskCheckList()
        form.addRow("Bin masks:", self._binMaskList)

        self._pixelMaskDrop = _ArtefactDropdown()
        form.addRow("Pixel mask:", self._pixelMaskDrop)

        self._attenuationDrop = _ArtefactDropdown()
        form.addRow("Attenuation:", self._attenuationDrop)

        # Expert params (hidden by default)
        self._expertWidget = QWidget()
        exp_layout = QHBoxLayout(self._expertWidget)
        exp_layout.setContentsMargins(0, 0, 0, 0)
        self._keepUnfocussedCheck = QCheckBox("keepUnfocussed")
        self._continueNoDifcalCheck = QCheckBox("continueNoDifcal")
        self._continueNoVanCheck = QCheckBox("continueNoVan")
        self._verboseCheck = QCheckBox("verbose")
        for cb in (self._keepUnfocussedCheck, self._continueNoDifcalCheck,
                   self._continueNoVanCheck, self._verboseCheck):
            exp_layout.addWidget(cb)
        exp_layout.addStretch(1)
        self._expertWidget.setVisible(False)
        form.addRow("Expert options:", self._expertWidget)

        outer.addLayout(form)

    def setExpertMode(self, enabled: bool) -> None:
        self._expertMode = enabled
        self._expertWidget.setVisible(enabled)

    def setArtefacts(
        self,
        bin_masks: list[dict[str, Any]],
        pixel_masks: list[dict[str, Any]],
        attenuations: list[dict[str, Any]],
    ) -> None:
        self._binMaskList.populate(bin_masks)
        self._pixelMaskDrop.populate(pixel_masks)
        self._attenuationDrop.populate(attenuations)

    def toStep(self) -> WorkflowStep:
        sels: dict[str, list[str]] = {}
        bm = self._binMaskList.selectedIds()
        if bm:
            sels["bin_mask"] = bm
        pm = self._pixelMaskDrop.selectedId()
        if pm:
            sels["pixel_mask"] = [pm]
        att = self._attenuationDrop.selectedId()
        if att:
            sels["attenuation_workspace"] = [att]
        params: dict[str, Any] = {
            "keepUnfocussed": self._keepUnfocussedCheck.isChecked(),
            "continueNoDifcal": self._continueNoDifcalCheck.isChecked(),
            "continueNoVan": self._continueNoVanCheck.isChecked(),
            "verbose": self._verboseCheck.isChecked(),
        }
        return WorkflowStep(step_type="reduce", params=params, artefact_selections=sels)

    def fromStep(self, step: WorkflowStep) -> None:
        self._binMaskList.setSelectedIds(step.artefact_selections.get("bin_mask", []))
        self._pixelMaskDrop.setSelectedId(
            (step.artefact_selections.get("pixel_mask") or [None])[0]
        )
        self._attenuationDrop.setSelectedId(
            (step.artefact_selections.get("attenuation_workspace") or [None])[0]
        )
        p = step.params
        self._keepUnfocussedCheck.setChecked(bool(p.get("keepUnfocussed")))
        self._continueNoDifcalCheck.setChecked(bool(p.get("continueNoDifcal")))
        self._continueNoVanCheck.setChecked(bool(p.get("continueNoVan")))
        self._verboseCheck.setChecked(bool(p.get("verbose")))


class _ResampleCard(QGroupBox):
    removeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Resample", parent)
        outer = QVBoxLayout(self)

        hdr = QHBoxLayout()
        hdr.addStretch(1)
        self._removeBtn = QPushButton("✕ Remove")
        self._removeBtn.setFixedWidth(100)
        self._removeBtn.clicked.connect(lambda: self.removeRequested.emit("resample"))
        hdr.addWidget(self._removeBtn)
        outer.addLayout(hdr)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._factorSpin = QDoubleSpinBox()
        self._factorSpin.setRange(0.1, 10.0)
        self._factorSpin.setSingleStep(0.1)
        self._factorSpin.setValue(1.0)
        self._factorSpin.setDecimals(2)
        self._factorSpin.setMaximumWidth(120)
        form.addRow("Sample factor:", self._factorSpin)

        outer.addLayout(form)

    def setExpertMode(self, _enabled: bool) -> None:
        pass  # Resample has no expert options currently

    def setArtefacts(self, **_) -> None:
        pass  # Resample uses no artefacts

    def toStep(self) -> WorkflowStep:
        return WorkflowStep(
            step_type="resample",
            params={"sample_factor": self._factorSpin.value()},
        )

    def fromStep(self, step: WorkflowStep) -> None:
        p = step.params
        if "sample_factor" in p:
            self._factorSpin.setValue(float(p["sample_factor"]))


class _CropCard(QGroupBox):
    removeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Crop", parent)
        outer = QVBoxLayout(self)

        hdr = QHBoxLayout()
        hdr.addStretch(1)
        self._removeBtn = QPushButton("✕ Remove")
        self._removeBtn.setFixedWidth(100)
        self._removeBtn.clicked.connect(lambda: self.removeRequested.emit("crop"))
        hdr.addWidget(self._removeBtn)
        outer.addLayout(hdr)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._binMaskList = _BinMaskCheckList()
        form.addRow("Bin masks:", self._binMaskList)

        self._liteCheck = QCheckBox("Lite mode (18 432 pixels)")
        self._liteCheck.setChecked(True)
        form.addRow("Instrument mode:", self._liteCheck)

        self._edgeSpin = QDoubleSpinBox()
        self._edgeSpin.setRange(0, 50)
        self._edgeSpin.setSingleStep(1)
        self._edgeSpin.setDecimals(0)
        self._edgeSpin.setValue(0)
        self._edgeSpin.setMaximumWidth(100)
        form.addRow("Edge expansion (bins):", self._edgeSpin)

        self._minCovSpin = QDoubleSpinBox()
        self._minCovSpin.setRange(0.0, 0.05)
        self._minCovSpin.setSingleStep(0.001)
        self._minCovSpin.setDecimals(3)
        self._minCovSpin.setValue(0.002)
        self._minCovSpin.setMaximumWidth(100)
        form.addRow("Min coverage:", self._minCovSpin)

        self._forceCheck = QCheckBox("Force recalculate")
        form.addRow("Recompute:", self._forceCheck)

        self._diagCheck = QCheckBox("Retain diagnostics workspaces in ADS")
        self._diagCheck.setVisible(False)
        form.addRow("Diagnostics:", self._diagCheck)

        self._expertWidget = self._diagCheck
        outer.addLayout(form)

    def setExpertMode(self, enabled: bool) -> None:
        self._diagCheck.setVisible(enabled)

    def setArtefacts(self, bin_masks: list[dict[str, Any]], **_) -> None:
        self._binMaskList.populate(bin_masks)

    def toStep(self) -> WorkflowStep:
        sels: dict[str, list[str]] = {}
        bm = self._binMaskList.selectedIds()
        if bm:
            sels["bin_mask"] = bm
        params: dict[str, Any] = {
            "is_lite": self._liteCheck.isChecked(),
            "edge_bins": int(self._edgeSpin.value()),
            "min_coverage": self._minCovSpin.value(),
            "force_recompute": self._forceCheck.isChecked(),
            "diagnostics": self._diagCheck.isChecked(),
        }
        return WorkflowStep(step_type="crop", params=params, artefact_selections=sels)

    def fromStep(self, step: WorkflowStep) -> None:
        self._binMaskList.setSelectedIds(step.artefact_selections.get("bin_mask", []))
        p = step.params
        self._liteCheck.setChecked(bool(p.get("is_lite", True)))
        if "edge_bins" in p:
            self._edgeSpin.setValue(float(p["edge_bins"]))
        if "min_coverage" in p:
            self._minCovSpin.setValue(float(p["min_coverage"]))
        self._forceCheck.setChecked(bool(p.get("force_recompute")))
        self._diagCheck.setChecked(bool(p.get("diagnostics")))


# ── Card registry ──────────────────────────────────────────────────────────────

_CARD_CLASSES = {
    "reduce": _ReduceCard,
    "resample": _ResampleCard,
    "crop": _CropCard,
}


# ── Background execution helper ────────────────────────────────────────────────

def _execute_queue_fn(
    steps: list[dict[str, Any]],
    run_number: int,
    ipts: int,
    campaign_slug: str,
) -> str:
    """Execute all workflow steps sequentially.  Returns accumulated log.

    source_prefix for the Crop step is derived automatically: if a Resample
    step is present in the queue, Crop reads from 'resampled' workspaces;
    otherwise it reads from 'reduced'.
    """
    from snapwrap.campaignManager.model import CampaignManagerModel  # type: ignore

    step_types = [s["step_type"] for s in steps]
    has_resample = "resample" in step_types

    log_parts: list[str] = []
    for step_dict in steps:
        stype = step_dict["step_type"]
        params = dict(step_dict.get("params") or {})
        sels = dict(step_dict.get("artefact_selections") or {})

        log_parts.append(f"\n── Step: {STEP_LABELS.get(stype, stype)} ──\n")

        if stype == "reduce":
            result = CampaignManagerModel.executeReduceStep(
                ipts=ipts,
                campaign_identifier=campaign_slug,
                run_number=run_number,
                artefact_selections=sels,
                step_params=params,
            )
            log_parts.append(result)

        elif stype == "resample":
            result = CampaignManagerModel.postprocessResample(
                run_number=run_number,
                sample_factor=params.get("sample_factor", 1.0),
                units="dsp",
            )
            log_parts.append(result)

        elif stype == "crop":
            # Auto-derive source prefix: use resampled output if resample ran.
            source_prefix = "resampled" if has_resample else "reduced"
            log_parts.append(f"  source_prefix: {source_prefix}\n")
            bin_ids = sels.get("bin_mask") or None
            result = CampaignManagerModel.postprocessCrop(
                ipts=ipts,
                campaign_identifier=campaign_slug,
                run_number=run_number,
                is_lite=params.get("is_lite", True),
                source_prefix=source_prefix,
                edge_bins=int(params.get("edge_bins", 0)),
                min_coverage=float(params.get("min_coverage", 0.002)),
                force_recompute=bool(params.get("force_recompute", False)),
                diagnostics=bool(params.get("diagnostics", False)),
                bin_mask_ids=bin_ids,
            )
            log_parts.append(result)

        else:
            log_parts.append(f"Unknown step type '{stype}' — skipped.\n")

    return "".join(log_parts)


# ── Main panel ─────────────────────────────────────────────────────────────────


class WorkflowPanel(QWidget):
    """Unified Reduce + Post-process workflow panel.

    Signals
    -------
    workflowExecuted()
        Emitted after the queue executes successfully — host uses this to
        refresh the Runs summary panel.
    """

    workflowExecuted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ipts: int | None = None
        self._campaignSlug: str | None = None
        self._runNumber: int | None = None
        self._expertMode: bool = False
        self._execThread: QThread | None = None
        self._execWorker: GenericWorker | None = None
        self._logHandler: QtLogHandler | None = None
        # step_type → card widget
        self._cards: dict[str, QGroupBox] = {}

        self._buildUi()

    # ── UI construction ───────────────────────────────────────────────

    def _buildUi(self) -> None:
        layout = QVBoxLayout(self)

        # Context label
        self._ctxLabel = QLabel("No campaign selected.")
        self._ctxLabel.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self._ctxLabel)

        # Run number + expert mode row
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Run:"))
        self._runLabel = QLabel("—")
        self._runLabel.setStyleSheet("font-weight: bold;")
        top_row.addWidget(self._runLabel)
        top_row.addSpacing(20)
        self._expertCheck = QCheckBox("Expert mode")
        self._expertCheck.setToolTip(
            "Show advanced wrap.reduce options.\n"
            "Note: only a subset of options are shown — more will be added as needed."
        )
        self._expertCheck.toggled.connect(self._onExpertModeToggled)
        top_row.addWidget(self._expertCheck)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        # Step management row
        mgmt_row = QHBoxLayout()
        mgmt_row.addWidget(QLabel("Add step:"))
        self._addCombo = QComboBox()
        self._addCombo.setMaximumWidth(160)
        for st in STEP_TYPES:
            self._addCombo.addItem(STEP_LABELS[st], st)
        mgmt_row.addWidget(self._addCombo)
        self._addBtn = QPushButton("+")
        self._addBtn.setFixedWidth(32)
        self._addBtn.setToolTip("Add the selected step to the queue")
        self._addBtn.clicked.connect(self._onAddStep)
        mgmt_row.addWidget(self._addBtn)

        mgmt_row.addSpacing(16)
        mgmt_row.addWidget(QLabel("Copy from run:"))
        self._copyRunEdit = QLineEdit()
        self._copyRunEdit.setMaximumWidth(100)
        self._copyRunEdit.setPlaceholderText("run no.")
        mgmt_row.addWidget(self._copyRunEdit)
        self._copyBtn = QPushButton("Copy")
        self._copyBtn.setToolTip(
            "Copy the queue from another run into this one.\n"
            "Artefacts absent here are flagged ⚠."
        )
        self._copyBtn.clicked.connect(self._onCopyFromRun)
        mgmt_row.addWidget(self._copyBtn)
        mgmt_row.addStretch(1)
        layout.addLayout(mgmt_row)

        # Scrollable step cards area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.NoFrame)
        self._cardsContainer = QWidget()
        self._cardsLayout = QVBoxLayout(self._cardsContainer)
        self._cardsLayout.setAlignment(Qt.AlignTop)
        self._cardsLayout.addStretch(1)
        scroll.setWidget(self._cardsContainer)
        layout.addWidget(scroll, stretch=3)

        # Action buttons
        btn_row = QHBoxLayout()
        self._saveBtn = QPushButton("Save queue")
        self._saveBtn.setToolTip("Persist the current queue to disk")
        self._saveBtn.clicked.connect(self._onSaveQueue)
        btn_row.addWidget(self._saveBtn)

        self._execBtn = QPushButton("▶  Execute queue")
        self._execBtn.setToolTip("Run all steps in order")
        self._execBtn.clicked.connect(self._onExecuteQueue)
        btn_row.addWidget(self._execBtn)
        btn_row.addStretch(1)

        self._clearLogBtn = QPushButton("Clear log")
        self._clearLogBtn.clicked.connect(self._logEdit.clear if hasattr(self, "_logEdit") else lambda: None)
        btn_row.addWidget(self._clearLogBtn)
        layout.addLayout(btn_row)

        # Log pane
        self._logEdit = QPlainTextEdit()
        self._logEdit.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self._logEdit.setFont(mono)
        self._logEdit.setMaximumBlockCount(5000)
        layout.addWidget(self._logEdit, stretch=2)

        # Wire up clear log now that _logEdit exists
        self._clearLogBtn.clicked.disconnect()
        self._clearLogBtn.clicked.connect(self._logEdit.clear)

        self._updateButtonStates()

    # ── Public API ─────────────────────────────────────────────────────

    def setContext(self, ipts: int | None, campaign_slug: str | None) -> None:
        self._ipts = ipts
        self._campaignSlug = campaign_slug
        if ipts is not None and campaign_slug:
            self._ctxLabel.setText(f"IPTS-{ipts} / {campaign_slug}")
        else:
            self._ctxLabel.setText("No campaign selected.")
        self._updateButtonStates()

    def setRunNumber(self, run_number: int) -> None:
        self._runNumber = run_number
        self._runLabel.setText(str(run_number))
        self._loadQueue()
        self._refreshArtefacts()
        self._updateButtonStates()

    # ── Internals ──────────────────────────────────────────────────────

    def _updateButtonStates(self) -> None:
        has_ctx = self._ipts is not None and bool(self._campaignSlug)
        has_run = self._runNumber is not None
        ready = has_ctx and has_run and bool(self._cards)
        self._saveBtn.setEnabled(has_ctx and has_run)
        self._execBtn.setEnabled(ready and self._execThread is None)
        self._addBtn.setEnabled(has_ctx and has_run)
        self._copyBtn.setEnabled(has_ctx and has_run)

    def _appendLog(self, text: str) -> None:
        self._logEdit.appendPlainText(text)
        sb = self._logEdit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _onExpertModeToggled(self, checked: bool) -> None:
        self._expertMode = checked
        for card in self._cards.values():
            card.setExpertMode(checked)

    # ── Step card management ───────────────────────────────────────────

    def _onAddStep(self) -> None:
        step_type = self._addCombo.currentData()
        if step_type in self._cards:
            QMessageBox.information(
                self, "Step already exists",
                f"A '{STEP_LABELS[step_type]}' step is already in the queue.\n"
                "Remove it first to reconfigure."
            )
            return
        # Capability check
        required = STEP_REQUIRED_ARTEFACTS.get(step_type, [])
        if required and not self._hasActiveArtefacts(required):
            QMessageBox.warning(
                self, "Prerequisites not met",
                f"Cannot add '{STEP_LABELS[step_type]}' step:\n"
                f"No active artefacts of type(s) {required} found for this run."
            )
            return
        step = WorkflowStep.default(step_type)
        self._addCard(step)

    def _addCard(self, step: WorkflowStep) -> None:
        """Create and insert a step card, honouring STEP_TYPES execution order."""
        if step.step_type in self._cards:
            return
        cls = _CARD_CLASSES.get(step.step_type)
        if cls is None:
            return
        card: QGroupBox = cls(self)
        card.removeRequested.connect(self._removeCard)
        card.setExpertMode(self._expertMode)
        # Insert before the stretch item (always last)
        stretch_idx = self._cardsLayout.count() - 1
        # Find correct position by STEP_TYPES order
        existing_types = list(self._cards.keys())
        insert_pos = 0
        for i, st in enumerate(STEP_TYPES):
            if st == step.step_type:
                break
            if st in existing_types:
                insert_pos = self._cardsLayout.indexOf(self._cards[st]) + 1
        self._cardsLayout.insertWidget(insert_pos, card)
        self._cards[step.step_type] = card
        # Populate artefacts and restore state
        self._populateCardArtefacts(card, step.step_type)
        card.fromStep(step)
        self._updateButtonStates()

    def _removeCard(self, step_type: str) -> None:
        card = self._cards.pop(step_type, None)
        if card is not None:
            self._cardsLayout.removeWidget(card)
            card.deleteLater()
        self._updateButtonStates()

    def _hasActiveArtefacts(self, artefact_types: list[str]) -> bool:
        """Check if any active artefacts of the given types exist for this run."""
        try:
            from snapwrap.reduction_artefacts import list_artefact_records  # type: ignore
            for atype in artefact_types:
                recs = list_artefact_records(
                    ipts=self._ipts,
                    campaign_identifier=self._campaignSlug,
                    artefact_type=atype,
                    status="active",
                )
                if recs:
                    return True
            return False
        except Exception:
            return True  # optimistic if lookup fails

    def _populateCardArtefacts(self, card: QGroupBox, step_type: str) -> None:
        """Populate a card with current artefact lists."""
        if not (self._ipts and self._campaignSlug and self._runNumber is not None):
            return
        try:
            from snapwrap.reduction_artefacts import list_artefact_records  # type: ignore

            def _fetch(atype: str) -> list[dict[str, Any]]:
                all_recs = list_artefact_records(
                    ipts=self._ipts,
                    campaign_identifier=self._campaignSlug,
                    artefact_type=atype,
                    status="active",
                )
                return [
                    r for r in all_recs
                    if (r.get("run_context") or {}).get("run_number")
                    in (self._runNumber, None)
                ]

            bin_masks = _fetch("bin_mask")
            if step_type == "reduce":
                card.setArtefacts(
                    bin_masks=bin_masks,
                    pixel_masks=_fetch("pixel_mask"),
                    attenuations=_fetch("attenuation_workspace"),
                )
            elif step_type == "crop":
                card.setArtefacts(bin_masks=bin_masks)
        except Exception as exc:
            self._appendLog(f"  Warning: could not load artefacts: {exc}")

    # ── Queue persistence ──────────────────────────────────────────────

    def _buildQueue(self) -> WorkflowQueue:
        queue = WorkflowQueue(run_number=self._runNumber)
        for st in STEP_TYPES:
            if st in self._cards:
                queue.append(self._cards[st].toStep())
        return queue

    def _loadQueue(self) -> None:
        """Load the queue from disk and rebuild step cards."""
        if not (self._ipts and self._campaignSlug and self._runNumber is not None):
            return
        try:
            from snapwrap.reduction_artefacts import get_campaign_paths  # type: ignore
            paths = get_campaign_paths(
                ipts=self._ipts,
                campaign_identifier=self._campaignSlug,
            )
            queue = WorkflowQueue.load(paths.campaign_dir, self._runNumber)
        except Exception:
            queue = WorkflowQueue(run_number=self._runNumber)

        # Rebuild cards
        for st in list(self._cards.keys()):
            self._removeCard(st)
        for step in queue.steps:
            self._addCard(step)

    def _onSaveQueue(self) -> None:
        if not (self._ipts and self._campaignSlug and self._runNumber is not None):
            return
        try:
            from snapwrap.reduction_artefacts import get_campaign_paths  # type: ignore
            paths = get_campaign_paths(
                ipts=self._ipts,
                campaign_identifier=self._campaignSlug,
            )
            queue = self._buildQueue()
            saved = queue.save(paths.campaign_dir)
            self._appendLog(f"Queue saved: {saved.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _onCopyFromRun(self) -> None:
        src_text = self._copyRunEdit.text().strip()
        try:
            src_run = int(src_text)
        except ValueError:
            QMessageBox.warning(
                self, "Invalid run", "Enter a valid source run number."
            )
            return
        if not (self._ipts and self._campaignSlug and self._runNumber is not None):
            return
        try:
            from snapwrap.reduction_artefacts import get_campaign_paths, list_artefact_records  # type: ignore
            paths = get_campaign_paths(
                ipts=self._ipts, campaign_identifier=self._campaignSlug,
            )
            src_queue = WorkflowQueue.load(paths.campaign_dir, src_run)
            if not src_queue.steps:
                QMessageBox.information(
                    self, "No queue", f"No saved queue found for run {src_run}."
                )
                return
            all_recs = list_artefact_records(
                ipts=self._ipts, campaign_identifier=self._campaignSlug, status="active",
            )
            available_ids = {r["artefact_id"] for r in all_recs if r.get("artefact_id")}
            new_queue = WorkflowQueue.copy_from_run(src_queue, self._runNumber, available_ids)
        except Exception as exc:
            QMessageBox.warning(self, "Copy failed", str(exc))
            return
        for st in list(self._cards.keys()):
            self._removeCard(st)
        for step in new_queue.steps:
            self._addCard(step)
        if new_queue.has_missing_artefacts():
            self._appendLog(
                f"⚠  Copied queue from run {src_run}. "
                "Some artefacts are not yet registered for this run (shown as :MISSING)."
            )
        else:
            self._appendLog(f"Copied queue from run {src_run}.")

    # ── Queue execution ────────────────────────────────────────────────

    def _onExecuteQueue(self) -> None:
        if self._execThread is not None:
            QMessageBox.information(
                self, "Busy", "A workflow execution is already running."
            )
            return
        if not (self._ipts and self._campaignSlug and self._runNumber is not None):
            QMessageBox.warning(self, "No context", "Select a campaign and run first.")
            return
        if not self._cards:
            QMessageBox.warning(self, "Empty queue", "Add at least one step before executing.")
            return

        queue = self._buildQueue()
        if queue.has_missing_artefacts():
            QMessageBox.warning(
                self, "Missing artefacts",
                "Some selected artefacts are marked :MISSING for this run.\n"
                "Register the required artefacts before executing."
            )
            return

        steps_data = [s.to_dict() for s in queue.steps]
        step_labels = " → ".join(STEP_LABELS.get(s.step_type, s.step_type) for s in queue.steps)
        self._appendLog(
            f"\n── Executing workflow: run {self._runNumber}  "
            f"IPTS-{self._ipts} / {self._campaignSlug}\n"
            f"   Steps: {step_labels}\n"
        )

        self._execBtn.setEnabled(False)
        self._saveBtn.setEnabled(False)
        self._installLogHandler()

        thread = QThread(self)
        worker = GenericWorker(
            _execute_queue_fn,
            {
                "steps": steps_data,
                "run_number": self._runNumber,
                "ipts": self._ipts,
                "campaign_slug": self._campaignSlug,
            },
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._onExecFinished)
        worker.error.connect(self._onExecError)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._onExecCleanup)
        thread.start()
        self._execThread = thread
        self._execWorker = worker

    def _onExecFinished(self, result: Any) -> None:
        if isinstance(result, str) and result.strip():
            self._appendLog(result)
        self._appendLog("\n── Workflow complete. ──")
        self.workflowExecuted.emit()

    def _onExecError(self, message: str) -> None:
        self._appendLog(f"\n── ERROR: {message} ──")
        QMessageBox.warning(self, "Workflow failed", message)

    def _onExecCleanup(self) -> None:
        self._uninstallLogHandler()
        self._execThread = None
        self._execWorker = None
        self._updateButtonStates()
        self._saveBtn.setEnabled(
            self._ipts is not None and bool(self._campaignSlug) and self._runNumber is not None
        )

    # ── Log handler ────────────────────────────────────────────────────

    def _installLogHandler(self) -> None:
        handler = QtLogHandler()
        handler.logLine.connect(self._appendLog)
        logger = logging.getLogger(_SNAPWRAP_LOGGER)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        self._logHandler = handler

    def _uninstallLogHandler(self) -> None:
        if self._logHandler is not None:
            logging.getLogger(_SNAPWRAP_LOGGER).removeHandler(self._logHandler)
            self._logHandler = None

    # ── Artefact refresh ───────────────────────────────────────────────

    def _refreshArtefacts(self) -> None:
        """Re-populate all existing step cards with current artefact lists."""
        for step_type, card in self._cards.items():
            self._populateCardArtefacts(card, step_type)
