"""Background workers for the Campaign Manager.

Long-running backend calls (artefact list scans, future reductions and
mask builds) MUST go through a QThread/worker pair so the GUI thread
remains responsive.  This module hosts the reusable pattern.
"""

from __future__ import annotations

from typing import Any, Callable

from qtpy.QtCore import QObject, Signal  # type: ignore


class GenericWorker(QObject):
    """Run *fn* on a worker thread and emit the result.

    Designed to be moved onto a ``QThread`` by the host:

    .. code-block:: python

        thread = QThread(parent_widget)
        worker = GenericWorker(fn, kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_loaded)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn: Callable[..., Any], kwargs: dict[str, Any] | None = None):
        super().__init__()
        self._fn = fn
        self._kwargs = kwargs or {}

    def run(self) -> None:
        try:
            result = self._fn(**self._kwargs)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(result)
