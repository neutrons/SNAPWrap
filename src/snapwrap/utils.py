# some helpful functions for use with SNAPRed script version
import yaml
from mantid.simpleapi import *
import numpy as np
import matplotlib.pyplot as plt
import json
import os
import shutil
import inspect
import importlib
import copy
import time
import re
import getpass
from datetime import datetime
import importlib.resources as resources

from .wrapConfig import WrapConfig
from snapwrap.statusPrinter import (printWarning,
                            citation,
                            printStatus,
                            completionMessage,
                            verboseStatus)

import snapwrap.snapStateMgr as ssm
import snapwrap.io as io
import snapwrap.maskUtils as mut
import snapwrap.pixelResolution.mantid_utils as pixRes
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
from snapred.backend.dao.request.FarmFreshIngredients import FarmFreshIngredients
from snapred.backend.service.SousChef import SousChef
from snapred.backend.dao.Hook import Hook

from packaging.version import Version
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

# Utility to allow some checking of version

def versionAtLeast(current, required):
    return Version(current) >= Version(required)


def getConfigPath(name: str):

    # returns the full path to a SNAPRed config file stored in the 
    # snapwrap package configDefinitions folder
    
    return str(resources.files("snapwrap.configDefinitions") / f"{name}.yml")

def reloadRedConfig(path=None):

    # allows reloading of specific overrides of SNAPRed application.yml parameters 
    # by specifying the path to an override file
    # if path is not specified then it will reload the original yml according to the
    # current environment  

    if path is None:
        Config.reload() # reloads original config according to environment
        Config.reload(os.environ.get("env")) # needed to correctly retain a user specified env
        print("Original SNAPRed config reloaded")
    else:
        # confirm file exists at path
        if not os.path.isfile(path):
            print(f"Error: specified SNAPRed config override file does not exist at {path}")
            return
        else:
            Config.reload(path) # reloads specified override file
            print(f"SNAPRed config override applied")
            Config.reload(os.environ.get("env")) # needed to correctly retain a user specified env
    return

def filterLite(runNumber, boundaries, **reduce_kwargs):

    # accepts a single run number and instructions for filtering
    # and then reduces the data accordingly

    # first validate inputs
    if not isinstance(runNumber, int):
        print("Error: runNumber must be an integer")
        return
    if not isinstance(boundaries, dict):
        print("Error: boundaries must be a dictionary")
        return
    
    # check current value for qsp parameter
    sig = inspect.signature(reduce)
    qsp = reduce_kwargs.get('qsp', sig.parameters['qsp'].default)
    

    # process boundaries
    if boundaries["type"] == "time":
        # require list of times in seconds as floats.
        if boundaries["units"] == "seconds":
            secondBoundaries = [float(x) for x in boundaries["values"]] 
        elif boundaries["units"] == "minutes":
            secondBoundaries = [float(x)*60.0 for x in boundaries["values"]] 
        elif boundaries["units"] == "hours":
            secondBoundaries = [float(x)*3600.0 for x in boundaries["values"]]
        else:
            print(f"Error: currently only time units of seconds, minutes, and hours are supported. You requested: {boundaries['units']}")
            return
        # TODO: check if boundaries are within run time of run runNumber

    else:
        print("Error: currently only time boundaries are supported")
        return

    # obtain original nexus file path
    iptsPath = GetIPTS(RunNumber=runNumber, Instrument="SNAP")
    # iptsNumber = iptsPath.split("IPTS-")[-1].split("/")[0]
    nexusPath = f"{iptsPath}/nexus/SNAP_{runNumber}.nxs.h5"


    # override SNAPRed parameters lite location params
    s = getConfigPath("nexusDefinitionFilterOverride")
    reloadRedConfig(s)

    # specify lite params
    liteDir=f"{iptsPath}/{Config['nexus']['lite']['prefix'][0:-5]}"
    liteFilename=f"SNAP_{runNumber}.lite.nxs.h5"
    liteYml = f"SNAP_{runNumber}.lite.yml"
    litePars = {"TOFTol" : -0.0001, #default for no TOF compression
                            "clockTol": None,
                            "liteGroupMapFile": Config['instrument']['lite']['map']['file'],
                            "liteIDF":Config['instrument']['lite']['definition']['file'],
                            "liteDir":liteDir,
                            "liteFilename":liteFilename,
                            "liteYAML":liteYml,
                            "saveLite":True
                            }
    for key in litePars.keys():
        print(f"{key}: {litePars[key]}")

    #loop through boundaries, create lite file for each, then reduce that
    outputWSNames = []
    if qsp:
        outputWSNames_qsp = []
    for sliceID in range(len(secondBoundaries)-1):

        startTime = secondBoundaries[sliceID]
        stopTime = secondBoundaries[sliceID+1]

        displayStartTime = boundaries["values"][sliceID]
        displayStopTime = boundaries["values"][sliceID+1]
        displayUnits = boundaries["units"]

        litePars["filterStartTime"]= startTime
        litePars["filterStopTime"]= stopTime

        # load time filtered raw data
        LoadEventNexus(Filename=nexusPath,
                       OutputWorkspace="tmp",
                       LoadMonitors=False,
                       FilterByTimeStart=startTime,
                       FilterByTimeStop=stopTime)

        # make lite version and save to disk in special filtered folder
        makeLite(inWS="tmp",outWS="tmpLite",litePars=litePars,overwrite=True)

        # reduce this filtered lite data.
        print(f"Reducing run {runNumber} from {startTime}s to {stopTime}s")
        wsNames = reduce(runNumber=runNumber, **reduce_kwargs)

        # rename output workspace to indicate sequences
        print(f"Debug: reduced workspace names are: {wsNames}")
        for name in wsNames:
            if "pixelmask" in name:
                continue #if a pixel mask is used, SNAPRed returns its workspace name. Skip this as it's not a reduced workspace
            print("Original name: ",name)
            if qsp:
                handle=io.redObject(name,requiredUnits="qsp")
            else:
                handle = io.redObject(name)

            newName = f"slice-{str(sliceID).zfill(3)}_{handle.units}_{handle.pixelGroup}_{handle.runNumberString}"
            RenameWorkspace(InputWorkspace=name, OutputWorkspace=newName)
            outputWSNames.append(newName)

            # update label for plotting
            from mantid.api import TextAxis

            ws = mtd[newName]
            N = ws.getNumberHistograms()
            labels = [f"bank {i+1}: {displayStartTime:.1f} to {displayStopTime:.1f} {displayUnits}" for i in range(N)]
            taxis = TextAxis.create(N)
            for i,lab in enumerate(labels):
                taxis.setLabel(i, lab)

            ws.replaceAxis(1, taxis)

        DeleteWorkspace(Workspace="tmp")
        DeleteWorkspace(Workspace="tmpLite")




    # group output names into workspace group

    #First group alphabetically 

    def sortKey(name):
        parts = name.split("_")
        string_id = parts[2]       # "all", "bank", "column
        slice_num = int(parts[-1]) # "000" -> 0
        return (string_id, slice_num)
    
    sortedOutputWSNames = sorted(outputWSNames, key=sortKey)
    if qsp:
        groupUnits = "qsp"
    else:
        groupUnits = "dsp"

    GroupWorkspaces(InputWorkspaces=sortedOutputWSNames, OutputWorkspace=f"slice_{groupUnits}_{runNumber}")
    # if qsp:
    #     sortedOutputWSNames_qsp = sorted(outputWSNames_qsp, key=sortKey)
    #     GroupWorkspaces(InputWorkspaces=sortedOutputWSNames_qsp, OutputWorkspace=f"slice_qsp_{runNumber}")


    #Reset config to original
    reloadRedConfig()

    print(f"Config reset. lite data directory reset to: {Config['nexus']['lite']['prefix'][0:-5]}")
    return

def makeLite(inWS,outWS,litePars,overwrite=False):

    # utility to convert an input native workspace to a lite workspace
    # requires litePars, a dictionary providing necessary parameters

	#check if lite directory exists and create if it doesn't

    mut.LoadH5GroupingDefinition(inWS,
                            litePars["liteGroupMapFile"],
                            "liteGroup")

    logger.notice("makelite: Grouping Pixels")

    GroupDetectors(InputWorkspace=inWS,
                OutputWorkspace=outWS,
                CopyGroupingFromWorkspace="liteGroup")

    DeleteWorkspace(Workspace="liteGroup")

    logger.notice("makelite: relabelling pixel IDs")
    nHst = mtd[outWS].getNumberHistograms()
    for i in range(nHst):
        el = mtd[outWS].getSpectrum(i)
        el.clearDetectorIDs()
        el.addDetectorID(i)
    mtd[outWS].setComment(mtd[outWS].getComment() + "\nLite")

    logger.notice("makelite: loading instrument")

    LoadInstrument(Workspace=outWS,
                Filename=litePars["liteIDF"],
                RewriteSpectraMap=False)

    logger.notice("makelite: compressingEvents")
    #modified to allow compression tolerances to be switched

    if litePars["TOFTol"] is None:
        tolVal = 1e-5
    else:
        tolVal = litePars["TOFTol"]

    if litePars["clockTol"] is None:
        
        CompressEvents(InputWorkspace=outWS,
                OutputWorkspace=outWS,
                Tolerance=tolVal)
                # sortFirst=False) #not in stable mantid release yet.
    else:
        CompressEvents(InputWorkspace=outWS,
                OutputWorkspace=outWS,
                Tolerance=tolVal,
                WallClockTolerance=litePars["clockTol"])

    if litePars["saveLite"]:
        #check that lite directory exists
        if not os.path.exists(litePars['liteDir']):
            try: 
                os.mkdir(litePars['liteDir'])
            except:
                logger.error(f"makelite: unable to create lite directory: {litePars['liteDir']}")
                print(f"Perhaps you don't have write permissions?")

        litePath = f"{litePars['liteDir']}{litePars['liteFilename']}"

        SaveNexusProcessed(InputWorkspace=outWS,
                    Filename=litePath,
                    Title="autoLite")
        
        logger.notice(f"makelite: Lite file {litePath} written to disk")

        with open(f"{litePars['liteDir']}{litePars['liteYAML']}", 'w') as file:
            yaml.dump(litePars,file)

        logger.notice(f"makelite: compression parameters written to: {litePars['liteDir']}{litePars['liteYAML']}")

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
            # We want the most recent *cycle* that has a calibration, not the most
            # recent calibration by timestamp (which could be a re-calibration for
            # an older cycle).  Iterate all index entries, resolve each to its
            # effective run number (accounting for propagated calibrations whose
            # true donor run is embedded in the comments field), map to cycle, and
            # pick the latest.
            import re
            bestCycle = ""
            bestRun = ""
            for entry in difcal['calibIndexList']:
                # skip the default geometric entry (version 0)
                if entry.get('version', -1) == 0:
                    continue
                comment = entry.get('comments', '')
                propagated = re.match(r"\(copied from run:(\S+)\s+version:", comment)
                if propagated:
                    effectiveRun = propagated.group(1)
                else:
                    effectiveRun = entry['runNumber']
                cycle = ssm.cycleForRun(effectiveRun) or ""
                if cycle > bestCycle:
                    bestCycle = cycle
                    bestRun = effectiveRun
            latestDifcalRun = bestRun
            latestDifcalCycle = bestCycle
        else:
            latestDifcalRun = ""
            latestDifcalCycle = ""

        nNrmcal = nrmcal['numberCalibrations']

        if nrmcal['latestCalibrationDate'] != "never":
            latestNrmcalRun = nrmcal['latestCalibrationDict']['runNumber']
            latestNrmcalBack = nrmcal['latestVBRunNumber']
            latestNrmcalCycle = ssm.cycleForRun(latestNrmcalRun) or ""
            latestNrmcalBackCycle = ssm.cycleForRun(latestNrmcalBack) or ""
        else:
            latestNrmcalRun = ""
            latestNrmcalBack = ""
            latestNrmcalCycle = ""
            latestNrmcalBackCycle = ""

        outputString = (f"{stateID}|{desc}|"
                        f" {calStatus} |"
                        f"     {nDifcal}     | {latestDifcalCycle.rjust(6)} |"
                        f"     {nNrmcal}     | {latestNrmcalCycle.rjust(6)} | {latestNrmcalBackCycle.rjust(6)} |"
                            )
        statuses.append(calStatus) 
        outputStrings.append(outputString)

    #output in order of calibration status...
    print("\nStateID         |Desc.                                                      | Status  |No. difcals| latest |No. nrmcals| latest | (bgnd) |")
    for i,string in enumerate(outputStrings):
        if statuses[i] == "UNCALIB":
            print(string) 

    for i,string in enumerate(outputStrings):
        if statuses[i] == "PARTIAL":
            print(string) 

    for i,string in enumerate(outputStrings):
        if statuses[i] == "*CALIB*":
            print(string) 


def estimatePixelAspect(pixelID,spectrumInfo,isLite=True):
    
    #This attempts to estimate the aspect ratio of a pixel by looking at 
    #relative angles from detector centre

    pixelID = int(pixelID)

    if isLite:
        if pixelID >= 0 and pixelID <=9215 :
            bank = 'east'
            centrePixel = int((4096+5119)/2)
        elif pixelID > 9215:
            bank = 'west'
            centrePixel = int((13312+14335)/2)
    else:
        print("Error: doesn\'t currently work for native mode")
        raise NotImplementedError("estimatePixelAspect does not currently support native mode (isLite=False)")

    centreAngles = np.array(spectrumInfo.geographicalAngles(centrePixel))
    pixelAngles = np.array(spectrumInfo.geographicalAngles(pixelID))
    relativeAngles = pixelAngles-centreAngles
    aspect = np.cos(relativeAngles[0])*np.cos(relativeAngles[1])


    return aspect


def GroupDetectorsIgnoreNAN(wsName,groupingWSName,outputWSName,behaviour="Average",weightWorkspaceName=None):

    # for makeResolutionWorkspace to work properly I need a special version of 
    # GroupDetectors algo that will ignore the NAN values that occur in in spectra 
    # That have been diamond notched.
    # 
    # In addition, a workspace containing the solid angle of each pixel 
    # can be specified. If it is, the contribution of each pixel to the 
    # grouped spectrum will be weighted according to its solid angle.


    if behaviour not in ["Sum","Average"]:
        print("Error: unexpected behaviour requested. Should be either \'Sum\' or \'Average\'")
        return

    ws = mtd[wsName]

    #some validation
    if not ws.isCommonBins():
        # if bins aren't common, might still be point data, check this
        x = ws.dataX(0)
        if len(x) != 1:
            print("error: GroupDetectorsIgnoreNAN requires common bins (non ragged)")
            return
        else:
            print("NOTICE: input workspace appears to contain point data")
    
    #TODO: check this is not an event workspace (how?)

    # specInfo=ws.spectrumInfo()

    gpws = mtd[groupingWSName]

    # get ID's of subgroups and loop over these
    groupIDs = gpws.getGroupIDs()
    ngroup = len(groupIDs)

    # print(f"found {ngroup} subgroups in {groupingWSName}") 

    
    # loop over subgroups, and average all y arrays for each, ignoring NAN and weighting
    # if, requested, weighting individual pixels contributions according to their solid angle
    #to retain geometry, create a grouped workspace using normal GroupDetectors, but then over
    #write this with the weighted/NAN-ignored data

    #build grouped workspace that retains instrument geometry. Y-values will be overwritten    
    GroupDetectors(InputWorkspace=wsName,
                OutputWorkspace=outputWSName,
                CopyGroupingFromWorkspace=groupingWSName,
                PreserveEvents=False)
    
    # if provided extract array of weights for all pixels
    if weightWorkspaceName is not None:
        weightWS = mtd[weightWorkspaceName]
        w = []
        for i in range(weightWS.getNumberHistograms()):
            w.append(weightWS.readY(i)[0]) #assumes single bin
        pixelWeight = np.array(w)
        print(f"Created weight array of length {len(pixelWeight)} from {weightWorkspaceName}")

    wsOut = mtd[outputWSName]
    groupPixelCount = []
    for sub in groupIDs:
        
        #list of pixels in group
        idList = gpws.getDetectorIDsOfGroup(int(sub))
        nPixelsInGroup = len(idList)
        groupPixelCount.append(nPixelsInGroup)

        # Purge fully masked spectra
        idList = [int(i) for i in idList if not ws.getDetector(int(i)).isMasked()]

        if len(idList) < nPixelsInGroup:
            print(f"Notice: {nPixelsInGroup - len(idList)} pixels were masked in subgroup {sub}.")

        # set all masked bins to nan, average remaining bins in all spectra ignoring NAN
        YNorm = []
        totalMaskedBins = 0
        for j, i in enumerate(idList): #for each subgroup, loop over all pixels here.

            y = ws.dataY(int(i))
            if ws.hasMaskedBins(int(i)):
                mask_indices = ws.maskedBinsIndices(int(i))
                y[mask_indices] = np.nan  # set masked bins to nan
                totalMaskedBins += len(mask_indices)
            YNorm.append(y)

        if totalMaskedBins > 0:
            print(f"Notice: a total of {totalMaskedBins} bins were masked in subgroupID {sub}.")

        if len(YNorm) == 0:
            print(f"Warning: all spectra in subgroupID {sub} are fully masked.")
            y_avg = np.full(wsOut.blocksize(), np.nan)
        else:
            
            YNorm = np.vstack(YNorm)
            if behaviour == "Sum":
                y_avg = np.nansum(YNorm, axis=0) 
            elif behaviour == "Average":
                if weightWorkspaceName is None:
                    # equal weights for the subgroup only
                    w_pix = np.ones(YNorm.shape[0], dtype=float)
                else:
                    w_pix = pixelWeight[np.asarray(idList, dtype=int)]  # or row_idx if mapped

                w = w_pix[:, None]
                mask = np.isfinite(YNorm)
                num = np.nansum((YNorm**2) * w, axis=0)
                den = np.sum(w * mask, axis=0)
                y_avg = np.sqrt(np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0))

                # sanity check
                assert len(idList) == YNorm.shape[0], "idList length must match YNorm rows"
                assert w_pix.shape[0] == YNorm.shape[0], "weights must align with YNorm rows"

        h = int(sub)-1 # subgroupID starts at one instead of zero
        wsOut.setY(h,y_avg)

def getDetectorArcs(wsName,alias=True):
    
    # extract detector arc values these can either come from the original
    # pv logs or their aliases.
    #
    # important note, it seems like it is the aliases that are used to adjust
    # the IDF detector positions to their actual values

    ws = mtd[wsName]

    logs = ws.getRun().getLogData()

    if alias:
        arcLogs = ["det_arc1","det_arc2"]
    else:
        arcLogs = ["BL3:Mot:vdet_arc1","BL3:Mot:vdet_arc2"]

    # print("\n Debug getDetectorArcs:")
    for log in logs:

        if log.name == arcLogs[0]:
            arc1 = log.value[0]
        if log.name == arcLogs[1]:
            arc2 = log.value[0]

    print("arc1",arc1)
    print("arc2",arc2)
    if not arc1 or not arc2:
        print(f"Error: did not find logs {arcLogs}")

    return [arc1,arc2]    

def resetDetectorArcs(donorWSName):

    # will set detector arcs equal to original pv log values
    # and reload instrument to apply them

    #first get original pv log values
    [origArc1,origArc2] = getDetectorArcs(donorWSName,alias=False)

    # then update to these values
    updateDetectorArcs(donorWSName,origArc1,origArc2)

def updateDetectorArcs(donorWSName,arc1,arc2,isLite=True):

    #update detector arc aliases and reload instrument to apply
    # need arcs angles to be strings. 
    arcs = {
        "det_arc1": str(arc1),
        "det_arc2": str(arc2)
    }

    for arc in arcs.keys():

        AddSampleLog(Workspace=donorWSName,
                    LogName=arc,
                    LogText=arcs[arc],
                    LogType="Number Series")
        
    if isLite:
        xml = Config["instrument.lite.definition.file"]
        LoadInstrument(Workspace=donorWSName,
                   Filename=xml,
                   MonitorList="-2--1",
                   RewriteSpectraMap=False)
        print("loaded SNAP lite instrument")
    else:
        LoadInstrument(Workspace=donorWSName,
                   InstrumentName="SNAP",
                   MonitorList="-2--1",
                   RewriteSpectraMap=False)
        print("loaded native instrument")
    return


def makeResolutionWorkspace(prefix,
                            runNumber,
                            pixelMask=None,
                            binMaskList=[],
                            isLite=True):
    
    # This function will use donor workspace to create a resolution workspace
    # any present swiss cheese masks and a specified pixel mask will be used
    # to calculated the full unfocused resolution workspace. If pgs is not none,
    # the unfocused resolution workspace will be diffraction focused accordingly

    #TODO: fix that pgs capitalisation is different from saved workspaces :( 

    if isLite:
        donorWSName = f"dsp_unfoc_lite_{str(runNumber).zfill(6)}"

        # load pixel weight workspace
        LoadNexus(Filename="/SNS/SNAP/shared/Calibration/Auxiliary/pixWeightsLite.nxs",
           OutputWorkspace="pixWeightsLite")
    else:
        # donorWSName = f"dsp_unfoc_{str(runNumber).zfill(6)}"
        raise Exception("Error: Currently makeResolutionWorkspace only works with Lite data")


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
    # First determine the state ID for this run number
    stateID, _ = ssm.stateDef(runNumber)
    
    farmFresh = FarmFreshIngredients(
        runNumber=str(runNumber),
        useLiteMode=isLite,
        state=stateID,
        focusGroups=[{"name":"All", "definition":""}], #pixel group irrelevant, so just choose one.
        )
    instrumentState = SousChef().prepInstrumentState(farmFresh)

    L1 = instrumentState.instrumentConfig.L1
    L2 = instrumentState.instrumentConfig.L2
    Ltot = L1 + L2
    delTOverT = instrumentState.instrumentConfig.delTOverT
    delLOverL = instrumentState.instrumentConfig.delLOverL
    delL = delLOverL*Ltot
    #divergence is guide dependent
    if instrumentState.detectorState.guideStat == 1:
        delTh = instrumentState.instrumentConfig.delThWithGuide
    elif instrumentState.detectorState.guideStat == 2:
        delTh = instrumentState.instrumentConfig.delThNoGuide
    else:
        raise Exception(f"ERROR: unexpected guide status {instrumentState.detectorState.guideStat} for run {runNumber}")

    # also need values to correctly calculate d-limits
    lamMin = instrumentState.particleBounds.wavelength.minimum
    lamMax = instrumentState.particleBounds.wavelength.maximum
    lowdSpacingCrop = Config["constants.CropFactors.lowdSpacingCrop"]
    highdSpacingCrop = Config["constants.CropFactors.highdSpacingCrop"] 

    #make delDOverD workspace
    print(f"Resolution params from SNAPRed: delT/T: {delTOverT:.6f}, delL {delLOverL*Ltot:.6f}, delTh: {delTh:.6f}")

    # update 20251029: finished an extensive investigation into resolution calculation. It demonstrated that we need to
    # include the resolution effects of individual pixels (at least in lite mode). It also demonstrated that the effective
    # size of lite pixels is larger than the definition in IDF due to physical realities in the detector.
    # Finally, it also revealed that the true beam is rotated 1.5 deg towards the east bank relative to the ideal location
    # To handle all of this. I have had to create a custom version of EstimateResolutionDiffraction that includes pixel aspects and
    # allows me to handle beam angle offsets. I've imaginatively called this EstimateResolutionDiffractionSNAP.

    # create workspaces containing pixel solid angle and pixel delta2Theta. The pixEdgeMultiplier value
    # should be considered provisional, but was fitted to a series of peak fit data extracted from run 64413
    # TODO: how on earth should this be properly handled??

    #override SNAPRed values for now with values fitted on 20251029 for run 64413 in Lite mode
    #TODO: migrate to SNAPInstPRm once these are confirmed

    delTOverT = 0.00111
    delTh = 0.00317
    delL = 0.005
    pixMult = 1.621
    beamTilt = -1.509 #best fit: 1.509degrees TODO: why is sign negative? This was confirmed to equate to the beam
    #pointing right looking a long the beam, explicitly: 
        # magnitude of angle of East bank increases, while West decreases. It should be the opposite?
        # Yet, this perfectly fits the data. 

    print(f"Resolution params override: delT/T: {delTOverT:.6f}, delL {delLOverL*Ltot:.6f}, delTh: {delTh:.6f}")
    print(f"Pixel edge multiplier: {pixMult:.6f}, beam tilt: {beamTilt:.6f} deg.")

    #calculate d2t workspace
    pixRes.make_resolution_workspaces(donorWSName,pixelEdgeMultiplier=pixMult) 
    #EstimateResolutionDiffraction requires a workspace with delta-theta, not delta-2theta, so divide by two
    Scale(InputWorkspace="d2t",
        OutputWorkspace="delThetaPix",
        Factor = 0.5,
        Operation = "Multiply")
    
    
    # apply beam tilt correction by adjusting detector arcs
    oldArc1, oldArc2 = getDetectorArcs(donorWSName)
    
    arc1 = oldArc1 + beamTilt #note: arc1 and arc2 have opposite senses, so adding to both is the correct way to apply tilt
    arc2 = oldArc2 + beamTilt

    updateDetectorArcs(donorWSName,arc1,arc2)

    arc1, arc2 = getDetectorArcs(donorWSName)
    print(f"beam tilt of {beamTilt} deg. was applied during resolution calculation")

    ConvertUnits(InputWorkspace=donorWSName,
        OutputWorkspace=donorWSName,
        Target="dSpacing")    
    
    #this calculates delta_d/d for each pixel using the TOF resolution equation
    EstimateResolutionDiffraction(InputWorkspace=donorWSName,
                                DivergenceWorkspace="delThetaPix",
                                DeltaTOFOverTOF = delTOverT,
                                SourceDeltaL = delL,
                                SourceDeltaTheta = delTh,
                                PartialResolutionWorkspaces="partial",
                                OutputWorkspace="delDOverD_ERD_Output")

    resetDetectorArcs(donorWSName) #reset detector arcs to original values

    delDOverD= CloneWorkspace(InputWorkspace="omega") #make clone to use its x-values

    wsRes = mtd["delDOverD"]
    nhist = wsRes.getNumberHistograms()
    wsERD = mtd["delDOverD_ERD_Output"]
    for i in range(nhist):
        wsRes.dataY(i)[0]= wsERD.dataY(i)[0] # overwrite with original y-value with ERD output

    DeleteWorkspaces(["partial_tof","partial_length","partial_angle","delDOverD_ERD_Output"])

    #get grouping workspaces

    snap = ssm.SNAPHome()
    calibrationHome = snap.calib

    pgsWorkspaces = []
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
        pgsWorkspaces.append(gpWSName)    

    resWSName = f"resolution_dsp_unfoc_{str(runNumber).zfill(6)}"

    GroupWorkspaces(InputWorkspaces=pgsWorkspaces,OutputWorkspace="groupingWorkspaces")

    CloneWorkspace(InputWorkspace=donorWSName,
            OutputWorkspace=resWSName)

    # Create unfocussed workspace with x-axes in units of d-spacing 
    # running between global d limits with constant log binning. The
    # y-values are calculated delta-d

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
          Params=(xMin,-0.005,xMax), #TODO: check that delta is appropriate
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

    #apply pixel mask if requested
    if pixelMask is not None:
        if mtd.doesExist(pixelMask):
            print(f"Applying pixel mask: {pixelMask}")
            MaskDetectors(Workspace=resWSName,
                           MaskedWorkspace=pixelMask,
                           )
        else:
            print(f"ERROR: pixel mask {pixelMask} does not exist")
            return
        
    # apply bin mask if requested
    print(f"will apply {len(binMaskList)} bin mask workspaces")
    for table in binMaskList:
        
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
    
    #Finally, apply d-limits to every spectrum by setting d values out of range to NAN
    ws = mtd[resWSName]
    spectrumInfo = ws.spectrumInfo()
    for pix in range(nPix):
        theta = spectrumInfo.twoTheta(pix)/2.0
        dMin = lamMin/(2*np.sin(theta)) + lowdSpacingCrop 
        dMax = lamMax/(2*np.sin(theta)) - highdSpacingCrop
        x = ws.dataX(pix)
        y = ws.dataY(pix)

        # Handle histogram vs point data
        if len(x) == len(y) + 1:
            x_centers = 0.5 * (x[:-1] + x[1:])
        else:
            x_centers = x

        #indices for bins within range
        inside = (x_centers >= dMin) & (x_centers <= dMax)
        
        #copy original y values, but set those outside range to be NAN
        y_new = np.array(y, dtype=float, copy=True)
        y_new[~inside] = np.nan
        ws.setY(pix, y_new)


    #Finally, GroupDetectors for all pgs present in ws handle. 
    # By selecting `Behaviour='Average'` populate
    # each grouped output spectrum to contain averaged del_d. 
    #
    # Note GroupDetectors does not handle NAN values properly, so created
    # GroupDetectorsIgnoreNAN instead.

    # resWSName = resWSName + "_nrm"

    for handle in handles:

        pgs = handle.pixelGroup

        if isLite:
            gpWSName = f"SNAPLite_grouping__{pgs}"
        else:
            gpWSName = f"SNAP_grouping__{pgs}"

        outWS = f"resolution_dsp_{pgs.lower()}_{str(runNumber).zfill(6)}"

        GroupDetectorsIgnoreNAN(resWSName, 
                                gpWSName, 
                                outWS,
                                behaviour="Average",
                                weightWorkspaceName="pixWeightsLite"
                                )

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

    # keep resolution workspaces, but tidy up into group
    GroupWorkspaces(InputWorkspaces=["d2t","delThetaPix","omega","delDOverD","pixWeightsLite"],OutputWorkspace="resolutionWorkspaces")

    return 

def file(nameKeys,operation="add",cabinetName="File_Cabinet"):

#creates a Workspace Group called cabinetName.
# if operation = "add" workspaces with specified nameKeys in their name will be added to group
# if operation = "remove" workspaces with specified nameKeys in their name will be removed from group
# if operation = "empty" cabinet will be emptied and removed
 
    if operation.lower() == "empty":
        if not mtd.doesExist(cabinetName):
            print(f"{cabinetName} doesn\'t exist cannot empty it")
            return
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
            if len(toBeFiled) == 0:
                print(f"No workspaces found with name keys {nameKeys}, so no cabinet created")
                return
            GroupWorkspaces(InputWorkspaces=toBeFiled,
                        OutputWorkspace=cabinetName)

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

def cleanTheTree(prefix="reduced",removePGS=None,deleteWorkspaces=False, verbose=False):
    
    # finds files with timestamps, creates a clone of the latest workspace without a timestamp
    # if cleanMode = "hide" the older workspaces are hidden else
    # if cleanMode = "delete" the older workspaces are deleted
    # if pgs is not None, specified pixel groups will also be cleaned.  
    
    reducedGroups = io.reducedRuns(prefix=prefix,
                                   cleanTreeOverride=False) #by setting cleanTreeOverride to False, we get all workspaces

    for redGroup in reducedGroups:

        runDict = redGroup.objectDict
        for pgs in runDict.keys():
            if verbose:
                print(f"Found pixel group: {pgs}")

            # identify latest workspace in group and rename it.
            latest = runDict[pgs][0] #redObject for most recent workspace
            _prefix_tag = f"{latest.prefix}-{latest.prefixNumberString}" if latest.prefixNumberString else latest.prefix
            wsKeep = f"{_prefix_tag}_{latest.units}_{latest.pixelGroup}_{latest.runNumberString}"
            if deleteWorkspaces:
                RenameWorkspace(InputWorkspace=latest.wsName,
                            OutputWorkspace=wsKeep)
            else:
                CloneWorkspace(InputWorkspace=latest.wsName,
                            OutputWorkspace=wsKeep)
                RenameWorkspace(InputWorkspace=latest.wsName,
                            OutputWorkspace=f"__{latest.wsName}")

            #Delete or hide any remaining workspaces. 
            if len(runDict[pgs]) > 1:
                for i in range(1,len(runDict[pgs])):
                    redObj = runDict[pgs][i]
                    if deleteWorkspaces == False:
                        RenameWorkspace(InputWorkspace=redObj.wsName,
                                        OutputWorkspace=f"__{redObj.wsName}")
                    else: 
                        DeleteWorkspace(redObj.wsName)

            if removePGS is None:
                continue

            # ensure pgs is a list
            if type(removePGS) != list:
                removePGS = [removePGS]

            #if pgs is specified, also clean those workspaces
            if pgs in removePGS:
                DeleteWorkspace(wsKeep)

    # to also support removing workspaces without timestamps that match removePGS need a second
    # pass through all workspaces

    if removePGS is None:
        return  

    reducedGroupsNoTimestamp = io.reducedRuns(prefix=prefix,
                                   cleanTreeOverride=True) #will only find workspaces without timestamps
    
    for redGroup in reducedGroupsNoTimestamp:
        
        runDict = redGroup.objectDict
        for pgs in runDict.keys():
            if pgs in removePGS:
                for redObj in runDict[pgs]:
                    DeleteWorkspace(redObj.wsName)

def revealHidden(prefix='reduced',
           units='dsp',
           PGS = None,
           runNumber=None):

    # function to unhide previously hidden workspaces

    handles = workspaceHandles(prefix=f"__{prefix}",
                              units=units,
                              PGS=PGS,
                              runNumber=runNumber,
                              latestOnly=False,
                              cleanTreeOverride=False) #finds all hidden workspaces with timestamps
    
    if handles is None:
        print("No hidden workspaces found")
        return

    for handle in handles:
        hiddenWSName = handle.wsName
        unhiddenWSName = hiddenWSName.replace(f"__{prefix}_",f"{prefix}_")
        # print(f"Unhiding workspace: {hiddenWSName} to {unhiddenWSName}")
        RenameWorkspace(InputWorkspace=hiddenWSName,
                        OutputWorkspace=unhiddenWSName)
    
    # if we are unhiding workspaces with timestamps we no longer need to keep any copies without timestamps

    reducedGroupsTS = io.reducedRuns(prefix=prefix,
                                   cleanTreeOverride=False)
    
    reducedGroupsNoTS = io.reducedRuns(prefix=prefix,
                                   cleanTreeOverride=True)
    
    for redGroupTS in reducedGroupsTS:
        
        runDictTS = redGroupTS.objectDict
        for pgs in runDictTS.keys():
            # for each pixel group in the timestamped group, check if there are any workspaces without timestamps
            redGroupNoTS = None
            for redGroupNT in reducedGroupsNoTS:
                if redGroupNT.runNumber == redGroupTS.runNumber:
                    redGroupNoTS = redGroupNT
                    break
            if redGroupNoTS is None:
                continue
            runDictNoTS = redGroupNoTS.objectDict
            if pgs in runDictNoTS.keys():
                for redObj in runDictNoTS[pgs]:
                    # print(f"Deleting non-timestamped workspace: {redObj.wsName}")
                    DeleteWorkspace(redObj.wsName)

def resample(sampleFactor=1,
             prefix='reduced',
             units='dsp',
             PGS = None,
             runNumber=None,
             allowSuffix=False,
             requiredSuffix=None):

    # function to downsample reduced workspaces

    reducedGroups = io.reducedRuns(prefix=prefix,
                                   units=units,
                                   PGS = PGS,
                                   runNumber=runNumber,
                                   exportFormats=[],
                                   allowSuffix=allowSuffix,
                                   requiredSuffix=requiredSuffix)

    if sampleFactor > 1:
        print(f"Warning: sampleFactor is > 1. This will upsample data which is lossy!")


    for redGroup in reducedGroups:

        runNumber = redGroup.runNumber
        runDict = redGroup.objectDict
        print(f"Resampling run: {runNumber} with {len(runDict)} pixel group(s)")

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

                cleanTree= WrapConfig.get("cleanTree")
                if cleanTree:
                    outWSName = f"resampled_{redObj.units}_{redObj.pixelGroup}_{redObj.runNumberString}"
                else:
                    outWSName = f"resampled_{redObj.units}_{redObj.pixelGroup}_{redObj.runNumberString}_{redObj.timeStamp}"

                print(f"outputWorkspace is: {outWSName}")
                RebinRagged(InputWorkspace=redObj.wsName,
                            OutputWorkspace=outWSName,
                            XMin = XMin,
                            XMax = XMax,
                            Delta = dsDelta,
                            )

def exportData(prefix='reduced',
               units='dsp',
               PGS = None,
               runNumber=None,
               iptsOverride=None,
               exportFormats=['gsa','xye','csv'],
               fileTag=None,
               latestOnly=True,
               gsaInstPrm=True,
               allowSuffix=False,
               requiredSuffix=None,
               ):
    
    #creates a list of reducedGroups then export using the requested export formats
    reducedGroups = io.reducedRuns(prefix = prefix,
                                   units = units,
                                   PGS = PGS,
                                   runNumber = runNumber,
                                   iptsOverride = iptsOverride,
                                   exportFormats = exportFormats,
                                   fileTag = fileTag,
                                   allowSuffix=allowSuffix,
                                   requiredSuffix=requiredSuffix)
    
    if len(reducedGroups) == 0:
        print("No matching reduced workspaces found. Check filters.")
        return

    io.exportReducedGroups(reducedGroups,latestOnly,gsaInstPrm)

def workspaceHandles(prefix="reduced",
                     units="dsp",
                     PGS=None,
                     runNumber=None,
                     latestOnly=True,
                     cleanTreeOverride = None,
                     allowSuffix=False,
                     requiredSuffix=None):

    # returns a list of redObjects for the requested workspaces matching arguments

    reducedList = io.reducedRuns(prefix=prefix,
                                 units=units,
                                 PGS=PGS,
                                 runNumber=runNumber,
                                 cleanTreeOverride=cleanTreeOverride,
                                 allowSuffix=allowSuffix,
                                 requiredSuffix=requiredSuffix)
    if not reducedList:
        print("No matching workspaces found. Check filters")
        return
    
    # process reducedRun dictionaries to create a list of of redObjects 
    handleList = []
    for red in reducedList:

        pgsList = red.objectDict.keys()
        for p in pgsList:
            if latestOnly:
                redObj = red.objectDict[p][0] # selects most recent workspace only 
                handleList.append(redObj)
            else:
                redObjects = [red.objectDict[p][i] for i in range(len(red.objectDict[p]))] #this is a list now
                handleList.extend(redObjects)

    return handleList
    
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
  

    # print("DEBUG: copying original pixel groups info here")
    # print("original pixelGroups object:", inputIngredients.pixelGroups)
    # print("Entire input ingredients:")
    # for name, value in vars(inputIngredients).items():
    #     print(f"{name} = {value!r}")

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

    dMins = []
    dMaxs = []
    dBins = []
    
    for pg in originalIngredients:
        if pg.focusGroup.name.lower() == pgName:
            for subgroup in pg.pixelGroupingParameters:
                params = pg.pixelGroupingParameters[subgroup]
                dMin = params.dResolution.minimum + Config["constants.CropFactors.lowdSpacingCrop"]
                dMax = params.dResolution.maximum - Config["constants.CropFactors.highdSpacingCrop"]
                dBin = params.dRelativeResolution/pg.nBinsAcrossPeakWidth
                dMins.append(dMin)
                dMaxs.append(dMax)
                dBins.append(-1*dBin) #ugh...
            break  # Found matching pixel group, no need to continue

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


_PROPAGATED_ENTRY_RE = re.compile(r"^\(copied from run:\S+ version:\d+\)")


def _is_propagated_entry(entry: dict) -> bool:
    """Return True if a calibration index entry was produced by propagateDifcal."""

    if not isinstance(entry, dict):
        return False

    comments = entry.get("comments", "")
    if not isinstance(comments, str):
        return False

    return bool(_PROPAGATED_ENTRY_RE.match(comments.strip()))


def _write_propagation_log(entry: dict) -> None:
    """Append a propagation event to calibrationHome/.logs/propagation_log.jsonl."""

    try:
        calibrationHome = Config["instrument.calibration.home"]
        logDir = os.path.join(calibrationHome, ".logs")
        os.makedirs(logDir, exist_ok=True)
        logPath = os.path.join(logDir, "propagation_log.jsonl")

        payload = dict(entry or {})
        payload.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
        payload.setdefault("linux_user", getpass.getuser())

        with open(logPath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception as e:
        printWarning(f"WARNING: failed to write propagation log entry: {e}")

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

    donorLatest = donorCalStatus.get("latestValidCalibrationDict", {})


    # if state is uncalibrated, stop. Nothing to propagate
    if not donorCalStatus["runIsCalibrated"]:
        print(f"ERROR: provided run number: {donorRunNumber} of state: {donorStateID} does not have a valid difcal")
        _write_propagation_log({
            "donorRunNumber": str(donorRunNumber),
            "donorStateID": donorStateID,
            "donorVersion": None,
            "donorCycleID": None,
            "recipientStateID": None,
            "recipientPreviousVersions": None,
            "newVersion": None,
            "outcome": "skipped_no_donor_calibration",
            "dryRun": not propagate,
            "error": None,
        })
        return

    if _is_propagated_entry(donorLatest):
        msg = (
            f"propagateDifcal — donor run {donorRunNumber} (state {donorStateID}) "
            f"has a propagated calibration as its latest valid entry "
            f"(version {donorLatest.get('version')}, comment: {donorLatest.get('comments', '')!r}). "
            "Propagating a propagated calibration is not permitted. "
            "Use the original measured calibration donor run instead."
        )
        try:
            Logger("snapwrap").error(msg)
        except Exception:
            print(f"ERROR: {msg}")

        _write_propagation_log({
            "donorRunNumber": str(donorRunNumber),
            "donorStateID": donorStateID,
            "donorVersion": donorLatest.get("version"),
            "donorCycleID": donorLatest.get("cycleID"),
            "recipientStateID": None,
            "recipientPreviousVersions": None,
            "newVersion": None,
            "outcome": "skipped_donor_is_propagated",
            "dryRun": not propagate,
            "error": None,
        })
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

    # Note: The calibration being propagated will become the latest calibration in the receiving state
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
        print("\nThese states will accept the donor calibration")
        for calStatus in recipientCalStatus:

            print("recipient:")
            for key in calStatus:
               
                print("    ",key," : ",calStatus[key])
            try:
                ssm.copyDifcal(donorCalStatus,calStatus,propagate)
                maxExistingVersion = max(entry["version"] for entry in calStatus["calibIndexList"])
                _write_propagation_log({
                    "donorRunNumber": str(donorRunNumber),
                    "donorStateID": donorStateID,
                    "donorVersion": donorLatest.get("version"),
                    "donorCycleID": donorLatest.get("cycleID"),
                    "recipientStateID": calStatus.get("stateID"),
                    "recipientPreviousVersions": calStatus.get("numberCalibrations"),
                    "newVersion": maxExistingVersion + 1,
                    "outcome": "success",
                    "dryRun": False,
                    "error": None,
                })
            except Exception as e:
                _write_propagation_log({
                    "donorRunNumber": str(donorRunNumber),
                    "donorStateID": donorStateID,
                    "donorVersion": donorLatest.get("version"),
                    "donorCycleID": donorLatest.get("cycleID"),
                    "recipientStateID": calStatus.get("stateID"),
                    "recipientPreviousVersions": calStatus.get("numberCalibrations"),
                    "newVersion": None,
                    "outcome": "error",
                    "dryRun": False,
                    "error": str(e),
                })
                raise
    else:
        print("\nPropagatation of calibration was not requested")
        for calStatus in recipientCalStatus:
            maxExistingVersion = max(entry["version"] for entry in calStatus["calibIndexList"])
            _write_propagation_log({
                "donorRunNumber": str(donorRunNumber),
                "donorStateID": donorStateID,
                "donorVersion": donorLatest.get("version"),
                "donorCycleID": donorLatest.get("cycleID"),
                "recipientStateID": calStatus.get("stateID"),
                "recipientPreviousVersions": calStatus.get("numberCalibrations"),
                "newVersion": maxExistingVersion + 1,
                "outcome": "dry_run",
                "dryRun": True,
                "error": None,
            })
        
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
    if WrapConfig.get("cleanTree"):
        cleanTheTree(prefix="reduced",
                     deleteWorkspaces=False)

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

class HookCollection:


    @staticmethod
    def doNothingHook(context):

        pass

    @staticmethod
    def BackgroundAttenuationCorrection(context, attenuationWSName=None, backgroundWSName=None):

        # TODO: validate input ws match sample workspace: need to be from same state
        # note this is post hook to preprocessReductionRecipe, so outputWS starts as unfocussed TOF
        # and needs to end this way too.

        if backgroundWSName is not None:

            # if background workspace is specified, subtract it before attenuation correction

            # background must be in TOF too

            context.mantidSnapper.ConvertUnits("",InputWorkspace=backgroundWSName,
                                            OutputWorkspace=backgroundWSName,
                                            Target="TOF")
            
            # rebin to match sample data

            context.mantidSnapper.RebinToWorkspace("",WorkspaceToRebin=backgroundWSName,
                                                WorkspaceToMatch=context.outputWs,
                                                OutputWorkspace=backgroundWSName,
                                                PreserveEvents=True) 

            # sample ws needs to be NBC here
            context.mantidSnapper.NormalizeByCurrentButTheCorrectWay("",
                                    InputWorkspace=context.outputWs,
                                    OutputWorkspace=context.outputWs)
            # and background too
            context.mantidSnapper.NormalizeByCurrentButTheCorrectWay("",
                                    InputWorkspace=backgroundWSName,
                                    OutputWorkspace=backgroundWSName)

            context.mantidSnapper.Minus("",LHSWorkspace=context.outputWs,
                                    RHSWorkspace=backgroundWSName,
                                    OutputWorkspace=context.outputWs)

        if attenuationWSName is not None:

            # if attenuation workspace is specified divide by it

            context.mantidSnapper.ConvertUnits("",InputWorkspace=context.outputWs,
                                            OutputWorkspace=context.outputWs,
                                            Target="Wavelength")

            context.mantidSnapper.RebinToWorkspace("",WorkspaceToRebin=attenuationWSName,
                                                WorkspaceToMatch=context.outputWs,
                                                OutputWorkspace=attenuationWSName,
                                                PreserveEvents=True) 

            context.mantidSnapper.Divide("",LHSWorkspace=context.outputWs,
                                    RHSWorkspace=attenuationWSName,
                                    OutputWorkspace=context.outputWs)

        context.mantidSnapper.ConvertUnits("",InputWorkspace=context.outputWs,
                                        OutputWorkspace=context.outputWs,
                                        Target="dSpacing")

        context.mantidSnapper.executeQueue()

    @staticmethod
    def cheeseMask(context, binMaskList):

        # this hook will take a list of bin mask table workspaces and run a maskBinsFromTable on each of these.

        for mask in binMaskList:
            # extract units from ws name (table workspaces don't have logs)
            maskUnits = mask.split("_")[-1]

            # check current units of workspace
            currentUnits = mtd[context.outputWs].getAxis(0).getUnit().unitID()
            if currentUnits != maskUnits:

                # ensure units of workspace match
                context.mantidSnapper.ConvertUnits(
                    f"Hook: Converting current units {currentUnits} to match Bin Mask with units of {maskUnits}",
                    InputWorkspace=context.outputWs,
                    Target=maskUnits,
                    OutputWorkspace=context.outputWs,
                )
            # mask bins
            context.mantidSnapper.MaskBinsFromTable(
                f"Hook: Masking bins on workspace {context.outputWs} using table {mask}",
                InputWorkspace=context.outputWs,
                MaskingInformation=mask,
                OutputWorkspace=context.outputWs,
            )
            if currentUnits != maskUnits:
                # convert back to original units
                context.mantidSnapper.ConvertUnits(
                    f"Hook: Converting units back to original {currentUnits}",
                    InputWorkspace=context.outputWs,
                    Target=currentUnits,
                    OutputWorkspace=context.outputWs,
                )

        context.mantidSnapper.CloneWorkspace("Hook: keep copy of masked unfocussed workspace",
                                             InputWorkspace=context.outputWs,
                                            OutputWorkspace=f"{context.outputWs}_unfoc_masked")
        context.mantidSnapper.executeQueue()



def reduce(runNumber,
               sampleEnv='none',
               pixelMaskIndex='none',
               binMaskList=[],
               YMLOverride='none',
               backgroundWSName = None,
               attenuationWSName = None,
               continueNoDifcal = False,
               continueNoVan = False,
               requireSameCycle = True,
               verbose=False,
               reduceData=True,
               keepUnfocussed=False,
               noNorm=False,
               emptyTrash=True, #remove temporary mantid workspaces at the end of reduction
               cisMode=False,
               focusGroupAllowList=None,
               qsp=False,
               linBin=0.01,
               removePGS=None,
               save=True):

    from mantid import config

    # Helper for consistent, graceful aborts when called from Mantid Workbench.
    # IMPORTANT: this does not raise, it just logs/prints and returns a sentinel
    # so that no traceback is produced by the surrounding interpreter.
    def _abort(msg: str):
        """Print/log a friendly error and signal that reduction failed.

        Callers must immediately return the result of this function from
        ``reduce`` so that the error does not propagate further.
        """
        try:
            from mantid.kernel import Logger  # type: ignore
            Logger("snapwrap").error(msg)
        except Exception:
            # Logger not critical in Workbench script context
            pass
        if msg == "":
            print(f"\nReduction aborted.\n")
        else:
            print(f"\nERROR: {msg}\nReduction aborted.\n")
        # Return empty list as no reduced workspacea were created. 
        return []

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

    #TODO: REMOVE YML REFERENCES

    if YMLOverride == 'none':
        defaultYML = os.path.join(os.path.dirname(__file__), "defaultRedConfig.yml") #this will live in repo
    else:
        defaultYML = YMLOverride

    snapwrapGlob = globalParams(defaultYML)

    #set global parameters
    useLiteMode=snapwrapGlob.useLiteMode
    pixelMasks = snapwrapGlob.pixelMasks
    convertUnitsTo = snapwrapGlob.convertUnitsTo

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # process calibration status and continue flags
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    print("Processing calibration status and continue flags...")

    #first catch dead ends, abort and return useful information

    #difcal
    calibrationStatus = ssm.isCalibrated(runNumber=runNumber,
                                         silent=True ,
                                         requireSameCycle=requireSameCycle, 
                                         isLite=useLiteMode)
    
    print(f"Difcal status: {calibrationStatus[0]}")
    print(f"Normcal status: {calibrationStatus[1]}")
    difcal = calibrationStatus[2]
    nrmcal = calibrationStatus[3]

    if not any([calibrationStatus[0],continueNoDifcal]):  # difcal is absent and fallback not requested
        printWarning('noDifcal',runNumber,difcal)
        return _abort(
            f""
        )
    
    #normcal
    if not any([calibrationStatus[1],continueNoVan,noNorm]):  # van is absent and fallback not requested
        printWarning('noNormcal',runNumber,nrmcal)
        return _abort(
            f""
        )

    continueFlags = ContinueWarning.Type.UNSET  # by default do not continue

    if continueNoVan and not noNorm:
        print("artificial normalisation requested in lieu of no normcal")
        artificialNormalizationIngredients = ArtificialNormalizationIngredients(
        peakWindowClippingSize = Config["constants.ArtificialNormalization.peakWindowClippingSize"],
        smoothingParameter=snapwrapGlob.AN_smoothingParameter,
        decreaseParameter=snapwrapGlob.AN_decreaseParameter,
        lss=snapwrapGlob.AN_lss
        )
    else:
        artificialNormalizationIngredients = None


    if continueNoDifcal and not (continueNoVan or noNorm):
        continueFlags = ContinueWarning.Type.MISSING_DIFFRACTION_CALIBRATION

    elif (continueNoVan or noNorm) and not continueNoDifcal:
        continueFlags = ContinueWarning.Type.MISSING_NORMALIZATION
    
    elif (continueNoVan or noNorm) and continueNoDifcal:
        continueFlags = ContinueWarning.Type.MISSING_NORMALIZATION
        continueFlags |= ContinueWarning.Type.MISSING_DIFFRACTION_CALIBRATION

    print("ContinueFlags")
    print(continueFlags)

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

    print("Calling reduction service")
    reductionService = ReductionService()
    interfaceController = InterfaceController()
    timestamp = reductionService.getUniqueTimestamp()

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
#process options that require SNAPRed hooks
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    #hook: background and attenuation correction

    if backgroundWSName is not None or attenuationWSName is not None: # do if either is true

        # print(f"backgroundWSName is: {backgroundWSName}")
        # print(f"attenuationWSName is: {attenuationWSName}")

        print("\nHOOK WILL BE APPLIED!!!!\n")
        #define hook
        hook = Hook(func=BackgroundAttenuationCorrection,
                    attenuationWSName = attenuationWSName, #TODO: correctly manage ws names 
                    backgroundWSName= backgroundWSName) #TODO: correctly manage ws names

        emptyHook = Hook(func=doNothingHook) #dummy doesn't do anything for now
        hooks = {
            "PostPreprocessReductionRecipe" : [hook, emptyHook]
        }

    if len(binMaskList) > 0:
        # currently doesn't do anything, just runs empty hook in PreprocessReductionRecipe

        print("\nBIN MASK HOOK WILL BE APPLIED!!!!\n")

        binMaskHook = Hook(func=HookCollection.cheeseMask,
                           binMaskList=binMaskList)

        hooks = {
            "PostPreprocessReductionRecipe" : [binMaskHook,binMaskHook]
        }
        
    else:
        hooks = None

    # pre-process option to specify focusGroupAllowList

    if focusGroupAllowList is not None:
        focusGroupAllowList = [s.capitalize() for s in focusGroupAllowList] # ensure capitilized strings

    # first create a request with focusGroupAllowList as None. This gives me all of the standard focus groups

    reductionRequest = ReductionRequest(
            runNumber=runNumber,
            useLiteMode=useLiteMode,
            timestamp=timestamp,
            continueFlags=continueFlags,
            pixelMasks=pixelMasks,
            keepUnfocused=keepUnfocussed,
            focusGroupAllowList=None,
            convertUnitsTo=convertUnitsTo,
            artificialNormalizationIngredients=artificialNormalizationIngredients,
            hooks = hooks,
        )
    
    # Now fetch these available groupings
    groupings = reductionService.fetchReductionGroupings(reductionRequest)
    pgs = groupings["focusGroups"]
    pgsNames = []
    for p in pgs:
        pgsNames.append(p.name)

    if focusGroupAllowList is not None:
        # check that all requested focus groups actually exist
        for fg in focusGroupAllowList:
            if fg not in pgsNames:
                print(f"ERROR: you requested focus group {fg} but this doesn\'t exist. Available groups are: {pgsNames}")
                print("Reduction Failed")
                return []

        # Now we can safely set the focus group allow list
        reductionRequest = ReductionRequest(
            runNumber=runNumber,
            useLiteMode=useLiteMode,
            timestamp=timestamp,
            continueFlags=continueFlags,
            pixelMasks=pixelMasks,
            keepUnfocused=keepUnfocussed,
            focusGroupAllowList=focusGroupAllowList,
            convertUnitsTo=convertUnitsTo,
            artificialNormalizationIngredients=artificialNormalizationIngredients,
            hooks = hooks,
        )

    # manually add focus groups to the request.
    groupings = reductionService.fetchReductionGroupings(reductionRequest)
    pgs = groupings["focusGroups"]
    reductionRequest.focusGroups = pgs

    # # print("Debug 1866, pixel group allow list = ",reductionRequest.focusGroupAllowList)

    snapRequest = SNAPRequest(path="/reduction",payload=reductionRequest,hooks=hooks)
    reductionService.validateReduction(reductionRequest)
    # manually add focus groups to the request.
    groupings = reductionService.fetchReductionGroupings(reductionRequest)
    pgs = groupings["focusGroups"]
    reductionRequest.focusGroups = pgs

    print("snapRequest:")
    print(snapRequest)

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # "fetchReductionGroceries" Loads necessary data (e.g. sample neutron data,
    # raw vanadium data, pixel group definitions, DIFCs
    # and pixel masks )
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    groceries = reductionService.fetchReductionGroceries(reductionRequest)

    groceries["groupingWorkspaces"] = groupings["groupingWorkspaces"]

    # print(groceries["inputWorkspace"])
    print("checking groceries")
    print(groceries)


    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    #  Load the metadata i.e. ingredients
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    # 1. load reduction ingredients
    # ingredients = reductionService.prepReductionIngredients(reductionRequest, groceries.get("combinedPixelMask",""))
    # print("DEBUG: modifying ingredients definition")

    ingredients = reductionService.prepReductionIngredients(reductionRequest)
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
        printWarning('noDifcal')
        return _abort("")#No diffraction calibration found. Provide calibration or set continueNoDifcal=True to proceed in diagnostic mode.")

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
    
    if normalizationRecord is None and not (continueNoVan or noNorm):
        printWarning('noNormcal')
        return _abort("No normalization (vanadium) calibration found. Provide normalization or set continueNoVan=True / noNorm=True to bypass.")

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # Pretty print useful information regarding reduction status
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> 

    allPixelGroups = []
    for ingredient in ingredients:   
        if ingredient[0] == "pixelGroups":
            for item in ingredient[1]:
                allPixelGroups.append(item.focusGroup.name)

    status = {
        "ingredients": ingredients,
        "stateID": stateID,
        "stateDict": stateDict,
        "allPixelGroups": allPixelGroups,
        "calibrationRecord": calibrationRecord,
        "calibrationPath": calibrationPath,
        "normalizationRecord": normalizationRecord,     
        "normalizationPath": normalizationPath,
        "runNumber": runNumber,
        "pixelMasks": pixelMasks,
        "binMaskList": binMaskList,
        "continueNoDifcal": continueNoDifcal,
        "continueNoVan": continueNoVan,
        "noNorm": noNorm,
    }
    printStatus(status)

    time.sleep(5) #pause to allow user to read status info

    #TODO: move to statusPrinter? 
    # obtain useful values from instrument state
    farmFresh = FarmFreshIngredients(
        runNumber=runNumber,
        useLiteMode=useLiteMode,
        focusGroups=[{"name":"All", "definition":""}], #pixel group irrelevant, so just choose one.
        state=stateID)
    instrumentState = SousChef().prepInstrumentState(farmFresh)

    if qsp:

        #prior to reduction, need to determine appropriate binning to match requested
        #Q-space binning

        originalIngredients,ingredients = updateBinForQ(ingredients,linBin)

        pgs = ingredients.pixelGroups

        for pg in pgs:

            for subgroup in pg.pixelGroupingParameters:
                params = pg.pixelGroupingParameters[subgroup]
                dMin = params.dResolution.minimum
                dMax = params.dResolution.maximum
                dBin = params.dRelativeResolution/pg.nBinsAcrossPeakWidth

    if reduceData:

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # Execute reduction here
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

        try:
            data = interfaceController.executeRequest(snapRequest).data
        except Exception as e:
            return _abort(f"Reduction execution failed: {type(e).__name__}: {e!r}")
        try:
            record = data.record
        except AttributeError:
            return _abort("Reduction failed: response missing reduction record attribute.")

        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        #  Save the data
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        if save:
            saveReductionRequest = ReductionExportRequest(
                record=record
            )

            reductionService.saveReduction(saveReductionRequest)

        printStatus(status)
    
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        #  if cleanTree, hide timstamped reduced workspaces.
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        cleanTree = WrapConfig.get("cleanTree")
        if cleanTree:
            cleanTheTree(removePGS=removePGS)
            cleanTheTree(prefix="diagnostic",removePGS=removePGS) #also clean diagnostic workspaces
            print("Time-stamped Workspaces have been hidden")
            outputWSList = [ws[:-18] for ws in data.record.workspaceNames]
        else:
            outputWSList = data.record.workspaceNames

    else:
        outputWSList = None

    if verbose:       
        verboseStatus(Config,instrumentState,ingredients)

    if qsp:
        # post reduction, need to convert d-space reduced data to Q-space

        outputWSList_Q = [] #reset to hold q-space names
        if outputWSList is not None:
            for dspName in [ws for ws in outputWSList if "pixelmask" not in ws]: #SNAPRed returns a pixel mask if there's a calib mask
                qspName = dspName.replace("_dsp_","_qsp_")
                ConvertUnits(InputWorkspace=dspName,
                            OutputWorkspace=qspName,
                            Target="MomentumTransfer")

                rebPrm = linBin*np.ones(mtd[qspName].getNumberHistograms())
                RebinRagged(InputWorkspace = qspName,
                            OutputWorkspace= qspName,
                            Delta = rebPrm) #ragged is needed as Qmin/max vary
                
                # lastly, downsample d-space data back to original request. have to handle possiblity
                # that we are in diagnostic mode.
                if any("diagnostic" in s for s in outputWSList):
                    handle = io.redObject(dspName, requiredPrefix='diagnostic')
                else:
                    handle = io.redObject(dspName)
                
                restoreDBins(handle,originalIngredients)

                outputWSList_Q.append(qspName)
            outputWSList = outputWSList_Q

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

    citation()
    config.setLogLevel(3, quiet=True)
    return outputWSList 


    

