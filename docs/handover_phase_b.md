# Handover: SNAPWrap `reduction_artifacts` branch — Phase B onward

**Date of handover:** 2026-05-12
**Outgoing model:** Claude Sonnet 4.5
**Branch:** `reduction_artifacts`
**Test baseline at handover:** 488 passing (`pixi run pytest -q --no-cov`)
**Last three commits (in order):**

1. `1f2c11e` reduction_artefacts: add assets/requirements modules and locking tests
2. `b5f6923` Vendor mguthriem/inspectrum into snapwrap._inspectrum
3. `f852677` Phase A: harden crystalSpecies.from_cif; standardise on 'artefact' spelling

The repo is at a known-good checkpoint; you (the incoming model) are picking
up at the start of **Phase B**.

---

## Where to start reading

In this order:

1. `docs/crystal_species_refinement_plan.md` — the master plan. Phase A is
   marked done. Phases B, C, D, E are what remain.
2. `docs/inspectrum_absorption_plan.md` — vendoring decision and the
   bucket 1 / 2 / 3 migration scheme for `snapwrap._inspectrum`.
3. `docs/inspectrum_ground_truths.md` — hard-won reference values
   (W EOS, ice-VII EOS, F² symop fix, `cubic_d2Inv` fix, peak-tuning
   constants). **Treat as authoritative** when implementing refinement.
4. `src/snapwrap/sampleMeta/utils.py` — `crystalSpecies` class. Read the
   constructor, `from_cif`, `to_dict`/`from_dict`, and `_cellFromReflections`.
5. `src/snapwrap/_inspectrum/__init__.py` — narrow re-export surface.
   Only import via this `__init__`; do not reach into submodules from
   snapwrap-native code (keeps the bucket-3 deletion easy later).

## Domain conventions you must respect

- **Spelling**: British "artefact" everywhere in our own code/docs/tests.
  Exceptions (deliberately left as "artifact"): hatch's `artifacts = [...]`
  build key in `pyproject.toml:53`, GitHub Actions API names
  (`actions/upload-artifact`), and anything inside
  `src/snapwrap/_inspectrum/` (frozen vendor).
- **`_inspectrum/` is read-only**. Phase B re-exports it; don't edit it.
  When inspectrum modules need to be migrated into `snapwrap.sampleMeta`
  or `snapwrap.spectralTools`, that's a separate, tracked refactor
  (bucket 1 in the absorption plan).
- **`crystalSpecies` is the canonical crystallography artefact**. Do not
  introduce a parallel `crystalBox`-style class. The `CrystalBoxObject`
  placeholder was deleted in commit `f852677`.
- **Tests are the contract**. Run `pixi run pytest -q --no-cov` after
  every meaningful change. Aim for green before handing back to the user.
- **Pixi is the deployment story**, not pip. Use
  `pixi run python ...` and `pixi run pytest ...`. Do not invoke a system
  Python or create a venv.

## What Phase B asks for

From `docs/crystal_species_refinement_plan.md`:

> **Phase B — EOS object inside `snapwrap.sampleMeta`**
>
> - B1. Add `snapwrap.sampleMeta.eos` re-exporting
>   `snapwrap._inspectrum.models.EquationOfState as EOS` plus
>   `snapwrap._inspectrum.eos.predicted_strain` / `pressure_at`.
> - B2. Add `crystalSpecies.eos: EOS | None` attribute, plumbed through
>   `to_dict`/`from_dict`.
> - B3. (Skipped — inspectrum is now vendored.)
> - B4. Failure mode: if EOS is missing, `refine` falls back to a blind
>   strain search (inspectrum's `sweep_strain`).

**Note that B2 is already done** as part of Phase A (the `eos` attribute
exists, validates, and round-trips). What remains for Phase B:

- B1 — the `snapwrap.sampleMeta.eos` re-export module + a small test
  that imports through it.
- B4 — the `crystalSpecies.refine(...)` method (or a free function in
  a new `snapwrap.sampleMeta.refinement` module — pick whichever
  matches the `crystalSpecies` API style; lean toward a method since
  the existing class already owns its fitting state).

`predicted_strain` and `pressure_at` are in
`src/snapwrap/_inspectrum/eos.py`; `sweep_strain` is in the same file
or `engine.py` — search before assuming. The `EquationOfState` data
class is at `src/snapwrap/_inspectrum/models.py:378`.

## Suggested first three steps for the incoming agent

1. Read the five files in "Where to start reading" above. Don't skip
   `inspectrum_ground_truths.md`.
2. `grep -n "predicted_strain\|pressure_at\|sweep_strain" src/snapwrap/_inspectrum/`
   to locate the exact functions; then create
   `src/snapwrap/sampleMeta/eos.py` as the thin re-export.
3. Add `tests/test_sample_meta_eos.py` (Mantid not required for B1) that
   asserts the re-exported symbols are importable and `is`-identical to
   the underlying `_inspectrum` objects. Run the suite. Commit.

Then move on to B4 (`refine` skeleton) with a separate commit.

## ⚠️ Escalation reminder — read this before starting Phase D

Phases B and C are within scope for a Haiku-class model. **Phase D is not.**
It is the actual refinement bridge: strain/pressure parameterisation, a
non-trivial least-squares fit that has to interoperate cleanly with both
`crystalSpecies.unitCell` and the vendored `EquationOfState` machinery,
and it is the step where getting the math wrong silently produces
plausible-looking but incorrect EOS-derived pressures.

**Before you (the incoming agent) write a single line of Phase D code,
explicitly remind the user to switch back to a frontier-class model
(Claude Sonnet 4.5, GPT-5, or equivalent) for the Phase D *design*
pass.** Do this even if the user is mid-flow and clearly wants to keep
going — a short pause here is much cheaper than re-doing a refinement
that quietly disagrees with the inspectrum ground truths by 0.1 GPa.

Suggested wording you can paste verbatim:

> Heads-up before we start Phase D: the handover note from the previous
> agent flags this as the point to escalate back to a frontier model
> for the design pass (least-squares wiring + strain/pressure
> parameterisation). I can keep going at my current capability if you
> prefer, but the recommendation is to do the design pass with a
> stronger model and then drop back down for the implementation. How
> would you like to proceed?

Once the design is locked in (a written sub-plan in
`docs/crystal_species_refinement_plan.md` or a sibling doc), dropping
back to Haiku for the mechanical implementation is fine.

## Operational gotchas observed this session

- The `create_file` tool occasionally produced **interleaved/duplicated
  content** when rewriting a file that had just been deleted. Symptom:
  `wc -l` shows ~3× expected size; `python -c "import ast; ast.parse(...)"`
  fails. Workaround: write the file via a shell heredoc
  (`cat > path <<'PYEOF' ... PYEOF`) and validate with `ast.parse`.
- The vendored inspectrum was copied with `cp -r` and arrived with its
  own `.git/` directory. `git add` flagged it as an embedded repo. We
  removed `src/snapwrap/_inspectrum/.git`, then `git rm --cached -f`
  the stale gitlink, then re-`git add` to track it as plain content.
  If you `cp -r` anything else with a `.git/`, do the same dance.
- `cryspy`'s import chain pulls `scipy.optimize`; cold `pixi run` calls
  can take ~30 s on first invocation. Use `timeout 180` or `300` on
  pixi commands so they don't appear hung.
- `_version.py` is auto-generated by versioningit. **Do not commit it**.
- Branch name is `reduction_artifacts` (American spelling — predates the
  spelling sweep). Don't try to rename the branch.

## Recommended incoming model

For Phases B–E, the work is mostly mechanical re-exports, dataclass
plumbing, and porting an existing fitting routine — the design decisions
are already made. Models I'd recommend, in order of preference:

1. **Claude Sonnet 4.5** (current) — overkill for what's left, but you
   know it's safe.
2. **Claude Haiku 4.5** — best price/performance match for Phase B/C
   work. Big enough context to hold the plan + the inspectrum modules,
   strong at "follow this checklist precisely" tasks. **My recommendation.**
3. **GPT-5 mini** or **Gemini 2.5 Flash** — viable alternatives if
   you're already paying for them; comparable on coding-with-tools
   benchmarks at this scope.

What I would *not* drop down to:
- Anything in the **GPT-4o-mini / Claude-3-Haiku class** — they tend to
  drift on multi-file refactors and miss the "respect the spelling
  convention" / "`_inspectrum/` is read-only" guardrails.
- **Local 7-8B models** — fine for autocomplete, not for the kind of
  cross-file plumbing Phase D will need.

If you (incoming agent) hit Phase D (the actual refinement bridge —
non-trivial least-squares wiring with strain/pressure parameterisation),
**stop and prompt the user to switch back to a frontier model for the
design pass before you write code.** See the "Escalation reminder"
section above for suggested wording. Drop back down to Haiku for the
implementation pass once the design is written down.

---

**Outgoing model's last test result:** 488 passed.
**Working directory at handover:** clean (only `_version.py` floating).
Good luck.
