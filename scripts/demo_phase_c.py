"""
demo_phase_c.py — interactive smoke-test for Phase C work.

Demonstrates the new capabilities WITHOUT needing Mantid or a real CIF file:

  1. AssetType.EOS_DESCRIPTION — the new asset type (C1)
  2. load_eos_description()    — EOS JSON → EquationOfState (C2)
  3. build_crystal_species()   — type signature / import check (C2+C3)
  4. register_crystal_species_artefact() + list_crystal_species_records()
                               — crystal_species_index.jsonl (C4)

Run with:

    pixi run python scripts/demo_phase_c.py

No Mantid, no CIF file, no network access required.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

# ── 1. New AssetType value ────────────────────────────────────────────────────
from snapwrap.reduction_artefacts import AssetType

print("=" * 60)
print("Part 1 — AssetType.EOS_DESCRIPTION (C1)")
print("=" * 60)
print()
print(f"  AssetType.EOS_DESCRIPTION = {AssetType.EOS_DESCRIPTION!r}")
print()
print("  All asset types:")
for at in AssetType:
    print(f"    {at.name:25s} = {at.value!r}")

# ── 2. load_eos_description ───────────────────────────────────────────────────
from snapwrap.reduction_artefacts import load_eos_description
from snapwrap.sampleMeta.eos import predicted_strain

print()
print("=" * 60)
print("Part 2 — load_eos_description (C2)")
print("=" * 60)

with tempfile.TemporaryDirectory() as tmp:
    eos_file = Path(tmp) / "W_vinet.eos.json"
    eos_data = {
        "eos_type": "vinet",
        "V_0": 31.724,    # Å³ per unit cell (BCC W, a=3.165 Å)
        "K_0": 295.2,     # GPa
        "K_prime": 4.32,
        "source": "Dewaele et al., PRB 70 094112 (2004)",
    }
    eos_file.write_text(json.dumps(eos_data, indent=2), encoding="utf-8")
    print(f"\n  Written: {eos_file.name}")
    print(f"  Contents:\n{eos_file.read_text()}")

    eos = load_eos_description(eos_file)
    print(f"\n  Loaded: {eos.eos_type}  V₀={eos.V_0}  K₀={eos.K_0}  K'={eos.K_prime}")
    print(f"  source: {eos.source}")
    print()
    print(f"  Strain at  0 GPa: {predicted_strain(eos,  0.0):.6f}  (expected 1.000000)")
    print(f"  Strain at 10 GPa: {predicted_strain(eos, 10.0):.6f}")
    print(f"  Strain at 50 GPa: {predicted_strain(eos, 50.0):.6f}")

# ── 3. build_crystal_species signature check (no Mantid) ─────────────────────
print()
print("=" * 60)
print("Part 3 — build_crystal_species import check (C2+C3)")
print("=" * 60)

from snapwrap.reduction_artefacts import build_crystal_species
import inspect
sig = inspect.signature(build_crystal_species)
print(f"\n  Signature: build_crystal_species{sig}")
print(f"  Returns:   LoadedAsset[crystalSpecies]")
print(f"  (Mantid required to actually call it — skipping invocation here)")

# ── 4. Campaign round-trip with crystal_species_index.jsonl ──────────────────
from snapwrap.reduction_artefacts import (
    bootstrap_campaign,
    register_asset_record,
    register_crystal_species_artefact,
    list_crystal_species_records,
)

print()
print("=" * 60)
print("Part 4 — crystal_species_index.jsonl round-trip (C4)")
print("=" * 60)

with tempfile.TemporaryDirectory() as tmp:
    # Bootstrap a demo campaign.
    camp = bootstrap_campaign(
        ipts=33219,
        campaign_slug="demo-phase-c",
        assembly_type="DAC",
        description="Phase C demo campaign",
        shared_root=tmp,
    )
    print(f"\n  Campaign bootstrapped: id={camp['campaign_id']}  slug={camp['campaign_slug']}")

    # Register the CIF and EOS assets.
    cif_rec = register_asset_record(
        ipts=33219,
        campaign_identifier="demo-phase-c",
        asset_id="cif-W-01",
        asset_type="cif",
        path="assets/W.cif",
        shared_root=tmp,
    )
    eos_rec = register_asset_record(
        ipts=33219,
        campaign_identifier="demo-phase-c",
        asset_id="eos-W-01",
        asset_type="eos_description",
        path="assets/W_vinet.eos.json",
        shared_root=tmp,
    )
    print(f"  Assets registered: {cif_rec['asset_id']}, {eos_rec['asset_id']}")

    # Simulate a refinement result and register it.
    cs_rec = register_crystal_species_artefact(
        ipts=33219,
        campaign_identifier="demo-phase-c",
        species_name="W",
        cif_path="assets/W.cif",
        role="sample",
        eos_path="assets/W_vinet.eos.json",
        source_run=12345,
        refined_a=3.162,
        refined_b=3.162,
        refined_c=3.162,
        refined_pressure_gpa=10.5,
        unitCell_updated=True,
        cif_asset_id="cif-W-01",
        eos_asset_id="eos-W-01",
        shared_root=tmp,
    )
    print(f"\n  crystalSpecies artefact registered:")
    print(f"    species_name     : {cs_rec['species_name']}")
    print(f"    role             : {cs_rec['role']}")
    print(f"    cifPath          : {cs_rec['cifPath']}")
    print(f"    eosPath          : {cs_rec['eosPath']}")
    print(f"    source_run       : {cs_rec['source_run']}")
    print(f"    refined_a        : {cs_rec['refined_a']} Å")
    print(f"    refinedPressure  : {cs_rec['refinedPressure_GPa']} GPa")
    print(f"    unitCell_updated : {cs_rec['unitCell_updated']}")
    print(f"    cif_asset_id     : {cs_rec['cif_asset_id']}")
    print(f"    eos_asset_id     : {cs_rec['eos_asset_id']}")

    # Read back from the JSONL file.
    records = list_crystal_species_records(
        ipts=33219,
        campaign_identifier="demo-phase-c",
        shared_root=tmp,
    )
    print(f"\n  Read back {len(records)} record(s) from crystal_species_index.jsonl — ✓")

    # Show the raw JSONL line.
    from snapwrap.reduction_artefacts.persistence import _resolve_paths
    paths = _resolve_paths(33219, "demo-phase-c", tmp)
    raw_line = paths.crystal_species_index.read_text().strip()
    parsed = json.loads(raw_line)
    print(f"\n  Raw JSONL record keys: {list(parsed.keys())}")

print()
print("All Phase C demos completed successfully.")
