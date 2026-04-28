# Calibration Propagation Bug Fix — Implementation Plan

**Date:** 2026-04-27  
**Branch:** `propagateInvestigation`  
**Tracking:** https://github.com/neutrons/SNAPWrap

---

## Background

A recursive propagation condition was identified: a calibration that was itself
produced by `propagateDifcal()` (rather than being measured directly) was
subsequently used as a *donor* in a further propagation call.  The result is a
"copy of a copy" sitting in the calibration index.

### Detection fingerprint

Every propagated calibration has a standardised `comments` entry:

```
(copied from run:<runNumber> version:<N>) original comments: <original>
```

A **double-propagated** entry is detected when `<original>` *also starts with*
`(copied from run:…)`:

```
(copied from run:68979 version:2) original comments: (copied from run:12345 version:1) original comments: ...
```

Detection regex (see `constants.py`):

```python
_DOUBLE_PROP_RE = re.compile(
    r"^\(copied from run:\S+ version:\d+\) original comments: \(copied from run:"
)
```

---

## Confirmed design decisions

| Question | Decision |
|---|---|
| Can a state be simultaneously `CORRUPT` and `DOUBLE_PROPAGATED`? | Yes. `CORRUPT` takes priority in `combine_caltype_statuses()`. `DOUBLE_PROPAGATED` is only shown when the state is otherwise structurally valid. |
| Should double-propagated entries block reduction? | No guard in `isCalibrated()` — fix via Phases 1+2 (detect & remove) and Phase 3 (prevent recurrence). |
| Log file location | `{calibrationHome}/.logs/propagation_log.jsonl` (hidden subdirectory for cleanliness). |
| JSONL log includes linux user? | **Yes** — `"linux_user": getpass.getuser()` is included in every log entry. |

---

## Phase 1 — Detection: Surface Double-Propagations in Calibration Manager

### Status

- [ ] `constants.py` — add `DOUBLE_PROPAGATED` to `CalStatus`, `STATUS_LABEL`, `STATUS_COLOUR`, `STATUS_TOOLTIP`
- [ ] `constants.py` — add `is_double_propagated(comment: str) -> bool` helper and `_DOUBLE_PROP_RE`
- [ ] `model.py` — `getCalibrationDetails()` annotates each entry with `"isDoublePropagated": bool`
- [ ] `model.py` — `getStateSummary()` sets `"hasDoublePropagated": bool` and `"doublePropagatedVersions": list`
- [ ] `model.py` — `combine_caltype_statuses()` / `getStateSummary()` returns `DOUBLE_PROPAGATED` when appropriate
- [ ] `delegates.py` — amber/yellow LED for `DOUBLE_PROPAGATED`
- [ ] `stateOverviewPanel.py` — amber foreground text for `DOUBLE_PROPAGATED` rows
- [ ] `calibrationDetailPanel.py` — highlight double-propagated rows in difcal tab (amber italic); tooltip
- [ ] `tests/test_calibration_overview.py` — unit tests for `is_double_propagated()` and `getStateSummary()`

### Key detail

`DOUBLE_PROPAGATED` sits *below* `CORRUPT` in precedence.  `combine_caltype_statuses()`
is extended to accept a `hasDoublePropagated` flag and returns `DOUBLE_PROPAGATED` only
when neither `CORRUPT` nor `CORRUPT_INDEX` applies.

---

## Phase 2 — Repair: Delete Double-Propagated Entries

### Status

- [ ] `model.py` — add `findDoublePropagatedVersions(stateID, isLite) -> List[int]`
- [ ] `model.py` — add `removeDoublePropagatedEntries(stateID, isLite, dryRun=True) -> dict`
- [ ] `mainWindow.py` — extend `_onRepairRequested()` to handle `DOUBLE_PROPAGATED` case with confirmation dialog
- [ ] `stateOverviewPanel.py` — show "Remove Double-Propagations" button for `DOUBLE_PROPAGATED` states
- [ ] `tests/test_calibration_overview.py` — unit tests for `removeDoublePropagatedEntries()` (dry-run + live, mock filesystem)

### Repair flow

1. User clicks **"Remove Double-Propagations"** in the state overview panel
2. `mainWindow` calls `model.removeDoublePropagatedEntries(..., dryRun=True)` → gets list of versions
3. Confirmation dialog: `"Versions {N, M, …} will be permanently deleted. This cannot be undone. Proceed?"`
4. On confirm: call live mode; refresh the state row

### Behaviour

- Each deleted version follows the existing `deleteCalibrationVersion()` path (backup → remove folder → rewrite index → `fixIndex`)
- `_INDEX_KEYS` stripping already in place to prevent `cycleID` annotation leaking back to disk

---

## Phase 3 — Prevention: Guard `propagateDifcal()` Against Propagated Donors

### Status

- [x] `utils.py` — add `_is_propagated_entry(entry: dict) -> bool`
- [x] `utils.py` — guard in `propagateDifcal()`: reject if latest valid difcal entry is a propagation
- [x] `tests/test_propagation.py` (new) — unit tests for guard (mock `checkCalibrationStatus` returning propagated entry)

### Guard logic

```python
def _is_propagated_entry(entry: dict) -> bool:
    """Return True if this index entry was produced by propagateDifcal()."""
    return bool(re.match(r"^\(copied from run:", entry.get("comments", "")))
```

Inserted immediately after the existing donor calibration validity check.
Uses `mantid.kernel.Logger("snapwrap").error(...)` for the error message
(visible at Notice level in Workbench).

### Error message format

```
propagateDifcal — donor run {donorRunNumber} (state {donorStateID})
has a propagated calibration as its latest valid entry
(version {N}, comment: "...").
Propagating a propagated calibration is not permitted.
Use the original measured calibration donor run instead.
```

---

## Phase 4 — Audit Trail: Propagation Log

### Status

- [x] `utils.py` — add `_write_propagation_log(entry: dict)`
- [x] `utils.py` — call `_write_propagation_log()` in `propagateDifcal()` at each outcome
- [x] `tests/test_propagation.py` — test log file creation/append and entry schema
- [ ] `mainWindow.py` — stretch goal: "View Propagation Log" button opening a `QDialog`

### Log file

```
{calibrationHome}/.logs/propagation_log.jsonl
```

Directory is created automatically on first write.  The `.logs` prefix keeps it
hidden from casual filesystem browsing.

### JSONL entry schema

```json
{
  "timestamp":               "2026-04-27T14:32:00",
  "linux_user":              "mal",
  "donorRunNumber":          "68979",
  "donorStateID":            "12ea3abc...",
  "donorVersion":            2,
  "donorCycleID":            "2026-A",
  "recipientStateID":        "06977e...",
  "recipientPreviousVersions": 1,
  "newVersion":              2,
  "outcome":                 "success",
  "dryRun":                  false,
  "error":                   null
}
```

`outcome` values:

| Value | Meaning |
|---|---|
| `"success"` | Calibration successfully propagated to recipient state |
| `"skipped_donor_is_propagated"` | Phase 3 guard blocked propagation |
| `"skipped_no_donor_calibration"` | Donor state has no valid difcal |
| `"dry_run"` | `propagate=False` — only reporting, no file changes |
| `"error"` | Unexpected exception during propagation |

### Stretch goal: log viewer

A **"View Propagation Log"** button in `mainWindow.py` that opens a read-only
`QDialog` with a reverse-chronological table of log entries.  Deferred until
Phases 1–3 are deployed and the damage has been assessed.

---

## Phase 5 — UX Migration: Propagation Workflow in Calibration Manager

### Goal

Move propagation from ad-hoc script usage into a guided UI flow so users can:

1. preview exactly which donor calibration/version will be used,
2. inspect recipient impact before writing,
3. confirm execution explicitly,
4. immediately validate outcomes in the same UI.

### Status

- [ ] `model.py` — add `previewPropagation(donorRunNumber, isLite, includeGuideStatus=False) -> dict`
- [ ] `model.py` — add `executePropagation(donorRunNumber, isLite, includeGuideStatus=False) -> dict`
- [ ] `mainWindow.py` — add "Propagate…" action/button launching a propagation dialog
- [ ] `mainWindow.py` — wire preview → confirm → execute flow with refresh of affected state rows
- [ ] `stateOverviewPanel.py` — optional donor-run quick action (populate run field + open dialog)
- [ ] `calibrationDetailPanel.py` — optional auto-select recipient state after success
- [ ] `tests/test_calibration_overview.py` — unit tests for preview/execute model wrappers (mock ssm/utils)
- [ ] `tests/test_propagation.py` — add UI-facing contract tests for expected preview payload keys

### Proposed interaction flow

1. User clicks **Propagate…**
2. Dialog asks for donor run number (and lite/native toggle)
3. User clicks **Preview** (always dry-run)
4. UI shows:
     - donor state, donor selected version, donor comments,
     - recipient states and current/latest versions,
     - block reason if donor is propagated or donor has no valid difcal
5. User clicks **Confirm Propagation**
6. UI runs execute path (`propagate=True`) and then refreshes tables/details
7. Success panel shows summary and latest log entries (Phase 4 JSONL)

### Preview payload contract (draft)

```json
{
    "ok": true,
    "donorRunNumber": "68926",
    "donorStateID": "7a68989468eb04f0",
    "selectedDonorVersion": 3,
    "selectedDonorCycleID": "2026-A",
    "selectedDonorComment": "(copied from run:68922 version:1)...",
    "blocked": true,
    "blockReason": "donor_is_propagated",
    "recipients": [
        {
            "stateID": "...",
            "recipientPreviousVersions": 1,
            "newVersion": 2
        }
    ]
}
```

### Error/confirm UX requirements

- **Hard stop** when `blocked=true`; execute button disabled.
- Confirmation text must include donor run/state/version and number of recipients.
- Post-run summary must include success count / failure count and log-file location:
    `{calibrationHome}/.logs/propagation_log.jsonl`.

### Non-goals (Phase 5)

- No multi-donor batch propagation.
- No editable version override (still derived from run-number validity logic).
- No historical rollback UI (existing backup/fixIndex tooling remains backend-only).

---

## File Inventory

| File | Phases |
|---|---|
| `src/snapwrap/calibrationManager/constants.py` | 1 |
| `src/snapwrap/calibrationManager/model.py` | 1, 2 |
| `src/snapwrap/calibrationManager/delegates.py` | 1 |
| `src/snapwrap/calibrationManager/stateOverviewPanel.py` | 1, 2 |
| `src/snapwrap/calibrationManager/calibrationDetailPanel.py` | 1 |
| `src/snapwrap/calibrationManager/mainWindow.py` | 2, 5 |
| `src/snapwrap/utils.py` | 3, 4 |
| `tests/test_calibration_overview.py` | 1, 2, 5 |
| `tests/test_propagation.py` *(new)* | 3, 4 |
| `docs/propagation_fix_plan.md` *(this file)* | — |

---

## Dependency graph

```
Phase 1 (Detection)
    └── Phase 2 (Repair) — depends on Phase 1 status model
Phase 3 (Prevention) — logically independent; deploy after Phase 2 cleanup
Phase 4 (Audit Trail) — independent; can be done in parallel with Phase 3
Phase 5 (UI propagation workflow) — depends on Phase 3 guard + Phase 4 logging
```

Recommended deployment order: **1 → 2 → (clean the damage) → 3 → 4 → 5**
