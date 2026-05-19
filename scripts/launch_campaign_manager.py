"""Launcher for the Campaign Manager from inside Mantid Workbench.

Reloads every submodule from leaves → mainWindow → package, so you can
iterate on snapwrap.campaignManager without restarting Workbench.

Maintained by the dev — if you add or move a campaignManager submodule,
add a line here.  Order matters: leaves first, mainWindow before the
package __init__.
"""

import importlib

# ── Imports (leaves first) ────────────────────────────────────────────
import snapwrap.campaignManager.constants
import snapwrap.campaignManager.model
import snapwrap.campaignManager.workers
import snapwrap.campaignManager.delegates
import snapwrap.campaignManager.dialogs
import snapwrap.campaignManager.logHandler
import snapwrap.campaignManager.panels.artefactsPanel
import snapwrap.campaignManager.panels.runsPanel
import snapwrap.campaignManager.panels.reducePanel
import snapwrap.campaignManager.mainWindow
import snapwrap.campaignManager

# ── Reloads (same order) ──────────────────────────────────────────────
importlib.reload(snapwrap.campaignManager.constants)
importlib.reload(snapwrap.campaignManager.model)
importlib.reload(snapwrap.campaignManager.workers)
importlib.reload(snapwrap.campaignManager.delegates)
importlib.reload(snapwrap.campaignManager.dialogs)
importlib.reload(snapwrap.campaignManager.logHandler)
importlib.reload(snapwrap.campaignManager.panels.artefactsPanel)
importlib.reload(snapwrap.campaignManager.panels.runsPanel)
importlib.reload(snapwrap.campaignManager.panels.reducePanel)
importlib.reload(snapwrap.campaignManager.mainWindow)
importlib.reload(snapwrap.campaignManager)

# Drop any cached dialog so the freshly-reloaded class is used.
snapwrap.campaignManager._active_dialog = None

snapwrap.campaignManager.show()
