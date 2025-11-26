# SNAPStateManager is a module for holding convenient functions for managing SNAP instrument states
#
import h5py
import sys
import json
from datetime import datetime
from dateutil import parser
import os
import sys
import copy
import shutil
import operator
import re
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

def stateDef(runNumber):
    #returns a list, first entry is stateID, second is dictionary of state parameters
    
    dataFactoryService = DataFactoryService()
    if type(runNumber) != str:
            runNumber=str(runNumber)

    stateID,detectorState = dataFactoryService.constructStateId(runNumber)

    schema = dataFactoryService.getInstrumentConfig(runNumber).stateIdSchema

    keys = [key for key in schema["properties"].keys() if not schema["properties"][key].get('ignore', False)]
    logs = dataFactoryService.getRunMetadata(runNumber)

    #only report used pvs (not all are used)
    stateDict = {
        key: logs[key] for key in keys
    }

    #convert arrays to values
    cleaned = {k: v.item() for k, v in stateDict.items()}


    return [stateID,cleaned]

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

def matchingCalibrationIndex(calIndexList, runNumber):

    # accept a presorted list of calibration index entries and a run number. Find the most recent
    # entry that has an "appliesTo" attribute that is consisten with runNumber

    # Define allowed operators
    ops = {
        '>': operator.gt,
        '>=': operator.ge,
        '<': operator.lt,
        '<=': operator.le,
        '==': operator.eq,
        '!=': operator.ne
    }

    #runNumber must be int and somehow isn't always

    runNumber = int(runNumber)

    calIndexList = sorted(enumerate(calIndexList), key=lambda x: x[1]['timestamp'], reverse=True)
   

    for original_index, entry in calIndexList:
        conditions = entry['appliesTo'].split(',')
        match = True

        for cond in conditions:
            cond = cond.strip()
            # Extract operator and number using regex
            match_obj = re.match(r'(>=|<=|==|!=|>|<)\s*(\d+)', cond)
            if not match_obj:
                match = False
                break

            op_str, value_str = match_obj.groups()
            value = int(value_str)

            # print("runNumber:",type(runNumber))
            # print("value", type(value))

            if not ops[op_str](runNumber, value):
                match = False
                break

        if match:
            return original_index

    return None  # No match found

def VBRunNumberFromVersion(calDict,calFolder):
        
        # the vanadium background (VB) run number is useful to have, but is not stored in the
        # calibration index, so need to locate this by inspecting the corresponding 
        # NormalizationRecord, which is indexed using the calibration version


        v = str(calDict["version"])
        latestNormcalRecordPath = f"{calFolder}v_{v.zfill(4)}/NormalizationRecord.json"

        #load normRecord
        f = open(latestNormcalRecordPath)
        normRec = json.load(f)
        f.close()

        return normRec["backgroundRunNumber"]

def isCalibrated(runNumber,isLite=True,silent=False):

    # returns tuple of booleans for difcal and normcal status respectively
    # values will only be true if valid calibration exists

    difcal = checkCalibrationStatus(runNumber, stateID=None,
                                    isLite=isLite, 
                                    calType="difcal")
    
    nrmcal = checkCalibrationStatus(runNumber, stateID=None,
                                    isLite=isLite, 
                                    calType="normcal")

    if silent:
        return (difcal["runIsCalibrated"],nrmcal["runIsCalibrated"])

    #otherwise print calibration status
    if difcal['runIsCalibrated']:
        print(f"difcal: is calibrated: {difcal['runIsCalibrated']} with run {difcal['latestValidCalibrationDict']['runNumber']} ")
    else:
        print(f"difcal: is calibrated: {difcal['runIsCalibrated']}")

    if nrmcal['runIsCalibrated']:
        print(f"nrmcal: is calibrated: {nrmcal['runIsCalibrated']} with run {nrmcal['latestValidCalibrationDict']['runNumber']} (and background {nrmcal['latestValidVBRunNumber']})")
    else:
        print(f"nrmcal: is calibrated: {nrmcal['runIsCalibrated']}")
    

    return (difcal["runIsCalibrated"],nrmcal["runIsCalibrated"])

def dateFromLinux(ts):

    # takes linux epoch time as a float and returns human readable string

    return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    
def checkCalibrationStatus(runNumber,stateID=None, isLite=True,calType="difcal"):

    # checks either difcal or normcal calibrations for a given state and `isLite` setting. Returns dictionary of useful
    # properties regarding these.
    
    # an initial version of this function tried to answer the question if a _state_ is calibrated. But, of course this is
    # incorrect as calibration is contingent on the sample run number satisfying an entry in the index. In the present
    # version, the main call is now a sample run number. 
    
    # it remains useful to pull general information for a state, so the possibility of runNumber == None is allowed. In this case
    # a stateID must be provided. If a runNumber is provided, it is not necessary to provide a stateID

    # To distinguish between most recent calibration versus most recent _valid_ calibration, additional keys are now added
    # and their names made more explicit  

    #try to fix incoming typos and case errors
    nrmAlt = ["nrmcal"]
    if calType.lower() in nrmAlt:
        calType = "normcal"

    if calType.lower() == "difcal":
        calType = "difcal"

    if calType != "difcal" and calType != "normcal":
        print("ERROR: unsupported calibration type selected. Options are difcal or normcal")
        return

    #determine stateID corresponding to run number 

    if runNumber is None:
        pass
    else: 
        [stateID, stateDict] = stateDef(runNumber)


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

    #build paths to calibration indices
    if isLite:
        calFolder = f"{powderHome}{stateID}/lite/{subFolder[calType]}/"
    else:
        calFolder = f"{powderHome}{stateID}/native/{subFolder[calType]}/"

    indexPath = f"{calFolder}{jsonName[calType]}"

    calStatus["calFolder"] = calFolder
    calStatus["indexPath"] = indexPath

    ## case: State does not exist
    if not checkStateExists(calStatus["stateID"]):
        calStatus["stateIsCalibrated"] = False
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibrationDate"] = "never"
        calStatus["latestCalibrationDict"] = {}
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        # print(f"Run: {runNumber} corresponds to stateID: {stateID}. This state does not exist so run is uncalibrated")
        
        return calStatus


    ##Case: normcal requested, state exists, but no normcal index exists
    if not os.path.isfile(indexPath) and calType=="normcal":
        calStatus["stateIsCalibrated"] = False
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibrationDate"] = "never"
        calStatus["latestCalibrationDict"] = {}
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        # print(f"Run: {runNumber} corresponds to stateID: {stateID}. State exists but has no normcal")
        
        return calStatus

    #load calibration index     
    f = open(indexPath)
    calIndexList = json.load(f) # a list of all calibrations
    f.close()


    ## case: difcal requested, state exists, but no difcal exists (only default)
    if len(calIndexList) == 1 and calType == "difcal":

        # a single calibration indicates that only the default geometric calibration exists
        # and the state is uncalibrated

        calStatus["calibIndexList"] = calIndexList
        calStatus["stateIsCalibrated"] = False
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibrationDate"] = "never"
        calStatus["latestCalibrationDict"] = calIndexList[0] # still need to have default index entry
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        # print(f"Run: {runNumber} corresponds to stateID: {stateID}. This state exists but only has default difcal")
        
        return calStatus

    # At this point, the state has some calibrations, but we don't know if any calibrations are valid for
    # the provided run number

    #useful to sort calIndexList in order of calibration timestamps, most recent first.
    #in snapred >v1.0.0 this was a float, in snapred >v2.0.0 it's a string. Check which and handle accordingly)

    #first gather all timestamps

    tsTypes = {type(d["timestamp"]) for d in calIndexList}

    if len(tsTypes) != 1:
        raise TypeError(f"Inconsistent timestamp types found in calibration index: {types}")

    t = tsTypes.pop()
    if t in (int, float):
        raise TypeError("Numeric timestamps are no longer supported (change since SNAPRed v2.0.0)")

    if t is not str:
        raise TypeError(f"Unexpected timestamp type: {t}. Since SNAPRed v2.0.0 calibration index timestamps must be strings")


    calIndexList.sort(key = lambda d: parser.parse(d["timestamp"]),
                      reverse=True
                      )

    calStatus["calibIndexList"] = calIndexList

    # If no runnumber only obtainable information relates to general state calibrations so return
    # with this

    if runNumber is None:
        calStatus["stateIsCalibrated"] = True
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = len(calStatus["calibIndexList"])-firstIndex[calType]
        calStatus["latestCalibrationDate"] = calStatus["calibIndexList"][0]["timestamp"].split(".")[0]
        calStatus["latestCalibrationDict"] = calStatus["calibIndexList"][0]
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        if calType == "normcal":
            calStatus["latestVBRunNumber"] = VBRunNumberFromVersion(calStatus["latestCalibrationDict"],calStatus["calFolder"])
            calStatus["latestValidVBRunNumber"] = None

        return calStatus

    # Now examine list of existing calibrations in order of date to find the most recent valid one considering the provided
    # run number. 

    validIndex = matchingCalibrationIndex(calStatus["calibIndexList"], runNumber)

    if validIndex is None:

        calStatus["stateIsCalibrated"] = True
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = len(calStatus["calibIndexList"])-firstIndex[calType]
        calStatus["latestCalibrationDate"] = calStatus["calibIndexList"][0]["timestamp"].split(".")[0]
        calStatus["latestCalibrationDict"] = calStatus["calibIndexList"][0]
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        if calType == "normcal":
            calStatus["latestVBRunNumber"] = VBRunNumberFromVersion(calStatus["latestCalibrationDict"],calStatus["calFolder"])
            calStatus["latestValidVBRunNumber"] = None

        return calStatus

    else:

        calStatus["stateIsCalibrated"] = True
        calStatus["runIsCalibrated"] = True
        calStatus["numberCalibrations"] = len(calStatus["calibIndexList"])-firstIndex[calType]
    
        calStatus["latestCalibrationDate"] = calStatus["calibIndexList"][0]["timestamp"].split(".")[0]
        calStatus["latestCalibrationDict"] = calStatus["calibIndexList"][0]
        calStatus["latestValidCalibrationDate"] = calStatus["calibIndexList"][validIndex]["timestamp"].split(".")[0]
        calStatus["latestValidCalibrationDict"] = calStatus["calibIndexList"][validIndex]
        if calType == "normcal":
            calStatus["latestVBRunNumber"] = VBRunNumberFromVersion(calStatus["latestCalibrationDict"],calStatus["calFolder"])
            calStatus["latestValidVBRunNumber"] = VBRunNumberFromVersion(calStatus["latestValidCalibrationDict"],calStatus["calFolder"])


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
                "det_arc1" : stateDict["det_arc1"],
                "det_arc2" : stateDict["det_arc2"],
                "BL3:Mot:OpticsPos:Pos" : stateDict["BL3:Mot:OpticsPos:Pos"]}
    else:
        detectorDict = {
                "det_arc1" : stateDict["det_arc1"],
                "det_arc2" : stateDict["det_arc2"]}


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

    #purge statefolders that don't have exactly 16 charater strings as names

    for folder in stateFolderList:
        if len(folder) != 16:
            stateFolderList.remove(folder)

    return stateFolderList

def pullStateDict(stateIDString):

    #given a stateID as a string, will return a dictionary of state parameters
    #this works by reading the default CalibrationParameters written when a state is created. 
    #
    # In SNAPRed v2.0.0 state ID calculation was overhauled to generalise, allowing additional
    # pv's to be designated as state pvs. This was required to implement 'BL3:Mot:OpticsPos:ExitSlit' 
    # as a new state pv.
    # As part of the overhaul, keys for the CalibrationParameters dictionary that holds state have changed
    # the plan is to create a script to  

    stateSeedDir = f"{Config['instrument.calibration.home']}/Powder/{stateIDString}/lite/diffraction/v_0000/"
    stateParamsJson = stateSeedDir + "/CalibrationParameters.json"

    f = open(stateParamsJson)
    stateParamsJson = json.load(f)
    f.close()

    detectorState = stateParamsJson["instrumentState"]["detectorState"]
    if "PVs" in detectorState.keys():
        dict = detectorState["PVs"]

        # have to manually remove keys that are not used
        if "det_lin1" in dict.keys():
            del dict["det_lin1"]
        if "det_lin2" in dict.keys():
            del dict["det_lin2"]

        # and manually convert int to float
        if dict["BL3:Det:TH:BL:Frequency"]:
            dict["BL3:Det:TH:BL:Frequency"] = float(dict["BL3:Det:TH:BL:Frequency"])

        return dict
    else:
        print("snapred v1.3.0 format CalibrationParameters found, converted to snapred v2.0.0 format")
        arc1 = float(round(detectorState["arc"][0]*2)/2)
        arc2 = float(round(detectorState["arc"][1]*2)/2)
        wav = float(round(detectorState["wav"],1))
        freq = float(round(detectorState["freq"] )) #note this was int, here change to float to be compatible. but I'm worried about 
                                                    #unexpected consequences if/when state hash is calculated using this
        pos = int(detectorState["guideStat"])

        dict = {"det_arc1" : arc1,
                    "det_arc2" : arc2,
                    "BL3:Chop:Skf1:WavelengthUserReq" : wav,
                    "BL3:Det:TH:BL:Frequency" : freq,
                    "BL3:Mot:OpticsPos:Pos" : pos 
                    }
        
        return dict


def autoStateName(stateDict):

    #to do generalise for arbitrary length of stateDict

    #use a map for abbreviated pv names
    map = {
        "det_arc1": "arc1", 
        "det_arc2": "arc2", 
        "BL3:Chop:Skf1:WavelengthUserReq": "wav", 
        "BL3:Det:TH:BL:Frequency": "freq", 
        "BL3:Mot:OpticsPos:Pos": "pos",
        "BL3:Mot:OpticsPos:ExitSlit": "slit", 
        #and some legacy names (which should go away after migration)
        "vdet_arc1": "arc1",
        "vdet_arc2": "arc2",
        "WavelengthUserReq": "wav",
        "Frequency" : "freq",
        "Pos" : "pos",
        "slit" : "slit"
    }

    name = ""
    for key in stateDict.keys():
        if map[key][0:-1] == "arc":
            name += f"{map[key]}:{stateDict[key]:6.1f}::"
        else:
            name += f"{map[key]}:{stateDict[key]}::"
    
    #strip final two colons
    name = name[:-2]

    #fix length
    name = f"{name:<59}"

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

def copyDifcal(donor,recipient,propagate=False): # donor and recipient are CalibrationStatus dictionaries generated by checkCalibrationStatus

    donorCal = donor["latestValidCalibrationDict"] #donor: This is the most recent 
    recipientCal = recipient["latestCalibrationDict"] #recipient: note, this will be default if state is uncalibrated

    donorRun = donorCal["runNumber"]
    recipientRun = recipient["calibIndexList"][0]["runNumber"] #need instantiating run number to ensure it matches state
 
    print("\ncopying difcal...")
    print(f"\nDONOR STATE: {stateDef(donorRun)[0]} with {donor['numberCalibrations']} total calibrations")
    print(f"Most recent valid calibration is version {donorCal['version']} this will be copied:")


    print(f"\nRECIPIENT STATE: {stateDef(recipientRun)[0]} with {recipient['numberCalibrations']} total calibrations")
    newVersion = recipientCal['version']+1
    print(f"Most recent calibration is version {recipientCal['version']} this will be updated to version {newVersion}")

    newIE = IndexEntry(version=newVersion, #one more than most recent
        runNumber=recipientCal["runNumber"],
        useLiteMode=donorCal["useLiteMode"],
        appliesTo = donorCal["appliesTo"],
        comments = f"(copied from run:{donorCal['runNumber']} version:{donorCal['version']})  original comments: {donorCal['comments']}",
        author = f"{donorCal['author']} (original author)",
        timestamp = donorCal['timestamp']
        )
    
    #build directory name and create directory
    donorVersion = donor["latestValidCalibrationDict"]["version"]
    donorDir = f"{os.path.dirname(donor['indexPath'])}/v_{str(donorVersion).zfill(4)}"
    recipientDir = f"{os.path.dirname(recipient['indexPath'])}/v_{str(newIE.version).zfill(4)}"

    print("\nFolder paths:")
    print("donor:",donorDir)
    print("recipient:",recipientDir)

    if propagate:

        print(f"propagation requested, this will create version {newIE.version} at: {os.path.dirname(recipient['indexPath'])}")

        #first check if folder exists
        if os.path.isdir(recipientDir):
            print(f"Error directory already exists: {recipientDir}")
            print("can\'t overwrite existing directory!") 
            print("Confirm versioning in calibration indexing is consistent with actual folders")
            return
        else: #safe to make a copy
            print("copying...")
            shutil.copytree(donorDir,recipientDir)
            # print("debug: at this point, donor folder has been copied ")
            # a = input("enter anything to continue:")
            os.remove(f"{recipientDir}/CalibrationRecord.json") # it will be replaced with franken CR
            os.remove(f"{recipientDir}/CalibrationParameters.json")
            # print("debug: at this point, CalibrationRecord and CalibrationParameters have been deleted")
            # a = input("enter anything to continue:")
            # assert False
            print("reversioning...")
            #need to manually change version in file names
            reVersionDifcal(donorDir,recipientDir,donorRun,recipientRun)
            print(" - Calibration folder has been copied and reVersioned")
            print("updating recipient calibration record...")            
            newCR = frankenRecord(donorRun=donorRun,
                donorVersion=donorVersion,
                recipientRun = recipientRun, #only used to define recipient state
                recipientVersion = newIE.version,
                isLite=donorCal["useLiteMode"],
                printRecord=True #used for debugging
                )
            print("saving...")
            saveCalibrationRecord(newCR,newIE)
            print("COMPLETE - Calibration Record, Parameters and Index have been updated")

    if not propagate:
        print("Calibration was requested to not be propagated")

    return

def reVersionDifcal(donorDir,recipientDir,donorRun,recipientRun):

    # this function will conduct various operations to update version info between
    # a copied difcal folder and the original donor folder

    donorVersion = donorDir.split('/')[-1].split('_')[1]
    recipientVersion = recipientDir.split('/')[-1].split('_')[1]

    #rename one at a time:

    donorRun = str(donorRun).zfill(6)
    recipientRun = str(recipientRun).zfill(6)


    os.rename(f"{recipientDir}/dsp_column_{donorRun}_v{donorVersion.zfill(4)}.nxs.h5",
              f"{recipientDir}/dsp_column_{recipientRun}_v{recipientVersion.zfill(4)}.nxs.h5")
    
    os.rename(f"{recipientDir}/diffract_consts_{donorRun}_v{donorVersion.zfill(4)}.h5",
              f"{recipientDir}/diffract_consts_{recipientRun}_v{recipientVersion.zfill(4)}.h5")
    
    os.rename(f"{recipientDir}/diagnostic_column_{donorRun}_v{donorVersion.zfill(4)}.nxs.h5",
              f"{recipientDir}/diagnostic_column_{recipientRun}_v{recipientVersion.zfill(4)}.nxs.h5")

def loadCalibrationRecord(runNum,isLite,version):

    #read existing calibration record from disk

    if type(runNum) != str:
        runNum=str(runNum)    

    id,dict = stateDef(runNumber=runNum)    
    
    localDataService=LocalDataService()
    cr = localDataService.readCalibrationRecord(runNum,isLite,id,version)

    return cr

def saveCalibrationRecord(calibrationRecord,indexEntry):

    localDataService=LocalDataService()
    localDataService.writeCalibrationRecord(calibrationRecord)#,indexEntry)

    return

def frankenRecord(donorRun,
    donorVersion, recipientRun, recipientVersion, isLite, printRecord=False):

    from snapred.meta.mantid.WorkspaceNameGenerator import (
    WorkspaceType as wngt,
    )   

    #this will copy the calibration record (CR) corresponding to the state associated with "donorRun"
    #and with version "donorVersion". Then it will get the default calibration record ("v_0000")
    #corresponding to state of recipientRun. isLite must be the same for both.
    #
    #a copy is made of the donor CR is made, then its attributes updated.
    # The frankenCR is returned

    donorCR = loadCalibrationRecord(donorRun,isLite,donorVersion)

    recipientDefaultCR = loadCalibrationRecord(recipientRun,isLite,0)
    franken = copy.deepcopy(donorCR)

    print("copied original calibration record")

    franken.version = recipientVersion
    franken.runNumber = recipientRun
    franken.calculationParameters.version = recipientVersion
    franken.calculationParameters.instrumentState = recipientDefaultCR.calculationParameters.instrumentState
    franken.calculationParameters.seedRun = recipientDefaultCR.calculationParameters.seedRun
    franken.calculationParameters.creationDate = recipientDefaultCR.calculationParameters.creationDate
    franken.calculationParameters.name = recipientDefaultCR.calculationParameters.name
    #need to rewrite workspace names

    "Donor workspaces:"

    for ws in donorCR.workspaces:
        print(ws,donorCR.workspaces[ws],type(donorCR.workspaces[ws][0]))

    print("updating workspace names")
    franken.workspaces = {
        wngt.DIFFCAL_OUTPUT : [f"dsp_column_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"],
        wngt.DIFFCAL_DIAG : [f"diagnostic_column_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"],
        wngt.DIFFCAL_TABLE : [f"diffract_consts_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"],
        wngt.DIFFCAL_MASK : [f"diffract_consts_mask_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"]
    }

    
    # print(f"dsp_column_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}")
    # print(f"diagnostic_column_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}")
    # print(f"diffract_consts_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}")
    # print(f"diffract_consts_mask_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}")


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
