"""
Equation of state (EOS) evaluation for high-pressure crystallography.

Provides forward evaluation P → V/V₀ for Birch-Murnaghan 3rd-order
and Vinet equations.  Used by the peak-matching pipeline to predict
the volumetric strain of a phase at a given pressure, which narrows
the search window for lattice parameter estimation.

Supported EOS types:
- ``birch-murnaghan`` (3rd order)
- ``vinet`` (universal EOS)
- ``murnaghan`` (isothermal first-order)

Example:
    >>> from snapwrap._inspectrum.models import EquationOfState
    >>> eos = EquationOfState(
    ...     eos_type="vinet", order=3,
    ...     V_0=31.724, K_0=295.2, K_prime=4.32, source="test",
    ... )
    >>> volume_ratio(eos, pressure=10.0)  # V/V₀ at 10 GPa
    0.9888...
    >>> predicted_strain(eos, pressure=10.0)  # (V/V₀)^(1/3)
    0.9962...
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

from snapwrap._inspectrum.models import EquationOfState


def _pressure_birch_murnaghan(v_ratio: float, K_0: float, K_prime: float) -> float:
    """Birch-Murnaghan 3rd-order: P as a function of V/V₀.

    Args:
        v_ratio: Volume ratio V/V₀ (dimensionless, < 1 under compression).
        K_0: Bulk modulus at zero pressure (GPa).
        K_prime: Pressure derivative of bulk modulus (dimensionless).

    Returns:
        Pressure in GPa.
    """
    # Eulerian finite strain f = [(V₀/V)^(2/3) - 1] / 2
    f = 0.5 * (v_ratio ** (-2.0 / 3.0) - 1.0)
    return 3.0 * K_0 * f * (1.0 + 2.0 * f) ** 2.5 * (1.0 + 1.5 * (K_prime - 4.0) * f)


def _pressure_vinet(v_ratio: float, K_0: float, K_prime: float) -> float:
    """Vinet universal EOS: P as a function of V/V₀.

    Args:
        v_ratio: Volume ratio V/V₀ (dimensionless).
        K_0: Bulk modulus at zero pressure (GPa).
        K_prime: Pressure derivative of bulk modulus (dimensionless).

    Returns:
        Pressure in GPa.
    """
    eta = v_ratio ** (1.0 / 3.0)  # linear strain ratio
    return (
        3.0 * K_0 * (1.0 - eta) / eta**2 * np.exp(1.5 * (K_prime - 1.0) * (1.0 - eta))
    )


def _pressure_murnaghan(v_ratio: float, K_0: float, K_prime: float) -> float:
    """Murnaghan isothermal EOS: P as a function of V/V₀.

    Args:
        v_ratio: Volume ratio V/V₀ (dimensionless).
        K_0: Bulk modulus at zero pressure (GPa).
        K_prime: Pressure derivative of bulk modulus (dimensionless).

    Returns:
        Pressure in GPa.
    """
    return (K_0 / K_prime) * (v_ratio ** (-K_prime) - 1.0)


_EOS_FUNCTIONS = {
    "birch-murnaghan": _pressure_birch_murnaghan,
    "vinet": _pressure_vinet,
    "murnaghan": _pressure_murnaghan,
}


def pressure_at(eos: EquationOfState, v_ratio: float) -> float:
    """Evaluate EOS: compute pressure for a given V/V₀.

    Args:
        eos: Equation of state parameters.
        v_ratio: Volume ratio V/V₀ (0 < v_ratio ≤ 1 for compression).

    Returns:
        Pressure in GPa.

    Raises:
        ValueError: If ``v_ratio`` is non-positive or EOS type is unknown.
    """
    if v_ratio <= 0:
        raise ValueError(f"v_ratio must be positive, got {v_ratio}")
    fn = _EOS_FUNCTIONS.get(eos.eos_type)
    if fn is None:
        raise ValueError(
            f"Unknown EOS type {eos.eos_type!r}. "
            f"Supported: {sorted(_EOS_FUNCTIONS)}"
        )
    return fn(v_ratio, eos.K_0, eos.K_prime)


def volume_ratio(
    eos: EquationOfState,
    pressure: float,
    v_ratio_bounds: tuple[float, float] = (0.5, 1.0),
) -> float:
    """Solve EOS for V/V₀ at a given pressure.

    Uses Brent's method to find the volume ratio that yields the
    target pressure.  Works for any monotonically decreasing P(V/V₀).

    Args:
        eos: Equation of state parameters.
        pressure: Target pressure (GPa).  Must be ≥ 0.
        v_ratio_bounds: Search interval for V/V₀.  Default (0.5, 1.0)
            covers compressions up to 50%.

    Returns:
        Volume ratio V/V₀ (dimensionless).

    Raises:
        ValueError: If pressure is negative, or root is not bracketed.
    """
    if pressure < 0:
        raise ValueError(f"Pressure must be non-negative, got {pressure}")

    # At P = 0, V/V₀ = 1 exactly
    if pressure == 0:
        return 1.0

    lo, hi = v_ratio_bounds

    def residual(vr: float) -> float:
        return pressure_at(eos, vr) - pressure

    # Verify bracket
    f_lo = residual(lo)
    f_hi = residual(hi)
    if f_lo * f_hi > 0:
        raise ValueError(
            f"Root not bracketed in [{lo}, {hi}]: "
            f"P({lo})={f_lo + pressure:.2f}, P({hi})={f_hi + pressure:.2f} GPa. "
            f"Try widening v_ratio_bounds."
        )

    return brentq(residual, lo, hi, xtol=1e-12, rtol=1e-12)


def predicted_strain(
    eos: EquationOfState,
    pressure: float,
    v_ratio_bounds: tuple[float, float] = (0.5, 1.0),
) -> float:
    """Predict the isotropic linear strain at a given pressure.

    Strain is defined as s = (V/V₀)^(1/3), so that the d-spacing
    of every reflection scales as d_obs ≈ s × d_calc.

    Args:
        eos: Equation of state parameters.
        pressure: Target pressure (GPa).  Must be ≥ 0.
        v_ratio_bounds: Search interval for V/V₀.

    Returns:
        Linear strain factor s (dimensionless, < 1 for compression).
    """
    vr = volume_ratio(eos, pressure, v_ratio_bounds)
    return vr ** (1.0 / 3.0)
