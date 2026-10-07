# Manual test: wrap pins the calibration version it validated

Unit tests (`tests/test_pinned_versions.py`) cover wrap's selection logic and the
hand-off type. They **cannot** prove the end-to-end outcome, because the defect
only appears when SNAPRed is given a choice it would resolve differently from
wrap. That needs a calibration home built to contain exactly that disagreement.

## The defect this proves is closed

wrap's cycle filtering decided *whether* a reduction could proceed. SNAPRed
independently decided *which* calibration to use, via
`Indexer.latestApplicableVersion` → `latestApplicableEntry`, which takes the most
recently **written** applicable entry and does not consider cycle at all
(`_isApplicableEntry` checks only `appliesTo`).

So wrap would confirm an in-cycle calibration existed, allow the reduction, and
SNAPRed would then silently use a *different*, out-of-cycle calibration — purely
because that entry carried a later timestamp. Nothing in the output said so.

wrap now sets `ReductionRequest.versions` to the version it validated, rather
than leaving SNAPRed's default of `VersionState.LATEST`.

## Scenario to construct

In one state, for `difcal`, two entries that are **both applicable to the test
run by `appliesTo`**, where the out-of-cycle one is **newer**:

| version | runNumber | cycle of that run | appliesTo | timestamp | role |
|---|---|---|---|---|---|
| `vGOOD` | a run in the **same** cycle as `R` | e.g. 2026-A | covers `R` | **earlier** | what wrap validates |
| `vBAD` | a run in a **different** cycle | e.g. 2025-B | covers `R` | **later** | what SNAPRed would pick |

`R` is the run to reduce. The ordering matters in both dimensions: `vBAD` must be
newer by timestamp *and* its `appliesTo` must cover `R`, or SNAPRed would not have
preferred it and the test proves nothing.

**Prerequisite:** cycle data must be resolvable for each entry's run, since
wrap annotates each index entry with `cycleID` via `snapStateMgr.cycleForRun`.
That comes from SNAPRed's SNAPInstPrm if cycles are registered there, otherwise
from wrap's `cycleDates` fallback. Either is fine — just make sure the two runs
resolve to *different* cycles, or the scenario is inert.

## Test matrix

| # | call | expected calibration used | what it proves |
|---|---|---|---|
| 1 | `reduce(R)` — defaults, `requireSameCycle=True` | **`vGOOD`** | the fix: wrap's choice wins |
| 2 | same scenario, on `next` without this commit | `vBAD` | the defect is real and this is what changed |
| 3 | `reduce(R, requireSameCycle=False)` | `vBAD` | a deliberate override still works, and pins *one* choice rather than letting SNAPRed pick a third |
| 4 | `reduce(R, continueNoDifcal=True)` in a state with **no** difcal | SNAPRed's default (v0) | the fall-through still works — `VersionState.LATEST` is retained |
| 5 | `reduce(R, noNorm=True)` | difcal pinned, normalization not | normalization fall-through is retained |

Case 2 is the important control. Without it, case 1 passing could just mean
SNAPRed happened to agree.

## How to read the result

The output reduction record names the version actually used:

```
/SNS/SNAP/IPTS-<n>/shared/SNAPRed/<stateId>/lite/<run>/<timestamp>/ReductionRecord.json
```

```python
import json
rec = json.load(open(path))
print(rec["calibration"]["version"], rec["normalization"]["version"])
```

wrap also prints the pinned versions as it hands off, which is the quicker check
while iterating:

```
Pinned calibration versions: difcal=<n>, normalization=<n>
```

If that line shows `VersionState.LATEST` for difcal in case 1, wrap did not
validate a calibration and the scenario is not set up as intended — check that
both entries' `appliesTo` cover `R`.

## Expected new failure mode, worth watching for

Pinning turns a disagreement between wrap's and SNAPRed's index reading into a
**hard failure** rather than a silent substitution. Such disagreements are known
to exist — the SNAPWrap/SNAPRed cross-check diverges for runs below the QA floor.

That is an improvement on silently reducing against the wrong calibration, but it
means a reduction that "worked" before may now refuse. If case 1 fails with
SNAPRed unable to find the pinned version, that is this failure mode and not a
bug in the pinning: it means wrap selected a version SNAPRed does not agree
exists or applies. Capture the version wrap pinned and the state it looked in.
