# SNAPWrap structural refactor — plan

**Status:** agreed 2026-08-05 (MG). **Not started, and deliberately not started
yet.** Cycle gating closes out first; the refactor then happens on its own
branch and is field-tested before merge.

This document exists so the conclusions survive between sessions. It records
*why* as much as *what*, because the reasoning is what tends to get lost.

## Origin

The question that prompted it: *does it make sense to have `cycleDates` as a
standalone file in the main folder of the repo?* — asked while adding
stopDate-aware cycle resolution, against a background of SNAPWrap having grown
organically for a long time.

## Answer to the question as asked: `cycleDates.py` is not the problem

594 lines, one coherent job, a clean public API, three importers
(`__init__.py`, `snapStateMgr.py`, `calibrationManager/model.py`), and 41 tests.
It is the **healthiest flat module in the repo**. Moving it for tidiness would
be motion without benefit and would churn a file under active change.

It does eventually move — see the target structure — but for a domain reason,
not a housekeeping one.

## Measured diagnosis

Sizes as of 2026-08-05:

| flat module | lines | | package | lines | files |
|---|---|---|---|---|---|
| `utils.py` | **2328** | | `calibrationManager/` | 2730 | 7 |
| `snapStateMgr.py` | **1936** | | `SEEMeta/` | 1896 | 7 |
| `io.py` | 1023 | | `pixelResolution/` | 848 | 5 |
| `maskUtils.py` | 699 | | `sampleMeta/` | 635 | 3 |
| `cycleDates.py` | 594 | | `spectralTools/` | 255 | 2 |
| `SEEBuilder.py` | 533 | | | | |

`utils` + `snapStateMgr` + `io` is **5287 lines, ~55% of the flat code**, and
carries essentially all of the internal coupling.

**The package-vs-flat split is historical, not principled.** Everything that
attracted interactive or GUI work became a package; the core reduction and state
layer stayed flat and grew. The result is two tiers: a well-factored modern
periphery that keeps growing healthily, and an unrefactored core that everything
calls into and nobody touches because it is daunting.

### The fact that makes this tractable

`reduction_artifacts` is **92 commits and 147 files ahead of `next`**, and it
modifies `utils.py`, `snapStateMgr.py`, `io.py` and `cycleDates.py` **exactly
zero times**. Its only new top-level flat file is `diamondUB.py`. It grew purely
by adding new packages (`reduction_artefacts/`, `campaignManager/`) *alongside*
the core.

So **a core refactor will not conflict with the largest branch in flight.** This
was assumed to be the opposite before it was measured — re-measure rather than
re-assume if the branch landscape changes.

## Target structure

### `snapwrap/cycle/`

`cycleDates` is the **facility schedule**; `snapStateMgr` is **instrument state
and calibration inventory**. Different domains, so `cycleDates` should not be
folded into `snapStateMgr` either. The cycle cut-over adds a third thing with no
home today — gating *policy* — currently smeared between
`cycleDates.resolve_cycle_for_run` and `snapStateMgr.checkCalibrationStatus`.

```
snapwrap/cycle/
    table.py      build_cycle_json, _validate_dataframe, load_cycle_data   (moved)
    resolve.py    get_cycle_for_run, resolve_cycle_for_run, CycleResolution (moved)
    policy.py     NEW — is this calibration usable for this run, and the
                  explicit out-of-cycle override plus its provenance record
```

### `snapwrap/state/`

`snapStateMgr.py`'s 26 top-level functions fall into four groups with almost no
argument, and the file already has test coverage
(`test_calibration_status.py`, `test_snapStateMgr_phase0.py`):

```
snapwrap/state/
    identity.py   SNAPHome, stateDef, detectorConfig, checkStateExists,
                  availableStates, pullStateDict, autoStateName, createState,
                  printCalibrationHome
    status.py     matchingCalibrationIndex, checkCalibrationStatus, isCalibrated,
                  VBRunNumberFromVersion, dateFromLinux, cycleForRun
    validate.py   validateIndex, printValidationReport, fixIndex, _backup_dir,
                  _session_backup_dir, _folder_stat_summary
    records.py    copyDifcal, renameDifcal, loadCalibrationRecord,
                  saveCalibrationRecord, frankenRecord, retrieveReductionRecord
```

### `utils.py` — last

Most callers, least obvious seams, no urgency. Do not start here.

### Compatibility

Keep a shim at `snapwrap/snapStateMgr.py` re-exporting the moved names, so the
many `import snapwrap.snapStateMgr as ssm` call sites keep working. Same for
`snapwrap/cycleDates.py`. Retire the shims only once call sites are migrated,
as a separate change.

## Sequencing and why

1. **Finish cycle gating functionally** — the Q4 explicit out-of-cycle flag
   through `reduce()`, plus provenance recording.
2. **Verify in `/SNS/SNAP/shared/Calibration_scratch/`.**
3. **Then refactor, on its own branch, as pure moves with no behaviour change**,
   and field-test thoroughly before merge.

Refactoring mid-verification means the thing you tested is not the thing you
ship. Keeping "does it work" and "is it tidy" as separate reviewable diffs makes
both easier to review — and the structural diff should be *provably*
behaviour-free, which it cannot be if functional changes ride along with it.
