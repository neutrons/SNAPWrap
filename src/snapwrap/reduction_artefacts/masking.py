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
    keep_diagnostics: bool = True,
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
        keep_diagnostics: When ``True`` (default for direct interactive
            calls), the intermediate workspaces created during peak finding
            (``snapwrap_DSP_{run}``, ``snapwrap_MD_{run}``,
            ``snapwrap_PKS_{run}``) are moved into a per-run diagnostics
            workspace group (``wrap_diagnostics_{run}``) so they remain
            inspectable in Mantid Workbench.  When ``False`` they are
            deleted.  In either case the indexed-peaks artefact workspaces
            (``snapwrap_PKS_{run}_UB{i}``) are moved into the per-run
            artefact group (``wrap_artefacts_{run}``).

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

    # ── Step 6: tidy the Mantid ADS ────────────────────────────────────────
    from .workspace_groups import finalize_builder_workspaces

    finalize_builder_workspaces(
        run_number=run_number,
        artefact_ws=[
            f"snapwrap_PKS_{run_number}_UB{i}" for i in range(1, n_diamonds + 1)
        ],
        diagnostic_ws=[
            f"snapwrap_DSP_{run_number}",
            f"snapwrap_MD_{run_number}",
            f"snapwrap_PKS_{run_number}",
        ],
        keep_diagnostics=keep_diagnostics,
    )

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
    keep_diagnostics: bool = True,
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
        keep_diagnostics: When ``True`` (default), the metadata-only donor
            workspace ``_snapwrap_donor_{run}`` is preserved and adopted into
            the per-run diagnostics group ``wrap_diagnostics_{run}``.  When
            ``False`` it is deleted as soon as the mask has been built.

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
        from .workspace_groups import finalize_builder_workspaces

        finalize_builder_workspaces(
            run_number=run_number,
            artefact_ws=(),
            diagnostic_ws=[ws_name],
            keep_diagnostics=keep_diagnostics,
        )

    sc.save(str(output_dir), file_prefix)
    return sorted(output_dir.glob(f"{file_prefix}_*.json"))


# ---------------------------------------------------------------------------
# Transmission-monitor driven swiss-cheese builder
# ---------------------------------------------------------------------------
#
# Algorithm overview
# ------------------
# 1. Load monitors from the raw nexus, convert to wavelength, rebin.
# 2. Extract the transmission-monitor spectrum (default workspace index 1).
# 3. Smooth lightly with a boxcar (sigma_smooth bins) to suppress shot noise.
# 4. Estimate the continuum with a **rolling median** over a wide window
#    (median is robust to dips; mean would be biased *down* by them, hiding
#    the very features we are trying to find).
# 5. Compute ratio = smoothed / continuum and flag bins where
#    ratio < dip_threshold.
# 6. Group contiguous flagged bins into notches; merge those whose
#    edges are closer than ``merge_gap_aa`` Å; drop notches whose width
#    is below ``min_width_aa`` Å.
# 7. Optionally pad each notch by ``edge_pad_aa`` Å to be conservative.

def _rolling_median(y, window):
    """Pure-numpy rolling median, edges handled by reflection.

    Window is forced to be odd. Slow O(N·W·log W) but fine for ~10⁴ bins.
    """
    import numpy as np

    w = int(window)
    if w < 3:
        return y.copy()
    if w % 2 == 0:
        w += 1
    half = w // 2
    pad = np.pad(y, half, mode="reflect")
    out = np.empty_like(y)
    for i in range(y.size):
        out[i] = np.median(pad[i:i + w])
    return out


def _rolling_percentile(y, window, q):
    """Pure-numpy rolling percentile (0 ≤ q ≤ 100), reflection padding.

    With ``q=90`` this traces the upper envelope of the spectrum, which is
    a much better continuum estimator than the median when notches are
    so dense that they dominate the local distribution.
    """
    import numpy as np

    w = int(window)
    if w < 3:
        return y.copy()
    if w % 2 == 0:
        w += 1
    half = w // 2
    pad = np.pad(y, half, mode="reflect")
    out = np.empty_like(y)
    for i in range(y.size):
        out[i] = np.percentile(pad[i:i + w], q)
    return out


def detect_notches_in_spectrum(
    centers,
    y,
    *,
    sigma_smooth: int = 3,
    continuum_window: int = 51,
    continuum_method: str = "median",
    continuum_percentile: float = 90.0,
    clip_win_size: int = 40,
    clip_smoothing: float = 5.0,
    dip_threshold: float = 0.85,
    min_width_aa: float = 0.005,
    merge_gap_aa: float = 0.01,
    edge_pad_aa: float = 0.0,
):
    """Find absorption notches in a 1-D spectrum (pure numpy, no Mantid).

    Args:
        centers: 1-D array of bin centres (wavelength, Å).
        y: 1-D array of monitor counts, same length as *centers*.
        sigma_smooth: Half-width of the boxcar pre-smoothing kernel (bins).
            ``0`` disables smoothing.
        continuum_window: Width of the rolling continuum window (bins),
            used by ``"median"`` and ``"percentile"`` methods only.
            Should be much wider than the widest expected notch.
        continuum_method: One of:

            * ``"median"`` — rolling median; dip-robust when notches occupy
              < ½ window.
            * ``"percentile"`` — rolling ``continuum_percentile``; tracks
              the upper envelope when notch density is high.
            * ``"clip_peaks"`` — invert spectrum (dips → peaks), apply the
              SNIP rolling-ball peak-clipping algorithm
              (``snapwrap._inspectrum.background.estimate_background``)
              to estimate the inverted-background, then map back. The
              resulting ratio is renormalised so its median is 1, which
              absorbs the multiplicative offset (~1.2) that SNIP
              introduces. Use ``clip_win_size`` to control its window.
        continuum_percentile: Percentile for ``continuum_method="percentile"``
            (default 90). Higher → tighter to the upper envelope.
        clip_win_size: Maximum half-window (bins) for the SNIP rolling-ball
            in ``continuum_method="clip_peaks"`` (default 40, matching
            ``inspectrum``'s default). Larger → broader features clipped.
        clip_smoothing: SNIP's own smoothing parameter, passed straight to
            ``estimate_background(smoothing=...)``. Default 5.0 matches
            inspectrum's default. Set to 0 to disable SNIP smoothing (in
            which case ``sigma_smooth`` becomes the only smoother).
        dip_threshold: Bins where ``smoothed/continuum < dip_threshold`` are
            flagged. Lower → only deeper dips are kept.
        min_width_aa: Minimum notch width in Å. Narrower notches are
            discarded as noise.
        merge_gap_aa: Notches separated by less than this gap (Å) are
            merged.
        edge_pad_aa: Symmetric padding (Å) added to each notch edge.

    Returns:
        ``(notches, diagnostics)`` where:
        - ``notches`` is a ``list[[lam_min, lam_max]]`` sorted by lam_min.
        - ``diagnostics`` is a dict with keys ``smoothed``, ``continuum``,
          ``ratio``, ``below_threshold`` (numpy arrays), useful for plotting.
    """
    import numpy as np

    centers = np.asarray(centers, dtype=float)
    y = np.asarray(y, dtype=float)
    if centers.size != y.size:
        raise ValueError("centers and y must have the same length")
    if centers.size < 3:
        return [], {
            "smoothed": y.copy(),
            "continuum": y.copy(),
            "ratio": np.ones_like(y),
            "below_threshold": np.zeros_like(y, dtype=bool),
        }

    # 1. Light smoothing (boxcar with reflection padding to avoid
    #    zero-padding edge artefacts that look like fake notches).
    if sigma_smooth and sigma_smooth >= 1:
        kw = 2 * int(sigma_smooth) + 1
        kern = np.ones(kw) / kw
        padded = np.pad(y, kw // 2, mode="reflect")
        smoothed = np.convolve(padded, kern, mode="valid")
    else:
        smoothed = y.copy()

    # Container for method-specific debugging intermediates (only populated
    # by clip_peaks; merged into the diagnostics dict at the end).
    _extra_diag: dict = {}

    # 2. Continuum estimation (median, rolling-percentile envelope, or
    #    SNIP peak-clipping after dip→peak inversion).
    win = max(3, int(continuum_window))
    method = str(continuum_method).lower()
    if method == "percentile":
        cont = _rolling_percentile(smoothed, win, float(continuum_percentile))
        cont_safe = np.where(cont <= 0, 1.0, cont)
        ratio = smoothed / cont_safe
    elif method == "median":
        cont = _rolling_median(smoothed, win)
        cont_safe = np.where(cont <= 0, 1.0, cont)
        ratio = smoothed / cont_safe
    elif method == "clip_peaks":
        from snapwrap._inspectrum.background import estimate_background

        # The "clip_peaks" route applies SNIP's own smoothing (controlled by
        # `clip_smoothing`, mapped to inspectrum's `smoothing` parameter).
        # The pre-smoothed `smoothed` array is therefore used only as the
        # comparison baseline (and as the source of y_min/y_max for the
        # inversion bookkeeping). Setting sigma_smooth=0 is a clean way to
        # use SNIP alone; the default sigma_smooth=3 is harmless because the
        # boxcar window is much narrower than SNIP's rolling-ball.
        #
        # Step A — invert so dips become peaks. y_inv ≥ 0 everywhere,
        # with the strongest dip in `smoothed` mapping to the highest peak
        # in y_inv, and the brightest bin mapping to y_inv == 0.
        y_min = float(np.min(smoothed))
        y_max = float(np.max(smoothed))
        y_inv = y_max - smoothed                       # all ≥ 0, peaks-up
        # Step B — feed y_inv to SNIP. SNIP returns the *lower* envelope
        # of its input (= the inverted continuum, with the peaks clipped).
        bg_inv, _ = estimate_background(
            y_inv,
            win_size=int(clip_win_size),
            decrease=True,
            lls=True,
            smoothing=float(clip_smoothing),
        )
        # Step C — map SNIP's output back to original-space. cont is the
        # upper envelope of `smoothed` (the continuum, with dips hidden).
        cont = y_max - bg_inv
        cont_safe = np.where(cont <= 0, 1.0, cont)
        ratio = smoothed / cont_safe
        # Step D — renormalise so that flat baseline regions sit at
        # ratio == 1, restoring standard `ratio < threshold` semantics.
        # SNIP usually leaves a multiplicative offset because it pins the
        # background to the inverted spectrum at a single point.
        baseline = float(np.median(ratio))
        if baseline > 0:
            ratio = ratio / baseline
            cont = cont * baseline                     # keep cont ↔ ratio
        # Stash SNIP intermediates so the caller can plot every step.
        _extra_diag = {
            "clip_y_inv": y_inv,                       # SNIP input
            "clip_bg_inv": bg_inv,                     # SNIP raw output
            "clip_y_max": y_max,
            "clip_y_min": y_min,
            "clip_baseline_offset": baseline,
        }
    else:
        raise ValueError(
            "continuum_method must be 'median', 'percentile', or "
            f"'clip_peaks', got {continuum_method!r}"
        )

    # 3. Threshold + contiguous regions.
    below = ratio < float(dip_threshold)
    raw_notches: list[list[float]] = []
    if below.any():
        diff = np.diff(below.astype(np.int8))
        starts = np.where(diff == 1)[0] + 1
        ends = np.where(diff == -1)[0] + 1
        if below[0]:
            starts = np.insert(starts, 0, 0)
        if below[-1]:
            ends = np.append(ends, below.size)
        for s, e in zip(starts, ends):
            lam_lo = float(centers[s])
            lam_hi = float(centers[e - 1])
            if lam_hi > lam_lo:
                raw_notches.append([lam_lo, lam_hi])

    # 4. Merge nearby notches.
    merged: list[list[float]] = []
    for n in sorted(raw_notches):
        if merged and (n[0] - merged[-1][1]) <= merge_gap_aa:
            merged[-1][1] = max(merged[-1][1], n[1])
        else:
            merged.append(list(n))

    # 5. Drop too-narrow notches; apply edge padding.
    final: list[list[float]] = []
    for lo, hi in merged:
        if (hi - lo) < min_width_aa:
            continue
        final.append([lo - edge_pad_aa, hi + edge_pad_aa])

    diagnostics = {
        "raw": y.copy(),
        "smoothed": smoothed,
        "continuum": cont,
        "ratio": ratio,
        "below_threshold": below,
    }
    diagnostics.update(_extra_diag)
    return final, diagnostics


def _save_notch_diagnostic_plot(
    *,
    x: "np.ndarray",
    ratio: "np.ndarray",
    notches: list[list[float]],
    dip_threshold: float,
    output_path: "Path",
    run_number: int,
) -> "Path | None":
    """Save a PNG showing the ratio spectrum with detected notches shaded.

    Returns the saved path on success, None on failure (e.g. matplotlib
    unavailable in the current environment).
    """
    try:
        import numpy as _np
        from matplotlib.backends.backend_agg import FigureCanvasAgg  # type: ignore
        from matplotlib.figure import Figure  # type: ignore

        fig = Figure(figsize=(8, 3), dpi=100)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.plot(x, ratio, color="#60aaff", lw=0.8, label="ratio")
        ax.axhline(dip_threshold, color="#ff8844", lw=0.9, ls="--",
                   label=f"threshold ({dip_threshold})")
        for lo, hi in notches:
            ax.axvspan(lo, hi, alpha=0.25, color="#ff4444")
        ax.set_xlabel("Wavelength (Å)", fontsize=8)
        ax.set_ylabel("Ratio", fontsize=8)
        ax.set_title(f"Notch detection — run {run_number}", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7, loc="lower right")
        fig.tight_layout()
        fig.savefig(str(output_path), dpi=100)
        return output_path
    except Exception:
        return None


def build_swiss_cheese_from_transmission_monitor(
    run_number: int,
    is_lite: bool,
    output_dir: str | Path,
    file_prefix: str,
    *,
    ipts: int,
    lam_min: float | None = None,
    lam_max: float | None = None,
    nexus_path: str | Path | None = None,
    monitor_index: int = 1,
    rebin_step: float = 0.0015,
    dip_threshold: float = 0.98,
    sigma_smooth: int = 3,
    continuum_window: int = 1500,
    continuum_method: str = "clip_peaks",
    continuum_percentile: float = 75.0,
    clip_win_size: int = 15,
    clip_smoothing: float = 5.0,
    min_width_aa: float = 0.01,
    merge_gap_aa: float = 0.05,
    edge_pad_aa: float = 0.01,
    suffix_units: str = "Wavelength",
    keep_diagnostics: bool = True,
    workspace_prefix: str | None = None,
    monitor2_l2: float | None = None,
) -> tuple[list[Path], list[list[float]]]:
    """Build a swiss-cheese mask by identifying notches in the transmission monitor.

    Pipeline:

    1. ``LoadNexusMonitors`` → ``ConvertUnits`` (Wavelength) → ``Rebin``.
    2. ``ExtractSingleSpectrum`` to isolate the transmission monitor
       (workspace index ``monitor_index``; default 1 for SNAP).
    3. :func:`detect_notches_in_spectrum` (pure numpy).
    4. ``swissCheese.notchFromList`` → save JSON.

    Wavelength bounds default to the SNAPRed instrument-state
    ``particleBounds.wavelength`` if ``lam_min``/``lam_max`` are ``None``.

    Args:
        run_number: SNAP run number to process.
        is_lite: Lite mode flag (passed to ``notchFromList`` and SNAPRed).
        output_dir: Directory in which mask JSON files are written.
        file_prefix: Filename stem for saved mask files.
        ipts: IPTS experiment number (used to resolve nexus path when
            *nexus_path* is ``None``).
        lam_min, lam_max: Optional wavelength limits (Å). If omitted, the
            instrument state is queried via ``snapred.SousChef``.
        nexus_path: Optional override for raw nexus path.
        monitor_index: Workspace index of the transmission monitor (default 1).
        rebin_step: Bin step passed straight to Mantid's ``Rebin``.
            Positive → linear bins of width ``rebin_step`` Å.
            Negative → logarithmic bins with constant
            Δλ/λ = ``|rebin_step|``. Default ``0.0015`` (linear, fine).
            Log binning matches the TOF instrument's natural resolution
            profile and is usually preferable; pass e.g. ``-0.0015``.
        dip_threshold, sigma_smooth, continuum_window, continuum_method,
            continuum_percentile, clip_win_size, min_width_aa, merge_gap_aa,
            edge_pad_aa: Forwarded to :func:`detect_notches_in_spectrum`.
            Defaults here are the **production-tuned** values for SNAP
            diamond-anvil-cell transmission monitors (verified
            interactively via ``scripts/inspect_transmission_notches.py``):
            ``clip_peaks`` SNIP continuum with ``continuum_window=1500``,
            ``clip_win_size=15``, ``clip_smoothing=5``, ``dip_threshold=0.98``,
            ``min_width_aa=0.01``, ``merge_gap_aa=0.05``, ``edge_pad_aa=0.01``.
            See :func:`detect_notches_in_spectrum` for the available
            ``continuum_method`` strategies (``"median"``, ``"percentile"``,
            ``"clip_peaks"``).
        suffix_units: Units label for the saved mask (default "Wavelength").
        keep_diagnostics: When ``True`` (default for direct interactive
            calls), the intermediate workspaces (monitor, rebinned, single
            spectrum) **and** a per-mask diagnostic workspace
            ``{workspace_prefix}_diag`` (rows ``raw``, ``smoothed``,
            ``continuum``, ``ratio`` — plus the SNIP intermediates when
            ``continuum_method="clip_peaks"``) are moved into the per-run
            diagnostics group ``wrap_diagnostics_{run_number}`` so the
            operator can inspect them in Mantid Workbench.  When ``False``
            all intermediates are deleted.
        workspace_prefix: Optional override for ADS workspace names. Defaults
            to ``f"snapwrap_trans_{run_number}"``.
        monitor2_l2: Optional corrected L2 distance (metres) for
            ``monitor2``.  When provided, ``MoveInstrumentComponent`` is
            applied to the loaded monitor workspace (still in TOF) to
            reposition ``monitor2`` at ``(0, 0, L2)`` **before**
            ``ConvertUnits`` is called.  This corrects an instrument
            calibration error in the recorded nexus geometry.  Default
            ``None`` (no correction applied).  Example: ``4.910``.

    Returns:
        ``(mask_paths, notches)`` — list of saved mask JSON paths and the
        ``[lam_min, lam_max]`` list used to build them.
    """
    import numpy as np

    nexus = Path(nexus_path) if nexus_path is not None else _raw_nexus_path(ipts, run_number)
    if not nexus.exists():
        raise FileNotFoundError(f"Raw nexus file not found: {nexus}")

    # Determine wavelength bounds via SousChef if not supplied.
    if lam_min is None or lam_max is None:
        try:
            SR = _importlib.import_module("snapred.backend.service.SousChef").SousChef
            FFI = _importlib.import_module(
                "snapred.backend.dao.request.FarmFreshIngredients"
            ).FarmFreshIngredients
            ssm = _importlib.import_module("snapwrap.snapStateMgr")
            state_id, _ = ssm.stateDef(run_number)
            ff = FFI(
                runNumber=str(run_number),
                useLiteMode=is_lite,
                focusGroups=[{"name": "Column", "definition": ""}],
                state=state_id,
            )
            inst_state = SR().prepInstrumentState(ff)
            if lam_min is None:
                lam_min = float(inst_state.particleBounds.wavelength.minimum)
            if lam_max is None:
                lam_max = float(inst_state.particleBounds.wavelength.maximum)
        except Exception:  # pragma: no cover — external deps in real env
            lam_min = lam_min if lam_min is not None else 0.5
            lam_max = lam_max if lam_max is not None else 5.0

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = workspace_prefix or f"snapwrap_trans_{run_number}"
    mon_ws = f"{prefix}_monitors"
    rebinned_ws = f"{prefix}_rebinned"
    spec_ws = f"{prefix}_spectrum"
    diag_ws = f"{prefix}_diag"

    _mantid.LoadNexusMonitors(
        Filename=str(nexus), OutputWorkspace=mon_ws, LoadOnly="Events"
    )
    diagnostic_ws = [mon_ws, rebinned_ws, spec_ws]
    try:
        # Optional: correct monitor2 L2 before unit conversion.
        # ConvertUnits uses the recorded source-to-detector distance, so any
        # geometry error must be fixed here, while the data is still in TOF.
        if monitor2_l2 is not None:
            _mantid.MoveInstrumentComponent(
                Workspace=mon_ws,
                ComponentName="monitor2",
                X=0.0,
                Y=0.0,
                Z=float(monitor2_l2),
                RelativePosition=False,
            )
        _mantid.ConvertUnits(
            InputWorkspace=mon_ws, OutputWorkspace=mon_ws, Target="Wavelength"
        )
        # Sign of rebin_step follows Mantid's Rebin convention:
        #   positive → linear bins of width |rebin_step| Å,
        #   negative → logarithmic bins of constant Δλ/λ = |rebin_step|.
        params = f"{lam_min},{float(rebin_step)},{lam_max}"
        _mantid.Rebin(
            InputWorkspace=mon_ws,
            OutputWorkspace=rebinned_ws,
            Params=params,
            PreserveEvents=False,
            FullBinsOnly=True,
        )
        _mantid.ConvertToPointData(
            InputWorkspace=rebinned_ws,
            OutputWorkspace=rebinned_ws,
        )
        _mantid.ExtractSingleSpectrum(
            InputWorkspace=rebinned_ws,
            OutputWorkspace=spec_ws,
            WorkspaceIndex=monitor_index,
        )

        x = np.asarray(_mantid.mtd[spec_ws].readX(0), dtype=float)
        y = np.asarray(_mantid.mtd[spec_ws].readY(0), dtype=float)
        centers = x  # point data after ConvertToPointData

        notches, diag = detect_notches_in_spectrum(
            centers,
            y,
            sigma_smooth=sigma_smooth,
            continuum_window=continuum_window,
            continuum_method=continuum_method,
            continuum_percentile=continuum_percentile,
            clip_win_size=clip_win_size,
            clip_smoothing=clip_smoothing,
            dip_threshold=dip_threshold,
            min_width_aa=min_width_aa,
            merge_gap_aa=merge_gap_aa,
            edge_pad_aa=edge_pad_aa,
        )

        # Publish a stacked diagnostic workspace iff we're keeping diagnostics.
        if keep_diagnostics:
            # Always-present rows: raw, smoothed, continuum, ratio.
            rows = [
                ("raw",        y),
                ("smoothed",   diag["smoothed"]),
                ("continuum",  diag["continuum"]),
                ("ratio",      diag["ratio"]),
            ]
            # clip_peaks adds SNIP-specific intermediates so the operator
            # can verify the inverted spectrum that SNIP actually saw and
            # the SNIP-fitted background BEFORE the back-mapping step.
            if "clip_y_inv" in diag:
                rows.extend([
                    ("clip_y_inv",   diag["clip_y_inv"]),   # SNIP input
                    ("clip_bg_inv",  diag["clip_bg_inv"]),  # SNIP output
                ])
            n_rows = len(rows)
            labels = [r[0] for r in rows]
            stacked_y = np.concatenate([r[1] for r in rows])
            stacked_x = np.tile(x, n_rows)
            _mantid.CreateWorkspace(
                OutputWorkspace=diag_ws,
                DataX=stacked_x.tolist(),
                DataY=stacked_y.tolist(),
                NSpec=n_rows,
                UnitX="Wavelength",
                VerticalAxisUnit="Text",
                VerticalAxisValues=labels,
            )
            diagnostic_ws.append(diag_ws)

            # ── Notch list as a sortable TableWorkspace ──────────────────
            notches_ws = f"{prefix}_notches"
            if _mantid.mtd.doesExist(notches_ws):
                _mantid.mtd.remove(notches_ws)
            tab = _mantid.CreateEmptyTableWorkspace(OutputWorkspace=notches_ws)
            tab.addColumn("double", "lam_min")
            tab.addColumn("double", "lam_max")
            tab.addColumn("double", "width")
            for lo, hi in notches:
                tab.addRow([float(lo), float(hi), float(hi - lo)])
            diagnostic_ws.append(notches_ws)

            # ── "Kept" overlay: ratio + ratio-with-notches-masked-to-NaN ─
            # Two spectra on a shared x-axis (Plot Spectra → All gives the
            # full notch-identification view in one click).  Add a
            # horizontal marker at y=dip_threshold to see where the cut
            # falls relative to kept bins.
            kept_ws = f"{prefix}_kept"
            if _mantid.mtd.doesExist(kept_ws):
                _mantid.mtd.remove(kept_ws)
            ratio_y = np.asarray(diag["ratio"], dtype=float)
            kept_y = ratio_y.copy()
            mask = np.zeros(kept_y.size, dtype=bool)
            for lo, hi in notches:
                mask |= (x >= lo) & (x <= hi)
            kept_y[mask] = np.nan
            _mantid.CreateWorkspace(
                OutputWorkspace=kept_ws,
                DataX=np.tile(x, 2).tolist(),
                DataY=np.concatenate([ratio_y, kept_y]).tolist(),
                NSpec=2,
                UnitX="Wavelength",
                VerticalAxisUnit="Text",
                VerticalAxisValues=["ratio", "kept"],
            )
            diagnostic_ws.append(kept_ws)

        sc = _swissCheese()
        sc.notchFromList(suffix_units, notches, is_lite)
        sc.save(str(output_dir), file_prefix)
        mask_paths = sorted(output_dir.glob(f"{file_prefix}_*.json"))

        diag_png_path: Path | None = None
        if keep_diagnostics:
            diag_png_path = _save_notch_diagnostic_plot(
                x=centers,
                ratio=diag["ratio"],
                notches=notches,
                dip_threshold=dip_threshold,
                output_path=output_dir / f"{file_prefix}_diag.png",
                run_number=run_number,
            )

        return mask_paths, notches, diag_png_path
    finally:
        from .workspace_groups import finalize_builder_workspaces

        finalize_builder_workspaces(
            run_number=run_number,
            artefact_ws=(),  # monitor mask is a JSON file, no ADS artefact
            diagnostic_ws=diagnostic_ws,
            keep_diagnostics=keep_diagnostics,
        )


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
