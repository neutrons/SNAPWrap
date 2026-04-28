"""Main window for the SNAP Calibration Manager.

Assembles :class:`StateOverviewPanel` (top) and
:class:`CalibrationDetailPanel` (bottom) inside a vertical splitter, wires
signals to the :class:`CalibrationManagerModel`, and handles threaded data
loading so the UI stays responsive while scanning 50+ states.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from qtpy.QtCore import QObject, QThread, Qt, Signal  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QHBoxLayout,
    QDialog,
    QLineEdit,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
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


class _PropagationDialog(QDialog):
    """Small modal dialog for previewing/executing propagation from UI."""

    def __init__(self, model: CalibrationManagerModel, isLite: bool, parent=None):
        super().__init__(parent)
        self._model = model
        self._isLite = isLite
        self._lastPreview = None
        self.didExecute = False

        self.setWindowTitle("Propagate difcal")
        self.setMinimumSize(820, 620)

        layout = QVBoxLayout(self)

        donorRow = QHBoxLayout()
        donorRow.addWidget(QLabel("Donor run:"))
        self._donorRunEdit = QLineEdit()
        self._donorRunEdit.setPlaceholderText("e.g. 68926")
        donorRow.addWidget(self._donorRunEdit)

        self._previewBtn = QPushButton("Preview")
        self._previewBtn.clicked.connect(self._onPreview)
        donorRow.addWidget(self._previewBtn)
        layout.addLayout(donorRow)

        self._previewText = QTextEdit()
        self._previewText.setReadOnly(True)
        self._previewText.setPlaceholderText("Preview details will appear here.")
        layout.addWidget(self._previewText)

        logHeader = QHBoxLayout()
        logHeader.addWidget(QLabel("Recent propagation log entries"))
        logHeader.addStretch()
        self._refreshLogBtn = QPushButton("Refresh log")
        self._refreshLogBtn.clicked.connect(self._refreshLogView)
        logHeader.addWidget(self._refreshLogBtn)
        layout.addLayout(logHeader)

        self._logText = QTextEdit()
        self._logText.setReadOnly(True)
        self._logText.setPlaceholderText("No propagation log entries found yet.")
        layout.addWidget(self._logText)

        actionRow = QHBoxLayout()
        actionRow.addStretch()
        self._executeBtn = QPushButton("Confirm Propagation")
        self._executeBtn.setEnabled(False)
        self._executeBtn.clicked.connect(self._onExecute)
        actionRow.addWidget(self._executeBtn)

        self._closeBtn = QPushButton("Close")
        self._closeBtn.clicked.connect(self.reject)
        actionRow.addWidget(self._closeBtn)
        layout.addLayout(actionRow)

        self._refreshLogView()

    @staticmethod
    def _propagation_log_path() -> str:
        import snapwrap.snapStateMgr as ssm

        calibrationHome = ssm.SNAPHome().calib
        return os.path.join(calibrationHome, ".logs", "propagation_log.jsonl")

    @staticmethod
    def _format_log_entry(entry: dict) -> str:
        ts = entry.get("timestamp", "?")
        user = entry.get("linux_user", "?")
        outcome = entry.get("outcome", "?")
        donor = entry.get("donorRunNumber", "?")
        dstate = entry.get("donorStateID", "?")
        dver = entry.get("donorVersion", "?")
        rstate = entry.get("recipientStateID", "-")
        newv = entry.get("newVersion", "-")
        err = entry.get("error")
        line = (
            f"{ts} | user={user} | outcome={outcome} | "
            f"donorRun={donor} state={dstate} v={dver} | "
            f"recipient={rstate} newVersion={newv}"
        )
        if err:
            line += f" | error={err}"
        return line

    def _refreshLogView(self) -> None:
        logPath = self._propagation_log_path()
        if not os.path.exists(logPath):
            self._logText.setPlainText(
                f"Log file not found yet:\n{logPath}\n\n"
                "It will be created after the first propagation attempt."
            )
            return

        try:
            with open(logPath, "r", encoding="utf-8") as fh:
                lines = [line.strip() for line in fh.readlines() if line.strip()]
        except Exception as exc:
            self._logText.setPlainText(f"Failed to read log file:\n{logPath}\n\n{exc}")
            return

        if not lines:
            self._logText.setPlainText(f"Log file is empty:\n{logPath}")
            return

        parsed = []
        for line in lines[-50:]:  # keep view lightweight
            try:
                parsed.append(json.loads(line))
            except Exception:
                parsed.append({
                    "timestamp": "?",
                    "outcome": "parse_error",
                    "error": f"malformed JSONL line: {line[:180]}",
                })

        parsed.reverse()  # newest first
        display = [self._format_log_entry(entry) for entry in parsed]
        self._logText.setPlainText("\n".join(display))

    @staticmethod
    def _formatPreview(preview: dict) -> str:
        lines = [
            f"donorRunNumber: {preview.get('donorRunNumber')}",
            f"donorStateID: {preview.get('donorStateID')}",
            f"selectedDonorVersion: {preview.get('selectedDonorVersion')}",
            f"selectedDonorCycleID: {preview.get('selectedDonorCycleID')}",
            f"blocked: {preview.get('blocked')}",
            f"blockReason: {preview.get('blockReason')}",
            "",
            "Recipients:",
        ]
        recipients = preview.get("recipients", [])
        if not recipients:
            lines.append("  (none)")
        else:
            for r in recipients:
                lines.append(
                    f"  - {r.get('stateID')} "
                    f"(current={r.get('recipientPreviousVersions')}, newVersion={r.get('newVersion')})"
                )
        return "\n".join(lines)

    def _onPreview(self) -> None:
        donorRun = self._donorRunEdit.text().strip()
        if not donorRun:
            QMessageBox.information(self, "Preview", "Please enter a donor run number.")
            return
        try:
            preview = self._model.previewPropagation(donorRun, isLite=self._isLite)
            self._lastPreview = preview
            self._previewText.setPlainText(self._formatPreview(preview))
            self._executeBtn.setEnabled(bool(preview.get("ok")) and not bool(preview.get("blocked")))
            self._refreshLogView()
        except Exception as exc:
            self._executeBtn.setEnabled(False)
            QMessageBox.warning(self, "Preview", f"Preview failed: {exc}")

    def _onExecute(self) -> None:
        donorRun = self._donorRunEdit.text().strip()
        if not donorRun:
            return
        if self._lastPreview is None:
            QMessageBox.information(self, "Propagate", "Run Preview before executing.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Propagation",
            f"Execute propagation from donor run {donorRun} to "
            f"{len(self._lastPreview.get('recipients', []))} recipient state(s)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            result = self._model.executePropagation(donorRun, isLite=self._isLite)
            self._previewText.setPlainText(
                self._formatPreview(result) + "\n\nSummary:\n" + result.get("summary", "")
            )
            self._refreshLogView()
            if result.get("ok") and result.get("executed"):
                self.didExecute = True
                QMessageBox.information(self, "Propagation", result.get("summary", "Propagation completed."))
            else:
                QMessageBox.warning(self, "Propagation", result.get("summary", "Propagation was blocked."))
        except Exception as exc:
            QMessageBox.warning(self, "Propagation", f"Propagation failed: {exc}")


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

        actionBar = QHBoxLayout()
        actionBar.addStretch()
        self._propagateBtn = QPushButton("Propagate…")
        self._propagateBtn.setToolTip("Preview and execute difcal propagation")
        self._propagateBtn.clicked.connect(self._onPropagateRequested)
        actionBar.addWidget(self._propagateBtn)
        outerLayout.addLayout(actionBar)

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

    def _onPropagateRequested(self) -> None:
        """Open the propagation dialog and refresh on successful execution."""
        dlg = _PropagationDialog(self._model, self._isLite, self)
        if self._runNumber:
            dlg._donorRunEdit.setText(str(self._runNumber))
        dlg.exec_()
        if dlg.didExecute:
            self._refresh()
            self._statusBar.showMessage("Propagation complete; views refreshed.", 5000)
