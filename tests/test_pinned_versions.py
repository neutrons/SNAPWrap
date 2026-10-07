"""wrap pins the calibration versions it validated, instead of letting SNAPRed re-resolve.

The defect being closed: wrap's cycle filtering decided *whether* to reduce,
while SNAPRed independently decided *which* calibration to use — by taking the
most recently written applicable entry, with no regard to cycle. So a run with a
good in-cycle calibration could be reduced against an out-of-cycle one purely
because that entry was written later, and nothing announced it.

These tests cover the wrap-side logic and the hand-off type. They cannot prove
the end-to-end outcome; that needs a calibration home containing a newer
out-of-cycle calibration alongside an older in-cycle one. See
``docs/manual_test_pinned_versions.md`` for that scenario.
"""

from __future__ import annotations

import pytest

from snapred.backend.dao.indexing.Versioning import VersionState
from snapred.backend.dao.request.ReductionRequest import ReductionRequest, Versions

from snapwrap.utils import _pinnedVersions


def _status(version):
    """A checkCalibrationStatus result carrying the version wrap selected."""
    return {"latestValidCalibrationDict": {"version": version}}


# ═══════════════════════════════════════════════════════════════════════
# what gets pinned
# ═══════════════════════════════════════════════════════════════════════


class TestPinnedVersions:

    def test_pins_both_when_both_found(self):
        versions = _pinnedVersions(
            _status(12), _status(4),
            difcalFound=True, normcalFound=True, skipNormalization=False,
        )
        assert versions.calibration == 12
        assert versions.normalization == 4

    def test_pins_the_version_wrap_validated_not_the_newest(self):
        """The whole point: wrap's choice, which SNAPRed must not re-derive."""
        versions = _pinnedVersions(
            _status(3), _status(0),
            difcalFound=True, normcalFound=True, skipNormalization=False,
        )
        # 3 rather than some later entry SNAPRed would have preferred
        assert versions.calibration == 3

    def test_version_zero_is_pinnable(self):
        """0 is a real normalization version, not a missing value."""
        versions = _pinnedVersions(
            _status(1), _status(0),
            difcalFound=True, normcalFound=True, skipNormalization=False,
        )
        assert versions.normalization == 0

    # ── the fall-through paths: SNAPRed keeps its own behaviour ──

    def test_no_difcal_leaves_latest(self):
        """continueNoDifcal: nothing to pin, SNAPRed falls back to its default."""
        versions = _pinnedVersions(
            {}, _status(4),
            difcalFound=False, normcalFound=True, skipNormalization=False,
        )
        assert versions.calibration is VersionState.LATEST
        assert versions.normalization == 4

    def test_skipped_normalization_leaves_latest(self):
        """noNorm / artificial normalization: normalization is not looked up."""
        versions = _pinnedVersions(
            _status(12), _status(4),
            difcalFound=True, normcalFound=True, skipNormalization=True,
        )
        assert versions.calibration == 12
        assert versions.normalization is VersionState.LATEST

    def test_no_normcal_leaves_latest(self):
        versions = _pinnedVersions(
            _status(12), {},
            difcalFound=True, normcalFound=False, skipNormalization=False,
        )
        assert versions.normalization is VersionState.LATEST

    def test_neither_found_leaves_both_latest(self):
        versions = _pinnedVersions(
            {}, {},
            difcalFound=False, normcalFound=False, skipNormalization=True,
        )
        assert versions.calibration is VersionState.LATEST
        assert versions.normalization is VersionState.LATEST

    # ── malformed input must degrade, not raise ──

    @pytest.mark.parametrize("bad", [None, {}, {"latestValidCalibrationDict": {}},
                                     {"latestValidCalibrationDict": None},
                                     {"latestValidCalibrationDict": {"version": None}},
                                     {"latestValidCalibrationDict": {"version": "12"}}])
    def test_unusable_version_falls_back_to_latest(self, bad):
        """Should not happen, but must not turn into a hard failure if it does."""
        versions = _pinnedVersions(
            bad, bad,
            difcalFound=True, normcalFound=True, skipNormalization=False,
        )
        assert versions.calibration is VersionState.LATEST
        assert versions.normalization is VersionState.LATEST


# ═══════════════════════════════════════════════════════════════════════
# the hand-off to SNAPRed
# ═══════════════════════════════════════════════════════════════════════


def test_snapred_default_is_latest_which_is_the_hole_being_closed():
    """Documents why pinning is necessary: unset means SNAPRed re-resolves."""
    request = ReductionRequest(runNumber="72375", useLiteMode=True)
    assert request.versions.calibration is VersionState.LATEST
    assert request.versions.normalization is VersionState.LATEST


def test_pinned_versions_survive_the_reduction_request():
    """The type wrap builds must be accepted and carried by SNAPRed's DAO."""
    versions = _pinnedVersions(
        _status(12), _status(4),
        difcalFound=True, normcalFound=True, skipNormalization=False,
    )
    request = ReductionRequest(runNumber="72375", useLiteMode=True, versions=versions)

    assert isinstance(request.versions, Versions)
    assert request.versions.calibration == 12
    assert request.versions.normalization == 4


def test_latest_sentinel_survives_the_reduction_request():
    """The fall-through paths must also round-trip through the DAO."""
    versions = _pinnedVersions(
        {}, {},
        difcalFound=False, normcalFound=False, skipNormalization=True,
    )
    request = ReductionRequest(runNumber="72375", useLiteMode=True, versions=versions)

    assert request.versions.calibration is VersionState.LATEST
    assert request.versions.normalization is VersionState.LATEST
