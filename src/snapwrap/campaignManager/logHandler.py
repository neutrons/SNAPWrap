"""Qt logging handler for live log streaming in the Campaign Manager.

Bridges Python's ``logging`` framework to a Qt signal so log records
emitted from a worker thread are delivered to a GUI widget via Qt's
queued-connection mechanism — no manual polling required.
"""

from __future__ import annotations

import logging

from qtpy.QtCore import QObject, Signal  # type: ignore


class QtLogHandler(QObject, logging.Handler):
    """Emit each formatted log record as a Qt signal.

    Install on a logger before running a long operation, connect
    ``logLine`` to a ``QPlainTextEdit.appendPlainText`` slot, then
    remove when done::

        handler = QtLogHandler()
        handler.logLine.connect(self._logEdit.appendPlainText)
        logger = logging.getLogger("snapwrap")
        logger.addHandler(handler)
        try:
            do_work()
        finally:
            logger.removeHandler(handler)

    Because the receiver slot lives in the GUI thread and the signal is
    emitted from the worker thread, Qt automatically uses a queued
    delivery — the GUI thread is never touched from the worker.
    """

    logLine = Signal(str)

    def __init__(self) -> None:
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.setFormatter(
            logging.Formatter("%(levelname)-8s  %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.logLine.emit(self.format(record))
        except Exception:
            self.handleError(record)
