"""Main window for the SNAPWrap Campaign Manager.

Phase 0+1 layout:

* A context bar at the top — IPTS picker + campaign picker + Reload.
* A tab widget with one populated tab (Artefacts) and placeholders for
  Runs / Reduce / Setup (Phase 2+).

Data loading runs on background threads via :mod:`workers` so the GUI
stays responsive even when the artefacts index is large.
"""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import QThread, Qt  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from snapwrap.campaignManager.dialogs import CopyArtefactDialog, CopyCrystalSpeciesDialog, IngestAssetDialog, NewCampaignDialog
from snapwrap.campaignManager.model import CampaignManagerModel
from snapwrap.campaignManager.panels.artefactsPanel import ArtefactsPanel
from snapwrap.campaignManager.panels.runsPanel import RunsPanel
from snapwrap.campaignManager.panels.setupPanel import SetupPanel
from snapwrap.campaignManager.panels.workflowPanel import WorkflowPanel
from snapwrap.campaignManager.workers import GenericWorker


_PLACEHOLDER_TEXT = (
    "Coming in a later phase.\n\n"
    "This tab will host the corresponding workflow once Phase 1 (read-only "
    "Artefacts) has been validated with real operator usage."
)


def _placeholderTab(title: str) -> QWidget:
    """Trivial 'coming soon' widget used for unimplemented tabs."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    label = QLabel(f"{title}\n\n{_PLACEHOLDER_TEXT}")
    label.setAlignment(Qt.AlignCenter)
    label.setWordWrap(True)
    layout.addWidget(label)
    return widget


class CampaignManager(QDialog):
    """Top-level Campaign Manager dialog."""

    _IPTS_PLACEHOLDER = "— select IPTS —"
    _CAMPAIGN_PLACEHOLDER = "— select campaign —"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SNAPWrap Campaign Manager")
        self.setMinimumSize(960, 640)

        self._model = CampaignManagerModel()
        self._loadThread: QThread | None = None
        self._loadWorker: GenericWorker | None = None

        self._buildUi()
        self._populateIPTSList()

    # ── UI construction ──────────────────────────────────────────────

    def _buildUi(self) -> None:
        layout = QVBoxLayout(self)

        # Context bar.
        ctx = QHBoxLayout()
        ctx.addWidget(QLabel("IPTS:"))

        # Editable combo: operator can pick from the discovered list OR
        # type a number directly (handy when there are 200+ proposals,
        # or when picking an IPTS the user has access to but which isn't
        # listed under /SNS/SNAP from this machine).
        self._iptsCombo = QComboBox()
        self._iptsCombo.setEditable(True)
        self._iptsCombo.setInsertPolicy(QComboBox.NoInsert)
        self._iptsCombo.setMinimumWidth(180)
        self._iptsCombo.lineEdit().setPlaceholderText("type or pick (e.g. 33219)")
        # Pick on selection from the list.
        self._iptsCombo.activated.connect(self._onIPTSPicked)
        # Submit on Enter inside the line edit.
        self._iptsCombo.lineEdit().returnPressed.connect(self._onIPTSSubmitted)
        ctx.addWidget(self._iptsCombo)

        self._iptsGoBtn = QPushButton("Go")
        self._iptsGoBtn.setToolTip("Load the typed IPTS")
        self._iptsGoBtn.clicked.connect(self._onIPTSSubmitted)
        ctx.addWidget(self._iptsGoBtn)

        ctx.addSpacing(12)
        ctx.addWidget(QLabel("Campaign:"))
        self._campaignCombo = QComboBox()
        self._campaignCombo.setMinimumWidth(220)
        self._campaignCombo.currentTextChanged.connect(self._onCampaignChanged)
        ctx.addWidget(self._campaignCombo)

        self._newCampaignBtn = QPushButton("+ New…")
        self._newCampaignBtn.setToolTip("Create a new campaign under the selected IPTS")
        self._newCampaignBtn.clicked.connect(self._onNewCampaignClicked)
        ctx.addWidget(self._newCampaignBtn)

        self._renameCampaignBtn = QPushButton("Rename…")
        self._renameCampaignBtn.setToolTip("Rename the selected campaign slug")
        self._renameCampaignBtn.setEnabled(False)
        self._renameCampaignBtn.clicked.connect(self._onRenameCampaignClicked)
        ctx.addWidget(self._renameCampaignBtn)

        self._deleteCampaignBtn = QPushButton("Delete…")
        self._deleteCampaignBtn.setToolTip("Permanently delete this campaign and all its artefacts")
        self._deleteCampaignBtn.setEnabled(False)
        self._deleteCampaignBtn.clicked.connect(self._onDeleteCampaignClicked)
        ctx.addWidget(self._deleteCampaignBtn)

        ctx.addStretch(1)

        self._liteModeCheck = QCheckBox("Lite mode")
        self._liteModeCheck.setChecked(True)
        self._liteModeCheck.setToolTip(
            "Lite mode: 18 432 detector pixels (fast).\n"
            "Unchecked: full native 1 179 648 pixels."
        )
        self._liteModeCheck.toggled.connect(self._onLiteModeToggled)
        ctx.addWidget(self._liteModeCheck)

        ctx.addSpacing(8)
        self._reloadBtn = QPushButton("Reload")
        self._reloadBtn.clicked.connect(self._reloadCurrent)
        ctx.addWidget(self._reloadBtn)

        layout.addLayout(ctx)

        # Tabs.
        self._tabs = QTabWidget(self)
        self._artefactsPanel = ArtefactsPanel(self)
        self._artefactsPanel.refreshRequested.connect(self._reloadCurrent)
        self._artefactsPanel.retireRequested.connect(self._onRetireRequested)
        self._artefactsPanel.copyRequested.connect(self._onCopyRequested)
        self._artefactsPanel.copyCrystalSpeciesRequested.connect(self._onCopyCrystalSpeciesRequested)
        self._artefactsPanel.openFileRequested.connect(self._onOpenFileRequested)
        self._runsPanel = RunsPanel(self)
        self._runsPanel.refreshRequested.connect(self._reloadRunSummaries)

        self._workflowPanel = WorkflowPanel(self)
        self._runsPanel.runSelected.connect(self._workflowPanel.setRunNumber)
        self._runsPanel.runSelected.connect(lambda _: self._tabs.setCurrentWidget(self._workflowPanel))
        self._workflowPanel.workflowExecuted.connect(self._reloadRunSummaries)

        self._setupPanel = SetupPanel(self)
        self._setupPanel.ingestRequested.connect(self._onIngestRequested)
        self._setupPanel.refreshRequested.connect(self._reloadSetup)
        self._setupPanel.pixelMaskRegistrationRequested.connect(self._onPixelMaskRegistrationRequested)
        self._setupPanel.crystalSpeciesRegistrationRequested.connect(self._onCrystalSpeciesRegistrationRequested)
        self._setupPanel.binMaskFromMonitorRequested.connect(self._onBinMaskFromMonitorRequested)
        self._setupPanel.binMaskManualRequested.connect(self._onBinMaskManualRequested)
        self._setupPanel.binMaskFromWorkspaceRequested.connect(self._onBinMaskFromWorkspaceRequested)
        self._setupPanel.binMaskFromJsonRequested.connect(self._onBinMaskFromJsonRequested)
        self._setupPanel.assetDeleteRequested.connect(self._onAssetDeleteRequested)

        self._tabs.addTab(self._setupPanel, "Setup")
        self._tabs.addTab(self._artefactsPanel, "Artefacts")
        self._tabs.addTab(self._runsPanel, "Runs")
        self._tabs.addTab(self._workflowPanel, "Workflow")
        self._tabs.setCurrentWidget(self._artefactsPanel)
        self._tabs.currentChanged.connect(self._onTabChanged)
        layout.addWidget(self._tabs, stretch=1)

        # Status bar with embedded progress bar.
        self._statusBar = QStatusBar(self)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        self._progress.setFixedWidth(160)
        self._statusBar.addPermanentWidget(self._progress)
        layout.addWidget(self._statusBar)

        self._setStatus("Ready.")

    def _setStatus(self, text: str) -> None:
        self._statusBar.showMessage(text)

    # ── IPTS / campaign pickers ──────────────────────────────────────

    def _populateIPTSList(self) -> None:
        """Fill the combo with discovered IPTSs and wire up a substring completer.

        The combo stays editable so an operator can type a number that
        isn't in the discovered list (or that they don't want to scroll
        for, given ~200 proposals).
        """
        self._iptsCombo.blockSignals(True)
        self._iptsCombo.clear()
        # First item is the placeholder; userData=None marks "no selection".
        self._iptsCombo.addItem(self._IPTS_PLACEHOLDER, userData=None)

        try:
            ipts_list = self._model.discoverIPTSList()
        except Exception as exc:  # pragma: no cover - filesystem-dependent
            QMessageBox.warning(
                self, "IPTS discovery failed", f"{type(exc).__name__}: {exc}"
            )
            ipts_list = []
        for ipts in ipts_list:
            self._iptsCombo.addItem(f"IPTS-{ipts}", userData=ipts)

        # Substring completer over the visible labels — typing "332"
        # narrows the popup to anything containing "332".
        completer = QCompleter([f"IPTS-{i}" for i in ipts_list], self._iptsCombo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self._iptsCombo.setCompleter(completer)

        # Reset the line edit so the placeholder is visible at startup.
        self._iptsCombo.setCurrentIndex(0)
        self._iptsCombo.lineEdit().clear()
        self._iptsCombo.blockSignals(False)

        self._setStatus(
            f"Discovered {len(ipts_list)} IPTS folder(s) — "
            "you can also type any IPTS number you have access to."
        )

    @staticmethod
    def _parseIPTS(text: str) -> int | None:
        """Convert a user-entered string into an IPTS number, or None."""
        if text is None:
            return None
        t = text.strip()
        if not t or t.startswith("—"):
            return None
        if t.upper().startswith("IPTS-"):
            t = t[5:].strip()
        if t.isdigit():
            return int(t)
        return None

    def _currentIPTS(self) -> int | None:
        """Resolve the IPTS that should drive the current view.

        Preference order:

        1. ``userData`` on the selected combo item (if a known entry is
           selected — the most common case).
        2. The number parsed out of the line-edit text (covers the
           "operator typed a value not in the discovered list" case).
        """
        data = self._iptsCombo.currentData()
        if data is not None:
            return int(data)
        return self._parseIPTS(self._iptsCombo.currentText())

    def _currentCampaign(self) -> str | None:
        text = self._campaignCombo.currentText()
        if not text or text == self._CAMPAIGN_PLACEHOLDER:
            return None
        return text

    def _onIPTSPicked(self, _index: int) -> None:
        """Triggered when the operator selects an item from the popup."""
        self._loadIPTSCampaigns()

    def _onIPTSSubmitted(self) -> None:
        """Triggered by Enter in the line edit or clicking 'Go'."""
        ipts = self._parseIPTS(self._iptsCombo.currentText())
        if ipts is None:
            QMessageBox.warning(
                self,
                "Invalid IPTS",
                "Type an IPTS number (e.g. 33219) or 'IPTS-33219'.",
            )
            return
        # Try to align the combo with an existing entry so userData is set;
        # if not present, the line-edit text still carries the value and
        # _currentIPTS() falls back to parsing it.
        idx = self._iptsCombo.findData(ipts)
        if idx >= 0:
            self._iptsCombo.setCurrentIndex(idx)
        self._loadIPTSCampaigns()

    def _loadIPTSCampaigns(self) -> None:
        """Fetch and display the campaign list for the currently-selected IPTS."""
        ipts = self._currentIPTS()
        self._campaignCombo.blockSignals(True)
        self._campaignCombo.clear()
        self._campaignCombo.addItem(self._CAMPAIGN_PLACEHOLDER)
        self._campaignCombo.blockSignals(False)
        self._artefactsPanel.setRecords([])

        if ipts is None:
            return

        try:
            campaigns = self._model.getCampaigns(ipts=ipts)
        except FileNotFoundError:
            self._setStatus(
                f"IPTS-{ipts}: shared root not accessible from this machine."
            )
            return
        except PermissionError:
            self._setStatus(
                f"IPTS-{ipts}: permission denied (you are not on this proposal)."
            )
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Campaign discovery failed",
                f"{type(exc).__name__}: {exc}",
            )
            return

        if not campaigns:
            self._setStatus(f"IPTS-{ipts}: no campaigns registered.")
            return

        self._campaignCombo.blockSignals(True)
        for c in campaigns:
            slug = c.get("campaign_slug", "")
            cid = c.get("campaign_id", "")
            label = f"{slug}  (id={cid})" if cid != "" else slug
            self._campaignCombo.addItem(label, userData=slug)
        self._campaignCombo.blockSignals(False)
        self._setStatus(f"IPTS-{ipts}: {len(campaigns)} campaign(s).")

    def _onLiteModeToggled(self, checked: bool) -> None:
        self._workflowPanel.setLiteMode(checked)

    def _onCampaignChanged(self, _text: str) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        has_campaign = ipts is not None and bool(slug)
        self._renameCampaignBtn.setEnabled(has_campaign)
        self._deleteCampaignBtn.setEnabled(has_campaign)
        if not has_campaign:
            self._workflowPanel.setContext(None, None)
            self._setupPanel.setIPTS(None)
            return
        self._workflowPanel.setContext(ipts, slug)
        self._setupPanel.setIPTS(ipts)
        self._reloadCurrent()
        self._reloadRunSummaries()
        self._reloadSetup()

    def _onNewCampaignClicked(self) -> None:
        ipts = self._currentIPTS()
        if ipts is None:
            QMessageBox.warning(
                self,
                "No IPTS selected",
                "Select an IPTS before creating a campaign.",
            )
            return

        dlg = NewCampaignDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        slug = dlg.slug()

        def _after_success() -> None:
            self._loadIPTSCampaigns()
            idx = self._campaignCombo.findData(slug)
            if idx >= 0:
                self._campaignCombo.setCurrentIndex(idx)

        self._runMutation(
            label=f"Creating campaign '{slug}'",
            fn=self._model.createCampaign,
            kwargs={
                "ipts": ipts,
                "campaign_slug": slug,
                "assembly_type": dlg.assemblyType(),
                "description": dlg.description(),
                "owners": dlg.owners(),
            },
            success_msg=lambda _result: f"Campaign '{slug}' created.",
            after_success=_after_success,
        )

    def _onRenameCampaignClicked(self) -> None:
        ipts = self._currentIPTS()
        old_slug = self._campaignCombo.currentData()
        if ipts is None or not old_slug:
            return

        new_slug, ok = QInputDialog.getText(
            self,
            "Rename campaign",
            f"New slug for <b>{old_slug}</b>:<br>"
            "<small>(lowercase letters, digits, hyphens/underscores, 2–63 chars)</small>",
            text=old_slug,
        )
        if not ok or not new_slug.strip():
            return
        new_slug = new_slug.strip()
        if new_slug == old_slug:
            return

        def _after_success() -> None:
            self._loadIPTSCampaigns()
            idx = self._campaignCombo.findData(new_slug)
            if idx >= 0:
                self._campaignCombo.setCurrentIndex(idx)

        self._runMutation(
            label=f"Renaming '{old_slug}' → '{new_slug}'…",
            fn=self._model.renameCampaign,
            kwargs={"ipts": ipts, "old_slug": old_slug, "new_slug": new_slug},
            success_msg=lambda r: f"Campaign renamed to '{r.get('campaign_slug', new_slug)}'.",
            after_success=_after_success,
        )

    def _onDeleteCampaignClicked(self) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            return

        typed, ok = QInputDialog.getText(
            self,
            "Delete campaign — confirm",
            (
                f"This will permanently delete campaign <b>'{slug}'</b> from IPTS-{ipts} "
                "and all its contents (artefact records, assets, thumbnails).<br><br>"
                f"Type <b>{slug}</b> to confirm:"
            ),
        )
        if not ok or typed.strip() != slug:
            if ok:
                QMessageBox.warning(self, "Cancelled", "Campaign name did not match — deletion cancelled.")
            return

        def _after_success() -> None:
            self._loadIPTSCampaigns()

        self._runMutation(
            label=f"Deleting campaign '{slug}'…",
            fn=self._model.deleteCampaign,
            kwargs={"ipts": ipts, "campaign_identifier": slug},
            success_msg=lambda _r: f"Campaign '{slug}' deleted.",
            after_success=_after_success,
        )

    # ── Data loading (background) ────────────────────────────────────

    def _onTabChanged(self, _index: int) -> None:
        """Auto-refresh the Artefacts panel whenever the user switches to it."""
        if self._tabs.currentWidget() is self._artefactsPanel:
            self._reloadCurrent()

    def _reloadCurrent(self) -> None:
        ipts = self._currentIPTS()
        slug_label = self._campaignCombo.currentData()
        if ipts is None or not slug_label:
            self._setStatus("Pick an IPTS and a campaign.")
            return

        if self._loadThread is not None:
            # A load is already in flight; ignore the click.
            return

        self._setStatus(
            f"Loading artefacts for IPTS-{ipts} / {slug_label}…"
        )
        self._progress.setVisible(True)
        self._reloadBtn.setEnabled(False)

        thread = QThread(self)
        worker = GenericWorker(
            self._model.getArtefacts,
            {"ipts": ipts, "campaign_identifier": slug_label},
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._onLoadFinished)
        worker.error.connect(self._onLoadError)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._onLoadCleanup)
        thread.start()
        self._loadThread = thread
        self._loadWorker = worker

    def _reloadSetup(self) -> None:
        """Refresh the Setup panel's assets table (synchronous — fast)."""
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            self._setupPanel.setRows([])
            return
        try:
            assets = self._model.getAssets(ipts=ipts, campaign_identifier=slug)
        except Exception as exc:
            self._setStatus(f"Assets load failed: {exc}")
            return
        self._setupPanel.setRows(assets)

    def _reloadRunSummaries(self) -> None:
        """Refresh the Runs panel from artefact records (synchronous — fast)."""
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        runs_idx = self._tabs.indexOf(self._runsPanel)
        if ipts is None or not slug:
            self._runsPanel.setRows([])
            self._tabs.setTabEnabled(runs_idx, False)
            self._tabs.setTabToolTip(runs_idx, "No runs with artefacts yet — use Reduce to start.")
            return
        try:
            summaries = self._model.getRunSummaries(
                ipts=ipts, campaign_identifier=slug
            )
        except Exception as exc:
            self._setStatus(f"Run summary failed: {exc}")
            return
        self._runsPanel.setRows(summaries)
        has_runs = bool(summaries)
        self._tabs.setTabEnabled(runs_idx, has_runs)
        self._tabs.setTabToolTip(
            runs_idx,
            "" if has_runs else "No runs with artefacts yet — use Reduce to start.",
        )

    def _onLoadFinished(self, records: Any) -> None:
        if not isinstance(records, list):
            records = []
        self._artefactsPanel.setRecords(records)
        self._setStatus(f"Loaded {len(records)} artefact record(s).")

    def _onLoadError(self, message: str) -> None:
        QMessageBox.warning(self, "Load failed", message)
        self._setStatus(f"Load failed: {message}")

    def _onLoadCleanup(self) -> None:
        self._loadThread = None
        self._loadWorker = None
        self._progress.setVisible(False)
        self._reloadBtn.setEnabled(True)

    # ── Mutations (Retire / Copy / Open file) ────────────────────────

    def _onRetireRequested(self, record: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            return

        artefact_id = record.get("artefact_id", "")

        # Crystal species have no status field — "retire" is a hard delete.
        if record.get("artefact_type") == "crystal_species":
            confirm = QMessageBox.question(
                self,
                "Delete crystal species?",
                (
                    f"Permanently remove crystal species <b>{artefact_id}</b>?<br><br>"
                    "Crystal species records have no 'retired' state — this removes "
                    "the entry completely and cannot be undone."
                ),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if confirm != QMessageBox.Yes:
                return
            self._runMutation(
                label=f"Deleting crystal species '{artefact_id}'…",
                fn=self._model.deleteCrystalSpecies,
                kwargs={"ipts": ipts, "campaign_identifier": slug, "record_id": artefact_id},
                success_msg=lambda n: f"Deleted {n} crystal species record(s).",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Retire artefact?",
            (
                f"Mark <b>{artefact_id}</b> as retired?<br><br>"
                "Reduction will skip it on the next run.  The JSONL index will be "
                "rewritten with this record's status set to 'retired'."
            ),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return

        self._runMutation(
            label=f"Retiring {artefact_id}",
            fn=self._model.retireArtefact,
            kwargs={
                "ipts": ipts,
                "campaign_identifier": slug,
                "artefact_id": artefact_id,
            },
            success_msg=lambda result: f"Retired {result} record(s) for {artefact_id}.",
        )

    def _onCopyRequested(self, record: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            return

        dlg = CopyArtefactDialog(record, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        new_id = dlg.newArtefactId()
        if not new_id:
            QMessageBox.warning(self, "Copy artefact", "New artefact id is required.")
            return

        self._runMutation(
            label=f"Copying {record.get('artefact_id', '')} → {new_id}",
            fn=self._model.copyArtefact,
            kwargs={
                "ipts": ipts,
                "campaign_identifier": slug,
                "source_artefact_id": record.get("artefact_id", ""),
                "new_artefact_id": new_id,
                "run_number": dlg.runNumberOverride(),
                "copy_file": dlg.copyFile(),
                "notes": dlg.notes(),
            },
            success_msg=lambda _result: f"Registered new artefact {new_id}.",
        )

    def _onCopyCrystalSpeciesRequested(self, record: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            return
        cs = record.get("_crystal_species", {})
        dlg = CopyCrystalSpeciesDialog(cs, ipts, slug, self._model, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        target_ipts = dlg.targetIpts()
        target_campaign = dlg.targetCampaign()
        if target_ipts is None or not target_campaign:
            return
        species = cs.get("species_name", "?")
        self._runMutation(
            label=f"Copying '{species}' to {target_campaign}…",
            fn=self._model.copyCrystalSpeciesToCampaign,
            kwargs={"cs_record": cs, "target_ipts": target_ipts, "target_campaign": target_campaign},
            success_msg=lambda _r: f"Copied '{species}' to campaign '{target_campaign}'.",
        )

    def _onPixelMaskRegistrationRequested(self, params: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        def _after_success() -> None:
            self._reloadCurrent()
            self._reloadSetup()

        self._runMutation(
            label="Registering pixel mask…",
            fn=self._model.registerPixelMask,
            kwargs={
                "ipts": ipts,
                "campaign_identifier": slug,
                **params,
            },
            success_msg=lambda r: f"Pixel mask '{r.get('artefact_id', '')}' registered.",
            after_success=_after_success,
        )

    def _onAssetDeleteRequested(self, asset_id: str) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return
        reply = QMessageBox.question(
            self,
            "Delete asset",
            f"Permanently remove asset <b>{asset_id}</b> from the index?<br>"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._runMutation(
            label=f"Deleting asset '{asset_id}'…",
            fn=self._model.deleteAsset,
            kwargs={"ipts": ipts, "campaign_identifier": slug, "asset_id": asset_id},
            success_msg=lambda n: f"Deleted {n} record(s) for asset '{asset_id}'.",
            after_success=self._reloadSetup,
        )

    def _onCrystalSpeciesRegistrationRequested(self, params: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        def _after_success() -> None:
            self._reloadCurrent()

        self._runMutation(
            label=f"Registering crystal species '{params.get('species_name', '')}'…",
            fn=self._model.registerCrystalSpecies,
            kwargs={
                "ipts": ipts,
                "campaign_identifier": slug,
                **params,
            },
            success_msg=lambda r: f"Crystal species '{r.get('species_name', '')}' registered.",
            after_success=_after_success,
        )

    def _onBinMaskFromMonitorRequested(self, params: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        def _after_success() -> None:
            self._reloadCurrent()
            self._reloadRunSummaries()

        run = params.get("run_number", "?")
        self._runMutation(
            label=f"Building bin mask from transmission monitor (run {run})…",
            fn=self._model.registerBinMaskFromTransmission,
            kwargs={"ipts": ipts, "campaign_identifier": slug, **params},
            success_msg=lambda recs: (
                f"Registered {len(recs)} bin mask artefact(s) from run {run}."
                if isinstance(recs, list) else "Bin mask registered."
            ),
            after_success=_after_success,
        )

    def _onBinMaskManualRequested(self, params: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        def _after_success() -> None:
            self._reloadCurrent()
            self._reloadRunSummaries()

        n = len(params.get("notches", []))
        run = params.get("run_number")
        scope = f"run {run}" if run is not None else "campaign-wide"
        self._runMutation(
            label=f"Registering manual bin mask ({n} notch(es), {scope})…",
            fn=self._model.registerManualNotchMask,
            kwargs={"ipts": ipts, "campaign_identifier": slug, **params},
            success_msg=lambda _r: f"Manual bin mask registered ({n} notch(es), {scope}).",
            after_success=_after_success,
        )

    def _onBinMaskFromWorkspaceRequested(self, params: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        def _after_success() -> None:
            self._reloadCurrent()
            self._reloadRunSummaries()

        ws = params.get("ws_name", "?")
        run = params.get("run_number")
        scope = f"run {run}" if run is not None else "campaign-wide"
        self._runMutation(
            label=f"Extracting bin mask from '{ws}' history ({scope})…",
            fn=self._model.registerBinMaskFromWorkspaceHistory,
            kwargs={"ipts": ipts, "campaign_identifier": slug, **params},
            success_msg=lambda recs: (
                f"Registered {len(recs)} bin mask artefact(s) from workspace '{ws}'."
                if isinstance(recs, list) else f"Bin mask from workspace '{ws}' registered."
            ),
            after_success=_after_success,
        )

    def _onBinMaskFromJsonRequested(self, params: dict[str, Any]) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        def _after_success() -> None:
            self._reloadCurrent()
            self._reloadRunSummaries()

        from pathlib import Path as _Path
        fname = _Path(params.get("json_path", "")).name
        run = params.get("run_number")
        scope = f"run {run}" if run is not None else "campaign-wide"
        self._runMutation(
            label=f"Registering bin mask from '{fname}' ({scope})…",
            fn=self._model.registerBinMaskFromJsonFile,
            kwargs={"ipts": ipts, "campaign_identifier": slug, **params},
            success_msg=lambda _r: f"Bin mask from '{fname}' registered ({scope}).",
            after_success=_after_success,
        )

    def _onIngestRequested(self) -> None:
        ipts = self._currentIPTS()
        slug = self._campaignCombo.currentData()
        if ipts is None or not slug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        dlg = IngestAssetDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        run_number = dlg.runNumber() if dlg.scope() == "run" else None

        self._runMutation(
            label=f"Ingesting {dlg.assetType()} asset",
            fn=self._model.ingestAsset,
            kwargs={
                "ipts": ipts,
                "campaign_identifier": slug,
                "source_path": dlg.filePath(),
                "asset_type": dlg.assetType(),
                "asset_id": dlg.assetId(),
                "applicability_scope": dlg.scope(),
                "run_number": run_number,
                "notes": dlg.notes(),
            },
            success_msg=lambda rec: f"Ingested asset '{rec.get('asset_id', '')}'.",
            after_success=self._reloadSetup,
        )

    def _onOpenFileRequested(self, record: dict[str, Any]) -> None:
        from pathlib import Path

        from qtpy.QtCore import QUrl  # type: ignore
        from qtpy.QtGui import QDesktopServices  # type: ignore

        path_str = (
            record.get("path")
            or record.get("file_path")
            or record.get("mask_json_path")
            or (record.get("_crystal_species") or {}).get("cifPath")
            or ""
        )
        if not path_str:
            self._setStatus("No file path on this record.")
            return

        path = Path(path_str)
        target = path if path.is_dir() else path.parent
        if not target.exists():
            QMessageBox.warning(
                self,
                "Path not found",
                f"The artefact's file location does not exist:<br><tt>{target}</tt>",
            )
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        self._setStatus(f"Opened {target}")

    # ── Generic mutation runner (background thread) ──────────────────

    def _runMutation(
        self,
        *,
        label: str,
        fn,
        kwargs: dict[str, Any],
        success_msg,
        after_success=None,
    ) -> None:
        """Dispatch a backend mutation onto a worker thread and refresh on success.

        ``success_msg`` is a callable taking the worker result and returning
        the status-bar message to display.  ``after_success`` is an optional
        zero-argument callable that replaces the default ``_reloadCurrent()``
        call — use it when the post-mutation action differs (e.g. refreshing
        the campaign list instead of the artefacts table).
        """
        if self._loadThread is not None:
            # Don't pile mutations on top of a load.
            self._setStatus("Busy — try again in a moment.")
            return

        self._setStatus(f"{label}…")
        self._progress.setVisible(True)

        thread = QThread(self)
        worker = GenericWorker(fn, kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _on_done(result):
            # Release the active-thread slot BEFORE calling after_success so
            # the callback (e.g. _reloadCurrent) can start a new load without
            # hitting the in-flight busy guard.
            if self._loadThread is thread:
                self._loadThread = None
                self._loadWorker = None
            # Always hide progress here.  If after_success triggers a new
            # background load (e.g. _reloadCurrent) that load will re-show it.
            # If after_success is synchronous (e.g. _loadIPTSCampaigns) the
            # _cleanup guard will be False by now and would never hide it.
            self._progress.setVisible(False)
            self._setStatus(success_msg(result))
            if after_success is not None:
                after_success()
            else:
                self._reloadCurrent()

        def _on_err(message):
            if self._loadThread is thread:
                self._loadThread = None
                self._loadWorker = None
                self._progress.setVisible(False)
            QMessageBox.warning(self, "Action failed", message)
            self._setStatus(f"Failed: {message}")

        def _cleanup():
            # thread.finished fires after thread.quit() is processed; by then
            # after_success may have handed _loadThread to a new worker.
            # Only clear and hide progress if this thread is still the active one.
            if self._loadThread is thread:
                self._loadThread = None
                self._loadWorker = None
                self._progress.setVisible(False)

        worker.finished.connect(_on_done)
        worker.error.connect(_on_err)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_cleanup)
        thread.start()
        self._loadThread = thread
        self._loadWorker = worker
