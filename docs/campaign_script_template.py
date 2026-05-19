"""IPTS-XXXXX <sample name> — campaign script (template).

Copy this file, rename it, edit the constants, and press Run (F5) in
Mantid Workbench (or ``python my_campaign.py`` from a shell).

Everything is automatic from there — see
``snapwrap.reduction_artefacts.run_campaign`` for the details:
  * IPTS derived from the first run via GetIPTS
  * Assembly type (DAC / PE / OTHER) derived from the first run's SEEMeta
  * SEEMeta ingested for every run
  * Bin-mask artefact built automatically for DAC campaigns
      - if UB matrices have been ingested  → swiss-cheese from UBs
      - otherwise                          → notch mask from monitor
  * Per-run reduction via ``reduceSEE`` (auto-discovers manifest + artefacts)
"""
from __future__ import annotations

from snapwrap.reduction_artefacts import run_campaign

# ── Run control ──────────────────────────────────────────────────────────────
DRY_RUN     = False
SETUP_ONLY  = False   # ingest assets/artefacts, do not reduce
REDUCE_ONLY = False   # skip ingestion, reduce only
CREATED_BY  = "fedid"

# ── Campaign ─────────────────────────────────────────────────────────────────
CAMPAIGN_SLUG = "my_campaign"
DESCRIPTION   = "My sample — campaign A"

RUNS = [10001]   # ← add more as the experiment progresses

# Optional: pin the run used for automatic mask generation (default: RUNS[0]).
MASK_SOURCE_RUN: int | None = None

# Mask strategy: "monitor" (notches from transmission monitor) or "ub"
# (swiss-cheese from UB matrices, with monitor fallback).
MASK_PREFER: str = "monitor"

# Keep intermediate mask-building workspaces in a per-run diagnostics group.
KEEP_DIAGNOSTICS: bool = False

# ── Raw assets ───────────────────────────────────────────────────────────────
# Bare filenames are resolved against the canonical sub-folder for the asset
# type (cif → shared/cif/, ub_matrix → shared/ub/, etc.).  UB matrices in
# the campaign's ``artefacts/masks/ubs/`` are auto-discovered — no need to
# list them here.
ASSETS = [
    {
        "asset_type": "cif",
        "asset_id": "cif-sample",
        "path": "MySample.cif",
        "notes": "Sample phase CIF",
    },
    {
        "asset_type": "cif",
        "asset_id": "cif-calibrant",
        "path": "Calibrant.cif",
        "notes": "Pressure calibrant / gasket material CIF",
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
    reduce_options=REDUCE_OPTIONS,
    dry_run=DRY_RUN,
    setup_only=SETUP_ONLY,
    reduce_only=REDUCE_ONLY,
)
