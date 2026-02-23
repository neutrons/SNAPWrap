"""Contains the entry point for the application"""
from .wrapConfig import WrapConfig

WrapConfig.load()

__all__ = ["WrapConfig"]

# Load cycle-date data for calibration-validity checks.
# build_cycle_json compares the .ods against the existing JSON and only
# rewrites (and bumps the version) when the cycle data actually changed.
# It also populates the in-memory cache, so a separate load_cycle_data
# call is not needed.
#
# If neither the .ods nor the JSON are available (e.g. CI / test
# environments) we warn but allow the import to proceed — cycle-aware
# features will simply return None.
from snapred.meta.Config import Config
from .cycleDates import build_cycle_json
import os as _os

_calib_home = Config["instrument.calibration.home"]

try:
    build_cycle_json(
        json_path=_os.path.join(_calib_home, "cycleDates.json"),
        ods_path=_os.path.join(_calib_home, "cycleDates.ods"),
    )
    print("Loaded cycle-date data successfully.")
    print(f"  source: {_os.path.join(_calib_home, 'cycleDates.ods')}")
    print(f"  index:  {_os.path.join(_calib_home, 'cycleDates.json')}")
except FileNotFoundError as _e:
    import warnings as _w
    _w.warn(
        f"Cycle-date data not available ({_e}). "
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
