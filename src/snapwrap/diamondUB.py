"""Diamond UB-matrix determination for DAC experiments on SNAP.

Adapted from ``diamUBFunctions.py`` (M. Guthrie, 2020–2025) for the SNAPWrap
reduction artefact framework.

Changes from the original module
---------------------------------
- ``generatePeaksWorkspace``: ``ipts`` is now an explicit keyword argument
  rather than being discovered via ``GetIPTS``; ``nexus_path`` can be overridden
  for testing or non-standard data locations.
- ``peakInfo.CreatePeaksWSAndSave``: accepts an explicit ``output_path`` for
  the saved ``.mat`` file rather than constructing one from ``self.ipts``.
- ``chooseIntFromArray`` (interactive helper) removed — not needed in the
  automated artefact-build workflow.
- Workspace naming follows SNAPWrap conventions:
  ``snapwrap_DSP_{run}``, ``snapwrap_MD_{run}``, ``snapwrap_PKS_{run}``.
- Mantid imports are deferred inside functions / at class method call-time
  where feasible, but this module **requires Mantid** at runtime.

Algorithm notes
---------------
The UB-determination algorithm is an implementation of the method described
in R.A. Jacobsen, *Zeitschrift fur Kristallographie* **212**, 99–102 (1997).
See :func:`jacobsen` for details.

Two UBs are found because a DAC contains two diamond anvils that are
typically slightly misaligned.  :func:`findDiamUB` runs the search twice —
first on all candidate diamond reflections, then on those *not* indexed by
the first crystal — returning both orientations in ``peakInfo.UBList``.

Usage (within Mantid/SNAPWrap)
------------------------------
::

    from snapwrap.diamondUB import generatePeaksWorkspace, peakInfo, findDiamUB

    peaks_ws, _ = generatePeaksWorkspace(65891, ipts=33219)
    pk = peakInfo(peaks_ws)
    pk.ipts = 33219
    pk.runNumber = 65891
    findDiamUB(pk)
    pk.CreatePeaksWSAndSave(1, "/path/to/SNAP65891UB1.mat")
    pk.CreatePeaksWSAndSave(2, "/path/to/SNAP65891UB2.mat")
"""

from __future__ import annotations

from itertools import combinations  # noqa: F401 (kept for API compatibility)
from pathlib import Path

import numpy as np
from mantid.kernel import logger
from mantid.simpleapi import (
    CloneWorkspace,
    ClearUB,
    ConvertToMD,
    ConvertUnits,
    CropWorkspace,
    FilterPeaks,
    FindPeaksMD,
    IndexPeaks,
    IntegratePeaksMD,
    LoadEventNexus,
    SaveIsawUB,
    SetGoniometer,
    SetUB,
    SumNeighbours,
    mtd,
)


# ---------------------------------------------------------------------------
# Raw nexus path helper
# ---------------------------------------------------------------------------

def _raw_nexus_path(ipts: int, run_number: int) -> str:
    """Return the conventional SNS raw nexus path for a SNAP run."""
    return f"/SNS/SNAP/IPTS-{ipts}/nexus/SNAP_{run_number}.nxs.h5"


# ---------------------------------------------------------------------------
# Peak-finding
# ---------------------------------------------------------------------------

def generatePeaksWorkspace(
    run_number: int,
    *,
    ipts: int,
    nexus_path: str | Path | None = None,
    dens_thresh: float = 400,
) -> tuple[str, str]:
    """Load a SNAP run, find diamond candidate peaks, and return the workspace name.

    This is the first step of the DAC UB-determination pipeline.  It loads
    the full event nexus file, converts to d-spacing, sums neighbours (to
    improve signal-to-noise), converts to reciprocal space (MD), and runs
    peak finding + integration + filtering.

    The heavy MDEventWorkspace (``snapwrap_MD_{run_number}``) is preserved in
    the Mantid ADS so that a second call with the same run number skips the
    expensive conversion step.  The peaks workspace is regenerated on every
    call (different ``dens_thresh`` values may be needed).

    Args:
        run_number: SNAP run number.
        ipts: IPTS experiment number, used to locate the nexus file when
            *nexus_path* is not supplied.
        nexus_path: Override for the raw nexus file path.  When ``None``
            (default) the conventional SNS path is used.
        dens_thresh: Density threshold factor passed to
            ``FindPeaksMD``.  Higher values find fewer, stronger peaks.

    Returns:
        ``(peaks_ws_name, ipts_path)`` where *peaks_ws_name* is the Mantid ADS
        key for the :class:`~mantid.api.IPeaksWorkspace` and *ipts_path* is
        the IPTS directory string (for compatibility with downstream code that
        checks ``peakInfo.ipts``).
    """
    nexus = str(nexus_path) if nexus_path is not None else _raw_nexus_path(ipts, run_number)
    ipts_path = f"/SNS/SNAP/IPTS-{ipts}/"

    ws_dsp = f"snapwrap_DSP_{run_number}"
    ws_md = f"snapwrap_MD_{run_number}"
    ws_pks = f"snapwrap_PKS_{run_number}"

    if ws_md not in mtd.getObjectNames():
        LoadEventNexus(Filename=nexus, OutputWorkspace=ws_dsp)

        ConvertUnits(
            InputWorkspace=ws_dsp,
            Target="dSpacing",
            EMode="Elastic",
            OutputWorkspace=ws_dsp,
        )

        SumNeighbours(
            InputWorkspace=ws_dsp,
            OutputWorkspace=ws_dsp,
            SumX=8,
            SumY=8,
        )

        CropWorkspace(
            InputWorkspace=ws_dsp,
            OutputWorkspace=ws_dsp,
            XMin=0.5,
        )

        ConvertToMD(
            InputWorkspace=ws_dsp,
            QDimensions="Q3D",
            dEAnalysisMode="Elastic",
            Q3DFrames="Q_lab",
            OutputWorkspace=ws_md,
        )

    FindPeaksMD(
        InputWorkspace=ws_md,
        PeakDistanceThreshold=0.25,
        MaxPeaks=50,
        DensityThresholdFactor=dens_thresh,
        OutputWorkspace=ws_pks,
    )

    IntegratePeaksMD(
        InputWorkspace=ws_md,
        PeakRadius=0.12,
        BackgroundInnerRadius=0.14,
        BackgroundOuterRadius=0.17,
        PeaksWorkspace=ws_pks,
        OutputWorkspace=ws_pks,
    )

    FilterPeaks(
        InputWorkspace=ws_pks,
        OutputWorkspace=ws_pks,
        FilterVariable="Signal/Noise",
        FilterValue=40,
        Operator=">",
    )

    FilterPeaks(
        InputWorkspace=ws_pks,
        OutputWorkspace=ws_pks,
        FilterVariable="DSpacing",
        FilterValue=0.5,
        Operator=">",
    )

    FilterPeaks(
        InputWorkspace=ws_pks,
        OutputWorkspace=ws_pks,
        FilterVariable="DSpacing",
        FilterValue=2.15,
        Operator="<",
    )

    SetGoniometer(Workspace=ws_pks, Axis0="omega, 0,1,0,1")

    n_peaks = mtd[ws_pks].getNumberPeaks()
    print(f"Found {n_peaks} candidate peaks in workspace: {ws_pks}")

    return ws_pks, ipts_path


# ---------------------------------------------------------------------------
# peakInfo class
# ---------------------------------------------------------------------------

class peakInfo:
    """Container and indexing helper for a Mantid peaks workspace.

    Holds a copy of the key peak attributes (d-spacing, Q, HKL, intensity,
    wavelength) sorted by decreasing d-spacing, together with bookkeeping
    arrays (``crystalID``, ``position``, ``beta``) used by the iterative
    UB-finding algorithm.

    After :func:`findDiamUB` has run, the found UB matrices are stored in
    ``self.UBList`` (list of 3×3 numpy arrays, one per diamond crystal, in
    discovery order).

    Args:
        peakWSName: Name of the :class:`~mantid.api.IPeaksWorkspace` in the
            Mantid ADS.
        purgePeaks: If non-zero, reset all HKL indices to (0,0,0) on load
            (useful for re-indexing from scratch).
    """

    def __init__(self, peakWSName: str, purgePeaks: int = 0) -> None:
        self.ipts: int | str | None = None
        self.runNumber: int | None = None

        self.peaksWS = peakWSName
        print(f"Loading workspace: {peakWSName}")
        sxlLst = mtd[peakWSName]

        self.npk = sxlLst.getNumberPeaks()
        print(f"Read: {self.npk} peaks")
        self.totalDiamondReflections = 0

        self.refID = np.zeros(self.npk, dtype=np.int8)
        self.crystalID = np.zeros(self.npk, dtype=np.int8)
        self.position = np.zeros(self.npk, dtype=np.int8)
        self.hkl = np.zeros([self.npk, 3])
        self.d = np.zeros(self.npk)
        self.Q = np.zeros([self.npk, 3])
        self.intensity = np.zeros(self.npk)
        self.lam = np.zeros(self.npk)
        self.beta = np.zeros(self.npk)
        self.calcBeta = np.zeros(self.npk)

        Q = []
        for i in range(self.npk):
            p = sxlLst.getPeak(i)
            self.refID[i] = i
            self.d[i] = p.getDSpacing()
            Q.append(p.getQLabFrame())
            self.intensity[i] = p.getIntensity()
            self.lam[i] = p.getWavelength()
            if purgePeaks:
                p.setHKL(0, 0, 0)
            self.hkl[i][:] = p.getHKL()
            self.position[i] = 0

        self.Q = np.array(Q)

        srtIndx = np.flip(np.argsort(self.d))
        self.refID = self.refID[srtIndx]
        self.d = self.d[srtIndx]
        self.Q = self.Q[srtIndx][:]
        self.intensity = self.intensity[srtIndx]
        self.lam = self.lam[srtIndx]
        self.hkl = self.hkl[srtIndx][:]
        self.crystalID = self.crystalID[srtIndx]
        self.position = self.position[srtIndx]
        self.beta = self.beta[srtIndx]
        self.calcBeta = self.calcBeta[srtIndx]

        self.UBList: list[np.ndarray] = []
        self.verbose = False

    def toggleVerbose(self, setting: bool) -> None:
        self.verbose = setting

    def printPeaks(self, crystalID=None) -> None:
        print(" ref       h       k       l      d   ID  pos     beta    calcBet    Q1      Q2      Q3")
        for i in range(self.npk):
            if crystalID is None or self.crystalID[i] == crystalID:
                print(
                    f"{self.refID[i]:4} {self.hkl[i][0]:7.3f} {self.hkl[i][1]:7.3f} {self.hkl[i][2]:7.3f}"
                    f"{self.d[i]:7.4f} {self.crystalID[i]:4} {self.position[i]:4}"
                    f"{self.beta[i]:9.1f} {self.calcBeta[i]:9.1f}"
                    f"{self.Q[i][0]:7.3f} {self.Q[i][1]:7.3f} {self.Q[i][2]:7.3f}"
                )

    def countID(self, id):
        nID = 0
        IDList = []
        for i in range(self.npk):
            if self.crystalID[i] == id:
                self.position[i] = int(nID)
                nID += 1
                IDList.append(int(self.refID[i]))
        return IDList, nID

    def resetPositions(self, crystalID) -> None:
        count = 0
        for i in range(self.npk):
            if self.crystalID[i] == crystalID:
                self.position[i] = count
                count += 1

    def resetCrystalIDForList(self, uniqueIDList, newCrystalID) -> None:
        for index in range(self.npk):
            if self.refID[index] in uniqueIDList:
                self.crystalID[index] = newCrystalID
                self.beta[index] = 0.0
                self.calcBeta[index] = 0.0

    def findIndexFromRefID(self, id):
        for index in range(self.npk):
            if self.refID[index] == id:
                return index

    def uniqueID(self, crystalID, position):
        for i in range(self.npk):
            if (self.crystalID[i] == crystalID) and (self.position[i] == position):
                return self.refID[i]

    def resetCrystal(self) -> None:
        count = 0
        for row in range(self.npk):
            self.crystalID[row] = 0
            self.position[row] = count
            count += 1
            self.beta[row] = 0.0
            self.calcBeta[row] = 0.0

    def indexToReferenceReflection(
        self,
        inputCrystalID,
        referenceID,
        angleTolerance=3.5,
        indexingTolerance=0.05,
    ):
        refIndex = self.findIndexFromRefID(referenceID)
        inputReflectionList, nInputReflections = self.countID(inputCrystalID)

        self.crystalID[refIndex] = 99

        for i in range(self.npk):
            if self.crystalID[i] == inputCrystalID:
                if self.refID[i] == refIndex:
                    self.beta[i] = 0.0
                else:
                    self.beta[i] = self.angleBetweenVectors(self.Q[refIndex], self.Q[i])
                    self.equivMatch(
                        referenceID=referenceID,
                        checkID=self.refID[i],
                        tolerance=angleTolerance,
                        outputCrystalID=99,
                    )

        subSubList, nSubSub = self.countID(99)

        if nSubSub <= 1:
            if self.verbose:
                print("WARNING: insufficient candidate reflections")
            return [[0, 0, 0], [0, 0, 0], [0, 0, 0]], 0, [-1, -1]

        if self.verbose:
            print("In indexToReferenceReflection:")
            self.crystalID[refIndex] = 98
            self.printPeaks(98)
            print("matching reflections:")
            self.printPeaks(99)
            self.crystalID[refIndex] = 99
            print(f"{nSubSub - 1} candidate reflections are at correct angle to reference")
            print("list of candidates: ", subSubList)

        maxIndexed = 0
        bestRef = None
        bestUB = None
        for i in subSubList:
            row = self.findIndexFromRefID(i)
            if row == refIndex:
                continue
            if self.beta[row] <= 0.5:
                continue
            try:
                UB = jacobsen(self.hkl[refIndex], self.Q[refIndex], self.hkl[row], self.Q[row])
                nIndex = self.indexWithUB(
                    inputCrystalID=99,
                    outputCrystalID=None,
                    UB=UB,
                    referenceID=referenceID,
                    indexingTolerance=indexingTolerance,
                    angleTolerance=angleTolerance,
                )
                if nIndex > maxIndexed:
                    maxIndexed = nIndex
                    bestRef = i
                    bestUB = UB
            except Exception:
                print("WARNING: UB determination error. Are input reflections parallel?")

        if maxIndexed == 0 or bestUB is None:
            if self.verbose:
                print("No usable UB found")
            self.resetCrystalIDForList(inputReflectionList, -1)
            self.resetPositions(-1)
            return [[0, 0, 0], [0, 0, 0], [0, 0, 0]], 0, [-1, -1]

        seedPair = [referenceID, bestRef]

        if self.verbose:
            print(f"\nBest UB for reference peak {referenceID} with pair {bestRef}, {maxIndexed} peaks")
            print(bestUB)

        self.resetCrystalIDForList(inputReflectionList, -1)
        self.resetPositions(-1)
        return bestUB, maxIndexed, seedPair

    def angleBetweenVectors(self, a, b) -> float:
        angle = np.arccos(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        return float(np.degrees(angle))

    def equivMatch(self, referenceID, checkID, tolerance, outputCrystalID) -> None:
        nCheck = self.findIndexFromRefID(checkID)
        refIndex = self.findIndexFromRefID(referenceID)
        allEqv = m3mEquiv(self.hkl[nCheck])
        for HKL in allEqv:
            refHKL = self.hkl[refIndex]
            calcBeta = self.angleBetweenVectors(refHKL, HKL)
            dif = abs(calcBeta - self.beta[nCheck])
            if dif <= tolerance:
                self.crystalID[nCheck] = outputCrystalID
                self.calcBeta[nCheck] = calcBeta
                self.hkl[nCheck] = HKL
                return

    def fd3mReflectionCondition(self, hkl) -> bool:
        hkl = np.array(np.absolute(np.rint(hkl)), dtype=np.int8)
        hkl = np.sort(hkl)
        zeroLoc = np.where(hkl == 0)[0]
        if len(zeroLoc) == 2:
            return bool(hkl[2] % 4 == 0)
        if len(zeroLoc) == 1:
            return bool(
                np.any(
                    [
                        (hkl[1] + hkl[2]) % 4 == 0,
                        (hkl[1] + hkl[2]) == hkl[1],
                        (hkl[1] + hkl[2]) == hkl[2],
                    ]
                )
            )
        if len(zeroLoc) == 0:
            return bool(
                np.all(
                    [
                        (hkl[0] + hkl[1]) % 2 == 0,
                        (hkl[0] + hkl[2]) % 2 == 0,
                        (hkl[1] + hkl[2]) % 2 == 0,
                    ]
                )
            )
        return False

    def indexWithUB(
        self,
        inputCrystalID,
        outputCrystalID,
        UB,
        referenceID,
        indexingTolerance=0.03,
        angleTolerance=3.5,
    ) -> int:
        refIndex = self.findIndexFromRefID(referenceID)
        invUB = np.linalg.inv(UB)
        count = 0

        for row in range(self.npk):
            if self.crystalID[row] == inputCrystalID:
                Q = self.Q[row] / (2 * np.pi)
                hkl = np.dot(invUB, Q)
                if row == refIndex:
                    count += 1
                    self.hkl[row] = hkl
                    if outputCrystalID is not None:
                        self.crystalID[row] = outputCrystalID
                else:
                    dif = np.average(np.absolute(hkl - np.around(hkl)))
                    if np.all([(dif <= indexingTolerance), self.fd3mReflectionCondition(hkl)]):
                        count += 1
                        if outputCrystalID is not None:
                            self.hkl[row] = hkl
                            self.crystalID[row] = outputCrystalID
                            self.beta[row] = self.angleBetweenVectors(self.Q[refIndex], self.Q[row])
                            self.calcBeta[row] = self.angleBetweenVectors(
                                self.hkl[refIndex], self.hkl[row]
                            )

        if outputCrystalID is not None:
            self.resetPositions(crystalID=outputCrystalID)
        return count

    def CreatePeaksWSAndSave(self, outputCrystalID: int, output_path: str | Path) -> None:
        """Create an indexed peaks workspace for *outputCrystalID* and save the UB.

        Args:
            outputCrystalID: 1-based crystal index in ``self.UBList``.
            output_path: Full path (including filename) for the ISAW ``.mat``
                UB file.  The parent directory must already exist.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        outWS = f"snapwrap_PKS_{self.runNumber}_UB{outputCrystalID}"
        CloneWorkspace(InputWorkspace=self.peaksWS, OutputWorkspace=outWS)
        ClearUB(Workspace=outWS)

        UB = self.UBList[outputCrystalID - 1]
        UBList = [
            UB[0, 0], UB[0, 1], UB[0, 2],
            UB[1, 0], UB[1, 1], UB[1, 2],
            UB[2, 0], UB[2, 1], UB[2, 2],
        ]

        SetUB(Workspace=outWS, a=3.567, b=3.567, c=3.567, UB=UBList)
        IndexPeaks(PeaksWorkspace=outWS, Tolerance=0.05)
        SaveIsawUB(InputWorkspace=outWS, Filename=str(output_path))
        print(f"UB saved to {output_path}")

    def UBStandardOrient(self, crystalID: int) -> None:
        """Impose the convention that the diamond *a*-axis points upstream."""
        a = 3.567
        ast = 1 / a
        UB = self.UBList[crystalID - 1]
        print(f"\nStandardising UB for crystal {crystalID}")
        print(UB)

        B = np.array([[ast, 0.0, 0.0], [0.0, ast, 0.0], [0.0, 0.0, ast]])
        Binv = np.linalg.inv(B)
        U = np.dot(UB, Binv)
        a_vecs = np.zeros([3, 3])
        for ax in range(3):
            e = np.zeros(3); e[ax] = 1.0
            a_vecs[ax, :] = np.dot(UB, e) / np.linalg.norm(np.dot(UB, e))

        zDot = np.array([np.dot(a_vecs[i, :], [0, 0, 1]) for i in range(3)])
        zMax = np.amax(np.absolute(zDot))
        k = np.where(np.absolute(zDot) == zMax)[0][0]
        anti = zDot[k] <= 0

        def _rot(deg, axis):
            R = cartRotDeg(deg, axis)
            RB = np.dot(R, B)
            return np.dot(U, RB)

        if k == 0:
            UB = UB if anti else _rot(180, [0, 1, 0])
        elif k == 1:
            UB = _rot(90, [0, 0, 1]) if anti else _rot(-90, [0, 0, 1])
        elif k == 2:
            UB = _rot(-90, [0, 1, 0]) if anti else _rot(90, [0, 1, 0])

        self.UBList[crystalID - 1] = UB
        print(f"Crystal {crystalID} standard UB:")
        print(UB)


# ---------------------------------------------------------------------------
# Main UB-finding algorithm
# ---------------------------------------------------------------------------

def findDiamUB(pkInfo: peakInfo) -> None:
    """Find the two best-fitting diamond UB matrices in *pkInfo*.

    Runs the Jacobsen search twice — first for diamond 1 (all candidate
    reflections), then for diamond 2 (reflections *not* indexed by diamond 1).
    The two UB matrices are appended to ``pkInfo.UBList`` in discovery order
    and then standardised so that the *a*-axis points upstream.

    Args:
        pkInfo: A freshly constructed :class:`peakInfo` object (all peaks
            have ``crystalID == 0``).
    """
    ang_tol = 1.5
    hkl_tol = 0.05

    # ── Diamond 1 ──────────────────────────────────────────────────────────
    guessDiamIndx(pkInfo, inputCrystalID=0, outputCrystalID=-1, dSpacingTolerance=0.03)
    allDiamRefs, nDiamRefs = pkInfo.countID(-1)
    pkInfo.totalDiamondReflections = nDiamRefs
    print(f"Out of {pkInfo.npk} total reflections, {nDiamRefs} match diamond d-spacings")

    if nDiamRefs <= 2:
        print("Insufficient available reflections to calculate any diamond UB!")
        return

    pkInfo.printPeaks(crystalID=-1)

    maxIndexed = 0
    bestUB1 = None
    bestPair: list[int] = []
    for diamond in allDiamRefs:
        UB, nIndexed, seedPair = pkInfo.indexToReferenceReflection(
            inputCrystalID=-1,
            referenceID=diamond,
            angleTolerance=ang_tol,
            indexingTolerance=hkl_tol,
        )
        if nIndexed > maxIndexed:
            maxIndexed = nIndexed
            bestPair = seedPair
            bestUB1 = UB

    if bestUB1 is None:
        print("No UB found for diamond 1.")
        return

    print(f"Diamond 1: best pair {bestPair}, {maxIndexed} peaks indexed")
    print(bestUB1)

    pkInfo.resetCrystal()
    pkInfo.indexWithUB(
        inputCrystalID=0,
        outputCrystalID=1,
        UB=bestUB1,
        referenceID=bestPair[0],
        indexingTolerance=hkl_tol,
        angleTolerance=ang_tol,
    )
    pkInfo.resetPositions(1)
    pkInfo.UBList.append(bestUB1)

    # ── Diamond 2 ──────────────────────────────────────────────────────────
    print("\nSearching for second diamond...")

    guessDiamIndx(pkInfo, inputCrystalID=0, outputCrystalID=-1, dSpacingTolerance=0.03)
    diamRefIDs, nDiam = pkInfo.countID(-1)
    print(f"Out of {pkInfo.npk} remaining reflections, {nDiam} match diamond d-spacings")

    if nDiam <= 2:
        print("Insufficient available reflections to calculate second diamond UB!")
        return

    pkInfo.printPeaks(crystalID=-1)

    maxIndexed2 = 0
    bestUB2 = None
    bestPair2: list[int] = []
    for diamond in diamRefIDs:
        UB, nIndexed, seedPair = pkInfo.indexToReferenceReflection(
            inputCrystalID=-1,
            referenceID=diamond,
            angleTolerance=ang_tol,
            indexingTolerance=hkl_tol,
        )
        if nIndexed > maxIndexed2:
            maxIndexed2 = nIndexed
            bestPair2 = seedPair
            bestUB2 = UB

    if bestUB2 is None:
        print("No UB found for diamond 2.")
        return

    pkInfo.UBList.append(bestUB2)
    print(f"Diamond 2: best pair {bestPair2}, {maxIndexed2} peaks indexed")
    print(bestUB2)

    # ── Re-index with both UBs ─────────────────────────────────────────────
    pkInfo.resetCrystal()
    nIdx1 = pkInfo.indexWithUB(
        inputCrystalID=0,
        outputCrystalID=1,
        UB=bestUB1,
        referenceID=bestPair[0],
        indexingTolerance=hkl_tol,
        angleTolerance=ang_tol,
    )
    pkInfo.resetPositions(1)

    nIdx2 = pkInfo.indexWithUB(
        inputCrystalID=0,
        outputCrystalID=2,
        UB=bestUB2,
        referenceID=bestPair2[0],
        indexingTolerance=hkl_tol,
        angleTolerance=ang_tol,
    )
    pkInfo.resetPositions(2)

    pkInfo.printPeaks()
    total = pkInfo.totalDiamondReflections
    print(f"{nIdx1} indexed to crystal 1, {nIdx2} indexed to crystal 2")
    if total > 0:
        print(
            f"{nIdx1 + nIdx2} / {total} total diamond reflections indexed "
            f"({100 * (nIdx1 + nIdx2) / total:.1f}%)"
        )

    # ── Standardise orientations ───────────────────────────────────────────
    pkInfo.UBStandardOrient(1)
    pkInfo.UBStandardOrient(2)


# ---------------------------------------------------------------------------
# Supporting algorithms (unchanged from original)
# ---------------------------------------------------------------------------

def guessDiamIndx(
    pkInfo: peakInfo,
    inputCrystalID: int,
    outputCrystalID: int,
    dSpacingTolerance: float = 0.01,
) -> None:
    """Assign initial HKL guesses by matching peak d-spacings to known diamond reflections."""
    dref = np.array([2.0593, 1.2611, 1.0754, 0.8917, 0.8183, 0.7281, 0.6305, 0.6029])
    href = np.array(
        [[-1, 1, 1], [-2, 2, 0], [-3, 1, 1], [-4, 0, 0], [-3, 3, 1], [-4, 2, 2], [-4, 4, 0], [-5, 3, 1]]
    )

    for row in range(pkInfo.npk):
        if pkInfo.crystalID[row] == inputCrystalID:
            reltol = dSpacingTolerance * pkInfo.d[row]
            delta = np.absolute(dref - pkInfo.d[row])
            hits = np.where(delta < reltol)[0]
            n_hits = hits.size
            if n_hits == 0:
                pkInfo.hkl[row, :] = [0, 0, 0]
            elif n_hits > 1:
                best_idx = hits[np.argmin(delta[hits])]
                logger.warning(
                    f"Multiple d-spacing matches for reflection {row} (d={pkInfo.d[row]:.4f}). "
                    f"Choosing closest reference d={dref[best_idx]:.4f} (href={href[best_idx]}). "
                    f"Reduce dSpacingTolerance to avoid ambiguity if needed."
                )
                pkInfo.hkl[row, :] = href[best_idx, :]
                pkInfo.crystalID[row] = outputCrystalID
            else:
                hit = hits[0]
                pkInfo.hkl[row, :] = href[hit, :]
                pkInfo.crystalID[row] = outputCrystalID


def jacobsen(
    h1: np.ndarray,
    Xm_1: np.ndarray,
    h2: np.ndarray,
    Xm_2: np.ndarray,
) -> np.ndarray:
    """Compute a UB matrix from two indexed reflections.

    Implementation of the method in R.A. Jacobsen, *Z. Kristallogr.* **212**,
    99–102 (1997), adapted for the Mantid 2π convention.

    Args:
        h1: Miller indices of first reflection (3-vector).
        Xm_1: Q-lab coordinates of first reflection (3-vector, Mantid 2π convention).
        h2: Miller indices of second reflection.
        Xm_2: Q-lab coordinates of second reflection.

    Returns:
        3×3 UB matrix (Mantid convention: ``UB · h = Q / 2π``).
    """
    if np.array_equal(h1, h2):
        return np.zeros((3, 3))

    pi = np.pi
    a = 3.567
    ast = 2 * pi / a

    B = np.array([[ast, 0.0, 0.0], [0.0, ast, 0.0], [0.0, 0.0, ast]])

    Xm_g = np.cross(Xm_1, Xm_2)
    Xm = np.transpose(np.array([Xm_1, Xm_2, Xm_g]))

    Xa_1 = np.dot(B, h1)
    Xa_2 = np.dot(B, h2)
    Xa_g = np.cross(Xa_1, Xa_2)
    Xa = np.transpose(np.array([Xa_1, Xa_2, Xa_g]))

    R = np.dot(Xa, np.linalg.inv(Xm))
    U = np.linalg.inv(R)
    UB = np.dot(U, B)
    return UB / (2 * np.pi)


def UBStandardOrient(UB: np.ndarray) -> np.ndarray:
    """Return a copy of *UB* reoriented so the diamond *a*-axis points upstream.

    Module-level convenience wrapper; equivalent to
    :meth:`peakInfo.UBStandardOrient` but operates on a bare numpy array.
    """
    a = 3.567
    ast = 2 * np.pi / a
    B = np.array([[ast, 0.0, 0.0], [0.0, ast, 0.0], [0.0, 0.0, ast]])
    U = np.dot(UB, np.linalg.inv(B))

    a_vecs = np.zeros([3, 3])
    for ax in range(3):
        e = np.zeros(3); e[ax] = 1.0
        a_vecs[ax, :] = np.dot(UB, e) / np.linalg.norm(np.dot(UB, e))

    zDot = np.array([np.dot(a_vecs[i, :], [0, 0, 1]) for i in range(3)])
    zMax = np.amax(np.absolute(zDot))
    k = np.where(np.absolute(zDot) == zMax)[0][0]
    anti = zDot[k] <= 0

    def _rot(deg, axis):
        R = cartRotDeg(deg, axis)
        return np.dot(U, np.dot(R, B))

    if k == 0:
        return UB if anti else _rot(180, [0, 1, 0])
    elif k == 1:
        return _rot(90, [0, 0, 1]) if anti else _rot(-90, [0, 0, 1])
    else:
        return _rot(-90, [0, 1, 0]) if anti else _rot(90, [0, 1, 0])


def cartRotDeg(ang: float, vect: list | np.ndarray) -> np.ndarray:
    """Return a rotation matrix for *ang* degrees about *vect*."""
    t = np.radians(ang)
    v = np.asarray(vect, dtype=float)
    v = v / np.linalg.norm(v)
    ux, uy, uz = v
    c, s = np.cos(t), np.sin(t)
    return np.array(
        [
            [c + ux**2 * (1 - c),       ux * uy * (1 - c) - uz * s, ux * uz * (1 - c) + uy * s],
            [uy * ux * (1 - c) + uz * s, c + uy**2 * (1 - c),       uy * uz * (1 - c) - ux * s],
            [uz * ux * (1 - c) - uy * s, uz * uy * (1 - c) + ux * s, c + uz**2 * (1 - c)],
        ]
    )


def m3mEquiv(hkl: np.ndarray) -> np.ndarray:
    """Return all unique m-3m symmetry-equivalent Miller indices for *hkl*."""
    h, k, l = hkl[0], hkl[1], hkl[2]
    all_hkl = np.reshape(
        [
            h,  k,  l,  -h, -k,  l,  -h,  k, -l,   h, -k, -l,
            k,  h, -l,  -k, -h, -l,   k, -h,  l,  -k,  h,  l,
            l,  h,  k,   l, -h, -k,  -l, -h,  k,  -l,  h, -k,
           -l,  k,  h,  -l, -k, -h,   l,  k, -h,   l, -k,  h,
            k,  l,  h,  -k,  l, -h,   k, -l, -h,  -k, -l,  h,
            h, -l,  k,  -h, -l, -k,  -h,  l,  k,   h,  l, -k,
           -h, -k, -l,   h,  k, -l,   h, -k,  l,  -h,  k,  l,
           -k, -h,  l,   k,  h,  l,  -k,  h, -l,   k, -h, -l,
           -l, -h, -k,  -l,  h,  k,   l,  h, -k,   l, -h,  k,
            l, -k, -h,   l,  k,  h,  -l, -k,  h,  -l,  k, -h,
           -k, -l, -h,   k, -l,  h,  -k,  l,  h,   k,  l, -h,
           -h,  l, -k,   h,  l,  k,   h, -l, -k,  -h, -l,  k,
        ],
        (48, 3),
    )
    lab = -np.ones(48, dtype=int)
    nlab = -1
    for i in range(48):
        if lab[i] == -1:
            nlab += 1
            lab[i] = nlab
            for j in range(i + 1, 48):
                if np.linalg.norm(all_hkl[i] - all_hkl[j]) == 0:
                    lab[j] = lab[i]
    eqvs = np.zeros((nlab + 1, 3), dtype=int)
    for i in range(nlab + 1):
        k = np.where(lab == i)[0]
        eqvs[i, :] = all_hkl[k[0], :]
    return eqvs
