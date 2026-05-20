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
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
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


# ── Copy crystal species to campaign dialog ────────────────────────────────────

class CopyCrystalSpeciesDialog(QDialog):
    """Pick a target IPTS + campaign to copy a crystal species into.

    The model is passed so campaigns can be reloaded when the IPTS changes.
    """

    def __init__(self, cs_record: dict, current_ipts: int, current_slug: str, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._current_ipts = current_ipts
        self._current_slug = current_slug

        self.setWindowTitle("Copy crystal species to campaign")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        species_name = cs_record.get("species_name", "?")
        role = cs_record.get("role", "?")
        has_eos = bool(cs_record.get("eosPath"))
        summary = QLabel(
            f"<b>Species:</b> {species_name} &nbsp; <b>Role:</b> {role}"
            + (" &nbsp; <i>(includes EOS)</i>" if has_eos else "")
        )
        summary.setTextFormat(Qt.RichText)
        layout.addWidget(summary)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        ipts_row = QHBoxLayout()
        self._iptsEdit = QLineEdit(str(current_ipts))
        self._iptsEdit.setMaximumWidth(140)
        ipts_row.addWidget(self._iptsEdit)
        load_btn = QPushButton("Load campaigns")
        load_btn.clicked.connect(self._loadCampaigns)
        ipts_row.addWidget(load_btn)
        ipts_row.addStretch(1)
        form.addRow("Target IPTS:", ipts_row)

        self._campaignCombo = QComboBox()
        self._campaignCombo.setMinimumWidth(240)
        form.addRow("Target campaign:", self._campaignCombo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("Copy")
        self._okBtn = buttons.button(QDialogButtonBox.Ok)
        self._okBtn.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._loadCampaigns()

    def _loadCampaigns(self) -> None:
        ipts = self.targetIpts()
        if ipts is None:
            self._okBtn.setEnabled(False)
            return
        try:
            campaigns = self._model.getCampaigns(ipts=ipts)
        except Exception:
            campaigns = []
        self._campaignCombo.clear()
        for c in campaigns:
            slug = c.get("campaign_slug", "")
            cid = c.get("campaign_id", "")
            label = f"{slug}  (id={cid})" if cid != "" else slug
            if slug == self._current_slug and ipts == self._current_ipts:
                label += "  [current]"
            self._campaignCombo.addItem(label, userData=slug)
        self._okBtn.setEnabled(bool(campaigns))

    def targetIpts(self) -> int | None:
        try:
            return int(self._iptsEdit.text().strip())
        except ValueError:
            return None

    def targetCampaign(self) -> str | None:
        return self._campaignCombo.currentData()


# ── New-campaign dialog ────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_ASSEMBLY_TYPES = ["DAC", "PE", "OTHER"]


class NewCampaignDialog(QDialog):
    """Prompt the operator for parameters to :func:`bootstrap_campaign`.

    The slug field validates against the same regex the backend enforces so
    the operator gets immediate feedback rather than a server-side error.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New campaign")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._slugEdit = QLineEdit()
        self._slugEdit.setPlaceholderText(
            "lowercase letters, digits, hyphens, underscores — min 2 chars"
        )
        self._slugEdit.textChanged.connect(self._onSlugChanged)
        form.addRow("Campaign slug:", self._slugEdit)

        self._slugError = QLabel()
        self._slugError.setStyleSheet("color: red;")
        self._slugError.setVisible(False)
        form.addRow("", self._slugError)

        self._assemblyCombo = QComboBox()
        for t in _ASSEMBLY_TYPES:
            self._assemblyCombo.addItem(t)
        form.addRow("Assembly type:", self._assemblyCombo)

        self._descEdit = QPlainTextEdit()
        self._descEdit.setPlaceholderText("Optional description")
        self._descEdit.setFixedHeight(70)
        form.addRow("Description:", self._descEdit)

        self._ownersEdit = QLineEdit()
        self._ownersEdit.setPlaceholderText("Optional — comma-separated usernames")
        form.addRow("Owners:", self._ownersEdit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        self._okBtn = buttons.button(QDialogButtonBox.Ok)
        self._okBtn.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._slugEdit.setFocus()

    # ── Internal slots ─────────────────────────────────────────────────

    def _onSlugChanged(self, text: str) -> None:
        stripped = text.strip()
        valid = bool(_SLUG_RE.fullmatch(stripped))
        self._okBtn.setEnabled(valid)
        if not stripped or valid:
            self._slugError.setVisible(False)
        else:
            self._slugError.setText(
                "Must match ^[a-z0-9][a-z0-9_-]{1,62}$  (min 2 chars, lowercase)"
            )
            self._slugError.setVisible(True)

    # ── Public API ─────────────────────────────────────────────────────

    def slug(self) -> str:
        return self._slugEdit.text().strip()

    def assemblyType(self) -> str:
        return self._assemblyCombo.currentText()

    def description(self) -> str | None:
        text = self._descEdit.toPlainText().strip()
        return text or None

    def owners(self) -> list[str] | None:
        text = self._ownersEdit.text().strip()
        if not text:
            return None
        return [o.strip() for o in text.split(",") if o.strip()]


# ── Ingest-asset dialog ────────────────────────────────────────────────────

_ASSET_TYPES = [
    "cif",
    "ub_matrix",
    "seemeta_json",
    "manual_pixel_mask",
    "eos_description",
    "phase_description",
    "other",
]


class IngestAssetDialog(QDialog):
    """Prompt the operator for the parameters needed to ingest a file as an asset.

    The asset_id field defaults to the file stem but can be overridden.
    The run-number field is shown only when scope is 'run'.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ingest asset")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # File picker
        file_row = QHBoxLayout()
        self._fileEdit = QLineEdit()
        self._fileEdit.setPlaceholderText("Path to file on disk")
        self._fileEdit.textChanged.connect(self._onFileChanged)
        file_row.addWidget(self._fileEdit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._onBrowse)
        file_row.addWidget(browse_btn)
        form.addRow("File:", file_row)

        # Asset type
        self._typeCombo = QComboBox()
        for t in _ASSET_TYPES:
            self._typeCombo.addItem(t)
        form.addRow("Asset type:", self._typeCombo)

        # Asset ID (optional)
        self._idEdit = QLineEdit()
        self._idEdit.setPlaceholderText("defaults to filename stem")
        form.addRow("Asset ID:", self._idEdit)

        # Scope
        self._scopeCombo = QComboBox()
        self._scopeCombo.addItem("Campaign-wide", userData="campaign")
        self._scopeCombo.addItem("Run-specific", userData="run")
        self._scopeCombo.currentIndexChanged.connect(self._onScopeChanged)
        form.addRow("Scope:", self._scopeCombo)

        # Run number (shown only for run scope)
        self._runEdit = QLineEdit()
        self._runEdit.setPlaceholderText("e.g. 65891")
        self._runEdit.setMaximumWidth(180)
        self._runRow_label = QLabel("Run number:")
        form.addRow(self._runRow_label, self._runEdit)
        self._runRow_label.setVisible(False)
        self._runEdit.setVisible(False)

        # Notes
        self._notesEdit = QPlainTextEdit()
        self._notesEdit.setPlaceholderText("Optional notes")
        self._notesEdit.setFixedHeight(60)
        form.addRow("Notes:", self._notesEdit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("Ingest")
        self._okBtn = buttons.button(QDialogButtonBox.Ok)
        self._okBtn.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Internal slots ─────────────────────────────────────────────────

    def _onBrowse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select asset file")
        if path:
            self._fileEdit.setText(path)

    def _onFileChanged(self, text: str) -> None:
        self._okBtn.setEnabled(bool(text.strip()))
        # Auto-fill asset ID from stem if operator hasn't typed anything
        if not self._idEdit.text().strip():
            from pathlib import Path
            stem = Path(text.strip()).stem if text.strip() else ""
            self._idEdit.setPlaceholderText(stem or "defaults to filename stem")

    def _onScopeChanged(self, _index: int) -> None:
        is_run = self._scopeCombo.currentData() == "run"
        self._runRow_label.setVisible(is_run)
        self._runEdit.setVisible(is_run)

    # ── Public API ─────────────────────────────────────────────────────

    def filePath(self) -> str:
        return self._fileEdit.text().strip()

    def assetType(self) -> str:
        return self._typeCombo.currentText()

    def assetId(self) -> str | None:
        text = self._idEdit.text().strip()
        return text or None

    def scope(self) -> str:
        return self._scopeCombo.currentData()

    def runNumber(self) -> int | None:
        text = self._runEdit.text().strip()
        try:
            return int(text) if text else None
        except ValueError:
            return None

    def notes(self) -> str | None:
        text = self._notesEdit.toPlainText().strip()
        return text or None
