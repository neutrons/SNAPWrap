"""Cycle enumeration read from SNAPInstPrm rather than the cycleDates table.

``orderCycleIDs`` is pure and is exercised directly. ``registeredCycles`` does
I/O through snapred, so it is driven with stand-in instrument configs rather
than against the production index — the logic under test is which cycles get
collected and in what order, not snapred's file reading.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from snapwrap import snapStateMgr as ssm


# ═══════════════════════════════════════════════════════════════════════
# orderCycleIDs — pure
# ═══════════════════════════════════════════════════════════════════════


class TestOrderCycleIDs:

    def test_most_recent_first(self):
        assert ssm.orderCycleIDs(["2025-A", "2026-B", "2025-B", "2026-A"]) == [
            "2026-B", "2026-A", "2025-B", "2025-A",
        ]

    def test_lexicographic_order_is_chronological_across_years(self):
        """YYYY-L is fixed width, so no date lookup is needed."""
        assert ssm.orderCycleIDs(["2026-A", "2025-B"]) == ["2026-A", "2025-B"]

    def test_duplicates_collapse(self):
        """Stage 1 may write several entries sharing one cycleID."""
        assert ssm.orderCycleIDs(["2025-B", "2025-B", "2026-A"]) == ["2026-A", "2025-B"]

    def test_drops_the_no_cycle_sentinel(self):
        """snapred's Cycle.NO_CYCLE is 'unknown' and must not reach the UI."""
        assert ssm.orderCycleIDs(["2026-A", "unknown"]) == ["2026-A"]

    def test_drops_none_and_non_strings(self):
        assert ssm.orderCycleIDs(["2026-A", None, 2026, ""]) == ["2026-A"]

    @pytest.mark.parametrize("bad", ["2026-AB", "26-A", "2026-a", "2026A", "2026-", "-A"])
    def test_drops_malformed(self, bad):
        assert ssm.orderCycleIDs(["2026-A", bad]) == ["2026-A"]

    def test_empty_and_none_input(self):
        assert ssm.orderCycleIDs([]) == []
        assert ssm.orderCycleIDs(None) == []


# ═══════════════════════════════════════════════════════════════════════
# registeredCycles — driven with stand-in configs
# ═══════════════════════════════════════════════════════════════════════


def _config(cycleID):
    """An InstrumentConfig stand-in: only `.cycle.cycleID` is consulted."""
    cycle = None if cycleID is None else SimpleNamespace(cycleID=cycleID)
    return SimpleNamespace(cycle=cycle)


class _Service:
    """Stands in for LocalDataService over the two calls registeredCycles makes."""

    def __init__(self, byVersion, *, raiseOn=()):
        self._byVersion = byVersion
        self._raiseOn = set(raiseOn)

    def instrumentParameterIndexer(self):
        versions = sorted(self._byVersion)
        return SimpleNamespace(allVersions=lambda: versions)

    def readInstrumentParametersVersion(self, version):
        if version in self._raiseOn:
            raise RuntimeError(f"corrupt record at version {version}")
        return self._byVersion[version]


def _install(monkeypatch, service):
    monkeypatch.setattr(ssm, "LocalDataService", lambda: service)


class TestRegisteredCycles:

    def test_collects_distinct_cycles_most_recent_first(self, monkeypatch):
        _install(monkeypatch, _Service({
            0: _config(None),        # epoch entry, no cycle
            1: _config("2025-B"),
            2: _config("2026-A"),
            3: _config("2025-B"),    # same cycle, second epoch segment
        }))
        assert ssm.registeredCycles() == ["2026-A", "2025-B"]

    def test_epoch_entries_without_cycles_contribute_nothing(self, monkeypatch):
        """This is what makes a run outside every cycle read as out-of-cycle."""
        _install(monkeypatch, _Service({0: _config(None), 1: _config(None)}))
        assert ssm.registeredCycles() == []

    def test_empty_index(self, monkeypatch):
        _install(monkeypatch, _Service({}))
        assert ssm.registeredCycles() == []

    def test_one_unreadable_version_does_not_hide_the_rest(self, monkeypatch, capsys):
        _install(monkeypatch, _Service(
            {0: _config("2025-B"), 1: _config("2026-A"), 2: _config("2026-B")},
            raiseOn=(1,),
        ))
        assert ssm.registeredCycles() == ["2026-B", "2025-B"]
        assert "could not read version 1" in capsys.readouterr().out

    def test_sentinel_cycle_is_not_reported(self, monkeypatch):
        _install(monkeypatch, _Service({0: _config("unknown"), 1: _config("2026-A")}))
        assert ssm.registeredCycles() == ["2026-A"]


def test_degrades_to_empty_on_snapred_without_the_version_reader(monkeypatch):
    """snapred 2.3.1 has neither InstrumentConfig.cycle nor the version reader.

    Against it there are no cycles to report, and that must read as "none
    registered" rather than raising — the pin does not move until a release
    carries the cycle support.
    """

    class _Old:
        def instrumentParameterIndexer(self):
            return SimpleNamespace(allVersions=lambda: [0, 1])
        # deliberately no readInstrumentParametersVersion

    monkeypatch.setattr(ssm, "LocalDataService", lambda: _Old())
    assert ssm.registeredCycles() == []


def test_model_getCycleList_delegates_to_snapinstprm(monkeypatch):
    """The CalibrationManager dropdown must not read cycleDates any more."""

    from snapwrap.calibrationManager.model import CalibrationManagerModel

    monkeypatch.setattr(ssm, "registeredCycles", lambda: ["2026-B", "2026-A"])
    assert CalibrationManagerModel.getCycleList() == ["2026-B", "2026-A"]


def test_model_no_longer_imports_cycledates_loader():
    """Regression guard on the dependency being removed, not just unused."""

    from snapwrap.calibrationManager import model

    assert not hasattr(model, "load_cycle_data")
