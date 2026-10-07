"""Data-layer for the Calibration Manager UI.

This module is a *thin aggregation layer* over the existing functions in
:mod:`snapwrap.snapStateMgr` and :mod:`snapwrap.cycleDates`.  It adds no
duplicated business logic — it calls through to the existing backend and
reshapes the output into simple data structures that are easy for
``QAbstractTableModel`` to consume.

The only genuinely *new* business logic here is
:meth:`CalibrationManagerModel.invalidateCalibrationVersion`, which does
not have a pre-existing counterpart in ``snapStateMgr``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import snapwrap.snapStateMgr as ssm
from snapwrap.cycleDates import load_cycle_data
from snapwrap.calibrationManager.constants import (
    CalStatus,
    CalTypeStatus,
    caltype_status_for_cycle,
    caltype_status_from_detail,
    combine_caltype_statuses,
    is_double_propagated,
)


# ── PV key → short name mapping (mirrors autoStateName) ─────────────────
_PV_SHORT = {
    "det_arc1": "arc1",
    "det_arc2": "arc2",
    "BL3:Chop:Skf1:WavelengthUserReq": "wav",
    "BL3:Det:TH:BL:Frequency": "freq",
    "BL3:Mot:OpticsPos:Pos": "pos",
    "BL3:Mot:OpticsPos:ExitSlit": "slit",
    # legacy names
    "vdet_arc1": "arc1",
    "vdet_arc2": "arc2",
    "WavelengthUserReq": "wav",
    "Frequency": "freq",
    "Pos": "pos",
    "slit": "slit",
}

# Regex to extract the effective donor run from a propagation comment
_PROPAGATION_RE = re.compile(r"\(copied from run:(\S+)\s+version:")


class CalibrationManagerModel:
    """Pure-Python data model for the Calibration Manager.

    Designed to be usable *without* Qt so it can be tested independently.
    """

    # ── Cycle helpers ────────────────────────────────────────────────

    @staticmethod
    def getCycleList() -> List[str]:
        """Return a list of cycle IDs, most recent first.

        Uses :func:`cycleDates.load_cycle_data` which caches after first
        call.
        """
        cycles = load_cycle_data()
        # load_cycle_data returns records sorted by firstRun ascending
        return [c["cycleID"] for c in reversed(cycles)]

    @staticmethod
    def cycleForRun(runNumber) -> Optional[str]:
        """Convenience wrapper around ``ssm.cycleForRun``."""
        return ssm.cycleForRun(runNumber)

    # ── Run → state resolution ───────────────────────────────────────

    @staticmethod
    def stateForRun(runNumber) -> Dict[str, Any]:
        """Resolve a run number to its stateID and cycleID.

        Returns
        -------
        dict
            ``stateID``, ``cycleID``, and the full ``stateDict``.
        """
        stateID, stateDict = ssm.stateDef(runNumber)
        return {
            "stateID": stateID,
            "stateDict": stateDict,
            "cycleID": ssm.cycleForRun(runNumber),
        }

    # ── State-level queries ──────────────────────────────────────────

    @staticmethod
    def _parseStateParams(stateDict: dict) -> dict:
        """Extract short-name parameters from a ``pullStateDict`` result.

        Returns a flat dict with keys ``arc1``, ``arc2``, ``wav``, ``freq``,
        ``pos``, ``slit`` (any missing key is ``None``).
        """
        params: Dict[str, Any] = {
            "arc1": None, "arc2": None, "wav": None,
            "freq": None, "pos": None, "slit": None,
        }
        for pvKey, value in stateDict.items():
            short = _PV_SHORT.get(pvKey)
            if short:
                params[short] = value
        return params

    @staticmethod
    def _bestCycleFromIndex(calibIndexList: List[dict]) -> str:
        """Determine the most recent cycle represented in an index list.

        Accounts for propagated calibrations whose true donor run is
        embedded in the comments field.  Skips version 0 (geometric
        default).

        This consolidates the logic previously inline in
        ``utils.indexStates``.
        """
        bestCycle = ""
        for entry in calibIndexList:
            if entry.get("version", -1) == 0:
                continue
            comment = entry.get("comments", "")
            m = _PROPAGATION_RE.match(comment)
            effectiveRun = m.group(1) if m else entry.get("runNumber", "")
            cycle = ssm.cycleForRun(effectiveRun) or ""
            if cycle > bestCycle:
                bestCycle = cycle
        return bestCycle

    def getAllStates(
        self,
        isLite: bool = True,
        runNumber=None,
        cycleID: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return a list of state summary dicts for every known state.

        Each dict contains the keys consumed by the State Overview table:
        ``stateID``, ``description``, ``status`` (:class:`CalStatus`),
        individual state params (``arc1``, …), calibration counts,
        latest cycle for difcal/normcal, and corruption flag.

        Parameters
        ----------
        runNumber : int or str, optional
            If provided, status is scoped to this run (including
            appliesTo and cycle matching).  This enables the
            OUT_OF_CYCLE and UNMATCHED classifications.
        cycleID : str, optional
            If provided (and *runNumber* is ``None``), status reflects
            whether the state has a calibration *from* this cycle.
            The ``appliesTo`` range is not checked — only the
            calibration's own cycle membership matters.
        """
        rows: List[Dict[str, Any]] = []

        for stateID in ssm.availableStates():
            rows.append(self.getStateSummary(
                stateID, isLite=isLite, runNumber=runNumber, cycleID=cycleID,
            ))

        return rows

    def getStateSummary(
        self,
        stateID: str,
        isLite: bool = True,
        runNumber=None,
        cycleID: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a single state-summary dict.

        Parameters
        ----------
        stateID : str
            The 16-character state hash.
        isLite : bool
            Whether to query lite-mode calibrations.
        runNumber : int or str, optional
            If provided, status is evaluated *for this run* (including
            cycle matching via ``requireSameCycle=True``).  If ``None``,
            status reflects whether the state has *any* calibrations.
        cycleID : str, optional
            If provided (and *runNumber* is ``None``), status reflects
            whether the state has a calibration *from* this cycle.
            The ``appliesTo`` range is not checked.

        Returns
        -------
        dict
            Keys consumed by the State Overview table, plus
            ``difcalTypeStatus`` and ``normcalTypeStatus`` for the
            detail panel.

        Separated from :meth:`getAllStates` so a single row can be
        refreshed after a repair without re-scanning everything.
        """
        stateDict = ssm.pullStateDict(stateID)
        params = self._parseStateParams(stateDict)
        desc = ssm.autoStateName(stateDict)

        # When a cycleID is selected (without a specific run), we only
        # need the unscoped index — appliesTo is irrelevant.
        effectiveRun = runNumber if cycleID is None else None

        difcal = ssm.checkCalibrationStatus(
            runNumber=effectiveRun, stateID=stateID, isLite=isLite, calType="difcal",
        )
        nrmcal = ssm.checkCalibrationStatus(
            runNumber=effectiveRun, stateID=stateID, isLite=isLite, calType="normcal",
        )

        # ── per-calType classification ───────────────────────────
        if cycleID is not None and runNumber is None:
            difTypeStatus = caltype_status_for_cycle(difcal, cycleID)
            nrmTypeStatus = caltype_status_for_cycle(nrmcal, cycleID)
        else:
            difTypeStatus = caltype_status_from_detail(difcal)
            nrmTypeStatus = caltype_status_from_detail(nrmcal)

        # ── corruption check ─────────────────────────────────────
        difCorrupt = False
        nrmCorrupt = False
        corruptIssues: List[str] = []
        try:
            difReport = ssm.validateIndex(
                runNumber=None, stateID=stateID, isLite=isLite, calType="difcal",
            )
            if not difReport["ok"]:
                difCorrupt = True
                for issue in difReport.get("issues", []):
                    corruptIssues.append(f"difcal: {issue}")
                for er in difReport.get("entries", []):
                    for issue in er.get("issues", []):
                        corruptIssues.append(f"difcal v{er.get('version', '?')}: {issue}")
        except Exception as exc:
            difCorrupt = True
            corruptIssues.append(f"difcal: validation error: {exc}")
        try:
            nrmReport = ssm.validateIndex(
                runNumber=None, stateID=stateID, isLite=isLite, calType="normcal",
            )
            if not nrmReport["ok"]:
                nrmCorrupt = True
                for issue in nrmReport.get("issues", []):
                    corruptIssues.append(f"normcal: {issue}")
                for er in nrmReport.get("entries", []):
                    for issue in er.get("issues", []):
                        corruptIssues.append(f"normcal v{er.get('version', '?')}: {issue}")
        except Exception as exc:
            nrmCorrupt = True
            corruptIssues.append(f"normcal: validation error: {exc}")

        # ── combine into overall status ──────────────────────────
        # Check for double-propagated difcal entries (copy-of-copy).
        # Only scan entries that are not version 0 (geometric default).
        difcalEntries = difcal.get("calibIndexList", [])
        doublePropVersions = [
            int(e.get("version", -1))
            for e in difcalEntries
            if int(e.get("version", -1)) != 0
            and is_double_propagated(e.get("comments", ""))
        ]
        hasDoublePropagated = bool(doublePropVersions)

        status = combine_caltype_statuses(
            difTypeStatus, nrmTypeStatus,
            difCorrupt=difCorrupt, nrmCorrupt=nrmCorrupt,
            hasDoublePropagated=hasDoublePropagated,
        )

        # ── latest difcal cycle ──────────────────────────────────
        nDifcal = difcal["numberCalibrations"]
        if difcal["latestCalibrationDate"] != "never":
            latestDifcalCycle = self._bestCycleFromIndex(
                difcal.get("calibIndexList", [])
            )
        else:
            latestDifcalCycle = ""

        # ── latest normcal cycle ─────────────────────────────────
        nNormcal = nrmcal["numberCalibrations"]
        if nrmcal["latestCalibrationDate"] != "never":
            latestNormcalCycle = ssm.cycleForRun(
                nrmcal["latestCalibrationDict"]["runNumber"]
            ) or ""
        else:
            latestNormcalCycle = ""

        return {
            "stateID": stateID,
            "description": desc,
            "status": status,
            "difcalTypeStatus": difTypeStatus,
            "normcalTypeStatus": nrmTypeStatus,
            "difcalDetail": difcal.get("statusDetail", ""),
            "normcalDetail": nrmcal.get("statusDetail", ""),
            **params,
            "nDifcal": nDifcal,
            "latestDifcalCycle": latestDifcalCycle,
            "nNormcal": nNormcal,
            "latestNormcalCycle": latestNormcalCycle,
            "isCorrupt": difCorrupt or nrmCorrupt,
            "corruptDetails": "\n".join(corruptIssues) if corruptIssues else "",
            # True when the corruption cannot be fixed by fixIndex and the
            # only resolution is deleting the entire state folder.
            "deleteOnly": any("cross-state contamination" in ci for ci in corruptIssues),
            "hasDoublePropagated": hasDoublePropagated,
            "doublePropagatedVersions": doublePropVersions,
        }

    # ── Calibration detail queries ───────────────────────────────────

    def getCalibrationDetails(
        self,
        stateID: str,
        calType: str = "difcal",
        isLite: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return enriched index entries for a state+calType.

        Each entry is a copy of the raw index dict augmented with:

        * ``cycleID`` – already annotated by ``checkCalibrationStatus``.
        * ``isPropagated`` – ``True`` when the entry was copied from
          another state (detected via the standardised comment prefix).
        * ``effectiveRun`` – for propagated entries this is the *donor*
          run extracted from the comment; for native entries it is the
          same as ``runNumber``.

        Entries are sorted by version ascending.
        """
        calStatus = ssm.checkCalibrationStatus(
            runNumber=None, stateID=stateID, isLite=isLite, calType=calType,
        )
        entries = calStatus.get("calibIndexList", [])

        for entry in entries:
            comment = entry.get("comments", "")
            m = _PROPAGATION_RE.match(comment)
            if m:
                entry["isPropagated"] = True
                entry["effectiveRun"] = m.group(1)
            else:
                entry["isPropagated"] = False
                entry["effectiveRun"] = entry.get("runNumber", "")
            # Flag copy-of-copy entries for the UI to highlight
            entry["isDoublePropagated"] = is_double_propagated(comment)

        # checkCalibrationStatus sorts by timestamp desc; re-sort by version asc
        entries.sort(key=lambda e: int(e.get("version", 0)))
        return entries

    # ── Validation / repair pass-throughs ────────────────────────────

    @staticmethod
    def validateState(
        stateID: str, isLite: bool = True,
    ) -> Dict[str, dict]:
        """Run ``validateIndex`` for both difcal and normcal.

        Returns
        -------
        dict
            ``{"difcal": report, "normcal": report}`` where each report
            is the dict returned by :func:`ssm.validateIndex`.
        """
        return {
            "difcal": ssm.validateIndex(
                runNumber=None, stateID=stateID, isLite=isLite, calType="difcal",
            ),
            "normcal": ssm.validateIndex(
                runNumber=None, stateID=stateID, isLite=isLite, calType="normcal",
            ),
        }

    @staticmethod
    def repairState(
        stateID: str,
        calType: str = "difcal",
        isLite: bool = True,
        dryRun: bool = True,
    ) -> dict:
        """Run ``fixIndex`` for a specific calType.

        Parameters
        ----------
        dryRun : bool
            If True (default) only report what *would* change.

        Returns the fixIndex report dict.
        """
        return ssm.fixIndex(
            runNumber=None,
            stateID=stateID,
            isLite=isLite,
            calType=calType,
            dryRun=dryRun,
        )

    # ── Phase 5: propagation preview/execute wrappers ─────────────

    def previewPropagation(
        self,
        donorRunNumber,
        isLite: bool = True,
        includeGuideStatus: bool = True,
    ) -> Dict[str, Any]:
        """Preview donor/recipient details for propagation without writing files.

        Returns a UI-friendly payload that explains which donor calibration
        would be used and which states would be targeted.
        """

        donorRunNumber = str(donorRunNumber)
        donorStateID, donorStateDict = ssm.stateDef(donorRunNumber)
        donorDetConfig = ssm.detectorConfig(donorStateDict, includeGuideStatus)

        donorCalStatus = ssm.checkCalibrationStatus(
            runNumber=donorRunNumber,
            stateID=None,
            isLite=isLite,
            calType="difcal",
        )

        donorLatest = donorCalStatus.get("latestValidCalibrationDict", {})
        preview: Dict[str, Any] = {
            "ok": True,
            "donorRunNumber": donorRunNumber,
            "donorStateID": donorStateID,
            "selectedDonorVersion": donorLatest.get("version"),
            "selectedDonorCycleID": donorLatest.get("cycleID"),
            "selectedDonorComment": donorLatest.get("comments", ""),
            "blocked": False,
            "blockReason": None,
            "recipients": [],
        }

        if not donorCalStatus.get("runIsCalibrated", False):
            preview["blocked"] = True
            preview["blockReason"] = "no_donor_calibration"
            return preview

        from snapwrap import utils as wrap

        if wrap._is_propagated_entry(donorLatest):
            preview["blocked"] = True
            preview["blockReason"] = "donor_is_propagated"

        recipients: List[Dict[str, Any]] = []
        for stateID in ssm.availableStates():
            if stateID == donorStateID:
                continue
            stateDict = ssm.pullStateDict(stateID)
            detConfig = ssm.detectorConfig(stateDict, includeGuideStatus)
            if detConfig != donorDetConfig:
                continue

            calStatus = ssm.checkCalibrationStatus(
                runNumber=None,
                stateID=stateID,
                isLite=isLite,
                calType="difcal",
            )
            existingVersions = [
                int(entry.get("version", 0))
                for entry in calStatus.get("calibIndexList", [])
            ]
            maxVersion = max(existingVersions) if existingVersions else None
            recipients.append({
                "stateID": stateID,
                "recipientPreviousVersions": calStatus.get("numberCalibrations", 0),
                "newVersion": (maxVersion + 1) if maxVersion is not None else None,
            })

        preview["recipients"] = recipients
        return preview

    def executePropagation(
        self,
        donorRunNumber,
        isLite: bool = True,
        includeGuideStatus: bool = True,
    ) -> Dict[str, Any]:
        """Execute propagation from UI after preview/confirmation."""

        preview = self.previewPropagation(
            donorRunNumber,
            isLite=isLite,
            includeGuideStatus=includeGuideStatus,
        )

        if preview.get("blocked"):
            return {
                **preview,
                "ok": False,
                "executed": False,
                "summary": "Propagation blocked by donor validation.",
            }

        try:
            from snapwrap import utils as wrap

            wrap.propagateDifcal(
                donorRunNumber,
                isLite=isLite,
                propagate=True,
                includeGuideStatus=includeGuideStatus,
            )
        except Exception as exc:
            return {
                **preview,
                "ok": False,
                "executed": False,
                "summary": f"Propagation failed: {exc}",
                "error": str(exc),
            }

        return {
            **preview,
            "ok": True,
            "executed": True,
            "summary": f"Propagation executed for {len(preview.get('recipients', []))} recipient state(s).",
        }

    # ── New functionality: invalidate double-propagated entries ─────

    def invalidateDoublePropagatedEntries(
        self,
        stateID: str,
        isLite: bool = True,
        dryRun: bool = True,
    ) -> Dict[str, Any]:
        """Invalidate all double-propagated difcal versions in a state's index.

        A double-propagated entry is one whose ``comments`` field is itself
        a propagation comment (copy-of-a-copy).  These entries are
        semantically invalid and must be taken out of use before
        re-propagating from the correct donor.

        Versions are processed in ascending order.  The former
        ``removeDoublePropagatedEntries`` had to work from highest to lowest
        because each deletion triggered a ``fixIndex`` re-numbering that
        shifted the versions still to be removed; invalidation re-numbers
        nothing, so order no longer matters.

        Parameters
        ----------
        dryRun : bool
            If ``True`` (default), only report what *would* be invalidated.
            No files are modified.

        Returns
        -------
        dict
            * ``ok`` – ``True`` if all invalidations succeeded (or dry-run).
            * ``versions`` – sorted list of version numbers that are / would
              be invalidated.
            * ``messages`` – per-version result messages from
              :meth:`invalidateCalibrationVersion`.
            * ``summary`` – human-readable one-line summary.
        """
        calStatus = ssm.checkCalibrationStatus(
            runNumber=None, stateID=stateID, isLite=isLite, calType="difcal",
        )
        entries = calStatus.get("calibIndexList", [])
        dp_versions = sorted(
            int(e.get("version", -1))
            for e in entries
            if int(e.get("version", -1)) != 0
            and is_double_propagated(e.get("comments", ""))
        )

        if not dp_versions:
            return {
                "ok": True,
                "versions": [],
                "messages": [],
                "summary": f"No double-propagated entries found in state {stateID}.",
            }

        messages = []
        all_ok = True
        for version in dp_versions:
            result = self.invalidateCalibrationVersion(
                stateID, "difcal", version, isLite=isLite, dryRun=dryRun,
            )
            messages.append(result.get("message", ""))
            if not result.get("ok"):
                all_ok = False

        prefix = "[DRY RUN] Would invalidate" if dryRun else "Invalidated"
        summary = (
            f"{prefix} {len(dp_versions)} double-propagated difcal version(s) "
            f"in state {stateID}: {dp_versions}."
        )
        return {
            "ok": all_ok,
            "versions": dp_versions,
            "messages": messages,
            "summary": summary,
        }

    # ── New functionality: invalidate a calibration version ──────────

    @staticmethod
    def invalidateCalibrationVersion(
        stateID: str,
        calType: str,
        version: int,
        isLite: bool = True,
        dryRun: bool = True,
    ) -> Dict[str, Any]:
        """Retire a calibration version without destroying it.

        Replaces the former ``deleteCalibrationVersion``. Deleting a version
        removed its folder and re-numbered everything above it, which broke
        provenance: a run reduced against "version N" could no longer be tied
        to the calibration that produced it, because a different calibration
        had since become version N.

        Invalidation leaves the version number, folder and record in place and
        instead makes the entry unselectable — ``appliesTo`` becomes
        ``<0``, which no run can satisfy, and the comment is prefixed with
        ``(INVALIDATED)``. ``Indexer._isApplicableEntry`` compares run numbers
        numerically, so the entry is filtered out of every lookup while the
        history stays readable.

        Because nothing is removed, version numbering stays contiguous and no
        ``fixIndex`` re-versioning pass is needed.

        The ``indexEntry`` is duplicated in three places inside the version
        folder alongside the index itself, and ``validateIndex`` flags any
        mismatch, so all four copies are rewritten together:

        1. the entry in ``CalibrationIndex.json`` / ``NormalizationIndex.json``
        2. ``<Cal|Norm>Record.json`` → ``indexEntry``
        3. ``<Cal|Norm>Record.json`` → ``calculationParameters.indexEntry``
        4. ``<Cal|Norm>Parameters.json`` → ``indexEntry``

        Parameters
        ----------
        version : int
            The version to invalidate.  Version 0 (the geometric default for
            difcal) cannot be invalidated.
        dryRun : bool
            If True (default), only report what *would* happen.

        Returns
        -------
        dict
            ``ok``, ``message``, and on success ``updatedFiles`` — the paths
            actually rewritten — plus ``backupDir``.
        """
        import json
        import os
        import shutil

        from snapwrap.indexComments import NEVER_APPLIES, mark_invalidated

        if calType == "difcal" and version == 0:
            return {
                "ok": False,
                "message": "Cannot invalidate the default geometric calibration (version 0).",
            }

        calStatus = ssm.checkCalibrationStatus(
            runNumber=None, stateID=stateID, isLite=isLite, calType=calType,
        )
        calFolder = calStatus["calFolder"]
        indexPath = calStatus["indexPath"]
        indexEntries = calStatus.get("calibIndexList", [])

        target = None
        for entry in indexEntries:
            if int(entry.get("version", -1)) == version:
                target = entry
                break

        if target is None:
            return {"ok": False, "message": f"Version {version} not found in index."}

        if str(target.get("appliesTo", "")).strip() == NEVER_APPLIES:
            return {
                "ok": False,
                "message": f"Version {version} is already invalidated.",
            }

        vFolderName = f"v_{str(version).zfill(4)}"
        vFolderPath = os.path.join(calFolder, vFolderName)
        newComment = mark_invalidated(target.get("comments", ""))

        if dryRun:
            return {
                "ok": True,
                "message": (
                    f"[DRY RUN] Would invalidate version {version}: set appliesTo to "
                    f"'{NEVER_APPLIES}' and prefix its comment with '(INVALIDATED)', in the "
                    f"index and in the record files under {vFolderPath}.\n\n"
                    f"The version folder is kept and remaining versions are NOT re-numbered, "
                    f"so provenance for already-reduced runs is preserved."
                ),
            }

        # ── back up before touching anything ──────────────────────
        backupDir = ssm._session_backup_dir(stateID, calType)
        if os.path.isdir(vFolderPath):
            backupTarget = os.path.join(backupDir, vFolderName)
            if not os.path.exists(backupTarget):
                # Records are small; the bulk of a version folder is nexus data
                # that invalidation never touches, so copy only the JSON.
                os.makedirs(backupTarget, exist_ok=True)
                for fn in os.listdir(vFolderPath):
                    if fn.endswith(".json"):
                        shutil.copy2(os.path.join(vFolderPath, fn),
                                     os.path.join(backupTarget, fn))
        try:
            shutil.copy2(indexPath, os.path.join(backupDir, os.path.basename(indexPath)))
        except Exception:
            pass

        # ── 1. the index itself ───────────────────────────────────
        _INDEX_KEYS = {"version", "runNumber", "useLiteMode",
                       "appliesTo", "comments", "author", "timestamp"}
        updatedEntries = []
        newEntry = None
        for e in sorted(indexEntries, key=lambda e: int(e.get("version", 0))):
            clean = {k: v for k, v in e.items() if k in _INDEX_KEYS}
            if int(e.get("version", -1)) == version:
                clean["appliesTo"] = NEVER_APPLIES
                clean["comments"] = newComment
                newEntry = clean
            updatedEntries.append(clean)

        with open(indexPath, "w") as fh:
            json.dump(updatedEntries, fh, indent=2)

        updatedFiles = [indexPath]

        # ── 2-4. the copies embedded in the version folder ────────
        recordName, paramsName = (
            ("CalibrationRecord.json", "CalibrationParameters.json")
            if calType == "difcal"
            else ("NormalizationRecord.json", "NormalizationParameters.json")
        )

        recordPath = os.path.join(vFolderPath, recordName)
        if os.path.isfile(recordPath):
            with open(recordPath) as fh:
                rec = json.load(fh)
            if isinstance(rec.get("indexEntry"), dict):
                rec["indexEntry"] = newEntry
            calcParams = rec.get("calculationParameters")
            if isinstance(calcParams, dict) and isinstance(calcParams.get("indexEntry"), dict):
                calcParams["indexEntry"] = newEntry
            with open(recordPath, "w") as fh:
                json.dump(rec, fh, indent=2)
            updatedFiles.append(recordPath)

        paramsPath = os.path.join(vFolderPath, paramsName)
        if os.path.isfile(paramsPath):
            with open(paramsPath) as fh:
                par = json.load(fh)
            if isinstance(par.get("indexEntry"), dict):
                par["indexEntry"] = newEntry
                with open(paramsPath, "w") as fh:
                    json.dump(par, fh, indent=2)
                updatedFiles.append(paramsPath)

        return {
            "ok": True,
            "message": (
                f"Invalidated version {version} (appliesTo '{NEVER_APPLIES}'). "
                f"Folder retained, versions not re-numbered. Backup at {backupDir}."
            ),
            "updatedFiles": updatedFiles,
            "backupDir": backupDir,
        }

    @staticmethod
    def deleteStateFolder(stateID: str, dryRun: bool = True) -> Dict[str, str]:
        """Delete an entire state folder (use with extreme caution).

        The function first creates a full backup of the state folder under
        the calibration Backup directory. When *dryRun* is True the function
        only reports what would be done.

        Returns
        -------
        dict
            ``ok`` : bool
            ``message`` : human-readable summary
            ``backupPath`` : path to the backup (or proposed backup) location
        """
        import os
        import shutil
        from datetime import datetime

        home = ssm.SNAPHome()
        statePath = os.path.join(home.powder, stateID)
        if not os.path.exists(statePath):
            return {"ok": False, "message": f"State folder not found: {statePath}", "backupPath": ""}

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = ssm._backup_dir()
        backupName = f"deleteState_{stateID}_{stamp}"
        backupPath = os.path.join(backup_root, backupName)

        summary = ssm._folder_stat_summary(statePath)

        if dryRun:
            return {
                "ok": True,
                "message": (
                    f"[DRY RUN] Would back up {statePath} → {backupPath} and then "
                    "delete the original state folder.\n\nFolder summary:\n" + summary
                ),
                "backupPath": backupPath,
            }

        # Perform backup then delete
        try:
            shutil.copytree(statePath, backupPath)
        except Exception as e:
            return {"ok": False, "message": f"Failed to copy backup: {e}", "backupPath": ""}

        try:
            shutil.rmtree(statePath)
        except Exception as e:
            return {"ok": False, "message": f"Backup created at {backupPath} but failed to delete original: {e}", "backupPath": backupPath}

        return {"ok": True, "message": f"State folder deleted. Backup at {backupPath}", "backupPath": backupPath}
