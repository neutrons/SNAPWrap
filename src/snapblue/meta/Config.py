import importlib.resources as resources

import os
import sys

from pathlib import Path

from snapred.meta.Config import Resource as RedResource, Config

def _find_root_dir():
    try:
        MODULE_ROOT = Path(sys.modules["snapblue"].__file__).parent

        # Using `"test" in env` here allows different versions of "[category]_test.yml" to be used for different
        #  test categories: e.g. unit tests use "test.yml" but integration tests use "integration_test.yml".
        env = os.environ.get("snapblue_env")
        if env and "test" in env and "conftest" in sys.modules:
            # WARNING: there are now multiple "conftest.py" at various levels in the test hierarchy.
            MODULE_ROOT = MODULE_ROOT.parent.parent / "tests"
    except Exception as e:
        raise RuntimeError("Unable to determine SNAPBlue module-root directory") from e

    return str(MODULE_ROOT)

class _Resource:
    _packageMode: bool
    _resourcesPath: str

    def __init__(self):
        # where the location of resources are depends on whether or not this is in package mode
        self._packageMode = not self._existsInPackage("application.yml")
        if self._packageMode:
            self._resourcesPath = "/resources/"
        else:
            self._resourcesPath = os.path.join(_find_root_dir(), "resources/")

    def _existsInPackage(self, subPath) -> bool:
        with resources.path("snapblue.resources", subPath) as path:
            return os.path.exists(path)

    def exists(self, subPath) -> bool:
        if self._packageMode:
            return self._existsInPackage(subPath)
        else:
            return os.path.exists(self.getPath(subPath))

    def getPath(self, subPath):
        if subPath.startswith("/"):
            return os.path.join(self._resourcesPath, subPath[1:])
        else:
            return os.path.join(self._resourcesPath, subPath)

    def read(self, subPath):
        with self.open(subPath, "r") as file:
            return file.read()

    def open(self, subPath, mode):  # noqa: A003
        if self._packageMode:
            with resources.path("snapblue.resources", subPath) as path:
                return open(path, mode)
        else:
            return open(self.getPath(subPath), mode)


Resource = _Resource()
RedResource._resourcesPath = Resource._resourcesPath
RedResource._packageMode = Resource._packageMode
# use refresh to do initial load, clearing shouldn't matter
Config.refresh("application.yml")

# ---------- SNAPRed-internal values: --------------------------
# allow "resources" relative paths to be entered into the "yml"
#   using "${module.root}"
Config._config["module"] = {}
Config._config["module"]["root"] = _find_root_dir()

Config._config["version"] = Config._config.get("version", {})
Config._config["version"]["default"] = -1
# ---------- end: internal values: -----------------------------

# see if user used environment injection to modify what is needed
# this will get from the os environment or from the currently loaded one
# first case wins
env = os.environ.get("snapblue_env", Config._config.get("environment", None))
if env is not None:
    Config.refresh(env)