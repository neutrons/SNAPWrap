"""SNAP Calibration Manager — Qt5 GUI for inspecting and managing calibration states.

Usage from Mantid Workbench script console::

    from snapwrap.calibrationManager import show
    show()
"""

# Module-level reference keeps the dialog alive while it is open.
_active_dialog = None


def show():
    """Open the Calibration Manager dialog from Mantid Workbench.

    Safe to call from the Workbench script window.  Uses Mantid's
    ``QAppThreadCall`` to create widgets on the GUI thread.
    """
    from mantidqt.utils.qt.qappthreadcall import QAppThreadCall

    def _open():
        global _active_dialog
        if _active_dialog is not None:
            _active_dialog.raise_()
            _active_dialog.activateWindow()
            return

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

    QAppThreadCall(_open, blocking=True)()
