"""Post-processing utilities for reduced SNAP workspaces.

Provides workspace-cropping based on registered bin-mask artefacts:

1. Obtain the grouping workspaces for this run — first by scanning ADS for
   any that SNAPRed left behind, then by loading them fresh via
   ``ReductionService.loadAllGroupings`` if none are present.
2. Build a synthetic flat workspace, zero the notched wavelength regions for
   the appropriate detectors, then diffraction-focus it.
3. Identify the resulting zero-valued regions as d-space gaps.
4. Apply those gaps to the real reduced/resampled workspaces:
   end-gaps are removed with ``CropWorkspaceRagged``; interior gaps are set
   to ``NaN``.

All Mantid imports are deferred to function scope so the module can be
imported outside of Mantid Workbench (e.g. in unit tests).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ── ADS workspace discovery ────────────────────────────────────────────────────


def _run_tokens(run_number: int) -> list[str]:
    """Return both the bare and zero-padded run-number strings."""
    return [str(run_number), f"{run_number:06d}"]


def find_grouping_workspaces(run_number: int, is_lite: bool) -> dict[str, str]:
    """Scan ADS for SNAPRed's hidden grouping workspaces; return ``{group_name: ws_name}``.

    SNAPRed loads grouping workspaces with names of the form::

        __SNAPLite_grouping_<Group>_<run>   (lite mode)
        __SNAP_grouping_<Group>_<run>       (native mode)

    These are normally cleaned up after reduction completes.  This function
    returns whatever happens to still be present; use
    :func:`load_grouping_workspaces` to guarantee they exist.
    """
    from mantid.api import mtd  # type: ignore

    mode_tag = "SNAPLite" if is_lite else "SNAP"
    run_tokens = _run_tokens(run_number)
    result: dict[str, str] = {}

    for name in mtd.getObjectNames():
        if not name.startswith("__"):
            continue
        if "grouping" not in name:
            continue
        if mode_tag not in name:
            continue
        # Must end with the run number (bare or zero-padded)
        matched_token = next((t for t in run_tokens if name.endswith(f"_{t}")), None)
        if matched_token is None:
            continue
        # Extract group name from between "grouping_" and "_{run}"
        after_mode = name.lstrip("_")  # strip leading __
        idx = after_mode.find("grouping_")
        if idx < 0:
            continue
        tail = after_mode[idx + len("grouping_"):]  # e.g. "Column_065891"
        tail = tail.lstrip("_")  # absorb double-underscore separator if present
        group_name = tail[: -(len(matched_token) + 1)]  # strip "_065891"
        if group_name:
            result[group_name.lower()] = name

    return result


def load_grouping_workspaces(
    run_number: int, is_lite: bool
) -> tuple[dict[str, str], list[str]]:
    """Return grouping workspaces, loading them via SNAPRed if necessary.

    Tries the ADS scan first (fast, zero overhead).  If nothing is found —
    the common case after reduction has finished and SNAPRed has cleaned up —
    calls ``ReductionService.loadAllGroupings`` to load them fresh.

    Returns:
        ``(grouping_ws_map, freshly_loaded)`` where *grouping_ws_map* is
        ``{group_name: ws_name}`` and *freshly_loaded* is the list of
        workspace names that were just loaded (caller should delete them
        when no longer needed).

    Raises:
        RuntimeError: If no grouping workspaces can be obtained.
    """
    # Fast path: already in ADS
    present = find_grouping_workspaces(run_number, is_lite)
    if present:
        return present, []

    # Slow path: ask SNAPRed to load them
    from snapred.backend.service.ReductionService import ReductionService  # type: ignore

    service = ReductionService()
    result = service.loadAllGroupings(str(run_number), is_lite)

    focus_groups = result["focusGroups"]
    ws_names: list[str] = result["groupingWorkspaces"]

    if not ws_names:
        raise RuntimeError(
            f"ReductionService.loadAllGroupings returned no grouping workspaces "
            f"for run {run_number} (lite={is_lite})."
        )

    grouping_ws_map = {
        fg.name.lower(): ws_name for fg, ws_name in zip(focus_groups, ws_names)
    }
    return grouping_ws_map, ws_names


def find_unfocused_workspace(run_number: int, is_lite: bool) -> str | None:
    """Find the keepUnfocused workspace left in ADS after reduction.

    Tries in priority order:

    1. Visible workspace whose name contains ``"Unfoc"`` and the run number.
    2. Hidden workspace with the expected lite/native detector count.
    """
    from mantid.api import mtd  # type: ignore

    run_tokens = _run_tokens(run_number)

    # Option 1: visible unfocused workspace
    for name in mtd.getObjectNames():
        if name.startswith("__"):
            continue
        if "Unfoc" not in name and "unfoc" not in name:
            continue
        if any(t in name for t in run_tokens):
            return name

    # Option 2: hidden instrument workspace identified by spectrum count
    expected_n = 18_432 if is_lite else 1_179_648
    for name in mtd.getObjectNames():
        if not name.startswith("__"):
            continue
        if "grouping" in name or "SNAP" in name:
            continue
        try:
            ws = mtd[name]
            if hasattr(ws, "getNumberHistograms") and ws.getNumberHistograms() == expected_n:
                return name
        except Exception:
            pass

    return None


# ── Bin-mask loading ───────────────────────────────────────────────────────────


def _parse_spectra_list(spec_str: str) -> list[range]:
    """Parse a spectraLst string into a compact list of ranges.

    Handles comma-separated integers (``"7661,7662,7663"``), range notation
    (``"0-18431"``), and mixtures.  Single integers are stored as
    ``range(n, n+1)``.  Membership testing via ``any(d in r for r in ranges)``
    is O(1) per range because ``range.__contains__`` uses arithmetic.

    Returns an empty list if the string is blank (meaning: apply to all
    detectors).
    """
    ranges: list[range] = []
    for token in spec_str.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            try:
                lo, hi = int(parts[0]), int(parts[1])
                ranges.append(range(lo, hi + 1))
            except (ValueError, IndexError):
                pass
        else:
            try:
                n = int(token)
                ranges.append(range(n, n + 1))
            except ValueError:
                pass
    return ranges


def _load_notches(
    mask_json_path: str | Path,
) -> list[tuple[float, float, list[range]]]:
    """Load notches from a swiss-cheese bin-mask JSON.

    Returns a list of ``(xmin, xmax, det_ranges)`` tuples where
    ``det_ranges`` is a compact list of ``range`` objects (empty list
    means the notch applies to all detectors).
    """
    data = json.loads(Path(mask_json_path).read_text(encoding="utf-8"))
    xmins: list[float] = data["xmins"]
    xmaxs: list[float] = data["xmaxs"]
    spectra_lsts: list[str] = data.get("spectraLsts", [])

    result = []
    for i, (xmin, xmax) in enumerate(zip(xmins, xmaxs)):
        if i < len(spectra_lsts) and spectra_lsts[i]:
            det_ranges = _parse_spectra_list(spectra_lsts[i])
        else:
            det_ranges = []
        result.append((float(xmin), float(xmax), det_ranges))
    return result


# ── Gap detection in a focused workspace ──────────────────────────────────────


def _find_zero_runs(ws: Any, spectrum_idx: int) -> list[tuple[float, float]]:
    """Return ``[(d_lo, d_hi)]`` for contiguous near-zero Y regions."""
    import numpy as np  # type: ignore

    y = np.asarray(ws.readY(spectrum_idx))
    x = np.asarray(ws.readX(spectrum_idx))
    threshold = 1e-10
    is_zero = np.abs(y) <= threshold

    gaps: list[tuple[float, float]] = []
    in_gap = False
    gap_start = 0
    for i, z in enumerate(is_zero):
        if z and not in_gap:
            in_gap = True
            gap_start = i
        elif not z and in_gap:
            in_gap = False
            gaps.append((float(x[gap_start]), float(x[i])))
    if in_gap:
        gaps.append((float(x[gap_start]), float(x[len(y)])))
    return gaps


# ── Main gap-computation entry point ──────────────────────────────────────────


def compute_dspace_gaps(
    run_number: int,
    is_lite: bool,
    bin_mask_paths: list[str | Path],
    diagnostics: bool = False,
) -> dict[str, list[list[tuple[float, float]]]]:
    """Compute d-space gap intervals from registered wavelength bin masks.

    For each focus group and each spectrum within that group, returns the
    list of ``(d_lo, d_hi)`` intervals that are masked.

    Args:
        run_number: Run number whose ADS workspaces are used.
        is_lite: ``True`` for Lite (18 432-pixel) mode.
        bin_mask_paths: Paths to swiss-cheese JSON mask files.
        diagnostics: If ``True``, leave the synthetic and focused gap-map
            workspaces in ADS (named ``crop_diag_synthetic_{run}`` and
            ``crop_diag_focused_{group}_{run}``) for inspection.

    Returns:
        ``{group_name: [[gaps_for_spectrum_0], [gaps_for_spectrum_1], …]}``

    Raises:
        RuntimeError: If the required ADS workspaces are not found.
    """
    import numpy as np  # type: ignore
    from mantid.simpleapi import (  # type: ignore
        CloneWorkspace,
        ConvertToMatrixWorkspace,
        ConvertUnits,
        DeleteWorkspace,
        DiffractionFocussing,
        mtd,
    )

    # ── 1. Obtain grouping workspaces (ADS scan, then SNAPRed load) ───
    grouping_ws_map, freshly_loaded_groupings = load_grouping_workspaces(
        run_number, is_lite
    )

    # ── 2. Locate donor unfocused workspace ───────────────────────────
    donor_name = find_unfocused_workspace(run_number, is_lite)
    if donor_name is None:
        raise RuntimeError(
            f"No unfocused workspace found in ADS for run {run_number}. "
            "Re-reduce with keepUnfocussed=True, or reload the raw data."
        )

    # ── 3. Load all notches from the supplied bin-mask files ──────────
    all_notches: list[tuple[float, float, list[range]]] = []
    for path in bin_mask_paths:
        all_notches.extend(_load_notches(path))

    if not all_notches:
        return {}

    # ── 4. Build a synthetic flat workspace in Wavelength ─────────────
    synthetic_name = f"crop_diag_synthetic_{run_number}"
    CloneWorkspace(InputWorkspace=donor_name, OutputWorkspace=synthetic_name)
    ConvertUnits(
        InputWorkspace=synthetic_name,
        OutputWorkspace=synthetic_name,
        Target="Wavelength",
        EMode="Elastic",
    )
    # EventWorkspace.dataY() is read-only; convert to histogram before writing.
    ConvertToMatrixWorkspace(
        InputWorkspace=synthetic_name,
        OutputWorkspace=synthetic_name,
    )

    ws_syn = mtd[synthetic_name]
    n_hist = ws_syn.getNumberHistograms()
    for i in range(n_hist):
        ws_syn.dataY(i)[:] = 1.0
        ws_syn.dataE(i)[:] = 0.0

    # ── 5. Build detector-ID → workspace-index map (one-time) ─────────
    det_to_idx: dict[int, int] = {}
    for i in range(n_hist):
        for did in ws_syn.getSpectrum(i).getDetectorIDs():
            det_to_idx[did] = i

    # ── 6. Apply wavelength notches to the synthetic workspace ─────────
    for xmin, xmax, det_ranges in all_notches:
        if det_ranges:
            # range.__contains__ is O(1) — no list expansion even for "0-1179647"
            indices = [
                idx for did, idx in det_to_idx.items()
                if any(did in r for r in det_ranges)
            ]
        else:
            indices = range(n_hist)
        for i in indices:
            x = ws_syn.readX(i)
            y = ws_syn.dataY(i)
            lo = int(np.searchsorted(x, xmin, side="left"))
            hi = int(np.searchsorted(x, xmax, side="right"))
            y[lo:hi] = 0.0

    # ── 7. Convert synthetic workspace to dSpacing for DiffractionFocussing ──
    ConvertUnits(
        InputWorkspace=synthetic_name,
        OutputWorkspace=synthetic_name,
        Target="dSpacing",
        EMode="Elastic",
    )

    # ── 8. Focus per group; extract d-space gap regions ───────────────
    result: dict[str, list[list[tuple[float, float]]]] = {}
    for group_name, grouping_ws in grouping_ws_map.items():
        focused_name = f"crop_diag_focused_{group_name}_{run_number}"
        DiffractionFocussing(
            InputWorkspace=synthetic_name,
            OutputWorkspace=focused_name,
            GroupingWorkspace=grouping_ws,
        )
        # Output is already in dSpacing — no unit conversion needed.
        focused_ws = mtd[focused_name]
        spectrum_gaps = [
            _find_zero_runs(focused_ws, i)
            for i in range(focused_ws.getNumberHistograms())
        ]
        result[group_name] = spectrum_gaps
        if not diagnostics:
            DeleteWorkspace(focused_name)

    if not diagnostics:
        DeleteWorkspace(synthetic_name)

    # Always clean up grouping workspaces we loaded ourselves — they are
    # infrastructure, not diagnostic output.
    for ws_name in freshly_loaded_groupings:
        try:
            DeleteWorkspace(ws_name)
        except Exception:
            pass

    return result


# ── Gap application ────────────────────────────────────────────────────────────


def apply_dspace_gaps(
    ws_name: str,
    gaps_per_spectrum: list[list[tuple[float, float]]],
    output_ws_name: str | None = None,
) -> str:
    """Apply d-space gap intervals to a focused workspace.

    Interior gaps (within the spectrum x-range) have their Y values set to
    ``NaN``.  End-gaps (overlapping the spectrum edges) are removed with a
    single call to ``CropWorkspaceRagged``.

    Args:
        ws_name: Name of the input focused workspace in ADS.
        gaps_per_spectrum: Per-spectrum gap lists as returned by
            :func:`compute_dspace_gaps` for one group.
        output_ws_name: Output workspace name.  Defaults to
            ``{ws_name}_cropped``.

    Returns:
        The output workspace name.
    """
    import logging

    import numpy as np  # type: ignore
    from mantid.simpleapi import CloneWorkspace, CropWorkspaceRagged, mtd  # type: ignore

    log = logging.getLogger("snapwrap")

    if output_ws_name is None:
        output_ws_name = ws_name + "_cropped"

    CloneWorkspace(InputWorkspace=ws_name, OutputWorkspace=output_ws_name)
    ws = mtd[output_ws_name]

    xmins: list[float] = []
    xmaxs: list[float] = []

    for i in range(ws.getNumberHistograms()):
        x = np.asarray(ws.readX(i))
        y = ws.dataY(i)
        d_start = float(x[0])
        d_end = float(x[-1])
        new_xmin = d_start
        new_xmax = d_end

        gaps = gaps_per_spectrum[i] if i < len(gaps_per_spectrum) else []
        for g_lo, g_hi in sorted(gaps):
            if g_lo <= d_start:
                # Left end-gap: advance the lower crop boundary
                new_xmin = max(new_xmin, g_hi)
            elif g_hi >= d_end:
                # Right end-gap: retract the upper crop boundary
                new_xmax = min(new_xmax, g_lo)
            else:
                # Interior gap: NaN the affected bins
                lo = int(np.searchsorted(x, g_lo, side="left"))
                hi = int(np.searchsorted(x, g_hi, side="right"))
                y[lo:hi] = np.nan

        if new_xmin >= new_xmax:
            log.warning(
                "Spectrum %d of '%s': end-gaps consume the entire range "
                "[%.4f, %.4f] — skipping crop for this spectrum.",
                i, ws_name, d_start, d_end,
            )
            new_xmin = d_start
            new_xmax = d_end

        log.debug(
            "Spectrum %d: crop [%.4f, %.4f] → [%.4f, %.4f], %d interior gap(s)",
            i, d_start, d_end, new_xmin, new_xmax,
            sum(1 for g_lo, g_hi in gaps if d_start < g_lo and g_hi < d_end),
        )
        xmins.append(new_xmin)
        xmaxs.append(new_xmax)

    CropWorkspaceRagged(
        InputWorkspace=output_ws_name,
        OutputWorkspace=output_ws_name,
        XMin=xmins,
        XMax=xmaxs,
    )

    return output_ws_name
