"""
Crystallographic calculations for snapwrap._inspectrum.

Provides reflection generation, d-spacing calculation, multiplicity
determination, and neutron structure factor computation.  Uses cryspy
for low-level crystallographic math and neutron scattering lengths.

Typical usage::

    from snapwrap._inspectrum.crystallography import generate_reflections
    from snapwrap._inspectrum.loaders import load_cif

    phase = load_cif("tungsten.cif")
    reflections = generate_reflections(phase, d_min=0.5, d_max=3.0)
    for r in reflections:
        print(r["hkl"], r["d"], r["multiplicity"], r["F_sq"])
"""

from __future__ import annotations

from typing import Any

import cryspy
import numpy as np

from snapwrap._inspectrum.models import CrystalPhase

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_reflections(
    phase: CrystalPhase,
    d_min: float,
    d_max: float,
) -> list[dict[str, Any]]:
    """Generate allowed reflections for *phase* in the d-spacing range.

    For each unique reflection the returned dict contains:

    - ``hkl``: tuple (h, k, l)
    - ``d``: d-spacing in Angstroms
    - ``multiplicity``: number of symmetry-equivalent reflections
    - ``F_sq``: neutron structure factor |F(hkl)|²

    Reflections are sorted by decreasing d-spacing (lowest-angle first).

    Args:
        phase: Crystal phase with lattice parameters, space group, and
            atom sites populated (e.g. from :func:`load_cif`).
        d_min: Minimum d-spacing (Å).
        d_max: Maximum d-spacing (Å).

    Returns:
        List of reflection dicts, sorted by decreasing d.

    Raises:
        ValueError: If d_min >= d_max or lattice parameters are invalid.
    """
    if d_min >= d_max:
        raise ValueError(f"d_min ({d_min}) must be less than d_max ({d_max})")

    centering = _extract_centering(phase.space_group)

    # Upper bound on Miller index from the smallest d-spacing
    a_max = max(phase.a, phase.b, phase.c)
    h_max = int(np.ceil(a_max / d_min)) + 1

    # Convert angles to radians once
    al = np.radians(phase.alpha)
    be = np.radians(phase.beta)
    ga = np.radians(phase.gamma)

    reflections: list[dict[str, Any]] = []

    for h in range(0, h_max + 1):
        for k in range(0, h_max + 1):
            for l_idx in range(0, h_max + 1):
                if h == 0 and k == 0 and l_idx == 0:
                    continue

                # Lattice centering systematic absences
                if not _passes_centering(h, k, l_idx, centering):
                    continue

                inv_d = cryspy.calc_inverse_d_by_hkl_abc_angles(
                    h,
                    k,
                    l_idx,
                    phase.a,
                    phase.b,
                    phase.c,
                    al,
                    be,
                    ga,
                )
                if inv_d <= 0:
                    continue

                d = 1.0 / inv_d
                if d < d_min or d > d_max:
                    continue

                mult = _multiplicity(h, k, l_idx, phase.space_group_number)
                f_sq = _calc_structure_factor_sq(
                    h,
                    k,
                    l_idx,
                    d,
                    phase,
                )

                reflections.append(
                    {
                        "hkl": (h, k, l_idx),
                        "d": d,
                        "multiplicity": mult,
                        "F_sq": f_sq,
                    }
                )

    # Sort by decreasing d-spacing
    reflections.sort(key=lambda r: -r["d"])

    # Remove near-duplicate d-spacings (symmetry-equivalent reflections
    # that we enumerated separately because we loop over all positive hkl).
    reflections = _merge_equivalent_reflections(reflections)

    return reflections


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_centering(space_group: str) -> str:
    """Return the lattice centering letter from a Hermann-Mauguin symbol.

    Examples:
        "I m -3 m" → "I"
        "P n -3 m" → "P"
        "F m -3 m" → "F"
        "C 2/m"    → "C"
    """
    sg = space_group.strip()
    if sg:
        return sg[0].upper()
    return "P"


def _passes_centering(h: int, k: int, l_val: int, centering: str) -> bool:
    """Check if (h, k, l) passes the lattice centering condition.

    Centering conditions (integral reflection conditions):

    - P: no condition
    - I: h + k + l = 2n
    - F: h, k, l all even or all odd
    - A: k + l = 2n
    - B: h + l = 2n
    - C: h + k = 2n
    - R (hexagonal axes): -h + k + l = 3n
    """
    if centering == "P":
        return True
    elif centering == "I":
        return (h + k + l_val) % 2 == 0
    elif centering == "F":
        # All even or all odd
        parities = (h % 2, k % 2, l_val % 2)
        return parities[0] == parities[1] == parities[2]
    elif centering == "A":
        return (k + l_val) % 2 == 0
    elif centering == "B":
        return (h + l_val) % 2 == 0
    elif centering == "C":
        return (h + k) % 2 == 0
    elif centering == "R":
        return (-h + k + l_val) % 3 == 0
    else:
        # Unknown centering — allow everything
        return True


def _multiplicity(h: int, k: int, l_val: int, sg_number: int) -> int:
    """Estimate reflection multiplicity from the Laue class.

    Uses the International Tables space group number to determine the
    crystal system and point group, then counts the number of
    symmetry-equivalent (h, k, l) reflections.

    This is an approximation — it uses the *Laue class* multiplicity
    (which is correct for powder diffraction where Friedel's law
    applies).
    """
    crystal_system = cryspy.get_crystal_system_by_it_number(sg_number)
    return _laue_multiplicity(h, k, l_val, crystal_system, sg_number)


def _laue_multiplicity(
    h: int, k: int, l_val: int, crystal_system: str, sg_number: int
) -> int:
    """Count equivalent reflections for the Laue class.

    For powder diffraction the multiplicity is the number of
    reflections that overlap at the same d-spacing.
    """
    # Generate all permutations and sign changes, count unique
    equivalents: set[tuple[int, int, int]] = set()

    if crystal_system == "cubic":
        _cubic_equivalents(h, k, l_val, equivalents)
    elif crystal_system == "hexagonal" or crystal_system == "trigonal":
        _hexagonal_equivalents(h, k, l_val, equivalents)
    elif crystal_system == "tetragonal":
        _tetragonal_equivalents(h, k, l_val, equivalents)
    elif crystal_system == "orthorhombic":
        _orthorhombic_equivalents(h, k, l_val, equivalents)
    elif crystal_system == "monoclinic":
        _monoclinic_equivalents(h, k, l_val, equivalents)
    elif crystal_system == "triclinic":
        _triclinic_equivalents(h, k, l_val, equivalents)
    else:
        _triclinic_equivalents(h, k, l_val, equivalents)

    return len(equivalents)


def _add_sign_permutations(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """Add all sign combinations of (±h, ±k, ±l)."""
    for sh in (1, -1):
        for sk in (1, -1):
            for sl in (1, -1):
                equivalents.add((sh * h, sk * k, sl * l_val))


def _cubic_equivalents(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """All permutations of indices with all sign combinations (m-3m)."""
    from itertools import permutations

    for perm in set(permutations((h, k, l_val))):
        _add_sign_permutations(perm[0], perm[1], perm[2], equivalents)


def _hexagonal_equivalents(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """Equivalents for hexagonal Laue class 6/mmm."""
    i = -(h + k)
    # The 12 in-plane operations on (h, k, i) keeping l sign
    hex_perms = [
        (h, k),
        (k, i),
        (i, h),
        (-h, -k),
        (-k, -i),
        (-i, -h),
        (k, h),
        (h, i),
        (i, k),
        (-k, -h),
        (-h, -i),
        (-i, -k),
    ]
    for hh, kk in hex_perms:
        equivalents.add((hh, kk, l_val))
        equivalents.add((hh, kk, -l_val))


def _tetragonal_equivalents(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """Equivalents for tetragonal Laue class 4/mmm."""
    perms_hk = [(h, k), (-h, -k), (-k, h), (k, -h), (k, h), (-k, -h), (h, -k), (-h, k)]
    for hh, kk in perms_hk:
        equivalents.add((hh, kk, l_val))
        equivalents.add((hh, kk, -l_val))


def _orthorhombic_equivalents(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """Equivalents for orthorhombic Laue class mmm."""
    _add_sign_permutations(h, k, l_val, equivalents)


def _monoclinic_equivalents(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """Equivalents for monoclinic Laue class 2/m (unique axis b)."""
    equivalents.add((h, k, l_val))
    equivalents.add((-h, k, -l_val))
    equivalents.add((-h, -k, -l_val))
    equivalents.add((h, -k, l_val))


def _triclinic_equivalents(
    h: int, k: int, l_val: int, equivalents: set[tuple[int, int, int]]
) -> None:
    """Equivalents for triclinic Laue class -1."""
    equivalents.add((h, k, l_val))
    equivalents.add((-h, -k, -l_val))


def _calc_structure_factor_sq(
    h: int,
    k: int,
    l_val: int,
    d: float,
    phase: CrystalPhase,
) -> float:
    """Calculate |F(hkl)|² for neutron scattering.

    Uses the kinematic approximation::

        F(hkl) = Σ_j  b_j · occ_j · T_j · exp(2πi(h·x_j + k·y_j + l·z_j))

    where the sum runs over **all** symmetry-equivalent positions in the
    unit cell (not just the asymmetric unit).

    When the CIF-derived symmetry operations (``phase.symops``) are
    available, each asymmetric-unit site is expanded to all its
    equivalent positions using :func:`expand_position`.  This gives
    correct |F|² for any structure.

    If ``phase.symops`` is empty (legacy path), a centering-only fallback
    is used — correct only for simple structures where all atoms sit on
    special positions of maximum symmetry.
    """
    if not phase.atom_sites:
        return 1.0

    sthovl = 0.5 / d  # sin(θ)/λ = 1/(2d)
    use_symops = len(phase.symops) > 0
    centering = _extract_centering(phase.space_group)
    centering_vectors = _CENTERING_VECTORS.get(centering, [(0.0, 0.0, 0.0)])

    F = 0.0 + 0.0j
    hkl_vec = np.array([h, k, l_val], dtype=float)

    for site in phase.atom_sites:
        symbol = _extract_element(site.get("type_symbol", site.get("label", "")))
        try:
            b = cryspy.get_scat_length_neutron(symbol)
        except (KeyError, ValueError):
            b = 0.5 + 0j  # fallback

        occ = float(_parse_cif_number(str(site.get("occupancy", 1.0))))

        x = float(_parse_cif_number(str(site.get("fract_x", 0.0))))
        y = float(_parse_cif_number(str(site.get("fract_y", 0.0))))
        z = float(_parse_cif_number(str(site.get("fract_z", 0.0))))

        # Isotropic Debye-Waller factor
        b_iso_str = site.get("B_iso_or_equiv", site.get("b_iso_or_equiv", "."))
        u_iso_str = site.get("U_iso_or_equiv", site.get("u_iso_or_equiv", "."))
        b_iso = 0.0
        if b_iso_str not in (".", "", None):
            b_iso = float(_parse_cif_number(str(b_iso_str)))
        elif u_iso_str not in (".", "", None):
            u_iso = float(_parse_cif_number(str(u_iso_str)))
            b_iso = 8 * np.pi**2 * u_iso
        dw = np.exp(-b_iso * sthovl**2)

        if use_symops:
            # Full symmetry expansion — correct for all structures
            pos = np.array([x, y, z])
            equiv_positions = expand_position(pos, phase.symops)
            for ep in equiv_positions:
                phase_angle = 2 * np.pi * np.dot(hkl_vec, ep)
                F += complex(b) * occ * dw * np.exp(1j * phase_angle)
        else:
            # Legacy centering-only fallback
            for tx, ty, tz in centering_vectors:
                xc = x + tx
                yc = y + ty
                zc = z + tz
                phase_angle = 2 * np.pi * (h * xc + k * yc + l_val * zc)
                F += complex(b) * occ * dw * np.exp(1j * phase_angle)

    return float(abs(F) ** 2)


def _extract_element(type_symbol: str) -> str:
    """Extract the element symbol from a CIF type_symbol.

    Handles cases like "W", "O2-", "H1+", "Fe3+", "W0+".
    """
    # Take the alphabetic prefix
    element = ""
    for char in type_symbol:
        if char.isalpha():
            element += char
        else:
            break
    return element if element else type_symbol


def _parse_cif_number(value_str: str) -> float:
    """Parse a CIF numeric value, stripping uncertainty in parentheses.

    Examples:
        "3.16475(20)" → 3.16475
        "0.202(3)"    → 0.202
        "90."         → 90.0
        "0"           → 0.0
    """
    s = str(value_str).strip()
    paren = s.find("(")
    if paren != -1:
        s = s[:paren]
    return float(s)


# Centering translation vectors for each Bravais lattice type
_CENTERING_VECTORS: dict[str, list[tuple[float, float, float]]] = {
    "P": [(0.0, 0.0, 0.0)],
    "I": [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5)],
    "F": [
        (0.0, 0.0, 0.0),
        (0.5, 0.5, 0.0),
        (0.5, 0.0, 0.5),
        (0.0, 0.5, 0.5),
    ],
    "A": [(0.0, 0.0, 0.0), (0.0, 0.5, 0.5)],
    "B": [(0.0, 0.0, 0.0), (0.5, 0.0, 0.5)],
    "C": [(0.0, 0.0, 0.0), (0.5, 0.5, 0.0)],
    "R": [(0.0, 0.0, 0.0), (2 / 3, 1 / 3, 1 / 3), (1 / 3, 2 / 3, 2 / 3)],
}


def parse_symop(symop_str: str) -> tuple[np.ndarray, np.ndarray]:
    """Parse a CIF symmetry operation string into rotation + translation.

    Handles standard CIF ``_space_group_symop_operation_xyz`` format,
    e.g. ``'-y, x+1/2, z+1/2'``.

    Args:
        symop_str: Symmetry operation as comma-separated xyz expression.

    Returns:
        Tuple of (3×3 rotation matrix, 3-vector translation), both as
        numpy arrays.  Rotation is integer-valued (±1, 0), translation
        is fractional.

    Example:
        >>> rot, trans = parse_symop('-y, x+1/2, z+1/2')
        >>> rot   # [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        >>> trans  # [0.0, 0.5, 0.5]
    """
    rot = np.zeros((3, 3), dtype=float)
    trans = np.zeros(3, dtype=float)
    var_map = {"x": 0, "y": 1, "z": 2}

    parts = [p.strip() for p in symop_str.split(",")]
    for row, part in enumerate(parts):
        part = part.replace(" ", "")
        i = 0
        sign = 1
        while i < len(part):
            ch = part[i]
            if ch == "+":
                sign = 1
                i += 1
            elif ch == "-":
                sign = -1
                i += 1
            elif ch in var_map:
                rot[row, var_map[ch]] = sign
                sign = 1  # reset default to positive
                i += 1
            elif ch.isdigit():
                num_str = ch
                i += 1
                while i < len(part) and (part[i].isdigit() or part[i] == "/"):
                    num_str += part[i]
                    i += 1
                if "/" in num_str:
                    num, den = num_str.split("/")
                    trans[row] += sign * int(num) / int(den)
                else:
                    trans[row] += sign * int(num_str)
                sign = 1
            else:
                i += 1
    return rot, trans


def expand_position(
    pos: np.ndarray,
    symops: list[tuple[np.ndarray, np.ndarray]],
    tol: float = 1e-5,
) -> np.ndarray:
    """Apply symmetry operations to expand one position to all equivalents.

    Takes a fractional coordinate from the asymmetric unit and applies
    every symmetry operation, returning the unique positions in [0, 1).

    Args:
        pos: Fractional coordinate (3-vector).
        symops: List of (rotation, translation) tuples from
            :func:`parse_symop`.
        tol: Tolerance for considering two positions identical.

    Returns:
        Array of shape (N, 3) with unique equivalent positions.
    """
    all_pos = []
    for rot, trans in symops:
        new_pos = rot @ pos + trans
        new_pos = new_pos % 1.0
        # Snap values very close to 1.0 back to 0.0
        new_pos[new_pos > 1.0 - tol] = 0.0
        all_pos.append(new_pos)

    # Deduplicate — O(n²) but n ≤ 192 for even the largest space groups
    unique = [all_pos[0]]
    for p in all_pos[1:]:
        is_dup = False
        for u in unique:
            diff = np.abs(p - u)
            diff = np.minimum(diff, 1.0 - diff)  # periodic boundary
            if np.all(diff < tol):
                is_dup = True
                break
        if not is_dup:
            unique.append(p)
    return np.array(unique)


def _merge_equivalent_reflections(
    reflections: list[dict[str, Any]],
    d_tolerance: float = 1e-6,
) -> list[dict[str, Any]]:
    """Merge reflections with the same d-spacing (within tolerance).

    When we loop over all positive (h, k, l) we may generate
    symmetry-equivalent reflections separately (e.g. (2,1,0) and
    (2,0,1) for cubic).  This function merges them, keeping the
    first hkl tuple as representative and summing nothing (they
    have the same d, F_sq, and multiplicity by construction).
    """
    if not reflections:
        return reflections

    merged: list[dict[str, Any]] = [reflections[0]]
    for r in reflections[1:]:
        if abs(r["d"] - merged[-1]["d"]) < d_tolerance:
            # Same d-spacing — skip duplicate
            continue
        merged.append(r)
    return merged
