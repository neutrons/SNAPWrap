

import pytest
from util.pytest_helpers import calibration_home_from_mirror, handleStateInit, reduction_home_from_mirror  # noqa: F401


@pytest.mark.integration
@pytest.mark.datarepo
def test_reduction(reduction_home_from_mirror):
    pass