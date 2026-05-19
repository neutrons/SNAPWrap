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
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from snapwrap.campaignManager.model import CampaignManagerModel
from snapwrap.campaignManager.panels.artefactsPanel import ArtefactsPanel
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
        self._iptsCombo = QComboBox()
        self._iptsCombo.setMinimumWidth(140)
        self._iptsCombo.currentTextChanged.connect(self._onIPTSChanged)
        ctx.addWidget(self._iptsCombo)

        ctx.addSpacing(12)
        ctx.addWidget(QLabel("Campaign:"))
        self._campaignCombo = QComboBox()
        self._campaignCombo.setMinimumWidth(220)
        self._campaignCombo.currentTextChanged.connect(self._onCampaignChanged)
        ctx.addWidget(self._campaignCombo)

        ctx.addStretch(1)

        self._reloadBtn = QPushButton("Reload")
        self._reloadBtn.clicked.connect(self._reloadCurrent)
        ctx.addWidget(self._reloadBtn)

        layout.addLayout(ctx)

        # Tabs.
        self._tabs = QTabWidget(self)
        self._artefactsPanel = ArtefactsPanel(self)
        self._artefactsPanel.refreshRequested.connect(self._reloadCurrent)
        self._tabs.addTab(self._artefactsPanel, "Artefacts")
        self._tabs.addTab(_placeholderTab("Runs"), "Runs")
        self._tabs.addTab(_placeholderTab("Reduce"), "Reduce")
        self._tabs.addTab(_placeholderTab("Setup"), "Setup")
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
        self._iptsCombo.blockSignals(True)
        self._iptsCombo.clear()
        self._iptsCombo.addItem(self._IPTS_PLACEHOLDER)
        try:
            ipts_list = self._model.discoverIPTSList()
        except Exception as exc:  # pragma: no cover - filesystem-dependent
            QMessageBox.warning(
                self, "IPTS discovery failed", f"{type(exc).__name__}: {exc}"
            )
            ipts_list = []
        for ipts in ipts_list:
            self._iptsCombo.addItem(f"IPTS-{ipts}", userData=ipts)
        self._iptsCombo.blockSignals(False)
        self._setStatus(f"Discovered {len(ipts_list)} IPTS folder(s).")

    def _currentIPTS(self) -> int | None:
        data = self._iptsCombo.currentData()
        return int(data) if data is not None else None

    def _currentCampaign(self) -> str | None:
        text = self._campaignCombo.currentText()
        if not text or text == self._CAMPAIGN_PLACEHOLDER:
            return None
        return text

    def _onIPTSChanged(self, _text: str) -> None:
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

    def _onCampaignChanged(self, _text: str) -> None:
        if self._currentIPTS() is None or self._currentCampaign() is None:
            return
        self._reloadCurrent()

    # ── Data loading (background) ────────────────────────────────────

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
