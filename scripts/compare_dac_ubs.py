"""Compare UBs produced by build_swiss_cheese_from_run against manually-made
SNAP68713UB1.mat / SNAP68713UB2.mat.

Usage (from repo root):
    pixi run python scripts/compare_ubs_68713.py

What it does
------------
1. Runs the full ``build_swiss_cheese_from_run`` pipeline on SNAP run 68713.
2. Loads the 3×3 UB matrix (top block) from each of the two output .mat files.
3. Loads the same block from the manually-made reference files.
4. For each crystal index, finds the best permutation of new vs reference
   (crystal labelling order may differ) and reports the residual.

A residual below ~1e-4 Å⁻¹ per element means the UBs are equivalent within
rounding and the pipeline is working correctly.
"""

from __future__ import annotations

import numpy as np
import json
from pathlib import Path
import tempfile
import sys

REFERENCE_DIR = Path("/SNS/SNAP/IPTS-33219/shared")
RUN = 65891
IPTS = 33219
NEXUS = Path(f"/SNS/SNAP/IPTS-{IPTS}/nexus/SNAP_{RUN}.nxs.h5")


def read_ub_matrix(mat_path: Path) -> np.ndarray:
    """Parse the 3x3 UB matrix from an ISAW-format .mat file.

    ISAW .mat format: first 3 non-empty lines each contain 3 floats (the
    *transpose* of the UB matrix), followed by a lattice parameters line.
    We return U·B (not its transpose) to be consistent with Mantid's
    convention.
    """
    rows: list[list[float]] = []
    with mat_path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("The"):
                continue
            parts = stripped.split()
            if len(parts) == 3:
                try:
                    rows.append([float(x) for x in parts])
                except ValueError:
                    continue
            if len(rows) == 3:
                break
    ub_T = np.array(rows)        # shape (3,3) — this is (UB)^T per ISAW header
    return ub_T.T                # return UB


def lattice_params(ub: np.ndarray) -> np.ndarray:
    """Return (a*, b*, c*) — the column norms of UB (reciprocal axis lengths).

    For a cubic crystal all three should be equal to 1/a.
    """
    return np.linalg.norm(ub, axis=0)  # shape (3,)


def beam_parallelism(ub: np.ndarray) -> tuple[float, int]:
    """Angle (degrees) between the most beam-aligned reciprocal axis and the beam (z = [0,0,1]).

    Matches the convention in ``UBStandardOrient``: each axis unit vector is
    ``UB @ e_i / |UB @ e_i|`` and its z-component gives the cosine of the
    angle with the beam.  Pass ``pk.UBList[i-1]`` (before any disk roundtrip)
    to get correct results.

    Returns (angle_deg, column_index).  0° = axis parallel to beam (maximum
    notches); 90° = perpendicular (minimum notches).
    """
    beam = np.array([0.0, 0.0, 1.0])
    col_norms = np.linalg.norm(ub, axis=0)
    dots = np.abs(ub.T @ beam) / col_norms          # cosines, shape (3,)
    best = int(np.argmax(dots))
    angle_deg = float(np.degrees(np.arccos(np.clip(dots[best], -1.0, 1.0))))
    return angle_deg, best


def metric_tensor(ub: np.ndarray) -> np.ndarray:
    """Return G* = UB^T @ UB — the reciprocal-space metric tensor.

    Eigenvalues of G* are invariant to choice of unit-cell orientation, so
    two UBs representing the same crystal will have identical eigenvalue sets
    even if their columns are permuted or sign-flipped.
    """
    return ub.T @ ub


def eigenvalue_residual(ub1: np.ndarray, ub2: np.ndarray) -> float:
    """Max absolute difference between sorted eigenvalues of G* for two UBs."""
    ev1 = np.sort(np.linalg.eigvalsh(metric_tensor(ub1)))
    ev2 = np.sort(np.linalg.eigvalsh(metric_tensor(ub2)))
    return float(np.abs(ev1 - ev2).max())


def best_match_residual(
    new_ubs: list[np.ndarray], ref_ubs: list[np.ndarray]
) -> tuple[float, list[int]]:
    """Find permutation of new_ubs that minimises max eigenvalue residual.

    Returns (max_eigenvalue_residual, best_permutation).
    """
    from itertools import permutations

    best_resid = np.inf
    best_perm = list(range(len(new_ubs)))
    for perm in permutations(range(len(new_ubs))):
        resid = max(
            eigenvalue_residual(new_ubs[perm[i]], ref_ubs[i])
            for i in range(len(ref_ubs))
        )
        if resid < best_resid:
            best_resid = resid
            best_perm = list(perm)
    return best_resid, best_perm


def main() -> None:
    if not NEXUS.exists():
        sys.exit(f"Nexus file not found: {NEXUS}")

    ref_ub_paths = sorted(REFERENCE_DIR.glob(f"SNAP{RUN}UB*.mat"))
    if not ref_ub_paths:
        sys.exit(f"No reference UBs found in {REFERENCE_DIR}")

    print(f"Reference UBs: {[p.name for p in ref_ub_paths]}")
    ref_ubs = [read_ub_matrix(p) for p in ref_ub_paths]

    with tempfile.TemporaryDirectory(prefix="snapwrap_compare_") as tmpdir:
        out_dir = Path(tmpdir) / "output"
        ub_dir = out_dir / "ubs"
        ub_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nRunning pipeline on SNAP_{RUN} (IPTS-{IPTS}) …")

        import numpy as np
        from snapwrap import diamondUB as _dub
        from snapwrap.maskUtils import swissCheese

        peaks_ws_name, _ = _dub.generatePeaksWorkspace(RUN, ipts=IPTS, dens_thresh=400)
        pk = _dub.peakInfo(peaks_ws_name)
        pk.ipts = IPTS
        pk.runNumber = RUN
        _dub.findDiamUB(pk)

        # Capture in-memory UBs immediately after standardisation.
        # These are used for beam-parallelism angles so we avoid any
        # row-reordering that Mantid's SetUB / SaveIsawUB may introduce.
        pipeline_ubs = [ub.copy() for ub in pk.UBList]

        # Indexing stats — read directly off pk before it goes out of scope
        n_crystal = {
            cid: int(np.sum(pk.crystalID == cid))
            for cid in range(1, len(pk.UBList) + 1)
        }
        n_indexed = sum(n_crystal.values())
        n_diamond = int(pk.totalDiamondReflections)
        n_total   = int(pk.npk)

        ub_paths = []
        for i in range(1, 3):
            p = ub_dir / f"SNAP{RUN}UB{i}.mat"
            pk.CreatePeaksWSAndSave(i, p)
            ub_paths.append(p)

        sc = swissCheese()
        for ub in ub_paths:
            sc.notchFromUB(peaks_ws_name, str(ub), [0.02], True, lamMin=0.5)
        sc.save(str(out_dir), f"dac_mask_{RUN}")
        mask_paths = sorted(out_dir.glob(f"dac_mask_{RUN}_*.json"))

        print(f"Pipeline produced {len(ub_paths)} UBs and {len(mask_paths)} mask(s)")

        new_ubs = [read_ub_matrix(p) for p in sorted(ub_paths)]
        new_mask = json.loads(mask_paths[0].read_text()) if mask_paths else None

    # Also build a reference mask from the manually-made UBs so we can diff
    print("\nBuilding reference mask from saved UBs for comparison …")
    with tempfile.TemporaryDirectory(prefix="snapwrap_refmask_") as tmpdir2:
        ref_out = Path(tmpdir2) / "ref"
        from snapwrap.reduction_artefacts.masking import build_swiss_cheese_from_ub_files

        ref_mask_paths = build_swiss_cheese_from_ub_files(
            ref_ub_paths, RUN, [0.02], True,
            ref_out, f"dac_mask_{RUN}_ref",
            ipts=IPTS,
        )
        ref_mask = json.loads(ref_mask_paths[0].read_text()) if ref_mask_paths else None

    # ── Peak indexing stats ───────────────────────────────────────────────
    print("\n--- Peak indexing statistics ---")
    print(f"  Total candidate peaks:           {n_total}")
    print(f"  Matching diamond d-spacings:     {n_diamond}  ({100*n_diamond/n_total:.0f}% of total)")
    for cid, count in sorted(n_crystal.items()):
        frac = 100 * count / n_diamond if n_diamond else 0
        print(f"  Indexed to crystal {cid}:            {count}  ({frac:.0f}% of diamond peaks)")
    print(f"  Total indexed:                   {n_indexed}  ({100*n_indexed/n_diamond:.0f}% of diamond peaks)"
          f"  ← ideally ≥ 80%")

    # ── UB comparison (lattice-invariant eigenvalues) ─────────────────────
    print("\n--- UB comparison (metric-tensor eigenvalues) ---")
    for i, (ub, p) in enumerate(zip(new_ubs, sorted(ub_paths)), 1):
        astar = lattice_params(ub)
        angle, col = beam_parallelism(pipeline_ubs[i - 1])   # from pk.UBList, not disk roundtrip
        col_label = ["a*", "b*", "c*"][col]
        print(f"  New  crystal {i}: a ≈ {1/astar.mean():.4f} Å  |  "
              f"beam∠{col_label} = {angle:.1f}°  ({'few notches' if angle > 60 else 'many notches' if angle < 30 else 'moderate notches'})")
    for i, (ub, p) in enumerate(zip(ref_ubs, ref_ub_paths), 1):
        astar = lattice_params(ub)
        angle, col = beam_parallelism(ub)
        col_label = ["a*", "b*", "c*"][col]
        print(f"  Ref  crystal {i}: a ≈ {1/astar.mean():.4f} Å  |  "
              f"beam∠{col_label} = {angle:.1f}°  ({'few notches' if angle > 60 else 'many notches' if angle < 30 else 'moderate notches'})")

    ub_resid, best_perm = best_match_residual(new_ubs, ref_ubs)
    print(f"\nBest permutation of new UBs: {[i+1 for i in best_perm]}")
    print(f"Max eigenvalue residual: {ub_resid:.2e} Å⁻²")

    ub_threshold = 1e-4
    ub_ok = ub_resid < ub_threshold

    # ── Mask comparison (notch positions) ─────────────────────────────────
    if new_mask and ref_mask:
        new_xmins = sorted(new_mask.get("xmins", []))
        ref_xmins = sorted(ref_mask.get("xmins", []))
        n_new = len(new_xmins)
        n_ref = len(ref_xmins)
        print(f"\n--- Mask comparison ---")
        print(f"  New mask: {n_new} notch edges")
        print(f"  Ref mask: {n_ref} notch edges")
        if n_new == n_ref and n_new > 0:
            max_notch_diff = max(abs(a - b) for a, b in zip(new_xmins, ref_xmins))
            print(f"  Max notch-edge difference: {max_notch_diff:.4f} Å")
            mask_ok = max_notch_diff < 0.01
        else:
            print("  ⚠️  Different number of notches — counts differ")
            mask_ok = False
    else:
        print("\n⚠️  Could not compare masks (missing mask data)")
        mask_ok = False

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n=== Summary ===")
    if ub_ok:
        print(f"✅  UBs PASS — eigenvalue residual {ub_resid:.2e} < {ub_threshold:.0e} Å⁻²")
    else:
        print(f"❌  UBs FAIL — eigenvalue residual {ub_resid:.2e} ≥ {ub_threshold:.0e} Å⁻²")
    if mask_ok:
        print(f"✅  Mask PASS — notch positions match within 0.01 Å")
    else:
        print(f"❌  Mask FAIL — notch positions diverge or counts differ")

    if not (ub_ok and mask_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
