"""Tests for the custom versioningit ``tag2version`` in ``tools/versioning.py``.

``tools`` is not a package, so the module is loaded from its path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_VERSIONING_PATH = Path(__file__).resolve().parents[1] / "tools" / "versioning.py"
_spec = importlib.util.spec_from_file_location("versioning", _VERSIONING_PATH)
versioning = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(versioning)


def _tag2version(tag: str) -> str:
    return versioning.tag2version(tag=tag, params={})


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("v2.4.0", "2.4.0"),
        ("v2.4.0rc1", "2.4.0rc1"),
        ("2.3.1", "2.3.1"),
    ],
)
def test_non_exp_tags_pass_through(tag, expected):
    assert _tag2version(tag) == expected


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("v2.4.0exp1", "2.4.0+exp.1"),
        ("v2.4.0exp10", "2.4.0+exp.10"),
        ("v2.4.0exp1-Cycle_aware.calib", "2.4.0+exp.1.cycle.aware.calib"),
        ("v2.4.0exp", "2.4.0+exp"),
    ],
)
def test_exp_tags_map_to_local_version(tag, expected):
    assert _tag2version(tag) == expected


def test_exp_number_compares_numerically():
    from packaging.version import Version

    assert Version(_tag2version("v2.4.0exp10")) > Version(_tag2version("v2.4.0exp2"))


@pytest.mark.parametrize("tag", ["v2.4.0exp1-", "v2.4.0exp1-bad!name"])
def test_invalid_exp_tags_raise(tag):
    with pytest.raises(ValueError, match="Invalid exp tag"):
        _tag2version(tag)
