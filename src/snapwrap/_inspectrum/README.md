# `snapwrap._inspectrum` (vendored)

This directory is a vendored copy of the standalone
[`inspectrum`](https://github.com/mguthriem/inspectrum) prototype, absorbed
into SNAPWrap on 2026-05-12.  Independent development of `inspectrum` is
**frozen** — the canonical home for these modules is now SNAPWrap.

The leading underscore in `_inspectrum` flags this as an *internal*
namespace.  External code should not import directly from here; use the
snapwrap-side wrappers (`snapwrap.sampleMeta.eos`, `snapwrap.sampleMeta.refine`,
…) once they exist.

## Migration plan

The contents of this directory will be progressively promoted into snapwrap
proper (`snapwrap.sampleMeta`, `snapwrap.spectralTools`, …) and this
directory will eventually disappear.  See:

- `docs/inspectrum_absorption_plan.md` — what is vendored vs dropped, and the
  per-module migration targets.
- `docs/crystal_species_refinement_plan.md` — the user-facing motivation
  (CIF-driven `crystalSpecies` + lattice refinement from data).

## What was dropped during vendoring

- `ui/` — PyQt5 widget; `snapwrap.calibrationManager` is the canonical Qt host.
- `cli.py` — stub; snapwrap convention is `scripts/`.
- inspectrum's own `pyproject.toml`, `.github/`, `.vscode/`, `pre-commit`
  config.
- inspectrum's `scripts/` — can be salvaged later as snapwrap scripts.
- inspectrum's `docs/getting-started.md`, `project.md`, `plan.md`, template
  README — replaced by snapwrap's plan docs.

The `LICENSE` file is preserved (BSD-3-Clause, compatible with snapwrap).

## Tests

The vendored test suite lives at `tests/_inspectrum/` and is auto-marked with
the `inspectrum` pytest marker.  The whole tree skips automatically if
`cryspy` is not importable.

```bash
pytest -m inspectrum            # vendored inspectrum tests only
pytest -m "not inspectrum"      # everything else
```
