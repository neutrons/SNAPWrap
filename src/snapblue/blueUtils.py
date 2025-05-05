# some helpful functions for use with SNAPRed script version
import yaml
from mantid.simpleapi import *
from mantid.kernel import PhysicalConstants
import numpy as np
import matplotlib.pyplot as plt
import json
import os
import shutil
import importlib
import copy


import snapblue.SNAPStateMgr as ssm
importlib.reload(ssm)
import snapblue.blueIO as blueIO
importlib.reload(blueIO)
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# SNAPRed imports
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
from snapred.backend.dao.ingredients.ArtificialNormalizationIngredients import ArtificialNormalizationIngredients
from snapred.backend.dao.request import ReductionExportRequest
from snapred.backend.dao.request.ReductionRequest import ReductionRequest
from snapred.backend.data.DataFactoryService import DataFactoryService
from snapred.backend.error.ContinueWarning import ContinueWarning
from snapred.backend.recipe.ReductionRecipe import ReductionRecipe
from snapred.backend.service.ReductionService import ReductionService
from snapred.backend.dao.indexing.Versioning import Version, VersionState
from snapred.meta.mantid.WorkspaceNameGenerator import WorkspaceNameGenerator as wng
from snapred.meta.Config import Config
# from snapred.backend.data import LocalDataService as lds
from snapred.backend.dao.request.FarmFreshIngredients import FarmFreshIngredients
from snapred.backend.service.SousChef import SousChef

class globalParams:

# This class holds a set of parameters that will be applied during reduction
# these are stored in a YAML file and can be changed by specifying alternate
# YAML files

    def __init__(self,defaultYML):

        with open(defaultYML,'r') as file:
            ymlIn = yaml.safe_load(file)

        self.useLiteMode = ymlIn["useLiteMode"]
        self.pixelMasks = ymlIn["pixelMasks"]
        self.keepUnfocussed = ymlIn["keepUnfocussed"]
        self.convertUnitsTo = ymlIn["defaultUnfocussedWorkspaceUnits"]
        self.AN_smoothingParameter = ymlIn["artificialNorm"]["smoothingParameter"]
        self.AN_decreaseParameter = ymlIn["artificialNorm"]["decreaseParameter"]
        self.AN_lss = ymlIn["artificialNorm"]["lss"]

        return
    
def makeDefaultYML(outputYML):

    #dictionary of params
    params = {"useLiteMode": True,
              "pixelMasks": [],
              "keepUnfocussed": False,
              "defaultUnfocussedWorkspaceUnits": "dSpacing"
              }
    
    with open(outputYML, 'w') as file:
        yaml.dump(params, file)

    print('wrote: ',outputYML)

def makeSEE(outputName,SEEDirectory):

    #TODO: make function to initialise SEE (=  Sample Environment Equipment) definition with mandatory inputs
    ymlOut = SEEDirectory + outputName
    return ymlOut 

def loadSEE(seeDefinition,SEEFolder):

    #loads Parameters from SEE definition as a dictionary

    #TODO: add this to application.yml
    inputYML = f"{SEEFolder}/{seeDefinition}.yml"

    #TODO: manage errors when file doesn't exist etc.
    with open(inputYML,'r') as file:
            seeDict = yaml.safe_load(file)

    return seeDict

def purgeNormalisation(isLite=True,purge=False):
    #this removes all existing normalization folders. User with caution!!!!!!!!!!!
    allAvailableStates = ssm.availableStates()


    print("Existing Normalization calibrations:\n")
    for stateID in allAvailableStates:
        nrmcal = ssm.checkCalibrationStatus(stateID,isLite,calType='normcal')
        if nrmcal["isCalibrated"]:
            nrmDir = os.path.dirname(nrmcal['indexPath'])
            print(f"{nrmDir}")
                  
    if purge:
        doubleCheck = input("Listed folders will be deleted. Enter \"yes\" if you are very sure you are OK with this!")
        if doubleCheck == 'yes':
            nDeleted = 0
            for stateID in allAvailableStates:
                nrmcal = ssm.checkCalibrationStatus(stateID,isLite,calType='normcal')
                if nrmcal["isCalibrated"]:
                    nrmDir = os.path.dirname(nrmcal['indexPath'])
                    shutil.rmtree(nrmDir)
                    nDeleted += 1

            print(f"Done. {nDeleted} folders were deleted")
    else:
        print("\nRe-run with purge=True to actually delete these")

def indexStates(isLite=True):
    #prints an index of existing states and their calibration statuses
    

    allAvailableStates = ssm.availableStates()
    

    outputStrings = []
    statuses = []
    for stateID in allAvailableStates:

        stateDict = ssm.pullStateDict(stateID)
        difcal = ssm.checkCalibrationStatus(stateID,isLite,calType='difcal')
        nrmcal = ssm.checkCalibrationStatus(stateID,isLite,calType='normcal')

        # parse possible scenarios
        if difcal["isCalibrated"] and nrmcal["isCalibrated"]:
            calStatus = '*CALIB*'
        if not difcal["isCalibrated"] or not nrmcal["isCalibrated"]:
            calStatus = "PARTIAL"
        if not difcal["isCalibrated"] and not nrmcal["isCalibrated"]:
            calStatus = "UNCALIB"

        desc = ssm.autoStateName(stateDict)
        nDifcal = difcal['numberCalibrations']

        if difcal['latestCalibration'] != "never":

            latestDifcalRun = difcal['mostRecentCalib']['runNumber']
        else:
            latestDifcalRun = ""

        nNrmcal = nrmcal['numberCalibrations']

        if nrmcal['latestCalibration'] != "never":
            latestNrmcalRun = nrmcal['mostRecentCalib']['runNumber']
            latestNrmcalBack = nrmcal["backgroundRunNumber"]
        else:
            latestNrmcalRun = ""
            latestNrmcalBack = ""

        outputString = (f"{stateID}|{desc}|"
                        f" {calStatus} |"
                        f"     {nDifcal}     | {latestDifcalRun.rjust(6)} |"
                        f"     {nNrmcal}     | {latestNrmcalRun.rjust(6)} | {latestNrmcalBack.rjust(6)} |"
                            )
        statuses.append(calStatus) 
        outputStrings.append(outputString)

    #output in order of calibration status...
    print("\n StateID        | Desc.                   | Status  |No. difcals| latest |No. nrmcals| latest | (back) |")
    for i,string in enumerate(outputStrings):
        if statuses[i] == "UNCALIB":
            print(string) 

    for i,string in enumerate(outputStrings):
        if statuses[i] == "PARTIAL":
            print(string) 

    for i,string in enumerate(outputStrings):
        if statuses[i] == "*CALIB*":
            print(string) 

def file(nameKeys,operation="add",cabinetName="File_Cabinet"):

#creates a Workspace Group called cabinetName.
# if operation = "add" workspaces with specified nameKeys in their name will be added to group
# if operation = "remove" workspaces with specified nameKeys in their name will be removed from group
# if operation = "empty" cabinet will be emptied and removed
 
    if operation.lower() == "empty":
        groupWS = mtd[cabinetName]
        UnGroupWorkspace(groupWS)
        return

    # print("nameKeys: ",nameKeys)
    if type(nameKeys) != list:
        print("ERROR: name keys must be a list")
        return

    allWorkspaces = mtd.getObjectNames()
    toBeFiled = []
    for wsName in allWorkspaces:
        for key in nameKeys:
            if key.lower() in wsName.lower():
                toBeFiled.append(wsName)

    if operation.lower() == "add":
        print(f"{len(toBeFiled)} workspaces will be added to {cabinetName}")
        # check if filing cabinet exists already 
        if mtd.doesExist(cabinetName):
            wsGroup = mtd[cabinetName]
            cabinetContents = wsGroup.getNames()
            for wsName in toBeFiled:
                wsGroup.add(wsName)

        else:
            GroupWorkspaces(InputWorkspaces=toBeFiled,
                        OutputWOrkspace=cabinetName)

    if operation.lower() == "remove":
        if not mtd.doesExist(cabinetName):
            print(f"{cabinetName} doesn\'t exist cannot remove from it")
            return
        
        print(f"{len(toBeFiled)} workspaces will be removed from {cabinetName}")
        wsGroup = mtd[cabinetName]
        for wsName in toBeFiled:
            wsGroup.remove(wsName)


    wsGroup = mtd[cabinetName]
    print(f"{cabinetName} has {wsGroup.getNumberOfEntries()} total workspaces")

def resample(sampleFactor=1):

    # function to downsample reduced workspaces

    reducedGroups = blueIO.reducedRuns(exportFormats=[],prefix="reduced_dsp")

    for redGroup in reducedGroups:

        runNumber = redGroup.runNumber
        runDict = redGroup.objectDict
        print(f"Down sampling run: {runNumber} with {len(runDict)} pixel group(s)")

        for pgs in runDict.keys():
            #each key is a pixel group and each pixel group has a list of objects (each is a workspace)
            print(f"processing group {pgs} with {len(runDict[pgs])} associated workspaces")
            for redObj in runDict[pgs]:
                # each redObj corresponds to a mantid workspace containing with reduced data
                print(redObj.redRecord)
                XMin = redObj.xMin
                XMax = redObj.xMax
                Delta = redObj.delta
                print("XMin: ",XMin)
                print("XMax: ",XMax)
                print("Delta: ",Delta)
                dsDelta = Delta/sampleFactor #TODO: worry about this sign...
                print("DS Delta: ",dsDelta)

                print(f"inputWorkspace is: {redObj.wsName}")
                outWSName = f"resampled_dsp_{redObj.suffix}"
                print(f"outputWorkspace is: {outWSName}")
                RebinRagged(InputWorkspace=redObj.wsName,
                            OutputWorkspace=outWSName,
                            XMin = XMin,
                            XMax = XMax,
                            Delta = dsDelta,
                            )

def exportData(exportFormats=['gsa','xye','csv'],
               prefix='reduced_dsp',
               latestOnly=True,
               gsaInstPrm=True):
    #creates reducedGroups and then exports these using the requested export formats

    reducedGroups = blueIO.reducedRuns(exportFormats,prefix)
    
    blueIO.exportReducedGroups(reducedGroups,latestOnly,gsaInstPrm)

def workspaceHandles(prefix="reduced_dsp",pgs="bank"):

    #returns a list of redObjects for the requested workspaces

    reducedList = blueIO.reducedRuns([],prefix=prefix)

    handleList = []
    for red in reducedList:
        redObj = red.objectDict[pgs][0]
        handleList.append(redObj)

    if len(handleList) == 0:
        print("no workspaces found. Check your input")
    else:
        print(f"found {len(handleList)} workspaces handles")

    return handleList
    
def confirmIPTS(ipts,comment="SNAPRed/Blue", subNum=1, redType="Scripts"):

    import subprocess

    #TODO: input validation!

    #validate redType
    allowedRedTypes = ["Scripts","CIS","Auto",""]
    if redType not in allowedRedTypes:
        print(f"ERROR: {redType} is not a supported option for redType parameters")
        return
    #check case
    if redType.lower() == "scripts":
        redType = "Scripts"
    if redType.lower() == "cis":
        redType = "CIS"
    if redType.lower() == "auto":
        redType = "Auto"

    
    execArg = [
        "/SNS/SNAP/shared/Malcolm/devel/confirm-data",
        "SNAP",
        f"{ipts}",
        f"{subNum}",
        f"{redType}",
        "-c",
        f"{comment}",
        "-s",
        "Yes"
    ]

    print(execArg)
    subprocess.run(execArg,
                   capture_output=True,
                   check=True,
                   shell=False) 

def findQLogBin(dMin,dBin,dMax,linBin):

    #starting off with an initial dBin will iteratively determine a final dBin that ensures the
    #largest q bin size is <= linbin request. the final dBin will be less than the initial dBin
    
    Nit = 3000
    for i in range(Nit):
        
        f = (Nit-i)/Nit
        dBinTrial = dBin*f
        
        
        N = int((1/dBinTrial)*np.log(dMax/dMin)) 
        maxQBin = (2*np.pi/dMax)*dBinTrial*(1+dBinTrial)**N
        
        # print(f"f: {f:.3f} dBin trial: {dBinTrial:6f} Npt: {N} maxQBin: {maxQBin:.3f}")
        
        dif = maxQBin-linBin
        if dif <= 0:
            break
            
    return dBinTrial

def updateBinForQ(inputIngredients,linBin):

    # Takes input of pixelGroup ingredients, pgs, copies this, then 
    # modifies the original parameters by changing the binning
    # determined via 
    # - pgs.PixelGroupingParameter.dRelativeResolution/pgs.nBinsAcrossPeakWidth
    # to a set of new values (one for each subgroup in each pixel grouping scheme)
    # that will ensure that *after converion to Q-space* the largest Q-bin is equal to
    # the requrested linBin value.
  
    pgs = inputIngredients.pixelGroups
    originalIngredients = copy.deepcopy(pgs)

    for pg in pgs:
        print(f"pgs: {pg.focusGroup.name} with {len(pg.pixelGroupingParameters)} subgroups")
        for subgroup in pg.pixelGroupingParameters:
            params = pg.pixelGroupingParameters[subgroup]
            dMin = params.dResolution.minimum + Config["constants.CropFactors.lowdSpacingCrop"]
            dMax = params.dResolution.maximum - Config["constants.CropFactors.highdSpacingCrop"]
            dBin = params.dRelativeResolution/pg.nBinsAcrossPeakWidth
            print(f"{dMin:.4f} {dBin:.6f} {dMax:.4f} (with final cropping)")
            newdBin = findQLogBin(dMin,dBin,dMax,linBin)
            #overwrite
            params.dRelativeResolution = newdBin*pg.nBinsAcrossPeakWidth

    return originalIngredients,inputIngredients
            
def restoreDBins(redObj,originalIngredients):

    #extract ragged binning params from originalIngredients

    pgName = redObj.pixelGroup.lower()
    for pg in originalIngredients:
        if pg.focusGroup.name.lower() == pgName:
            dMins = []
            dMaxs = []
            dBins = []
            for subgroup in pg.pixelGroupingParameters:
                params = pg.pixelGroupingParameters[subgroup]
                dMin = params.dResolution.minimum + Config["constants.CropFactors.lowdSpacingCrop"]
                dMax = params.dResolution.maximum - Config["constants.CropFactors.highdSpacingCrop"]
                dBin = params.dRelativeResolution/pg.nBinsAcrossPeakWidth
                dMins.append(dMin)
                dMaxs.append(dMax)
                dBins.append(-1*dBin) #ugh...

    if len(dMins) == 0:
        print(f"ERROR: could not match pixelGroupingScheme {pgName} with reduction ingredients")
        return
    else:
        RebinRagged(InputWorkspace=redObj.wsName,
                    Outputworkspace=redObj.wsName,
                    XMin=dMins,
                    XMax=dMaxs,
                    Delta = dBins,
                    FullBinsOnly=True)
        print(f"restored binning on {redObj.wsName}")
        
    return

def propagateDifcal(refRunNumber,isLite=True,propagate=False,includeGuideStatus=True):

    #This will accept a reference Run number, determine a list of all existing 
    # states with equivalent detector positions propagate and their (diff) calibration status
    # if propagate==True, the latest calibration from the state corresponding to 
    # refRunNumber will be propagates to other compatible states as if it's a formal
    # calibration
 
    refStateID,refStateDict = ssm.stateDef(refRunNumber)
    refDetConfig = ssm.detectorConfig(refStateDict,includeGuideStatus)

    # check diffraction calibration status of reference run
    refCalStatus = ssm.checkCalibrationStatus(refStateID,isLite,"difcal")
    # if state is uncalibrated, stop. Nothing to propagate
    if not refCalStatus["isCalibrated"]:
        print("ERROR: Reference State is uncalibrated! Please calibrate or choose a different reference")
        return
    else:
         print(f"""
/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/
propagateDifcal: Utility to copy calibrations
/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/
Origin calibration info
    - Run:  {refRunNumber}
    - State: {refStateID}
    - Detector config: {refDetConfig}
    - calibrated: {refCalStatus['numberCalibrations']} times
    - latest version: {refCalStatus['mostRecentCalib']['version']}           
    """)

    nCompatibleStates = 0
    toPropagateCal = []
    toPropagateState = []
    toPropagateDetConfig = []
    for stateID in ssm.availableStates():
        if stateID != refStateID:
            stateDict = ssm.pullStateDict(stateID) ##
            detConfig = ssm.detectorConfig(stateDict,includeGuideStatus)
            if detConfig == refDetConfig:
                calStatus = ssm.checkCalibrationStatus(stateID,isLite,"difcal")
                toPropagateCal.append(calStatus)
                toPropagateState.append(stateID)
                toPropagateDetConfig.append(detConfig)
                     
                nCompatibleStates += 1

    print(f"\n{nCompatibleStates} state(s) found with matching detector configs\n")

    print("Existing compatible states are:")
    for state in toPropagateState:
        print(state)

    if propagate:
        print("\nThese will be propagated")
        for cal in toPropagateCal:
            ssm.copyDifcal(refCalStatus,cal,propagate)
    else:
        print("\nPropagatation of calibration was not requested")
        
def reload(runNumber,
           all=False,
           unpack=True,
           keepMask=False,
           pixelGroup=None,
           isLite=True):

    r = blueIO.diskObject(runNumber,isLite)
    if not r.isReduced: 
        print(f"WARNING: Run {runNumber} has no reduction record")
    else:
        print(f"Reduction record(s) found, run has been reduced {r.nReduced} times")
        if r.nReduced > 1 and not all:
            print("Only latest reduction will be loaded")
        r.reload(all=False,
             unpack=unpack,
             keepMask=keepMask,
             pixelGroup=pixelGroup,
             )

def autoMask(inputWorkspace,maskType="PE",plotOn=True):

    import snapblue.maskUtils as mut
    importlib.reload(mut)

    if maskType == "PE":

        # convert to image and make mask
        slice = mut.sliceImage(inputWorkspace) #need workspace name here.

        slice.combineMasks=True
        mut.maskGrid(slice,gridWidth=0)
        mut.liLee(slice)
        print(f"{slice.percentMasked:.2f}% of pixels masked")

        if plotOn:
        #show  mask
            maskedImage = slice.image
            #mantid plots masks as the the maxi,mum of colour scale, so need to grab this
            zmax = np.max(maskedImage)
            for indx,val in np.ndenumerate(slice.mask):
                # print(indx,val)
                if val:
                    maskedImage[indx] = zmax

            figName = "masked"
            figContent = maskedImage
            fig, ax = plt.subplots()
            ax.set_title(figName)
            ax.imshow(figContent)
            fig.show()

        # #convert mask back to workspace
        nextMaskWSName = mut.nextMaskWSName()
        a = mut.mask2mantid(slice,inputWorkspace,nextMaskWSName)
        print(f"Mask: {nextMaskWSName} was created")


def reduce(runNumber,
               sampleEnv='none',
               pixelMaskIndex='none',
               YMLOverride='none',
               continueNoDifcal = False,
               continueNoVan = False,
               verbose=False,
               reduceData=True,
               keepUnfocussed=False,
               lambdaCrop=False, #no longer needed TODO: delete
               emptyTrash=True, #remove temporary mantid workspaces at the end of reduction
            #    export=['gsas','xye','ascii'], #file formats to export to. If empty, no export 
               cisMode=False,
               singlePixelGroup=None,
               qsp=False,
               linBin=0.01,
               save=True):

    from mantid import config

    if verbose:
        config.setLogLevel(5, quiet=True)
    else:
        config.setLogLevel(0, quiet=True)


    if cisMode:
        Config._config["cis_mode.enabled"] = True
        Config._config["cis_mode.preserveDiagnosticWorkspaces"] = True

    else:
        Config._config["cis_mode.enabled"] = False

    print("SNAPBlue: gathering reduction ingredients...\n")
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # load reduction params from default yml with option to override 
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    #TODO: update default to final shared repo path

    if YMLOverride == 'none':
        defaultYML = "/SNS/SNAP/shared/code/SNAPBlue/defaultRedConfig.yml" #this will live in repo
    else:
        defaultYML = YMLOverride

    blueGlob = globalParams(defaultYML)

    #set global parameters
    useLiteMode=blueGlob.useLiteMode
    pixelMasks = blueGlob.pixelMasks
    # keepUnfocussed = blueGlob.keepUnfocussed
    convertUnitsTo = blueGlob.convertUnitsTo

    #process continue flags
    continueFlags = ContinueWarning.Type.UNSET #by default do not continue

    if continueNoVan:
        artificialNormalizationIngredients = ArtificialNormalizationIngredients(
        peakWindowClippingSize = Config["constants.ArtificialNormalization.peakWindowClippingSize"],
        smoothingParameter=blueGlob.AN_smoothingParameter,
        decreaseParameter=blueGlob.AN_decreaseParameter,
        lss=blueGlob.AN_lss
        )
        continueFlags = ContinueWarning.Type.MISSING_NORMALIZATION
        
    else:
        artificialNormalizationIngredients = None

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # process input arguments
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    runNumber = str(runNumber)
    SEEFolder = f'{Config["instrument.calibration.home"]}/sampleEnvironmentDefinitions'

    if sampleEnv != 'none':
        seeDict = loadSEE(sampleEnv,SEEFolder)

        if seeDict["masks"]["maskExists"] and (seeDict["masks"]["maskType"]=="static"):
            # TODO: need to separately manage lite versus non lite masks
            # TODO: mantid can't load lite masks ... need to use SNAPRed
            pass

    if pixelMaskIndex != 'none':
        #check that provided value is a list convert if it isn't
        if type(pixelMaskIndex) is not list:
            pixelMaskIndex = [pixelMaskIndex]

        #check that all requested masks actually exist
        for maskIndex in pixelMaskIndex:
            if maskIndex == 0: #account for weird mantid indexing by getting rid of zero 
                maskName = (wng.reductionUserPixelMask().numberTag(1)).build()
            else:
                maskName = (wng.reductionUserPixelMask().numberTag(maskIndex)).build()

            if maskName not in mtd.getObjectNames():
                print(f"ERROR: you requested mask workspace {maskName} but this doesn\'t exist")
                assert False
            pixelMasks.append(maskName)
    
    reductionService = ReductionService()
    timestamp = reductionService.getUniqueTimestamp()

    reductionRequest = ReductionRequest(
        runNumber=runNumber,
        useLiteMode=useLiteMode,
        timestamp=timestamp,
        continueFlags=continueFlags,
        pixelMasks=pixelMasks,
        keepUnfocused=keepUnfocussed,
        convertUnitsTo=convertUnitsTo,
        artificialNormalizationIngredients=artificialNormalizationIngredients
    )

    print(reductionRequest)

    reductionService.validateReduction(reductionRequest)

    # 1. load default grouping workspaces from the state folder 
    groupings = reductionService.fetchReductionGroupings(reductionRequest)

    # allow selection of singlePixelGroup

    if singlePixelGroup is None:
        reductionRequest.focusGroups = groupings["focusGroups"]
    else:
        reductionRequest.focusGroups = []
        for focGroup in groupings["focusGroups"]:
            if singlePixelGroup.lower()==focGroup.name.lower():
                print(f"Setting single focus group: {focGroup.name}")
                reductionRequest.focusGroups.append(focGroup)


    print("request",reductionRequest.focusGroups)

    # 2. Load Calibration (error out if it doesnt exist, comment out if continue anyway)
    # 3. Load Normalization (error out if it doesnt exist, comment out if continue anyway)
    # 3. Load the run data (lite or native)

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # "fetchReductionGroceries" Loads necessary data (e.g. sample neutron data,
    # raw vanadium data, pixel group definitions, DIFCs
    # and pixel masks )
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    groceries = reductionService.fetchReductionGroceries(reductionRequest)

    groceries["groupingWorkspaces"] = groupings["groupingWorkspaces"]

    # print(groceries["inputWorkspace"])
    print("groceries")
    print(groceries)

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    #  Load the metadata i.e. ingredients
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    # 1. load reduction ingredients
    ingredients = reductionService.prepReductionIngredients(reductionRequest, groceries.get("combinedPixelMask",""))
    ingredients.artificialNormalizationIngredients = artificialNormalizationIngredients

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Determine calibration status and process this
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>


    dataFactoryService = DataFactoryService()
    calibrationPath = dataFactoryService.getCalibrationDataPath(
                runNumber, useLiteMode, VersionState.LATEST
            )
    # print(calibrationPath)
    calibrationRecord = dataFactoryService.getCalibrationRecord(
                runNumber, useLiteMode, VersionState.LATEST
            )
    
    if calibrationRecord.version == 0 and not continueNoDifcal:
        print("""         
                 
          - WARNING: NO DIFFRACTION CALIBRATION FOUND. TO PROCEED EITHER:
              1. RUN A DIFFRACTION CALIBRATION OR 
              2. SET "continueNoDifcal = True" TO PROCEED WITH DEFAULT GEOMETRY

            """)
        assert False

    # print(calibrationRecord.version)
    normalizationPath = dataFactoryService.getNormalizationDataPath(
                runNumber, useLiteMode, VersionState.LATEST
            )
    # print(normalizationPath)
    normalizationRecord = dataFactoryService.getNormalizationRecord(
                runNumber, useLiteMode, VersionState.LATEST
            )
    
    if type(normalizationRecord) == None:
        print("""         
                 
          - WARNING: NO VANADIUM FOUND. TO PROCEED EITHER: 
              1. RUN A VANADIUM CALIBRATION OR 
              2. SET "continueNoVan = True" TO USE ARTIFICIAL NORMALISATION

            """)
        
    
    # print(normalizationRecord.version)
    stateID = dataFactoryService.constructStateId(runNumber)


    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Pretty print useful information regarding reduction status
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> 

    allPixelGroups = []
    for ingredient in ingredients:   
        if ingredient[0] == "pixelGroups":
            for item in ingredient[1]:
                allPixelGroups.append(item.focusGroup.name)

    print(f"""
            SNAPRed:

                - Run Number: {ingredients.runNumber}

                - state: 
                    - ID: {stateID[0]},
                    - definition: {stateID[1]}

                - Pixel Groups to process: {allPixelGroups}

            """)
    
    
    
    if calibrationRecord.version==0 and continueNoDifcal:
        print("""

          - WARNING: DIAGNOSTIC MODE! DEFAULT GEOMETRY USED.

              """)
    else:
        print(f"""
          Calibration Status:
            - Diffraction Calibration:
                - .h5 path: {calibrationPath}
                - .h5 version: {calibrationRecord.version}

    """)

    if continueNoVan:
        print("""         
                 
          - WARNING: DIAGNOSTIC MODE! VANADIUM CORRECTION NOT USED
            DATA WILL BE ARTIFICIALLY NORMALISED BY DIVISION BY BACKGROUND.

            """)
    else:
        print(f"""            
                - Normalisation Calibration:
                    - raw vanadium path: {normalizationPath}
                    - raw vanadium version: {normalizationRecord.version}

            """)


    #optional arguments provided...

    if sampleEnv != 'none':
        print(f"""          
            Sample environment was specified.

                - name: {seeDict["name"]}
                - id: {seeDict["id"]}
                - type: {seeDict["type"]}
                - mask: {seeDict["masks"]["maskFilenameList"]} NOT YET IMPLEMENTED
            
            """)

    if pixelMasks != 'none' or []:
        print(f"""
            Mask workspace(s) specified:
        """)
        for mask in pixelMasks:
            print(f"""
                {mask}
                  """)

    #obtain useful values from instrument state

        farmFresh = FarmFreshIngredients(
        runNumber=runNumber,
        useLiteMode=useLiteMode,
        focusGroups=[{"name":"All", "definition":""}], #pixel group irrelevant, so just choose one.
        )
        instrumentState = SousChef().prepInstrumentState(farmFresh)

    if qsp:

        #prior to reduction, need to determine appropriate binning to match requested
        #Q-space binning

        originalIngredients,ingredients = updateBinForQ(ingredients,0.01)

        # for pgs in ingredients.pixelGroups:
        #     print(f"processing pgs: {pgs.focusGroup.name} with {len(pgs.pixelGroupingParameters)} subgroups")
        
        #     for subGroup in pgs.pixelGroupingParameters:
        #         params = pgs.pixelGroupingParameters[subGroup]
        #         dMax = params.dResolution.maximum
        #         dMin = params.dResolution.minimum
        #         dBin = params.dRelativeResolution/pgs.nBinsAcrossPeakWidth

        pgs = ingredients.pixelGroups
        print("UPDATED")
        for pg in pgs:
            print(f"pgs: {pg.focusGroup.name} with {len(pg.pixelGroupingParameters)} subgroups")
            for subgroup in pg.pixelGroupingParameters:
                params = pg.pixelGroupingParameters[subgroup]
                dMin = params.dResolution.minimum
                dMax = params.dResolution.maximum
                dBin = params.dRelativeResolution/pg.nBinsAcrossPeakWidth
                print(f"{dMin:.4f} {dBin:.6f} {dMax:.4f}")


    if reduceData:

        if lambdaCrop:
            # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
            #  Crop data in wavelength space prior to reduction
            #  This was used while troubleshooting spectral edges
            #
            # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

            ConvertUnits(InputWorkspace=groceries["inputWorkspace"],
                        OutputWorkspace=groceries["inputWorkspace"],
                        Target="Wavelength")
            
            CropWorkspace(InputWorkspace=groceries["inputWorkspace"],
                        OutputWorkspace=groceries["inputWorkspace"],
                        XMin = instrumentState.particleBounds.wavelength.minimum,
                        XMax = instrumentState.particleBounds.wavelength.maximum)
            
            ConvertUnits(InputWorkspace=groceries["inputWorkspace"],
                        OutputWorkspace=groceries["inputWorkspace"],
                        Target="TOF")


        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # Execute reduction here
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

        data = ReductionRecipe().cook(ingredients, groceries)
        record = reductionService._createReductionRecord(reductionRequest, ingredients, data["outputs"])

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        #  Save the data
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        if save:
            saveReductionRequest = ReductionExportRequest(
                record=record
            )

            reductionService.saveReduction(saveReductionRequest)

        print(f"""
        Reduction COMPLETE

            - Run Number: {ingredients.runNumber}

            - state: 
                - ID: {stateID[0]},
                - definition: {stateID[1]}

            - Pixel Groups to process: {allPixelGroups}

        """)
    
    if calibrationRecord.version==0 and continueNoDifcal:
        print("""
          - WARNING: DIAGNOSTIC MODE! DEFAULT GEOMETRY USED TO CONVERT UNITS.
              """)
    else:
        print(f"""
          Calibration Status:
            - Diffraction Calibration:
                - .h5 path: {calibrationPath}
                - .h5 version: {calibrationRecord.version}

    """)

    if continueNoVan:
        print("""         
          - WARNING: DIAGNOSTIC MODE! VANADIUM CORRECTION NOT USED
            DATA WILL BE ARTIFICIALLY NORMALISED USING DIVISION BY BACKGROUND
            """)
    else:
        print(f"""            
            - Normalisation Calibration:
                - raw vanadium path: {normalizationPath}
                - raw vanadium version: {normalizationRecord.version}

            """)

    #optional arguments provided...

    if sampleEnv != 'none':
        print(f"""          
            Sample environment was specified.

                - name: {seeDict["name"]}
                - id: {seeDict["id"]}
                - type: {seeDict["type"]}
                - mask: {seeDict["masks"]["maskFilenameList"]} NOT YET IMPLEMENTED
            
            """)

    if pixelMasks != 'none' or []:
        print(f"""
            Mask workspace(s) specified:
        """)
        for mask in pixelMasks:
            print(f"""
                {mask}
                  """)


    if verbose:

        

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

    if reduceData:
        print(data)
        for dat in data:
            print(dat)

    if qsp:
        # blueIO.convertToQ()
        # first generate list of redObjects for this run:

        redWSList = []
        for ws in data["outputs"]:
            redObj = blueIO.redObject(ws)
            if redObj.isReducedDataWorkspace:
                redWSList.append(redObj)
            
        for redObj in redWSList:
            dspName = redObj.wsName
            qspName = dspName.replace("_dsp_","_qsp_")
            ConvertUnits(InputWorkspace=dspName,
                        OutputWorkspace=qspName,
                        Target="MomentumTransfer")

            rebPrm = linBin*np.ones(mtd[qspName].getNumberHistograms())
            RebinRagged(InputWorkspace = qspName,
                        OutputWorkspace= qspName,
                        Delta = rebPrm) #ragged is needed as Qmin/max vary
            
            #lastly, downsample d-space data back to original request
            restoreDBins(redObj,originalIngredients)

    #clean up after myself

    dirty = ["tof_all_lite_raw",
            #  "tof_all_lite_copy",
             "tof_all_copy",
             "tof_all_raw",
             "SNAPLite_grouping",
             "SNAP_grouping",
             "diffract_consts_",
             "pixelmask_"] #workspaces with these expresions in their names
    if emptyTrash:
        wsList = mtd.getObjectNames()
        for ws in wsList:
            for dirt in dirty:
                if dirt in ws:
                    DeleteWorkspace(ws)

    # for par in instrumentState:
    #     print(par)
    config.setLogLevel(3, quiet=True)


    

