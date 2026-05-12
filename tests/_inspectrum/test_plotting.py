"""Tests for plotting helpers that summarise phase matches."""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")

from snapwrap._inspectrum.matching import MatchedPeak, MatchResult, PhaseMatch
from snapwrap._inspectrum.models import DiffractionSpectrum
from snapwrap._inspectrum.plotting import (
    build_match_table,
    format_match_table,
    inspect_phase_matches,
    plot_phase_matches,
    summarize_phase_matches,
)


def _make_match_result() -> MatchResult:
    """Build a small deterministic match result for plotting tests."""
    alpha = PhaseMatch(
        phase_name="alpha",
        strain=0.9900,
        n_matched=2,
        n_expected=3,
        matched_peaks=[
            MatchedPeak(
                obs_idx=0,
                obs_d=2.20000,
                obs_height=10.0,
                obs_fwhm=0.02,
                calc_d=2.22000,
                strained_d=2.19780,
                hkl=(1, 1, 0),
                multiplicity=6,
                F_sq=1.0,
                residual=0.00220,
            ),
            MatchedPeak(
                obs_idx=2,
                obs_d=1.10000,
                obs_height=8.0,
                obs_fwhm=0.02,
                calc_d=1.11100,
                strained_d=1.09989,
                hkl=(2, 2, 0),
                multiplicity=12,
                F_sq=0.8,
                residual=0.00011,
            ),
        ],
        score=5.0,
    )
    beta = PhaseMatch(
        phase_name="beta",
        strain=0.9200,
        n_matched=1,
        n_expected=2,
        matched_peaks=[
            MatchedPeak(
                obs_idx=1,
                obs_d=1.75000,
                obs_height=9.0,
                obs_fwhm=0.03,
                calc_d=1.90200,
                strained_d=1.74984,
                hkl=(1, 1, 1),
                multiplicity=8,
                F_sq=1.2,
                residual=0.00016,
            ),
        ],
        score=4.0,
    )
    return MatchResult(
        phase_matches=[alpha, beta],
        unmatched_indices=[],
    )


def test_build_match_table_aligns_rows_by_observed_peak() -> None:
    """Each row should stay aligned to one observed d-spacing."""
    obs_d = np.array([2.2, 1.75, 1.1])
    result = _make_match_result()

    headers, rows = build_match_table(obs_d, result, blank="-")

    assert headers == ["observed_d", "alpha", "beta"]
    assert rows == [
        ["2.20000", "2.19780", "-"],
        ["1.75000", "-", "1.74984"],
        ["1.10000", "1.09989", "-"],
    ]


def test_format_match_table_includes_headers_and_phase_columns() -> None:
    """Formatted output should be readable as a console table."""
    obs_d = np.array([2.2, 1.75, 1.1])
    result = _make_match_result()

    table = format_match_table(obs_d, result, blank="-")

    assert "observed_d" in table
    assert "alpha" in table
    assert "beta" in table
    assert "2.19780" in table
    assert "1.74984" in table


def test_plot_phase_matches_adds_phase_labels_to_legend() -> None:
    """Overlay plot should expose separate legend entries per phase."""
    x = np.linspace(0.8, 2.4, 200)
    peaks = np.exp(-(((x - 2.2) / 0.03) ** 2)) + np.exp(-(((x - 1.75) / 0.04) ** 2))
    spectrum = DiffractionSpectrum(
        x=x,
        y=peaks,
        e=np.ones_like(x),
        x_unit="d-Spacing (A)",
        y_unit="Counts",
        label="test",
    )
    result = _make_match_result()

    fig, ax = plot_phase_matches(
        spectrum,
        peaks,
        result,
        observed_positions=np.array([2.2, 1.75, 1.1]),
    )
    legend = ax.get_legend()
    labels = [text.get_text() for text in legend.get_texts()] if legend else []

    assert any(label.startswith("alpha ") for label in labels)
    assert any(label.startswith("beta ") for label in labels)
    assert "obs peaks" in labels
    assert ax.get_title().endswith("phase matches")
    fig.clf()


def test_plot_phase_matches_accepts_full_reflection_lists() -> None:
    """Optional phase reflection lists should add faint expected ticks."""
    x = np.linspace(0.8, 2.4, 200)
    peaks = np.exp(-(((x - 2.2) / 0.03) ** 2))
    spectrum = DiffractionSpectrum(
        x=x,
        y=peaks,
        e=np.ones_like(x),
        x_unit="d-Spacing (A)",
        y_unit="Counts",
        label="test",
    )
    result = _make_match_result()
    phase_reflections = {
        "alpha": [{"d": 2.22}, {"d": 1.11}, {"d": 0.95}],
        "beta": [{"d": 1.902}, {"d": 1.55}],
    }

    fig, ax = plot_phase_matches(
        spectrum,
        peaks,
        result,
        observed_positions=np.array([2.2, 1.75, 1.1]),
        phase_reflections=phase_reflections,
    )

    legend = ax.get_legend()
    labels = [text.get_text() for text in legend.get_texts()] if legend else []
    assert any(label.startswith("alpha ") for label in labels)
    assert any(label.startswith("beta ") for label in labels)
    fig.clf()


def test_summarize_phase_matches_returns_plot_and_table() -> None:
    """Single-call helper should return the figure and the table text."""
    x = np.linspace(0.8, 2.4, 200)
    peaks = np.exp(-(((x - 2.2) / 0.03) ** 2))
    spectrum = DiffractionSpectrum(
        x=x,
        y=peaks,
        e=np.ones_like(x),
        x_unit="d-Spacing (A)",
        y_unit="Counts",
        label="test",
    )
    result = _make_match_result()

    fig, ax, table = summarize_phase_matches(
        spectrum,
        peaks,
        result,
        observed_positions=np.array([2.2, 1.75, 1.1]),
        blank="-",
    )

    assert ax.get_title().endswith("phase matches")
    assert "observed_d" in table
    assert "alpha" in table
    fig.clf()


def test_inspect_phase_matches_returns_table_text() -> None:
    """Interactive helper should still return the formatted table."""
    x = np.linspace(0.8, 2.4, 200)
    peaks = np.exp(-(((x - 2.2) / 0.03) ** 2))
    spectrum = DiffractionSpectrum(
        x=x,
        y=peaks,
        e=np.ones_like(x),
        x_unit="d-Spacing (A)",
        y_unit="Counts",
        label="test",
    )
    result = _make_match_result()

    fig, ax, table = inspect_phase_matches(
        spectrum,
        peaks,
        result,
        observed_positions=np.array([2.2, 1.75, 1.1]),
        blank="-",
        show=False,
    )

    assert "beta" in table
    assert ax.get_title().endswith("phase matches")
    fig.clf()
