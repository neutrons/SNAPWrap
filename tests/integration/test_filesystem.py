

import pytest
from util.pytest_helpers import calibration_home_from_mirror, handleStateInit, reduction_home_from_mirror  # noqa: F401
from snapblue.meta.Config import Config
from pathlib import Path


@pytest.mark.integration
@pytest.mark.datarepo
def test_calibrationHomeExists(calibration_home_from_mirror):
    tmpCalibrationHomeDirectory = calibration_home_from_mirror()
    calibrationHomePath = Path(Config["instrument.calibration.home"])
    assert calibrationHomePath.exists()
    iptsHomePath = Path(Config["IPTS.root"])
    assert iptsHomePath.exists()