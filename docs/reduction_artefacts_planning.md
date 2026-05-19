# Reduction artefacts planning

This document outlines the goals of a new feature to support automated, sample-environment aware reduction using SNAPWRap.

Use scripts/skills_planning to ingest important context on reduction and artefacts in high-pressure data.

## Assets as inputs to artefact creation.

I use the word `asset` to mean an available data object, typically a file on disk, that is potentially useful in the goal of creating reduction artefacts. An important example is a cif file, containing crystallographic information on the sample(s), other examples might be a manually created pixel mask, or UB matrices for both diamonds in a DAC. 

The asset may itself become an artefact or, it could be an important input that can be used to create an artefact.

### Campaigns

A typical user on SNAP will collect data during a specific experiment, identified by its IPTS number. Within that experiment, there are typically several campaigns. A classic example would be a diamond anvil experiment, where three different DACs are loaded and measured. I would call each DAC a campaign. The importance of this is that all runs within a specific campaign will likely share useful assets and artefacts.

An important consideration is that the specific run numbers in a campaign will likely not be known in advance. So, a campaign must have a `runs` attribute that can continually be updated during the experiment (but becomes static when the experiment ends).

Each campaign has to we writable to disk in a way that allows its `runs` and any `assets` to be recovered during a reduction run.

### Current list of assets

1. cif file. This is a standard format for conveying crystallographic information. Potentially multiple cif files may be needed for a given reduction flow. As the measurements are likely at high pressure, the atomic structure in the cif file should be considered provisional

2. UB Matrixes. For DAC reduction, the bin mask artefact _can_ be constructed using a pair of two UB matrices, which describe the orientation of the diamond crystal lattices relative to the beam. UB Matrixes follow a standard "ISAW" format, often these can be auto determined from an input diffraction dataset. Often a pair of UB matrices will apply to an entire campaign

3. Sample environment specification. The SEEMeta json acts as a very useful asset and should be available for every run in a campaign although, typically a campaign will have identical SEEMeta.

4. A manual pixel mask. A user could manually create a pixel mask, say to remove pixels occluded by some equipment. Typically this would be stored to disk as a .nxs format file and would be applicable to all runs in a campaign.


### Asset creation and ingestion

We will need to find a way to easily define a set of assets. A user will typically begin a campaign with some foreknowledge. For example, they may have cif files for the samples they are measuring. But then additional assets/artefacts may have to be generated from data. An example is the diamond UB matrices, which require diffraction data in order to be calculated. 

Thus, the asset list for a given run should be viewed as a dynamic evolving thing becoming richer as more data are applied. We should therefore create a separate workflow for asset/artefact creation that can be executed prior to reduction and which stores the files it creates to disk, so that subsequent runs (from the same campaign) can use these existing data as rich applicable context.

Once an asset is ingested and becomes an artefact, it will typically reside in memory as a mantid workspace or other data object.

### Artefacts gathering

The best way to categorize what artefacts are needed for a given reduction is via the SEEMeta: if a PE cell is used or a DAC is used, these require different artefacts. We should therefore envisage a way to define specific artefact gathering instructions for each assembly type. To add more complexity, it should also be possible to specify alternate artefact creation methods for a given assembly type. 

Current list of artefacts:

1. a crystalBox object. This is a python class generated via a cif file asset and is a class from which multiple crystallographic properties can be derived. It is used in background extraction. The crystalBox module is not currently in SNAPWrap so this has to be imported.

2. a bin mask object. This is primarily used for DAC reduction and has the form of a mantid table workspace. It can be automatically generated given two UB Matrix assests correspondind to the DACs anvils. It can also be extracted from transmission monitor data, extracted from an input neutron datasets (.nxs file), currently this is a manual process, but it is intended to automate this. Thus a user should be able to specify the preferred artefact creation route. A third way to generate this is fully manual: a user inspect a neutron dataset and manually masks this. In this case, this must be done in advance of artefact collection so that the artefact is available to be collected.

3. a pixel mask object. For PE cells, there is a standard "letterbox" mask shape that is typically applied to all datasets. There is also a customized version of this that adapts to the exact geometry of the run. The former could be loaded direct from disk, the latter requires input neutron data that must be processed. 

4. an attenuation correction workspace. This is a mantid 2d matrix workspace in units of wavelength. It is applied by dividing an unfocussed sample workspace in wavelength space, prior to diffraction focusing (this is not yet implemented).

### Artefact tracking

We need a standardized way to track all artefacts that are required in order to successfully execute a specialised high-pressure reduction workflow. Artefacts must be indexed to a run number so that they can be retrieved during reduction of that specific run. We also need a way to identify what the artefact is i.e. assign it a type. Note that artefacts may be different shapes: a bin mask artefact is a tableworkspace

We must also create a record so that the exact artefacts can be recovered in the future should re-reduction be required.

Another important consideration: it's foreseen that we will also have to support post-reduction operations on the data, for example, to support background subtraction routines. We may also want to label artefacts according to whether their intendedd use is pre- or post-reduction

## Some Concrete examples

### Diamond anvil cell experiments

Experiments that use a DAC require a standard set of artefacts. Typically some kind of bin/pixel mask and a crystallographic object containing information about the sample(s) and, likely, the gasket which may also contribute to the scattering signal.

Typical flow is outline below 

#### Before measurement at the start of a campaign

At this point, we have no data, but we do know what the sample is supposed to be and should also know details of the loading, for example that this experiment uses a DAC and what the gasket material is via SEEMeta. So, beyond SEEMeta, the only likely inputs are cif files for the sample (typically at ambient conditions) and the gaskets. 

This is likely insufficient to complete a successful reduction, therefore reduction will have to be preceded by a workflow that creates needed artefacts

#### Data available from the first run of a campaign

For now, let's assume that the first run aquisition has completed and, therefore, a .nxs file is available with the corresponding data (in a future iteration we should extend this to include an ongoing run, where the live data are used to generate artefacts).

The user will need to generate a bin mask object. Here we will enable two optional routes to generate is: 1. via ub matrix and 2. via transmission monitor data. The user must be able to specify which. In both cases, neutron data must be loaded _prior_ to the reduction run itself.

Once the bin mask artefact has been created, it should be saved to disk as an asset for the campaign, so subsequent runs may use it. 

It can then be used in a reduction run. Importantly, success/failure of a particular bin mask is often not known until _after_ reduction completes. Therefore, we have to enable some iterative process whereby a new mask may need to be generated followed by another reduction run and inspection. When the user is satisfied, the asset should be saved for future runs.

#### Subsequent runs in the campaign

For subsequent runs, we should already have a more complete set of artefacts to complete a reduction. However, we may need to regenerate some artefacts. A common example is that a bin Mask will typically grow dramatically as the pressure increases and the diamonds strain. Therefore, an existing bin mask should be treated as "a good starting point" for a later run, rather than an absolute truth.

If a bin mask is updated, then the specific instance of that artefact should be stored as a new asset so it can then be used as the starting point for a subsequent run.

### PE cell experiments

Experiments in a PE cell require a standard set of artefacts. A standard or customized pixel mask is always needed. Additionally an attenuation workspace is needed, but the machinery to calculate this is not yet available (let's flag this as an important TOOD and include it in the artefact creation for PE cells)

#### Before measurement at the start of a campaign

This is generally much easier than DACs as the SEEMeta should specify all necessary parameters to generate artefacts. If specificed the standard letter box pixel mask can be aquired for any PE cell datasets. 

Although not yet implemented, it is intended that an attenuation workspace will be created, but this can be build using solely information in SEEMeta

#### Data available from the first run of a campaign,

If the user elects to use a custom pixel mask, this will require input data to generate (snapwrap.maskUtils has a function that can do this given an input unfocused workspace (only lite data are supported)

#### Subequent runs in the campaign

These will be treated the same as the first run of a campaign.


[If ](SNS/SNAP/shared/Malcolm/code/inspectrum/src/inspectrum/models.py)

## Glossary (normative)

These terms are used precisely throughout this document. Implementations must
conform to these definitions.

- **IPTS**: Integrated Proposal Tracking System number identifying a SNAP
  experiment. Drives the on-disk root `/SNS/SNAP/IPTS-<ipts>/shared/`.
- **Campaign**: A logically grouped subset of runs within a single IPTS that
  share the same physical configuration (e.g. a single DAC loading). Identified
  by both `campaign_slug` (human) and `campaign_id` (numeric, monotonic per
  IPTS). A run belongs to exactly one campaign.
- **Asset**: A persisted on-disk input that is potentially useful for building
  artefacts (e.g. CIF, UB pair, manual mask, SEEMeta JSON). An asset is a
  *file*; it carries no in-memory representation by itself. An asset may be
  campaign-wide or run-specific.
- **Artefact**: A reduction-ready data object derived from one or more assets
  and/or neutron data, used directly by a reduction workflow (e.g. crystalBox
  instance, bin mask table workspace, pixel mask workspace, attenuation
  workspace). An artefact has a *type*, an *intended_use* (`pre_reduction` or
  `post_reduction`), and a *creation method*.
- **Method**: The named procedure used to derive an artefact from its inputs
  (e.g. `bin_mask.from_ub_pair`, `bin_mask.from_transmission`,
  `bin_mask.manual_import`, `pixel_mask.letterbox`, `pixel_mask.custom`).
- **Manifest**: A per-run record (`manifests/run_<run>.json`) capturing the
  exact assets and artefacts (by id and content hash) used in a reduction run,
  enabling reproducible re-reduction.
- **Index**: A JSONL append-only log of records of one kind
  (`assets_index.jsonl`, `artefacts_index.jsonl`, `runs.jsonl`). The index is
  the source of truth; physical files are addressed by stable ids.
- **Supersede**: The act of marking an existing asset/artefact record as
  `superseded` while writing a new active record that references the prior id
  via `supersedes`. Supersede is non-destructive; history is preserved.
- **Active record**: The most recent record for a given logical asset/artefact
  whose `status` is `active`. At most one active record exists per logical
  identity at any time.

## Implementation roadmap and milestones

This section is the execution plan for the `reduction_artefacts` effort. It is
intended to be kept live and updated as work progresses.

### Filesystem conventions (agreed)

IPTS root is authoritative:

`/SNS/SNAP/IPTS-<ipts>/shared/`

Reduction artefacts root under shared:

`/SNS/SNAP/IPTS-<ipts>/shared/snapwrap/reduction_artefacts/`

Proposed v1 layout:

```text
/SNS/SNAP/IPTS-<ipts>/shared/snapwrap/reduction_artefacts/
├── schema_version.json
├── campaigns/
│   ├── <campaign_slug>/
│   │   ├── campaign.json
│   │   ├── runs.jsonl
│   │   ├── assets_index.jsonl
│   │   ├── artefacts_index.jsonl
│   │   ├── manifests/
│   │   ├── assets/
│   │   ├── artefacts/
│   │   └── logs/
└── cache/
```

### Campaign identity conventions (agreed)

Each campaign has both:

- `campaign_slug` (human-readable): user-facing identifier, e.g. `dac_fe_01`
- `campaign_id` (numeric): machine-stable integer (monotonic within IPTS)

Both are stored in `campaign.json`, and index records should include both.

Example:

```json
{
	"campaign_id": 3,
	"campaign_slug": "dac_fe_01",
	"ipts": 35214,
	"assembly_type": "DAC"
}
```

### Campaign ID allocation rules (agreed)

These rules govern how `campaign_id` and `campaign_slug` are assigned and
maintained. They are designed for a small number of concurrent writers on a
shared filesystem (POSIX-style locking).

#### `_state.json` (per-IPTS allocation ledger)

A single file per IPTS holds the monotonic allocator state and slug → id map:

`/SNS/SNAP/IPTS-<ipts>/shared/snapwrap/reduction_artefacts/_state.json`

Schema (now formalized in `src/snapwrap/reduction_artefacts/schemas/state.schema.json`):

```json
{
	"schema_version": "0.1.0",
	"ipts": 35214,
	"next_campaign_id": 4,
	"campaigns": {
		"dac_fe_01": {"campaign_id": 1, "created_at": "2026-05-11T12:00:00Z", "status": "active"},
		"dac_fe_02": {"campaign_id": 2, "created_at": "2026-05-11T12:30:00Z", "status": "active"},
		"pe_h2o_01": {"campaign_id": 3, "created_at": "2026-05-11T13:00:00Z", "status": "active"}
	},
	"aliases": {
		"dac_iron_01": "dac_fe_01"
	}
}
```

#### Allocation rules

1. **`campaign_id` is monotonic and never reused.** On allocation, the writer
	 reads `_state.json`, takes `next_campaign_id`, increments it, and writes
	 atomically (write to temp file then `os.replace`) under an `flock` on
	 `_state.json.lock`.
2. **`campaign_slug` is unique within an IPTS.** Slug must match
	 `^[a-z0-9][a-z0-9_-]{1,62}$`. Reserved slugs: `cache`, `_state`, anything
	 starting with `_`.
3. **Slug → id is established at creation and is immutable.** Once a campaign
	 directory is created, its `campaign_id` cannot change.
4. **Slug rename is supported via aliasing.** A rename:
	 - Adds an entry in `aliases` mapping `old_slug -> new_slug`.
	 - Renames the on-disk directory `campaigns/<old_slug>/` to
		 `campaigns/<new_slug>/`.
	 - Updates `campaign.json` `campaign_slug` field; `campaign_id` is unchanged.
	 - All historical index records retain the slug they were written with;
		 lookups must consult `aliases` to resolve old slugs.
5. **Lookup precedence.** Resolution order for a user-supplied identifier:
	 (a) numeric `campaign_id`, (b) exact `campaign_slug` match, (c) `aliases`
	 lookup. First match wins.
6. **Concurrency.** All mutations of `_state.json` and any `*_index.jsonl` go
	 through `fcntl.flock` on a sibling `.lock` file. Readers may read without a
	 lock (JSONL is append-only and line-atomic on POSIX for `< PIPE_BUF`-sized
	 writes; record writes must be `<= 4 KiB` and end with `\n`).
7. **Crash safety.** `_state.json` writes use the temp-file + `os.replace`
	 pattern. If a writer crashes between `_state.json` update and campaign
	 directory creation, a recovery scan reconciles by listing `campaigns/` and
	 reporting orphans; allocator never reuses ids.
8. **Status field.** Campaigns may be `active`, `closed` (no further writes
	 expected), or `archived` (read-only, may be moved to cold storage).

#### Bootstrap algorithm (Phase 1 reference)

```
acquire flock(_state.json.lock)
load _state.json (create if absent with next_campaign_id=1)
if slug in campaigns or slug in aliases: raise SlugConflict
cid = state.next_campaign_id
state.next_campaign_id += 1
state.campaigns[slug] = {campaign_id: cid, created_at: now, status: "active"}
write _state.json atomically (tmp + os.replace)
mkdir campaigns/<slug>/ and write initial campaign.json
release flock
```

### Lifecycle and state transitions

Each persisted entity has an explicit lifecycle. State is recorded in the
`status` field of the relevant record and changes are realised by appending a
new record to the appropriate index (never by mutating prior records).

#### Campaign

States: `active` → `closed` → `archived`

- `active`: experiment in progress; runs and assets/artefacts may be added.
- `closed`: experiment complete; no further runs expected. New artefact
	versions may still be added (e.g. for re-reduction).
- `archived`: read-only; may be relocated to cold storage. A pointer file is
	left at the original path.

Transitions are explicit operator actions and recorded in `_state.json` and
`campaign.json` with timestamps.

#### Asset

States: `active` → (`superseded` | `invalid` | `archived`)

- `active`: current canonical version of this logical asset.
- `superseded`: replaced by a newer version; new record's `supersedes` field
	references this record's id.
- `invalid`: explicitly marked as not usable (e.g. wrong CIF was ingested);
	retained for audit but excluded from resolution.
- `archived`: kept for history; not selected by default.

#### Artefact

States: `active` → (`superseded` | `invalid` | `archived`)

Same semantics as Asset. Additionally:

- An artefact's selection for a given run is recorded in that run's manifest
	and is immutable once written.
- Updating an artefact (e.g. evolving DAC bin mask) writes a new `active`
	record with `supersedes` set; the prior record becomes `superseded`. Past
	manifests still reference the prior record by id, preserving reproducibility.

#### Run

States: `pending` → `acquired` → `reduced` → (`re_reducing` → `reduced`)*

- `pending`: declared as part of the campaign but no neutron data yet.
- `acquired`: `.nxs` exists; eligible for artefact creation and reduction.
- `reduced`: a manifest has been written for at least one reduction attempt.
- `re_reducing`/`reduced`: subsequent reductions append additional manifests;
	manifests are versioned by `attempt_number`.

### Phase 0 schema stubs (created)

Runtime schema files now live in:

`src/snapwrap/reduction_artefacts/schemas/`

- `src/snapwrap/reduction_artefacts/schemas/campaign.schema.json`
- `src/snapwrap/reduction_artefacts/schemas/asset_record.schema.json`
- `src/snapwrap/reduction_artefacts/schemas/artefact_record.schema.json`
- `src/snapwrap/reduction_artefacts/schemas/run_manifest.schema.json`

These define minimal record contracts for:

- `campaign.json`
- one-line records in `assets_index.jsonl`
- one-line records in `artefacts_index.jsonl`
- per-run files in `manifests/run_<run>.json`

### Phase plan

#### Phase 0 — Contract freeze

Scope:

- freeze vocabulary (`asset`, `artefact`, `campaign`, `method`, `intended_use`)
- freeze path conventions and campaign ID strategy
- define minimal JSON schemas for campaign + index records

Milestone:

- [x] approved contract section in this doc and schema stubs committed

#### Phase 1 — Persistence skeleton

Scope:

- implement campaign directory bootstrap
- implement `campaign.json`, `runs.jsonl`, `assets_index.jsonl`, `artefacts_index.jsonl`
- append-only log/event writing

Milestone:

- [x] campaign can be created, loaded, and round-tripped from disk

#### Phase 2 — Requirement resolver (assembly-aware)

Scope:

- map SEEMeta/assembly to required artefact types
- support method preference selection (especially DAC bin-mask routes)
- emit missing/available checklist per run

Milestone:

- [x] deterministic requirement report for DAC and PE runs

#### Phase 3 — Asset ingestion workflows

Scope:

- ingest/validate CIF, UB pair, manual masks, SEEMeta references
- record applicability scope (campaign-wide vs run-specific)

Milestone:

- [x] all v1 asset types can be ingested and indexed

#### Phase 4 — Artefact creation workflows (v1)

Scope:

- DAC bin mask creation routes (UB-driven, transmission-driven, manual import)
- PE mask creation routes (letterbox, custom)
- crystalBox generation from CIF
- attenuation workspace tracked as planned/TODO where unavailable

Milestone:

- [x] first-run campaign flow can generate and persist required artefacts

#### Phase 5 — Reduction-time selection + provenance

Scope:

- resolve best artefact for a run and method policy
- persist per-run reduction manifest of exact artefacts used
- support supersede/version lineage

Milestone:

- [x] re-reduction can reproduce identical artefact selection

#### Phase 6 — Iteration and operator workflow

Scope:

- support iterative updates (e.g., evolving DAC bin mask)
- promote/reject artefact versions and preserve history
- add concise diagnostics/log summary views

Milestone:

- [ ] user can iterate artefact -> reduce -> inspect -> supersede in one workflow

### Progress log (living)

Update this table whenever phase status changes.

| Date | Area | Update | Status |
|---|---|---|---|
| 2026-05-11 | Planning/Tooling | Added standalone `scripts/skills_planning.py` so planning context ingestion stays out of core package runtime. | Done |
| 2026-05-11 | Architecture | Agreed IPTS shared root convention and proposed `shared/snapwrap/reduction_artefacts` directory layout. | Done |
| 2026-05-11 | Architecture | Agreed dual campaign identifiers (`campaign_slug` + numeric `campaign_id`). | Done |
| 2026-05-11 | Phase 0 | Created schema stubs for campaign, asset records, artefact records, and run manifests. | Done |
| 2026-05-11 | Architecture | Moved schemas from `docs/` into runtime module path `src/snapwrap/reduction_artefacts/schemas/` for executable validation usage. | Done |
| 2026-05-11 | Plan | Added normative Glossary, Lifecycle/state-transition rules, Campaign ID allocation rules with `_state.json` design, and Risks/Assumptions sections. | Done |
| 2026-05-11 | Phase 1 | Added `state.schema.json`, campaign bootstrap allocator helpers, and JSONL schema validation helpers in `src/snapwrap/reduction_artefacts/persistence.py`. | Done |
| 2026-05-11 | Phase 1 | Added persistence round-trip and validation tests in `tests/test_reduction_artefacts_persistence.py`. | Done |
| 2026-05-11 | Phase 1 | Added `rename_campaign_slug` and `resolve_campaign_slug` (id/slug/alias lookup precedence) and tests for alias-backed slug migration behavior. | Done |
| 2026-05-11 | Phase 2 | Added run-facing requirement report generation (`generate_requirement_report_for_run`) with optional manifest persistence under `campaigns/<slug>/manifests/requirements_run_<run>.json`. | Done |
| 2026-05-11 | Phase 2 | Added operator scripts `scripts/run_requirements_report.py` (single/multi-run) and `scripts/run_requirements_batch.py` (campaign dictionary template mode). | Done |
| 2026-05-11 | Phase 2 | Added ad-hoc dry-run fallback for IPTS/campaigns without existing `_state.json` and improved user-facing error guidance for missing assembly context. | Done |
| 2026-05-11 | Phase 1 | Added multiprocessing contention tests (`tests/test_reduction_artefacts_concurrency.py`) validating `flock` allocator correctness (unique monotonic IDs + same-slug conflict behavior). | Done |
| 2026-05-11 | Phase 2 | Added assembly-aware requirement resolver (`src/snapwrap/reduction_artefacts/requirements.py`) with deterministic DAC/PE requirement checklist and method preference selection. | In Progress |
| 2026-05-11 | Phase 2 | Added resolver tests (`tests/test_reduction_artefacts_requirements.py`) covering SEEMeta inference, deterministic ordering, method preference selection, and missing/ready summary. | In Progress |
| 2026-05-18 | Phase 4 (DAC) | Added clip-peaks (SNIP) continuum option to `detect_notches_in_spectrum` with full pipeline diagnostics (`_diag`, `_pipeline`, `_kept` workspaces) via `scripts/inspect_transmission_notches.py`. Validated on real data: `DIP_THRESHOLD ≈ 0.98` gives near-perfect notch identification. | Done (recipe-level) |
| 2026-05-18 | Planning | Parked recipe-level follow-ups (adaptive threshold, raw-mask diagnostic, presets, sweep harness, robustness guards, provenance capture) under "Deferred follow-ups — notch_from_monitor recipe" to refocus on Phase 2 closeout + Phase 3 ingestion surface + Phase 5 provenance manifests. | Done |
| 2026-05-18 | Phase 2 | Added `unsupported: True` flag to requirement report when assembly_type is `OTHER`. Added round-trip tests for `generate_requirement_report_for_run` with `persist=True`/`False`. | Done |
| 2026-05-18 | Phase 3 | Implemented `ingest_asset(...)`: validates AssetType enum, copies to managed store via `copy_to_asset_store`, computes SHA-256 checksum, auto-increments version, handles supersede semantics (new record carries `provenance.supersedes` list of prior active record_ids). Added `ingest_seemeta_for_run` convenience. Added `scripts/ingest_asset.py` CLI. Extended `asset_record.schema.json` provenance sources to include `"acquired"`. | Done |
| 2026-05-18 | Phase 4 (PE) | Added `register_attenuation_artefact_planned(...)` to declare PE attenuation requirement with `status="planned"` / `path="PENDING"` without a real generator (R7 mitigation). Extended `artefact_record.schema.json` status enum to include `"planned"`. | Done |
| 2026-05-18 | Phase 5 | Implemented `build_run_manifest(...)`: resolves assembly type, builds requirement report, selects best active artefact per type using method policy, auto-increments attempt number, writes `manifests/run_<run>_attempt_<n>.json` per `run_manifest.schema.json`, returns manifest dict with `manifest_path`. Added `scripts/show_run_resolution.py` for read-only preview using normative glossary terms. | Done |

### Risks and assumptions

Tracked so reviewers and future contributors can challenge them explicitly.

#### Assumptions

- A1. Single SNAP instrument; IPTS-rooted shared filesystem is always
	writable by the running user. No multi-instrument abstractions in v1.
- A2. POSIX semantics for `os.replace`, `fcntl.flock`, and append-atomic
	writes up to `PIPE_BUF` (4 KiB) bytes. GPFS at SNS satisfies this.
- A3. Concurrent writers per campaign are rare (typically one operator). The
	allocator must be safe but is not optimised for high contention.
- A4. SEEMeta is always available and authoritative for assembly type
	(`DAC` / `PE` / `OTHER`). Reduction requirements derive from SEEMeta.
- A5. Mantid workspaces created from artefact records are not themselves
	persisted as artefacts; they are reconstructed on demand from the asset
	plus method + parameters recorded in the artefact record.
- A6. CIF, UB, manual mask asset files are immutable once ingested. Edits
	require a new asset record (supersede).
- A7. Re-reduction is possible iff every record referenced in the run
	manifest is still resolvable on disk by id and content hash.

#### Risks (and mitigations)

- R1. **Index corruption** from interrupted writes.
	*Mitigation*: append-only JSONL with line-atomic writes ≤ 4 KiB; a
	`fsck`-style validator (Phase 1 deliverable) that reads the index and
	flags malformed lines without losing prior records.
- R2. **Slug collisions** across separate operators.
	*Mitigation*: `_state.json` allocator under `flock`; slug uniqueness
	enforced at allocation time (rule 2); rename via alias only.
- R3. **Lost lineage** when an artefact is regenerated outside the framework.
	*Mitigation*: artefact records require `method` + `inputs` (asset ids and
	hashes); CLI must refuse to register an artefact without them. A future
	"adopt" workflow can wrap legacy artefacts but must mark them
	`provenance: legacy`.
- R4. **Schema drift** between code and on-disk records.
	*Mitigation*: every record carries `schema_version`; loader validates and
	can dispatch to migration shims. Schemas are packaged with snapwrap
	(already done) so version is pinned to the installed code.
- R5. **Cold storage / archival** breaks reproducibility.
	*Mitigation*: archival writes a pointer file at the original path with the
	new location and a content manifest; loaders follow pointers transparently.
- R6. **CrystalBox external dependency** is not in SNAPWrap.
	*Mitigation*: capture import path and version in artefact record
	`provenance.tooling`; treat unavailability as a structured error, not a
	crash.
- R7. **Attenuation workspace not yet implementable**.
	*Mitigation*: schema permits `status: "planned"` artefact records so PE
	flow can declare the requirement now and fulfil it later without schema
	change.
- R8. **Operator confusion between assets and artefacts**.
	*Mitigation*: glossary above is normative; CLI and log messages must use
	these terms exactly; a Phase 6 diagnostic command should print the
	resolved set per run with both labels.

### Next explicit actions

1. ~~Define campaign bootstrap rules (`campaign_id` allocation, slug uniqueness, and slug rename policy).~~ **Done — see "Campaign ID allocation rules".**
2. ~~Promote the informal `_state.json` shape to a JSON schema in
	 `src/snapwrap/reduction_artefacts/schemas/state.schema.json`.~~ **Done.**
3. ~~Add JSONL writer/reader helpers that validate each record against the
	 packaged schemas (use `jsonschema` Draft 2020-12).
~~ **Done (initial implementation).**
4. ~~Implement the Phase 1 bootstrap algorithm with `flock`-based concurrency
	 and round-trip tests under `tests/test_reduction_artefacts_*.py`.~~ **Done (initial implementation).**
5. ~~Add a `fsck`-style index validator (R1 mitigation) as part of Phase 1.~~ **Done (initial `validate_jsonl_file`).**
6. ~~Add explicit alias-based slug rename support (`rename_campaign_slug`) and tests that verify backward lookup through `_state.json.aliases`.~~ **Done (`rename_campaign_slug` + `resolve_campaign_slug` + tests).**
7. ~~Add concurrent writer tests (multi-process) to verify monotonic `campaign_id` allocation and lock behavior under contention.~~ **Done (`tests/test_reduction_artefacts_concurrency.py`).**
8. Wire Phase 2 resolver into a thin run-facing entry point (e.g., report builder from campaign + run context) and persist requirement report snapshots to `manifests/` for traceability.
9. Run a real-IPTS shadow pilot (read-only reporting mode) on a mixed DAC/PE dataset to validate campaign segmentation and missing/available requirement outputs before enabling write-back workflows.

### Deferred follow-ups — `bin_mask.from_transmission` (notch_from_monitor) recipe

The clip-peaks (SNIP) continuum path inside
`detect_notches_in_spectrum` / `build_swiss_cheese_from_transmission_monitor`
is functionally proven on real data (DIP_THRESHOLD ≈ 0.98 gives near-perfect
results on the test datasets), and pipeline diagnostics
(`snapwrap_trans_<RUN>_diag` / `_pipeline` / `_kept` workspaces) are in
place for tuning. The following recipe-level improvements are **explicitly
deferred** so we can prioritise the broader asset → artefact → reduction
architecture. They should be picked up after Phase 5 lands, or earlier if a
real campaign requires them:

- D1. **Adaptive dip threshold.** Replace the magic `DIP_THRESHOLD` constant
	with a `dip_threshold_mode` argument supporting `"fixed"` (current),
	`"mad"` (`baseline - k * MAD(ratio)`), and `"percentile"`. Clamp to a
	sane band (e.g. `[0.85, 0.995]`) and expose `dip_threshold_k`.
- D2. **Raw-threshold diagnostic row** in the `_kept` workspace so the raw
	`ratio < threshold` mask is visible alongside the post-processed
	(merge / min-width / edge-pad) notches.
- D3. **Per-instrument / per-assembly presets** for `clip_win_size`,
	`clip_smoothing`, `dip_threshold` once Phase 5 method-policy resolution
	exists. These belong with the method record, not in the script.
- D4. **Parameter-sweep harness** (notebook or script) to calibrate defaults
	on a curated set of runs and record recommended presets in the campaign.
- D5. **Robustness guards** in `detect_notches_in_spectrum`: detect
	pathological SNIP outputs (e.g. `cont <= 0`, ratio baseline far from 1),
	emit structured warnings, and fall back to the median continuum.
- D6. **Capture clip-peaks parameters in the artefact record** so a bin
	mask built via this route can be reproduced byte-for-byte under Phase 5
	provenance rules.

These items are tracked here (not as TODOs in source) to keep the recipe
surface stable while the architectural phases are in flight.

### Revised priorities (post clip-peaks excursion)

The clip-peaks work depth-tested one Phase 4 method. The remaining
architectural backbone is the higher priority. Revised ordering:

1. **Close Phase 2.** Flip the resolver/report entries in the progress log
	 from *In Progress* to *Done* once (a) the resolver covers `OTHER` /
	 unknown assembly types with an explicit `unsupported` outcome and (b)
	 the report snapshot path under `manifests/requirements_run_<run>.json`
	 is covered by a round-trip test.
2. **Complete Phase 3 — asset ingestion surface.** A single
	 `ingest_asset(...)` entry point that: validates the asset against its
	 `AssetType`, copies into `assets/` via `copy_to_asset_store`, computes
	 content hash, appends an `AssetRecord` to `assets_index.jsonl`, and
	 honours supersede semantics. Add a thin `scripts/ingest_asset.py`
	 wrapper and an `ingest_seemeta_for_run` convenience that registers the
	 run-specific SEEMeta JSON automatically.
3. **Fill the PE side of Phase 4.** Wire `pixel_mask.letterbox` and
	 `pixel_mask.custom` through `register_pixel_mask_artefact`, and land
	 the `attenuation_workspace` artefact as a `status: "planned"` record
	 so PE campaigns can declare and resolve the requirement before the
	 generator exists (per R7).
4. **Begin Phase 5 — provenance manifests.** Introduce
	 `build_run_manifest(campaign, run, selections)` that:
	 - resolves the active artefact record per required type using the
		 Phase 2 method policy,
	 - writes `manifests/run_<run>_attempt_<n>.json` per the
		 `run_manifest.schema.json`,
	 - records the asset → artefact → method chain plus content hashes so
		 re-reduction is reproducible.
5. **Phase 6 — iteration helpers.** A `supersede_artefact(...)` helper plus
	 a one-screen diagnostic (`scripts/show_run_resolution.py`) that prints
	 the resolved asset/artefact set per run using the normative glossary
	 terms (R8 mitigation).

Concretely, the next deliverable I'd recommend is **(2)**: a unified
`ingest_asset` API plus tests. It unblocks both the PE Phase 4 work and the
Phase 5 manifest builder, because both consume `AssetRecord` lookups by id
and hash.
