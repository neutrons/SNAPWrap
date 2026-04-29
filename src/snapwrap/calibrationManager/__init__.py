"""SNAP Calibration Manager — Qt5 GUI for inspecting and managing calibration states.

Usage from Mantid Workbench script console::

    from snapwrap.calibrationManager import show
    show()
"""

import logging as _logging

# Silence the flood of INFO messages from SNAPRed's MantidSnapper
# (e.g. "CheckIPTS - get IPTS directory") that fire on every
# DataFactoryService / LocalDataService call.  These use Python's
# logging module, so Mantid's own ConfigService log level has no
# effect on them.
_logging.getLogger("snapred.backend.recipe.algorithm.MantidSnapper").setLevel(
    _logging.WARNING
)

# Module-level reference keeps the dialog alive while it is open.
_active_dialog = None


def show():
    """Open the Calibration Manager dialog from Mantid Workbench.

    Safe to call from the Workbench script window.  Uses Mantid's
    ``QAppThreadCall`` to create widgets on the GUI thread.
    """
    from mantidqt.utils.qt.qappthreadcall import QAppThreadCall
    from qtpy.QtCore import QThread
    from qtpy.QtWidgets import QApplication

    def _open():
        global _active_dialog
        if _active_dialog is not None:
            # If the Qt object was deleted but the Python reference remained,
            # clear it and create a fresh dialog.
            try:
                # Probe object validity; this can raise if underlying C++ object
                # has already been deleted.
                _ = _active_dialog.isVisible()

                # Re-show when previously closed/hidden.
                if not _active_dialog.isVisible():
                    _active_dialog.show()
                _active_dialog.raise_()
                _active_dialog.activateWindow()
                return
            except Exception:
                _active_dialog = None

        from snapwrap.calibrationManager.mainWindow import CalibrationManager

        _active_dialog = CalibrationManager()
        _active_dialog.show()
        _active_dialog.raise_()
        _active_dialog.activateWindow()
        _active_dialog.loadData()

        # Clean up reference when closed
        def _on_destroyed():
            global _active_dialog
            _active_dialog = None

        _active_dialog.destroyed.connect(_on_destroyed)

    # If called from a GUI menu action, we're already on the Qt GUI thread.
    # In that case call directly to avoid thread-handoff quirks in some
    # Workbench builds. Otherwise marshal to GUI thread via QAppThreadCall.
    app = QApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        # Direct call is safe when already in GUI context.
        _open()
        return

    try:
        QAppThreadCall(_open, blocking=True)()
    except Exception:
        # Last-resort fallback keeps manual scripting usable even if
        # qappthreadcall wiring is unavailable in a specific environment.
        _open()
