"""wrap finds SNAPRed's reduction output through ``instrument.reduction.home``.

snapwrap.io used to hard-code ``{ipts}shared/SNAPRed/``. With the default config
that is the same place, but any override of ``instrument.reduction.home`` -- such
as the CIS harness, which redirects SNAPRed's output out of the real IPTS -- left
wrap reading and EXPORTING into the real IPTS while SNAPRed wrote elsewhere.
"""

from __future__ import annotations

import pytest
from snapred.meta.Config import Config

import snapwrap.io as io


@pytest.mark.parametrize("ipts", ["/SNS/SNAP/IPTS-37478/", "/SNS/SNAP/IPTS-37478"])
def test_default_config_matches_the_old_hardcoded_path(ipts):
    """Production behaviour must not move."""
    assert "{IPTS}" in Config["instrument.reduction.home"]
    assert io.reductionHome(ipts) == "/SNS/SNAP/IPTS-37478/shared/SNAPRed/"


def test_override_with_ipts_placeholder(monkeypatch):
    monkeypatch.setattr(io, "Config", {"instrument.reduction.home": "/scratch/harness/Reduced/{IPTS}"})
    assert io.reductionHome("/SNS/SNAP/IPTS-37478/") == "/scratch/harness/Reduced/IPTS-37478/"


def test_override_without_placeholder(monkeypatch):
    monkeypatch.setattr(io, "Config", {"instrument.reduction.home": "/scratch/flat/"})
    assert io.reductionHome("/SNS/SNAP/IPTS-37478/") == "/scratch/flat/"
