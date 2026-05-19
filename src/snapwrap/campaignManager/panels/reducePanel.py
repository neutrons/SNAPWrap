"""Reduce panel for the Campaign Manager.

Lets the operator select a run number, configure ``reduceSEE`` options, and
trigger reduction.  Log output is streamed live into an embedded
``QPlainTextEdit`` via a :class:`~snapwrap.campaignManager.logHandler.QtLogHandler`
attached to the ``snapwrap`` logger for the duration of the run.
"""

from __future__ import annotations

import logging
from typing import Any

from qtpy.QtCore import QThread, Qt, Signal  # type: ignore
from qtpy.QtGui import QFont  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snapwrap.campaignManager.logHandler import QtLogHandler
from snapwrap.campaignManager.workers import GenericWorker

_SNAPWRAP_LOGGER = "snapwrap"


class ReducePanel(QWidget):
    """Panel for triggering ``reduceSEE`` on a specific run.

    The panel owns its own worker thread and log handler.  The host
    (``CampaignManager``) supplies the IPTS / campaign context via
    :meth:`setContext` whenever the campaign combo changes.

    Signals
    -------
    reduceFinished()
        Emitted (from the GUI thread) once a reduction completes
        successfully — the host can use this to refresh the Runs panel.
    """

    reduceFinished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ipts: int | None = None
        self._campaignSlug: str | None = None
        self._reduceThread: QThread | None = None
        self._reduceWorker: GenericWorker | None = None
        self._logHandler: QtLogHandler | None = None

        layout = QVBoxLayout(self)

        # ── Context label ─────────────────────────────────────────────
        self._ctxLabel = QLabel("No campaign selected.")
        self._ctxLabel.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self._ctxLabel)

        # ── Run-number + option form ───────────────────────────────────
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._runEdit = QLineEdit()
        self._runEdit.setPlaceholderText("e.g. 65891 — or click a row in the Runs tab")
        self._runEdit.setMaximumWidth(260)
        form.addRow("Run number:", self._runEdit)

        # Option checkboxes on one row
        opts = QWidget()
        opts_layout = QHBoxLayout(opts)
        opts_layout.setContentsMargins(0, 0, 0, 0)
        self._verboseCheck = QCheckBox("verbose")
        self._keepUnfocussedCheck = QCheckBox("keepUnfocussed")
        self._continueNoDifcalCheck = QCheckBox("continueNoDifcal")
        self._continueNoVanCheck = QCheckBox("continueNoVan")
        self._rebuildCheck = QCheckBox("rebuild manifest")
        for cb in (
            self._verboseCheck,
            self._keepUnfocussedCheck,
            self._continueNoDifcalCheck,
            self._continueNoVanCheck,
            self._rebuildCheck,
        ):
            opts_layout.addWidget(cb)
        opts_layout.addStretch(1)
        form.addRow("Options:", opts)

        layout.addLayout(form)

        # ── Action buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._reduceBtn = QPushButton("Reduce")
        self._reduceBtn.clicked.connect(self._onReduce)
        btn_row.addWidget(self._reduceBtn)
        btn_row.addStretch(1)
        self._clearBtn = QPushButton("Clear log")
        self._clearBtn.clicked.connect(self._logEdit_clear)
        btn_row.addWidget(self._clearBtn)
        layout.addLayout(btn_row)

        # ── Live log pane ──────────────────────────────────────────────
        self._logEdit = QPlainTextEdit()
        self._logEdit.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self._logEdit.setFont(mono)
        self._logEdit.setMaximumBlockCount(5000)  # keep last 5000 lines
        layout.addWidget(self._logEdit, stretch=1)

    # ── Public API ─────────────────────────────────────────────────────

    def setContext(self, ipts: int | None, campaign_slug: str | None) -> None:
        """Update the IPTS / campaign context used when Reduce is clicked."""
        self._ipts = ipts
        self._campaignSlug = campaign_slug
        if ipts is not None and campaign_slug:
            self._ctxLabel.setText(f"IPTS-{ipts} / {campaign_slug}")
        else:
            self._ctxLabel.setText("No campaign selected.")

    def setRunNumber(self, run_number: int) -> None:
        """Pre-fill the run number field (called from the Runs panel)."""
        self._runEdit.setText(str(run_number))

    # ── Internal ───────────────────────────────────────────────────────

    def _logEdit_clear(self) -> None:
        self._logEdit.clear()

    def _appendLog(self, text: str) -> None:
        self._logEdit.appendPlainText(text)
        # Scroll to bottom
        sb = self._logEdit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _parseRunNumber(self) -> int | None:
        text = self._runEdit.text().strip()
        try:
            n = int(text)
            return n if n > 0 else None
        except ValueError:
            return None

    def _onReduce(self) -> None:
        if self._reduceThread is not None:
            QMessageBox.information(
                self, "Reduction in progress", "A reduction is already running."
            )
            return

        if self._ipts is None or not self._campaignSlug:
            QMessageBox.warning(
                self, "No campaign", "Select an IPTS and campaign first."
            )
            return

        run_number = self._parseRunNumber()
        if run_number is None:
            QMessageBox.warning(
                self, "Invalid run number", "Enter a positive integer run number."
            )
            return

        kwargs: dict[str, Any] = {
            "run_number": run_number,
            "ipts": self._ipts,
            "campaign": self._campaignSlug,
            "verbose": self._verboseCheck.isChecked(),
            "keepUnfocussed": self._keepUnfocussedCheck.isChecked(),
            "continueNoDifcal": self._continueNoDifcalCheck.isChecked(),
            "continueNoVan": self._continueNoVanCheck.isChecked(),
            "rebuild_manifest": self._rebuildCheck.isChecked(),
        }

        self._appendLog(
            f"── Starting reduction: run {run_number}  "
            f"IPTS-{self._ipts} / {self._campaignSlug} ──"
        )
        self._logActiveArtefacts(run_number)
        self._reduceBtn.setEnabled(False)
        self._installLogHandler()

        from snapwrap.reduction_artefacts import reduceSEE

        thread = QThread(self)
        worker = GenericWorker(reduceSEE, kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._onReduceFinished)
        worker.error.connect(self._onReduceError)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._onReduceCleanup)
        thread.start()
        self._reduceThread = thread
        self._reduceWorker = worker

    def _logActiveArtefacts(self, run_number: int) -> None:
        """Log the active artefacts that will be used for this run."""
        try:
            from snapwrap.reduction_artefacts import list_artefact_records

            records = list_artefact_records(
                ipts=self._ipts,
                campaign_identifier=self._campaignSlug,
                run_number=run_number,
                status="active",
            )
        except Exception as exc:
            self._appendLog(f"  (could not list artefacts: {exc})")
            return

        if not records:
            self._appendLog(f"  No active artefacts registered for run {run_number}.")
            return

        self._appendLog(f"  Active artefacts for run {run_number}:")
        for rec in records:
            atype = rec.get("artefact_type", "unknown")
            aid = rec.get("artefact_id", "—")
            self._appendLog(f"    [{atype}]  {aid}")

    def _installLogHandler(self) -> None:
        handler = QtLogHandler()
        handler.logLine.connect(self._appendLog)
        logging.getLogger(_SNAPWRAP_LOGGER).addHandler(handler)
        self._logHandler = handler

    def _uninstallLogHandler(self) -> None:
        if self._logHandler is not None:
            logging.getLogger(_SNAPWRAP_LOGGER).removeHandler(self._logHandler)
            self._logHandler = None

    def _onReduceFinished(self, _result: Any) -> None:
        self._appendLog("── Reduction complete. ──")
        self.reduceFinished.emit()

    def _onReduceError(self, message: str) -> None:
        self._appendLog(f"── ERROR: {message} ──")
        QMessageBox.warning(self, "Reduction failed", message)

    def _onReduceCleanup(self) -> None:
        self._uninstallLogHandler()
        self._reduceThread = None
        self._reduceWorker = None
        self._reduceBtn.setEnabled(True)
