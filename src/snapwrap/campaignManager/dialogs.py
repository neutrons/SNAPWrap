"""Modal dialogs for mutating artefacts in the Campaign Manager."""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import Qt  # type: ignore
from qtpy.QtWidgets import (  # type: ignore
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)


class CopyArtefactDialog(QDialog):
    """Prompt the operator for parameters to :func:`copy_artefact`.

    The source record is displayed read-only at the top so the operator
    can see what they're about to copy.  All editable fields map directly
    to ``copy_artefact`` kwargs.
    """

    def __init__(self, source_record: dict[str, Any], parent=None):
        super().__init__(parent)
        self._source = source_record

        self.setWindowTitle("Copy artefact")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        # ── Source summary (read-only) ────────────────────────────────
        src_id = source_record.get("artefact_id", "")
        src_type = source_record.get("artefact_type", "")
        src_run = (source_record.get("run_context") or {}).get("run_number", "")

        summary = QLabel(
            f"<b>Source:</b> {src_id}<br>"
            f"<b>Type:</b> {src_type}"
            + (f"<br><b>Run:</b> {src_run}" if src_run != "" else "")
        )
        summary.setTextFormat(Qt.RichText)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # ── Form ───────────────────────────────────────────────────────
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._newIdEdit = QLineEdit()
        self._newIdEdit.setPlaceholderText("e.g. dspacing-mask-diamond-65892")
        # Suggest an obvious default — operator can edit.
        self._newIdEdit.setText(f"{src_id}-copy")
        form.addRow("New artefact id:", self._newIdEdit)

        self._runEdit = QLineEdit()
        self._runEdit.setPlaceholderText(
            "leave blank to keep source run scope" + (f" (currently {src_run})" if src_run != "" else "")
        )
        form.addRow("Run number override:", self._runEdit)

        self._copyFileCheck = QCheckBox(
            "Physically copy the underlying file (instead of sharing the path)"
        )
        self._copyFileCheck.setToolTip(
            "By default the new record points at the same file as the source.\n"
            "Tick this if you want to edit the new mask independently."
        )
        form.addRow("", self._copyFileCheck)

        self._notesEdit = QPlainTextEdit()
        self._notesEdit.setPlaceholderText(
            "Optional notes — recorded against the new record"
        )
        self._notesEdit.setFixedHeight(70)
        form.addRow("Notes:", self._notesEdit)

        layout.addLayout(form)

        # ── Buttons ────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.button(QDialogButtonBox.Ok).setText("Copy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Public API ─────────────────────────────────────────────────────

    def newArtefactId(self) -> str:
        return self._newIdEdit.text().strip()

    def runNumberOverride(self) -> int | None:
        text = self._runEdit.text().strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def copyFile(self) -> bool:
        return self._copyFileCheck.isChecked()

    def notes(self) -> str | None:
        text = self._notesEdit.toPlainText().strip()
        return text or None
