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
    QLabel,
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
    """Runs model queries on a background thread.

    When *stateID* is provided the worker fetches a single state summary
    (run-number mode).  Otherwise it calls ``getAllStates`` to scan every
    known state.
    """

    finished = Signal(list)  # list of state-summary dicts
    error = Signal(str)

    def __init__(
        self,
        model: CalibrationManagerModel,
        isLite: bool = True,
        runNumber=None,
        cycleID: Optional[str] = None,
        stateID: Optional[str] = None,
    ):
        super().__init__()
        self._model = model
        self._isLite = isLite
        self._runNumber = runNumber
        self._cycleID = cycleID
        self._stateID = stateID

    def run(self) -> None:
        try:
            if self._stateID:
                # Single-state fetch (run-number mode)
                row = self._model.getStateSummary(
                    self._stateID,
                    isLite=self._isLite,
                    runNumber=self._runNumber,
                    cycleID=self._cycleID,
                )
                self.finished.emit([row])
            else:
                rows = self._model.getAllStates(
                    isLite=self._isLite,
                    runNumber=self._runNumber,
                    cycleID=self._cycleID,
                )
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
        self._runNumber = None  # current context run number (None = Mode A)
        self._cycleID: Optional[str] = None  # current context cycle (None = Mode A)
        self._stateID: Optional[str] = None  # single-state filter (run mode)
        self._thread: Optional[QThread] = None

        # ── layout ────────────────────────────────────────────────
        outerLayout = QVBoxLayout(self)

        # ── calibration home path indicator ───────────────────────
        import snapwrap.snapStateMgr as ssm

        home = ssm.SNAPHome()
        self._homeLabel = QLabel(f"Calibration home: {home.calib}")
        self._homeLabel.setStyleSheet(
            "color: #666; font-size: 11px; padding: 2px 4px;"
        )
        self._homeLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outerLayout.addWidget(self._homeLabel)

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
        self._topPanel.deleteStateRequested.connect(self._onDeleteStateRequested)
        self._topPanel.refreshBtn.clicked.connect(self._refresh)
        self._topPanel.contextChanged.connect(self._onContextChanged)
        self._bottomPanel.deleteVersionRequested.connect(self._onDeleteVersion)

        # ── populate cycles ───────────────────────────────────────
        try:
            cycles = self._model.getCycleList()
            self._topPanel.setCycles(cycles)
        except Exception as exc:
            self._statusBar.showMessage(f"Failed to load cycle list: {exc}")

    # ── public ────────────────────────────────────────────────────

    def loadData(
        self,
        runNumber=None,
        cycleID: Optional[str] = None,
        stateID: Optional[str] = None,
    ) -> None:
        """Kick off background loading of state data.

        Parameters
        ----------
        runNumber : int or str, optional
            If provided together with *stateID*, the model evaluates
            validity scoped to this run for a single state.
        cycleID : str, optional
            If provided (and *runNumber* is ``None``), the model checks
            whether each state has a calibration *from* this cycle
            (Mode B — cycle).  If both are ``None``, existence-only
            classification is used (Mode A).
        stateID : str, optional
            If provided, load only this single state (run-number mode).
            Otherwise all states are scanned.
        """
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    return  # already loading
            except RuntimeError:
                # C++ object already deleted — safe to proceed
                self._thread = None

        self._runNumber = runNumber
        self._cycleID = cycleID
        self._stateID = stateID
        self._progressBar.setVisible(True)
        self._statusBar.showMessage("Loading calibration states…")

        self._thread = QThread()
        self._worker = _LoadWorker(
            self._model, self._isLite,
            runNumber=runNumber, cycleID=cycleID, stateID=stateID,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._onLoadFinished)
        self._worker.error.connect(self._onLoadError)
        # Ensure thread cleans up
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._onThreadFinished)

        self._thread.start()

    # ── slots ─────────────────────────────────────────────────────

    def _onThreadFinished(self) -> None:
        """Clean up the thread reference so the next loadData() can proceed."""
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None

    def _onLoadFinished(self, rows: list) -> None:
        self._topPanel.setData(rows)
        self._progressBar.setVisible(False)
        n = len(rows)
        if self._runNumber and self._stateID:
            self._statusBar.showMessage(
                f"Showing state {self._stateID} for run {self._runNumber}.", 5000,
            )
        elif self._cycleID:
            self._statusBar.showMessage(
                f"Loaded {n} states (context: cycle {self._cycleID}).", 5000,
            )
        else:
            self._statusBar.showMessage(f"Loaded {n} states.", 5000)

    def _onLoadError(self, msg: str) -> None:
        self._progressBar.setVisible(False)
        self._statusBar.showMessage(f"Error: {msg}")

    def _onContextChanged(self, runNumber: str) -> None:
        """Handle a context change from the top panel.

        If ``runNumber`` is non-empty, resolve its cycle and state,
        update the context bar, and reload showing **only** the single
        matching state (Mode B — run).

        If ``runNumber`` is empty, check whether a cycle is selected
        in the combo.  If so, reload all states with Mode B (cycle).
        Otherwise return to Mode A.
        """
        if runNumber:
            # Mode B — run number provided → show single state only
            try:
                cycleID = self._model.cycleForRun(runNumber) or ""
            except Exception:
                cycleID = ""
            try:
                stateInfo = self._model.stateForRun(runNumber)
                stateID = stateInfo.get("stateID", "")
            except Exception:
                stateID = ""

            if not stateID:
                self._statusBar.showMessage(
                    f"Could not resolve a state for run {runNumber}.", 5000,
                )
                return

            # Sync the cycle combo to match
            if cycleID:
                self._topPanel.cycleCombo.blockSignals(True)
                idx = self._topPanel.cycleCombo.findText(cycleID)
                if idx >= 0:
                    self._topPanel.cycleCombo.setCurrentIndex(idx)
                self._topPanel.cycleCombo.blockSignals(False)

            self._topPanel.setContextInfo(
                runNumber=runNumber, cycleID=cycleID, stateID=stateID,
            )
            self.loadData(runNumber=runNumber, stateID=stateID)
        else:
            cycle = self._topPanel.currentCycle()
            if cycle:
                # Mode B — cycle selected (no specific run)
                self._topPanel.setContextInfo(cycleID=cycle)
                self.loadData(cycleID=cycle)
            else:
                # Mode A — no context
                self._topPanel.setContextInfo()
                self.loadData()

    def _onStateSelected(self, stateID: str) -> None:
        """Load calibration details for the selected state."""
        try:
            difEntries = self._model.getCalibrationDetails(
                stateID, calType="difcal", isLite=self._isLite,
            )
            nrmEntries = self._model.getCalibrationDetails(
                stateID, calType="normcal", isLite=self._isLite,
            )
            summary = self._model.getStateSummary(
                stateID, isLite=self._isLite,
                runNumber=self._runNumber, cycleID=self._cycleID,
            )
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
            updated = self._model.getStateSummary(
                stateID, isLite=self._isLite,
                runNumber=self._runNumber, cycleID=self._cycleID,
            )
            self._topPanel.updateRow(stateID, updated)
            self._statusBar.showMessage(f"Repaired {stateID}.", 5000)
        except Exception as exc:
            QMessageBox.warning(self, "Repair", f"Repair failed: {exc}")

    def _onDeleteStateRequested(self, stateID: str) -> None:
        """Handle deletion of an unrepairable (cross-state contaminated) state."""
        # Dry run first
        try:
            result = self._model.deleteStateFolder(stateID, dryRun=True)
        except Exception as exc:
            QMessageBox.warning(self, "Delete State", f"Pre-check failed: {exc}")
            return

        if not result["ok"]:
            QMessageBox.warning(self, "Delete State", result["message"])
            return

        reply = QMessageBox.warning(
            self,
            "Confirm Delete State",
            f"This state has cross-state contamination and cannot be repaired.\n\n"
            f"{result['message']}\n\n"
            f"The entire folder will be backed up before deletion.\n"
            f"Proceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._model.deleteStateFolder(stateID, dryRun=False)
            if result["ok"]:
                self._statusBar.showMessage(result["message"], 8000)
                self._bottomPanel.clear()
                self._refresh()
            else:
                QMessageBox.warning(self, "Delete State", result["message"])
        except Exception as exc:
            QMessageBox.warning(self, "Delete State", f"Deletion failed: {exc}")

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
                updated = self._model.getStateSummary(
                    stateID, isLite=self._isLite,
                    runNumber=self._runNumber, cycleID=self._cycleID,
                )
                self._topPanel.updateRow(stateID, updated)
            else:
                QMessageBox.warning(self, "Delete Version", result["message"])
        except Exception as exc:
            QMessageBox.warning(self, "Delete Version", f"Delete failed: {exc}")

    def _refresh(self) -> None:
        """Full refresh triggered by the Refresh button.

        Preserves the current context (Mode A or B).
        """
        self._bottomPanel.clear()
        self.loadData(
            runNumber=self._runNumber,
            cycleID=self._cycleID,
            stateID=self._stateID,
        )
