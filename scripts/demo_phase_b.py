"""
demo_phase_b.py — interactive smoke-test for Phase B work.

Demonstrates the two new capabilities WITHOUT needing Mantid or a CIF file:

  1. snapwrap.sampleMeta.eos  — the EOS re-export facade (B1)
  2. crystalSpecies.refine()  — the strain-refinement skeleton (B4)

Run with:

    pixi run python scripts/demo_phase_b.py

No Mantid, no CIF file, no network access required.
"""

from __future__ import annotations

# ── 1. EOS facade ────────────────────────────────────────────────────────────
from snapwrap.sampleMeta.eos import (
    EquationOfState,
    pressure_at,
    predicted_strain,
    volume_ratio,
    sweep_strain,
)

print("=" * 60)
print("Part 1 — snapwrap.sampleMeta.eos (B1)")
print("=" * 60)

# Tungsten Vinet EOS (well-known high-pressure standard)
# Field names match the inspectrum dataclass: V_0, K_0, K_prime, eos_type, source.
W_eos = EquationOfState(
    eos_type="vinet",
    V_0=15.855,     # Å³ per unit cell
    K_0=310.0,      # GPa  (bulk modulus)
    K_prime=4.0,    # dimensionless (pressure derivative)
    source="demo",
)

print(f"\nEOS: {W_eos.eos_type}  source={W_eos.source}")
print(f"  V₀ = {W_eos.V_0:.3f} Å³,  K₀ = {W_eos.K_0:.1f} GPa,  K' = {W_eos.K_prime:.1f}")

pressures = [0, 10, 30, 50, 100]
print(f"\n  {'P (GPa)':>10}  {'V/V0':>8}  {'lin. strain':>12}  {'P back-calc (GPa)':>18}")
print("  " + "-" * 52)
for P in pressures:
    s   = predicted_strain(W_eos, P)   # linear strain = (V/V0)^(1/3)
    vr  = volume_ratio(W_eos, P)
    P_back = pressure_at(W_eos, vr * W_eos.V_0)
    print(f"  {P:>10.1f}  {vr:>8.5f}  {s:>12.6f}  {P_back:>18.3f}")

# ── 2. crystalSpecies.refine() skeleton ──────────────────────────────────────
print()
print("=" * 60)
print("Part 2 — crystalSpecies.refine() skeleton (B4)")
print("=" * 60)

import numpy as np

# Build a minimal crystalSpecies by hand — no Mantid / CIF needed.
# We just populate the attributes that refine() uses.
from snapwrap.sampleMeta.utils import crystalSpecies, unitCell

# Iron (BCC) unit cell, a₀ = 2.87 Å — a simple cubic example.
a0 = 2.87  # Å
species = crystalSpecies.__new__(crystalSpecies)
species.name          = "demo_iron_bcc"
species.crystalSystem = "cubic"
species.eos           = None         # no EOS yet → will use blind_sweep
species.valid         = {"unitCell": True}
species.observedReflections = []
species.dLimits       = None

cell = unitCell("cubic")
cell.a = cell.b = cell.c = a0
cell.alpha = cell.beta = cell.gamma = 90.0
species.unitCell = cell

print(f"\nSeed unit cell: a₀ = {a0:.4f} Å  (Iron BCC, approx.)")

# Simulate an observation at strain = 0.98
# (i.e. the sample is slightly compressed).
TRUE_STRAIN = 0.98
a_true = a0 * TRUE_STRAIN
print(f"Simulated true strain: {TRUE_STRAIN}  →  a_true = {a_true:.4f} Å")

# Generate "observed" d-spacings from the compressed cell and add a little noise.
rng = np.random.default_rng(42)
obs_d = []
for h in range(1, 5):
    for k in range(0, h + 1):
        for l in range(0, k + 1):
            hkl2 = h*h + k*k + l*l
            d = a_true / np.sqrt(hkl2)
            if 0.8 < d < 3.5:
                obs_d.append(d + rng.normal(0, 0.002))   # ±0.002 Å noise

obs_d = np.array(obs_d)
print(f"Observed d-spacings: {len(obs_d)} reflections, "
      f"range [{obs_d.min():.3f}, {obs_d.max():.3f}] Å")

# --- Path A: blind sweep (no EOS) ---
print("\n--- Blind sweep (no EOS) ---")
result = species.refine(obs_d)
print(f"  path           : {result['path']}")
print(f"  strain found   : {result['strain']:.6f}  (true = {TRUE_STRAIN:.6f})")
print(f"  a_refined      : {species.unitCell.a:.5f} Å  (true = {a_true:.5f} Å)")
print(f"  message        : {result['message']}")

# --- Path B: EOS-guided ---
# Reset the cell back to a0 and attach a fake EOS.
cell.a = cell.b = cell.c = a0
species.eos = W_eos   # pretend iron has W's EOS for this demo
P_demo = 10.0  # GPa

print(f"\n--- EOS-guided (P = {P_demo} GPa) ---")
result2 = species.refine(obs_d, pressure_gpa=P_demo)
print(f"  path           : {result2['path']}")
print(f"  strain found   : {result2['strain']:.6f}")
print(f"  a_refined      : {species.unitCell.a:.5f} Å")
print(f"  EOS prior      : {predicted_strain(W_eos, P_demo):.6f}")
print(f"  message        : {result2['message']}")

# --- Edge case: unsupported crystal system ---
print("\n--- Non-cubic (should raise NotImplementedError) ---")
species_hex = crystalSpecies.__new__(crystalSpecies)
species_hex.crystalSystem = "hexagonal"
species_hex.eos = None
species_hex.valid = {"unitCell": True}
species_hex.unitCell = cell
try:
    species_hex.refine(obs_d)
except NotImplementedError as e:
    print(f"  NotImplementedError raised as expected:")
    print(f"    {e}")

print("\nAll demos completed successfully.")
