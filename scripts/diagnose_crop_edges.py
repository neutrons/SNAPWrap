"""
Crop-edge diagnostic — paste into Mantid Workbench Script Editor and run.

Inspects the transition zones at the edges of cropped spectra and recommends
values for the two crop-tuning parameters:

  edge_bins    — expands each detected gap outward by N bins in the focused
                 synthetic workspace (absorbs the detector-2θ-spread ramp)
  min_coverage — fractional Y threshold: bins with Y ≤ min_coverage × max(Y)
                 in the focused synthetic workspace are counted as zero

The script auto-discovers workspaces from RUN_NUMBER and FOCUS_GROUP, or you
can set SOURCE_WS / CROPPED_WS directly.  If a diagnostic synthetic workspace
is present (requires running crop with "Retain diagnostics" checked), it is
analysed as well — that gives the most direct picture of what the gap-detector
sees before edge_bins/min_coverage are applied.
"""

import sys
import numpy as np
from mantid.api import mtd  # type: ignore  # noqa: F401

# ── Edit these ────────────────────────────────────────────────────────────────

RUN_NUMBER   = 65893      # <─ change to your run number
FOCUS_GROUP  = "column"   # focus group, lowercase (e.g. "column", "bank")
SOURCE_PREFIX = "resampled"  # "resampled" or "reduced"

# Override auto-discovery (set to None to auto-detect from the above):
SOURCE_WS  = None   # e.g. "resampled_dsp_column_065893"
CROPPED_WS = None   # e.g. "cropped_dsp_column_65893"

# Set to a file path to write output there instead of (or in addition to) the
# Workbench log, e.g. "/tmp/crop_diag.txt".  None = log only.
OUTPUT_FILE = "/tmp/crop_diag.txt"

# COMPACT = True  → only print the cross-spectrum ramp summary for each
#                   workspace (a ~10-line table).  Fast to read / paste.
# COMPACT = False → also print per-spectrum ramp tables and detailed bin
#                   tables around every edge/NaN boundary (very verbose).
COMPACT = True

# How many bins to show on each side of a transition boundary (verbose mode).
CONTEXT_BINS = 20

# Threshold fractions to report in the ramp-length summary.
# Extend to 0.90 so we can see the full detector-coverage ramp extent.
FRAC_LEVELS = [0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 0.90]

# ─────────────────────────────────────────────────────────────────────────────

_out_fh = open(OUTPUT_FILE, "w") if OUTPUT_FILE else None


def _pr(*args, **kwargs):
    print(*args, **kwargs)
    if _out_fh:
        print(*args, **kwargs, file=_out_fh)


def _find(patterns, run):
    tokens = [str(run), f"{run:06d}"]
    candidates = []
    for name in sorted(mtd.getObjectNames()):
        if name.startswith("__"):
            continue
        if not any(t in name for t in tokens):
            continue
        if all(p.lower() in name.lower() for p in patterns):
            candidates.append(name)
    return candidates[0] if candidates else None


def _ramp_lengths(y, y_max, thresholds):
    n = len(y)
    result = {}
    for frac in thresholds:
        thr = frac * y_max
        left = 0
        for i in range(n):
            if not np.isfinite(y[i]):
                break
            if abs(y[i]) <= thr:
                left += 1
            else:
                break
        right = 0
        for i in range(n - 1, -1, -1):
            if not np.isfinite(y[i]):
                break
            if abs(y[i]) <= thr:
                right += 1
            else:
                break
        result[frac] = (left, right)
    return result


def _print_edge_table(x, y, y_max, region, indices):
    n_bins = len(y)
    _pr(f"\n    ── {region} {len(list(indices))} bins ──")
    _pr(f"    {'bin':>5}  {'d-left':>8}  {'Y':>12}  {'|Y|/Ymax':>9}  note")
    for i in indices:
        if i < 0 or i >= n_bins:
            continue
        if not np.isfinite(y[i]):
            _pr(f"    {i:>5}  {x[i]:>8.4f}  {'NaN':>12}  {'---':>9}")
            continue
        frac = abs(y[i]) / y_max if y_max > 0 else 0.0
        note = ""
        if frac < 0.002:
            note = "< 0.2%"
        elif frac < 0.005:
            note = "< 0.5%"
        elif frac < 0.01:
            note = "< 1%"
        elif frac < 0.05:
            note = "< 5%"
        elif frac < 0.10:
            note = "< 10%"
        _pr(f"    {i:>5}  {x[i]:>8.4f}  {y[i]:>12.4g}  {frac:>9.4f}  {note}")


def _analyse_workspace(ws_name, label):
    if ws_name is None:
        _pr(f"\n  [{label}] not configured — skipping")
        return
    if ws_name not in mtd:
        _pr(f"\n  [{label}] '{ws_name}' not in ADS — skipping")
        return

    ws = mtd[ws_name]
    n = ws.getNumberHistograms()
    _pr(f"\n{'='*72}")
    _pr(f"[{label}]  {ws_name}  —  {n} spectrum/a")
    _pr(f"{'='*72}")

    all_left_ramps = {f: [] for f in FRAC_LEVELS}
    all_right_ramps = {f: [] for f in FRAC_LEVELS}

    for si in range(n):
        x = np.asarray(ws.readX(si))
        y = np.asarray(ws.readY(si))
        n_bins = len(y)
        finite_y = y[np.isfinite(y)]
        y_max = float(np.max(np.abs(finite_y))) if len(finite_y) else 1.0

        ramps = _ramp_lengths(y, y_max, FRAC_LEVELS)
        for frac in FRAC_LEVELS:
            lft, rgt = ramps[frac]
            all_left_ramps[frac].append(lft)
            all_right_ramps[frac].append(rgt)

        if not COMPACT:
            _pr(f"\n  Spectrum {si}: d∈[{x[0]:.4f}, {x[-1]:.4f}] Å, "
                f"{n_bins} bins, max|Y|={y_max:.4g}")
            _pr(f"  {'threshold':>10}  {'left ramp':>10}  {'right ramp':>11}")
            _pr(f"  {'─'*10}  {'─'*10}  {'─'*11}")
            for frac in FRAC_LEVELS:
                lft, rgt = ramps[frac]
                _pr(f"  {frac:>9.3f}  {lft:>9d}b  {rgt:>10d}b")

            left_end = min(CONTEXT_BINS, n_bins)
            right_start = max(0, n_bins - CONTEXT_BINS)
            _print_edge_table(x, y, y_max, f"first {left_end}", range(left_end))
            _print_edge_table(x, y, y_max, f"last  {CONTEXT_BINS}", range(right_start, n_bins))

            in_nan = False
            nan_starts = []
            for i, v in enumerate(y):
                if np.isnan(v) and not in_nan:
                    in_nan = True
                    nan_starts.append(i)
                elif not np.isnan(v) and in_nan:
                    in_nan = False
                    lo = max(0, i - CONTEXT_BINS // 2)
                    hi = min(n_bins, i + CONTEXT_BINS // 2)
                    _print_edge_table(x, y, y_max,
                                      f"NaN-end @ bin {i}",
                                      range(lo, hi))
            for ns in nan_starts:
                lo = max(0, ns - CONTEXT_BINS // 2)
                hi = min(n_bins, ns + CONTEXT_BINS // 2)
                _print_edge_table(x, y, y_max,
                                  f"NaN-start @ bin {ns}",
                                  range(lo, hi))

    # Cross-spectrum ramp summary (always printed)
    _pr(f"\n  ── Cross-spectrum ramp summary for [{label}] ──")
    _pr(f"  {'threshold':>10}  {'max_left':>9}  {'max_right':>10}")
    _pr(f"  {'─'*10}  {'─'*9}  {'─'*10}")
    for frac in FRAC_LEVELS:
        ml = max(all_left_ramps[frac]) if all_left_ramps[frac] else 0
        mr = max(all_right_ramps[frac]) if all_right_ramps[frac] else 0
        _pr(f"  {frac:>9.3f}  {ml:>8d}b  {mr:>9d}b")


# ── Auto-discover ──────────────────────────────────────────────────────────────

if SOURCE_WS is None:
    SOURCE_WS = _find([SOURCE_PREFIX, FOCUS_GROUP], RUN_NUMBER)
if CROPPED_WS is None:
    CROPPED_WS = (_find(["cropped", FOCUS_GROUP], RUN_NUMBER)
                  or _find([SOURCE_PREFIX, FOCUS_GROUP, "crop"], RUN_NUMBER))

diag_synth = _find(["crop_diag_synthetic"], RUN_NUMBER)
diag_foc   = _find(["crop_diag_focused", FOCUS_GROUP], RUN_NUMBER)

_pr(f"Auto-discovered:")
_pr(f"  Source          : {SOURCE_WS}")
_pr(f"  Cropped         : {CROPPED_WS}")
_pr(f"  Diag synthetic  : {diag_synth or '(not present — run crop with Retain diagnostics)'}")
_pr(f"  Diag focused    : {diag_foc   or '(not present)'}")
_pr(f"  Mode            : {'COMPACT (summaries only)' if COMPACT else 'VERBOSE (per-bin detail)'}")
if OUTPUT_FILE:
    _pr(f"  Output file     : {OUTPUT_FILE}")

# ── Run analysis ───────────────────────────────────────────────────────────────

_analyse_workspace(SOURCE_WS, "SOURCE (pre-crop)")
_analyse_workspace(CROPPED_WS, "CROPPED")

if diag_foc:
    _analyse_workspace(diag_foc, "DIAG FOCUSED SYNTHETIC")

# ── Guidance ───────────────────────────────────────────────────────────────────

_pr("""
╔══════════════════════════════════════════════════════════════════════════╗
║  HOW TO READ THESE RESULTS AND TUNE THE PARAMETERS                      ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  edge_bins:                                                              ║
║    The ramp at each gap edge is caused by detector 2θ spread — pixels   ║
║    that straddle the notch boundary contribute partial signal.           ║
║    edge_bins expands the DETECTED zero gap outward by N bins each side   ║
║    in the focused synthetic workspace.                                   ║
║                                                                          ║
║    From the cross-spectrum ramp summary above:                           ║
║      → Find the row where max_left/max_right ≈ 0  (the ramp has ended). ║
║        The threshold at that row is your min_coverage candidate.         ║
║      → The bin count in that row is your edge_bins candidate.            ║
║    Start with edge_bins = max(left, right) ramp length + 2 safety bins. ║
║                                                                          ║
║  min_coverage:                                                           ║
║    Bins in the focused synthetic workspace with Y ≤ min_coverage×max(Y) ║
║    are treated as zero.  In the synthetic workspace max(Y) ≈ 1.0.       ║
║    A value of 0.01 (1%) catches gentle ramps; 0.05-0.10 catches steep   ║
║    ramps and is safer for busy spectra.                                  ║
║                                                                          ║
║    Best approach: re-run crop with "Retain diagnostics" checked, then   ║
║    re-run this script — the DIAG FOCUSED SYNTHETIC section will show    ║
║    exactly what the gap detector sees and what threshold is needed.      ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
""")

if _out_fh:
    _out_fh.close()
    print(f"\nOutput written to: {OUTPUT_FILE}")
