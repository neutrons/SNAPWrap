"""Post-processing panel for the Campaign Manager.

Lets the operator apply post-processing steps (resample, crop, background
subtraction, export) to already-reduced workspaces.  Each operation is
selected via a combo box and has a dedicated parameter form in a stacked
widget below it.

Output from the underlying utilities is streamed into an embedded
``QPlainTextEdit`` via ``redirect_stdout`` (most post-processing calls use
``print`` rather than the Python logging module).
"""

from __future__ import annotations

import logging
from typing import Any

from qtpy.QtCore import QThread, Qt  # type: ignore
from qtpy.QtGui import QFont  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from snapwrap.campaignManager.logHandler import QtLogHandler
from snapwrap.campaignManager.workers import GenericWorker

_OP_RESAMPLE = 0
_SNAPWRAP_LOGGER = "snapwrap"


# ── Operation forms ────────────────────────────────────────────────────────────


class _ResampleForm(QWidget):
    """Parameter form for the Resample operation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._factorSpin = QDoubleSpinBox()
        self._factorSpin.setRange(0.1, 10.0)
        self._factorSpin.setSingleStep(0.5)
        self._factorSpin.setValue(1.0)
        self._factorSpin.setDecimals(2)
        self._factorSpin.setMaximumWidth(120)
        self._factorSpin.setToolTip(
            "Factor applied to bin widths.\n"
            "< 1  →  coarser binning (fewer bins, faster, recommended).\n"
            "> 1  →  finer binning (upsampling — lossy, use with care)."
        )
        form.addRow("Sample factor:", self._factorSpin)

        self._unitsCombo = QComboBox()
        self._unitsCombo.addItem("d-spacing  (dsp)", "dsp")
        self._unitsCombo.addItem("Time-of-flight  (tof)", "tof")
        self._unitsCombo.setMaximumWidth(240)
        form.addRow("Units:", self._unitsCombo)

        self._runEdit = QLineEdit()
        self._runEdit.setPlaceholderText("optional — leave blank to resample all runs")
        self._runEdit.setMaximumWidth(300)
        form.addRow("Run number:", self._runEdit)

    # ── Public API ─────────────────────────────────────────────────────

    def setRunNumber(self, run_number: int) -> None:
        self._runEdit.setText(str(run_number))

    def params(self) -> dict[str, Any]:
        run_text = self._runEdit.text().strip()
        try:
            run_number: int | None = int(run_text) if run_text else None
        except ValueError:
            run_number = None
        return {
            "sample_factor": self._factorSpin.value(),
            "units": self._unitsCombo.currentData(),
            "run_number": run_number,
        }

    def validate(self) -> str | None:
        run_text = self._runEdit.text().strip()
        if run_text:
            try:
                n = int(run_text)
                if n <= 0:
                    return "Run number must be a positive integer."
            except ValueError:
                return f"'{run_text}' is not a valid run number."
        return None


# ── Main panel ─────────────────────────────────────────────────────────────────


class PostProcessingPanel(QWidget):
    """Panel for post-processing reduced data.

    Operations are selected via a combo box; each has its own parameter
    form in a stacked widget.  The panel owns its own worker thread — only
    one operation runs at a time.

    The host (``CampaignManager``) supplies context via :meth:`setContext`
    and can pre-fill the run number via :meth:`setRunNumber`.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ipts: int | None = None
        self._campaignSlug: str | None = None
        self._thread: QThread | None = None
        self._worker: GenericWorker | None = None
        self._logHandler: QtLogHandler | None = None

        layout = QVBoxLayout(self)

        # ── Context label ─────────────────────────────────────────────
        self._ctxLabel = QLabel("No campaign selected.")
        self._ctxLabel.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self._ctxLabel)

        # ── Operation selector ────────────────────────────────────────
        op_row = QHBoxLayout()
        op_label = QLabel("Operation:")
        op_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._opCombo = QComboBox()
        self._opCombo.addItem("Resample", _OP_RESAMPLE)
        self._opCombo.setMaximumWidth(280)
        self._opCombo.currentIndexChanged.connect(self._onOpChanged)
        op_row.addWidget(op_label)
        op_row.addWidget(self._opCombo)
        op_row.addStretch(1)
        layout.addLayout(op_row)

        # ── Stacked parameter forms ───────────────────────────────────
        self._stack = QStackedWidget()
        self._resampleForm = _ResampleForm()
        self._stack.addWidget(self._resampleForm)  # index 0 = _OP_RESAMPLE
        layout.addWidget(self._stack)

        # ── Log pane (created before buttons so Clear can reference it) ──
        self._logEdit = QPlainTextEdit()
        self._logEdit.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self._logEdit.setFont(mono)
        self._logEdit.setMaximumBlockCount(5000)

        # ── Action buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._applyBtn = QPushButton("Apply")
        self._applyBtn.clicked.connect(self._onApply)
        btn_row.addWidget(self._applyBtn)
        btn_row.addStretch(1)
        self._clearBtn = QPushButton("Clear log")
        self._clearBtn.clicked.connect(self._logEdit.clear)
        btn_row.addWidget(self._clearBtn)
        layout.addLayout(btn_row)

        layout.addWidget(self._logEdit, stretch=1)

    # ── Public API ─────────────────────────────────────────────────────

    def setContext(self, ipts: int | None, campaign_slug: str | None) -> None:
        """Update the IPTS / campaign context."""
        self._ipts = ipts
        self._campaignSlug = campaign_slug
        if ipts is not None and campaign_slug:
            self._ctxLabel.setText(f"IPTS-{ipts} / {campaign_slug}")
        else:
            self._ctxLabel.setText("No campaign selected.")

    def setRunNumber(self, run_number: int) -> None:
        """Pre-fill the run number in the resample form (called from Runs panel)."""
        self._resampleForm.setRunNumber(run_number)

    # ── Internals ──────────────────────────────────────────────────────

    def _onOpChanged(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _onApply(self) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self, "Operation in progress", "An operation is already running."
            )
            return

        if self._ipts is None or not self._campaignSlug:
            QMessageBox.warning(self, "No campaign", "Select an IPTS and campaign first.")
            return

        op = self._opCombo.currentData()
        if op == _OP_RESAMPLE:
            self._onResample()

    def _onResample(self) -> None:
        error = self._resampleForm.validate()
        if error:
            QMessageBox.warning(self, "Invalid form", error)
            return

        params = self._resampleForm.params()
        run_desc = (
            f"run {params['run_number']}"
            if params["run_number"] is not None
            else "all runs"
        )
        self._appendLog(
            f"── Resampling {run_desc}  "
            f"(factor={params['sample_factor']:.2f}, units={params['units']})  "
            f"IPTS-{self._ipts} / {self._campaignSlug} ──"
        )

        self._applyBtn.setEnabled(False)
        self._installLogHandler()

        from snapwrap.campaignManager.model import CampaignManagerModel

        thread = QThread(self)
        worker = GenericWorker(
            CampaignManagerModel.postprocessResample,
            {
                "run_number": params["run_number"],
                "sample_factor": params["sample_factor"],
                "units": params["units"],
            },
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._onOpFinished)
        worker.error.connect(self._onOpError)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._onOpCleanup)
        thread.start()
        self._thread = thread
        self._worker = worker

    def _appendLog(self, text: str) -> None:
        self._logEdit.appendPlainText(text)
        sb = self._logEdit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _installLogHandler(self) -> None:
        handler = QtLogHandler()
        handler.logLine.connect(self._appendLog)
        logging.getLogger(_SNAPWRAP_LOGGER).addHandler(handler)
        self._logHandler = handler

    def _uninstallLogHandler(self) -> None:
        if self._logHandler is not None:
            logging.getLogger(_SNAPWRAP_LOGGER).removeHandler(self._logHandler)
            self._logHandler = None

    def _onOpFinished(self, result: Any) -> None:
        if isinstance(result, str) and result.strip():
            self._appendLog(result)
        self._appendLog("── Operation complete. ──")

    def _onOpError(self, message: str) -> None:
        self._appendLog(f"── ERROR: {message} ──")
        QMessageBox.warning(self, "Operation failed", message)

    def _onOpCleanup(self) -> None:
        self._uninstallLogHandler()
        self._thread = None
        self._worker = None
        self._applyBtn.setEnabled(True)
