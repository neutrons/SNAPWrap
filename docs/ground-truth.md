# Ground Truth — SNAPWrap

Verified facts, hard constraints, and key design decisions that must not be forgotten between sessions. Add an entry whenever something non-obvious is confirmed or a deliberate choice is made.

---

## Environment and tooling

### Always use `pixi run` to execute tests

```bash
pixi run pytest
pixi run pytest tests/test_specific_module.py -v
```

**Never** use the micromamba snapwrap env directly (`/SNS/users/66j/micromamba/envs/snapwrap/bin/python`) or `conda run`. That env lacks `odfpy` (required by pandas for the `.ods` file loaded in `snapwrap/__init__.py`), which causes an `ImportError` before any test runs.

**Confirmed:** 2026-05-27

---

### Workbench embedding — no standalone PyQt app

All UI code must run embedded in Mantid Workbench via `QAppThreadCall`. There is no standalone app mode for production use. Entry points (`show()` in `__init__.py`) must follow the `QAppThreadCall` pattern from `calibrationManager`.

**Confirmed:** learned from calibrationManager session; standalone mode caused stale-import bugs.

---

## Threading

### All backend calls via GenericWorker

Every call that touches the filesystem, runs Mantid algorithms, or blocks for any significant time must go through `GenericWorker` (a `QObject` moved to a `QThread`). Never call blocking functions directly from a Qt signal handler or any method on the main GUI thread.

**Why:** blocking the GUI thread under Workbench causes the entire application to freeze and can corrupt the event loop.

---

## Mantid imports

### Defer all Mantid imports to function scope

Modules in `reduction_artefacts/` and `campaignManager/` must not import Mantid at module level. All `from mantid.simpleapi import ...` and `from mantid.api import mtd` calls must appear inside the function body.

**Why:** allows the module to be imported in unit tests (outside Workbench), where Mantid is not available. This is the pattern used throughout and is what makes `pixi run pytest` work without a Mantid install.

---

## Bin mask file naming

### Filename stem determines unit domain

The unit of a swiss-cheese bin mask JSON is determined by its filename stem, not by any field inside the JSON:

- Stem ending `_Wavelength` → mask coordinates are in **wavelength** (Å)
- Stem ending `_dSpacing` → mask coordinates are in **d-spacing** (Å)

This convention is used in `compute_dspace_gaps` (`postprocessing.py`) to split masks and apply them in their respective domains. It is also used in `model.py` (`_units_tag`) to derive the artefact ID unit tag.

**Confirmed:** 2026-05-27 (bug fix commit `07cce9c` established this as the source of truth).

---

## Workspace naming convention

### SNAPWrap workspace names follow a strict pattern

All Mantid workspaces produced by SNAPWrap use:

```
{prefix}_{units}_{pgs}_{runNumber}
```

| Field | Values | Notes |
|---|---|---|
| `prefix` | `resampled`, `reduced`, `cropped` | step that produced the workspace |
| `units` | `dsp` | d-spacing (the only units currently produced) |
| `pgs` | `column`, `bank`, … | pixel grouping scheme, **lowercase** |
| `runNumber` | `065893` | 6-digit zero-padded integer |

Examples: `resampled_dsp_column_065893`, `cropped_dsp_column_65893`

**Critical for auto-discovery:** workspace search must match on the prefix, not assume the prefix from the step name. Cropped workspaces carry the `cropped_` prefix, not `resampled_…_cropped`. This bit `diagnose_crop_edges.py` until fixed (commit `ea22b0b`).

**Confirmed:** 2026-05-27

---

## Mantid workspace geometry

### d-spacing x-axis is monotonically increasing after ConvertUnits

After `ConvertUnits(..., Target="dSpacing")`, the x-axis bins within each spectrum run low-to-high. `numpy.searchsorted` is valid without reversing. An earlier concern about reversed axes was incorrect.

**Confirmed:** 2026-05-20

---

### spectraLsts stores workspace spectrum indices, not detector IDs

The `spectraLsts` field in swiss-cheese bin mask JSON files stores 0-based workspace spectrum indices. When applying masks in `compute_dspace_gaps`, compare directly against the loop variable `i` (the spectrum index), not against detector IDs.

**Confirmed:** 2026-05-15 (fix commit `69bc4dd`).

---

## Campaign data model

### JSON is the single source of truth

The campaign JSONL files on disk are the authoritative record. The UI reads from and writes to these files directly. There is no intermediate database or in-memory cache that could diverge from disk. Operator scripts are an optional export, not the primary persistence mechanism.

---

### Artefact ID scheme — bin masks

Bin mask artefact IDs follow: `binmask-{units}-{source}[-run{N}]`

- `units`: `wavelength` or `dspacing` (from filename stem)
- `source`: `transmission`, `manual`, `workspace`, or `json`
- `-run{N}`: omitted for campaign-scoped masks (no specific run)

Old campaigns with pre-Phase-1 IDs continue to work — the ID scheme change is additive, not a migration.

---

## Background extraction

### Background artefact ID scheme

Background artefact IDs follow `bgnd-{method}-run{N}` for per-run extractions, or `bgnd-composite-campaign` for the composite multi-run method.

| Field | Values |
|---|---|
| `method` | `clip` (ClipPeaks rolling sphere), `spline` (crystal species + weighted spline), `composite` (multi-run average) |
| `-run{N}` | included for Methods 1 and 2; omitted for composite (campaign scope) |

**Retention policy:** only the most recent background per method/scope is kept — not versioned.

**Confirmed:** 2026-05-28

---

### ClipPeaks window expressed in d-spacing (Å)

The rolling-sphere window size for ClipPeaks background extraction is `win_dspacing` (Å), not a bin count. This ensures the window covers the same physical extent regardless of resampling factor or PGS-specific binning — the same reasoning as `edge_dspacing` in cropping.

The natural nominal value can be derived from instrument resolution:

- SNAPRed provides `δd/d` per pixel via `EstimateResolutionDiffraction`
- After DiffractionFocussing: `resolution_dsp_{pgs}_{run}` workspace holds `δd(d) = (δd/d) × d` per focused spectrum (produced by `makeResolutionWorkspace` in `utils.py`)
- A window spanning N resolution units at d-spacing d₀ has `win_dspacing = N × (δd/d)|_{d₀} × d₀`
- For SNAP lite mode at column group: δd/d ≈ 0.003–0.005 at typical peak positions

The derivation from SNAPRed is a Phase 1 refinement — Phase 0 exposes `win_dspacing` directly to the user.

**Confirmed:** 2026-05-28

---

## Future decision pending

### Artefact ID scheme revisit (parked)

The current structured-string ID (`binmask-wavelength-manual-run65891`) conflates identity with scope. A numeric ID + description approach would be cleaner. Parked until Phase 3+ gives more workflow signal. See `docs/artefact_id_scheme_revisit.md`.
