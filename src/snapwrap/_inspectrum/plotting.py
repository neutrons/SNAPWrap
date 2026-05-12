"""
Diagnostic plotting for snapwrap._inspectrum.

Quick-look visualisation of diffraction spectra and pipeline
intermediate results.  These are development/inspection helpers,
not publication-quality figures.

All functions return the matplotlib ``(fig, ax)`` tuple so you can
further customise or save::

    fig, ax = plot_spectrum(spectrum)
    fig.savefig("quick_look.png", dpi=150)

Functions that overlay multiple datasets (e.g. background + peaks)
use a consistent colour scheme:

- blue:   observed data
- orange: estimated background
- green:  peak-only signal
- red:    calculated/expected tick marks
- mixed:  per-phase matched ticks in score order
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from numpy.typing import NDArray

from snapwrap._inspectrum.lattice import LatticeRefinementResult
from snapwrap._inspectrum.matching import MatchResult
from snapwrap._inspectrum.models import DiffractionSpectrum
from snapwrap._inspectrum.peakfinding import PeakTable


def plot_spectrum(
    spectrum: DiffractionSpectrum,
    *,
    title: str | None = None,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    """Plot a single diffraction spectrum.

    Args:
        spectrum: Spectrum to plot.
        title: Override for the plot title (default: spectrum label).
        ax: Existing axes to draw on.  A new figure is created if None.

    Returns:
        ``(fig, ax)`` tuple.
    """
    fig, ax = _get_fig_ax(ax)
    ax.plot(spectrum.x, spectrum.y, linewidth=0.6, color="C0")
    ax.set_xlabel(spectrum.x_unit)
    ax.set_ylabel(spectrum.y_unit)
    ax.set_title(title or spectrum.label or "Spectrum")
    return fig, ax


def plot_background(
    spectrum: DiffractionSpectrum,
    background: NDArray[np.float64],
    peaks: NDArray[np.float64],
    *,
    title: str | None = None,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    """Overlay observed data, estimated background, and peak signal.

    Args:
        spectrum: Original observed spectrum.
        background: Background estimate (same length as spectrum.y).
        peaks: Peak-only signal (spectrum.y − background).
        title: Override for the plot title.
        ax: Existing axes to draw on.

    Returns:
        ``(fig, ax)`` tuple.
    """
    fig, ax = _get_fig_ax(ax)
    ax.plot(
        spectrum.x, spectrum.y, linewidth=0.6, color="C0", label="observed", alpha=0.7
    )
    ax.plot(spectrum.x, background, linewidth=1.0, color="C1", label="background")
    ax.plot(spectrum.x, peaks, linewidth=0.5, color="C2", label="peaks", alpha=0.6)
    ax.set_xlabel(spectrum.x_unit)
    ax.set_ylabel(spectrum.y_unit)
    ax.set_title(title or f"{spectrum.label or 'Spectrum'} — background")
    ax.legend(fontsize="small")
    return fig, ax


def plot_peak_markers(
    spectrum: DiffractionSpectrum,
    peaks: NDArray[np.float64],
    *,
    observed_positions: NDArray[np.float64] | PeakTable | None = None,
    reflections: list[dict[str, Any]] | None = None,
    title: str | None = None,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    """Plot peak-only signal with observed and/or calculated tick marks.

    Vertical lines mark peak positions:

    - **Red ticks (top)**: calculated d-spacings from ``reflections``
    - **Blue ticks (bottom)**: observed peak positions

    Args:
        spectrum: Original spectrum (provides the x-axis).
        peaks: Background-subtracted peak signal.
        observed_positions: Observed peak d-spacings — either an array
            or a :class:`~snapwrap._inspectrum.peakfinding.PeakTable` (optional).
        reflections: List of reflection dicts from
            :func:`~snapwrap._inspectrum.crystallography.generate_reflections`
            (optional).  Each dict must have a ``"d"`` key.
        title: Override for the plot title.
        ax: Existing axes to draw on.

    Returns:
        ``(fig, ax)`` tuple.
    """
    fig, ax = _get_fig_ax(ax)
    ax.plot(spectrum.x, peaks, linewidth=0.5, color="C2", label="peaks")

    y_max = float(np.max(peaks)) if len(peaks) > 0 else 1.0

    if reflections is not None:
        calc_d = np.array([r["d"] for r in reflections])
        ax.vlines(
            calc_d,
            ymin=y_max * 0.85,
            ymax=y_max,
            colors="C3",
            linewidth=0.8,
            label="calc d",
        )

    if observed_positions is not None:
        if isinstance(observed_positions, PeakTable):
            obs_d = observed_positions.positions
            obs_fwhm = observed_positions.fwhm
            # Horizontal bars showing FWHM at 10% of y_max
            bar_y = y_max * 0.08
            ax.hlines(
                [bar_y] * len(obs_d),
                obs_d - obs_fwhm / 2,
                obs_d + obs_fwhm / 2,
                colors="C0",
                linewidth=1.5,
                alpha=0.6,
                label="obs FWHM",
            )
        else:
            obs_d = observed_positions
        ax.vlines(
            obs_d,
            ymin=0,
            ymax=y_max * 0.15,
            colors="C0",
            linewidth=0.8,
            label="obs peaks",
        )

    ax.set_xlabel(spectrum.x_unit)
    ax.set_ylabel(spectrum.y_unit)
    ax.set_title(title or f"{spectrum.label or 'Spectrum'} — peak markers")
    ax.legend(fontsize="small")
    return fig, ax


def build_match_table(
    obs_d: NDArray[np.float64],
    match_result: MatchResult,
    *,
    precision: int = 5,
    blank: str = "",
) -> tuple[list[str], list[list[str]]]:
    """Build a row-aligned phase-match table.

    Each row corresponds to one observed peak.  Phase columns contain
    the matched strained d-spacing for that observed peak, or ``blank``
    if that phase did not claim the peak.

    Args:
        obs_d: Observed peak d-spacings in the same order used for
            matching.
        match_result: Match result from :mod:`snapwrap._inspectrum.matching`.
        precision: Decimal places for formatted d-spacings.
        blank: Placeholder for unmatched cells.

    Returns:
        Tuple ``(headers, rows)`` where headers is a list of column
        names and rows is a list of string rows.
    """
    headers = ["observed_d"] + [pm.phase_name for pm in match_result.phase_matches]
    phase_maps = [
        {mp.obs_idx: mp.strained_d for mp in pm.matched_peaks}
        for pm in match_result.phase_matches
    ]

    rows: list[list[str]] = []
    for obs_idx, obs_val in enumerate(obs_d):
        row = [f"{float(obs_val):.{precision}f}"]
        for phase_map in phase_maps:
            strained_d = phase_map.get(obs_idx)
            if strained_d is None:
                row.append(blank)
            else:
                row.append(f"{float(strained_d):.{precision}f}")
        rows.append(row)

    return headers, rows


def format_match_table(
    obs_d: NDArray[np.float64],
    match_result: MatchResult,
    *,
    precision: int = 5,
    blank: str = "",
) -> str:
    """Format a phase-match table as aligned plain text.

    Args:
        obs_d: Observed peak d-spacings in the same order used for
            matching.
        match_result: Match result to render.
        precision: Decimal places for formatted d-spacings.
        blank: Placeholder for unmatched cells.

    Returns:
        Plain-text table suitable for console output.
    """
    headers, rows = build_match_table(
        obs_d,
        match_result,
        precision=precision,
        blank=blank,
    )
    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    def _fmt_row(values: Sequence[str]) -> str:
        return " | ".join(value.ljust(widths[i]) for i, value in enumerate(values))

    divider = "-+-".join("-" * width for width in widths)
    lines = [_fmt_row(headers), divider]
    lines.extend(_fmt_row(row) for row in rows)
    return "\n".join(lines)


def summarize_phase_matches(
    spectrum: DiffractionSpectrum,
    peaks: NDArray[np.float64],
    match_result: MatchResult,
    *,
    observed_positions: NDArray[np.float64] | PeakTable,
    phase_reflections: dict[str, list[dict[str, Any]]] | None = None,
    refinements: list[LatticeRefinementResult] | None = None,
    title: str | None = None,
    precision: int = 5,
    blank: str = "",
    ax: Axes | None = None,
) -> tuple[Figure, Axes, str]:
    """Return the plot and formatted table for a phase-matching result.

    This is the main UI-facing helper for reviewing fit quality. It
    generates the overlay figure and a row-aligned text table in one
    call so callers do not have to keep the plotting and formatting
    logic in sync.

    Args:
        spectrum: Spectrum used for the x-axis and labels.
        peaks: Background-subtracted peak signal.
        match_result: Match result to visualise.
        observed_positions: Observed peak positions or full peak table.
        phase_reflections: Optional per-phase reflection lists for
            showing all expected strained ticks.
        title: Optional plot title override.
        precision: Decimal places for formatted d-spacings.
        blank: Placeholder for unmatched cells in the table.
        ax: Existing axes to draw on.

    Returns:
        Tuple ``(fig, ax, table_text)``.
    """
    fig, ax = plot_phase_matches(
        spectrum,
        peaks,
        match_result,
        observed_positions=observed_positions,
        phase_reflections=phase_reflections,
        refinements=refinements,
        title=title,
        ax=ax,
    )
    obs_d = (
        observed_positions.positions
        if isinstance(observed_positions, PeakTable)
        else observed_positions
    )
    table_text = format_match_table(
        obs_d,
        match_result,
        precision=precision,
        blank=blank,
    )
    return fig, ax, table_text


def plot_phase_matches(
    spectrum: DiffractionSpectrum,
    peaks: NDArray[np.float64],
    match_result: MatchResult,
    *,
    observed_positions: NDArray[np.float64] | PeakTable | None = None,
    phase_reflections: dict[str, list[dict[str, Any]]] | None = None,
    refinements: list[LatticeRefinementResult] | None = None,
    title: str | None = None,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    """Plot matched phase tick marks on top of the peak-only signal.

    Observed peaks are drawn near the bottom of the plot.  Each phase
    gets its own coloured tick band near the top, using the strained
    d-spacings from ``match_result``.

    Args:
        spectrum: Spectrum providing x-axis, labels, and plot title.
        peaks: Background-subtracted peak signal.
        match_result: Phase-match result to visualise.
        observed_positions: Observed peak positions or full peak table.
        phase_reflections: Optional per-phase reflection lists. When
            provided, all strained reflection positions are drawn in a
            faint style and the matched subset is overlaid more strongly.
        refinements: Optional per-phase lattice refinement results.
            When provided, legend labels and an annotation box show
            refined lattice parameters and EOS-derived pressures.
        title: Optional plot title override.
        ax: Existing axes to draw on.

    Returns:
        ``(fig, ax)`` tuple.
    """
    fig, ax = _get_fig_ax(ax)
    ax.plot(spectrum.x, peaks, linewidth=0.5, color="C2", label="peaks")

    y_max = float(np.max(peaks)) if len(peaks) > 0 else 1.0

    # Build name->refinement lookup
    ref_by_name: dict[str, LatticeRefinementResult] = {}
    if refinements is not None:
        ref_by_name = {r.phase_name: r for r in refinements}

    if observed_positions is not None:
        if isinstance(observed_positions, PeakTable):
            obs_d = observed_positions.positions
            obs_fwhm = observed_positions.fwhm
            bar_y = y_max * 0.08
            ax.hlines(
                [bar_y] * len(obs_d),
                obs_d - obs_fwhm / 2,
                obs_d + obs_fwhm / 2,
                colors="C0",
                linewidth=1.5,
                alpha=0.6,
                label="obs FWHM",
            )
        else:
            obs_d = observed_positions
        ax.vlines(
            obs_d,
            ymin=0,
            ymax=y_max * 0.15,
            colors="C0",
            linewidth=0.8,
            alpha=0.9,
            label="obs peaks",
        )

    n_phases = max(len(match_result.phase_matches), 1)
    top = 0.98
    bottom = 0.62
    band_height = (top - bottom) / n_phases
    phase_colors = [f"C{i}" for i in range(3, 10)]

    for phase_idx, phase_match in enumerate(match_result.phase_matches):
        y0 = y_max * (top - (phase_idx + 1) * band_height)
        y1 = y0 + y_max * band_height * 0.7
        color = phase_colors[phase_idx % len(phase_colors)]
        refs = None
        if phase_reflections is not None:
            refs = phase_reflections.get(phase_match.phase_name)

        if refs:
            ref = ref_by_name.get(phase_match.phase_name)
            if ref is not None and ref.success:
                all_positions = np.array(
                    [ref.d_spacing(*tuple(int(x) for x in r["hkl"])) for r in refs],
                    dtype=np.float64,
                )
            else:
                all_positions = np.array(
                    [phase_match.strain * float(r["d"]) for r in refs],
                    dtype=np.float64,
                )
            ax.vlines(
                all_positions,
                ymin=y0,
                ymax=y1,
                colors=color,
                linewidth=0.9,
                alpha=0.25,
            )

        ref = ref_by_name.get(phase_match.phase_name)
        if ref is not None and ref.success:
            phase_positions = np.array(
                [ref.d_spacing(*mp.hkl) for mp in phase_match.matched_peaks],
                dtype=np.float64,
            )
        else:
            phase_positions = np.array(
                [mp.strained_d for mp in phase_match.matched_peaks],
                dtype=np.float64,
            )
        if len(phase_positions) == 0:
            continue

        if ref is not None and ref.success:
            if ref.crystal_system == "cubic":
                params = f"a={ref.a:.4f}"
            elif ref.crystal_system in ("tetragonal", "hexagonal", "trigonal"):
                params = f"a={ref.a:.4f}, c={ref.c:.4f}"
            else:
                params = f"a={ref.a:.4f}, b={ref.b:.4f}, c={ref.c:.4f}"
            p_str = (
                f", P={ref.pressure_gpa:.1f} GPa"
                if ref.pressure_gpa is not None
                else ""
            )
            lbl = (
                f"{phase_match.phase_name} ({params}{p_str}, n={phase_match.n_matched})"
            )
        else:
            lbl = (
                f"{phase_match.phase_name} "
                f"(s={phase_match.strain:.4f}, n={phase_match.n_matched})"
            )

        ax.vlines(
            phase_positions,
            ymin=y0,
            ymax=y1,
            colors=color,
            linewidth=1.8,
            label=lbl,
        )

    ax.set_xlabel(spectrum.x_unit)
    ax.set_ylabel(spectrum.y_unit)
    ax.set_title(title or f"{spectrum.label or 'Spectrum'} — phase matches")
    ax.legend(fontsize="small")

    # Annotation box with refinement summary
    if ref_by_name:
        lines = []
        for r in refinements or []:
            if not r.success:
                continue
            p_str = (
                f"  P = {r.pressure_gpa:.2f} GPa" if r.pressure_gpa is not None else ""
            )
            if r.crystal_system == "cubic":
                lines.append(
                    f"{r.phase_name}: a={r.a:.5f} \u00c5, V={r.volume:.2f} \u00c5\u00b3{p_str}"
                )
            elif r.crystal_system in ("tetragonal", "hexagonal", "trigonal"):
                lines.append(
                    f"{r.phase_name}: a={r.a:.5f}, c={r.c:.5f} \u00c5, V={r.volume:.2f} \u00c5\u00b3{p_str}"
                )
            else:
                lines.append(
                    f"{r.phase_name}: a={r.a:.4f}, b={r.b:.4f}, c={r.c:.4f} \u00c5{p_str}"
                )
        if lines:
            ax.text(
                0.02,
                0.97,
                "\n".join(lines),
                transform=ax.transAxes,
                fontsize=7,
                verticalalignment="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.7),
            )

    return fig, ax


def inspect_phase_matches(
    spectrum: DiffractionSpectrum,
    peaks: NDArray[np.float64],
    match_result: MatchResult,
    *,
    observed_positions: NDArray[np.float64] | PeakTable,
    phase_reflections: dict[str, list[dict[str, Any]]] | None = None,
    refinements: list[LatticeRefinementResult] | None = None,
    title: str | None = None,
    precision: int = 5,
    blank: str = "-",
    show: bool = True,
) -> tuple[Figure, Axes, str]:
    """Open an interactive phase-match inspection view and print a table.

    This mirrors :func:`inspect_peaks` for the match-review stage. It
    opens the overlay figure, prints the formatted match table to the
    console, and returns both the figure and table for further use.

    Args:
        spectrum: Spectrum used for plotting.
        peaks: Background-subtracted peak signal.
        match_result: Match result to review.
        observed_positions: Observed peak positions or full peak table.
        phase_reflections: Optional per-phase reflection lists for
            showing all expected strained ticks.
        title: Optional plot title override.
        precision: Decimal places for formatted d-spacings.
        blank: Placeholder for unmatched cells in the table.
        show: Whether to open the matplotlib window.

    Returns:
        Tuple ``(fig, ax, table_text)``.
    """
    fig, ax, table_text = summarize_phase_matches(
        spectrum,
        peaks,
        match_result,
        observed_positions=observed_positions,
        phase_reflections=phase_reflections,
        refinements=refinements,
        title=title,
        precision=precision,
        blank=blank,
    )
    if show:
        plt.show(block=False)
    print("\nMatch table:")
    print(table_text)
    return fig, ax, table_text


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_fig_ax(ax: Axes | None) -> tuple[Figure, Axes]:
    """Return (fig, ax), creating a new figure if *ax* is None."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    else:
        fig = ax.get_figure()
    return fig, ax


# ---------------------------------------------------------------------------
# Interactive inspection
# ---------------------------------------------------------------------------


def inspect_peaks(
    spectrum: DiffractionSpectrum,
    *,
    win_size: int = 40,
    decrease: bool = True,
    lls: bool = True,
    smoothing: float = 5.0,
    min_prominence: float | None = None,
    min_width_pts: int = 5,
) -> PeakTable:
    """Run the full pipeline and open an interactive 3-panel figure.

    Panels (top to bottom):

    1. **Raw data** — observed spectrum as-is.
    2. **Background subtraction** — observed (blue) + estimated
       background (orange) + peak-only residual (green).
    3. **Peak detection** — peak-only signal (green) with red
       vertical lines at each detected peak position.

    The matplotlib window provides **zoom** (rectangle-zoom icon or
    scroll wheel), **pan** (hand icon), and a **crosshair cursor**
    that reports ``(d, intensity)`` coordinates in the bottom-left
    corner of the toolbar.

    All background and peak-finding parameters are forwarded (see
    :func:`~snapwrap._inspectrum.background.estimate_background` and
    :func:`~snapwrap._inspectrum.peakfinding.find_peaks_in_spectrum`).

    Args:
        spectrum: Spectrum to inspect.
        win_size: Background estimator half-window size.
        decrease: Background estimator scan direction.
        lls: Apply LLS transform during background estimation.
        smoothing: Gaussian smoothing σ for background estimation.
        min_prominence: Peak prominence threshold (None = auto).
        min_width_pts: Minimum peak FWHM in data points.

    Returns:
        :class:`~snapwrap._inspectrum.peakfinding.PeakTable` of detected peaks
        (so you can inspect it programmatically too).
    """
    from matplotlib.widgets import Cursor

    from snapwrap._inspectrum.background import estimate_background
    from snapwrap._inspectrum.peakfinding import find_peaks_in_spectrum

    # --- Run pipeline ---
    bg, peaks_y = estimate_background(
        spectrum.y,
        win_size=win_size,
        decrease=decrease,
        lls=lls,
        smoothing=smoothing,
    )
    peak_table = find_peaks_in_spectrum(
        spectrum.x,
        peaks_y,
        min_prominence=min_prominence,
        min_width_pts=min_width_pts,
    )

    # --- Build figure ---
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(12, 9),
        sharex=True,
        gridspec_kw={"hspace": 0.08},
    )

    # Panel 1: raw data
    ax1 = axes[0]
    ax1.plot(spectrum.x, spectrum.y, linewidth=0.6, color="C0")
    ax1.set_ylabel(spectrum.y_unit)
    ax1.set_title(f"{spectrum.label or 'Spectrum'} — raw data")

    # Panel 2: background subtraction
    ax2 = axes[1]
    ax2.plot(
        spectrum.x, spectrum.y, linewidth=0.5, color="C0", label="observed", alpha=0.5
    )
    ax2.plot(spectrum.x, bg, linewidth=1.0, color="C1", label="background")
    ax2.plot(spectrum.x, peaks_y, linewidth=0.5, color="C2", label="peaks", alpha=0.7)
    ax2.set_ylabel(spectrum.y_unit)
    ax2.set_title("Background subtraction")
    ax2.legend(fontsize="small", loc="upper right")

    # Panel 3: peaks with markers
    ax3 = axes[2]
    ax3.plot(spectrum.x, peaks_y, linewidth=0.5, color="C2")
    if peak_table.n_peaks > 0:
        ax3.vlines(
            peak_table.positions,
            ymin=0,
            ymax=peak_table.heights,
            colors="C3",
            linewidth=0.8,
            alpha=0.8,
            label=f"{peak_table.n_peaks} peaks",
        )
        # Small dots at the apex
        ax3.plot(
            peak_table.positions,
            peak_table.heights,
            "v",
            color="C3",
            markersize=5,
        )
        # FWHM error-bar style: horizontal bars with end caps at half-max
        half_heights = peak_table.heights / 2.0
        ax3.errorbar(
            peak_table.positions,
            half_heights,
            xerr=peak_table.fwhm / 2,
            fmt="none",
            ecolor="k",
            elinewidth=1.5,
            capsize=4,
            capthick=1.5,
            alpha=0.8,
            label="FWHM",
        )
    ax3.set_xlabel(spectrum.x_unit)
    ax3.set_ylabel(spectrum.y_unit)
    ax3.set_title("Detected peaks")
    ax3.legend(fontsize="small", loc="upper right")

    # Crosshair cursor on all panels
    cursors = []
    for ax in axes:
        cursors.append(Cursor(ax, useblit=True, color="gray", linewidth=0.5))
    # Keep references alive so the cursors don't get garbage-collected
    fig._inspectrum_cursors = cursors  # type: ignore[attr-defined]

    fig.align_ylabels(axes)
    plt.show(block=False)

    # Print a summary to the console
    print(f"\n{'─' * 50}")
    print(f"  {peak_table.n_peaks} peaks detected")
    print(f"{'─' * 50}")
    for i in range(peak_table.n_peaks):
        print(
            f"  d = {peak_table.positions[i]:.4f} Å   "
            f"height = {peak_table.heights[i]:.1f}   "
            f"FWHM = {peak_table.fwhm[i]:.4f} Å   "
            f"Δ(apex→centroid) = "
            f"{peak_table.positions[i] - spectrum.x[peak_table.indices[i]]:.5f} Å"
        )
    print(f"{'─' * 50}\n")

    return peak_table
