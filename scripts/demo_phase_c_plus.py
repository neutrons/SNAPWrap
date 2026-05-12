"""Phase C+ end-to-end demo: campaign manifest v0.2.0 ingest + SEEMeta inference.

Demonstrates the living-manifest model:
  - candidate_species (CIF + inline EOS, no separate phases file)
  - ruby pressure annotation
  - post-analysis observed_species annotation
  - add_candidate_species mid-campaign

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
    add_candidate_species,
    annotate_run,
    bootstrap_campaign_from_manifest,
    list_asset_records,
)

_IPTS_SHARED = Path("/SNS/SNAP/IPTS-33219/shared")
_BRUCITE_MANIFEST = (
    _IPTS_SHARED
    / "snapwrap" / "reduction_artefacts" / "manifests" / "bruciteA_manifest.json"
)

# ── Part 1: Synthetic ingest ──────────────────────────────────────────────────

print("=" * 60)
print("Part 1 — Synthetic ingest (no IPTS mount required)")
print("=" * 60)

with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)

    # Synthetic SEE file for assembly_type inference
    see_dir = tmp / "SEE"
    see_dir.mkdir()
    (see_dir / "SEE000042.json").write_text(
        json.dumps({"type": "assembly.dac", "components": []})
    )

    manifest = {
        "schema_version": "0.2.0",
        "campaign": {
            "slug": "synthetic-demo",
            "ipts": 1,
            "source_run": 42,
            "description": "Synthetic demo campaign",
            "owners": ["demo"],
        },
        "candidate_species": [
            {
                "species_id": "tungsten",
                "role": "calibrant",
                "cif": "/data/W.cif",
                "eos": {
                    "type": "vinet", "V_0": 15.862, "K_0": 295.2, "K_prime": 4.32,
                    "source": "Dewaele 2004",
                },
                "stability_pressure": [None, None],
                "artefact_path": None,
            },
        ],
        "runs": [
            {"run_number": 1001, "ruby_pressure_gpa": None, "observed_species": None},
            {"run_number": 1002, "ruby_pressure_gpa": None, "observed_species": None},
        ],
    }
    mf = tmp / "manifest.json"
    mf.write_text(json.dumps(manifest))

    result = bootstrap_campaign_from_manifest(mf, shared_root=tmp, seemeta_dir=see_dir)

    print(f"  Campaign slug : {result['campaign']['campaign_slug']}")
    print(f"  Assembly type : {result['campaign']['assembly_type']}  (inferred from SEEMeta)")
    print(f"  Candidate species : {[s['species_id'] for s in result['candidate_species']]}")

    assets = list_asset_records(ipts=1, campaign_identifier="synthetic-demo", shared_root=tmp)
    print(f"  Assets registered : {len(assets)}")
    for a in assets:
        print(f"    • {a['asset_id']} [{a['asset_type']}]")

    # Simulate operator recording ruby pressure before run 1001
    annotate_run(ipts=1, campaign_identifier="synthetic-demo", run_number=1001,
                 shared_root=tmp, ruby_before_gpa=3.10)
    print("\n  After neutron collection (run 1001):")
    annotate_run(ipts=1, campaign_identifier="synthetic-demo", run_number=1001,
                 shared_root=tmp, ruby_after_gpa=3.14, ruby_nominal_gpa=3.10)

    # Simulate analysis writing back observed species
    annotate_run(
        ipts=1, campaign_identifier="synthetic-demo", run_number=1001,
        shared_root=tmp,
        observed_species=[{
            "species_id": "tungsten",
            "lattice_params": {"a": 3.138},
            "pressure_gpa": 3.24,
        }],
    )

    # Read living manifest back and show run state
    living = json.loads(
        (tmp / "snapwrap" / "reduction_artefacts" / "campaigns"
         / "synthetic-demo" / "manifest.json").read_text()
    )
    run = living["runs"][0]
    ruby = run["ruby_pressure_gpa"]
    print(f"  run 1001 ruby: before={ruby['before']} after={ruby['after']} "
          f"nominal={ruby['nominal']}")
    obs = run["observed_species"][0]
    print(f"  run 1001 observed: {obs['species_id']} a={obs['lattice_params']['a']} "
          f"P={obs['pressure_gpa']} GPa")

    # Mid-campaign: unexpected phase discovered — add it
    add_candidate_species(
        ipts=1, campaign_identifier="synthetic-demo",
        species_def={
            "species_id": "unexpected-phase",
            "role": "sample",
            "cif": "/data/unexpected.cif",
            "eos": None,
            "stability_pressure": [5.0, None],
        },
        shared_root=tmp,
    )
    living2 = json.loads(
        (tmp / "snapwrap" / "reduction_artefacts" / "campaigns"
         / "synthetic-demo" / "manifest.json").read_text()
    )
    print(f"\n  Candidate species after mid-campaign add: "
          f"{[s['species_id'] for s in living2['candidate_species']]}")

print()

# ── Part 2: Real bruciteA ingest (gated) ─────────────────────────────────────

print("=" * 60)
print("Part 2 — Real bruciteA ingest from IPTS-33219")
print("=" * 60)

if not _IPTS_SHARED.exists():
    print(f"  ⚠  IPTS mount not accessible; skipping Part 2.\n     ({_IPTS_SHARED})")
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        see_dir = _IPTS_SHARED / "SEE"

        result = bootstrap_campaign_from_manifest(
            _BRUCITE_MANIFEST, shared_root=tmp, seemeta_dir=see_dir,
        )

        print(f"  Campaign slug   : {result['campaign']['campaign_slug']}")
        print(f"  Assembly type   : {result['campaign']['assembly_type']}"
              f"  (from SEE065891.json)")
        print(f"  Candidate species:")
        for s in result["candidate_species"]:
            eos = s.get("cif_asset", {})
            print(f"    • {s['species_id']} [{s['role']}]")

        assets = list_asset_records(ipts=33219, campaign_identifier="brucitea",
                                    shared_root=tmp)
        print(f"  Assets in index : {len(assets)}")
        for a in assets:
            print(f"    • {a['asset_id']} [{a['asset_type']}]")

        # Show manifest runs
        living = json.loads(
            (tmp / "snapwrap" / "reduction_artefacts" / "campaigns"
             / "brucitea" / "manifest.json").read_text()
        )
        print(f"  Runs declared   : {[r['run_number'] for r in living['runs']]}")
        print(f"  (all ruby/observed fields are null — ready for real data)")

print()
print("Phase C+ demo complete.")
