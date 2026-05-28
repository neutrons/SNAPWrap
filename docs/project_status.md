# SNAPWrap Campaign Manager — Project Status

_Branch: `reduction_artifacts` | Updated: 2026-05-28_

---

## Current state

All work to date is on the `reduction_artifacts` branch, targeting a PR to `next`.

| Phase | Status | Commit(s) |
|---|---|---|
| Phase 1 — Bin mask ID naming reform | ✅ Done | `0da8ec4` |
| Phase 2 — WorkflowQueue/WorkflowStep backend | ✅ Done | `0bf50cd` |
| Phase 3 — WorkflowPanel UI (replaces Reduce + Post-process tabs) | ✅ Done | `d5dbdc5` |
| Post-launch fixes | ✅ Done | `e4ace6d` |
| Bug fix — d-spacing masks in `compute_dspace_gaps` | ✅ Committed, manual testing in progress | `07cce9c` |

### What's in each phase

**Phase 1** — Bin mask artefact IDs now follow `binmask-{units}-{source}[-run{N}]` where units is `wavelength` or `dspacing`. A `_units_tag()` helper in `model.py` reads the swissCheese JSON filename stem to derive the unit tag.

**Phase 2** — `WorkflowStep` / `WorkflowQueue` dataclasses in `workflow.py` (JSON-persisted). Model additions: `loadWorkflowQueue`, `saveWorkflowQueue`, `resolveArtefactsForQueue`, `executeReduceStep`. `build_reduce_kwargs` in `reduce.py` now accepts `selected_artefacts_override`.

**Phase 3** — `WorkflowPanel` in `workflowPanel.py` replaces the old Reduce and Post-process tabs. Expert params on `_ReduceCard` hidden by default with a global toggle. Source prefix (`reduced` vs `resampled`) auto-derived at execution time. `_BinMaskCheckList` for multi-select; `_ArtefactDropdown` for single-select. All queue steps run in a single `GenericWorker` thread.

**Bug fix** — `compute_dspace_gaps` in `postprocessing.py` now splits bin mask paths by filename stem (`_dSpacing` vs `_Wavelength`) and applies each in its correct unit domain: wavelength masks before `ConvertUnits`, d-spacing masks after. Edge-extension (step 4b) now only touches wavelength notches.

---

## Current work — Background extraction

The `reduction_artifacts` PR is pushed (branch `reduction_artifacts` → `next`). Background extraction is now the active workstream.

### Background extraction phases

| Phase | Description | Status |
|---|---|---|
| Phase 0 — Common infrastructure | `"background"` step in workflow + `_BackgroundCard` skeleton | 🔄 In progress |
| Phase 1 — Method 1: ClipPeaks | Rolling sphere; `win_dspacing` param; `bgnd-clip-run{N}` artefact | ⬜ Not started |
| Phase 2 — Method 2: Crystal species + spline | inspectrum pipeline; exclusion regions; weighted spline | ⬜ Not started |
| Phase 3 — Method 3: Composite | Multi-run nanmean; deNAN interpolation; `bgnd-composite-campaign` artefact | ⬜ Not started |

**Artefact IDs:** `bgnd-{method}-run{N}` (Methods 1, 2) or `bgnd-composite-campaign` (Method 3). See `docs/ground-truth.md`.

**Key design decisions locked:**
- `win_dspacing` in Å (not bins) — resampling-independent; derivable from δd/d via SNAPRed resolution workspace
- "Most recent only" retention — no versioning of backgrounds
- Apply by subtraction + positive constant offset (clip at zero)
- Diagnostic workspaces: `bgnd_{method}_dsp_{pgs}_{run}` — named by method for comparison

---

## Upcoming work (not yet started)

### Phase 4c — Inline EOS form in Setup panel

Replace the EOS file picker in `_CrystalPhaseForm` with an inline form. Fields: `eos_type` (murnaghan / birch-murnaghan / vinet), `V_0`, `K_0`, `K_prime`, `source` (free text). The model layer writes a `.eos.json` to the campaign artefact directory and passes the path to `register_crystal_species_artefact`.

**Open questions** (for Malcolm to decide before implementation starts):
1. Expose `stability_pressure` (P_min / P_max) in the UI? If yes, where to store it.
2. Offer V₀ unit conversion in UI (Å³/cell, Å³/atom, cm³/mol), or require Å³/cell directly?
3. Should the EOS sub-form be collapsible / optional?

Key files: `src/snapwrap/campaignManager/panels/setupPanel.py`, `src/snapwrap/campaignManager/model.py`

### Automatic notch detection from transmission monitor

Design notes in `docs/transmission_monitor_for_notched.md`. Uses the transmission monitor (workspace index 1, spectrum 2) to automatically identify notch positions by treating notches as inverted peaks.

---

## Key files (quick reference)

| File | Role |
|---|---|
| `src/snapwrap/campaignManager/model.py` | Model layer — artefact registration, reduction, crop |
| `src/snapwrap/campaignManager/workflow.py` | WorkflowStep / WorkflowQueue dataclasses + JSON persistence |
| `src/snapwrap/campaignManager/panels/workflowPanel.py` | WorkflowPanel Qt widget |
| `src/snapwrap/campaignManager/mainWindow.py` | Main window — wires all panels |
| `src/snapwrap/campaignManager/panels/setupPanel.py` | Setup panel — bin mask + crystal species forms |
| `src/snapwrap/reduction_artefacts/postprocessing.py` | `compute_dspace_gaps` + `apply_dspace_gaps` |
| `src/snapwrap/reduction_artefacts/reduce.py` | `build_reduce_kwargs` |
