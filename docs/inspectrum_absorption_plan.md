# Inspectrum absorption plan

**Created**: 2026-05-12
**Status**: vendoring imminent
**Companion**: `crystal_species_refinement_plan.md`

## Decision

`inspectrum` (https://github.com/mguthriem/inspectrum) is being absorbed into
snapwrap as a vendored internal package. The standalone `inspectrum` repo will
not be deployed alongside snapwrap; users get inspectrum's functionality
through snapwrap imports only.

Rationale:

- Same author owns both; "upstream drift" risk doesn't apply.
- One pixi env to manage instead of two.
- Inspectrum's tuning, fixtures, and EOS reference data are SNAP-specific —
  the package isn't a general-purpose library being held back by snapwrap.
- It eliminates the `sys.path.insert(...)` hack currently required to launch
  inspectrum's UI inside Mantid Workbench from the snapwrap pixi env.

## What gets vendored vs dropped

### Vendored (Bucket 1+2)

| inspectrum module | Vendored? | Eventual snapwrap home |
|---|---|---|
| `models.py` | yes | partially absorbed into `sampleMeta` |
| `eos.py` | yes | `snapwrap.sampleMeta.eos` |
| `lattice.py` | yes | `snapwrap.sampleMeta.refine` |
| `crystallography.py` | yes (initially) | likely shrinks once Mantid coverage is verified |
| `loaders.py` | yes (initially) | mostly superseded by Mantid; keep CIF symop parser |
| `background.py` | yes | `snapwrap.spectralTools.background` |
| `peakfinding.py` | yes | `snapwrap.spectralTools.peakfinding` |
| `resolution.py` | yes | `snapwrap.spectralTools.resolution` |
| `matching.py` | yes | `snapwrap.spectralTools.matching` |
| `engine.py` | yes | `snapwrap.spectralTools.engine` (or a sampleMeta-side `refine`) |
| `plotting.py` | yes | review later |
| `tests/` | yes (under `tests/_inspectrum/`, marker-gated) | merged into snapwrap test layout once modules are promoted |

### Dropped (Bucket 3)

| What | Why |
|---|---|
| `ui/` (PyQt5) | snapwrap's `CalibrationManager` is the canonical Qt host; a second Qt UI buys nothing |
| `cli.py` (stub) | snapwrap convention is `scripts/`; new entry points go there |
| inspectrum's own `pyproject.toml`, `.pre-commit-config.yaml`, `.github/` | subsumed into snapwrap's |
| inspectrum's `docs/getting-started.md`, `project.md`, `plan.md` | replaced by snapwrap's plan docs |
| inspectrum's `docs/ground_truths.md` | **migrated** to snapwrap's `docs/ground_truths.md` (don't drop — the SNAP tuning history is load-bearing) |

## Mechanical vendoring procedure

```bash
# from snapwrap repo root
git subtree add \
    --prefix=src/snapwrap/_inspectrum \
    https://github.com/mguthriem/inspectrum.git main \
    --squash

# Strip the things we don't want before committing further work
rm -rf src/snapwrap/_inspectrum/ui
rm -f  src/snapwrap/_inspectrum/cli.py
rm -f  src/snapwrap/_inspectrum/pyproject.toml
rm -rf src/snapwrap/_inspectrum/.github src/snapwrap/_inspectrum/.vscode
mv     src/snapwrap/_inspectrum/tests tests/_inspectrum
# leave src/snapwrap/_inspectrum/{LICENSE, README.md, src/inspectrum/, docs/}
```

After the subtree the python source ends up at
`src/snapwrap/_inspectrum/src/inspectrum/`; flatten that to
`src/snapwrap/_inspectrum/` so the import path is `snapwrap._inspectrum.engine`,
not `snapwrap._inspectrum.src.inspectrum.engine`.

The `__init__.py` of `snapwrap._inspectrum/` should be a deliberate, narrow
re-export — only what the snapwrap bridge actually needs:

```python
# src/snapwrap/_inspectrum/__init__.py
from .engine import inspect              # noqa: F401
from .models import (                    # noqa: F401
    EquationOfState,
    PhaseDescription,
    SampleConditions,
    DiffractionSpectrum,
    CrystalPhase,
    Instrument,
)
```

The imports *inside* the vendored modules stay as `from .lattice import ...`
(relative), not `from inspectrum.lattice import ...`. Most are already
relative; any absolute `inspectrum.*` imports must be rewritten to relative.

## pyproject delta

Add (or confirm) under `[tool.pixi.pypi-dependencies]`:

```toml
cryspy = ">=0.10.0"
pycifstar = "*"   # only if not pulled in transitively by cryspy
```

Per inspectrum's ground-truths file, snapwrap's pixi env already has `cryspy`
added. `pycifstar` should be checked.

## Test strategy during migration

- `tests/_inspectrum/` runs under a `pytest` marker (e.g. `inspectrum`).
  CI runs both groups; reduction_artefacts CI only runs snapwrap-native tests.
- Conftest for `tests/_inspectrum/` skips the whole tree if `cryspy` is not
  importable, so a stripped-down environment can still run snapwrap tests.

## Migration cadence (post-vendor)

```
Phase A → use crystalSpecies.from_cif (Mantid) + Phase 0 vendored code
Phase B → snapwrap.sampleMeta.eos re-exports from _inspectrum
Phase C → reduction_artefacts gains CIF + EOS asset types
Phase D → snapwrap.sampleMeta.refine bridges to _inspectrum.engine
Phase E → wire into io.WorkspaceHandle / spectralTools

then, opportunistically, per Bucket 1 module:
    move code from _inspectrum/ to its snapwrap home,
    update imports, delete the _inspectrum copy,
    deprecation note in _inspectrum/<module>.py for one release.

Endgame: src/snapwrap/_inspectrum/ contains only Bucket-2 modules, then
eventually disappears entirely as those promote to spectralTools/.
```

## Things to preserve regardless of the directory's fate

- `docs/ground_truths.md` content — especially the F² symop fix, the SNAP
  peak-tuning constants, the cubic_d2Inv bug note, and the W / ice-VII EOS
  reference values.
- The W and ice-VII CIF fixtures and the SNAP CSV / instprm fixtures.
- The "inspectrum does NOT refine" design principle as a docstring/comment in
  whichever module ends up holding the matching/refinement pipeline.

## Out of scope for the vendoring PR itself

- No API merging (`crystalSpecies` ↔ `CrystalPhase`).
- No deletions of inspectrum modules (other than `ui/`, `cli.py`, build files).
- No new snapwrap public surface.

The vendoring PR should be **mechanical, reviewable, and revertible**. All
semantic work happens in Phases A–E that follow.
