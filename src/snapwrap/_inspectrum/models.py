"""
Data models for snapwrap._inspectrum.

Defines the core domain objects used throughout the package:

- DiffractionSpectrum: a single 1D powder-diffraction spectrum
- DiffractionDataset: a collection of spectra (e.g. a pressure series)
- CrystalPhase: crystallographic phase with lattice params and atom sites
- Instrument: instrument description (GSAS-II TOF profile parameters)
- InspectionResult: container for optimisation output
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from snapwrap._inspectrum.lattice import LatticeRefinementResult
    from snapwrap._inspectrum.matching import MatchResult
    from snapwrap._inspectrum.peakfinding import PeakTable
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Diffraction data
# ---------------------------------------------------------------------------


@dataclass
class DiffractionSpectrum:
    """A single 1D powder-diffraction spectrum.

    Holds d-spacing (or TOF) vs intensity data for one detector bank
    of one measurement.

    Attributes:
        x: Independent variable — d-spacing in Angstroms (or TOF in µs).
        y: Dependent variable — intensity (counts / µA·hr or similar).
        e: Uncertainties on y (same units as y).
        x_unit: Unit label for x-axis (e.g. "d-Spacing", "TOF").
        y_unit: Unit label for y-axis.
        label: Human-readable label (e.g. filename or run number).
        bank: Detector bank index (0-based).
        metadata: Arbitrary key-value metadata from the file header.

    Example:
        >>> spectrum = DiffractionSpectrum(
        ...     x=np.array([0.79, 0.80, 0.81]),
        ...     y=np.array([85.0, 88.0, 91.0]),
        ...     e=np.array([2.1, 1.9, 1.8]),
        ...     label="SNAP059056",
        ... )
    """

    x: NDArray[np.float64]
    y: NDArray[np.float64]
    e: NDArray[np.float64]
    x_unit: str = "d-Spacing"
    y_unit: str = "Counts per microAmp.hour"
    label: str = ""
    bank: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.x) != len(self.y) or len(self.x) != len(self.e):
            raise ValueError(
                f"x, y, e must have equal length, got "
                f"{len(self.x)}, {len(self.y)}, {len(self.e)}"
            )

    @property
    def d_min(self) -> float:
        """Minimum d-spacing (Å)."""
        return float(np.min(self.x))

    @property
    def d_max(self) -> float:
        """Maximum d-spacing (Å)."""
        return float(np.max(self.x))

    @property
    def n_points(self) -> int:
        """Number of data points."""
        return len(self.x)

    def __repr__(self) -> str:
        return (
            f"DiffractionSpectrum(label={self.label!r}, bank={self.bank}, "
            f"n_points={self.n_points}, "
            f"d_range=[{self.d_min:.4f}, {self.d_max:.4f}] Å)"
        )


@dataclass
class DiffractionDataset:
    """A collection of 1D diffraction spectra.

    Represents a set of measurements — e.g. a pressure series where
    each entry is one spectrum from the same bank at a different
    condition.

    Attributes:
        spectra: Ordered list of DiffractionSpectrum objects.
        label: Dataset-level label (e.g. experiment name).
    """

    spectra: list[DiffractionSpectrum] = field(default_factory=list)
    label: str = ""

    @property
    def n_spectra(self) -> int:
        return len(self.spectra)

    def __repr__(self) -> str:
        return (
            f"DiffractionDataset(label={self.label!r}, " f"n_spectra={self.n_spectra})"
        )

    def __getitem__(self, index: int) -> DiffractionSpectrum:
        return self.spectra[index]

    def __len__(self) -> int:
        return self.n_spectra


# ---------------------------------------------------------------------------
# Crystal phase
# ---------------------------------------------------------------------------


@dataclass
class CrystalPhase:
    """A crystallographic phase.

    Holds lattice parameters, space group, atom site information, and
    a scale factor.  Designed to be populated from a CIF file.

    For inspectrum's purposes the key optimisable parameters are the
    lattice constants (a, b, c, alpha, beta, gamma) and a relative
    scale factor.

    Attributes:
        name: Phase label (e.g. "tungsten", "ice-VII").
        a: Lattice parameter a (Å).
        b: Lattice parameter b (Å).
        c: Lattice parameter c (Å).
        alpha: Lattice angle α (degrees).
        beta: Lattice angle β (degrees).
        gamma: Lattice angle γ (degrees).
        space_group: Hermann-Mauguin space group symbol.
        space_group_number: International Tables number.
        atom_sites: List of atom site dicts, each with at minimum
            keys 'label', 'type_symbol', 'fract_x/y/z', 'occupancy'.
        scale: Relative scale factor (dimensionless).
        metadata: Extra CIF fields or user annotations.

    Example:
        >>> tungsten = CrystalPhase(
        ...     name="tungsten",
        ...     a=3.16475, b=3.16475, c=3.16475,
        ...     alpha=90.0, beta=90.0, gamma=90.0,
        ...     space_group="I m -3 m",
        ...     space_group_number=229,
        ... )
    """

    name: str = ""
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    space_group: str = ""
    space_group_number: int = 0
    atom_sites: list[dict[str, Any]] = field(default_factory=list)
    symops: list[tuple[Any, Any]] = field(default_factory=list)
    scale: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def volume(self) -> float:
        """Unit cell volume (ų) from lattice parameters.

        Uses the general triclinic formula so it works for all
        crystal systems.
        """
        a, b, c = self.a, self.b, self.c
        al = np.radians(self.alpha)
        be = np.radians(self.beta)
        ga = np.radians(self.gamma)
        cos_al, cos_be, cos_ga = np.cos(al), np.cos(be), np.cos(ga)
        return float(
            a
            * b
            * c
            * np.sqrt(
                1 - cos_al**2 - cos_be**2 - cos_ga**2 + 2 * cos_al * cos_be * cos_ga
            )
        )

    def copy(self) -> CrystalPhase:
        """Return a deep copy of this phase."""
        return copy.deepcopy(self)

    def __repr__(self) -> str:
        return (
            f"CrystalPhase(name={self.name!r}, "
            f"SG={self.space_group!r} #{self.space_group_number}, "
            f"a={self.a:.5f}, b={self.b:.5f}, c={self.c:.5f}, "
            f"V={self.volume:.2f} ų, scale={self.scale:.4f})"
        )


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------


@dataclass
class Instrument:
    """GSAS-II style TOF instrument description.

    Stores the key parameters from a GSAS-II .instprm file for a
    pulsed-neutron TOF instrument (Type PNT).  Parameters follow
    the GSAS-II naming convention.

    The design anticipates multiple banks — each bank would have its
    own Instrument instance with different difC, 2-theta, profile
    coefficients, etc.

    Attributes:
        inst_type: Instrument type string (e.g. "PNT").
        bank: Bank number from the file header.
        two_theta: Scattering angle 2θ (degrees).
        flt_path: Total flight path (metres).
        difA: Quadratic d-to-TOF coefficient (µs/ų).
        difB: Linear offset d-to-TOF coefficient.
        difC: Primary d-to-TOF coefficient (µs/Å)
            — TOF ≈ difC·d + difA·d² + Zero.
        zero: Zero-point offset (µs).
        alpha: Ikeda-Carpenter alpha parameter.
        beta_0: Profile beta-0 coefficient.
        beta_1: Profile beta-1 coefficient.
        beta_q: Profile beta-q coefficient.
        sig_0: Gaussian sigma-0 coefficient.
        sig_1: Gaussian sigma-1 coefficient.
        sig_2: Gaussian sigma-2 coefficient.
        sig_q: Gaussian sigma-q coefficient.
        X: Lorentzian X profile parameter.
        Y: Lorentzian Y profile parameter.
        Z: Lorentzian Z profile parameter.
        azimuth: Detector azimuthal angle (degrees).
        source_file: Path to the .instprm file (if loaded from file).
        raw_params: Full dict of all key-value pairs from the file.
    """

    inst_type: str = "PNT"
    bank: int = 1
    two_theta: float = 0.0
    flt_path: float = 0.0
    difA: float = 0.0
    difB: float = 0.0
    difC: float = 0.0
    zero: float = 0.0
    alpha: float = 0.0
    beta_0: float = 0.0
    beta_1: float = 0.0
    beta_q: float = 0.0
    sig_0: float = 0.0
    sig_1: float = 0.0
    sig_2: float = 0.0
    sig_q: float = 0.0
    X: float = 0.0
    Y: float = 0.0
    Z: float = 0.0
    azimuth: float = 0.0
    source_file: str = ""
    raw_params: dict[str, Any] = field(default_factory=dict)

    @property
    def params(self) -> dict[str, float]:
        """Return the numeric instrument parameters as a flat dict.

        Useful for iteration and display (matches the project.md
        example: ``for param in result.instrument.params``).
        """
        return {
            "difA": self.difA,
            "difB": self.difB,
            "difC": self.difC,
            "Zero": self.zero,
            "2-theta": self.two_theta,
            "fltPath": self.flt_path,
            "alpha": self.alpha,
            "beta-0": self.beta_0,
            "beta-1": self.beta_1,
            "beta-q": self.beta_q,
            "sig-0": self.sig_0,
            "sig-1": self.sig_1,
            "sig-2": self.sig_2,
            "sig-q": self.sig_q,
            "X": self.X,
            "Y": self.Y,
            "Z": self.Z,
            "Azimuth": self.azimuth,
        }

    def copy(self) -> Instrument:
        """Return a deep copy of this instrument."""
        return copy.deepcopy(self)

    def __repr__(self) -> str:
        return (
            f"Instrument(type={self.inst_type!r}, bank={self.bank}, "
            f"2θ={self.two_theta:.2f}°, difC={self.difC:.2f}, "
            f"fltPath={self.flt_path:.4f})"
        )


# ---------------------------------------------------------------------------
# Inspection result
# ---------------------------------------------------------------------------


@dataclass
class InspectionResult:
    """Container for the output of inspect().

    Holds the full pipeline output: matched peaks per phase,
    refined lattice parameters, and diagnostic metadata.

    Attributes:
        crystal_phases: Input CrystalPhase objects (copies).
        instrument: Instrument description (copy).
        match_result: Multi-phase peak matching result from the
            pressure sweep, or None if matching was not performed.
        refinements: Per-phase lattice refinement results.
        peak_table: Observed peaks found by peak-finding.
        sweep_pressure_gpa: Best-fit pressure from the pressure
            sweep (GPa), or None.
        processed_spectra: Processed DiffractionDataset (e.g. after
            background subtraction), or None.
        chi_squared: Goodness-of-fit metric, if available.
        metadata: Additional diagnostic information.
    """

    crystal_phases: list[CrystalPhase] = field(default_factory=list)
    instrument: Instrument | None = None
    match_result: MatchResult | None = None
    refinements: list[LatticeRefinementResult] = field(default_factory=list)
    peak_table: PeakTable | None = None
    sweep_pressure_gpa: float | None = None
    processed_spectra: DiffractionDataset | None = None
    chi_squared: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        phase_names = [p.name for p in self.crystal_phases]
        n_ref = len(self.refinements)
        return (
            f"InspectionResult(phases={phase_names}, "
            f"sweep_P={self.sweep_pressure_gpa}, "
            f"refinements={n_ref}, "
            f"chi²={self.chi_squared})"
        )


# ---------------------------------------------------------------------------
# Equation of state & phase description
# ---------------------------------------------------------------------------


@dataclass
class EquationOfState:
    """Isothermal equation of state for a crystal phase.

    Relates unit-cell volume to pressure.  V₀ is always stored in
    ų per unit cell — conversion from published units happens at
    load time via :func:`loaders.load_phase_descriptions`.

    Supported EOS types:

    - ``"murnaghan"``: Murnaghan (1944)
    - ``"birch-murnaghan"``: 3rd-order Birch-Murnaghan
    - ``"vinet"``: Vinet (Rydberg) universal EOS

    Attributes:
        eos_type: One of ``"murnaghan"``, ``"birch-murnaghan"``,
            ``"vinet"``.
        order: Order of the EOS (e.g. 3 for 3rd-order BM).
        V_0: Reference volume in ų per unit cell.
        K_0: Isothermal bulk modulus at reference conditions (GPa).
        K_prime: Pressure derivative of bulk modulus (dimensionless).
        source: Literature citation for these parameters.
        extra: Higher-order coefficients, uncertainties, or other
            metadata (e.g. ``{"K_0_err": 3.9, "K_prime_err": 0.11}``).

    Example:
        >>> eos = EquationOfState(
        ...     eos_type="vinet",
        ...     V_0=31.724,
        ...     K_0=295.2,
        ...     K_prime=4.32,
        ...     source="Dewaele et al., PRB 70 094112 (2004)",
        ... )
    """

    eos_type: str = "birch-murnaghan"
    order: int = 3
    V_0: float = 0.0
    K_0: float = 0.0
    K_prime: float = 4.0
    source: str = ""
    extra: dict[str, float] = field(default_factory=dict)

    _VALID_TYPES = ("murnaghan", "birch-murnaghan", "vinet")

    def __post_init__(self) -> None:
        if self.eos_type not in self._VALID_TYPES:
            raise ValueError(
                f"eos_type must be one of {self._VALID_TYPES}, "
                f"got {self.eos_type!r}"
            )
        if self.V_0 <= 0:
            raise ValueError(f"V_0 must be positive, got {self.V_0}")
        if self.K_0 <= 0:
            raise ValueError(f"K_0 must be positive, got {self.K_0}")

    def __repr__(self) -> str:
        return (
            f"EquationOfState(type={self.eos_type!r}, order={self.order}, "
            f"V₀={self.V_0:.3f} ų, K₀={self.K_0:.1f} GPa, "
            f"K′={self.K_prime:.2f})"
        )


@dataclass
class SampleConditions:
    """Experimental conditions for a measurement or reference state.

    Both fields are optional — ``None`` means unknown or ambient.

    Attributes:
        pressure: Sample pressure in GPa, or None.
        temperature: Sample temperature in K, or None.

    Example:
        >>> cond = SampleConditions(pressure=3.5, temperature=300)
    """

    pressure: float | None = None
    temperature: float | None = None

    def __repr__(self) -> str:
        parts = []
        if self.pressure is not None:
            parts.append(f"P={self.pressure} GPa")
        if self.temperature is not None:
            parts.append(f"T={self.temperature} K")
        return f"SampleConditions({', '.join(parts) or 'ambient'})"


@dataclass
class PhaseDescription:
    """A crystal phase with optional EOS and stability metadata.

    Links a CIF file (via ``cif_path``) to equation-of-state
    parameters and the conditions under which the CIF lattice
    parameters were determined.  This is the user-facing input
    that wraps a :class:`CrystalPhase` with the physics needed
    to predict lattice parameters at non-ambient conditions.

    Attributes:
        name: Human label (e.g. ``"tungsten"``, ``"ice-VII"``).
        cif_path: Path to the CIF file (relative or absolute).
        role: ``"calibrant"`` or ``"sample"``.  Calibrants have
            well-known EOS usable for pressure cross-checks.
        reference_conditions: P/T at which the CIF was determined.
            Defaults to ambient (None/None).
        eos: Equation of state, or None if unknown.
        stability_pressure: ``(P_min, P_max)`` in GPa where this
            structure is expected to be stable.  None means no
            constraint (always considered present).  Endpoints
            of None mean open-ended — e.g. ``(2.1, None)`` means
            stable above 2.1 GPa with no known upper bound.
        phase: :class:`CrystalPhase` populated at runtime from CIF.
            Not serialized to JSON.

    Example:
        >>> desc = PhaseDescription(
        ...     name="tungsten",
        ...     cif_path="tungsten.cif",
        ...     role="calibrant",
        ... )
    """

    name: str = ""
    cif_path: str = ""
    role: str = "sample"
    reference_conditions: SampleConditions = field(default_factory=SampleConditions)
    eos: EquationOfState | None = None
    stability_pressure: tuple[float | None, float | None] | None = None
    phase: CrystalPhase | None = field(default=None, repr=False)

    _VALID_ROLES = ("calibrant", "sample")

    def __post_init__(self) -> None:
        if self.role not in self._VALID_ROLES:
            raise ValueError(
                f"role must be one of {self._VALID_ROLES}, " f"got {self.role!r}"
            )

    def is_stable_at(self, pressure: float | None) -> bool:
        """Check whether this phase is expected at the given pressure.

        Returns True if no stability range is defined or if pressure
        is None (unknown).

        Args:
            pressure: Pressure in GPa, or None if unknown.

        Returns:
            True if the phase should be considered present.
        """
        if self.stability_pressure is None or pressure is None:
            return True
        p_min, p_max = self.stability_pressure
        if p_min is not None and pressure < p_min:
            return False
        if p_max is not None and pressure > p_max:
            return False
        return True

    def __repr__(self) -> str:
        eos_str = self.eos.eos_type if self.eos else "none"
        return (
            f"PhaseDescription(name={self.name!r}, role={self.role!r}, "
            f"eos={eos_str}, cif={self.cif_path!r})"
        )


@dataclass
class SpectrumConditions:
    """Per-spectrum conditions and data provenance.

    Holds the identifiers needed to locate a dataset on a facility
    data mount, plus any known per-run conditions.  Per-run values
    override the global defaults in :class:`ExperimentDescription`.

    The ``label`` is derived automatically from instrument + run_number
    if not set explicitly (e.g. ``"SNAP059056"``).

    Attributes:
        run_number: Unique run identifier (e.g. ``59056``).
        instrument: Instrument name (e.g. ``"SNAP"``).  Inherits
            from global if None.
        facility: Facility name (e.g. ``"SNS"``).  Inherits from
            global if None.
        pgs: Pixel grouping scheme (e.g. ``"all"``, ``"bank"``,
            ``"column"``).  Inherits from global if None.
        label: Spectrum label for matching.  If empty, derived as
            ``"{instrument}{run_number:06d}"``.
        pressure: Per-run pressure (GPa), or None to inherit global.
        temperature: Per-run temperature (K), or None to inherit global.
    """

    run_number: int = 0
    instrument: str | None = None
    facility: str | None = None
    pgs: str | None = None
    label: str = ""
    pressure: float | None = None
    temperature: float | None = None

    def resolved_label(self, default_instrument: str = "") -> str:
        """Return the label, deriving it from instrument + run_number if empty.

        Args:
            default_instrument: Fallback instrument name from globals.

        Returns:
            Spectrum label string.
        """
        if self.label:
            return self.label
        inst = self.instrument or default_instrument
        if inst and self.run_number:
            return f"{inst}{self.run_number:06d}"
        return ""

    def __repr__(self) -> str:
        parts = []
        lbl = self.label or f"run={self.run_number}"
        parts.append(lbl)
        if self.pressure is not None:
            parts.append(f"P={self.pressure} GPa")
        if self.temperature is not None:
            parts.append(f"T={self.temperature} K")
        return f"SpectrumConditions({', '.join(parts)})"


@dataclass
class ExperimentDescription:
    """Top-level experiment description loaded from JSON.

    Groups phase descriptions with global and per-spectrum conditions.
    Global values act as defaults — per-spectrum values override them.

    Attributes:
        phases: Phase descriptions with optional EOS.
        global_temperature: Default temperature for all spectra (K).
            None means unknown.
        global_max_pressure: Hard upper bound on pressure across all
            runs (GPa).  Constrains the strain search window and
            filters phases by stability.  None means no constraint.
        instrument: Default instrument name (e.g. ``"SNAP"``).
        facility: Default facility name (e.g. ``"SNS"``).
        pgs: Default pixel grouping scheme (e.g. ``"all"``).
        spectrum_conditions: Per-spectrum overrides.  Matched to
            spectra by label.
        metadata: Arbitrary experiment-level metadata.

    Example:
        >>> exp = ExperimentDescription(
        ...     phases=[...],
        ...     global_temperature=295,
        ...     global_max_pressure=60.0,
        ...     instrument="SNAP",
        ...     facility="SNS",
        ...     pgs="all",
        ... )
        >>> exp.conditions_for("SNAP059056")
        SampleConditions(P=None, T=295 K)
    """

    phases: list[PhaseDescription] = field(default_factory=list)
    global_temperature: float | None = None
    global_max_pressure: float | None = None
    instrument: str = ""
    facility: str = ""
    pgs: str = "all"
    spectrum_conditions: list[SpectrumConditions] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def conditions_for(self, label: str) -> SampleConditions:
        """Resolve effective conditions for a spectrum by label.

        Per-spectrum values override globals.  If a per-spectrum
        entry is not found, global values are used.

        Args:
            label: Spectrum label to look up.

        Returns:
            Resolved SampleConditions with inherited globals.
        """
        pressure: float | None = None
        temperature = self.global_temperature

        # Look for per-spectrum override
        for sc in self.spectrum_conditions:
            resolved = sc.resolved_label(self.instrument)
            if resolved == label or sc.label == label:
                if sc.pressure is not None:
                    pressure = sc.pressure
                if sc.temperature is not None:
                    temperature = sc.temperature
                break

        return SampleConditions(pressure=pressure, temperature=temperature)

    def active_phases_at(
        self,
        pressure: float | None = None,
    ) -> list[PhaseDescription]:
        """Return phases expected to be stable at the given pressure.

        Uses each phase's ``stability_pressure`` range.  If pressure
        is None, returns all phases.

        Args:
            pressure: Pressure in GPa, or None.

        Returns:
            Filtered list of PhaseDescription objects.
        """
        return [p for p in self.phases if p.is_stable_at(pressure)]

    def __repr__(self) -> str:
        names = [p.name for p in self.phases]
        return (
            f"ExperimentDescription(phases={names}, "
            f"instrument={self.instrument!r}, "
            f"T={self.global_temperature} K, "
            f"P_max={self.global_max_pressure} GPa, "
            f"n_spectra={len(self.spectrum_conditions)})"
        )
