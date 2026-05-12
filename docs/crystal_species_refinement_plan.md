# Crystal-species refinement plan (CIF → refined `crystalSpecies` artefact)

**Created**: 2026-05-12
**Status**: Phase 0 (vendoring) starting
**Reference**: `inspectrum_absorption_plan.md`, `reduction_artefacts_plan.md`

## Goals

1. **G1** — `crystalSpecies` instantiable directly from a CIF file (Mantid-backed).
2. **G2** — Refine the lattice from real diffraction data, not from the CIF starting
   point (the high-pressure reality: ambient CIF is just a seed).
3. **G3** — Reuse the inspectrum prototype's matching/refinement code rather than
   re-implementing it.
4. **G4** — Make the refined `crystalSpecies` (with EOS-derived per-phase pressure)
   a registerable artefact in `reduction_artefacts/`.
5. **G5** — Don't break existing call sites
   (`io.WorkspaceHandle.crystalSpecies`, `spectralTools.tools`, manual
   `crystalSpecies(...)` construction in user scripts).

## Phases

### Phase 0 — Vendor inspectrum into `src/snapwrap/_inspectrum/`

Mechanical move. No semantic change. Pinned to inspectrum commit `3231f71`
(2026-04-02, "Phase 4.2: UI verified end-to-end").

- Strip `ui/`, `cli.py` from the vendored copy.
- Add `cryspy>=0.10.0` (and `pycifstar` if not pulled transitively) to
  `pyproject.toml` `[tool.pixi.pypi-dependencies]`.
- Move inspectrum tests to `tests/_inspectrum/` with a `pytest` marker so they
  can be run/skipped as a group.
- Copy inspectrum's `LICENSE` to `src/snapwrap/_inspectrum/LICENSE`; note in
  top-level `README.md`.
- Migrate inspectrum's `docs/ground_truths.md` content into
  `docs/ground_truths.md` (snapwrap-side) so the hard-won SNAP tuning history
  survives future renames.

**Exit criteria**: `from snapwrap._inspectrum.engine import inspect` works in
the snapwrap pixi env without `sys.path` hacks; existing snapwrap tests still
pass; vendored inspectrum tests pass under their marker.

### Phase A — `crystalSpecies.from_cif` hardening  ✅ done (May 2026)

Already prototyped via `LoadCIF`. Promoted to first-class:

- A1. ✅ `from_cif` accepts `name`, `dLimits`, `role`
  (`"sample"` | `"calibrant"`), and `eos`.
- A2. ✅ `__init__` accepts `cifPath`, `role`, `eos`; persisted in
  `to_dict`/`from_dict` with `_schema_version: 1`. `from_dict` is tolerant of
  legacy payloads missing the v1 fields.
- A3. ✅ `_cellFromReflections` now logs+returns `None` for
  orthorhombic/monoclinic/triclinic instead of raising — a CIF-seeded cell is
  never clobbered by later observed-reflection refinement on unsupported
  systems.
- A4. ✅ `cubic_d2Inv` bug fixed in `latticeFittingFunctions.py`
  (`ref.h*ref.k` → `ref.k**2`) — parity with the inspectrum fix.
- A5. ✅ `tests/test_sample_meta_from_cif.py` covers W + ice-VII CIFs,
  role validation, EOS round-trip, legacy-dict tolerance (Mantid-gated).
- A6. ✅ `CrystalBoxObject` placeholder replaced in
  `asset_artefact_examples.py`; the `cif_to_crystal_species` slug now builds a
  real `crystalSpecies` via `from_cif`.

### Phase B — EOS object inside `snapwrap.sampleMeta` ✅ done (May 2026)

- B1. ✅ Add `snapwrap.sampleMeta.eos` re-exporting
  `snapwrap._inspectrum.models.EquationOfState as EOS` plus
  `snapwrap._inspectrum.eos.predicted_strain` / `pressure_at`.
  Committed `d001098`. Tests: `tests/test_sample_meta_eos.py` (7 tests, no Mantid).
- B2. ✅ Add `crystalSpecies.eos: EOS | None` attribute, plumbed through
  `to_dict`/`from_dict`. Completed in Phase A commit `f852677`.
- B3. ✅ (Skipped — inspectrum is now vendored, no extra deps required beyond
  what Phase 0 added.)
- B4. ✅ Failure mode: if EOS is missing, `refine` falls back to a blind strain
  search (inspectrum's `sweep_strain`). Committed `8231143`.
  Tests: `tests/test_sample_meta_refine.py` (7 tests, Mantid-gated).

### Phase C — `reduction_artefacts` recognises crystallography ✅ done (May 2026)

- C1. ✅ `AssetType.EOS_DESCRIPTION = "eos_description"` added; `asset_record.schema.json` enum updated.
- C2. ✅ `builders.py`: `load_eos_description(path)` reads `.eos.json` → `EquationOfState`;
  `build_crystal_species(cif_asset, eos_asset=None, role)` → `LoadedAsset[crystalSpecies]`.
  Committed `307156c`. Tests: `tests/test_reduction_artefacts_crystal_species_builder.py` (15 tests, no Mantid).
- C3. ✅ `LoadedAsset[crystalSpecies]` expressible via existing generic; `build_crystal_species` is its factory.
- C4. ✅ `CampaignPaths.crystal_species_index`; `register_crystal_species_artefact()` + `list_crystal_species_records()`
  in `persistence.py`. Fields: `species_name, role, cifPath, eosPath, source_run, refined_a/b/c,
  refinedPressure_GPa, unitCell_updated, cif_asset_id, eos_asset_id`.

### Phase D — Refinement bridge

- D1. New module `snapwrap.sampleMeta.refine`:
  - `refine_species_from_workspace(species_list, ws, instprm_path,
    conditions) -> RefinementReport`.
  - Build `_inspectrum.models.PhaseDescription` per `crystalSpecies` from its
    `cifPath` + `role` + `eos` (re-loading the CIF via inspectrum's loader so
    full symop expansion is preserved — see Risk in §Risks).
  - Convert the Mantid `Workspace2D` to an `_inspectrum.models.DiffractionSpectrum`
    (a thin numeric-array adapter; doesn't go through disk).
  - Call `_inspectrum.engine.inspect(...)`.
  - Map each `LatticeRefinementResult` back onto its `crystalSpecies`
    (mutate `unitCell`, set `refined` summary, rebuild `crystalStructure` via
    `_buildCrystalStructure`).
- D2. `RefinementReport.to_dict()` → JSON artefact persisted under
  `reduction_artefacts/`.
- D3. CLI: `scripts/refine_lattice.py --campaign … --workspace … --species …`.
- D4. Tests: synthetic single-cubic peaks → known `a`; SNAP CSV fixture →
  expect ice-VII `a` within 1% of inspectrum's own integration baseline.

### Phase E — Wire into existing snapwrap flows

- E1. `io.WorkspaceHandle.crystalSpecies` gains a
  `handle.refine_crystal_species(eos_map=None)` convenience wrapping Phase D.
- E2. `spectralTools.tools` consumers see refined d-spacings for free
  (no API change — they read `species.crystalStructure`).
- E3. Document the dual path in `docs/`.

## Risks

| Risk | Mitigation |
|---|---|
| Mantid `LoadCIF` doesn't preserve explicit symops → wrong F² for non-trivial structures (the bug inspectrum fixed) | The refinement bridge hands inspectrum the **CIF path**, not the Mantid `CrystalStructure`. Inspectrum builds its own `CrystalPhase` via `pycifstar` for matching. snapwrap-side `crystalSpecies.crystalStructure` is only ever used for tick-mark generation, never for F²-critical work. |
| Two cell representations (snapwrap `unitCell` vs inspectrum `CrystalPhase.cell`) drift | After refinement, the **snapwrap `crystalSpecies` is the single source of truth**. Inspectrum's `LatticeRefinementResult` is consumed and discarded. |
| `bruciteA.py`-style scripts that pass observed reflections without a CIF | Phase A3 keeps that path working (no raise on unsupported systems); missing `cifPath` simply disables the inspectrum bridge. |
| `crystalSpecies` JSON evolution | `_schema_version` introduced in A2; `from_dict` stays tolerant of v0 (no version field). |

## Out of scope (deferred)

- Background subtraction / peak finding inside snapwrap public API (lives in
  `_inspectrum/` for now; promotion deferred to `spectralTools/`).
- Multi-bank refinement (inspectrum backlog).
- Phase-transition detection.
- Writing back to GSAS-II `.instprm` / `.EXP` files.
- Inspectrum's PyQt5 UI — `CalibrationManager` is the canonical Qt host.
