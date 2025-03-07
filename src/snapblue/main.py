"""Main Qt application"""

import sys

from mantid.kernel import Logger
from mantidqt.gui_helper import set_matplotlib_backend
from qtpy.QtWidgets import QApplication, QMainWindow

# make sure matplotlib is correctly set before we import shiver
set_matplotlib_backend()

# make sure the algorithms have been loaded so they are available to the AlgorithmManager
import mantid.simpleapi  # noqa: F401, E402 pylint: disable=unused-import, wrong-import-position

from snapblue import __version__  # noqa: E402 pylint: disable=wrong-import-position
from snapblue.configuration import Configuration  # noqa: E402 pylint: disable=wrong-import-position

logger = Logger("PACKAGENAME")


print("Hello World")
