# Phase D handover note

**Written**: 2026-05-12  
**Branch**: `reduction_artifacts`  
**Last commit at time of writing**: Phase C (`307156c`)

---

## What Phase D must build

Phase D replaces the `crystalSpecies.refine()` skeleton (B4, cubic-only, no real engine)
with a proper inspectrum-backed refinement bridge.

### New public entry point

```
snapwrap/sampleMeta/refine.py
    refine_species_from_workspace(
        species_list: list[crystalSpecies],
        ws,                       # Mantid Workspace2D, focused, d-spacing
        instprm_path: str | Path, # GSAS-II .instprm file
        conditions=None,          # snapwrap._inspectrum.models.SampleConditions
        *,
        bank: int = 0,            # which workspace spectrum index to use
        P_min: float = 0.0,
        P_max: float | None = None,
    ) -> RefinementReport
```

`RefinementReport` is a new dataclass (same file) with:
- `refinements: list[LatticeRefinementResult]` — raw inspectrum output
- `species: list[crystalSpecies]` — the **mutated** input objects
- `sweep_pressure_gpa: float | None`
- `metadata: dict`
- `to_dict() -> dict` — JSON-serialisable, to be persisted via `register_crystal_species_artefact`

### D2 — Persistence

After calling `refine_species_from_workspace`, the caller (or the CLI) should call
`register_crystal_species_artefact(refined_a=..., refined_pressure_gpa=..., ...)` from
Phase C's persistence module.  Phase D does **not** call this automatically — it just
returns the report.

### D3 — CLI

`scripts/refine_lattice.py --campaign SLUG --workspace PATH --instprm PATH [--pressure GPa]`

Loads `crystalSpecies` from campaign's `crystal_species_index.jsonl` (most recent record
per species name), runs `refine_species_from_workspace`, writes the JSON report, and
calls `register_crystal_species_artefact`.

### D4 — Tests

- **No-Mantid unit test**: build a synthetic `DiffractionSpectrum` directly (numpy arrays)
  with known cubic peaks at strained `a`, build `PhaseDescription` from a CIF fixture,
  call `refine_species_from_workspace` — expect `species.unitCell.a` within 1%.
- **Integration test** (Mantid-gated): load a frozen SNAP `.nxs` fixture, run full bridge,
  expect ice-VII `a` within 1% of inspectrum's own ground truth.

---

## Architecture of `refine_species_from_workspace`

The implementation must follow these steps exactly (see `Risks` in the plan doc for why):

### Step 1 — Build `PhaseDescription` objects directly (no JSON file)

`load_phase_descriptions()` in `_inspectrum/loaders.py` takes a JSON **file path**, not a
list of dicts.  **Do not write a temp file.**  Instead construct the objects directly:

```python
from snapwrap._inspectrum.loaders import load_cif          # load_cif(path) -> CrystalPhase
from snapwrap._inspectrum.models import PhaseDescription, ExperimentDescription

phase_descs = []
for sp in species_list:
    if not sp.cifPath:
        continue   # can't bridge without a CIF
    crystal_phase = load_cif(sp.cifPath)            # inspectrum's own cryspy/pycifstar loader
    desc = PhaseDescription(
        name=sp.name,
        cif_path=sp.cifPath,
        role=sp.role,
        eos=sp.eos,            # already an EquationOfState or None
        phase=crystal_phase,
    )
    phase_descs.append(desc)

experiment = ExperimentDescription(
    phases=phase_descs,
    global_max_pressure=P_max,
    # spectrum_conditions can encode conditions.pressure if supplied
)
```

**Why this path, not Mantid `LoadCIF`?** Mantid's `LoadCIF` does not preserve explicit
symop tables — it regenerates them from the Hermann-Mauguin symbol, which can produce
wrong $F^2$ values for non-standard settings (the bug that was fixed inside inspectrum).
`load_cif` uses `pycifstar` + `cryspy` and keeps explicit symops.  Snapwrap's own
`crystalStructure` (Mantid-backed) is only used for tick-mark generation, never for
reflections here.

### Step 2 — Load `Instrument`

```python
from snapwrap._inspectrum.loaders import load_instprm
instrument = load_instprm(instprm_path)
```

### Step 3 — Adapt Mantid workspace → `DiffractionSpectrum`

```python
from snapwrap._inspectrum.models import DiffractionSpectrum
import numpy as np

x = np.array(ws.readX(bank))
y = np.array(ws.readY(bank))
e = np.array(ws.readE(bank))
# Mantid bin boundaries → bin centres if needed:
if len(x) == len(y) + 1:
    x = 0.5 * (x[:-1] + x[1:])
spectrum = DiffractionSpectrum(x=x, y=y, e=e, x_unit="d-Spacing",
                               label=str(ws.name()))
```

### Step 4 — Call `inspect()`

```python
from snapwrap._inspectrum.engine import inspect as _inspect
result = _inspect(spectrum, instrument, experiment,
                  P_min=P_min, P_max=P_max or 100.0)
```

### Step 5 — Map results back onto `crystalSpecies`

```python
for ref in result.refinements:          # each is a LatticeRefinementResult
    # Find matching crystalSpecies by name
    sp = next((s for s in species_list if s.name == ref.phase_name), None)
    if sp is None:
        continue
    # Mutate unit cell
    sp.unitCell.a = ref.a
    sp.unitCell.b = ref.b
    sp.unitCell.c = ref.c
    sp.unitCell.alpha = ref.alpha
    sp.unitCell.beta  = ref.beta
    sp.unitCell.gamma = ref.gamma
    sp.valid["unitCell"] = True
    # Rebuild crystalStructure so tick marks use the refined cell
    sp._buildCrystalStructure()
    # Store refinement summary
    sp.refined = {
        "a": ref.a, "b": ref.b, "c": ref.c,
        "pressure_gpa": ref.pressure_gpa,
        "residual_sum_sq": ref.residual_sum_sq,
        "n_peaks_used": ref.n_peaks_used,
        "success": ref.success,
    }
```

Note: `sp.refined` is a new attribute — add it to `__init__` (default `None`),
`to_dict`, and `from_dict`.

---

## Key types to know

| Type | Location | What it is |
|---|---|---|
| `DiffractionSpectrum` | `_inspectrum/models.py:33` | `x, y, e` numpy arrays + `x_unit` |
| `Instrument` | `_inspectrum/models.py:224` | `difC, difA, zero` + profile params |
| `PhaseDescription` | `_inspectrum/models.py:468` | CIF path + EOS + `phase: CrystalPhase` |
| `ExperimentDescription` | `_inspectrum/models.py:607` | list of `PhaseDescription` + global conditions |
| `InspectionResult` | `_inspectrum/models.py:330` | `refinements`, `sweep_pressure_gpa`, `metadata` |
| `LatticeRefinementResult` | `_inspectrum/lattice.py:43` | `a, b, c, alpha, beta, gamma, pressure_gpa, success, n_peaks_used` |
| `load_cif` | `_inspectrum/loaders.py:412` | `path -> CrystalPhase` (cryspy-backed) |
| `load_instprm` | `_inspectrum/loaders.py:326` | `path -> Instrument` |
| `inspect` | `_inspectrum/engine.py:96` | full pipeline: bg → peaks → pressure sweep → refine |

---

## Risks and mitigations already decided

| Risk | Decision |
|---|---|
| `load_phase_descriptions` takes a file path, not a list | Build `PhaseDescription` objects directly using `load_cif` (see Step 1 above) |
| Mantid `LoadCIF` wrong symops | Always use `_inspectrum.loaders.load_cif` for the bridge — Mantid CrystalStructure is tick-marks only |
| Mantid bin boundaries vs bin centres | Half-sum correction in Step 3 |
| Multi-bank workspace | Use `bank=0` for now; multi-bank is inspectrum backlog |
| `crystalSpecies.refined` attribute missing | Add to `__init__`/`to_dict`/`from_dict` before writing D tests |

---

## Escalation reminder ⚠️

Phase D involves non-trivial design work (the workspace adapter, the species-matching
loop, and the `RefinementReport` JSON schema).  Before writing any Phase D code,
**prompt the user to confirm they want to proceed with the current model or escalate to a
frontier model** (GPT-4o, Claude 3.5, or equivalent).  The complexity is manageable but
the error surface is higher than Phases A-C.
