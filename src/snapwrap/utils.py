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


import snapwrap.snapStateMgr as ssm
importlib.reload(ssm)
import snapwrap.io as io
importlib.reload(io)
import snapwrap.maskUtils as mut
importlib.reload(mut)
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# SNAPRed imports
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
from snapred.backend.dao.ingredients.ArtificialNormalizationIngredients import ArtificialNormalizationIngredients
from snapred.backend.dao.request import ReductionExportRequest
from snapred.backend.dao import SNAPRequest
from snapred.backend.dao.request.ReductionRequest import ReductionRequest
from snapred.backend.data.DataFactoryService import DataFactoryService
from snapred.backend.error.ContinueWarning import ContinueWarning
from snapred.backend.recipe.ReductionRecipe import ReductionRecipe
from snapred.backend.service.ReductionService import ReductionService
from snapred.backend.dao.indexing.Versioning import Version, VersionState
from snapred.meta.mantid.WorkspaceNameGenerator import WorkspaceNameGenerator as wng
from snapred.meta.Config import Config
from snapred.backend.api.InterfaceController import InterfaceController
# from snapred.backend.data import LocalDataService as lds
from snapred.backend.dao.request.FarmFreshIngredients import FarmFreshIngredients
from snapred.backend.service.SousChef import SousChef
from snapred.backend.dao.Hook import Hook

from snapred import __version__ as redVersion
from snapwrap import __version__ as snapwrapVersion

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

def deploy():
    #print information regarding the version of snapred/snapwrap being used
    print(f"snapred version: {redVersion}")

    #attempt to find and print snapwrap hash
    env = "snapred-dev"
    print(f"\nsnapwrap version: {snapwrapVersion}")
    packagePath = f"/opt/anaconda/envs/{env}/lib/python3.10/site-packages/"

    distInfo = [s for s in os.listdir(packagePath) if "dist-info" in s]
    snapwrapDist = [s for s in distInfo if "snapwrap" in s]
    snapwrapDistPath = f"{packagePath}{snapwrapDist[0]}/direct_url.json"

    with open(snapwrapDistPath, 'r') as f:
        deployInfo=json.load(f)

    for key in deployInfo["vcs_info"]:
        print(f"{key}:{deployInfo['vcs_info'][key]}")



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
        nrmcal = ssm.checkCalibrationStatus(runNumber=None,
                                            stateID=stateID,
                                            isLite=isLite,
                                            calType='normcal')
        if nrmcal["stateIsCalibrated"]:
            nrmDir = os.path.dirname(nrmcal['indexPath'])
            print(f"{nrmDir}")
                  
    if purge:
        doubleCheck = input("Listed folders will be deleted. Enter \"yes\" if you are very sure you are OK with this!")
        if doubleCheck == 'yes':
            nDeleted = 0
            for stateID in allAvailableStates:
                nrmcal = ssm.checkCalibrationStatus(runNumber=None,
                                            stateID=stateID,
                                            isLite=isLite,
                                            calType='normcal')
                if nrmcal["stateIsCalibrated"]:
                    nrmDir = os.path.dirname(nrmcal['indexPath'])
                    shutil.rmtree(nrmDir)
                    nDeleted += 1

            print(f"Done. {nDeleted} folders were deleted")
    else:
        print("\nRe-run with purge=True to actually delete these")

def indexStates(isLite=True):

    #prints an index of existing states with general information on their calibration statuses

    allAvailableStates = ssm.availableStates()
    
    outputStrings = []
    statuses = []
    for stateID in allAvailableStates:

        stateDict = ssm.pullStateDict(stateID)

        difcal = ssm.checkCalibrationStatus(runNumber=None,
                                            stateID=stateID,
                                            isLite=isLite,
                                            calType='difcal')
        
        nrmcal = ssm.checkCalibrationStatus(runNumber=None,
                                            stateID=stateID,
                                            isLite=isLite,
                                            calType='normcal')

        # parse possible scenarios
        if difcal["stateIsCalibrated"] and nrmcal["stateIsCalibrated"]:
            calStatus = '*CALIB*'
        if not difcal["stateIsCalibrated"] or not nrmcal["stateIsCalibrated"]:
            calStatus = "PARTIAL"
        if not difcal["stateIsCalibrated"] and not nrmcal["stateIsCalibrated"]:
            calStatus = "UNCALIB"

        desc = ssm.autoStateName(stateDict)
        nDifcal = difcal['numberCalibrations']

        if difcal['latestCalibrationDate'] != "never":
            latestDifcalRun = difcal['latestCalibrationDict']['runNumber']
        else:
            latestDifcalRun = ""

        nNrmcal = nrmcal['numberCalibrations']

        if nrmcal['latestCalibrationDate'] != "never":
            latestNrmcalRun = nrmcal['latestCalibrationDict']['runNumber']
            latestNrmcalBack = nrmcal['latestVBRunNumber']
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

def makeResolutionWorkspace(prefix,
                            runNumber,
                            pixelMask=None,
                            isLite=True):
    
    # This function will use donor workspace to create a resolution workspace
    # any present swiss cheese masks and a specified pixel mask will be used
    # to calculated the full unfocused resolution workspace. If pgs is not none,
    # the unfocused resolution workspace will be diffraction focused accordingly

    #TODO: fix that pgs capitalisation is different from saved workspaces :( 

    if isLite:
        donorWSName = f"dsp_unfoc_lite_{str(runNumber).zfill(6)}"
    else:
        donorWSName = f"dsp_unfoc_{str(runNumber).zfill(6)}"

    #unfocused workspace must exist to proceed
    if donorWSName not in mtd.getObjectNames():
        raise Exception(f"Error: unfocussed, d-space workspace must exist. {donorWSName} not found")

    handles = workspaceHandles(prefix=prefix,
                               runNumber = runNumber) #returns latest ws for runNumber

    # find list of pgs needed

    pgsList = []
    for handle in handles:
        pgsList.append(handle.pixelGroup)
    print(f"Found {len(pgsList)} pixel groups: {pgsList}")

    #get instrument state to extract resolution parameters 
    farmFresh = FarmFreshIngredients(
        runNumber=str(runNumber),
        useLiteMode=isLite,
        focusGroups=[{"name":"All", "definition":""}], #pixel group irrelevant, so just choose one.
        )
    instrumentState = SousChef().prepInstrumentState(farmFresh)

    L1 = instrumentState.instrumentConfig.L1
    L2 = instrumentState.instrumentConfig.L2
    Ltot = L1 + L2
    delTOverT = instrumentState.instrumentConfig.delTOverT
    delLOverL = instrumentState.instrumentConfig.delLOverL
    #divergence is guide dependent
    if instrumentState.detectorState.guideStat == 1:
        delTh = instrumentState.instrumentConfig.delThWithGuide
    elif instrumentState.detectorState.guideStat == 2:
        delTh = instrumentState.instrumentConfig.delThNoGuide
    else:
        raise Exception(f"ERROR: unexpected guide status {instrumentState.detectorState.guideStat} for run {runNumber}")

    #make delDOverD workspace
    print(f"Resolution params: delT/T: {delTOverT:.6f}, delL {delLOverL*Ltot:.6f}, delTh: {delTh:.4f}")

    ConvertUnits(InputWorkspace=donorWSName,
        OutputWorkspace=donorWSName,
        Target="dSpacing")
    
    #this calculates delta_d/d for each pixel using the TOF resolution equation
    EstimateResolutionDiffraction(InputWorkspace=donorWSName,
        DeltaTOFOverTOF = delTOverT,
        SourceDeltaL = delLOverL*Ltot,
        SourceDeltaTheta = delTh,
        PartialResolutionWorkspaces="partial",
        OutputWorkspace="delDOverD")
    
    #TODO: delete partial workspaces

    #get grouping workspaces

    snap = ssm.SNAPHome()
    calibrationHome = snap.calib

    for pgs in pgsList:
        pgsDefinition = f"{calibrationHome}/Powder/PixelGroupingDefinitions/SNAPFocGroup_{pgs.capitalize()}.lite.hdf"
        if isLite:
            gpWSName= f"SNAPLite_grouping__{pgs.capitalize()}"
        else:
            gpWSName = f"SNAP_grouping__{pgs.capitalize()}"

        if not mtd.doesExist(gpWSName):
            mut.LoadH5GroupingDefinition(donorWSName=donorWSName,
                                        groupingFilePath=pgsDefinition,
                                        gWS=gpWSName)    

    resWSName = f"resolution_dsp_unfoc_{str(runNumber).zfill(6)}"
    CloneWorkspace(InputWorkspace=donorWSName,
            OutputWorkspace=resWSName)
    

    # get global d limits
    ws = mtd[resWSName]
    xMin = 100000.0
    xMax = 0.0
    for i in range(ws.getNumberHistograms()):
        x = ws.dataX(i)
        if np.max(x) >= xMax:
            xMax = np.max(x)
        if np.min(x) <= xMin:
            xMin = np.min(x)
    
   
    Rebin(InputWorkspace=resWSName,
          OutputWorkspace=resWSName,
          Params=(xMin,-0.005,xMax),
          PreserveEvents=False)
    
    ws = mtd[resWSName]
    wsDoD = mtd["delDOverD"]
    nPix = wsDoD.getNumberHistograms()

    #populate workspace with values for del_d as a function of d
    for pix in range(nPix):
        
        delDOverD = wsDoD.dataY(pix)

        xVals = ws.dataX(pix)
        xMids = 0.5*(xVals[0:-1]+xVals[1:])
        
        yVals = delDOverD*xMids #delta_d as a function of d-space
        
        ws.setY(pix,yVals)

    #apply pixel mask if provided
    if pixelMask is not None:
        if mtd.doesExist(pixelMask):
            print(f"Applying pixel mask: {pixelMask}")
            MaskDetectors(Workspace=resWSName,
                           MaskedWorkspace=pixelMask,
                           )
        else:
            print(f"ERROR: pixel mask {pixelMask} does not exist")
            return
        
    # apply full set of masks: pixel and bin to resWSName

    #bin masks: pending proper snapred 4.0 this follows the very imperfect strategy
    # of applying any workspace with string "maskBins_" in its name found in the ADS. 

    maskBinTables = [table for table in mtd.getObjectNames() if "maskBins_" in table]
    print(f"found {len(maskBinTables)} bin mask workspaces")
    for table in maskBinTables:
        
        maskBinUnit = table.split("_")[1]

        ConvertUnits(InputWorkspace=resWSName,
            OutputWorkspace=resWSName,
            Target=maskBinUnit)
            
        print(f"Masking bins with: {table}")
        MaskBinsFromTable(InputWorkspace=resWSName,
            MaskingInformation=table,
            OutputWorkspace=resWSName)

    #return resolutionws to original units        
    ConvertUnits(InputWorkspace=resWSName,
        OutputWorkspace=resWSName,
        Target="dSpacing")

    #GroupDetectors for all pgs present in ws handle. 
    # By selecting `Behaviour='Average'` populate
    # each grouped output spectrum to contain averaged del_d. 

    for handle in handles:

        pgs = handle.pixelGroup

        if isLite:
            gpWSName = f"SNAPLite_grouping__{pgs}"
        else:
            gpWSName = f"SNAP_grouping__{pgs}"

        outWS = f"resolution_dsp_{pgs.lower()}_{str(runNumber).zfill(6)}"

        GroupDetectors(InputWorkspace=resWSName, 
            OutputWorkspace=outWS, 
            IgnoreGroupNumber=False,
            Behaviour='Average', 
            PreserveEvents=False,
            CopyGroupingFromWorkspace=gpWSName)

        ConvertToPointData(InputWorkspace=outWS,
        OutputWorkspace=outWS)

        # RebinRagged(InputWorkspace=outWS,
        #             OutputWorkspace=outWS,
        #             XMin=handle.xMin,
        #             XMax=handle.xMax,
        #             Delta=handle.delta,
        #             FullBinsOnly=True)

        # ws = mtd[outWS]
        # ws.setDistribution=False

        print(f"created resolution workspace: {outWS}")

    return 

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

    reducedGroups = io.reducedRuns(exportFormats=[],prefix="reduced_dsp")

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
               gsaInstPrm=True,
               iptsOverride=None,
               fileTag=None):
    #creates reducedGroups and then exports these using the requested export formats

    reducedGroups = io.reducedRuns(exportFormats,
                                       prefix,
                                       iptsOverride=iptsOverride,
                                       fileTag=fileTag)
    
    io.exportReducedGroups(reducedGroups,latestOnly,gsaInstPrm)

def workspaceHandles(prefix="reduced_dsp",pgs=None,runNumber=None):

    # returns a list of redObjects for the requested workspaces matching arguments
    # 20250530 modified to allow specific pgs or run number to be optionally specified
    # otherwise everything will be found.

    #currently only the latest timestamp is returned.

    reducedList = io.reducedRuns([],prefix=prefix) #first argument is a list that isn't used but needs to exist

    if not reducedList:
        print("No matching workspaces found")
        return
    
    #if a pgs is specified filter only those matching, otherwise do nothing here

    handleList = []
    for red in reducedList:
        pgsList = red.objectDict.keys()
        if runNumber == None:
            for p in pgsList:                
                redObj = red.objectDict[p][0]
                handleList.append(redObj)
        else:
            if int(red.runNumber) == runNumber:
                for p in pgsList:
                    redObj = red.objectDict[p][0]
                    handleList.append(redObj)

    # at this point all, pgs are included. If none is specified, return here otherwise
    # purge to match requested pgs

    if pgs == None:
        print(f"Found {len(handleList)} matching workspaces")
        return handleList
    else:
        purgeHandleList = []
        for h in handleList:
            if h.pixelGroup == pgs:
                purgeHandleList.append(h)
        print(f"Found {len(purgeHandleList)} matching workspaces")
        return purgeHandleList 

    
def confirmIPTS(ipts,comment="SNAPRed/snapwrap", subNum=1, redType="Scripts"):

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

def propagateDifcal(donorRunNumber,isLite=True,propagate=False,includeGuideStatus=False):

    #This will accept a reference Run number, determine a list of all existing 
    # states with equivalent detector positions
    # if propagate==True, the latest calibration from the state corresponding to 
    # refRunNumber will be propagated to other compatible states as if it's a formal
    # calibration
 
    donorStateID,donorStateDict = ssm.stateDef(donorRunNumber)
    donorDetConfig = ssm.detectorConfig(donorStateDict,includeGuideStatus)

    # check diffraction calibration status of reference run

    donorCalStatus = ssm.checkCalibrationStatus(runNumber=donorRunNumber,
                                            stateID=None,
                                            isLite=isLite,
                                            calType='difcal')


    # if state is uncalibrated, stop. Nothing to propagate
    if not donorCalStatus["runIsCalibrated"]:
        print(f"ERROR: provided run number: {donorRunNumber} of state: {donorStateID} does not have a valid difcal")
        return
    else:
         print(f"""
/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/
propagateDifcal: Utility to copy calibrations
/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/_/
Donor calibration info
    - Donor Run:  {donorRunNumber}
    - State: {donorStateID}
    - Detector config: {donorDetConfig}
    - calibrated: {donorCalStatus['numberCalibrations']} times
    - latest valid version: {donorCalStatus['latestValidCalibrationDict']['version']}       
    - most recent valid calibration on: {donorCalStatus['latestValidCalibrationDate']}    
    """)

    nCompatibleStates = 0
    recipientCalStatus = []
    recipientState = []
    recipientDetConfig = []

    # The calibration being propagated will become the latest calibration in the receiving state
    # However, the validity of the propagated state will follow that of the donor calibration

    for stateID in ssm.availableStates():
        if stateID != donorStateID:
            stateDict = ssm.pullStateDict(stateID) ##
            detConfig = ssm.detectorConfig(stateDict,includeGuideStatus)
            if detConfig == donorDetConfig:
                calStatus = ssm.checkCalibrationStatus(runNumber=None,
                                                       stateID=stateID,
                                                       isLite=isLite,
                                                       calType="difcal")
                recipientCalStatus.append(calStatus)
                recipientState.append(stateID)
                recipientDetConfig.append(detConfig)
                     
                nCompatibleStates += 1

    print(f"\n{nCompatibleStates} state(s) found with matching detector configs\n")

    print("Existing compatible states are:")
    for state in recipientState:
        print(state)

    if propagate:
        print("\nThese will be states will accept the donor calibration")
        for calStatus in recipientCalStatus:

            print("recipient:")
            for key in calStatus:
               
                print("    ",key," : ",calStatus[key])

            ssm.copyDifcal(donorCalStatus,calStatus,propagate)
    else:
        print("\nPropagatation of calibration was not requested")
        
def reload(runNumber,
           all=False,
           unpack=True,
           keepMask=False,
           pixelGroup=None,
           isLite=True):

    r = io.diskObject(runNumber,isLite)
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

    import snapwrap.maskUtils as mut
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

########## Define SNAPRed hook functions here ##################

def doNothingHook(self):

    pass

def BackgroundAttenuationCorrection(self, attenuationWSName = None, backgroundWSName=None):

    # TODO: validate input ws match sample workspace: need to be from same state
    # note this is post hook to preprocessReductionRecipe, so outputWS starts as unfocussed TOF
    # and needs to end this way too.

    if backgroundWSName is not None:

        # if background workspace is specified, subtract it before attenuation correction

        # background must be in TOF too

        self.mantidSnapper.ConvertUnits("",InputWorkspace=backgroundWSName,
                                        OutputWorkspace=backgroundWSName,
                                        Target="TOF")
        
        # rebin to match sample data

        self.mantidSnapper.RebinToWorkspace("",WorkspaceToRebin=backgroundWSName,
                                            WorkspaceToMatch=self.outputWs,
                                            OutputWorkspace=backgroundWSName,
                                            PreserveEvents=True) 

        # sample ws needs to be NBC here
        self.mantidSnapper.NormalizeByCurrentButTheCorrectWay("",
                                InputWorkspace=self.outputWs,
                                OutputWorkspace=self.outputWs)
        # and background too
        self.mantidSnapper.NormalizeByCurrentButTheCorrectWay("",
                                InputWorkspace=backgroundWSName,
                                OutputWorkspace=backgroundWSName)
        

        self.mantidSnapper.Minus("",LHSWorkspace=self.outputWs,
                                 RHSWorkspace=backgroundWSName,
                                 OutputWorkspace=self.outputWs)
        
    if attenuationWSName is not None:

        # if attenuation workspace is specified divide by it

        self.mantidSnapper.ConvertUnits("",InputWorkspace=self.outputWs,
                                        OutputWorkspace=self.outputWs,
                                        Target="Wavelength")
        
        self.mantidSnapper.RebinToWorkspace("",WorkspaceToRebin=attenuationWSName,
                                            WorkspaceToMatch=self.outputWs,
                                            OutputWorkspace=attenuationWSName,
                                            PreserveEvents=True) 

        self.mantidSnapper.Divide("",LHSWorkspace=self.outputWs,
                                  RHSWorkspace=attenuationWSName,
                                  OutputWorkspace=self.outputWs)
    
    self.mantidSnapper.ConvertUnits("",InputWorkspace=self.outputWs,
                                    OutputWorkspace=self.outputWs,
                                    Target="dSpacing")
        
    self.mantidSnapper.executeQueue()


def cheeseMask(binMaskList):

    #TODO
    print("test")


def reduce(runNumber,
               sampleEnv='none',
               pixelMaskIndex='none',
            #    binMaskList=[],
               YMLOverride='none',
               backgroundWSName = None,
               attenuationWSName = None,
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

    print("snapwrap: gathering reduction ingredients...\n")
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # load reduction params from default yml with option to override 
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    #TODO: update default to final shared repo path

    if YMLOverride == 'none':
        defaultYML = os.path.join(os.path.dirname(__file__), "defaultRedConfig.yml") #this will live in repo
    else:
        defaultYML = YMLOverride

    snapwrapGlob = globalParams(defaultYML)

    #set global parameters
    useLiteMode=snapwrapGlob.useLiteMode
    pixelMasks = snapwrapGlob.pixelMasks
    # keepUnfocussed = snapwrapGlob.keepUnfocussed
    convertUnitsTo = snapwrapGlob.convertUnitsTo

    #process continue flags
    continueFlags = ContinueWarning.Type.UNSET #by default do not continue

    if continueNoVan:
        artificialNormalizationIngredients = ArtificialNormalizationIngredients(
        peakWindowClippingSize = Config["constants.ArtificialNormalization.peakWindowClippingSize"],
        smoothingParameter=snapwrapGlob.AN_smoothingParameter,
        decreaseParameter=snapwrapGlob.AN_decreaseParameter,
        lss=snapwrapGlob.AN_lss
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

    # if binMaskList:
    #     # users can specify a list of table bin workspace names. If these are not found
    #     # look in a standardised folder (ipts-12345/shared/masks) and attempt to load them. If they do not 
    #     # exist, give a helpful error.
        
    #     for bMask in binMaskList:

    #         if bMask not in mtd.getObjectNames():

    #             #attempt to load from standard location
    #             ipts = GetIPTS(Instrument="SNAP",
    #                         RunNumber=runNumber)
    #             maskFolder = f"{ipts}masks/"
    #             maskPath = f"{maskFolder}bMask.json"
    #             cheese=mut.swissCheese()
    #             try: 
    #                 cheese.load(maskPath)
    #             except: 
    #                 raise Exception(f"Requested bin mask workspace doesn\'t exist and attempt to load: {maskPath} failed!")


    #     print("bin masks processed")

    print("Calling reduction service")
    reductionService = ReductionService()
    interfaceController = InterfaceController()

    timestamp = reductionService.getUniqueTimestamp()

    print(f"backgroundWSName is: {backgroundWSName}")
    print(f"attenuationWSName is: {attenuationWSName}")

    hooks = None

    if backgroundWSName is not None or attenuationWSName is not None: # do if either is true

        print("\nHOOK WILL BE APPLIED!!!!\n")
        #define hook

        hook = Hook(func=BackgroundAttenuationCorrection,
                    attenuationWSName = attenuationWSName, #TODO: correctly manage ws names 
                    backgroundWSName= backgroundWSName) #TODO: correctly manage ws names

        emptyHook = Hook(func=doNothingHook)
        hooks = {
            "PostPreprocessReductionRecipe" : [hook, emptyHook]
        }

        reductionRequest = ReductionRequest(
            runNumber=runNumber,
            useLiteMode=useLiteMode,
            timestamp=timestamp,
            continueFlags=continueFlags,
            pixelMasks=pixelMasks,
            keepUnfocused=keepUnfocussed,
            convertUnitsTo=convertUnitsTo,
            artificialNormalizationIngredients=artificialNormalizationIngredients,
            hooks = hooks,
        )

    else:

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


    snapRequest = SNAPRequest(path="/reduction",payload=reductionRequest,hooks=hooks)

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

    [stateID,stateDict] = ssm.stateDef(runNumber)

    dataFactoryService = DataFactoryService()
    calibrationPath = dataFactoryService.getCalibrationDataPath(
                useLiteMode=useLiteMode, 
                version = VersionState.LATEST,
                state = stateID
            )
    # print(calibrationPath)
    calibrationRecord = dataFactoryService.getCalibrationRecord(
                runId=runNumber, 
                useLiteMode=useLiteMode, 
                version = VersionState.LATEST,
                state = stateID
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
                useLiteMode=useLiteMode, 
                version = VersionState.LATEST,
                state = stateID
            )
    # print(normalizationPath)
    normalizationRecord = dataFactoryService.getNormalizationRecord(
                runId=runNumber, 
                useLiteMode=useLiteMode, 
                version = VersionState.LATEST,
                state = stateID
            )
    
    if type(normalizationRecord) == None:
        print("""         
                 
          - WARNING: NO VANADIUM FOUND. TO PROCEED EITHER: 
              1. RUN A VANADIUM CALIBRATION OR 
              2. SET "continueNoVan = True" TO USE ARTIFICIAL NORMALISATION

            """)
        
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
                    - ID: {stateID},
                    - definition: {stateDict}

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
        state=stateID)
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

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # Execute reduction here
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

        # TODO: This breaks Q-space option...

        # data = ReductionRecipe().cook(ingredients, groceries)
        data = interfaceController.executeRequest(snapRequest).data
        # record = reductionService._createReductionRecord(reductionRequest, ingredients, data["outputs"])
        record=data.record

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
        # snapwrapIO.convertToQ()
        # first generate list of redObjects for this run:

        redWSList = []
        for ws in data["outputs"]:
            redObj = io.redObject(ws)
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

    dirty = ["tof_all_lite_",
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


    

