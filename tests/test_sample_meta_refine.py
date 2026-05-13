"""Phase B4 tests: crystalSpecies.refine() skeleton.

Mantid is required (the species are seeded from CIF via from_cif).
Tests cover:
- Both refine paths (EOS-guided and blind sweep) return the expected dict keys.
- EOS-guided path produces a strain close to the theoretical value.
- Blind sweep path finds a consistent strain.
- Edge cases: no observed d, no valid cell, unsupported crystal system.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mantid")

from snapwrap.sampleMeta.utils import crystalSpecies
from snapwrap.sampleMeta.eos import EquationOfState

CIF_DIR = Path(__file__).parent / "_inspectrum" / "test_data"
TUNGSTEN_CIF = CIF_DIR / "EntryWithCollCode43421_tungsten.cif"

W_EOS = EquationOfState(
    eos_type="vinet",
    V_0=31.724,
    K_0=295.2,
    K_prime=4.32,
    source="Dewaele et al., PRB 70 094112 (2004)",
)

REQUIRED_RESULT_KEYS = {"strain", "path", "pressure_gpa", "unitCell_updated", "message"}


@pytest.fixture(scope="module")
def w_species_no_eos():
    return crystalSpecies.from_cif(TUNGSTEN_CIF)


@pytest.fixture(scope="module")
def w_species_with_eos():
    return crystalSpecies.from_cif(TUNGSTEN_CIF, role="calibrant", eos=W_EOS)


def _synthetic_obs_d(species, strain):
    """Shift all calculated d-spacings by a known strain factor."""
    import numpy as np

    a = species.unitCell.a
    ds = []
    for h in range(1, 5):
        for k in range(0, h + 1):
            for l in range(0, k + 1):
                hkl2 = h * h + k * k + l * l
                if hkl2 == 0:
                    continue
                ds.append(a / (hkl2 ** 0.5) * strain)
    return np.array(sorted(ds, reverse=True))


def test_refine_returns_required_keys(w_species_no_eos):
    obs = _synthetic_obs_d(w_species_no_eos, strain=0.98)
    result = w_species_no_eos.refine(obs)
    assert REQUIRED_RESULT_KEYS.issubset(result.keys())


def test_blind_sweep_path_label(w_species_no_eos):
    obs = _synthetic_obs_d(w_species_no_eos, strain=0.98)
    result = w_species_no_eos.refine(obs, pressure_gpa=None)
    assert result["path"] == "blind_sweep"
    assert result["unitCell_updated"] is True


def test_blind_sweep_recovers_strain(w_species_no_eos):
    """Blind sweep should recover a synthetic strain of 0.98 to ±1%."""
    true_strain = 0.98
    obs = _synthetic_obs_d(w_species_no_eos, strain=true_strain)
    result = w_species_no_eos.refine(obs)
    assert result["strain"] == pytest.approx(true_strain, abs=0.01)


def test_eos_guided_path_label(w_species_with_eos):
    obs = _synthetic_obs_d(w_species_with_eos, strain=0.98)
    result = w_species_with_eos.refine(obs, pressure_gpa=10.0)
    assert result["path"] == "eos_guided"
    assert result["unitCell_updated"] is True
    assert result["pressure_gpa"] == 10.0


def test_eos_guided_recovers_strain_near_theoretical(w_species_with_eos):
    """EOS-guided path on synthetic 10 GPa data should match EOS prediction."""
    from snapwrap.sampleMeta.eos import predicted_strain

    true_P = 10.0
    true_strain = predicted_strain(W_EOS, true_P)
    obs = _synthetic_obs_d(w_species_with_eos, strain=true_strain)
    result = w_species_with_eos.refine(obs, pressure_gpa=true_P)
    assert result["strain"] == pytest.approx(true_strain, abs=0.005)


def test_refine_no_data_returns_no_data_path(w_species_no_eos):
    result = w_species_no_eos.refine([])
    assert result["path"] == "no_data"
    assert result["unitCell_updated"] is False


def test_refine_unsupported_crystal_system():
    """A non-cubic species should raise NotImplementedError (Phase D TODO)."""
    ice_cif = CIF_DIR / "EntryWithCollCode211741_iceVII.cif"
    if not ice_cif.exists():
        pytest.skip("ice-VII CIF not available")
    sp = crystalSpecies.from_cif(ice_cif)
    # ice-VII is cubic too — make a monoclinic species manually
    sp_mono = crystalSpecies(
        spaceGroup="P 1 21/c 1",
        observedReflections=[],
        name="test_monoclinic",
    )
    # Inject a fake valid unit cell so we get past the early-exit checks.
    from snapwrap.sampleMeta.utils import unitCell
    sp_mono.unitCell = unitCell("monoclinic")
    sp_mono.unitCell.a = 5.0
    sp_mono.unitCell.b = 5.0
    sp_mono.unitCell.c = 5.0
    sp_mono.valid["unitCell"] = True

    import numpy as np
    obs = np.array([2.5, 2.0, 1.5])
    with pytest.raises(NotImplementedError, match="cubic"):
        sp_mono.refine(obs)


# ---------------------------------------------------------------------------
# Phase D tests: refine_species_from_workspace
# ---------------------------------------------------------------------------
# These tests do NOT require Mantid.  They build a synthetic workspace stub
# and call refine_species_from_workspace directly.
# ---------------------------------------------------------------------------


class _FakeWorkspace:
    """Minimal stub that mimics the Mantid Workspace2D interface."""

    def __init__(self, x, y, e, label="test_ws"):
        import numpy as np

        self._x = np.asarray(x, dtype=float)
        self._y = np.asarray(y, dtype=float)
        self._e = np.asarray(e, dtype=float)
        self._label = label

    def getNumberHistograms(self):
        return 1

    def readX(self, bank):
        return self._x

    def readY(self, bank):
        return self._y

    def readE(self, bank):
        return self._e

    def name(self):
        return self._label


def _make_synthetic_workspace(species, strain, n_bg=200, noise=0.5):
    """Build a fake d-spacing spectrum with peaks at strained positions.

    The spectrum has a flat background + Gaussian peaks placed at
    d-values predicted for the given strain factor.
    """
    import numpy as np

    a = species.unitCell.a * strain
    # Build a dense d-axis from 0.8 to 3.5 Å
    d = np.linspace(0.8, 3.5, 1000)
    y = np.full_like(d, 100.0)  # flat background

    # Inject Gaussian peaks for low-index hkl reflections
    for h in range(1, 6):
        for k in range(0, h + 1):
            for l in range(0, k + 1):
                if h == k == l == 0:
                    continue
                denom = h * h + k * k + l * l
                d_hkl = a / denom**0.5
                if d_hkl < 0.8 or d_hkl > 3.5:
                    continue
                sigma = 0.003 * d_hkl
                y = y + 5000.0 * np.exp(-0.5 * ((d - d_hkl) / sigma) ** 2)

    rng = np.random.default_rng(42)
    e = np.sqrt(np.abs(y)) + noise
    y = y + rng.normal(0, noise, size=len(y))

    return _FakeWorkspace(d, y, e, label="synthetic_tungsten")


@pytest.fixture(scope="module")
def w_species_for_bridge():
    """Tungsten crystalSpecies seeded from the real CIF (Mantid required)."""
    return crystalSpecies.from_cif(TUNGSTEN_CIF, role="calibrant", eos=W_EOS)


INSTPRM = CIF_DIR / "SNAP059056_all.instprm"


# D1 — RefinementReport structure ----------------------------------------


def test_refine_species_from_workspace_returns_report(w_species_for_bridge):
    from snapwrap.sampleMeta.refine import RefinementReport, refine_species_from_workspace

    ws = _make_synthetic_workspace(w_species_for_bridge, strain=1.0)
    report = refine_species_from_workspace(
        [w_species_for_bridge], ws, INSTPRM
    )
    assert isinstance(report, RefinementReport)


def test_report_has_species_list(w_species_for_bridge):
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    ws = _make_synthetic_workspace(w_species_for_bridge, strain=1.0)
    report = refine_species_from_workspace(
        [w_species_for_bridge], ws, INSTPRM
    )
    assert len(report.species) == 1
    assert report.species[0] is w_species_for_bridge


def test_report_to_dict_is_json_serialisable(w_species_for_bridge):
    import json

    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    ws = _make_synthetic_workspace(w_species_for_bridge, strain=1.0)
    report = refine_species_from_workspace(
        [w_species_for_bridge], ws, INSTPRM
    )
    d = report.to_dict()
    # Should round-trip through JSON without error.
    json.dumps(d)


# D2 — species mutation --------------------------------------------------


def test_refined_attribute_set_after_bridge(w_species_for_bridge):
    """After the bridge, crystalSpecies.refined contains the expected keys.

    The inspectrum engine is mocked so the test is deterministic and
    does not depend on peak-finding in a synthetic spectrum.
    """
    from unittest.mock import patch, MagicMock

    from snapwrap._inspectrum.lattice import LatticeRefinementResult
    from snapwrap._inspectrum.models import InspectionResult
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    # Build a fake InspectionResult that reports one successful refinement
    # for the tungsten phase.
    fake_ref = LatticeRefinementResult(
        phase_name=w_species_for_bridge.name,
        a=3.155, b=3.155, c=3.155,
        alpha=90.0, beta=90.0, gamma=90.0,
        pressure_gpa=5.0,
        residual_sum_sq=0.001,
        n_peaks_used=8,
        n_peaks_excluded=0,
        success=True,
    )
    fake_result = InspectionResult(
        refinements=[fake_ref],
        sweep_pressure_gpa=5.0,
    )

    w_species_for_bridge.refined = None
    ws = _make_synthetic_workspace(w_species_for_bridge, strain=0.995)

    with patch("snapwrap._inspectrum.engine.inspect", return_value=fake_result):
        refine_species_from_workspace([w_species_for_bridge], ws, INSTPRM)

    assert w_species_for_bridge.refined is not None
    for key in ("a", "b", "c", "alpha", "beta", "gamma", "pressure_gpa",
                "residual_sum_sq", "n_peaks_used", "success"):
        assert key in w_species_for_bridge.refined, f"missing key: {key}"
    assert w_species_for_bridge.refined["a"] == pytest.approx(3.155)
    assert w_species_for_bridge.refined["pressure_gpa"] == pytest.approx(5.0)


def test_refined_roundtrips_through_to_from_dict(w_species_for_bridge):
    """refined dict survives crystalSpecies.to_dict() / from_dict()."""
    from unittest.mock import patch

    from snapwrap._inspectrum.lattice import LatticeRefinementResult
    from snapwrap._inspectrum.models import InspectionResult
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    fake_ref = LatticeRefinementResult(
        phase_name=w_species_for_bridge.name,
        a=3.160, b=3.160, c=3.160,
        alpha=90.0, beta=90.0, gamma=90.0,
        pressure_gpa=0.0,
        residual_sum_sq=0.0005,
        n_peaks_used=10,
        success=True,
    )
    fake_result = InspectionResult(refinements=[fake_ref], sweep_pressure_gpa=0.0)

    w_species_for_bridge.refined = None
    ws = _make_synthetic_workspace(w_species_for_bridge, strain=1.0)

    with patch("snapwrap._inspectrum.engine.inspect", return_value=fake_result):
        refine_species_from_workspace([w_species_for_bridge], ws, INSTPRM)

    d = w_species_for_bridge.to_dict()
    assert "refined" in d

    sp2 = crystalSpecies.from_dict(d)
    assert sp2.refined == w_species_for_bridge.refined


# D3 — edge cases --------------------------------------------------------


def test_no_cif_path_returns_empty_report():
    """Species without cifPath → empty report with a warning."""
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    sp = crystalSpecies(
        spaceGroup="cubic",
        observedReflections=[],
        name="no_cif_species",
    )
    # Build a trivial fake workspace — it won't be used.
    import numpy as np
    ws = _FakeWorkspace(np.linspace(1, 3, 10), np.ones(10), np.ones(10))

    report = refine_species_from_workspace([sp], ws, INSTPRM)
    assert report.refinements == []
    assert "warning" in report.metadata


def test_missing_instprm_raises():
    """Non-existent instprm path → FileNotFoundError."""
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    import numpy as np
    ws = _FakeWorkspace(np.linspace(1, 3, 10), np.ones(10), np.ones(10))
    sp = crystalSpecies(spaceGroup="cubic", observedReflections=[], name="w")
    sp.cifPath = str(TUNGSTEN_CIF)

    with pytest.raises(FileNotFoundError):
        refine_species_from_workspace([sp], ws, "/nonexistent/path.instprm")


def test_bank_out_of_range_raises(w_species_for_bridge):
    """Requesting a bank beyond workspace size → ValueError."""
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    import numpy as np
    ws = _FakeWorkspace(np.linspace(1, 3, 10), np.ones(10), np.ones(10))

    with pytest.raises(ValueError, match="bank"):
        refine_species_from_workspace(
            [w_species_for_bridge], ws, INSTPRM, bank=5
        )


def test_bin_boundary_x_is_converted(w_species_for_bridge):
    """Workspace with n+1 X values (bin boundaries) should not raise."""
    from snapwrap.sampleMeta.refine import refine_species_from_workspace

    import numpy as np
    n = 100
    # bin boundaries: n+1 values
    x_bounds = np.linspace(0.8, 3.5, n + 1)
    y = np.ones(n) * 100.0
    e = np.ones(n) * 10.0
    ws = _FakeWorkspace(x_bounds, y, e)
    # Should not raise (bin boundary conversion is applied internally).
    report = refine_species_from_workspace([w_species_for_bridge], ws, INSTPRM)
    assert report is not None


# D4 — crystalSpecies.refined default ------------------------------------


def test_refined_default_is_none():
    """Newly constructed crystalSpecies.refined is None by default."""
    sp = crystalSpecies(spaceGroup="cubic", observedReflections=[], name="w")
    assert sp.refined is None


def test_refined_default_in_from_dict_legacy():
    """from_dict on a v1 dict (no 'refined' key) sets refined=None."""
    # Use a full species seeded from the real tungsten CIF so that the
    # spaceGroup round-trips cleanly through from_dict.
    sp = crystalSpecies.from_cif(TUNGSTEN_CIF, name="w_legacy")
    d = sp.to_dict()
    d.pop("refined", None)  # simulate a legacy v1 record
    sp2 = crystalSpecies.from_dict(d)
    assert sp2.refined is None
