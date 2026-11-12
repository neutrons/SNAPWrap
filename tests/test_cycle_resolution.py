"""Cycle resolution: SNAPRed's SNAPInstPrm first, wrap's cycleDates as fallback.

The fallback is temporary — it exists only because the pinned SNAPRed (2.3.1)
has no cycle support. These tests pin the three-way distinction that makes the
handover safe, so that deleting the fallback later is a visible change rather
than a silent one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from snapwrap import snapStateMgr as ssm


@pytest.fixture(autouse=True)
def _freshCycleCache():
    """wrap caches whether SNAPRed carries cycles; each test starts clean."""
    ssm.clearCycleCache()
    yield
    ssm.clearCycleCache()


def _redService(cycleID=None, *, missing=False, raises=False):
    """Stand in for SNAPRed's LocalDataService over the one call wrap makes."""

    class _Service:
        def getCycle(self, runNumber):
            if raises:
                raise RuntimeError("SNAPInstPrm unreadable")
            return SimpleNamespace(cycleID=cycleID)

    class _Old:
        pass  # SNAPRed 2.3.1: no getCycle at all

    return _Old() if missing else _Service()


def _install(monkeypatch, service, *, redHasCycles=False, wrapTable="2024-A"):
    monkeypatch.setattr(ssm, "LocalDataService", lambda: service)
    monkeypatch.setattr(
        ssm, "registeredCycles",
        lambda: ["2026-A"] if redHasCycles else [],
    )
    monkeypatch.setattr(ssm, "get_cycle_for_run", lambda runNumber: wrapTable)


# ═══════════════════════════════════════════════════════════════════════
# _cycleFromInstrumentParameters — the three-way distinction
# ═══════════════════════════════════════════════════════════════════════


class TestCycleFromInstrumentParameters:

    def test_real_cycle_is_authoritative(self, monkeypatch):
        _install(monkeypatch, _redService("2025-B"), redHasCycles=True)
        assert ssm._cycleFromInstrumentParameters(66600) == ("2025-B", True)

    def test_sentinel_with_registered_cycles_means_out_of_cycle(self, monkeypatch):
        """A real answer: the run falls outside every cycle entry."""
        _install(monkeypatch, _redService("unknown"), redHasCycles=True)
        assert ssm._cycleFromInstrumentParameters(66500) == (None, True)

    def test_sentinel_without_registered_cycles_means_no_data(self, monkeypatch):
        """Indistinguishable from out-of-cycle on SNAPRed's answer alone."""
        _install(monkeypatch, _redService("unknown"), redHasCycles=False)
        assert ssm._cycleFromInstrumentParameters(66500) == (None, False)

    def test_snapred_without_getcycle_is_not_authoritative(self, monkeypatch):
        _install(monkeypatch, _redService(missing=True))
        assert ssm._cycleFromInstrumentParameters(66500) == (None, False)

    def test_lookup_failure_is_not_authoritative(self, monkeypatch, capsys):
        _install(monkeypatch, _redService(raises=True), redHasCycles=True)
        assert ssm._cycleFromInstrumentParameters(66500) == (None, False)
        assert "cycle lookup failed" in capsys.readouterr().out

    def test_malformed_cycle_id_is_not_trusted(self, monkeypatch):
        _install(monkeypatch, _redService("26-A"), redHasCycles=False)
        assert ssm._cycleFromInstrumentParameters(66500) == (None, False)


# ═══════════════════════════════════════════════════════════════════════
# cycleForRun — when the fallback is and is not used
# ═══════════════════════════════════════════════════════════════════════


class TestCycleForRun:

    def test_snapred_answer_wins_over_the_wrap_table(self, monkeypatch):
        _install(monkeypatch, _redService("2025-B"), redHasCycles=True,
                 wrapTable="2024-A")
        assert ssm.cycleForRun(66600) == "2025-B"

    def test_authoritative_out_of_cycle_does_not_consult_the_wrap_table(self, monkeypatch):
        """Once SNAPRed carries cycles its "no cycle" is the answer."""
        _install(monkeypatch, _redService("unknown"), redHasCycles=True,
                 wrapTable="2024-A")
        assert ssm.cycleForRun(66500) is None

    def test_falls_back_when_snapred_has_no_cycle_data(self, monkeypatch):
        _install(monkeypatch, _redService(missing=True), wrapTable="2024-A")
        assert ssm.cycleForRun(61500) == "2024-A"

    def test_falls_back_when_no_cycles_registered_yet(self, monkeypatch):
        """Today's state in every deployed environment."""
        _install(monkeypatch, _redService("unknown"), redHasCycles=False,
                 wrapTable="2025-A")
        assert ssm.cycleForRun(64000) == "2025-A"

    def test_silent_suppresses_the_out_of_cycle_message(self, monkeypatch, capsys):
        _install(monkeypatch, _redService("unknown"), redHasCycles=True)
        ssm.cycleForRun(66500, silent=True)
        assert capsys.readouterr().out == ""

    def test_not_silent_reports_out_of_cycle(self, monkeypatch, capsys):
        _install(monkeypatch, _redService("unknown"), redHasCycles=True)
        ssm.cycleForRun(66500)
        assert "no registered cycle" in capsys.readouterr().out

    def test_silent_suppresses_the_fallback_message(self, monkeypatch, capsys):
        """The per-entry annotation loop must not print once per entry."""
        _install(monkeypatch, _redService(missing=True), wrapTable=None)

        assert ssm.cycleForRun(1, silent=True) is None
        assert capsys.readouterr().out == ""

        assert ssm.cycleForRun(1, silent=False) is None
        assert "no cycle found" in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════
# the cache
# ═══════════════════════════════════════════════════════════════════════


def test_registered_cycles_is_cached_then_cleared(monkeypatch):
    """wrap resolves a cycle per index entry; this must not re-read each time."""

    calls = {"n": 0}

    def _counting():
        calls["n"] += 1
        return ["2026-A"]

    monkeypatch.setattr(ssm, "LocalDataService", lambda: _redService("unknown"))
    monkeypatch.setattr(ssm, "registeredCycles", _counting)

    for _ in range(5):
        ssm._cycleFromInstrumentParameters(66500)
    assert calls["n"] == 1

    ssm.clearCycleCache()
    ssm._cycleFromInstrumentParameters(66500)
    assert calls["n"] == 2
