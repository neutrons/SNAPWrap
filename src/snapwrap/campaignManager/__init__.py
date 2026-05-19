"""SNAPWrap Campaign Manager — Qt5 GUI for managing reduction campaigns.

Usage from Mantid Workbench script console::

    from snapwrap.campaignManager import show
    show()

This UI is a thin client over :mod:`snapwrap.reduction_artefacts`.  It does
not add new business logic; every button corresponds to one existing
backend call.  The intent is to give operators a Workbench-native way to:

* browse and filter the artefacts registered for a campaign,
* retire / copy artefacts without dropping into a Python console,
* edit the campaign spec JSON (the single source of truth),
* trigger per-run reduction and watch the log live,
* load reduced outputs back into the ADS for inspection.

Phased delivery:

* Phase 0 — scaffolding + ``show()`` entry point + placeholder tabs.
* Phase 1 — read-only Artefacts panel backed by ``list_artefact_records``.
* Phase 2+ — mutations, Runs/Reduce/Setup tabs (planned).
"""

from __future__ import annotations

import logging as _logging

# Match the calibration-manager convention: silence the noisy SNAPRed
# MantidSnapper INFO logs that fire on every backend service call.
_logging.getLogger("snapred.backend.recipe.algorithm.MantidSnapper").setLevel(
    _logging.WARNING
)

# Module-level reference keeps the dialog alive while it is open.
_active_dialog = None


def show():
    """Open the Campaign Manager dialog from Mantid Workbench.

    Safe to call from the Workbench script window.  Uses Mantid's
    ``QAppThreadCall`` to marshal widget creation onto the GUI thread when
    invoked from a non-GUI context (e.g. a background script).

    If a Campaign Manager window is already open this call brings it to
    the front instead of opening a second one.
    """
    from mantidqt.utils.qt.qappthreadcall import QAppThreadCall
    from qtpy.QtCore import QThread
    from qtpy.QtWidgets import QApplication

    def _open():
        global _active_dialog
        if _active_dialog is not None:
            # Probe whether the underlying C++ object still exists.
            try:
                _ = _active_dialog.isVisible()
                if not _active_dialog.isVisible():
                    _active_dialog.show()
                _active_dialog.raise_()
                _active_dialog.activateWindow()
                return
            except Exception:
                _active_dialog = None

        from snapwrap.campaignManager.mainWindow import CampaignManager

        _active_dialog = CampaignManager()
        _active_dialog.show()
        _active_dialog.raise_()
        _active_dialog.activateWindow()

        def _on_destroyed():
            global _active_dialog
            _active_dialog = None

        _active_dialog.destroyed.connect(_on_destroyed)

    # Already on the Qt GUI thread (called from a menu action / interactive
    # console) — open directly to avoid thread-handoff quirks.
    app = QApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        _open()
        return

    try:
        QAppThreadCall(_open, blocking=True)()
    except Exception:
        # Last-resort fallback keeps manual scripting usable even when
        # qappthreadcall wiring is unavailable in a specific build.
        _open()
