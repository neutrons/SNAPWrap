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

## Future decision pending

### Artefact ID scheme revisit (parked)

The current structured-string ID (`binmask-wavelength-manual-run65891`) conflates identity with scope. A numeric ID + description approach would be cleaner. Parked until Phase 3+ gives more workflow signal. See `docs/artefact_id_scheme_revisit.md`.
