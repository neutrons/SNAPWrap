"""Modal dialogs for mutating artefacts in the Campaign Manager.

NOTE (revisit): the artefact-id scheme is currently doing double duty —
it encodes both *what the artefact is* and *which run it's scoped to*
(e.g. ``dspacing-mask-diamond-65891``).  That's why the Copy dialog has
to guess-rewrite the trailing run number.  Worth revisiting after Phase
3: either switch to simple numeric ids + a human-readable ``description``
attribute, or formalise the ``<kind>-<run>`` convention so the UI can
manipulate it safely.  Tracked in docs (to be added).
"""

from __future__ import annotations

import re
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


def _suggest_new_id(src_id: str, src_run: Any, new_run: Any) -> str:
    """Rewrite the trailing ``-{src_run}`` in *src_id* to ``-{new_run}``.

    Falls back to ``{src_id}-copy`` when the id doesn't end with the
    source run number (or either run is blank / non-integer-looking).
    """
    if not src_id:
        return ""
    # The new run must parse — without it we can't suggest anything useful.
    try:
        new_run_int = int(new_run)
    except (TypeError, ValueError):
        return f"{src_id}-copy"

    # If the source run parses, try the swap-trailing-run case first.
    try:
        src_run_int = int(src_run)
        suffix = f"-{src_run_int}"
        if src_id.endswith(suffix):
            return f"{src_id[: -len(suffix)]}-{new_run_int}"
    except (TypeError, ValueError):
        src_run_int = None  # noqa: F841 — fall through to append-or-copy

    # Source run unknown or didn't match a trailing -{run}.
    if re.search(r"-\d+$", src_id):
        # Has *some* trailing number we don't recognise — play it safe.
        return f"{src_id}-copy"
    return f"{src_id}-{new_run_int}"


class CopyArtefactDialog(QDialog):
    """Prompt the operator for parameters to :func:`copy_artefact`.

    Framed around the dominant workflow: *reuse an existing artefact
    (typically a mask) on a different run*.  The "for run number" field
    is the primary input; the new artefact id auto-rewrites to track it.

    The source record is shown read-only at the top so the operator can
    confirm what they're about to reuse.
    """

    def __init__(self, source_record: dict[str, Any], parent=None):
        super().__init__(parent)
        self._source = source_record

        self.setWindowTitle("Copy artefact to another run")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        # ── Source summary (read-only) ────────────────────────────────
        src_id = source_record.get("artefact_id", "")
        src_type = source_record.get("artefact_type", "")
        src_run = (source_record.get("run_context") or {}).get("run_number", "")
        self._src_id = src_id
        self._src_run = src_run

        summary = QLabel(
            f"<b>Source artefact:</b> {src_id}<br>"
            f"<b>Type:</b> {src_type}"
            + (f"<br><b>Source run:</b> {src_run}" if src_run != "" else "")
        )
        summary.setTextFormat(Qt.RichText)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        hint = QLabel(
            "Reuse this artefact on a different run. The new artefact id "
            "is suggested automatically — edit if needed."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(hint)

        # ── Form (run number first — that's the primary input) ───────
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._runEdit = QLineEdit()
        self._runEdit.setPlaceholderText(
            "e.g. 65892"
            + (f"   (source was {src_run})" if src_run != "" else "")
        )
        form.addRow("For run number:", self._runEdit)

        self._newIdEdit = QLineEdit()
        self._newIdEdit.setPlaceholderText("auto-suggested from the run number above")
        # Seed with a sensible default (no run typed yet)
        self._newIdEdit.setText(f"{src_id}-copy" if src_id else "")
        form.addRow("New artefact id:", self._newIdEdit)

        # Auto-rewrite the id whenever the run number changes — but only
        # while the operator hasn't started editing the id themselves.
        self._idEditedByUser = False
        self._newIdEdit.textEdited.connect(self._onIdEditedByUser)
        self._runEdit.textChanged.connect(self._onRunChanged)

        self._copyFileCheck = QCheckBox(
            "Make an independent copy I can edit separately"
        )
        self._copyFileCheck.setToolTip(
            "Unchecked (default): the new record points at the SAME file as "
            "the source — instant, zero disk cost, but edits affect both.\n\n"
            "Checked: the underlying file is physically duplicated so the "
            "new record can be edited without touching the original."
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

        # Start with focus on the primary input
        self._runEdit.setFocus()

    # ── Internal slots ─────────────────────────────────────────────────

    def _onIdEditedByUser(self, _text: str) -> None:
        # Once the operator types in the id field, stop auto-rewriting.
        self._idEditedByUser = True

    def _onRunChanged(self, text: str) -> None:
        if self._idEditedByUser:
            return
        new_run = text.strip()
        if not new_run:
            self._newIdEdit.setText(
                f"{self._src_id}-copy" if self._src_id else ""
            )
            self._idEditedByUser = False
            return
        suggested = _suggest_new_id(self._src_id, self._src_run, new_run)
        self._newIdEdit.setText(suggested)
        # setText() doesn't fire textEdited, so the flag stays False.
        self._idEditedByUser = False

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
