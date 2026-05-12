"""Conftest for the vendored ``snapwrap._inspectrum`` test suite.

Every test in this directory is auto-marked with the ``inspectrum`` pytest
marker, and the whole tree is skipped if ``cryspy`` (the only PyPI-only hard
dependency of the vendored code) is not importable.  This keeps snapwrap's
core test runs fast and lets developers exclude / include the inspectrum
tests as a group:

    # Run everything except inspectrum tests
    pytest -m "not inspectrum"

    # Run only inspectrum tests
    pytest -m inspectrum
"""

import importlib.util

import pytest

_HAS_CRYSPY = importlib.util.find_spec("cryspy") is not None


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test under ``tests/_inspectrum/`` and skip if cryspy is missing."""
    skip_marker = pytest.mark.skip(reason="cryspy not available; skipping vendored inspectrum tests")
    inspectrum_marker = pytest.mark.inspectrum
    for item in items:
        if "tests/_inspectrum/" not in item.nodeid.replace("\\", "/"):
            continue
        item.add_marker(inspectrum_marker)
        if not _HAS_CRYSPY:
            item.add_marker(skip_marker)
