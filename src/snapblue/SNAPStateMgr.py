# SNAPStateManager is a module for holding convenient functions for managing SNAP instrument states
#
import h5py
import sys
import json
from datetime import datetime
import os
import sys
import copy
import shutil
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# SNAPRed imports 
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

from snapred.backend.data.DataFactoryService import DataFactoryService
from snapred.meta.mantid.WorkspaceNameGenerator import WorkspaceNameGenerator as wng
from snapred.meta.Config import Config
from snapred.backend.data import LocalDataService as lds
from snapred.backend.data.LocalDataService import LocalDataService
from snapred.backend.dao.indexing.IndexEntry import IndexEntry


class SNAPHome():
   # main definition of calibration directory
   def __init__(self):
      self.calib = Config['instrument.calibration.home']
      self.powder = self.calib + "/Powder/"

def loadSNAPInstPrm():

  home = SNAPHome()
  instPrmJson = home + 'SNAPInstPrm.json' #to do update to take this parm from application.yml

  with open(instPrmJson, "r") as json_file:
    instPrm = json.load(json_file)
  return instPrm 

def stateDef(runNumber):
    #returns a list, first entry is stateID, second is dictionary of state parameters
    
    dataFactoryService = DataFactoryService()
    if type(runNumber) != str:
            runNumber=str(runNumber)

    stateID,detectorState = dataFactoryService.constructStateId(runNumber)

    stateDict = {
        "vdet_arc1" : float(round(detectorState.arc[0]*2))/2,
        "vdet_arc2" : float(round(detectorState.arc[1]*2))/2,
        "WavelengthUserReq" : float(round(detectorState.wav,1)),
        "Frequency" : int(round(detectorState.freq)),
        "Pos" : int(detectorState.guideStat)
    }

    return [stateID,stateDict]

def retrieveReductionRecord(redRecord):
    #returns a dictionary taken from the reduction record at path redPath

    with open(redRecord,'r') as file:
        recordDict = json.load(file)
    
    return recordDict


def checkStateExists(stateID):
  
  home = SNAPHome()
  powderHome = home.powder
  statePath = f"{powderHome}{stateID}/"

  return os.path.exists(statePath) 
 
def checkCalibrationStatus(stateID,isLite,calType):

    home = SNAPHome()
    powderHome = home.powder
    #dictionary to hold status
    calStatus = {
    "stateID":stateID,
    "calibrationType":calType,
    "isLite":isLite
    }

    #dictionaries to build paths for difference cases
    subFolder = {"difcal":'diffraction',
                "normcal":"normalization"}

    jsonName = {"difcal":"CalibrationIndex.json",
                "normcal":"NormalizationIndex.json"}

    firstIndex = {"difcal":1,
                 "normcal":0}    #annoyingly these are different

    #build paths
    if isLite:
        indexPath = f"{powderHome}{stateID}/lite/{subFolder[calType]}/{jsonName[calType]}"
    else:
        indexPath = f"{powderHome}{stateID}/native/{subFolder[calType]}/{jsonName[calType]}"

    #first check if index exists
    if not os.path.isfile(indexPath):
        calStatus["isCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibration"] = "never"
        
        return calStatus

    #if index exists, read it    
    f = open(indexPath)
    calIndex = json.load(f)
    f.close()    

    mostRecentCalibTS = 0
    mostRecentCalib = 0
    if len(calIndex) > firstIndex[calType]:
        calStatus["isCalibrated"] = True
        calStatus["numberCalibrations"] = len(calIndex)-firstIndex[calType]
        ts = calIndex[-1]["timestamp"]
        calStatus["latestCalibration"] = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
        calStatus["calibRuns"] = []
        
        for i,entry in enumerate(calIndex[firstIndex[calType]:]):
            calStatus["calibRuns"].append(entry["runNumber"])
            if entry["timestamp"]>= mostRecentCalibTS:
                mostRecentCalibTS = entry["timestamp"]
                mostRecentCalib = i + firstIndex[calType] #zeroth index is not counted

    else:
        calStatus["isCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibration"] = "never"

    calStatus["indexPath"] = indexPath
    calStatus["calibIndex"] = calIndex #list of calibrations


    calStatus["mostRecentCalib"] = calIndex[mostRecentCalib] #dict for most recent calibration
    return calStatus

def detectorConfig(stateDict,includeGuideStatus):

    #returns a unique ID for a given detector config. It only cares about
    #detector angles
    #
    #added optional flight-tube/guide status to definition of config

    import hashlib

    # print("detectorConfig:",stateDict)

    if includeGuideStatus:
        detectorDict = {
                "vdet_arc1" : stateDict["vdet_arc1"],
                "vdet_arc2" : stateDict["vdet_arc2"],
                "Pos" : stateDict["Pos"]}
    else:
        detectorDict = {
                "vdet_arc1" : stateDict["vdet_arc1"],
                "vdet_arc2" : stateDict["vdet_arc2"]}


    hasher = hashlib.shake_256()
    decodedKey = json.dumps(detectorDict).encode('utf-8')
    hasher.update(decodedKey)
    hashedKey = hasher.digest(4).hex()

    return hashedKey

def printCalibrationHome():

    home = SNAPHome()
    print(f"SNAPRed Calibration Home: {home.calib}")
    print(f"SNAPRed Powder Home: {home.powder}")
   
def availableStates():

    #list of non state folders within main calibration directory (just one atm)
    home = SNAPHome()
    powderHome = home.powder
    nonStateFolders = ['PixelGroupingDefinitions']

    #create list of state folders
    stateFolderList = [f for f in os.listdir(powderHome) if os.path.isdir(os.path.join(powderHome,f))]
    for nonState in nonStateFolders:
        stateFolderList.remove(nonState)

    return stateFolderList

def pullStateDict(stateIDString):

    #given a stateID as a string, will return a dictionary of state parameters

    stateSeedDir = f"{Config['instrument.calibration.home']}/Powder/{stateIDString}/lite/diffraction/v_0000/"
    stateParamsJson = stateSeedDir + "/CalibrationParameters.json"

    f = open(stateParamsJson)
    stateParamsJson = json.load(f)
    f.close()

    # This returns dictionary with different keys from defState. Convert the keys to 
    # match. Also, need to apply rounding that is used when generating state info.

    initDict = stateParamsJson["instrumentState"]["detectorState"]

    arc1 = float(round(initDict["arc"][0]*2)/2)
    arc2 = float(round(initDict["arc"][1]*2)/2)
    wav = float(round(initDict["wav"],1))
    freq = int(round(initDict["freq"] ))
    pos = int(initDict["guideStat"])

    finalDict = {"vdet_arc1" : arc1,
                 "vdet_arc2" : arc2,
                 "WavelengthUserReq" : wav,
                 "Frequency" : freq,
                 "Pos" : pos 
                 }

    return finalDict

def autoStateName(stateDict):


    arcStr1 = f"{stateDict['vdet_arc1']:.1f}".rjust(6)
    arcStr2 = f"{stateDict['vdet_arc2']:.1f}".rjust(6)
    lamStr = f"{stateDict['WavelengthUserReq']:.1f}".rjust(4)
    freqStr = f"{stateDict['Frequency']:.0f}".rjust(3)
    guideStr = str(stateDict['Pos']).rjust(2)
    name = f"{arcStr1}:{arcStr2}:{lamStr}:{freqStr}:{guideStr}"
    return name

def createState(runNumber,hrn='none'):

    stateID,stateDict = stateDef(runNumber)

    #only do anything if state doesn't exist
    if checkStateExists(stateID):
        print(f"state: {stateID} already exists. Nothing to do")
    else: 
        if hrn == 'none':
            hrn = autoStateName(stateDict) # if not specified, humanReadableName will be auto generated.

        print(f"Creating state {stateID} with name {hrn}")
        localDataService = lds.LocalDataService()
        #create both lite and native states:
        
        localDataService.initializeState(str(runNumber), True, hrn)

def copyDifcal(donor,dest,propagate=False): # refCal and Cal are CalibrationStatus dictionaries generated by checkCalibrationStatus

    donorCal = donor["mostRecentCalib"] #donor
    destCal = dest["mostRecentCalib"] #destination

    # print("DONOR")
    # for key in donorCal:
    #     print(key,donorCal[key])
    # print("DESTINATION")
    # for key in destCal:
    #     print(key,destCal[key])


    donorRun = donorCal["runNumber"]
    destRun = dest["calibIndex"][0]["runNumber"] #need instantiating run number to ensure it matches state
 
    print("\ncopying difcal...")
    print(f"\nDONOR STATE: {stateDef(donorRun)[0]} with {donor['numberCalibrations']} total calibrations")
    print(f"Most recent calibration is version {donorCal['version']} this will be copied:")


    # for key in refCalDict:
    #     print(f"{key} : {refCalDict[key]}")

    print(f"\nDESTINATION STATE: {stateDef(destRun)[0]} with {dest['numberCalibrations']} total calibrations")
    newVersion = destCal['version']+1
    print(f"Most recent calibration is version {destCal['version']} this will be updated to version {newVersion}")

    newIE = IndexEntry(version=newVersion, #one more than most recent
        runNumber=destCal["runNumber"],
        useLiteMode=donorCal["useLiteMode"],
        appliesTo = donorCal["appliesTo"],
        comments = f"(copied from run:{donorCal['runNumber']} version:{donorCal['version']})  original comments: {donorCal['comments']}",
        author = f"{donorCal['author']} (original author)",
        timestamp = donorCal['timestamp']
        )
    
    #build directory name and create directory
    donorVersion = donor["mostRecentCalib"]["version"]
    donorDir = f"{os.path.dirname(donor['indexPath'])}/v_{str(donorVersion).zfill(4)}"
    destDir = f"{os.path.dirname(dest['indexPath'])}/v_{str(newIE.version).zfill(4)}"

    print("\nFolder paths:")
    print("donor:",donorDir)
    print("dest:",destDir)

    if propagate:

        print(f"propagation requested, new calibration will be version {newIE.version}")

        #first check if folder exists
        if os.path.isdir(destDir):
            print(f"Error directory already exists: {destDir}")
            print("can\'t overwrite existing directory!") 
            print("Confirm versioning in calibration indexing is consistent with actual folders")
            return
        else: #safe to make a copy
            print("copying...")
            shutil.copytree(donorDir,destDir)
            os.remove(f"{destDir}/CalibrationRecord.json") # it will be replaced with franken CR
            os.remove(f"{destDir}/CalibrationParameters.json")
            print("reversioning...")
            #need to manually change version in file names
            reVersionDifcal(donorDir,destDir,donorRun,destRun)
            print(" - Calibration folder has been copied and reVersioned")
            print("updating destination calibration record...")            
            newCR = frankenRecord(donorRun=donorRun,
                donorVersion=donorVersion,
                destRun = destRun, #only used to define destination state
                destVersion = newIE.version,
                isLite=donorCal["useLiteMode"],
                printRecord=True #used for debugging
                )
            print("saving...")
            saveCalibrationRecord(newCR,newIE,destRun)
            print("COMPLETE - Calibration Record, Parameters and Index have been updated")

    if not propagate:
        print("Calibration was requested to not be propagated")

    return

def reVersionDifcal(donorDir,destDir,donorRun,destRun):

    # this function will conduct various operations to update version info between
    # a copied difcal folder and the original donor folder

    donorVersion = donorDir.split('/')[-1].split('_')[1]
    destVersion = destDir.split('/')[-1].split('_')[1]

    #rename one at a time:

    donorRun = str(donorRun).zfill(6)
    destRun = str(destRun).zfill(6)


    os.rename(f"{destDir}/dsp_column_{donorRun}_v{donorVersion.zfill(4)}.nxs.h5",
              f"{destDir}/dsp_column_{destRun}_v{destVersion.zfill(4)}.nxs.h5")
    
    os.rename(f"{destDir}/diffract_consts_{donorRun}_v{donorVersion.zfill(4)}.h5",
              f"{destDir}/diffract_consts_{destRun}_v{destVersion.zfill(4)}.h5")
    
    os.rename(f"{destDir}/diagnostic_column_{donorRun}_v{donorVersion.zfill(4)}.nxs.h5",
              f"{destDir}/diagnostic_column_{destRun}_v{destVersion.zfill(4)}.nxs.h5")

def loadCalibrationRecord(runNum,isLite,version):

    #read existing calibration record from disk

    if type(runNum) != str:
        runNum=str(runNum)    
    
    localDataService=LocalDataService()
    cr = localDataService.readCalibrationRecord(runNum,isLite,version)

    return cr

def saveCalibrationRecord(calibrationRecord,indexEntry,destinationRun):

    localDataService=LocalDataService()
    localDataService.writeCalibrationRecord(calibrationRecord,indexEntry)

    return

def frankenRecord(donorRun,
    donorVersion, destRun, destVersion, isLite, printRecord=False):

    from snapred.meta.mantid.WorkspaceNameGenerator import (
    WorkspaceType as wngt,
    )   

    #this will copy the calibration record (CR) corresponding to the state associated with "donorRun"
    #and with version "donorVersion". Then it will get the default calibration record ("v_0000")
    #corresponding to state of destRun. isLite must be the same for both.
    #
    #a copy is made of the donor CR is made, then its attributes updated.
    # The frankenCR is returned

    donorCR = loadCalibrationRecord(donorRun,isLite,donorVersion)

    destDefaultCR = loadCalibrationRecord(destRun,isLite,0)
    franken = copy.deepcopy(donorCR)

    print("copied original calibration record")

    franken.version = destVersion
    franken.runNumber = destRun
    franken.calculationParameters.version = destVersion
    franken.calculationParameters.instrumentState = destDefaultCR.calculationParameters.instrumentState
    franken.calculationParameters.seedRun = destDefaultCR.calculationParameters.seedRun
    franken.calculationParameters.creationDate = destDefaultCR.calculationParameters.creationDate
    franken.calculationParameters.name = destDefaultCR.calculationParameters.name
    #need to rewrite workspace names

    "Donor workspaces:"

    for ws in donorCR.workspaces:
        print(ws,donorCR.workspaces[ws],type(donorCR.workspaces[ws][0]))

    print("updating workspace names")
    franken.workspaces = {
        wngt.DIFFCAL_OUTPUT : [f"dsp_column_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}"],
        wngt.DIFFCAL_DIAG : [f"diagnostic_column_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}"],
        wngt.DIFFCAL_TABLE : [f"diffract_consts_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}"],
        wngt.DIFFCAL_MASK : [f"diffract_consts_mask_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}"]
    }

    
    # print(f"dsp_column_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}")
    # print(f"diagnostic_column_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}")
    # print(f"diffract_consts_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}")
    # print(f"diffract_consts_mask_{str(destRun).zfill(6)}_v{str(destVersion).zfill(4)}")


    if printRecord:
        print("FRANKEN RECORD:")
        print(franken.runNumber)
        print(franken.useLiteMode)
        print("version: ",franken.version)
        print("calculationParameters:")
        for par in franken.calculationParameters:
            print('\n')
            print(par)
        print("calculationParameters:")

        print("\ncrystalInfo\n")
        print(franken.crystalInfo)

        #pixelGroups
        print("\npixelGroups\n")
        print(franken.pixelGroups)

        #workspaces
        print("\nworkspaces")
        print(franken.workspaces)

    return franken
