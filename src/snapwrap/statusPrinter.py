# to tidy up the code in utils.reduce I've pulled out some print statements into functions here
from mantid.kernel import PhysicalConstants
import snapwrap.snapStateMgr as ssm
import numpy as np

def _cycleRemedy(details):
    """Extra remedy line when a calibration was withheld for cycle reasons.

    Without this the only advice on offer is "proceed without a calibration",
    which throws away a perfectly good calibration whose only fault is being
    from another cycle -- a strictly worse outcome than using it knowingly.
    """
    if not isinstance(details, dict):
        return ""

    statusDetail = details.get("statusDetail") or ""
    cycleRelated = (
        "out of cycle" in statusDetail
        or "cycle could not be established" in statusDetail
    )
    if not cycleRelated:
        return ""

    return (
        '\n    3. Set "requireSameCycle = False" to use the existing '
        "calibration from another cycle\n"
        "       (the override is recorded in the calibration home's "
        ".logs/cycle_override_log.jsonl)"
    )


def printWarning(warningType,runNumber,details=None):

    snapHome = ssm.SNAPHome()
    if warningType == 'noDifcal':

        print(f"""
ERROR: NO VALID DIFFRACTION CALIBRATION FOUND.
Reason: {details['statusDetail']}

To proceed either::
    1. Run a diffraction calibration or
    2. Set "continueNoDifcal = True" to proceed with diagnostic reduction{_cycleRemedy(details)}

INFO:
    - Calibration home: {snapHome.calib}
    - StateID: {ssm.stateDef(runNumber)[0]}
    - State Definition:""")
        
        stateDict = ssm.stateDef(runNumber)[1]
        for key in stateDict:
            print(f"        {key}: {stateDict[key]}")


    elif warningType == 'noNormcal':

        print(f"""
ERROR: NO NORMALISATION CALIBRATION FOUND.
Reason: {details['statusDetail']}

To proceed either::
    1. Run a normalisation calibration or
    2. Set "continueNoVan = True" to proceed with diagnostic reduction using artificial normalisation
    3. Set "noNorm = True" to proceed without any normalisation{_cycleRemedy(details).replace("    3. Set", "    4. Set")}

INFO:
    - Calibration home: {snapHome.calib}
    - StateID: {ssm.stateDef(runNumber)[0]}
    - State Definition:""")
        
        stateDict = ssm.stateDef(runNumber)[1]
        for key in stateDict:
            print(f"        {key}: {stateDict[key]}")

        
        
def citation():
    print("\nIf you use SNAPRed or snapwrap in your work please cite:\n")
    print("SNAPRed: Reduction of multidimensional neutron time-of-flight diffraction data")
    print("M. Guthrie, M. Walsh, K. Travis, R. Boston, D. Caballero, D. Dinger, G. ElsarBoukh, J. Hetrick, A.T. Savici and P. Peterson")
    print("Software X, 33, 102464 (2026)")
    print("https://doi-org.ornl.idm.oclc.org/10.1016/j.softx.2025.102464\n")
    print("\nPlease report any bugs at https://github.com/neutrons/SNAPWrap/issues")
    print("(or email Malcolm Guthrie at guthriem@ornl.gov)")

def printStatus(status):
    
    ingredients = status["ingredients"]
    stateID = status["stateID"]
    stateDict = status["stateDict"]
    allPixelGroups = status["allPixelGroups"]
    calibrationRecord = status["calibrationRecord"]
    calibrationPath = status["calibrationPath"]
    normalizationRecord = status["normalizationRecord"]
    normalizationPath = status["normalizationPath"]
    # runNumber = status["runNumber"]
    pixelMasks = status["pixelMasks"]
    binMaskList = status["binMaskList"]
    continueNoDifcal = status["continueNoDifcal"]
    continueNoVan = status["continueNoVan"]
    noNorm = status["noNorm"]

    snapHome = ssm.SNAPHome()

    print(f"""
SNAPRed reduction status:
- Run Number: {ingredients.runNumber}
- ID: {stateID}
            """)
    if calibrationRecord.version==0 and continueNoDifcal:
        print("""
    WARNING: DIAGNOSTIC MODE! DEFAULT GEOMETRY USED.
        """)
    else:
        print(f"""- Calibration: home: {snapHome.calib}
- difcal version: {calibrationRecord.version} runNumber: {calibrationRecord.runNumber}
- comment: {calibrationRecord.indexEntry.comments}""")

    if continueNoVan:
        print("""                         
    WARNING: DIAGNOSTIC MODE! VANADIUM CORRECTION NOT USED
    DATA WILL BE ARTIFICIALLY NORMALISED BY DIVISION BY BACKGROUND.
            """)
    elif noNorm:
        print("""                         
    WARNING: DIAGNOSTIC MODE! VANADIUM CORRECTION NOT USED
    DATA WILL BE UNNORMALISED.
            """)
    else:
        print(f"""- normCal version: {normalizationRecord.version} runNumber: {normalizationRecord.runNumber}
- comment: {normalizationRecord.indexEntry.comments}
""")

    #optional arguments provided...

    if pixelMasks not in ('none', []):
        print(f"""
    Mask workspace(s) specified: {pixelMasks}
        """)

    if binMaskList != []:
        print(f"""
    Bin Mask workspace(s) specified: {binMaskList}
        """)

def completionMessage(status):

    ingredients = status["ingredients"]
    stateID = status["stateID"]
    stateDict = status["stateDict"]
    allPixelGroups = status["allPixelGroups"]

    print(f"""
Reduction COMPLETE

- Run Number: {ingredients.runNumber}

- state: 
    - ID: {stateID},
    - definition: {stateDict}
    - Pixel Groups processed: {allPixelGroups}

""")
    
def verboseStatus(Config, instrumentState, ingredients):

    print("\nINSTRUMENT PARAMETERS")
    print(f"- Calib.home: {Config['instrument.calibration.home']}")
    # print("\nParams in SNAPInstPrm:")
    print("- L1: ",instrumentState.instrumentConfig.L1)
    print("- L2: ",instrumentState.instrumentConfig.L2)
    L = instrumentState.instrumentConfig.L1+instrumentState.instrumentConfig.L2
    print("- bandwidth: ",instrumentState.instrumentConfig.bandwidth)
    print("- lowWavelengthCrop: ",instrumentState.instrumentConfig.lowWavelengthCrop)

    # print("\nParams in application.yml")
    print("- low d-Spacing crop: ",Config["constants.CropFactors.lowdSpacingCrop"])
    print("- high d-Spacing crop: ",Config["constants.CropFactors.highdSpacingCrop"])

    # print("\nParams from state")
    wav = instrumentState.detectorState.wav
    print("- Central wavelength: ",wav)

    print("\n")
    bandwidth = instrumentState.instrumentConfig.bandwidth
    lowWavelengthCrop = instrumentState.instrumentConfig.lowWavelengthCrop
    lamMin = instrumentState.particleBounds.wavelength.minimum
    lamMax = instrumentState.particleBounds.wavelength.maximum
    tofMin = instrumentState.particleBounds.tof.minimum
    tofMax = instrumentState.particleBounds.tof.maximum
    
    print(f"- wavelength limits: {lamMin:.4f}, {lamMax:.4f}")
    # print(f"- TOF limits: {tofMin:.1f}, {tofMax:.1f}")

    # some tests to confirm that these numbers are being calculated as expected
    convFactor = Config["constants.m2cm"] * PhysicalConstants.h / PhysicalConstants.NeutronMass

#         print(f""" SOME TESTING...
# calculated lamMin is {wav - bandwidth/2 + lowWavelengthCrop}:.4f, {}
# """)

    assert lamMin == wav - bandwidth/2 + lowWavelengthCrop
    assert lamMax == wav + bandwidth/2
    # print(f"calculated tof limits: {lamMin*L/convFactor:.1f}, {lamMax*L/convFactor:.1f}")
    assert tofMin == lamMin*L/convFactor
    assert tofMax == lamMax*L/convFactor
    # calcTofM
    # calcTofMax

    pgs = ingredients.pixelGroups #ingredients.pixelGroups is a list of pgs
    print("\nPIXEL GROUP PARAMETERS")
#         print(f"""TOF limits {pgs[0].timeOfFlight.minimum:.1f} - {pgs[0].timeOfFlight.maximum:.1f}
# Requested Bins across halfWidth: {pgs[0].nBinsAcrossPeakWidth}""")

    for pgs in ingredients.pixelGroups:     #ingredients.pixelGroups is a list of pgs
        
        #pgs are pixel group classes, they are iterable with each item in the class are
        #tuples with the first value of the tuple being its name

        print(f"""
-----------------------------------------------
pixel grouping scheme: {pgs.focusGroup.name}
with {len(pgs.pixelGroupingParameters)} subGroup(s)
                """)
        dMins = []
        dMaxs = []
        dBins = []
        L2s = []
        twoThetas = []

        for subGroup in pgs.pixelGroupingParameters:

            params = pgs.pixelGroupingParameters[subGroup]
            dMaxs.append(params.dResolution.maximum)
            dBins.append(params.dRelativeResolution/pgs.nBinsAcrossPeakWidth)
            dMins.append(params.dResolution.minimum)
            L2s.append(params.L2)
            twoThetas.append(params.twoTheta)

        twoThetasDeg = [180.0*x/np.pi for x in twoThetas]
        cropDMins = [d+Config["constants.CropFactors.lowdSpacingCrop"] for d in dMins]
        cropDMaxs = [d-Config["constants.CropFactors.highdSpacingCrop"] for d in dMaxs]
        #reduce precision for pretty printing



        dMaxs = [round(num,4) for num in dMaxs]
        dMins = [round(num,4) for num in dMins]
        dBins = [round(num,4) for num in dBins]
        cropDMins = [round(num,4) for num in cropDMins]
        cropDMaxs = [round(num,4) for num in cropDMaxs]    

        L2s = [round(num,4) for num in L2s]
        twoThetas = [round(num,4) for num in twoThetas]
        twoThetasDeg = [round(num,1) for num in twoThetasDeg]

        just = 20
        print("L2 (m)".ljust(just),L2s)
        print("twoTheta (rad)".ljust(just),twoThetas)
        print("twoTheta (deg)".ljust(just),twoThetasDeg)
        print("dMin (Å)".ljust(just),dMins)
        print("dMax (Å)".ljust(just),dMaxs)
        print("dMin (Å) - cropped".ljust(just),cropDMins)
        print("dMax (Å) - cropped".ljust(just),cropDMaxs)
        print("dBin".ljust(just),dBins)
