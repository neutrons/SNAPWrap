"""Contains the entry point for the application"""
from .wrapConfig import WrapConfig

WrapConfig.load()

__all__ = ["WrapConfig"]

# Cycles come from SNAPRed's SNAPInstPrm when it carries them: see
# snapStateMgr.cycleForRun. Only when it carries none (SNAPRed 2.3.1, or no cycle
# registered yet) does wrap fall back to its own cycleDates table, loaded here.
# build_cycle_json compares the .ods against the existing JSON and only rewrites
# (and bumps the version) when the cycle data actually changed. It also populates
# the in-memory cache, so a separate load_cycle_data call is not needed.
#
# If the fallback is needed but unavailable (e.g. CI / test environments) we warn
# but allow the import to proceed: cycle-aware features will return None.
from snapred.meta.Config import Config
from .cycleDates import build_cycle_json
import os as _os

_calib_home = Config["instrument.calibration.home"]

try:
    from .snapStateMgr import registeredCycles as _registeredCycles

    _redCycles = _registeredCycles()
except Exception as _e:  # never let the check stop the import; fall back as before
    print(f"SNAPInstPrm: could not read registered cycles ({_e}); trying cycleDates")
    _redCycles = []

if _redCycles:
    print(f"Cycles: {len(_redCycles)} registered in SNAPRed's SNAPInstPrm, latest {_redCycles[0]}.")
else:
    try:
        build_cycle_json(
            json_path=_os.path.join(_calib_home, "cycleDates.json"),
            ods_path=_os.path.join(_calib_home, "cycleDates.ods"),
        )
        print("No cycles in SNAPRed's SNAPInstPrm; loaded wrap's cycle-date data instead.")
        print(f"  source: {_os.path.join(_calib_home, 'cycleDates.ods')}")
        print(f"  index:  {_os.path.join(_calib_home, 'cycleDates.json')}")
    except FileNotFoundError as _e:
        import warnings as _w
        _w.warn(
            f"No cycles in SNAPRed's SNAPInstPrm and no cycle-date data ({_e}). "
            "Cycle-aware calibration checks will be disabled.",
            stacklevel=1,
        )
    except PermissionError as _e:
        import warnings as _w
        _w.warn(
            f"Cycle-date data could not be written ({_e}). "
            "This is expected for non-instrument-scientist users. "
            "Cycle data from the existing JSON (if any) will be used.",
            stacklevel=1,
        )


try:
    from ._version import __version__  # noqa: F401
except ImportError:
    __version__ = "unknown"


def PackageName():  # noqa N802
    """This is needed for backward compatibility because mantid workbench does "from shiver import Shiver" """
    from .packagenamepy import PackageName as packagename  # noqa N813

    return packagename()
