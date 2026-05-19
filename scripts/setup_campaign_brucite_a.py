"""IPTS-33219 brucite A — campaign script.

This is the single file you edit and run throughout the experiment.
  - Add runs as they are collected.
  - Add raw assets (CIFs, UB matrices) as they become available.
  - Press Run (F5) at any point — everything else is automatic.

All the heavy lifting lives in ``snapwrap.reduction_artefacts.run_campaign``:
  * IPTS derived from the first run via GetIPTS
  * Assembly type (DAC / PE / OTHER) derived from the first run's SEEMeta
  * SEEMeta ingested for every run via the SNAPWrap convention
  * Bin-mask artefact built automatically for DAC campaigns
      - if UB matrices have been ingested  → swiss-cheese from UBs
      - otherwise                          → notch mask from monitor
  * Per-run reduction via ``reduceSEE`` (auto-discovers manifest + artefacts)
"""
from __future__ import annotations

from snapwrap.reduction_artefacts import run_campaign

# ── Run control ──────────────────────────────────────────────────────────────
# One of:
#   "full"        ingest assets/artefacts AND reduce every run
#   "setup_only"  ingest assets/artefacts, do not reduce
#   "reduce_only" skip ingestion, reduce only (assumes setup was done earlier)
#   "dry_run"     print the plan, touch nothing
MODE        = "setup_only"
CREATED_BY  = "loveday"

# ─── derived flags (don't edit) ──────────────────────────────────────────────
_MODE_FLAGS = {
    "full":        (False, False, False),
    "setup_only":  (False, True,  False),
    "reduce_only": (False, False, True),
    "dry_run":     (True,  False, False),
}
if MODE not in _MODE_FLAGS:
    raise ValueError(f"MODE must be one of {sorted(_MODE_FLAGS)}; got {MODE!r}")
DRY_RUN, SETUP_ONLY, REDUCE_ONLY = _MODE_FLAGS[MODE]

# ── Campaign ─────────────────────────────────────────────────────────────────
CAMPAIGN_SLUG = "dac_brucite_a"
DESCRIPTION   = "Brucite A (Mg(OH)2) high-pressure DAC experiment"

RUNS = [65891]

# Optional: pin the run used for automatic mask generation (default: RUNS[0]).
MASK_SOURCE_RUN: int | None = None

# Mask strategy: "monitor" (notches from transmission monitor) or "ub"
# (swiss-cheese from UB matrices, with monitor fallback).
MASK_PREFER: str = "monitor"

# Keep intermediate mask-building workspaces in a per-run diagnostics group.
KEEP_DIAGNOSTICS: bool = False

# Corrected L2 distance (metres) for monitor2.  The NeXus geometry has the
# wrong value; this overrides it before wavelength conversion so notch
# positions are accurate.
MONITOR2_L2: float = 4.910

# ── Raw assets ───────────────────────────────────────────────────────────────
# Bare filenames are resolved against the canonical sub-folder for the asset
# type (cif → shared/cif/, ub_matrix → shared/ub/, etc.).  UB matrices in
# the campaign's ``artefacts/masks/ubs/`` are auto-discovered — no need to
# list them here.
ASSETS = [
    {
        "asset_type": "cif",
        "asset_id": "cif-brucite",
        "path": "EntryWithCollCode43421.cif",
        "notes": "Brucite Mg(OH)2 — ambient-conditions starting structure",
    },
    {
        "asset_type": "cif",
        "asset_id": "cif-tungsten",
        "path": "EntryWithCollCode79033.cif",
        "notes": "Tungsten W — gasket material / internal calibrant",
    },
]

# ── Manual bin-masks ──────────────────────────────────────────────────────────
# Manually-built swiss-cheese JSON files (e.g. d-spacing diamond peaks
# identified in Workbench after inspecting the unfocussed output).
# These are registered alongside any auto-generated masks; reduction
# passes all registered bin_mask artefacts to binMaskList.
MANUAL_BIN_MASKS = [
    {
        "artefact_id": "dspacing-mask-diamond-65891",
        "mask_path": "/SNS/SNAP/IPTS-33219/shared/masks/SNAP_65891_dSpacing.json",
        "run_number": 65891,
        "notes": "d-spacing diamond Bragg peaks missed by auto wavelength notching",
    },
]

# ── Reduction options (forwarded as wrap.reduce kwargs) ──────────────────────
REDUCE_OPTIONS = {
    "keepUnfocussed": True,
    "verbose": True,
}

# ── Go ───────────────────────────────────────────────────────────────────────
run_campaign(
    campaign_slug=CAMPAIGN_SLUG,
    runs=RUNS,
    assets=ASSETS,
    description=DESCRIPTION,
    created_by=CREATED_BY,
    mask_source_run=MASK_SOURCE_RUN,
    mask_prefer=MASK_PREFER,
    keep_diagnostics=KEEP_DIAGNOSTICS,
    monitor2_l2=MONITOR2_L2,
    reduce_options=REDUCE_OPTIONS,
    manual_bin_masks=MANUAL_BIN_MASKS,
    dry_run=DRY_RUN,
    setup_only=SETUP_ONLY,
    reduce_only=REDUCE_ONLY,
)
