"""Main window for the SNAP Calibration Manager.

Assembles :class:`StateOverviewPanel` (top) and
:class:`CalibrationDetailPanel` (bottom) inside a vertical splitter, wires
signals to the :class:`CalibrationManagerModel`, and handles threaded data
loading so the UI stays responsive while scanning 50+ states.
"""

from __future__ import annotations

from typing import Optional

from qtpy.QtCore import QObject, QThread, Qt, Signal  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QDialog,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
)

from snapwrap.calibrationManager.calibrationDetailPanel import CalibrationDetailPanel
from snapwrap.calibrationManager.constants import CalStatus
from snapwrap.calibrationManager.model import CalibrationManagerModel
from snapwrap.calibrationManager.stateOverviewPanel import StateOverviewPanel


# ═══════════════════════════════════════════════════════════════════════
# Background worker for data loading
# ═══════════════════════════════════════════════════════════════════════

class _LoadWorker(QObject):
    """Runs :meth:`CalibrationManagerModel.getAllStates` on a background thread."""

    finished = Signal(list)  # list of state-summary dicts
    error = Signal(str)

    def __init__(self, model: CalibrationManagerModel, isLite: bool = True):
        super().__init__()
        self._model = model
        self._isLite = isLite

    def run(self) -> None:
        try:
            rows = self._model.getAllStates(isLite=self._isLite)
            self.finished.emit(rows)
        except Exception as exc:
            self.error.emit(str(exc))


# ═══════════════════════════════════════════════════════════════════════
# Main window
# ═══════════════════════════════════════════════════════════════════════

class CalibrationManager(QDialog):
    """Top-level Calibration Manager dialog.

    Launch from Mantid Workbench via::

        from snapwrap.calibrationManager import show
        show()
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SNAP Calibration Manager")
        self.setMinimumSize(1100, 700)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)

        self._model = CalibrationManagerModel()
        self._isLite = True
        self._thread: Optional[QThread] = None

        # ── layout ────────────────────────────────────────────────
        outerLayout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Vertical)

        self._topPanel = StateOverviewPanel()
        self._bottomPanel = CalibrationDetailPanel()

        splitter.addWidget(self._topPanel)
        splitter.addWidget(self._bottomPanel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        outerLayout.addWidget(splitter)

        # ── progress / status ─────────────────────────────────────
        self._progressBar = QProgressBar()
        self._progressBar.setRange(0, 0)  # indeterminate
        self._progressBar.setVisible(False)
        outerLayout.addWidget(self._progressBar)

        self._statusBar = QStatusBar()
        outerLayout.addWidget(self._statusBar)

        # ── signal wiring ─────────────────────────────────────────
        self._topPanel.stateSelected.connect(self._onStateSelected)
        self._topPanel.repairRequested.connect(self._onRepairRequested)
        self._topPanel.refreshBtn.clicked.connect(self._refresh)
        self._bottomPanel.deleteVersionRequested.connect(self._onDeleteVersion)

        # ── populate cycles ───────────────────────────────────────
        try:
            cycles = self._model.getCycleList()
            self._topPanel.setCycles(cycles)
        except Exception as exc:
            self._statusBar.showMessage(f"Failed to load cycle list: {exc}")

    # ── public ────────────────────────────────────────────────────

    def loadData(self) -> None:
        """Kick off background loading of all state data."""
        if self._thread is not None and self._thread.isRunning():
            return  # already loading

        self._progressBar.setVisible(True)
        self._statusBar.showMessage("Loading calibration states…")

        self._thread = QThread()
        self._worker = _LoadWorker(self._model, self._isLite)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._onLoadFinished)
        self._worker.error.connect(self._onLoadError)
        # Ensure thread cleans up
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    # ── slots ─────────────────────────────────────────────────────

    def _onLoadFinished(self, rows: list) -> None:
        self._topPanel.setData(rows)
        self._progressBar.setVisible(False)
        self._statusBar.showMessage(f"Loaded {len(rows)} states.", 5000)

    def _onLoadError(self, msg: str) -> None:
        self._progressBar.setVisible(False)
        self._statusBar.showMessage(f"Error: {msg}")

    def _onStateSelected(self, stateID: str) -> None:
        """Load calibration details for the selected state."""
        try:
            difEntries = self._model.getCalibrationDetails(
                stateID, calType="difcal", isLite=self._isLite,
            )
            nrmEntries = self._model.getCalibrationDetails(
                stateID, calType="normcal", isLite=self._isLite,
            )
            summary = self._model.getStateSummary(stateID, isLite=self._isLite)
            self._bottomPanel.showState(
                stateID=stateID,
                description=summary["description"],
                status=summary["status"],
                difcalEntries=difEntries,
                normcalEntries=nrmEntries,
                nDifcal=summary["nDifcal"],
                nNormcal=summary["nNormcal"],
            )
        except Exception as exc:
            self._statusBar.showMessage(f"Error loading details for {stateID}: {exc}")

    def _onRepairRequested(self, stateID: str) -> None:
        """Run fixIndex (dry-run first) for a corrupt state."""
        # Dry run first
        try:
            dryReport = self._model.repairState(
                stateID, calType="difcal", isLite=self._isLite, dryRun=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Repair", f"Dry-run failed: {exc}")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Repair",
            f"Repair state {stateID}?\n\n"
            f"fixIndex dry-run report:\n"
            f"  ok = {dryReport.get('ok')}\n"
            f"  issues = {len(dryReport.get('issues', []))}\n\n"
            "Proceed with actual repair?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self._model.repairState(
                stateID, calType="difcal", isLite=self._isLite, dryRun=False,
            )
            # Refresh just this row
            updated = self._model.getStateSummary(stateID, isLite=self._isLite)
            self._topPanel.updateRow(stateID, updated)
            self._statusBar.showMessage(f"Repaired {stateID}.", 5000)
        except Exception as exc:
            QMessageBox.warning(self, "Repair", f"Repair failed: {exc}")

    def _onDeleteVersion(self, stateID: str, calType: str, version: int) -> None:
        """Handle a version-deletion request from the detail panel."""
        # Dry run
        try:
            result = self._model.deleteCalibrationVersion(
                stateID, calType, version, isLite=self._isLite, dryRun=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Delete Version", f"Pre-check failed: {exc}")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"{result.get('message', '')}\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._model.deleteCalibrationVersion(
                stateID, calType, version, isLite=self._isLite, dryRun=False,
            )
            if result["ok"]:
                self._statusBar.showMessage(result["message"], 5000)
                # Refresh both panels
                self._onStateSelected(stateID)
                updated = self._model.getStateSummary(stateID, isLite=self._isLite)
                self._topPanel.updateRow(stateID, updated)
            else:
                QMessageBox.warning(self, "Delete Version", result["message"])
        except Exception as exc:
            QMessageBox.warning(self, "Delete Version", f"Delete failed: {exc}")

    def _refresh(self) -> None:
        """Full refresh triggered by the Refresh button."""
        self._bottomPanel.clear()
        self.loadData()
