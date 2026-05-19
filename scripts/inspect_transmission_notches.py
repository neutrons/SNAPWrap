"""Inspect transmission-monitor notch detection inside mantidworkbench.

Run this inside a mantidworkbench session (Script Editor → Run, or
``%run`` from the IPython console). All intermediate data is left in
the Analysis Data Service (ADS) so the workbench plotters / table
viewers can be used to tune detection parameters interactively.

What it does
------------
For a given SNAP run, runs the transmission-monitor swiss-cheese
pipeline with ``keep_diagnostics=True`` and publishes:

- ``snapwrap_trans_<run>_monitors``  — raw monitors after ConvertUnits.
- ``snapwrap_trans_<run>_rebinned``  — rebinned to wavelength.
- ``snapwrap_trans_<run>_spectrum``  — extracted transmission monitor.
- ``snapwrap_trans_<run>_diag``      — 4-row diagnostic workspace
  ``[raw, smoothed, continuum, ratio]`` versus wavelength. Plot rows
  0/1/2 together to visualise smoothing and the rolling-median
  continuum; plot row 3 against the ``DIP_THRESHOLD`` to see which
  bins triggered.
- ``snapwrap_trans_<run>_notches``   — TableWorkspace listing the
  detected notches (``lam_min``, ``lam_max``, ``width``).

Edit the CONFIG block below and re-run to iterate on parameters.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from mantid.simpleapi import *

import importlib, snapwrap.reduction_artefacts.masking as m
importlib.reload(m)



# ─── CONFIG ────────────────────────────────────────────────────────────────
RUN              = 65893
IPTS = GetIPTS(Instrument="SNAP",RunNumber=RUN)[-6:]
# IPTS             = 34952 # 33219
IS_LITE          = True
OUTPUT_DIR       = "/tmp/snapwrap_inspect"
FILE_PREFIX      = f"trans_inspect_{RUN}"

# Optional explicit nexus override (None → standard /SNS/SNAP/IPTS-.../nexus path)
NEXUS_PATH       = None

# Wavelength window — leave None to inherit from SNAPRed instrument state.
LAM_MIN          = None
LAM_MAX          = None

# Detection parameters (forwarded to detect_notches_in_spectrum)
REBIN_STEP        = 0.0015  # Mantid Rebin convention: +ve = linear (Å), -ve = log (Δλ/λ)
SIGMA_SMOOTH      = 3        # boxcar half-width (bins); 0 disables
CONTINUUM_WINDOW  = 1500     # rolling continuum window (bins); ≫ widest notch
CONTINUUM_METHOD  = "clip_peaks"
CONTINUUM_PCTL    = 75.0      # ignored when method != "percentile"
CLIP_WIN_SIZE     = 15        # SNIP rolling-ball half-window (bins)
CLIP_SMOOTHING    = 5.0       # SNIP's internal smoothing (set 0 to disable)
DIP_THRESHOLD     = 0.98     # bins where smoothed/continuum < this are flagged
MIN_WIDTH_AA      = 0.01     # Å — narrower notches discarded as noise
MERGE_GAP_AA      = 0.05     # Å — notches closer than this are merged
EDGE_PAD_AA       = 0.01     # Å — symmetric padding added to each notch edge
MONITOR_INDEX     = 1        # SNAP transmission monitor workspace index
# ───────────────────────────────────────────────────────────────────────────


def main() -> None:
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    mask_paths, notches = m.build_swiss_cheese_from_transmission_monitor(
        run_number=RUN,
        is_lite=IS_LITE,
        output_dir=OUTPUT_DIR,
        file_prefix=FILE_PREFIX,
        ipts=IPTS,
        nexus_path=NEXUS_PATH,
        lam_min=LAM_MIN,
        lam_max=LAM_MAX,
        rebin_step=REBIN_STEP,
        sigma_smooth=SIGMA_SMOOTH,
        continuum_window=CONTINUUM_WINDOW,
        continuum_method=CONTINUUM_METHOD,
        continuum_percentile=CONTINUUM_PCTL,
        clip_win_size=CLIP_WIN_SIZE,
        clip_smoothing=CLIP_SMOOTHING,
        dip_threshold=DIP_THRESHOLD,
        min_width_aa=MIN_WIDTH_AA,
        merge_gap_aa=MERGE_GAP_AA,
        edge_pad_aa=EDGE_PAD_AA,
        monitor_index=MONITOR_INDEX,
        keep_diagnostics=True,
    )

    # Build a sortable notches table for inspection.
    table_name = f"snapwrap_trans_{RUN}_notches"
    if mtd.doesExist(table_name):
        mtd.remove(table_name)
    tab = CreateEmptyTableWorkspace(OutputWorkspace=table_name)
    tab.addColumn("double", "lam_min")
    tab.addColumn("double", "lam_max")
    tab.addColumn("double", "width")
    for lo, hi in notches:
        tab.addRow([lo, hi, hi - lo])

    # Build a "kept-bins" overlay workspace with two spectra on a shared
    # x-axis (Plot Spectra → All gives the full notch-identification view
    # in one click):
    #   row 0  "ratio"  — the ratio spectrum (unmasked, full curve)
    #   row 1  "kept"   — ratio outside notches, NaN inside
    # Add a horizontal marker at y = DIP_THRESHOLD in the plot to see
    # exactly where the threshold cuts.
    spec_name = f"snapwrap_trans_{RUN}_spectrum"
    diag_name = f"snapwrap_trans_{RUN}_diag"
    kept_name = f"snapwrap_trans_{RUN}_kept"
    if mtd.doesExist(diag_name):
        d = mtd[diag_name]
        # Locate the `ratio` row by label (Text vertical axis).
        ax = d.getAxis(1)
        ratio_idx = None
        for i in range(d.getNumberHistograms()):
            try:
                if ax.label(i) == "ratio":
                    ratio_idx = i
                    break
            except Exception:
                pass
        if ratio_idx is None:
            ratio_idx = 3  # fall back to the documented row order
        x = np.asarray(d.readX(ratio_idx), dtype=float)
        ratio_y = np.asarray(d.readY(ratio_idx), dtype=float)
        kept_y = ratio_y.copy()
        centers = 0.5 * (x[:-1] + x[1:]) if x.size == kept_y.size + 1 else x
        mask = np.zeros(kept_y.size, dtype=bool)
        for lo, hi in notches:
            mask |= (centers >= lo) & (centers <= hi)
        kept_y[mask] = np.nan
        if mtd.doesExist(kept_name):
            mtd.remove(kept_name)
        CreateWorkspace(
            OutputWorkspace=kept_name,
            DataX=np.tile(x, 2).tolist(),
            DataY=np.concatenate([ratio_y, kept_y]).tolist(),
            NSpec=2,
            UnitX="Wavelength",
            VerticalAxisUnit="Text",
            VerticalAxisValues=["ratio", "kept"],
        )

    # Build a step-by-step "SNIP pipeline" workspace so each transformation
    # is independently inspectable. Rows differ by method:
    #
    #   "clip_peaks":  smoothed | clip_y_inv | clip_bg_inv | continuum
    #                  (rows 1, 4, 5, 2 of _diag if present)
    #   other:         smoothed | continuum
    overlay_name = f"snapwrap_trans_{RUN}_pipeline"
    if mtd.doesExist(diag_name):
        d = mtd[diag_name]
        ax = d.getAxis(1)
        # Map row label → row index (vertical Text axis).
        try:
            label_idx = {ax.label(i): i for i in range(d.getNumberHistograms())}
        except Exception:
            label_idx = {}
        dx = np.asarray(d.readX(0), dtype=float)

        wanted = ["smoothed"]
        if "clip_y_inv" in label_idx:
            # Full SNIP pipeline view, in execution order:
            #   smoothed (input to inverter) → clip_y_inv (SNIP input)
            #   → clip_bg_inv (SNIP output) → continuum (mapped back)
            wanted += ["clip_y_inv", "clip_bg_inv", "continuum"]
        else:
            wanted += ["continuum"]
        wanted = [w for w in wanted if w in label_idx]

        rows_y = [np.asarray(d.readY(label_idx[w]), dtype=float) for w in wanted]
        if mtd.doesExist(overlay_name):
            mtd.remove(overlay_name)
        CreateWorkspace(
            OutputWorkspace=overlay_name,
            DataX=np.tile(dx, len(wanted)).tolist(),
            DataY=np.concatenate(rows_y).tolist(),
            NSpec=len(wanted),
            UnitX="Wavelength",
            VerticalAxisUnit="Text",
            VerticalAxisValues=wanted,
        )
    print(f"\n{len(notches)} notches detected:")
    for lo, hi in notches:
        print(f"  [{lo:.4f}, {hi:.4f}]  width = {hi - lo:.4f} Å")
    print("\nMask JSON written to:")
    for p in mask_paths:
        print(f"  {p}")
    print("\nWorkspaces published to ADS for inspection:")
    print(f"  snapwrap_trans_{RUN}_monitors   (raw monitors, wavelength)")
    print(f"  snapwrap_trans_{RUN}_rebinned   (rebinned monitors)")
    print(f"  snapwrap_trans_{RUN}_spectrum   (transmission monitor only)")
    print(f"  snapwrap_trans_{RUN}_diag       (rows: raw, smoothed, continuum, ratio"
          + (", clip_y_inv, clip_bg_inv" if CONTINUUM_METHOD == "clip_peaks" else "")
          + ")")
    print(f"  snapwrap_trans_{RUN}_pipeline   ("
          + ("smoothed → clip_y_inv → clip_bg_inv → continuum"
             if CONTINUUM_METHOD == "clip_peaks"
             else "smoothed, continuum")
          + ")")
    print(f"  {kept_name}     (2 rows: ratio + kept — Plot Spectra → All for the notch view)")
    print(f"  {table_name}              (sortable notch list)")
    print(
        f"\nContinuum method: {CONTINUUM_METHOD}"
        + (f" (q={CONTINUUM_PCTL})" if CONTINUUM_METHOD == "percentile" else "")
        + (f" (win_size={CLIP_WIN_SIZE}, smoothing={CLIP_SMOOTHING})"
           if CONTINUUM_METHOD == "clip_peaks" else "")
    )
    if CONTINUUM_METHOD == "clip_peaks":
        print(
            "\nSNIP pipeline (inspect each step in *_pipeline):\n"
            "  smoothed     — boxcar-smoothed input spectrum (sigma_smooth bins).\n"
            "                  This is what gets inverted, NOT raw counts.\n"
            "  clip_y_inv   — y_max − smoothed (dips → peaks, all ≥ 0).\n"
            "                  THIS is the actual input fed to clip_peaks.\n"
            "  clip_bg_inv  — SNIP's fitted lower envelope of clip_y_inv\n"
            "                  (the inverted continuum).\n"
            "  continuum    — y_max − clip_bg_inv, then rescaled so the\n"
            "                  ratio's median equals 1 (flat baseline).\n"
            "If continuum is poor: plot clip_y_inv + clip_bg_inv overlaid —\n"
            "if SNIP's curve looks wrong there, the issue is win_size /\n"
            "smoothing, not the back-transform."
        )
    else:
        print(
            "\nTip: plot rows 0,1,2 of *_diag vs wavelength to see continuum fit;\n"
            f"     plot row 3 with a horizontal line at y={DIP_THRESHOLD} to see the threshold;\n"
            f"     overlay {kept_name} on the ratio row to see notch positions as gaps."
        )
    
    # postprocessing of  monitor spectrum
    ws = mtd[spec_name]
    yMax = np.max(ws.dataY(0))
    print(f"yMax is: {yMax}")
    Scale(InputWorkspace=spec_name,
        OutputWorkspace="mirror",
        Factor=-1,
        Operation="Multiply")
    Scale(InputWorkspace="mirror",
        OutputWorkspace="mirror",
        Factor=yMax,
        Operation="Add")
    # Rebin(InputWorkspace="mirror",
    #     OutputWorkspace="mirror_rr",
    #     Params=0.002)
        


if __name__ == "__main__":
    main()
else:
    # Workbench's Script Editor executes scripts with __name__ set to the
    # filename (not "__main__"), so the guard above won't fire there.
    main()
