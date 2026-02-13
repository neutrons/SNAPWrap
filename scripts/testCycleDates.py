"""Workbench test script for cycleDates functionality.

Usage (from the SNAPWrap repo root):
    env=/SNS/SNAP/shared/Malcolm/test/snapwrap/v2.0.0.yml pixi run python -m workbench

Then open this script in the Workbench script editor and run it.

What this script does:
  1. Builds the JSON index from the .ods spreadsheet in the test
     calibration directory.
  2. Prints all known cycles.
  3. Looks up several run numbers and prints their cycle assignments.
"""

from snapwrap.cycleDates import build_cycle_json, load_cycle_data, get_cycle_for_run, clear_cache
from snapwrap.snapStateMgr import cycleForRun

# ── Step 1: Build the JSON index from the .ods ──────────────────────────
print("=" * 60)
print("Building cycle-dates JSON index from .ods spreadsheet …")
print("=" * 60)

records = build_cycle_json()
print(f"\n✓ Indexed {len(records)} cycles.\n")

# ── Step 2: Show all cycles ─────────────────────────────────────────────
print(f"{'cycleID':<12}  {'startDate':<12}  {'stopDate':<12}  {'firstRun':>10}")
print("-" * 52)
for rec in records:
    fr = rec["firstRun"] if rec["firstRun"] is not None else "—"
    print(f"{rec['cycleID']:<12}  {rec['startDate']:<12}  {rec['stopDate']:<12}  {str(fr):>10}")

# ── Step 3: Look up some run numbers ────────────────────────────────────
test_runs = [52862, 55208, 57463, 58842, 61326, 64030, 66539, 99999, 1]

print("\n" + "=" * 60)
print("Run-number → cycle lookups")
print("=" * 60)
for run in test_runs:
    cycle = cycleForRun(run)
    print(f"  run {run:>6}  →  {cycle}")

print("\nDone.")
