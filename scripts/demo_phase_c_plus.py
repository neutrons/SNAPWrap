"""Phase C+ end-to-end demo: campaign manifest ingest + SEEMeta inference.

Part 1 — Synthetic ingest (always runs; no IPTS mount required).
Part 2 — Real bruciteA ingest from IPTS-33219 (gated on mount existence).

Run:
    pixi run python scripts/demo_phase_c_plus.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from snapwrap.reduction_artefacts import (
    bootstrap_campaign_from_manifest,
    list_asset_records,
    load_phase_description,
)

_IPTS_SHARED = Path("/SNS/SNAP/IPTS-33219/shared")
_BRUCITE_MANIFEST = (
    _IPTS_SHARED
    / "snapwrap"
    / "reduction_artefacts"
    / "manifests"
    / "bruciteA_manifest.json"
)

# ── Part 1: Synthetic ingest ──────────────────────────────────────────────────

print("=" * 60)
print("Part 1 — Synthetic ingest (no IPTS mount required)")
print("=" * 60)

with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)

    # Write a synthetic SEE file so assembly_type can be inferred
    see_dir = tmp / "SEE"
    see_dir.mkdir()
    see_file = see_dir / "SEE000042.json"
    see_file.write_text(json.dumps({"type": "assembly.dac", "components": []}))

    # Write a placeholder CIF and EOS file (contents don't matter for this demo)
    cif_path = tmp / "placeholder.cif"
    cif_path.write_text("# placeholder cif\n")
    eos_path = tmp / "placeholder.eos.json"
    eos_path.write_text(
        json.dumps({
            "eos_type": "vinet",
            "V_0": 15.862,
            "K_0": 295.2,
            "K_prime": 4.32,
            "source": "demo",
        })
    )

    manifest = {
        "schema_version": "0.1.0",
        "campaign": {
            "slug": "synthetic-demo",
            "ipts": 1,
            "source_run": 42,
            "description": "Synthetic demo campaign for Phase C+",
        },
        "assets": [
            {
                "asset_id": "cif-placeholder",
                "asset_type": "cif",
                "path": str(cif_path),
                "applicability": {"scope": "campaign"},
                "provenance": {"source": "manual", "created_by": "demo"},
            },
            {
                "asset_id": "eos-placeholder",
                "asset_type": "eos_description",
                "path": str(eos_path),
                "applicability": {"scope": "campaign"},
                "provenance": {"source": "manual", "created_by": "demo"},
            },
        ],
    }
    manifest_path = tmp / "demo_manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    result = bootstrap_campaign_from_manifest(
        manifest_path,
        shared_root=tmp,
        seemeta_dir=see_dir,
    )

    print(f"  Campaign slug : {result['campaign']['campaign_slug']}")
    print(f"  Assembly type : {result['campaign']['assembly_type']}  (inferred from SEEMeta)")
    print(f"  Assets registered : {len(result['assets'])}")

    registered = list_asset_records(
        ipts=1, campaign_identifier="synthetic-demo", shared_root=tmp
    )
    for rec in registered:
        print(f"    • {rec['asset_id']} [{rec['asset_type']}]")

print()

# ── Part 2: Real bruciteA ingest (gated) ────────────────────────────────────

print("=" * 60)
print("Part 2 — Real bruciteA ingest from IPTS-33219")
print("=" * 60)

if not _IPTS_SHARED.exists():
    print("  ⚠  IPTS mount not accessible; skipping Part 2.")
    print(f"     ({_IPTS_SHARED} does not exist)")
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        see_dir = _IPTS_SHARED / "SEE"

        result = bootstrap_campaign_from_manifest(
            _BRUCITE_MANIFEST,
            shared_root=tmp,
            seemeta_dir=see_dir,
        )

        print(f"  Campaign slug : {result['campaign']['campaign_slug']}")
        print(f"  Assembly type : {result['campaign']['assembly_type']}  (from SEE065891.json)")
        print(f"  Assets registered : {len(result['assets'])}")

        registered = list_asset_records(
            ipts=33219, campaign_identifier="brucitea", shared_root=tmp
        )
        for rec in registered:
            print(f"    • {rec['asset_id']} [{rec['asset_type']}]")

        # Load the phase description and show EOS K₀ for each phase
        phase_records = [r for r in registered if r["asset_type"] == "phase_description"]
        if phase_records:
            print()
            print("  Phase description loaded from inspectrum:")
            exp = load_phase_description(phase_records[0]["path"])
            for phase in exp.phases:
                k0 = getattr(phase.eos, "K_0", "n/a") if phase.eos else "n/a"
                print(f"    • {phase.name} [{phase.role}]  K₀ = {k0} GPa")

print()
print("Phase C+ demo complete.")
