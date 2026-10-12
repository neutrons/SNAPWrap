# Calibration backend: scope

Running difcal and normcal from SNAPWrap, without SNAPRed's calibration GUI.
Phase 2 of the Calibration Manager work; ships with the 2.4 release on
`cycleMigration`, against SNAPRed `next`. Written 2026-10-12 from SNAPRed
`next` (`e1f95b52`): `ui/workflow/DiffCalWorkflow.py` and
`NormalizationWorkflow.py`. Decisions by MG, 2026-10-12.

## Principles

1. **Running and publishing are separate acts.** A run produces a *candidate*:
   Mantid workspaces plus an in-memory assessment. Nothing is written to the
   calibration home until a separate, explicit publish.
2. **Publishing is a separate command, run manually and deliberately by an
   instrument scientist.** Automation may run calibrations, never publish them.
3. **Only instrument scientists publish formal calibrations**, and this is
   enforced by write permissions on the calibration home, checked through
   SNAPRed's own `validateWritePermissions`. SNAPRed also lets users run their
   own calibrations into their IPTS; those are separate, not QA-controlled, and
   out of scope here.
4. **Every published calibration is bounded to its cycle.** `appliesTo` is
   computed from the run's cycle (`>=firstRun,<=lastRun`, or `>=firstRun` for
   the open cycle), never typed by hand. This alone prevents a repeat of the
   23 July incident for every new calibration.
5. **Runs inside Workbench, through Calibration Manager.** The candidate keeps
   the inspection workspaces SNAPRed already creates (focused data, fitted
   peaks, residuals) for the IS to look at before publishing.
6. **A new module.** `snapwrap/calibration.py`, not `utils.py`. `utils` may
   re-export the public functions for script convenience.

## How SNAPRed does it now

SNAPRed's GUI already keeps the gate: everything before the final `save` lives
in workspaces and memory.

**Difcal** (`DiffCalWorkflow`), as requests to SNAPRed's backend:

| Step | Requests | GUI interaction |
|---|---|---|
| Specify run | `calibration/validateWritePermissions`, `calibration/groceries`, `calibration/ingredients` | run, lite/native, grouping, calibrant sample, peak function, skip pixel cal, pixel masks |
| Pixel calibration | `calibration/pixel` (unless skipped), `calibration/ingredients` again | — |
| Tweak peaks | `calibration/focus`, `calibration/fitpeaks`, `calibration/residual`; repeated on every change | d-range, peak function, FWHM multipliers, max χ², purge bad peaks, grouping, skip pixel cal; the IS looks at the fits |
| Calibrate | `calibration/group`, then `calibration/assessment` | — |
| Assess | (shows the assessment) | iterate, and choose which iteration to keep |
| Save | `calibration/lock`, `calibration/save` (`CalibrationExportRequest`), lock released | version, appliesTo, comments, author |

**Normcal** (`NormalizationWorkflow`):

| Step | Requests | GUI interaction |
|---|---|---|
| Specify run | `normalization/validateWritePermissions`, `normalization`, `normalization/calculateResidual` | vanadium run, background run, lite/native, grouping, calibrant sample, d-range |
| Tweak | `normalization/smooth` or `normalization` again; `normalization/calculateResidual` | smoothing parameter, d-range, grouping |
| Assess | `normalization/assessment` | — |
| Save | `normalization/lock`, `normalization/save` (`NormalizationExportRequest`), lock released | version, appliesTo, comments, author |

## Proposed SNAPWrap functions

```
runDifcal(runNumber, *, <overrides of the defaults below>)            -> DifcalCandidate
publishDifcal(candidate, *, comment, author)                          -> published version
runNormcal(runNumber, backgroundRun, *, <overrides>)                  -> NormcalCandidate
publishNormcal(candidate, *, comment, author)                         -> published version
```

A candidate carries the assessment (`calculationParameters`, `crystalInfo`,
`pixelGroups`, `focusGroupCalibrationMetrics`, workspaces), the parameters that
produced it, the run's cycle, the names of SNAPRed's inspection workspaces, and
the result of the regression check below. Re-running with different parameters
makes a new candidate; that replaces the GUI's "iterate and pick an
iteration". The `publish*` functions are the separate commands the IS runs.

Propagation of a *published* calibration reuses the existing `propagateDifcal`
machinery, changed to bound each copy to the donor's cycle (Phase 1 idea
"Keep copies inside the donor's cycle"). Finding recipients is a later step.

## Defaults: a `calibration` block in SNAPWrap's `application.yml`

Every input has an entry, so the file documents all of them. Values that are
SNAPRed's own peak-fitting defaults are `null`, meaning "use SNAPRed's value
from its `application.yml`". Copying SNAPRed's numbers here would let the two
drift apart silently when SNAPRed changes a default. Give a value only to
override SNAPRed.

```yaml
calibration:
  difcal:
    focusGroup: Column
    useLiteMode: true
    calibrantSample: Silicon_NIST640d_001.json     # to confirm
    purgeBadPeaks: true
    skipPixelCal: null        # null: SNAPRed's GUI rule, skip in native, not in lite
    peakFunction: null        # SNAPRed: calibration.diffraction.peakFunction (GAUSSIAN)
    crystalDMin: null         # SNAPRed: constants.CrystallographicInfo.crystalDMin (0.4)
    crystalDMax: null         # SNAPRed: constants.CrystallographicInfo.crystalDMax (100.0)
    fwhmMultipliers: null     # SNAPRed: FWHMMultiplier (1.5, 1.5)
    maxChiSq: null            # SNAPRed: constants.GroupDiffractionCalibration.MaxChiSq (10000)
  normcal:
    focusGroup: Column
    useLiteMode: true
    calibrantSample: V-Nb_NonNULL_001.json         # to confirm
    smoothingParameter: null  # SNAPRed: calibration.parameters.default.smoothing
    crystalDMin: null
    crystalDMax: null
  regression:                 # see "Quality check" below; thresholds to be set
    strainAverage: null
    sigmaAverage: null
```

The SNAPRed values in comments are from `next` on 2026-10-12, for reference only.
The calibrant defaults are the ones production's 2026-B records use.

## Every interactive choice, as a parameter

**Difcal**

| GUI choice | Parameter | Default | Note |
|---|---|---|---|
| Lite / native | `useLiteMode` | `true` | |
| Grouping | `focusGroup` | `Column` | |
| Calibrant sample | `calibrantSample` | `Silicon_NIST640d_001.json` (to confirm) | its file may *override* peak function and d-range; those become fixed |
| Peak function | `peakFunction` | SNAPRed's | |
| Crystal d-range | `crystalDMin`, `crystalDMax` | SNAPRed's | |
| FWHM multipliers | `fwhmMultipliers` | SNAPRed's | |
| Max χ² | `maxChiSq` | SNAPRed's | |
| Purge bad peaks | `purgeBadPeaks` | `true`, at SNAPRed's max χ² | if fewer than 2 peaks per group would remain, keep the peaks and warn, as the GUI does |
| Skip pixel calibration | `skipPixelCal` | `not useLiteMode` | GUI rule |
| Pixel masks | `pixelMasks` | none | GUI lists compatible resident masks |
| Convergence, bins across peak | (not exposed) | SNAPRed's | not in the GUI either |
| "Continue anyway" warnings | `continueFlags` | none: stop with the message | GUI prompts the user |
| Looking at the fits | — | SNAPRed's inspection workspaces, kept in Workbench | |
| Version, appliesTo | — | next version; cycle-bounded | never typed by hand |
| Comments, author | `comment`, `author` | required at publish | |

**Normcal**

| GUI choice | Parameter | Default | Note |
|---|---|---|---|
| Vanadium run, background run | `runNumber`, `backgroundRun` | required | |
| Calibrant sample | `calibrantSample` | `V-Nb_NonNULL_001.json` (to confirm) | may override d-range |
| Lite / native, grouping | as difcal | `true`, `Column` | |
| Smoothing | `smoothingParameter` | SNAPRed's | the main tweak in the GUI |
| Crystal d-range | `crystalDMin`, `crystalDMax` | SNAPRed's | |

## Quality check before publishing

SNAPRed's assessment already provides, per pixel group: **strain** mean and
spread (the peak-position offset against the calibrant) and **sigma** mean and
spread (peak width), plus mean 2θ. Example, `12ea3fefa51c79da` v3: 6 groups.
That covers the wireframe's "Si peak offset vs expected" without new SNAPRed
work.

**Regression check against earlier calibrations.** When a candidate is made,
SNAPWrap reads `focusGroupCalibrationMetrics` from the state's earlier
published calibrations, compares the candidate group by group, and warns when a
difference exceeds the thresholds in `calibration.regression`. The warning is
shown with the candidate, before the IS decides to publish; it never blocks.
Still to settle:

- the baseline: the previous published version, or the history of the same
  state (median, or same cycle only)
- the thresholds, once the units of strain are confirmed
- propagated copies carry their donor's metrics, so they are skipped or
  traced back to the donor

## Gaps and SNAPRed dependencies

1. **Normalization picks its difcal cycle-blind.** `NormalizationRequest` has no
   difcal-version field; `NormalizationService` calls
   `getLatestApplicableCalibrationVersion`. In a state where a newer
   out-of-cycle difcal applies (the nine states from the October scan), a new
   normalization would be computed against the wrong cycle's difcal, in
   SNAPRed's own GUI too. Production check 2026-10-12: 0 of 52 normalization
   records are affected, by timing rather than design.
   - **Needed in SNAPRed:** a difcal version on `NormalizationRequest`.
   - **Interim in SNAPWrap:** before running, check that the difcal SNAPRed will
     pick for the vanadium run is from the run's cycle, and refuse otherwise.
2. **"Invalidated" tag on index entries** (from the IS review), so retired
   versions are kept but never picked.
3. **Locks:** use SNAPRed's own `calibration/lock` and `normalization/lock`, as
   the GUI does; two people calibrating one state must not collide.

## Testing

In the snapwrap2.4 CIS harness: its calibration home is disposable and
guarded, and real calibrant runs exist (e.g. Si 72370 and V 72371 for
`12ea3fefa51c79da`). Tests: run a candidate and check nothing was written;
publish and check the new index entry's `appliesTo` is cycle-bounded and the
record matches the candidate; check the regression warning fires on a doctored
baseline; check the normalization guard refuses against a staged out-of-cycle
difcal; check publishing is refused without write permission.

## Still open

1. Confirm the calibrant defaults.
2. The regression baseline and thresholds (above).
