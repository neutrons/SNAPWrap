"""EOS utilities for high-pressure crystallography.

This is a thin re-export of the equation-of-state machinery vendored in
``snapwrap._inspectrum``.  All snapwrap-native code should import from here
rather than from ``_inspectrum`` directly — that way, when the absorption
plan bucket-1 migration moves these modules into ``snapwrap.sampleMeta``,
only this file changes.

Public surface
--------------
``EquationOfState``
    Dataclass holding EOS type + Birch-Murnaghan / Vinet / Murnaghan
    parameters.  Stored on ``crystalSpecies.eos`` and round-trips through
    ``crystalSpecies.to_dict`` / ``from_dict``.

``pressure_at(eos, v_ratio)``
    Forward evaluation: pressure (GPa) at a given volume ratio V/V₀.

``predicted_strain(eos, pressure)``
    Inverse path (EOS + Brent's method): linear strain (V/V₀)^(1/3) at a
    given pressure.  Used by the refinement bridge to narrow the d-spacing
    search window.

``volume_ratio(eos, pressure)``
    Intermediate step of ``predicted_strain``; exposed for completeness and
    direct use in lattice-parameter work.

``sweep_strain(obs_d, obs_heights, obs_fwhm, reflections, tolerance, ...)``
    Blind two-pass strain search.  Falls back to this when no EOS is
    available (Phase B4 / ``crystalSpecies.refine`` failure mode).
"""

from __future__ import annotations

from snapwrap._inspectrum.models import EquationOfState
from snapwrap._inspectrum.eos import (
    pressure_at,
    predicted_strain,
    volume_ratio,
)
from snapwrap._inspectrum.matching import sweep_strain

__all__ = [
    "EquationOfState",
    "pressure_at",
    "predicted_strain",
    "volume_ratio",
    "sweep_strain",
]
