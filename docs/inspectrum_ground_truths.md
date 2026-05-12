# Ground Truths

This file captures key findings, decisions, and verified facts discovered during development. It serves as a persistent knowledge base that AI assistants (like GitHub Copilot) and developers can reference across sessions.

**Why this matters:** AI assistants don't remember previous conversations. By recording important discoveries here, you ensure that context isn't lost between sessions. When Copilot reads this file, it can make better suggestions based on what's already been learned about your project.

## How to Use This File

- **Add entries as you discover important facts** — things like API quirks, configuration requirements, performance constraints, or design decisions.
- **Include the date and context** so future-you (or Copilot) understands why something was noted.
- **Link to relevant code or docs** when helpful.
- Copilot is instructed to update this file automatically when it discovers key findings during development.

## Findings

### 2026-03-11: Environment management uses pixi, not venv

The organisation uses pixi for deployment. The project uses `[tool.pixi.*]` sections in `pyproject.toml` (not a separate `pixi.toml`) for environment management. venv instructions are kept as a fallback in docs but pixi is the primary workflow.

### 2026-03-17: Pixi environment setup — TLS and Python version

- **pixi binary**: `~/.pixi/bin/pixi` (v0.62.1). Not on PATH by default.
- **TLS issue**: ORNL network uses a TLS-intercepting proxy causing `invalid peer certificate: UnknownIssuer`. Fix: `~/.config/pixi/config.toml` with `tls-no-verify = true`. This is machine-local, not committed.
- **Python pinned to `>=3.10,<3.14`**: Without an upper bound pixi solved to Python 3.14, which broke pandas. GSAS-II supports 3.10–3.13.
- **`[tool.pixi.project]` → `[tool.pixi.workspace]`**: Pixi 0.62 deprecated `project` in favour of `workspace`.
- **Verified env**: Python 3.13.12, numpy 2.4.2, scipy 1.17.1, matplotlib 3.10.8, h5py 3.15.1, pandas 2.3.3, cryspy, inspectrum 0.1.0. All 115 tests pass.
- **Pixi tasks**: `pixi run test` (pytest), editable install via `inspectrum = { path = ".", editable = true }` in pypi-dependencies.

### 2026-03-11: GSAS-II is a prerequisite, not a managed dependency

GSAS-II has a complex build process (Fortran compilers, platform-specific tooling) and cannot be installed via pip or conda. It must be installed separately. inspectrum's dependency version floors are aligned with GSAS-II's `pixi/pixi.toml` to ensure compatibility:

- Python: >=3.10 (GSAS-II supports 3.10–3.13)
- numpy: >=2.2.0 (GSAS-II uses >=2.2.1)
- scipy: >=1.15.0
- matplotlib: >=3.10.0
- h5py: >=3.12.0

In the pixi config, we use `matplotlib-base` (conda-forge package without Qt/Tk backends) since the backend choice is left to the user/GSAS-II environment.

### 2026-03-11: Target platforms are macOS and Linux only

Platforms: `osx-arm64`, `osx-64`, `linux-64`. No Windows support currently planned.

### 2026-03-16: CIF parsing / crystallographic library choice — cryspy

Chose `cryspy` (>=0.10.0, MIT license) over `crystals` (GPL-3.0, license-incompatible with BSD-3) and `gemmi` (good CIF reader but no powder diffraction tools). Reasons:

- **Neutron-specific**: built for polarized neutron diffraction, supports powder and single-crystal, has TOF support.
- **CIF support**: uses the core CIF dictionary of IUCr for data exchange.
- **MIT license**: compatible with inspectrum's BSD-3-Clause license.
- **Active**: v0.10.0 released Jan 2026, uses pixi for its own dev workflow.
- **PyPI only**: not on conda-forge, so added as a `[tool.pixi.pypi-dependencies]` entry.

cryspy is not on conda-forge so it's declared in pixi's pypi-dependencies section rather than conda dependencies.

### 2026-03-16: Test data — SNAP high-pressure neutron diffraction

Test fixtures are in `tests/test_data/`:

- **CIF files**: tungsten (Im-3m, a=3.16475 Å) and ice VII (Pn-3m, a=3.3891 Å) from ICSD.
- **Diffraction data**: 6 SNAP spectra (runs 059056–059063) as Mantid-exported CSV, each a single bank (bank 0). Format: d-spacing (Å) vs counts/µA·hr with uncertainties. ~863 points, d-range ~0.79–2.50 Å. Pressure increases across the series → lattice parameters shift.
- **Instrument params**: GSAS-II `.instprm` files (Type:PNT). Key params: difC=5218.45, 2θ=85.3035°, fltPath=15.5806 m. All 6 files have identical instrument params (same bank).

### 2026-03-16: Data model design decisions

- `DiffractionSpectrum` holds one bank's data (x, y, e arrays). `DiffractionDataset` is a list of spectra (e.g. pressure series).
- `CrystalPhase` holds lattice params, space group, atom sites, and a scale factor. Populated from CIF.
- `Instrument` mirrors GSAS-II .instprm key-value pairs (PNT type). Designed for one bank per instance; multi-bank instruments use multiple Instrument objects.
- `InspectionResult` holds deep copies of optimised phases + instrument. Originals are never modified.
- SNAP can output 1–6 banks per measurement with varying resolution and d-range. Testing with single bank; design accommodates multi-bank.

### 2026-03-16: Data loaders — formats and implementation details

Implemented in `src/inspectrum/loaders.py`. Four loaders:

- **`load_gsa(filepath)`** → `list[DiffractionSpectrum]`: Parses GSAS FXYE format (`.gsa`). Handles JSON metadata headers, comment lines (`#`), and `BANK` directives. FXYE = fixed-width X, Y, E columns. x_unit="TOF". Supports multi-bank files (one spectrum per BANK line).
- **`load_mantid_csv(filepath)`** → `list[DiffractionSpectrum]`: Parses Mantid-exported CSV. Extracts x-axis unit from header comment (`# X , Y , E`). Typically d-Spacing (Å). Comma-separated numerical data.
- **`load_instprm(filepath)`** → `Instrument`: Parses GSAS-II `.instprm` key:value format. Maps file keys (e.g. `difC`, `sig-1`, `2-theta`) to `Instrument` dataclass fields. Captures the `pdabc` multi-line absorption table block in `raw_params`.
- **`load_cif(filepath)`** → `CrystalPhase`: Uses pycifstar (`to_data(filepath)`) to parse CIF. Extracts cell parameters with `_parse_cif_number()` to strip CIF uncertainty notation (e.g. `3.16475(20)` → `3.16475`). Reads space group (H-M name + number), atom sites from CIF loops.

**pycifstar API notes**: `to_data(filepath)` returns a `Data` object. Access values via `data['_key'].value` (returns string). Loop data via `data.loops` — each loop has `.names` (list of column names) and you index with `loop['_column_name']` to get list of values.

### 2026-03-16: GSA ↔ CSV consistency

GSA (TOF) and CSV (d-spacing) files for the same SNAP run contain the same number of points (863). The relationship is: d = TOF / difC (approximately, for the linear term). This can be used for cross-validation.

### 2026-03-16: TODO — Mantid workspace loader

Future enhancement: add a loader that reads directly from a Mantid `Workspace2D` object (in-memory, no file I/O). This is for live-processing workflows where inspectrum is called from within Mantid scripts. Logged for Phase 3+.

### 2026-03-16: CRITICAL DESIGN DECISION — inspectrum does NOT refine

inspectrum's purpose is to **estimate good starting parameters** for Rietveld refinement, *without* performing a refinement itself. Rietveld refinements diverge when initial parameters are too far from the true values — inspectrum solves this by inspecting the spectrum directly.

**What inspectrum is NOT**: a profile-fitting optimizer or least-squares refinement engine. Do not use `scipy.optimize.least_squares` or similar to fit a calculated pattern to observed data — that *is* refinement and will suffer the same divergence problems.

**What inspectrum IS**: a peak-matching and parameter estimation tool. The pipeline:

1. **Calculate expected peak positions + intensities** from CIF lattice parameters and structure factors (crystallography module)
2. **Pre-process**: remove structured background (rolling ball technique) to cleanly expose peaks
3. **Find peaks** in the cleaned observed spectrum (peak detection)
4. **Match observed peaks to calculated peaks** — this is a 1D array matching problem (experimental mini-phase, needs experimentation)
5. **Estimate lattice parameters** from the offsets between matched peak positions (geometric/analytical)
6. **Estimate scale and peak widths** from observed peak heights and shapes

**Parameters to estimate at this stage**: lattice parameters (a, b, c, α, β, γ), relative scale factors (per phase), peak widths. These are sufficient to bootstrap a Rietveld refinement.

**Inspection via Mantid Workbench**: users will visually inspect intermediate results (background-subtracted spectra, found peaks, matched peaks) by loading them into Mantid Workbench, which has all the plotting/analysis tools needed. inspectrum does not need its own visualization.

### 2026-03-16: Crystallography module — cryspy building blocks

`src/inspectrum/crystallography.py` uses cryspy's low-level functions:

- **`cryspy.calc_inverse_d_by_hkl_abc_angles(h, k, l, a, b, c, α, β, γ)`** — returns 1/d for given Miller indices and cell params. Angles in **radians**.
- **`cryspy.get_scat_length_neutron(symbol)`** — returns complex bound coherent neutron scattering length (fm). E.g. W → 0.486, O → 0.5803, H → −0.3739.
- **`cryspy.get_crystal_system_by_it_number(sg_number)`** — returns crystal system string.
- **`cryspy.tof_Jorgensen(alpha, beta, sigma, time, time_hkl)`** — TOF peak profile (Ikeda-Carpenter convolved with Gaussian). Available but NOT used in the inspection pipeline (no profile fitting).

Key implementation details:
- Centering translation vectors (`_CENTERING_VECTORS` dict) applied to structure factor calculation for I, F, C, A, B, R lattices
- CIF atom site coordinates may contain uncertainty strings (`"0.202(3)"`) — `_parse_cif_number()` strips these
- Multiplicities computed from Laue class symmetry by enumerating equivalent reflections
- Reflections merged by d-spacing tolerance to remove duplicates from positive-hkl enumeration

### 2026-03-16: Peak finding module — tuning insights from SNAP data

`src/inspectrum/peakfinding.py` wraps `scipy.signal.find_peaks` with defaults tuned for neutron TOF powder diffraction.

**Auto-threshold strategy**: prominence threshold = std of the lower quartile of the peak signal. After background subtraction, peak-free regions cluster in the lower 25% — their std is a robust noise estimate. On SNAP data: noise σ ≈ 3.7, giving a prominence threshold of ~3.7 counts. This was chosen after testing several strategies:
- 3 × MAD was too aggressive (MAD=6.8, threshold=20.4 → 0 peaks found) because the residual background pedestal inflates the MAD
- Lower-quartile σ adapts well to the actual noise floor

**Width filter is the key discriminant**: real diffraction peaks have FWHM ≈ 0.01–0.06 Å (5–30 data points at SNAP resolution). Noise spikes have FWHM < 0.005 Å (1–3 points). The `min_width_pts=5` default effectively separates signal from noise.

**SNAP059056 results**: 9 peaks found (with auto-threshold + width filter). These correspond to tungsten and ice VII reflections. Offsets from ambient CIF d-spacings are 0.02–0.10 Å, consistent with ~3–5% lattice compression under high pressure.

**Diagnostic plotting**: `src/inspectrum/plotting.py` provides `plot_spectrum()`, `plot_background()`, and `plot_peak_markers()` — thin matplotlib wrappers that return `(fig, ax)` for one-liner visual inspection. `plot_peak_markers()` accepts a `PeakTable` directly.

### 2026-03-17: Background edge divergence — fixed with reflect-padding

The original peak-clipping implementation skipped points within `w` of the array edges (`if i < w: continue`). These untouched edge points kept their pre-clipping values, and after inverse-LLS + global normalization they diverged strongly from the real data.

**Fix**: Reflect-pad the working array by `win_size + 1` points on each side before clipping (like `np.pad(mode='reflect')`). This gives full windows at the edges. After clipping, strip the padding. The background now faithfully follows the data to the end points.

### 2026-03-17: Tuned parameters for SNAP high-pressure data

Tuned via `scripts/tune_peaks.py` interactive slider UI:
- `win_size=4` (was 40): SNAP spectra have structured, gnarly backgrounds that need tight tracking
- `smoothing=1.0` (was 5.0): less pre-smoothing preserves background features
- `min_prominence=4.0`: explicit threshold works better than auto for this data
- `min_width_pts=6` (was 5): slightly wider filter for SNAP resolution

These are stored as defaults in `scripts/tune_peaks.py`. The `estimate_background()` API defaults remain general-purpose (`win_size=40`, `smoothing=5.0`).

### 2026-03-17: Instrument resolution (pdabc) parsing

The instprm `pdabc` block contains 5 columns: d-spacing, TOF, 0, 0, σ_TOF. σ_TOF is the Gaussian sigma in TOF µs measured on NIST strain-free Si. NaN rows at low-d and high-d edges have no calibration data.

**Conversion**: `FWHM_d = 2·√(2·ln2) · σ_TOF / DIFC`

**SNAP Bank 0 resolution** (DIFC=5218.45):
- d=0.8 Å: FWHM ≈ 0.0045 Å (4.2 pts)
- d=1.0 Å: FWHM ≈ 0.0079 Å (6.0 pts)
- d=1.5 Å: FWHM ≈ 0.0174 Å (8.7 pts)
- d=2.0 Å: FWHM ≈ 0.0228 Å (8.6 pts)
- d=2.5 Å: FWHM ≈ 0.0307 Å (9.2 pts)

**Key insight**: `recommend_parameters()` derives background/peakfinding params from resolution. The `win_size` recommendation (3× max FWHM) gives 28 — too large for SNAP's structured backgrounds but reasonable for smoother instruments. Manual tuning (win_size=4) is needed for gnarly backgrounds.

### 2026-03-30: EOS, PhaseDescription schema, and non-ambient lattice parameters

**Context**: CIF files correspond to ambient conditions, but the sample may be at high pressure (lattice shrinks) or high temperature (lattice grows). Equations of state (EOS) relate volume to pressure and can predict the expected lattice strain.

**New data models** added to `models.py`:
- `EquationOfState`: type (murnaghan/birch-murnaghan/vinet), order, V₀ (ų/cell), K₀ (GPa), K′, source citation, extra params
- `SampleConditions`: pressure (GPa) and temperature (K), both optional
- `PhaseDescription`: wraps CIF path + role (calibrant/sample) + reference conditions + EOS + stability pressure range. `is_stable_at(pressure)` checks if the phase is expected at a given P.

**JSON serialization**: `tests/test_data/snap_phases.json` — human-editable format with V₀ unit conversion at load time. `load_phase_descriptions(json_path)` in `loaders.py` handles conversion and CIF loading.

**V₀ unit conversion**: Literature V₀ values come in different units. The loader converts to ų/cell:
- `"A3"` — per cell, no conversion
- `"A3/atom"` — multiply by Z (atoms/cell)
- `"cm3/mol"` — multiply by Z × 1e24 / Avogadro

**EOS reference values for test data**:
- **Tungsten** (calibrant): Vinet, V₀=15.862 ų/atom (Z=2 → 31.724 ų/cell), K₀=295.2±3.9 GPa, K′=4.32±0.11. Source: Dewaele, Loubeyre, Mezouar, PRB 70 094112 (2004).
- **Ice VII** (sample): 3rd-order Birch-Murnaghan, V₀=12.3±0.3 cm³/mol (Z=2 → 40.85 ų/cell), K₀=23.7±0.6 GPa, K′=4.15±0.07. Source: Hemley, Jephcoat, Mao, Zha, Finger, Cox, Nature 330 737-740 (1987). Note: V₀=40.85 ų is the extrapolated zero-pressure volume; ice VII doesn't exist at P=0.

**Calibrant role**: Tungsten has a well-characterised EOS and is commonly used as a pressure marker. If sample pressure is unknown but tungsten peaks are matched, the pressure can be determined from the calibrant strain.

**Stability ranges**: Ice VII is stable above ~2.1 GPa. Tungsten has no phase transitions in the pressure range of interest. The `stability_pressure` field enables filtering phases by condition.

**Design decisions**:
- Phase transitions handled by providing multiple CIFs with separate stability ranges — not by modelling the P-T phase boundary
- EOS is optional: if absent, the peak matcher does a blind strain search
- `role: "calibrant"` enables pressure-from-calibrant workflow
- Uncertainties stored as `_err` suffixed keys in `eos.extra` dict

### 2026-03-30: Engine refactoring — peak matching replaces least-squares

**Decision**: The `engine.py` `inspect()` function uses `scipy.optimize.least_squares` to fit a calculated pattern to observed data. This contradicts the core design principle (inspectrum does NOT refine). It will be replaced with a peak-matching pipeline:

1. For each phase, scan trial strain factors s to find the s that maximizes matched peaks between observed and calculated d-spacings
2. With EOS + known pressure: narrow the search around the EOS-predicted strain
3. With calibrant: determine pressure from calibrant first, then predict sample strain
4. Without EOS: blind search s ∈ [0.90, 1.10]

**Status**: ✅ DONE (2026-04-01). The old least-squares code (~400 lines) has been removed. `engine.py` is now ~175 lines: `d_to_tof`, `tof_to_d` (coordinate transforms) + `inspect()` (pipeline orchestrator). The pipeline: background → peaks → reflections → pressure sweep → lattice refinement.

**What was kept**: `d_to_tof()`, `tof_to_d()` — used by tests, scripts, and loaders.

**What was removed**: `simulate_pattern()`, `_tof_profile_batch()`, `_build_param_vector()`, `_unpack_params()`, `_get_crystal_system()`, `_chi_squared()`, `_build_result()`, `import cryspy`. Profile simulation is GSAS-II's job; crystal system logic moved to `lattice.py`.

**InspectionResult updated**: Now carries `match_result` (MatchResult), `refinements` (list[LatticeRefinementResult]), `peak_table` (PeakTable), `sweep_pressure_gpa` (float). Old `processed_spectra` and `chi_squared` fields retained for backward compat.

**Full implementation plan**: see `docs/plan.md`.

### 2026-03-30: SpectrumConditions restructured for data provenance

**Change**: `SpectrumConditions` now carries `run_number`, `instrument`, `facility`, and `pgs` (pixel grouping scheme) fields to support locating real datasets on facility data mounts. The `label` field is retained but auto-derived via `resolved_label()` as `"{instrument}{run_number:06d}"` when not set explicitly.

**Global defaults**: `ExperimentDescription` gained `instrument`, `facility`, and `pgs` fields as top-level defaults. Per-spectrum entries can override these. The JSON schema adds these at the root level alongside `global_conditions`.

**JSON schema change**: `spectrum_conditions` entries now use `run_number` (int) instead of `label` (string). Instrument/facility/pgs inherit from global defaults unless overridden per-entry.

**Matching**: `conditions_for(label)` now matches against `resolved_label(self.instrument)` or the explicit `label`, ensuring backward compatibility.

### 2026-03-30: F² structure factor bug — FIXED via full symmetry expansion

**Bug**: `_calc_structure_factor_sq()` in `crystallography.py` only expanded atoms by lattice centering translations (I/F/C/etc.), not by the full set of space group symmetry operations. This worked accidentally for BCC tungsten (single atom at origin + I-centering) but produced wildly wrong F² for ice-VII and any non-trivial structure.

**Diagnosis**: `scripts/audit_fsq.py` showed ice-VII (0,1,1) off by 2×, (1,1,1) should be near-zero but gave F²=6.4 (old CIF), (0,0,2) should be near-zero. Root cause: sum ran over asymmetric unit + centering only, missing rotational symmetry equivalents.

**What Mantid does**: Mantid's `StructureFactorCalculatorSummation.cpp` does the same algorithm — expand each asymmetric unit atom using `spaceGroup->getEquivalentPositions()`, then sum F(hkl) = Σ b·occ·DWF·exp(2πi h·r) over ALL equivalent positions. It's all custom C++, no external library.

**Fix**: 
1. Parse `_space_group_symop_operation_xyz` strings from CIF into (rotation, translation) pairs — `parse_symop()` in `crystallography.py`
2. Store parsed symops on `CrystalPhase.symops` (new field)
3. `expand_position()` applies all symops to generate unique equivalent positions
4. `_calc_structure_factor_sq()` now sums over full expansion when symops present, with centering-only fallback for legacy CrystalPhase objects without symops

**Validated results (ice-VII D₂O, Pn-3m, a=3.31812 Å)**:
- O at Wyckoff 2a (3/4,3/4,3/4) → 2 positions ✓
- D at Wyckoff 8e (0.91012,0.91012,0.91012) → 8 positions ✓
- (0,0,2) F² ≈ 0.04 (near-extinct: O and D contributions cancel) ✓
- (0,1,1) F² ≈ 3.14 (strong) ✓
- Tungsten: F² ≈ 4×0.486² = 0.945 unchanged ✓ (96 symops → same 2 positions)

**cryspy scattering length units**: `cryspy.get_scat_length_neutron()` returns values in 10⁻¹² cm, not fm. So F² is in (10⁻¹² cm)² units. Conversion to fm²: multiply by 100.

### 2026-03-30: Ice-VII CIF updated — D₂O, correct structure

**Old CIF**: `EntryWithCollCode211586_iceVII.cif` — H₂O, fractional occupancies (0.167) on both O and H sites. WRONG for our purposes.

**New CIF**: `EntryWithCollCode211741_iceVII.cif` — D₂O (deuterated, correct for neutron diffraction), Pn-3m Origin 2 (Z suffix), a=3.31812 Å, O at (0.75,0.75,0.75) occ=1.0, D at (0.91012,0.91012,0.91012) occ=0.5. From Yamashita et al., Acta Cryst. B, 2024.

**Origin choice**: `'P n -3 m Z'` — Z suffix denotes Origin 2 (inversion center at origin). Our code handles this correctly because we parse the explicit symops from the CIF rather than looking up operations by space group number.

### 2026-03-30: Pressure-sweep matching — key insight and implementation

**Problem**: Independent per-phase strain sweeps (`identify_phases`) cannot reliably match peaks when phases are under pressure. The strain sweep has no physics constraint linking phases — tungsten and ice-VII are swept independently, leading to incorrect strain estimates and poor peak matching (e.g. only 1/8 tungsten peaks matched at s=1.0).

**Key insight**: All phases in a DAC share the same pressure. Instead of sweeping strain per phase, sweep **pressure** as the shared variable. At each trial P, compute per-phase strains from their EOS via `predicted_strain(eos, P)`, match peaks at those strains, and sum scores.

**Implementation**: `sweep_pressure()` in `matching.py`:
1. Takes `phase_descriptions` (with EOS) + observed peaks + tolerance + P range
2. Two-pass coarse+fine grid search (same pattern as `sweep_strain`)
3. At each trial P: filters phases by `is_stable_at(P)`, computes `s = predicted_strain(eos, P)`, matches all phases at their predicted strains
4. Contested peaks resolved by smallest |residual| (same as `identify_phases`)
5. Returns `(best_pressure, MatchResult)` with per-phase strains from EOS

**Scoring function fix**: `_score_matches()` was rewritten with a Gaussian residual penalty: each match contributes `(1 + log1p(F²×mult)) × exp(-2 × (residual/tol)²)`. This makes the sweep sensitive to peak centering, not just peak counting. Without this, score was flat across any strain where all peaks fell within tolerance.

**SNAP059056 results with pressure sweep**:
- **Best pressure**: ~10 GPa (plausible for the first data point in the series)
- **Tungsten**: s=0.989 (stiff, barely compresses), 2 peaks matched
- **Ice-VII**: s=0.919 (significant compression), 7 peaks matched
- **Total**: 9/13 peaks matched (vs. 3/13 with blind strain sweep at s=1.0)
- **Improvement**: pressure sweep matches 3× more peaks than independent strain sweeps

**When to use which approach**:
- `sweep_pressure()` — when phases have EOS data and share a common pressure. Preferred for DAC experiments.
- `identify_phases()` — fallback when no EOS is available, or for non-pressure experiments.
- `sweep_strain()` — single-phase strain estimation.

**Test coverage**: 265 tests pass. 6 synthetic tests + 5 SNAP integration tests for `sweep_pressure`.

### 2026-04-01: Spurious peak discrimination — resolution floor + 5σ prominence

**Problem**: `find_peaks_in_spectrum()` was finding 13 peaks in SNAP059056, but only ≤8 are real (tungsten + ice-VII at ~10 GPa). Two failure modes:

1. **Sub-resolution spikes**: Peaks with FWHM < 75% of instrument resolution — physically impossible for real diffraction peaks. These are single-bin counting fluctuations.
2. **Low-amplitude noise peaks**: Peaks with prominence < 5σ of the noise floor — below the detection threshold for reliable identification.

**Diagnostic** (`scripts/diagnose_peaks.py`): Profiled all 13 peaks. The 5 spurious peaks split cleanly:
- 3 had FWHM/resolution_FWHM ratios of 0.59, 0.64, 0.73 (sub-resolution)
- 2 had prom/σ of 3.5 and 4.5 (low-SNR) with near-resolution widths

**Fix — two new filters in `find_peaks_in_spectrum()`**:
1. **`min_fwhm_factor=0.75`** (new parameter): Rejects peaks whose FWHM < 0.75× instrument FWHM at that d-spacing. Only active when `resolution` is provided. Catches sub-resolution noise spikes.
2. **`noise_sigma_factor=5.0`** (new parameter): Auto-prominence threshold raised from 1σ → 5σ of the lower-quartile noise. Catches low-amplitude noise fluctuations.

**Result**: 13 → 8 peaks, all 8 matched (7 ice-VII + 1 tungsten), 0 unmatched. Previous: 4 unmatched spurious peaks.

**Impact on tungsten matching**: With the cleaner peak list, only 1 tungsten peak matches (W 110 at d≈2.21) instead of 2. The second W match was likely a coincidental alignment of a spurious peak. The `test_tungsten_found_with_pressure` assertion relaxed from `≥2` to `≥1`.

**Key FWHM ratios for reference** (observed/instrument):
- Real peaks: 0.78–2.92 (all ≥ 0.75)
- Spurious spikes: 0.59, 0.64, 0.73 (all < 0.75)
- The 0.75 cutoff sits between the two groups with good margin

**Test coverage**: 272 tests pass. New synthetic test `test_resolution_filter_rejects_narrow_spikes` validates the min-FWHM filter.

### 2026-04-02: Per-phase lattice parameter refinement — "pressure tuning"

**Problem**: `sweep_pressure()` assumes all phases share the same hydrostatic pressure, but in a DAC the sample (ice-VII, at the center) and calibrant (tungsten, nearer the gasket) experience different strain environments. A shared-pressure sweep gives a compromise pressure (~10.15 GPa) that isn't correct for either phase.

**Solution**: After the pressure sweep identifies which peaks belong to which phase, a per-phase lattice parameter refinement step independently fits lattice parameters to each phase's matched peaks using least-squares in 1/d² space. The refined volumes are then converted to per-phase pressures via their respective EOS.

**Implementation**: `src/inspectrum/lattice.py` (~230 statements):
- `LatticeRefinementResult` dataclass: refined a/b/c/α/β/γ, volume, EOS-derived pressure, fit statistics
- `d2_inv_*()` functions for all 7 crystal systems (cubic through triclinic)
- `_residuals_*()` weighted residual functions for `scipy.optimize.least_squares(method="lm")`
- `refine_lattice_parameters(phase_match, phase_desc)`: main API — fits lattice params, excludes weak peaks, derives pressure
- `refine_all_phases(match_result, phase_descriptions)`: batch refinement
- `format_refinement_report()`: human-readable comparison report
- Weights: 1/FWHM as uncertainty proxy. Initial guess: CIF params × matched strain.

**snapwrap cubic bug**: SNAPWrap's `latticeFittingFunctions.py::cubic_d2Inv()` has `ref.h*ref.k` instead of `ref.k**2` in the formula `(h² + k² + l²)/a²`. This is fixed in inspectrum's implementation.

**Architecture decision**: Fitting code is in inspectrum (not a snapwrap dependency). snapwrap will eventually import from inspectrum. inspectrum is instrument-agnostic; snapwrap depends on Mantid/snapred which are heavy ORNL-specific dependencies.

**SNAP059056 results**:
- **Ice-VII**: a = 3.061 Å, V = 28.68 ų, P = 17.56 GPa (7 peaks)
- **Tungsten**: a = 3.118 Å, V = 30.32 ų, P = 14.72 GPa (1 peak)
- **Pressure spread**: 2.84 GPa between phases — physically reasonable for sample vs. calibrant in a DAC
- **Comparison to sweep**: sweep gave 10.15 GPa (shared); refinement shows ice at 17.6 GPa and tungsten at 14.7 GPa

**Note on tungsten**: Only 1 tungsten peak is matched (W 110), so the refinement is exact (0 residual) but has no redundancy. More peaks would improve confidence. This is a data limitation, not an algorithm issue.

**Weak-peak exclusion**: Peaks with `obs_height < min_prominence_sigma × noise_sigma` are excluded from the fit. Default threshold: 5σ. This prevents weak/marginal peaks from biasing the lattice parameter estimate.

**Relationship to "inspectrum does NOT refine" design decision**: This is NOT Rietveld refinement. It fits only lattice parameters (1–6 free params depending on crystal system) to discrete matched peak positions in d-spacing. No profile shape optimization, no background modeling, no intensity fitting. It's the analytical "estimate lattice parameters from peak offsets" step described in the original design — just formalized as a proper least-squares fit rather than a geometric calculation.

**Test coverage**: 300 tests pass. 28 new tests in `test_lattice.py`: 7 d²-inverse formula tests, 4 crystal system identification, 2 cell volume, 6 cubic refinement (exact, single-peak, strained, volume, EOS pressure, weak-peak exclusion), 2 hexagonal refinement, 1 multi-phase, 1 report formatting, 5 SNAP integration tests.

### 2026-04-01: Engine refactor (Phase 3.1 complete)

Replaced ~400 lines of old profile-simulation code in `engine.py` with a pipeline orchestrator:
- `inspect()` runs: background → peaks → reflections → sweep → refine
- Kept `d_to_tof()` / `tof_to_d()` (used by loaders, plotting, UI)
- Zero-peaks early-return guard with `noise_sigma` floor (`max(..., 1e-10)`)
- Result metadata now stores `bg_subtracted`, `spectrum` (in d-space), and `phase_reflections` for UI plotting
- 14 new engine tests, 314 total tests, 98% engine coverage

### 2026-04-01: PyQt5 UI scaffold (Phase 4.1 complete)

Built 7 files in `src/inspectrum/ui/` following SNAPWrap CalibrationManager pattern:
- **Entry points**: `show()` (Workbench via `QAppThreadCall`) and `show_standalone()` (dev mode)
- **Model**: `InspectrumModel` — pure Python, Qt-agnostic, wraps pipeline + phase management + data loading + JSON serialization
- **Worker**: `InspectionWorker(QObject)` for background thread execution
- **Panels**: DataPanel (file/workspace, P/T, bank), PhasePanel (CIF list + drag-drop + EOS editor + save/load JSON), ResultsPanel (matplotlib embed + summary table)
- **Main window**: `InspectrumWindow(QDialog)` — splitter layout, Run/Clear buttons, progress bar, status bar
- Uses `qtpy` for Qt bindings, `FigureCanvasQTAgg` for plots
- **Manual phase definition deferred to v2**

### 2026-04-02: CI workflows fixed

- `tests.yml`: Dropped Python 3.9 (requires ≥3.10), dropped Windows (not a target platform), added Python 3.13, fixed `--cov=src/package_name` → `--cov=src/inspectrum`
- `lint.yml`: Bumped Python to 3.12 for numpy ≥2.2.0 compatibility
- `pyproject.toml` ruff config: Suppressed E741 (`l` is standard Miller index notation), SIM103/SIM108, C408, ARG001
- Applied black + ruff formatting across all files
- GitHub remote: `git@github.com:mguthriem/inspectrum.git` (was template repo)
- CI matrix: ubuntu-latest + macos-latest × Python 3.10/3.11/3.12/3.13

### 2025-07-21: PyQt5 UI — interactive widget scaffold (Phase 4)

Built the interactive PyQt5 widget for launching from Mantid Workbench. Files in `src/inspectrum/ui/`:

- **`__init__.py`**: Entry points — `show()` (Workbench via `QAppThreadCall`) and `show_standalone()` (dev mode)
- **`model.py`**: Pure-Python model layer (`InspectrumModel`) — phase management, data loading (files or Mantid workspaces), phase-EOS JSON serialization, pipeline execution via `engine.inspect()`
- **`worker.py`**: `InspectionWorker(QObject)` with `finished`/`error` signals for QThread background execution
- **`dataPanel.py`**: Data source toggle (file/workspace), GSA/instprm browse, bank selector, P/T spin boxes
- **`phasePanel.py`**: Phase list with CIF drag-and-drop, EOS editor (type/V₀/K₀/K′), stability range, save/load JSON
- **`resultsPanel.py`**: Embedded matplotlib (`FigureCanvasQTAgg`) reusing `plot_phase_matches()`, per-phase summary table
- **`mainWindow.py`**: `InspectrumWindow(QDialog)` — splitter layout, Run/Clear buttons, progress bar, status label, signal wiring

**Key patterns**: Follows CalibrationManager (SNAPWrap) architecture — module-level `_active_dialog`, `QAppThreadCall` for thread safety, QThread+QObject worker, qtpy imports for Qt abstraction.

**Engine metadata addition**: `engine.inspect()` now stores `bg_subtracted`, `spectrum` (d-space), and `phase_reflections` in result metadata so the UI results panel can plot without re-running the pipeline.

**Manual phase definition** (defining phases without a CIF file) deferred to v2.

**314 tests still pass** after all changes. UI files are 0% coverage (need Qt for import — tested manually via `show_standalone()`).

### 2026-04-02: Inspectrum UI running inside Mantid Workbench on RHEL9 analysis cluster

**Milestone**: Phase 4.2 task 1 complete — inspectrum's `show()` successfully opens the `InspectrumWindow` dialog inside Mantid Workbench on the ORNL analysis cluster.

**Dev environment setup**:
- Uses the snapwrap fork at `/SNS/SNAP/shared/Malcolm/code/forks/SNAPWrap`
- Added `cryspy = ">=0.10.0"` to snapwrap's `[tool.pixi.pypi-dependencies]` (cryspy is PyPI-only, not on conda-forge)
- Activate the snapwrap pixi shell (e.g. `nsd-pixi-shell.sh` pointing at the fork)
- Launch workbench: `python -m workbench`
- In Workbench script console, inject inspectrum via `sys.path`:
  ```python
  import sys
  sys.path.insert(0, "/SNS/SNAP/shared/Malcolm/code/inspectrum/src")
  from inspectrum.ui import show
  show()
  ```

**Key finding — cryspy duplication**: inspectrum's `pyproject.toml` had `cryspy` in both `[project].dependencies` and `[tool.pixi.pypi-dependencies]`. This caused pixi to error with "cryspy is already a dependency" when inspectrum was installed as an editable package. Fixed by removing the duplicate from `[tool.pixi.pypi-dependencies]` — pixi resolves it from `[project].dependencies` automatically.

**Key finding — sys.path approach**: Rather than adding inspectrum as an editable pypi-dependency in snapwrap's toml (which triggered complex cross-project pixi resolution issues), the simpler approach is: install only `cryspy` in the snapwrap env, then `sys.path.insert()` inspectrum's `src/` directory at runtime. This avoids re-solving the full snapwrap environment and works reliably for dev/testing.

**End-to-end pipeline verified** (2026-04-02): Loaded SNAP CSV spectrum + instprm + tungsten/ice-VII CIFs, entered EOS parameters manually in the UI, ran the pipeline, and got results displayed in the plot panel. Full pipeline works inside Mantid Workbench on the RHEL9 analysis cluster.

**UX note**: EOS parameters must be entered manually per phase (select phase → set type/V₀/K₀/K′ → click "Apply EOS"). The "Load JSON" button loads single-phase JSON files (the format produced by "Save JSON"), not the multi-phase `snap_phases.json` format. Users should "Save JSON" per phase after first entry to avoid re-typing. UX improvements deferred to next session.
