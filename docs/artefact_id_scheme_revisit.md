# Artefact ID scheme — revisit

**Status:** parked. Revisit after Phase 3 of the Campaign Manager UX.

## Problem

The current artefact id is a single string doing two jobs:

- **What is it?** e.g. `dspacing-mask-diamond`, `binmask-wavelength`, `atten-pe`
- **What run is it scoped to?** appended as `-{run_number}`, e.g. `dspacing-mask-diamond-65891`

This shows up as awkwardness in the Campaign Manager UI:

- The Copy dialog has to *guess-rewrite* the trailing run number when an
  operator copies a mask to a new run (see `dialogs._suggest_new_id`).
- The Artefacts table can't sort or group sensibly by "kind" vs "run".
- Two artefacts of the same kind on the same run can't coexist without
  awkward suffixes (`-v2`, `-copy`, …).
- Operators have to type long structured strings into a free-text field.

## Options to consider

1. **Numeric ids + description.** Drop the structured-string id entirely.
   Assign monotonically increasing integers (per campaign) and add a
   human-readable `description` attribute. UI shows description as the
   primary label; id is plumbing.
2. **Formalised `<kind>-<run>` convention.** Keep the string id but
   model it as a `(kind, run_number)` tuple in code and storage, with
   the flat string derived for display only. UI can then manipulate
   kind and run independently.
3. **Hybrid.** Numeric id + structured tags (kind, run scope) + optional
   human description. Most flexible, most code.

Option 1 is the cleanest fit for the "make it intuitive for end users"
goal; option 2 minimises migration pain on existing on-disk records.

## Why park it

- Touches `bootstrap_campaign`, `register_*` helpers, persistence
  schema, existing on-disk records in production IPTSs, and every test
  that constructs an artefact id.
- We'll learn more about which workflows need ids surfaced (vs. hidden
  behind descriptions) from Phase 3 (Runs + Reduce) and Phase 4 (full
  Setup tab).
- Migration story is non-trivial: existing campaigns already have
  string ids baked into their `artefacts_index.jsonl`.

Revisit once we have more workflow signal.
