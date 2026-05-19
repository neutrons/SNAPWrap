# Handover — Campaign Manager UX (Phase 2 complete)

**Date:** 2026-05-19
**Branch:** `reduction_artifacts`
**Repo:** `neutrons/SNAPWrap`
**Workspace:** `/gpfs/neutronsfs/instruments/SNAP/shared/Malcolm/code/forks/SNAPWrap`
**Test status:** 660 passed, 2 skipped
**Last commit:** `e42a5b0`

You (the next Claude agent) are picking up an in-flight UX project. The
operator is a beamline scientist working in a small cabin during live
SNAP experiments, running everything through a local Mantid Workbench
instance. Everything below is real — there are no mocks.

---

## 1. Where we are

### Done

| Commit | What |
|---|---|
| `3e6b3cd` | Wired `monitor2_l2` L2 calibration override end-to-end (masking → campaign_setup → operator script) |
| `b2de76d` | Phase 0 scaffold + Phase 1 read-only Artefacts tab |
| `275ed90` | Permission-aware IPTS discovery (`_is_readable_dir` swallows PermissionError/OSError) |
| `4481cea` | Editable IPTS picker with QCompleter substring matching + Go button (200 IPTSs unscrollable in plain combo) |
| `782f412` | Phase 2 — Artefacts mutations: retire / copy / show-file-location / copy-id via right-click context menu |
| `1d0833d` | `scripts/launch_campaign_manager.py` — Workbench reload-and-launch helper |
| `e42a5b0` | Reframed Copy dialog around run-migration workflow |

### Pending — awaiting user decision

The user just confirmed the new Copy dialog is "much better" and asked
for handover. The **next decision point** is:

- **Phase 2.5** — "+ New campaign" mini-dialog (slug regex-validated,
  assembly_type combo DAC/PE/OTHER, description textarea, owners) →
  calls `bootstrap_campaign(...)`. Add "+ New…" button next to the
  campaign combo. ~1 hour.
- **Phase 3** — Runs panel + Reduce panel + live log streaming
  (QPlainTextEdit fed by signal from a `reduceSEE` worker). 2–3 days.
- **Phase 4** — Full Setup tab (assets table, manual bin-masks).

Recommendation already given to the user: do Phase 2.5 first (small,
immediately useful, gives Phase 4 a natural growth point), then Phase 3.
Ask the user to confirm before starting.

---

## 2. Non-negotiable constraints (learned the hard way)

1. **Must be Workbench-embedded.** No standalone PyQt app. Operators
   live in Workbench; pulling them out kills adoption.
2. **JSON spec is the single source of truth.** The
   `campaign_setup_spec.json` is canonical; the UI writes JSON; the
   operator script becomes an optional export. Do not invert this.
3. **Threading discipline is non-negotiable.** Every backend call goes
   through `workers.GenericWorker` (QObject moved to QThread, emits
   `finished(object)` / `error(str)`). The user explicitly cited this
   as a lesson from `calibrationManager`. Never block the GUI thread.
4. **Single-user assumption.** Per-instrument analysis node, one user
   at a time, files on shared `/SNS/SNAP/IPTS-<n>/shared` paths.
5. **No mocks in tests for backend logic.** The repo uses real `tmp_path`
   IPTS bootstraps. Look at `tests/conftest.py` and
   `tests/test_campaignManager_model.py` for the pattern.

---

## 3. Code layout

```
src/snapwrap/campaignManager/
├── __init__.py          # show() entry, QAppThreadCall marshalling,
│                        # module-level _active_dialog (anti-GC)
├── mainWindow.py        # CampaignManager(QDialog) — context bar, tabs,
│                        # status bar, _runMutation generic dispatcher
├── model.py             # Qt-free CampaignManagerModel (static methods
│                        # wrapping reduction_artefacts backend)
├── constants.py         # ArtefactStatus enum, ARTEFACT_COLUMNS, lookup()
├── delegates.py         # StatusPillDelegate (rounded coloured pill)
├── workers.py           # GenericWorker (fn + kwargs → finished/error)
├── dialogs.py           # CopyArtefactDialog (+ _suggest_new_id helper)
└── panels/
    └── artefactsPanel.py  # ArtefactTableModel + ArtefactsPanel
                            # (filters, refresh, context menu)
```

Backend the UI calls into:

```
src/snapwrap/reduction_artefacts/
├── __init__.py          # public API (exports list_campaigns, etc.)
└── persistence.py       # the meat — bootstrap_campaign, register_*,
                         #   list_artefact_records, retire_artefact,
                         #   copy_artefact, list_campaigns, ...
```

---

## 4. Workflow & dev loop

### Running the suite

```bash
pixi run pytest --no-cov -q                       # full suite (~15s)
pixi run pytest tests/test_campaignManager_model.py --no-cov -q
```

### Iterating on the UI without restarting Workbench

The operator opens `scripts/launch_campaign_manager.py` in Workbench's
script editor and re-runs it. It reloads every submodule in dependency
order (leaves → mainWindow → package). **Every time you add a new
submodule under `campaignManager/`, add a line to that file in the same
commit.** The user previously hit a stale-import bug because `mainWindow`
imported an old `ArtefactsPanel`; they don't want to debug that again.

### Convention

- **`get_errors` after every edit** before running tests.
- **Commit per logical step** with detailed multi-line messages (mirror
  the style of recent commits — they're verbose by design, the user
  reviews them).
- **Don't print code blocks** unless the user explicitly asks; use edit
  tools.
- The user values **honest pushback**. If a request is misframed (the
  Copy dialog UX was an example), say so and propose better.

---

## 5. Open design notes parked in docs

- `docs/artefact_id_scheme_revisit.md` — the artefact id is doing double
  duty as `kind + run_number`. Three options on the table (numeric+desc,
  formalised tuple, hybrid). **Park until after Phase 3** — touches
  persistence schema and existing on-disk records.
- `docs/handover_phase_*.md` — older handovers from previous phases.
  Useful context but don't conflict with this one.

---

## 6. Reading order to get oriented (~30 min)

1. `src/snapwrap/campaignManager/__init__.py` — see how `show()` works
   in/out of GUI thread.
2. `src/snapwrap/campaignManager/mainWindow.py` — read `_buildUi`,
   `_loadIPTSCampaigns`, `_runMutation`. This is the architectural
   template — copy its patterns for new panels.
3. `src/snapwrap/campaignManager/panels/artefactsPanel.py` — pattern
   for a panel: own `QAbstractTableModel`, expose signals, no direct
   backend calls.
4. `src/snapwrap/campaignManager/model.py` — Qt-free wrapper layer.
5. `src/snapwrap/reduction_artefacts/persistence.py` — start with
   `bootstrap_campaign`, `register_swiss_cheese_artefact`,
   `copy_artefact`, `retire_artefact`, `list_artefact_records`,
   `list_campaigns`.
6. `tests/test_campaignManager_model.py` + `tests/conftest.py` —
   testing pattern (real bootstrapped IPTSs in `tmp_path`).
7. This file's commit history: `git log --oneline -- src/snapwrap/campaignManager/`.

---

## 7. First message to send the user

Something like:

> I've read the handover. Quick sanity check before I start:
>
> - Last commit: `e42a5b0` (Copy dialog rework). Test suite at 660 passing.
> - Pending decision: **Phase 2.5 (+ New campaign dialog, ~1h)** or
>   **Phase 3 (Runs + Reduce + live log, 2–3d)**. Previous me
>   recommended 2.5 first. Still your call?
> - Any new constraints I should know about?

Don't start coding until they confirm.

---

## 8. Things that bit us — read this twice

- **`importlib.reload` is brittle across Qt classes.** Even with the
  launcher script, recommend Workbench restart for any cross-module
  refactor. Per-file edits are usually fine.
- **`os.access(path, R_OK|X_OK)` can still raise `PermissionError`** on
  some filesystem paths. Always wrap discovery iteration in try/except
  per child, not just at the root.
- **`QLineEdit.setText()` does NOT fire `textEdited`** (only
  `textChanged`). The Copy dialog's "operator started editing the id"
  detection relies on this — don't switch the signal.
- **`reduce_see` calls leak Mantid INFO logs into Workbench.** Already
  silenced in `__init__.py` for `snapred.backend.recipe.algorithm.MantidSnapper`.
  If new noisy loggers appear, add them there.

---

## 9. Contact

If anything is unclear, the user (Malcolm) will tell you. He prefers
honest pushback over polite agreement. Good luck.
