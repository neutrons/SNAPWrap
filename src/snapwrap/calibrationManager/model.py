"""Data-layer for the Calibration Manager UI.

This module is a *thin aggregation layer* over the existing functions in
:mod:`snapwrap.snapStateMgr` and :mod:`snapwrap.cycleDates`.  It adds no
duplicated business logic — it calls through to the existing backend and
reshapes the output into simple data structures that are easy for
``QAbstractTableModel`` to consume.

The only genuinely *new* business logic here is
:meth:`CalibrationManagerModel.deleteCalibrationVersion`, which does not
have a pre-existing counterpart in ``snapStateMgr``.
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
        try:
            difReport = ssm.validateIndex(
                runNumber=None, stateID=stateID, isLite=isLite, calType="difcal",
            )
            if not difReport["ok"]:
                difCorrupt = True
        except Exception:
            difCorrupt = True
        try:
            nrmReport = ssm.validateIndex(
                runNumber=None, stateID=stateID, isLite=isLite, calType="normcal",
            )
            if not nrmReport["ok"]:
                nrmCorrupt = True
        except Exception:
            nrmCorrupt = True

        # ── combine into overall status ──────────────────────────
        status = combine_caltype_statuses(
            difTypeStatus, nrmTypeStatus,
            difCorrupt=difCorrupt, nrmCorrupt=nrmCorrupt,
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
        }

    # ── Calibration detail queries ───────────────────────────────────

    def getCalibrationDetails(
        self,
        stateID: str,
        calType: str = "difcal",
        isLite: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return enriched index entries for a state+calType.

        Each entry is a copy of the raw index dict augmented with
        ``cycleID`` (already done by ``checkCalibrationStatus``).

        Entries are sorted by version ascending.
        """
        calStatus = ssm.checkCalibrationStatus(
            runNumber=None, stateID=stateID, isLite=isLite, calType=calType,
        )
        entries = calStatus.get("calibIndexList", [])
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

    # ── New functionality: delete a calibration version ──────────────

    @staticmethod
    def deleteCalibrationVersion(
        stateID: str,
        calType: str,
        version: int,
        isLite: bool = True,
        dryRun: bool = True,
    ) -> Dict[str, Any]:
        """Delete a single version from a state's calibration index.

        Removes the version folder and its index entry, then calls
        ``fixIndex`` to re-number remaining versions and rebuild the index.

        Parameters
        ----------
        version : int
            The version to delete.  Version 0 (geometric default for
            difcal) cannot be deleted.
        dryRun : bool
            If True (default), only report what *would* happen.

        Returns
        -------
        dict
            ``ok``, ``message``, and the ``fixIndex`` report (if
            re-versioning was triggered).
        """
        import json
        import os
        import shutil

        if calType == "difcal" and version == 0:
            return {"ok": False, "message": "Cannot delete the default geometric calibration (version 0)."}

        # Build path
        calStatus = ssm.checkCalibrationStatus(
            runNumber=None, stateID=stateID, isLite=isLite, calType=calType,
        )
        calFolder = calStatus["calFolder"]
        indexPath = calStatus["indexPath"]
        indexEntries = calStatus.get("calibIndexList", [])

        # Find the entry
        target = None
        for entry in indexEntries:
            if int(entry.get("version", -1)) == version:
                target = entry
                break

        if target is None:
            return {"ok": False, "message": f"Version {version} not found in index."}

        vFolderName = f"v_{str(version).zfill(4)}"
        vFolderPath = os.path.join(calFolder, vFolderName)

        if dryRun:
            return {
                "ok": True,
                "message": (
                    f"[DRY RUN] Would delete folder {vFolderPath} and remove "
                    f"index entry for version {version}, then re-version remaining "
                    f"calibrations."
                ),
            }

        # ── Actual deletion ──────────────────────────────────────
        # 1. Back up via the existing fixIndex backup machinery
        backupDir = ssm._session_backup_dir(stateID, calType)
        if os.path.isdir(vFolderPath):
            shutil.copytree(vFolderPath, os.path.join(backupDir, vFolderName))

        # 2. Remove the version folder
        if os.path.isdir(vFolderPath):
            shutil.rmtree(vFolderPath)

        # 3. Remove the entry from the index and rewrite
        updatedEntries = [e for e in indexEntries if int(e.get("version", -1)) != version]
        with open(indexPath, "w") as fh:
            json.dump(updatedEntries, fh, indent=2)

        # 4. Re-number via fixIndex (non-dry-run)
        fixReport = ssm.fixIndex(
            runNumber=None, stateID=stateID, isLite=isLite,
            calType=calType, dryRun=False,
        )

        return {
            "ok": True,
            "message": f"Deleted version {version}. Backup at {backupDir}.",
            "fixReport": fixReport,
        }
