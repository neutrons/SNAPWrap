"""Swiss-cheese bin-mask builder: raw run → UB matrices → artefact.

This module implements the second concrete asset→artefact route in the
SNAPWrap reduction artefact framework.  Unlike the CIF→crystalSpecies route
(which starts from pre-staged files), this route drives the *entire* pipeline
from a single run number:

1. Load raw events and find diamond peaks (``generatePeaksWorkspace``).
2. Determine two UB matrices with the Jacobsen algorithm (``findDiamUB``).
3. Save those UBs as ISAW ``.mat`` files under ``output_dir/ubs/``.
4. Build a :class:`~snapwrap.maskUtils.swissCheese` by calling
   ``notchFromUB`` once per UB.
5. Save the merged mask as ``{file_prefix}_Wavelength.json`` under
   ``output_dir/``.

The saved UB files serve as the **reproducibility anchor**: if the mask ever
needs to be regenerated without re-running the expensive peak-finding step,
the UBs can be reloaded directly via
:func:`build_swiss_cheese_from_ub_files`.

Width-coefficient note
----------------------
The notch width at wavelength λ is the polynomial::

    width(λ) = Σ_i  width_coef[i] · λ^i

Use ``width_coef=[0.02]`` (constant 0.02 Å width) as a safe starting point.

.. note::
    Automating *width_coef* determination from an instrument resolution
    function is planned but not yet implemented.  For now the value should be
    supplied by the experimenter and recorded in the campaign notes.

Mantid is **not** imported at module level; all imports are deferred to
call-time so this module stays importable in documentation / testing
environments.
"""

from __future__ import annotations

from pathlib import Path

# Module-level deferred imports — kept in try/except so this module stays
# importable without Mantid (docs, unit tests).  When mocking, reload this
# module inside a ``patch.dict(sys.modules, {...})`` context to replace these
# names.  We use ``importlib.import_module`` rather than ``from X import Y``
# so that ``sys.modules`` is always the authoritative cache (the ``from``
# form can return a stale package attribute even after patching sys.modules).
import importlib as _importlib

try:
    _dub = _importlib.import_module("snapwrap.diamondUB")
    _swissCheese = _importlib.import_module("snapwrap.maskUtils").swissCheese  # type: ignore[attr-defined]
    _mantid = _importlib.import_module("mantid.simpleapi")
except Exception:  # pragma: no cover — missing in doc/test environments
    _dub = None  # type: ignore[assignment]
    _swissCheese = None  # type: ignore[assignment]
    _mantid = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _raw_nexus_path(ipts: int, run_number: int) -> Path:
    """Return the conventional SNS raw nexus path for a SNAP run."""
    return Path(f"/SNS/SNAP/IPTS-{ipts}/nexus/SNAP_{run_number}.nxs.h5")


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_swiss_cheese_from_run(
    run_number: int,
    width_coef: list[float],
    is_lite: bool,
    output_dir: str | Path,
    file_prefix: str,
    *,
    ipts: int,
    lam_min: float = 0.5,
    nexus_path: str | Path | None = None,
    dens_thresh: float = 400,
    n_diamonds: int = 2,
) -> tuple[list[Path], list[Path]]:
    """Run the full DAC mask pipeline for a single SNAP run.

    Loads the raw event data, finds diamond peaks, determines *n_diamonds*
    UB matrices, saves them as ISAW ``.mat`` files, builds a swiss-cheese
    bin mask, and saves it as JSON.

    Args:
        run_number: SNAP run number to process.
        width_coef: Polynomial coefficients ``[a0, a1, …]`` for the notch
            half-width at each wavelength (Å).  ``[0.02]`` gives a flat
            0.02 Å width.
        is_lite: ``True`` for Lite (18 432-pixel) mode, ``False`` for native.
        output_dir: Directory in which mask JSON files are written.  A ``ubs/``
            subdirectory is created inside it for the ``.mat`` files.
        file_prefix: Filename stem for saved mask files, e.g.
            ``"dac_mask_bruciteA"``.  The unit label is appended by
            :meth:`~snapwrap.maskUtils.swissCheese.save`, producing
            ``{file_prefix}_Wavelength.json``.
        ipts: IPTS experiment number; used to locate the nexus file when
            *nexus_path* is not given.
        lam_min: Minimum wavelength (Å) for reflection enumeration.
        nexus_path: Override for the raw nexus file path.  Defaults to the
            SNS conventional path
            ``/SNS/SNAP/IPTS-{ipts}/nexus/SNAP_{run_number}.nxs.h5``.
        dens_thresh: Density threshold for ``FindPeaksMD``.
        n_diamonds: Number of diamond crystals to find (normally 2 for a DAC).

    Returns:
        ``(mask_json_paths, ub_mat_paths)`` — both are lists of
        :class:`~pathlib.Path`, sorted by name.  *mask_json_paths* are the
        saved swiss-cheese JSON files; *ub_mat_paths* are the saved ISAW UB
        files.

    Raises:
        FileNotFoundError: If the nexus file does not exist and no
            *nexus_path* override was given.
        ValueError: If *width_coef* is empty.
        RuntimeError: If ``findDiamUB`` finds fewer than *n_diamonds* UBs.
    """
    if not width_coef:
        raise ValueError("width_coef must contain at least one coefficient")

    nexus = Path(nexus_path) if nexus_path is not None else _raw_nexus_path(ipts, run_number)
    if not nexus.exists():
        raise FileNotFoundError(f"Raw nexus file not found: {nexus}")

    output_dir = Path(output_dir)
    ub_dir = output_dir / "ubs"
    ub_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: peak finding ───────────────────────────────────────────────
    peaks_ws_name, _ = _dub.generatePeaksWorkspace(
        run_number,
        ipts=ipts,
        nexus_path=nexus,
        dens_thresh=dens_thresh,
    )

    # ── Step 2: UB determination ───────────────────────────────────────────
    pk = _dub.peakInfo(peaks_ws_name)
    pk.ipts = ipts
    pk.runNumber = run_number
    _dub.findDiamUB(pk)

    if len(pk.UBList) < n_diamonds:
        raise RuntimeError(
            f"findDiamUB found only {len(pk.UBList)} UB(s); "
            f"expected {n_diamonds}.  Try lowering dens_thresh."
        )

    # ── Step 3: save UBs ──────────────────────────────────────────────────
    ub_paths: list[Path] = []
    for i in range(1, n_diamonds + 1):
        ub_path = ub_dir / f"SNAP{run_number}UB{i}.mat"
        pk.CreatePeaksWSAndSave(i, ub_path)
        ub_paths.append(ub_path)

    # ── Step 4: build swiss cheese ────────────────────────────────────────
    sc = _swissCheese()
    for ub in ub_paths:
        sc.notchFromUB(peaks_ws_name, str(ub), width_coef, is_lite, lamMin=lam_min)

    # ── Step 5: save mask ─────────────────────────────────────────────────
    sc.save(str(output_dir), file_prefix)
    mask_paths = sorted(output_dir.glob(f"{file_prefix}_*.json"))

    return mask_paths, ub_paths


def build_swiss_cheese_from_ub_files(
    ub_paths: list[str | Path],
    run_number: int,
    width_coef: list[float],
    is_lite: bool,
    output_dir: str | Path,
    file_prefix: str,
    *,
    ipts: int,
    lam_min: float = 0.5,
    nexus_path: str | Path | None = None,
) -> list[Path]:
    """Rebuild a swiss-cheese mask from previously saved UB ``.mat`` files.

    Fast path for regenerating a mask without re-running the expensive
    peak-finding step.  The raw nexus file is loaded with
    ``MetaDataOnly=True`` (no events) to provide an instrument donor for
    ``LoadIsawUB``.

    Args:
        ub_paths: Ordered list of paths to ISAW ``.mat`` UB files (e.g.
            ``SNAP65891UB1.mat``, ``SNAP65891UB2.mat``).
        run_number: SNAP run number used as instrument donor.
        width_coef: Notch-width polynomial coefficients.
        is_lite: Lite mode flag.
        output_dir: Output directory for mask JSON files.
        file_prefix: Filename stem.
        ipts: IPTS number (used to resolve nexus path when *nexus_path* is
            ``None``).
        lam_min: Minimum wavelength (Å).
        nexus_path: Override for raw nexus path.

    Returns:
        List of saved mask JSON :class:`~pathlib.Path` objects.

    Raises:
        FileNotFoundError: If the nexus file or any UB file does not exist.
        ValueError: If *ub_paths* or *width_coef* is empty.
    """
    if not ub_paths:        raise ValueError("ub_paths must contain at least one path")
    if not width_coef:
        raise ValueError("width_coef must contain at least one coefficient")

    nexus = Path(nexus_path) if nexus_path is not None else _raw_nexus_path(ipts, run_number)
    if not nexus.exists():
        raise FileNotFoundError(f"Raw nexus file not found: {nexus}")

    resolved_ubs = [Path(p) for p in ub_paths]
    for ub in resolved_ubs:
        if not ub.exists():
            raise FileNotFoundError(f"UB matrix file not found: {ub}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ws_name = f"_snapwrap_donor_{run_number}"
    _mantid.LoadEventNexus(Filename=str(nexus), OutputWorkspace=ws_name, MetaDataOnly=True)
    try:
        sc = _swissCheese()
        for ub in resolved_ubs:
            sc.notchFromUB(ws_name, str(ub), width_coef, is_lite, lamMin=lam_min)
    finally:
        _mantid.DeleteWorkspace(Workspace=ws_name)

    sc.save(str(output_dir), file_prefix)
    return sorted(output_dir.glob(f"{file_prefix}_*.json"))


# ---------------------------------------------------------------------------
# Pixel mask builders (PE cell)
# ---------------------------------------------------------------------------

#: Path to the standard SNAP PE-cell letterbox pixel mask.
STANDARD_PE_MASK_PATH: Path = Path("/SNS/SNAP/shared/autoreduce/masks/PEMask.nxs")


def build_pixel_mask_from_file(
    nxs_path: str | Path,
    ws_name: str,
) -> str:
    """Load a pixel mask workspace from a Nexus file via ``LoadNexus``.

    The *nxs_path* is the **asset** (an existing ``.nxs`` mask file on disk).
    This function produces the in-memory Mantid workspace (the **artefact**).
    Use :func:`build_pixel_mask_letterbox` as a convenience wrapper for the
    standard SNAP PE-cell mask.

    Args:
        nxs_path: Path to the ``.nxs`` pixel mask file.
        ws_name: Name for the resulting Mantid workspace.  Use a name that
            encodes campaign/run context, e.g.
            ``"snapwrap_pixmask_pe_h2o_01_run65200"``.

    Returns:
        *ws_name* (so callers can chain directly into reduction).

    Raises:
        FileNotFoundError: If *nxs_path* does not exist.
    """
    nxs_path = Path(nxs_path)
    if not nxs_path.exists():
        raise FileNotFoundError(f"Pixel mask file not found: {nxs_path}")
    _mantid.LoadNexus(Filename=str(nxs_path), OutputWorkspace=ws_name)
    return ws_name


def build_pixel_mask_letterbox(ws_name: str) -> str:
    """Load the standard SNAP PE-cell letterbox pixel mask.

    Convenience wrapper that calls :func:`build_pixel_mask_from_file` with
    :data:`STANDARD_PE_MASK_PATH`.

    Args:
        ws_name: Name for the resulting Mantid workspace.

    Returns:
        *ws_name*.

    Raises:
        FileNotFoundError: If the standard mask file is not present on disk.
    """
    return build_pixel_mask_from_file(STANDARD_PE_MASK_PATH, ws_name)
