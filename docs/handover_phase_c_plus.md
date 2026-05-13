# Phase C+ handover note — campaign manifests + bruciteA real-world fixture

**Written**: 2026-05-12
**Author**: Claude Opus 4.1 (planning)
**Intended executor**: Claude Sonnet 4.6
**Branch**: `reduction_artifacts`
**Last commit at time of writing**: `6d991c1` (Phase C done; Phase D handover)

---

## TL;DR

Phase C left two gaps that block clean Phase D work:

1. There is no asset type for inspectrum-style **multi-phase description files**
   (`snap_phases.json` shape) — only single-material `EOS_DESCRIPTION`.
2. There is no way to **declare a whole campaign** (slug + assets) in one file
   and ingest it. Today every campaign is bootstrapped imperatively.

Phase C+ closes both gaps and produces a permanent **bruciteA fixture** under
IPTS-33219 that Phase D can target as its integration-test substrate.

This is bounded, mostly mechanical work. Five tightly-coupled sub-tasks, all
testable without Mantid.

---

## Decisions already taken (do not re-litigate)

| # | Decision |
|---|---|
| Q1 | Brucite EOS source = **Fei & Mao 1993**. Verify exact values against the paper before writing the JSON; the most commonly quoted are K₀ ≈ 47 GPa, K' ≈ 4.7, V₀ from CIF. **Cross-check with Catti 1995 if Fei & Mao numbers look off.** |
| Q2 | `assembly_type` for the campaign **must be inferred from SEEMeta**, not hardcoded in the manifest. See "Gap discovered" section below. |
| Q3 | Real bruciteA campaign instantiates under `/SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/`. Local repo gets only synthetic unit-test fixtures. |
| Q4 | Absolute paths in manifests are fine for now. Future: IPTS-local + common-shared resolution (gasket types). Out of scope here. |
| Q5 | All five sub-tasks (C+.1 through C+.5) in one handover. |
| Q6 | Phase C+ goes **before** Phase D. |

---

## Gap discovered while planning — fix this first

`infer_assembly_type_from_seemeta()` in
`src/snapwrap/reduction_artefacts/requirements.py` currently looks for keys
`assembly_type`, `assembly`, `sample_environment`, `cell_type`.

**Real SEEMeta files at `/SNS/SNAP/IPTS-33219/shared/SEE/SEE*.json` use a
top-level `"type": "assembly.dac"` instead.** Verified by sampling
`SEE065891.json`:

```python
>>> d = json.load(open('/SNS/SNAP/IPTS-33219/shared/SEE/SEE065891.json'))
>>> d['type']
'assembly.dac'
```

`normalize_assembly_type` already handles the token form
`ASSEMBLY_DAC` → `DAC`, but the inference function never looks at `type`.

### C+.0 — Fix `infer_assembly_type_from_seemeta`

Add `"type"` to the key-search list:

```python
for key in ("assembly_type", "assembly", "sample_environment",
            "cell_type", "type"):
    ...
```

Add a regression test in
`tests/test_reduction_artefacts_requirements.py`:

```python
def test_infer_assembly_type_from_real_see_record():
    # Use the real top-level "type" key as found in
    # /SNS/SNAP/IPTS-33219/shared/SEE/SEE065891.json
    seemeta = {"type": "assembly.dac", "components": []}
    assert infer_assembly_type_from_seemeta(seemeta) == "DAC"
```

This must pass before any other C+ work lands.

---

## Sub-tasks

### C+.1 — `AssetType.PHASE_DESCRIPTION`

Tiny extension to Phase C's enum + schema.

**Edits:**
- `src/snapwrap/reduction_artefacts/assets.py` — add
  `PHASE_DESCRIPTION = "phase_description"` enum value.
- `src/snapwrap/reduction_artefacts/schemas/asset_record.schema.json` —
  add `"phase_description"` to the `asset_type` enum array.
- `src/snapwrap/reduction_artefacts/builders.py` — add:

  ```python
  def load_phase_description(path: str | Path) -> "ExperimentDescription":
      """Wrap inspectrum.loaders.load_phase_descriptions."""
      from snapwrap._inspectrum.loaders import load_phase_descriptions
      return load_phase_descriptions(path)
  ```

  No Mantid required. CIFs referenced inside the JSON are loaded by
  inspectrum's own `load_cif` (cryspy-backed).

- `src/snapwrap/reduction_artefacts/__init__.py` — export
  `load_phase_description`.

**Tests** (extend `tests/test_reduction_artefacts_crystal_species_builder.py`):
1. `AssetType.PHASE_DESCRIPTION == "phase_description"` — value + round-trip via `AssetRecord`.
2. Schema accepts `"phase_description"` — round-trip through
   `register_asset_record` in a `tmp_path` campaign.
3. `load_phase_description` returns an `ExperimentDescription` with the
   expected number of phases (use the existing
   `tests/_inspectrum/test_data/snap_phases.json` fixture — 2 phases:
   tungsten + ice-VII).

### C+.2 — Campaign manifest schema + bootstrap-from-manifest

**New schema file**:
`src/snapwrap/reduction_artefacts/schemas/campaign_manifest.schema.json`

Shape (Draft 2020-12, follow the style of the other schema files):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://neutrons.org/snapwrap/reduction_artefacts/campaign_manifest.schema.json",
  "title": "Reduction Artefacts Campaign Manifest",
  "type": "object",
  "required": ["schema_version", "campaign", "assets"],
  "properties": {
    "schema_version": { "type": "string" },
    "campaign": {
      "type": "object",
      "required": ["slug", "ipts"],
      "properties": {
        "slug": { "type": "string" },
        "ipts": { "type": "integer", "minimum": 1 },
        "assembly_type": {
          "description": "Optional. If absent, MUST be inferred from SEEMeta of source_run or any sample run.",
          "type": "string",
          "enum": ["DAC", "PE", "OTHER"]
        },
        "source_run": {
          "description": "Optional run number used to derive assembly_type via SEEMeta.",
          "type": "integer", "minimum": 1
        },
        "description": { "type": "string" },
        "owners": { "type": "array", "items": { "type": "string" } }
      },
      "additionalProperties": false
    },
    "assets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["asset_id", "asset_type", "path"],
        "properties": {
          "asset_id": { "type": "string" },
          "asset_type": {
            "type": "string",
            "enum": ["cif", "eos_description", "phase_description",
                     "ub_matrix", "seemeta_json", "manual_pixel_mask", "other"]
          },
          "path": { "type": "string" },
          "version": { "type": "integer", "minimum": 1 },
          "applicability": {
            "type": "object",
            "properties": {
              "scope": { "type": "string", "enum": ["campaign", "run"] },
              "run_number": { "type": ["integer", "null"], "minimum": 1 }
            },
            "additionalProperties": true
          },
          "provenance": {
            "type": "object",
            "required": ["source", "created_by"],
            "properties": {
              "source": { "type": "string", "enum": ["manual", "imported", "generated"] },
              "created_by": { "type": "string" },
              "notes": { "type": "string" }
            },
            "additionalProperties": true
          },
          "metadata": { "type": "object", "additionalProperties": true }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

**New persistence function** in
`src/snapwrap/reduction_artefacts/persistence.py`:

```python
def bootstrap_campaign_from_manifest(
    manifest_path: str | Path,
    *,
    shared_root: str | Path | None = None,
    seemeta_dir: str | Path | None = None,
) -> dict:
    """Validate manifest, bootstrap campaign, register every asset.

    Resolution of ``assembly_type``:
      1. If manifest.campaign.assembly_type present → use it (after
         normalize_assembly_type).
      2. Else if manifest.campaign.source_run present → load
         ``{seemeta_dir}/SEE{source_run:06d}.json`` and call
         infer_assembly_type_from_seemeta.
      3. Else: raise ValueError with a helpful message.

    Returns: dict with campaign record + list of asset records.
    """
```

Implementation skeleton:

1. Read + JSON-parse manifest.
2. Validate against `campaign_manifest.schema.json` via `validate_record`
   (extend `_schema_validator` to accept the new schema name).
3. Resolve `assembly_type` per the rule above.
4. Call `bootstrap_campaign(...)`.
5. Loop over `assets` list and call `register_asset_record(...)` for each
   (defaulting `version=1`, `status="active"`, `applicability.scope="campaign"`
   when absent).
6. Return `{"campaign": <campaign_record>, "assets": [<asset_records...>]}`.

**Export** from `__init__.py`:
`bootstrap_campaign_from_manifest`.

**Tests** (new file `tests/test_reduction_artefacts_manifest.py`):

1. Schema validation:
   - Valid manifest passes.
   - Missing `slug` rejected.
   - Unknown `asset_type` rejected.
2. `bootstrap_campaign_from_manifest` with `assembly_type` explicit in
   manifest — campaign created, assets all registered, `assets_index.jsonl`
   contains N rows.
3. Same but with `assembly_type` absent and `source_run` pointing to a
   synthetic SEE file in `tmp_path` containing
   `{"type": "assembly.dac"}` — assembly_type resolves to `"DAC"`.
4. Both `assembly_type` and `source_run` absent → `ValueError`.
5. Idempotent re-run is *not* required — second call should raise
   `SlugConflictError` (existing behaviour). Add a test asserting this.

### C+.3 — bruciteA fixture: Phase description JSON

**File location** (real-world, on the IPTS mount):
`/SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/manifests/bruciteA_phases.json`

(The directory will not exist yet — create it.)

**Content** — follow the shape of the existing
`tests/_inspectrum/test_data/snap_phases.json`:

```json
{
  "instrument": "SNAP",
  "facility": "SNS",
  "pixel_grouping_scheme": "bank",
  "global_conditions": {
    "temperature": 295,
    "max_pressure": 30.0
  },
  "phases": [
    {
      "name": "tungsten",
      "cif": "/SNS/SNAP/IPTS-33219/shared/cif/EntryWithCollCode43421.cif",
      "role": "calibrant",
      "reference_conditions": { "pressure": null, "temperature": 295 },
      "eos": {
        "type": "vinet",
        "order": 3,
        "V_0": 15.862, "V_0_unit": "A3/atom", "Z": 2,
        "K_0": 295.2, "K_0_err": 3.9,
        "K_prime": 4.32, "K_prime_err": 0.11,
        "source": "Dewaele, Loubeyre, Mezouar, PRB 70 094112 (2004)"
      },
      "stability_pressure": [null, null]
    },
    {
      "name": "brucite",
      "cif": "/SNS/SNAP/IPTS-33219/shared/cif/EntryWithCollCode79033.cif",
      "role": "sample",
      "reference_conditions": { "pressure": null, "temperature": 295 },
      "eos": {
        "type": "birch-murnaghan",
        "order": 3,
        "V_0": <FILL_FROM_CIF>, "V_0_unit": "A3", "Z": 1,
        "K_0": <FEI_MAO_1993>,
        "K_prime": <FEI_MAO_1993>,
        "source": "Fei & Mao, JGR 98 11875 (1993)"
      },
      "stability_pressure": [null, null]
    }
  ],
  "spectrum_conditions": [
    { "run_number": 65891, "pressure": null },
    { "run_number": 65892, "pressure": null },
    { "run_number": 65893, "pressure": null },
    { "run_number": 65894, "pressure": null },
    { "run_number": 65895, "pressure": null },
    { "run_number": 65896, "pressure": null }
  ]
}
```

**Action item for the executor**:
- Verify Fei & Mao 1993 brucite EOS values against the paper before
  filling. If the paper is not accessible from the analysis cluster,
  fall back to widely-cited values (typically K₀ ≈ 47 GPa, K' ≈ 4.7,
  V₀ from the CIF) and put a `"K_prime_err"` field if known.
- Read V₀ from `EntryWithCollCode79033.cif` directly (parse `_cell_volume`
  or compute from `_cell_length_a/b/c` and `_cell_angle_*`). Do **not**
  hardcode an estimate.
- Sanity check: load the file via `load_phase_description()` and confirm
  both phases instantiate cleanly. Report any cryspy errors.

### C+.4 — bruciteA fixture: Campaign manifest

**File location**:
`/SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/manifests/bruciteA_manifest.json`

```json
{
  "schema_version": "0.1.0",
  "campaign": {
    "slug": "bruciteA",
    "ipts": 33219,
    "source_run": 65891,
    "description": "Brucite Mg(OH)2 in DAC, W pressure marker, runs 65891-65896",
    "owners": ["malcolm"]
  },
  "assets": [
    {
      "asset_id": "cif-W-icsd43421",
      "asset_type": "cif",
      "path": "/SNS/SNAP/IPTS-33219/shared/cif/EntryWithCollCode43421.cif",
      "applicability": { "scope": "campaign" },
      "provenance": {
        "source": "imported",
        "created_by": "operator",
        "notes": "tungsten, ICSD 43421"
      }
    },
    {
      "asset_id": "cif-brucite-icsd79033",
      "asset_type": "cif",
      "path": "/SNS/SNAP/IPTS-33219/shared/cif/EntryWithCollCode79033.cif",
      "applicability": { "scope": "campaign" },
      "provenance": {
        "source": "imported",
        "created_by": "operator",
        "notes": "brucite Mg(OH)2, ICSD 79033"
      }
    },
    {
      "asset_id": "phases-bruciteA",
      "asset_type": "phase_description",
      "path": "/SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/manifests/bruciteA_phases.json",
      "applicability": { "scope": "campaign" },
      "provenance": {
        "source": "manual",
        "created_by": "operator",
        "notes": "W + brucite, two-phase description for inspectrum bridge"
      }
    }
  ]
}
```

Note: `assembly_type` is **deliberately absent** — the bootstrap function
must derive it from `SEE065891.json` (top-level `"type": "assembly.dac"` →
`"DAC"`).

### C+.5 — Demo script: `scripts/demo_phase_c_plus.py`

Two parts, mirroring the Phase C demo style:

**Part 1 — Synthetic ingest (no IPTS access required)**:
- Build a tiny manifest in `tempfile.TemporaryDirectory()` referencing a
  synthetic `.eos.json` written to disk, an empty `.cif` placeholder, and
  a synthetic SEE record `{"type": "assembly.dac"}`.
- Call `bootstrap_campaign_from_manifest(...)`.
- Print the resolved campaign + listed assets via `list_asset_records`.

**Part 2 — Real bruciteA ingest** (gated on
`Path("/SNS/SNAP/IPTS-33219/shared").exists()`; print a friendly skip
message otherwise):
- Bootstrap `bruciteA` into a `tmp_path` (do **not** persist to
  the IPTS shared mount from this demo — the executor will do that
  manually as the next step).
- Confirm 3 assets registered, assembly resolved to `DAC` from SEEMeta.
- Load the phase description via `load_phase_description` and print
  `phase.name` and `phase.role` for both phases plus the EOS K₀ values.

**Final manual step** (do NOT script this — the executor performs it
once and verifies):

```bash
pixi run python -c "
from snapwrap.reduction_artefacts import bootstrap_campaign_from_manifest
result = bootstrap_campaign_from_manifest(
    '/SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/manifests/bruciteA_manifest.json'
)
print('Campaign:', result['campaign']['campaign_slug'])
print('Assets registered:', len(result['assets']))
"
```

This creates the **real** persistent bruciteA campaign at
`/SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/`. Do this
last; if anything is wrong with the manifest, delete the campaign
directory and the corresponding entry from `_state.json` and retry.

### C+.6 — Update plan doc + Phase D handover

- `docs/crystal_species_refinement_plan.md` — insert a "Phase C+ — Real
  campaign substrate" section between Phase C and Phase D, marked done.
- `docs/handover_phase_d.md` — add a note that Phase D's integration
  tests should use the bruciteA fixture as ground truth.

---

## Test summary expected

| File | New tests |
|---|---|
| `tests/test_reduction_artefacts_requirements.py` | +1 (C+.0 regression) |
| `tests/test_reduction_artefacts_crystal_species_builder.py` | +3 (C+.1) |
| `tests/test_reduction_artefacts_manifest.py` (new) | +5 (C+.2) |

Full suite must remain green (currently 517 passed). Expected after C+:
**~526 passed**.

Run with: `pixi run pytest -q --no-cov`

---

## Files the executor will create or modify

```
MODIFIED:
  src/snapwrap/reduction_artefacts/assets.py                (+1 enum value)
  src/snapwrap/reduction_artefacts/schemas/asset_record.schema.json  (+1 enum entry)
  src/snapwrap/reduction_artefacts/builders.py              (+~20 lines)
  src/snapwrap/reduction_artefacts/persistence.py           (+~80 lines)
  src/snapwrap/reduction_artefacts/requirements.py          (+1 key in tuple)
  src/snapwrap/reduction_artefacts/__init__.py              (+2 exports)
  tests/test_reduction_artefacts_requirements.py            (+1 test)
  tests/test_reduction_artefacts_crystal_species_builder.py (+3 tests)
  docs/crystal_species_refinement_plan.md                   (+ Phase C+ section)
  docs/handover_phase_d.md                                  (+ bruciteA reference)

CREATED:
  src/snapwrap/reduction_artefacts/schemas/campaign_manifest.schema.json
  tests/test_reduction_artefacts_manifest.py
  scripts/demo_phase_c_plus.py
  /SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/manifests/bruciteA_phases.json
  /SNS/SNAP/IPTS-33219/shared/snapwrap/reduction_artefacts/manifests/bruciteA_manifest.json
```

---

## Suggested commit sequence

1. `Phase C+.0: infer_assembly_type_from_seemeta accepts top-level 'type' key`
2. `Phase C+.1: add AssetType.PHASE_DESCRIPTION + load_phase_description loader`
3. `Phase C+.2: campaign_manifest schema + bootstrap_campaign_from_manifest`
4. `Phase C+.3-4: add bruciteA real-world fixture under IPTS-33219` (only the IPTS-mount files; commit *paths*, not the JSON contents themselves if they shouldn't go in git — TBD by executor)
5. `Phase C+.5: demo_phase_c_plus.py end-to-end ingest demo`
6. `docs: mark Phase C+ done; reference bruciteA in Phase D handover`

---

## What this unblocks for Phase D

After C+ lands, Phase D's `refine_species_from_workspace` test can do:

```python
from snapwrap.reduction_artefacts import (
    bootstrap_campaign_from_manifest, list_asset_records, load_phase_description
)

# Re-create bruciteA campaign in tmp_path
bootstrap_campaign_from_manifest(BRUCITE_MANIFEST_PATH, shared_root=tmp_path)

# Pull the phase description asset, load it, build species_list
phase_assets = list_asset_records(
    ipts=33219, campaign_identifier="bruciteA",
    shared_root=tmp_path, asset_type="phase_description",
)
exp = load_phase_description(phase_assets[0]["path"])
species_list = [crystalSpecies.from_cif(p.cif_path, role=p.role, eos=p.eos)
                for p in exp.phases]

# Run the bridge against a real workspace (load via Mantid)
report = refine_species_from_workspace(species_list, ws, instprm_path)
```

That is *exactly* the integration test envisioned in plan §Phase D / D4.

---

## Escalation reminder

Phase D itself still requires a frontier-class model (per
`docs/handover_phase_b.md`). Phase C+ is mechanical enough that Sonnet 4.6
can complete it without escalation, **provided the Fei & Mao EOS values are
verifiable from sources accessible to the executor.** If the paper is
inaccessible, leave the brucite EOS block out of `bruciteA_phases.json` (it
is optional in the inspectrum schema) and add a `# TODO` note for the user
to fill in later.
