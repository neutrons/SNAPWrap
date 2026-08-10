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

from snapwrap.cycleDates import (
    get_cycle_for_run,
    build_cycle_json,
    load_cycle_data,
    resolve_cycle_for_run,
    BEFORE_RECORD,
    UNDECIDED,
)


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

    #convert arrays to scalar values
    # - for single-element arrays: use .item()
    # - for multi-element arrays (legacy time-series logs): take last value
    # - for already-scalar values: use as-is
    def to_scalar(v):
        import numpy as np
        if isinstance(v, np.ndarray):
            return v.item() if v.size == 1 else v[-1].item()
        elif hasattr(v, 'item'):
            return v.item()
        return v

    cleaned = {k: to_scalar(v) for k, v in stateDict.items()}


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

def matchingCalibrationIndex(calIndexList, runNumber, requiredCycleID=None):

    # accept a presorted list of calibration index entries and a run number. Find the most recent
    # entry that has an "appliesTo" attribute that is consistent with runNumber.
    #
    # If requiredCycleID is not None, additionally require that the entry's
    # "cycleID" key matches requiredCycleID.  Entries without a "cycleID" key
    # are treated as matching (backwards-compatible).

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

            if not ops[op_str](runNumber, value):
                match = False
                break

        # If appliesTo matched, optionally enforce cycle restriction
        if match and requiredCycleID is not None:
            entryCycle = entry.get("cycleID")
            if entryCycle is not None and entryCycle != requiredCycleID:
                match = False

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

def isCalibrated(runNumber,isLite=True,silent=False,requireSameCycle=True):

    # returns tuple of booleans for difcal and normcal status respectively
    # values will only be true if valid calibration exists

    difcal = checkCalibrationStatus(runNumber, stateID=None,
                                    isLite=isLite, 
                                    calType="difcal",
                                    requireSameCycle=requireSameCycle)
    
    nrmcal = checkCalibrationStatus(runNumber, stateID=None,
                                    isLite=isLite, 
                                    calType="normcal",
                                    requireSameCycle=requireSameCycle)

    if silent:
        return (difcal["runIsCalibrated"],nrmcal["runIsCalibrated"],difcal,nrmcal)

    #otherwise print calibration status
    if difcal['runIsCalibrated']:
        print(f"difcal: is calibrated: {difcal['runIsCalibrated']} with run {difcal['latestValidCalibrationDict']['runNumber']} ")
    else:
        print(f"difcal: is calibrated: {difcal['runIsCalibrated']}")
        print(f"Reason: {difcal['statusDetail']}")

    if nrmcal['runIsCalibrated']:
        print(f"nrmcal: is calibrated: {nrmcal['runIsCalibrated']} with run {nrmcal['latestValidCalibrationDict']['runNumber']} (and background {nrmcal['latestValidVBRunNumber']})")
    else:
        print(f"nrmcal: is calibrated: {nrmcal['runIsCalibrated']}")
        print(f"Reason: {nrmcal['statusDetail']}")
    

    return (difcal["runIsCalibrated"],nrmcal["runIsCalibrated"],difcal,nrmcal)

def dateFromLinux(ts):

    # takes linux epoch time as a float and returns human readable string

    return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
    
def checkCalibrationStatus(runNumber,stateID=None, isLite=True,calType="difcal",requireSameCycle=True):

    # checks either difcal or normcal calibrations for a given state and `isLite` setting. Returns dictionary of useful
    # properties regarding these.
    
    # an initial version of this function tried to answer the question if a _state_ is calibrated. But, of course this is
    # incorrect as calibration is contingent on the sample run number satisfying an entry in the index. In the present
    # version, the main call is now a sample run number. 
    
    # it remains useful to pull general information for a state, so the possibility of runNumber == None is allowed. In this case
    # a stateID must be provided. If a runNumber is provided, it is not necessary to provide a stateID

    # To distinguish between most recent calibration versus most recent _valid_ calibration, additional keys are now added
    # and their names made more explicit

    # If requireSameCycle is True (default), a calibration is only considered valid for a run if the calibration's
    # run number belongs to the same facility operating cycle as the input run number. Set to False to allow
    # out-of-cycle calibrations to be used (legacy behaviour).

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
    elif stateID is None:
        [stateID, stateDict] = stateDef(runNumber)
    # else: both runNumber and stateID provided — use the explicit stateID
    # but keep runNumber for appliesTo / cycle matching


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
        calStatus["statusDetail"] = "state does not exist"
        
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
        calStatus["statusDetail"] = "state exists but has no normalization index"
        
        return calStatus

    #load calibration index
    try:
        with open(indexPath, 'r') as fh:
            calIndexList = json.load(fh)  # a list of all calibrations
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON in calibration index at {indexPath}: {e}")
        calStatus["stateIsCalibrated"] = False
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibrationDate"] = "never"
        calStatus["latestCalibrationDict"] = {}
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        calStatus["statusDetail"] = f"calibration index exists but contains invalid JSON: {indexPath}"
        return calStatus
    except Exception as e:
        print(f"ERROR: Unexpected error reading calibration index at {indexPath}: {type(e).__name__}: {e}")
        calStatus["stateIsCalibrated"] = False
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = 0
        calStatus["latestCalibrationDate"] = "never"
        calStatus["latestCalibrationDict"] = {}
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}
        calStatus["statusDetail"] = f"unexpected error reading calibration index: {indexPath}"
        return calStatus

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
        calStatus["statusDetail"] = "state exists but only has default (geometric) difcal"
        
        return calStatus

    # At this point, the state has some calibrations, but we don't know if any calibrations are valid for
    # the provided run number

    #useful to sort calIndexList in order of calibration timestamps, most recent first.
    #in snapred >v1.0.0 this was a float, in snapred >v2.0.0 it's a string. Check which and handle accordingly)

    #first gather all timestamps

    tsTypes = {type(d["timestamp"]) for d in calIndexList}

    if len(tsTypes) != 1:
        raise TypeError(f"Inconsistent timestamp types found in calibration index: {tsTypes}")

    t = tsTypes.pop()
    if t in (int, float):
        raise TypeError("Numeric timestamps are no longer supported (change since SNAPRed v2.0.0)")

    if t is not str:
        raise TypeError(f"Unexpected timestamp type: {t}. Since SNAPRed v2.0.0 calibration index timestamps must be strings")


    calIndexList.sort(key = lambda d: parser.parse(d["timestamp"]),
                      reverse=True
                      )

    # Annotate every index entry with its cycleID.
    # For propagated calibrations the runNumber field still contains the
    # *recipient* state's original run, not the donor run that was actually
    # used to produce the calibration.  The donor run is recorded in the
    # comments field as "(copied from run:<run> version:<ver>)".  We must
    # use the donor (effective) run for the cycle lookup so that the cycle
    # filter in matchingCalibrationIndex works correctly.
    _propagation_re = re.compile(r"\(copied from run:(\S+)\s+version:")
    for entry in calIndexList:
        if "cycleID" not in entry:
            comment = entry.get("comments", "")
            m = _propagation_re.match(comment)
            effectiveRun = m.group(1) if m else entry["runNumber"]
            entry["cycleID"] = get_cycle_for_run(effectiveRun)

    calStatus["calibIndexList"] = calIndexList

    # Determine the cycle for the input run number (None if runNumber is None).
    # resolve_cycle_for_run fails closed: a run it cannot place reports
    # BEFORE_RECORD or UNDECIDED rather than a bare None that would disable the
    # cycle filter altogether.
    runCycleID = None
    runCycleStatus = None
    runCycleDetail = None
    if runNumber is not None:
        resolution = resolve_cycle_for_run(runNumber)
        runCycleID = resolution.cycleID
        runCycleStatus = resolution.status
        runCycleDetail = resolution.detail
    calStatus["runCycleID"] = runCycleID
    calStatus["runCycleStatus"] = runCycleStatus
    calStatus["runCycleDetail"] = runCycleDetail

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
        calStatus["statusDetail"] = "no run number provided; general state info only"
        if calType == "normcal":
            calStatus["latestVBRunNumber"] = VBRunNumberFromVersion(calStatus["latestCalibrationDict"],calStatus["calFolder"])
            calStatus["latestValidVBRunNumber"] = None

        return calStatus

    # Now examine list of existing calibrations in order of date to find the most recent valid one considering the provided
    # run number. The cycle of the calibration must also match the cycle of the input run (if known) unless
    # requireSameCycle is False.

    # Fail closed when the run's cycle could not be established.  Previously an
    # unresolvable cycle yielded requiredCycleID=None, which disabled the cycle
    # filter altogether -- i.e. the case we are least sure about was the case
    # that got waved through.  A run whose cycle is undecided (acquired after
    # the last registered cycle) or that predates the cycle record now has no
    # valid calibration unless the caller explicitly passes
    # requireSameCycle=False.
    cycleUnresolved = requireSameCycle and runCycleStatus in (UNDECIDED, BEFORE_RECORD)

    if cycleUnresolved:
        validIndex = None
    else:
        effectiveCycleID = runCycleID if requireSameCycle else None
        validIndex = matchingCalibrationIndex(
            calStatus["calibIndexList"], runNumber, requiredCycleID=effectiveCycleID
        )

    if validIndex is None:

        calStatus["stateIsCalibrated"] = True
        calStatus["runIsCalibrated"] = False
        calStatus["numberCalibrations"] = len(calStatus["calibIndexList"])-firstIndex[calType]
        calStatus["latestCalibrationDate"] = calStatus["calibIndexList"][0]["timestamp"].split(".")[0]
        calStatus["latestCalibrationDict"] = calStatus["calibIndexList"][0]
        calStatus["latestValidCalibrationDate"] = "never"
        calStatus["latestValidCalibrationDict"] = {}

        # Determine *why* no valid calibration was found
        if cycleUnresolved:
            # Would anything have matched on appliesTo alone?  Reported so the
            # message distinguishes "nothing applies" from "something applies
            # but we cannot confirm it is in cycle".
            noCycleIndex = matchingCalibrationIndex(
                calStatus["calibIndexList"], runNumber, requiredCycleID=None
            )
            if noCycleIndex is not None:
                calStatus["statusDetail"] = (
                    f"cycle could not be established for run {runNumber}, so an "
                    f"out-of-cycle calibration cannot be ruled out ({runCycleDetail}). "
                    f"A calibration matching appliesTo does exist "
                    f"(cycle: {calStatus['calibIndexList'][noCycleIndex].get('cycleID', '?')}). "
                    "Pass requireSameCycle=False to use it anyway."
                )
            else:
                calStatus["statusDetail"] = (
                    f"cycle could not be established for run {runNumber} "
                    f"({runCycleDetail}), and no calibration matches appliesTo either"
                )
        elif requireSameCycle and runCycleID is not None:
            # Re-check without the cycle filter to see if appliesTo alone would have matched
            noCycleIndex = matchingCalibrationIndex(calStatus["calibIndexList"], runNumber, requiredCycleID=None)
            if noCycleIndex is not None:
                calStatus["statusDetail"] = (
                    f"valid calibration exists but is out of cycle "
                    f"(run cycle: {runCycleID}, "
                    f"calibration cycle: {calStatus['calibIndexList'][noCycleIndex].get('cycleID', '?')}). "
                    "Pass requireSameCycle=False to use it anyway."
                )
            else:
                calStatus["statusDetail"] = "calibrations exist but no matching run range in appliesTo"
        else:
            calStatus["statusDetail"] = "calibrations exist but no matching run range in appliesTo"

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
        calStatus["statusDetail"] = "valid calibration found"
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

    # force tolerance on specific pvs, backstory: sometimes these need to be pulled from CalibrationParameters instead of 
    # calculated via run number, tiny formatting changes can lead to sufficiently different values that cause this check to 
    # fail. States are considered to be compatible if detectors angles are _equal within tolerance_

    if "det_arc1" in stateDict.keys():
        stateDict["det_arc1"] = float(round(stateDict["det_arc1"]*2)/2)
    if "det_arc2" in stateDict.keys():
        stateDict["det_arc2"] = float(round(stateDict["det_arc2"]*2)/2)


    if includeGuideStatus:
        detectorDict = {
                "det_arc1" : stateDict["det_arc1"],
                "det_arc2" : stateDict["det_arc2"],
                "BL3:Mot:OpticsPos:Pos" : stateDict["BL3:Mot:OpticsPos:Pos"]}
        # if slitPV exists, include it too
        if "BL3:Mot:OpticsPos:ExitSlit" in stateDict.keys():
            detectorDict["BL3:Mot:OpticsPos:ExitSlit"] = stateDict["BL3:Mot:OpticsPos:ExitSlit"]

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
        if nonState not in stateFolderList:
            raise ValueError(
                f"Powder home directory invalid: '{nonState}' directory is absent "
                f"(expected at {os.path.join(powderHome, nonState)})"
            )
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
    stateParamsPath = os.path.join(stateSeedDir, "CalibrationParameters.json")

    # Read calibration parameters with robust error messages for common failure modes
    try:
        with open(stateParamsPath, 'r') as fh:
            stateParams = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: CalibrationParameters.json not found at: {stateParamsPath}")
        return {}
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON in CalibrationParameters.json at {stateParamsPath}: {e}")
        return {}
    except Exception as e:
        print(f"ERROR: Unexpected error reading {stateParamsPath}: {type(e).__name__}: {e}")
        return {}

    detectorState = stateParams["instrumentState"]["detectorState"]
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
    donorRun = donorCal["runNumber"]

    recipientCal = recipient["latestCalibrationDict"] #recipient: note, this will be default if state is uncalibrated
    recipientRun = recipient["calibIndexList"][0]["runNumber"] #need instantiating run number to ensure it matches state

    print("\nCopying difcal...")
    print(f"\nDONOR STATE: {stateDef(donorRun)[0]} with {donor['numberCalibrations']} total calibrations")
    print(f"Most recent valid calibration is version {donorCal['version']} this will be copied:")

    # Determine new version from the highest existing version number in the
    # index (NOT from the timestamp-sorted "latest" entry, because propagated
    # calibrations inherit the donor's timestamp which may predate the v0
    # creation timestamp).
    maxExistingVersion = max(entry["version"] for entry in recipient["calibIndexList"])
    newVersion = maxExistingVersion + 1

    # Recipient state is determined by via run number of version 0 calibration the "seedRun". This might not
    # be the most recent, so explicitly look for version = 0
    v0 = next((e for e in recipient["calibIndexList"] if e["version"] == 0), None)
    if v0 is not None:
        recipientSeedRun = v0["runNumber"]
    else:
        print("Error reading run number from recipient: ")

    print("DEBUG: RECIPIENT dictionary", recipient)

    print("recipiend seed run: ", recipientSeedRun)

    print(f"\nRECIPIENT STATE: {stateDef(recipientSeedRun)[0]} with {recipient['numberCalibrations']} total calibrations")
    print("DEBUG: ")
    print(f"Highest existing version is {maxExistingVersion}, this will be updated to version {newVersion}")

    # Use the current time as the timestamp for the propagated entry.
    # matchingCalibrationIndex selects the most-recent valid calibration
    # by timestamp, so inheriting the donor's (older) timestamp would
    # cause the new entry to be hidden behind entries with newer
    # timestamps.  Using "now" ensures the propagated calibration is
    # picked up immediately.
    #
    # Format must include timezone offset (e.g. "-0400") because
    # IndexEntry.parseTimestamp uses np.datetime64 which treats
    # timezone-naive strings as offsets from epoch.  The 9-digit
    # fractional seconds match SNAPRed's nanosecond-precision convention.

    _now = datetime.now().astimezone()
    propagationTimestamp = (
        _now.strftime("%Y-%m-%dT%H:%M:%S")
        + f".{_now.microsecond:06d}000"
        + _now.strftime("%z")
    )

    newIE = IndexEntry(version=newVersion, #one more than most recent
        runNumber=recipientSeedRun, #TODO: check logic, but seems only way to ensure from state
        useLiteMode=donorCal["useLiteMode"],
        appliesTo = donorCal["appliesTo"],
        comments = f"(copied from run:{donorCal['runNumber']} version:{donorCal['version']})  original comments: {donorCal['comments']}",
        author = f"{donorCal['author']} (original author)",
        timestamp = propagationTimestamp #time of propagation, not time of calibration
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

        # Step 1 — Build the frankenRecord in memory (no disk I/O).
        print("Building recipient calibration record...")
        newCR = frankenRecord(donorRun=donorRun,
            donorVersion=donorVersion,
            recipientRun = recipientSeedRun, #only used to define recipient state
            recipientVersion = newIE.version,
            isLite=donorCal["useLiteMode"],
            printRecord=True #used for debugging
            )

        # Step 2 — Save record (creates version folder, writes JSONs,
        # updates index).  SNAPRed's writeCalibrationRecord creates the
        # v_#### directory itself, so we must NOT pre-create it.
        print("\nSaving Calibration Record (creates folder, JSONs, index)...")
        saveCalibrationRecord(newCR,newIE)
        print(" - Calibration Record, Parameters and Index have been written")

        # Step 3 — Copy data files from donor, renaming run number and
        # version in the filenames.  JSON files are skipped because
        # saveCalibrationRecord already wrote the authoritative versions.
        print("Copying data files from donor...")
        _donorRun6 = str(donorRun).zfill(6)
        _recipRun6 = str(recipientSeedRun).zfill(6)
        _donorVtag = f"v{str(donorVersion).zfill(4)}"
        _recipVtag = f"v{str(newIE.version).zfill(4)}"
        for fname in os.listdir(donorDir):
            if fname.endswith(".json"):
                continue  # already written by saveCalibrationRecord
            newName = fname.replace(_donorRun6, _recipRun6).replace(_donorVtag, _recipVtag)
            shutil.copy2(os.path.join(donorDir, fname),
                         os.path.join(recipientDir, newName))
            if newName != fname:
                print(f"  {fname} -> {newName}")
            else:
                print(f"  {fname} (unchanged)")
        print("COMPLETE - propagation finished successfully")

    if not propagate:
        print("Calibration was requested to not be propagated")

    return

def renameDifcal(donorDir,recipientDir,donorRun,recipientRun):

    # this function renames copied donor file to update
    # Donor runNumber -> recipientRun
    # Donor version -> recipient version

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

    # Attach the indexEntry to the record; writeCalibrationRecord expects
    # a single CalibrationRecord whose .indexEntry is already set.
    calibrationRecord.indexEntry = indexEntry
    localDataService=LocalDataService()
    localDataService.writeCalibrationRecord(calibrationRecord)

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

    print("\nbuilding Franken record...")
    # print("copied original calibration record")

    franken.version = recipientVersion
    franken.runNumber = recipientRun
    franken.calculationParameters.version = recipientVersion
    franken.calculationParameters.instrumentState = recipientDefaultCR.calculationParameters.instrumentState
    franken.calculationParameters.seedRun = recipientDefaultCR.calculationParameters.seedRun
    franken.calculationParameters.creationDate = recipientDefaultCR.calculationParameters.creationDate
    franken.calculationParameters.name = recipientDefaultCR.calculationParameters.name

    #need to rewrite workspace names

    franken.workspaces = {
        wngt.DIFFCAL_OUTPUT : [f"dsp_column_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"],
        wngt.DIFFCAL_DIAG : [f"diagnostic_column_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"],
        wngt.DIFFCAL_TABLE : [f"diffract_consts_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"],
        wngt.DIFFCAL_MASK : [f"diffract_consts_mask_{str(recipientRun).zfill(6)}_v{str(recipientVersion).zfill(4)}"]
    }

    if printRecord:
        # print("\nFRANKEN RECORD:")
        print(f"Recipient runNumber: {franken.runNumber}")
        print(f"Recipient useLite: {franken.useLiteMode}")
        print(f"Recipient version: {franken.version}")

        print("\nDONOR workspaces:")
        for ws in donorCR.workspaces:
            print(ws,donorCR.workspaces[ws])
        print("\nRECIPIENT workspaces:")
        for ws in franken.workspaces:
            print(ws,franken.workspaces[ws]) 
        # print("calculationParameters:")
        # for par in franken.calculationParameters:
        #     print('\n')
        #     print(par)
        # print("calculationParameters:")

        # print("\ncrystalInfo\n")
        # print(franken.crystalInfo)

        # #pixelGroups
        # print("\npixelGroups\n")
        # print(franken.pixelGroups)

        # #workspaces
        # print("\nworkspaces")
        # print(franken.workspaces)

    
    print("\nFranken record built successfully")

    return franken


# ---------------------------------------------------------------------------
# Cycle-date helpers
# ---------------------------------------------------------------------------

def cycleForRun(runNumber):
    """Return the facility operating-cycle ID for a given SNAP run number.

    Parameters
    ----------
    runNumber : int or str
        The run number to look up.

    Returns
    -------
    str or None
        The cycleID (e.g. ``'2025-A'``), or ``None`` if the run
        predates all recorded cycles.

    Notes
    -----
    On first call the module reads (or builds) a JSON index from the
    ``cycleDates.ods`` spreadsheet in the calibration directory.
    Subsequent calls use the in-memory cache.
    """
    cycle = get_cycle_for_run(runNumber)
    if cycle is None:
        print(f"cycleDates: no cycle found for run {runNumber}")
    return cycle

def validateIndex(runNumber, stateID=None, isLite=True, calType="difcal", requireSameCycle=True):
    """Validate a calibration/normalization index and its version subfolders.

    Parameters mirror :func:`checkCalibrationStatus` so callers can pass a runNumber
    (or ``None`` with an explicit *stateID*) and the function will locate the
    appropriate index path.

    Checks performed
    ----------------
    1. Each index entry has exactly the 7 required keys.
    2. Versions start at 0 and increment by 1 with no gaps.
    3. A ``v_####`` subfolder exists for every index entry (and no extras).
    4. Version-folder contents match the expected file set (difcal / normcal).
    5. Record JSON (``CalibrationRecord.json`` or ``NormalizationRecord.json``)
       contains ``version`` and ``indexEntry`` that exactly match the index.
    6. All JSON files inside version folders are syntactically valid.
    7. The pixel-group string (pgs) inferred from filenames must correspond to
       one of the focus-group names defined in ``groupingMap.json``.
    8. Workspace names embedded in the calibration/normalization record must
       contain the correct ``_v####`` version tag matching the entry version.
    9. (difcal only) The v0 seed-run resolves back to this state's ID.
       A mismatch indicates cross-state contamination at creation time.

    Returns
    -------
    dict
        ``ok`` : bool – ``True`` only when every check passes.
        ``stateID`` : str
        ``calType`` : str
        ``isLite`` : bool
        ``indexPath`` : str
        ``issues`` : list[str] – top-level problems.
        ``entries`` : list[dict] – per-index-entry results, each with
        ``index``, ``version`` and ``issues`` keys.
    """

    # ------------------------------------------------------------------
    # Normalise calType (same logic as checkCalibrationStatus)
    # ------------------------------------------------------------------
    if calType.lower() in ("nrmcal",):
        calType = "normcal"
    if calType.lower() == "difcal":
        calType = "difcal"
    if calType not in ("difcal", "normcal"):
        raise ValueError("unsupported calibration type selected. Options are 'difcal' or 'normcal'")

    if runNumber is None and stateID is None:
        raise ValueError("Either runNumber or stateID must be provided")

    if runNumber is not None:
        [stateID, _] = stateDef(runNumber)

    # ------------------------------------------------------------------
    # Build paths (mirrors checkCalibrationStatus exactly)
    # ------------------------------------------------------------------
    home = SNAPHome()
    powderHome = home.powder

    subFolder = {"difcal": "diffraction", "normcal": "normalization"}
    jsonName  = {"difcal": "CalibrationIndex.json", "normcal": "NormalizationIndex.json"}

    liteStr = "lite" if isLite else "native"
    calFolder = f"{powderHome}{stateID}/{liteStr}/{subFolder[calType]}/"
    indexPath = f"{calFolder}{jsonName[calType]}"

    report = {
        "ok": True,
        "stateID": stateID,
        "calType": calType,
        "isLite": isLite,
        "indexPath": indexPath,
        "issues": [],
        "entries": [],
    }

    def _flag(msg, entry_report=None):
        """Record an issue and set ok = False."""
        if entry_report is not None:
            entry_report["issues"].append(msg)
        else:
            report["issues"].append(msg)
        report["ok"] = False

    def _note(msg, entry_report=None):
        """Record a non-fatal note (don't change overall ok status)."""
        if entry_report is not None:
            entry_report["issues"].append(msg)
        else:
            report["issues"].append(msg)

    # ------------------------------------------------------------------
    # Load allowed pgs names from groupingMap.json (case-insensitive)
    # ------------------------------------------------------------------
    grouping_map_path = os.path.join(powderHome, stateID, "groupingMap.json")
    allowed_pgs = set()  # lowercase names; empty if file missing
    if os.path.isfile(grouping_map_path):
        try:
            with open(grouping_map_path, "r") as fh:
                gmap = json.load(fh)
            key = "liteFocusGroups" if isLite else "nativeFocusGroups"
            for entry in gmap.get(key, []):
                allowed_pgs.add(entry["name"].lower())
        except Exception as e:
            _flag(f"Unable to parse groupingMap.json ({grouping_map_path}): {e}")
    else:
        _flag(f"groupingMap.json not found at {grouping_map_path} – pgs validation will be skipped")

    # ------------------------------------------------------------------
    # Basic existence checks
    # ------------------------------------------------------------------
    if not checkStateExists(stateID):
        _flag(f"State {stateID} does not exist at {powderHome}")
        return report

    if not os.path.isfile(indexPath):
        if calType == "normcal":
            # A missing normalization index is valid – it simply means the
            # state has not been normalized yet.
            report["issues"].append("No normalization index exists (state has not been normalized – this is OK)")
            return report
        _flag(f"Index file not found: {indexPath}")
        return report

    # ------------------------------------------------------------------
    # Load index JSON
    # ------------------------------------------------------------------
    try:
        with open(indexPath, "r") as fh:
            indexEntries = json.load(fh)
    except Exception as e:
        _flag(f"Failed to load index JSON {indexPath}: {type(e).__name__}: {e}")
        return report

    if not isinstance(indexEntries, list):
        _flag(f"Index content is not a list in {indexPath}")
        return report

    # ------------------------------------------------------------------
    # 1. Validate keys & collect versions
    # ------------------------------------------------------------------
    required_keys = {"version", "runNumber", "useLiteMode",
                     "appliesTo", "comments", "author", "timestamp"}

    versions = []
    for i, ie in enumerate(indexEntries):
        er = {"index": i, "version": ie.get("version"), "issues": []}

        if set(ie.keys()) != required_keys:
            missing_k = sorted(required_keys - set(ie.keys()))
            extra_k   = sorted(set(ie.keys()) - required_keys)
            parts = []
            if missing_k:
                parts.append(f"missing keys {missing_k}")
            if extra_k:
                parts.append(f"extra keys {extra_k}")
            _flag(f"Entry {i}: key mismatch – {', '.join(parts)}", er)

        if "version" in ie:
            try:
                versions.append(int(ie["version"]))
            except Exception:
                _flag(f"Entry {i}: 'version' is not an integer", er)
        else:
            _flag(f"Entry {i}: missing 'version' key", er)

        report["entries"].append(er)

    # ------------------------------------------------------------------
    # 2. Version stride check
    # ------------------------------------------------------------------
    if versions:
        sv = sorted(versions)
        if sv[0] != 0:
            _flag(f"Versions must start at 0; lowest version found: {sv[0]}")
        for a, b in zip(sv, sv[1:]):
            if b - a != 1:
                _flag(f"Non-consecutive versions: ...{a}, {b}... (gap of {b - a})")

    # ------------------------------------------------------------------
    # 9. Seed-run stateID consistency (difcal only)
    # ------------------------------------------------------------------
    # The v0 runNumber (the "seed run") must resolve back to the stateID
    # of this folder.  A mismatch means the v0 data was written against
    # the wrong state – the kind of cross-state contamination we saw
    # with state bf0a23ee5ae1549c.
    if calType == "difcal" and indexEntries:
        v0_entry = next((e for e in indexEntries if e.get("version") == 0), None)
        if v0_entry is not None:
            v0_run = v0_entry.get("runNumber")
            if v0_run is not None:
                try:
                    resolved_stateID, _ = stateDef(v0_run)
                    if resolved_stateID != stateID:
                        _flag(
                            f"v0 runNumber '{v0_run}' resolves to state "
                            f"'{resolved_stateID}', expected '{stateID}' – "
                            f"possible cross-state contamination"
                        )
                except Exception as e:
                    _flag(f"Unable to resolve v0 runNumber '{v0_run}' to a state: {e}")

    # ------------------------------------------------------------------
    # 3. Folder ↔ index correspondence
    # ------------------------------------------------------------------
    expected_folders = {f"v_{str(v).zfill(4)}" for v in versions}
    base_dir = os.path.dirname(indexPath)
    try:
        actual_items = os.listdir(base_dir)
    except Exception as e:
        _flag(f"Unable to list directory {base_dir}: {e}")
        return report

    actual_folders = {
        n for n in actual_items
        if os.path.isdir(os.path.join(base_dir, n)) and n.startswith("v_")
    }
    missing_folders = expected_folders - actual_folders
    extra_folders   = actual_folders - expected_folders
    if missing_folders:
        _flag(f"Missing version folders: {sorted(missing_folders)}")
    if extra_folders:
        _flag(f"Extra version folders with no index entry: {sorted(extra_folders)}")

    # ------------------------------------------------------------------
    # Helper: validate pgs against groupingMap
    # ------------------------------------------------------------------
    def _check_pgs(pgs, entry_report):
        """Warn if *pgs* is not a recognised focus-group name."""
        if allowed_pgs and pgs.lower() not in allowed_pgs:
            _flag(
                f"pgs '{pgs}' is not a recognised focus-group name "
                f"(allowed: {sorted(allowed_pgs)})",
                entry_report,
            )

    # ------------------------------------------------------------------
    # 4 – 6. Per-entry folder validation
    # ------------------------------------------------------------------
    for i, ie in enumerate(indexEntries):
        er = report["entries"][i]
        v = int(ie["version"]) if "version" in ie and isinstance(ie.get("version"), (int, float)) else -1
        if v == -1:
            # version already flagged above – skip folder checks
            continue

        run = str(ie.get("runNumber", "")).zfill(6)
        folder_name = f"v_{str(v).zfill(4)}"
        folder_path = os.path.join(base_dir, folder_name)

        if not os.path.isdir(folder_path):
            _flag(f"Version folder missing: {folder_name}", er)
            continue

        folder_contents = os.listdir(folder_path)

        # 5. Validate every JSON file found in the folder
        for fname in folder_contents:
            if fname.endswith(".json"):
                fp = os.path.join(folder_path, fname)
                try:
                    with open(fp, "r") as fh:
                        json.load(fh)
                except Exception as e:
                    _flag(f"Invalid JSON in {fname}: {e}", er)

        # ---- difcal ----
        if calType == "difcal":
            rec_name   = "CalibrationRecord.json"
            param_name = "CalibrationParameters.json"
            rec_fp   = os.path.join(folder_path, rec_name)
            param_fp = os.path.join(folder_path, param_name)

            # Record JSON
            if not os.path.isfile(rec_fp):
                _flag(f"Missing {rec_name}", er)
            else:
                try:
                    with open(rec_fp, "r") as fh:
                        rec = json.load(fh)
                    if not isinstance(rec, dict):
                        _flag(f"{rec_name} top-level value is not a dict", er)
                    else:
                        missing_version = "version" not in rec
                        missing_index = "indexEntry" not in rec
                        if missing_version and missing_index:
                            _flag(f"{rec_name} missing required keys 'version' and/or 'indexEntry'", er)
                        elif missing_version:
                            _flag(f"{rec_name} missing required key 'version'", er)
                        elif missing_index:
                            # Older SNAPRed-produced records (legacy format) may
                            # omit the embedded indexEntry. Treat these as a
                            # non-fatal note so they are tracked but don't make
                            # the whole index fail the validation pass.
                            _note(f"{rec_name} missing 'indexEntry' (legacy older record format) – treated as NOTE", er)
                        else:
                            if int(rec["version"]) != v:
                                _flag(f"{rec_name}.version ({rec['version']}) != folder version {v}", er)
                            if rec["indexEntry"] != ie:
                                _flag(f"{rec_name}.indexEntry does not exactly match the index entry", er)

                        # 8. Workspace names must embed the correct version tag
                        expected_vtag = f"_v{str(v).zfill(4)}"
                        workspaces = rec.get("workspaces")
                        if workspaces and isinstance(workspaces, dict) and v > 0:
                            for ws_key, ws_names in workspaces.items():
                                if isinstance(ws_names, list):
                                    for ws_name in ws_names:
                                        if isinstance(ws_name, str) and "_v" in ws_name and expected_vtag not in ws_name:
                                            _flag(
                                                f"{rec_name} workspace '{ws_name}' does not contain "
                                                f"expected version tag '{expected_vtag}'",
                                                er,
                                            )
                except json.JSONDecodeError:
                    pass  # already caught above
                except Exception as e:
                    _flag(f"Error reading {rec_name}: {e}", er)

            # Parameters JSON
            if not os.path.isfile(param_fp):
                _flag(f"Missing {param_name}", er)

            # Data files
            if v == 0:
                if not os.path.isfile(os.path.join(folder_path, "diffract_consts_default_v0.h5")):
                    _flag("Missing diffract_consts_default_v0.h5 for version 0", er)
            else:
                # Infer pgs from dsp_<pgs>_<run>_v<ver>.nxs.h5
                dsp_re = re.compile(rf"dsp_(.+)_{run}_v{str(v).zfill(4)}\.nxs\.h5")
                dsp_hits = [m for m in (dsp_re.fullmatch(f) for f in folder_contents) if m]
                if not dsp_hits:
                    _flag(f"No dsp_<pgs>_{run}_v{str(v).zfill(4)}.nxs.h5 found – cannot determine pgs", er)
                else:
                    pgs = dsp_hits[0].group(1)
                    _check_pgs(pgs, er)
                    for ef in (
                        f"dsp_{pgs}_{run}_v{str(v).zfill(4)}.nxs.h5",
                        f"diffract_consts_{run}_v{str(v).zfill(4)}.h5",
                        f"diagnostic_{pgs}_{run}_v{str(v).zfill(4)}.nxs.h5",
                    ):
                        if ef not in folder_contents:
                            _flag(f"Missing expected file: {ef}", er)

        # ---- normcal ----
        else:
            rec_name   = "NormalizationRecord.json"
            param_name = "NormalizationParameters.json"
            rec_fp   = os.path.join(folder_path, rec_name)
            param_fp = os.path.join(folder_path, param_name)

            # Record JSON
            if not os.path.isfile(rec_fp):
                _flag(f"Missing {rec_name}", er)
            else:
                try:
                    with open(rec_fp, "r") as fh:
                        rec = json.load(fh)
                    if not isinstance(rec, dict):
                        _flag(f"{rec_name} top-level value is not a dict", er)
                    else:
                        missing_version = "version" not in rec
                        missing_index = "indexEntry" not in rec
                        if missing_version and missing_index:
                            _flag(f"{rec_name} missing required keys 'version' and/or 'indexEntry'", er)
                        elif missing_version:
                            _flag(f"{rec_name} missing required key 'version'", er)
                        elif missing_index:
                            _note(f"{rec_name} missing 'indexEntry' (legacy older record format) – treated as NOTE", er)
                        else:
                            if int(rec["version"]) != v:
                                _flag(f"{rec_name}.version ({rec['version']}) != folder version {v}", er)
                            if rec["indexEntry"] != ie:
                                _flag(f"{rec_name}.indexEntry does not exactly match the index entry", er)

                        # 8. Workspace names must embed the correct version tag
                        expected_vtag = f"_v{str(v).zfill(4)}"
                        workspaces = rec.get("workspaces")
                        if workspaces and isinstance(workspaces, dict) and v > 0:
                            for ws_key, ws_names in workspaces.items():
                                if isinstance(ws_names, list):
                                    for ws_name in ws_names:
                                        if isinstance(ws_name, str) and "_v" in ws_name and expected_vtag not in ws_name:
                                            _flag(
                                                f"{rec_name} workspace '{ws_name}' does not contain "
                                                f"expected version tag '{expected_vtag}'",
                                                er,
                                            )

                except json.JSONDecodeError:
                    pass  # already caught above
                except Exception as e:
                    _flag(f"Error reading {rec_name}: {e}")

            # Parameters JSON
            if not os.path.isfile(param_fp):
                _flag(f"Missing {param_name}", er)

            # Data files – infer pgs from dsp_<pgs>_<run>_fitted_van_corr_v<ver>.nxs
            dsp_re = re.compile(rf"dsp_(.+)_{run}_fitted_van_corr_v{str(v).zfill(4)}\.nxs")
            dsp_hits = [m for m in (dsp_re.fullmatch(f) for f in folder_contents) if m]
            if not dsp_hits:
                _flag(f"No dsp_<pgs>_{run}_fitted_van_corr_v{str(v).zfill(4)}.nxs found – cannot determine pgs", er)
            else:
                pgs = dsp_hits[0].group(1)
                _check_pgs(pgs, er)
                for ef in (
                    f"tof_unfoc_{run}_raw_van_corr_v{str(v).zfill(4)}.nxs",
                    f"tof_{pgs}_s+f-vanadium_{run}_v{str(v).zfill(4)}.nxs",
                    f"dsp_{pgs}_{run}_fitted_van_corr_v{str(v).zfill(4)}.nxs",
                ):
                    if ef not in folder_contents:
                        _flag(f"Missing expected file: {ef}", er)

    return report


def printValidationReport(report):
    """Pretty-print a report dict returned by :func:`validateIndex`."""

    header = (
        f"{'PASS' if report['ok'] else 'FAIL'}  "
        f"state={report['stateID']}  calType={report['calType']}  "
        f"lite={report['isLite']}"
    )
    print(header)
    print(f"  index: {report['indexPath']}")

    if report["issues"]:
        label = "Issues:" if not report["ok"] else "Notes:"
        print(f"  {label}")
        marker = "✗" if not report["ok"] else "ℹ"
        for issue in report["issues"]:
            print(f"    {marker} {issue}")

    for er in report.get("entries", []):
        if er["issues"]:
            print(f"  Entry {er['index']} (version {er['version']}):")
            for issue in er["issues"]:
                print(f"    ✗ {issue}")

    if report["ok"]:
        n = len(report.get("entries", []))
        print(f"  All {n} entries validated successfully.")

    return


# ---------------------------------------------------------------------------
# Phase-2 repair utilities
# ---------------------------------------------------------------------------

def _backup_dir():
    """Return (and create) the central backup directory under the calibration home."""
    home = SNAPHome()
    bk = os.path.join(home.calib, "Backup")
    os.makedirs(bk, exist_ok=True)
    return bk


def _session_backup_dir(stateID, calType):
    """Return (and create) a timestamped per-session backup folder.

    Layout: ``{calib}/Backup/fix_{stateID}_{calType}_{YYYYMMDD_HHMMSS}/``
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(_backup_dir(), f"fix_{stateID}_{calType}_{stamp}")
    os.makedirs(d, exist_ok=True)
    return d


def _folder_stat_summary(folder_path):
    """Return a human-readable summary of a folder's timestamps and contents."""
    lines = []
    try:
        st = os.stat(folder_path)
        lines.append(f"  path:  {folder_path}")
        lines.append(f"  ctime: {datetime.fromtimestamp(st.st_ctime).isoformat()}")
        lines.append(f"  mtime: {datetime.fromtimestamp(st.st_mtime).isoformat()}")
        contents = sorted(os.listdir(folder_path))
        lines.append(f"  contents ({len(contents)} items):")
        for c in contents:
            fp = os.path.join(folder_path, c)
            sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
            lines.append(f"    {c}  ({sz} bytes)" if os.path.isfile(fp) else f"    {c}/")
    except Exception as e:
        lines.append(f"  (unable to stat: {e})")
    return "\n".join(lines)


def fixIndex(runNumber=None, stateID=None, isLite=True, calType="difcal",
             dryRun=False, autoConfirm=False):
    """Repair a calibration/normalization index so it passes :func:`validateIndex`.

    This function performs the following repairs **in order**:

    0. **Reconstruct empty/corrupt index** — if the index JSON file is
       empty or unparseable, attempt to rebuild the index by scanning
       version folders for ``CalibrationRecord.json`` (or
       ``NormalizationRecord.json``) and extracting each ``indexEntry``.
       Folders without a valid record are treated as orphans.

    1. **Sync record ``indexEntry``** — for every version folder whose
       ``CalibrationRecord.json`` (or ``NormalizationRecord.json``)
       ``indexEntry`` or ``version`` disagrees with the calibration index,
       overwrite the record to match the index.  Also updates the nested
       ``calculationParameters.indexEntry`` and
       ``calculationParameters.version`` copies.

    2. **Remove orphaned folders** — version folders on disk that have no
       matching index entry are deleted (after logging their contents and
       timestamps).

    3. **Remove orphaned index entries** — index entries whose version
       folder is missing are removed from the index.

    4. **Re-version** — after removals the remaining entries are
       re-numbered starting at 0 with stride 1.  Folders are renamed and
       all embedded version references (record JSON files, data-file
       names) are updated accordingly.

    A detailed log of every action is written to a session-specific
    backup folder under ``{calibration_home}/Backup/``.

    Parameters
    ----------
    runNumber, stateID, isLite, calType
        Same semantics as :func:`validateIndex`.
    dryRun : bool
        If ``True``, report what *would* be done without modifying anything.
    autoConfirm : bool
        If ``True``, skip the interactive confirmation prompt.

    Returns
    -------
    dict
        ``actions`` : list[str] – description of each action taken (or planned).
        ``logFile`` : str – path to the saved log file (``None`` in dry-run mode).
        ``backupDir`` : str – path to the backup session folder.
    """

    # ------------------------------------------------------------------
    # Resolve paths (identical to validateIndex)
    # ------------------------------------------------------------------
    if calType.lower() in ("nrmcal",):
        calType = "normcal"
    if calType.lower() == "difcal":
        calType = "difcal"
    if calType not in ("difcal", "normcal"):
        raise ValueError("calType must be 'difcal' or 'normcal'")
    if runNumber is None and stateID is None:
        raise ValueError("Either runNumber or stateID must be provided")
    if runNumber is not None:
        [stateID, _] = stateDef(runNumber)

    home = SNAPHome()
    powderHome = home.powder
    subFolder = {"difcal": "diffraction", "normcal": "normalization"}
    jsonName  = {"difcal": "CalibrationIndex.json", "normcal": "NormalizationIndex.json"}
    recName   = {"difcal": "CalibrationRecord.json", "normcal": "NormalizationRecord.json"}
    liteStr   = "lite" if isLite else "native"
    base_dir  = f"{powderHome}{stateID}/{liteStr}/{subFolder[calType]}"
    indexPath = os.path.join(base_dir, jsonName[calType])

    actions = []     # human-readable log lines
    prefix = "[DRY RUN] " if dryRun else ""

    def log(msg):
        actions.append(f"{prefix}{msg}")

    # ------------------------------------------------------------------
    # Pre-flight: run validateIndex to see current state
    # ------------------------------------------------------------------
    pre_report = validateIndex(runNumber=runNumber, stateID=stateID,
                               isLite=isLite, calType=calType)
    if pre_report["ok"]:
        log("Index already valid – nothing to fix.")
        return {"actions": actions, "logFile": None, "backupDir": None}

    # ------------------------------------------------------------------
    # Load index
    # ------------------------------------------------------------------
    if not os.path.isfile(indexPath):
        log(f"ERROR: Index file not found: {indexPath} – cannot repair.")
        return {"actions": actions, "logFile": None, "backupDir": None}

    index_was_reconstructed = False
    try:
        with open(indexPath, "r") as fh:
            content = fh.read().strip()
        if not content:
            raise json.JSONDecodeError("Empty file", "", 0)
        indexEntries = json.loads(content)
        if not isinstance(indexEntries, list):
            raise json.JSONDecodeError("Index is not a list", content, 0)
    except (json.JSONDecodeError, ValueError) as e:
        log(f"Index JSON is corrupt/empty: {e}")
        log("Attempting to reconstruct index from version folders...")

        # Scan version folders for record files that contain indexEntry
        indexEntries = []
        try:
            folder_names = sorted(
                n for n in os.listdir(base_dir)
                if os.path.isdir(os.path.join(base_dir, n)) and n.startswith("v_")
            )
        except Exception:
            folder_names = []

        for fn in folder_names:
            folder_path = os.path.join(base_dir, fn)
            rec_fp = os.path.join(folder_path, recName[calType])
            if os.path.isfile(rec_fp):
                try:
                    with open(rec_fp, "r") as rfh:
                        rec = json.load(rfh)
                    ie = rec.get("indexEntry")
                    if ie and isinstance(ie, dict) and "version" in ie:
                        indexEntries.append(ie)
                        log(f"  recovered indexEntry from {fn}/{recName[calType]} (version {ie['version']})")
                    else:
                        log(f"  {fn}/{recName[calType]} has no usable indexEntry – folder will be orphaned")
                except Exception as exc:
                    log(f"  failed to read {fn}/{recName[calType]}: {exc} – folder will be orphaned")
            else:
                log(f"  {fn} has no {recName[calType]} – folder will be orphaned")

        if not indexEntries:
            log("ERROR: Could not recover any index entries from version folders.")
            log("Manual intervention required (e.g. delete state and rebuild).")
            return {"actions": actions, "logFile": None, "backupDir": None}

        index_was_reconstructed = True
        log(f"Reconstructed index with {len(indexEntries)} entries from version folders.")

    # ------------------------------------------------------------------
    # Create backup session
    # ------------------------------------------------------------------
    sessionDir = _session_backup_dir(stateID, calType)
    log(f"Backup session: {sessionDir}")

    # Back up the original index
    bkIndex = os.path.join(sessionDir, jsonName[calType])
    if not dryRun:
        shutil.copy2(indexPath, bkIndex)
    log(f"Backed up original index → {bkIndex}")

    # ------------------------------------------------------------------
    # Discover orphaned folders and orphaned index entries
    # ------------------------------------------------------------------
    indexed_versions = {}  # version -> index entry
    for ie in indexEntries:
        indexed_versions[int(ie["version"])] = ie

    actual_folders = {
        n for n in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, n)) and n.startswith("v_")
    }
    actual_versions = {}
    for fn in actual_folders:
        try:
            actual_versions[int(fn.split("_")[1])] = fn
        except (ValueError, IndexError):
            pass

    orphaned_folders = sorted(set(actual_versions.keys()) - set(indexed_versions.keys()))
    orphaned_entries = sorted(set(indexed_versions.keys()) - set(actual_versions.keys()))

    # ------------------------------------------------------------------
    # Detect corrupt entries: folder exists but data files are wrong
    # ------------------------------------------------------------------
    # Use the per-entry issues from the validation report to identify
    # entries whose version folder is present but whose contents are
    # irrecoverably inconsistent (e.g. data files have the wrong run
    # number).  These are treated the same as orphaned entries + orphaned
    # folders: both the folder and the index entry are removed.
    corrupt_versions = []
    for er in pre_report.get("entries", []):
        v = er.get("version")
        if v is None or int(v) in set(orphaned_folders) | set(orphaned_entries):
            continue
        # Look for issues that indicate the folder data is unusable
        for issue in er.get("issues", []):
            if any(marker in issue for marker in [
                "cannot determine pgs",
                "Missing expected file:",
                "Missing CalibrationRecord.json",
                "Missing NormalizationRecord.json",
                "Missing CalibrationParameters.json",
                "Missing NormalizationParameters.json",
            ]):
                corrupt_versions.append(int(v))
                break

    # ------------------------------------------------------------------
    # Build action plan summary for user confirmation
    # ------------------------------------------------------------------
    plan_lines = []

    # Step 1: record syncs (only for entries not already marked corrupt)
    corrupt_set = set(corrupt_versions)
    sync_targets = []
    for ie in indexEntries:
        v = int(ie["version"])
        if v in corrupt_set:
            continue  # will be deleted, no point syncing
        folder_path = os.path.join(base_dir, f"v_{str(v).zfill(4)}")
        rec_fp = os.path.join(folder_path, recName[calType])
        if not os.path.isfile(rec_fp):
            continue
        try:
            with open(rec_fp, "r") as fh:
                rec = json.load(fh)
            needs_sync = False
            if rec.get("indexEntry") != ie:
                needs_sync = True
            if int(rec.get("version", -1)) != v:
                needs_sync = True
            if needs_sync:
                sync_targets.append((v, ie, rec_fp))
        except Exception:
            pass

    if sync_targets:
        plan_lines.append(f"  Sync indexEntry in {len(sync_targets)} record(s): versions {[t[0] for t in sync_targets]}")

    if corrupt_versions:
        for v in corrupt_versions:
            fp = os.path.join(base_dir, f"v_{str(v).zfill(4)}")
            ie = indexed_versions[v]
            plan_lines.append(f"  DELETE corrupt entry v={v} (run {ie.get('runNumber')}) – folder & index entry: {fp}")

    if orphaned_folders:
        for v in orphaned_folders:
            fp = os.path.join(base_dir, actual_versions[v])
            plan_lines.append(f"  DELETE orphaned folder (no index entry): {fp}")

    if orphaned_entries:
        plan_lines.append(f"  Remove {len(orphaned_entries)} orphaned index entries (no folder): versions {orphaned_entries}")

    # Check if re-versioning needed
    all_removed = set(orphaned_entries) | corrupt_set
    surviving = sorted(set(indexed_versions.keys()) - all_removed)
    needs_reversion = surviving != list(range(len(surviving)))

    if needs_reversion:
        plan_lines.append(f"  Re-version {len(surviving)} entries: {surviving} → {list(range(len(surviving)))}")

    if not plan_lines:
        log("No actionable repairs identified (issues may require manual intervention).")
        return {"actions": actions, "logFile": None, "backupDir": sessionDir}

    # ------------------------------------------------------------------
    # Confirm with user
    # ------------------------------------------------------------------
    print(f"\n{'[DRY RUN] ' if dryRun else ''}Repair plan for state={stateID}  calType={calType}  lite={isLite}:")
    for line in plan_lines:
        print(line)
    print()

    if not dryRun and not autoConfirm:
        answer = input("Proceed with repairs? [y/N]: ").strip().lower()
        if answer != "y":
            log("User declined repairs.")
            print("Aborted.")
            return {"actions": actions, "logFile": None, "backupDir": sessionDir}

    # ------------------------------------------------------------------
    # Step 1: Sync record indexEntry to match index
    # ------------------------------------------------------------------
    for v, ie, rec_fp in sync_targets:
        log(f"Syncing {recName[calType]} in v_{str(v).zfill(4)} to match index entry")
        if not dryRun:
            # Back up the original record
            rec_bk = os.path.join(sessionDir, f"v_{str(v).zfill(4)}_{recName[calType]}")
            shutil.copy2(rec_fp, rec_bk)

            with open(rec_fp, "r") as fh:
                rec = json.load(fh)

            rec["version"] = int(ie["version"])
            rec["indexEntry"] = ie
            if "calculationParameters" in rec and isinstance(rec["calculationParameters"], dict):
                rec["calculationParameters"]["indexEntry"] = ie
                rec["calculationParameters"]["version"] = int(ie["version"])

            with open(rec_fp, "w") as fh:
                json.dump(rec, fh, indent=4)

            log(f"  backed up original → {rec_bk}")
            log(f"  updated {rec_fp}")

    # ------------------------------------------------------------------
    # Step 2: Delete orphaned folders (no index entry)
    # ------------------------------------------------------------------
    for v in orphaned_folders:
        folder_path = os.path.join(base_dir, actual_versions[v])
        log(f"Deleting orphaned folder: {folder_path}")
        log(_folder_stat_summary(folder_path))
        if not dryRun:
            shutil.rmtree(folder_path)
            log(f"  deleted.")

    # ------------------------------------------------------------------
    # Step 3: Delete corrupt entries (folder + index entry)
    # ------------------------------------------------------------------
    for v in corrupt_versions:
        folder_path = os.path.join(base_dir, f"v_{str(v).zfill(4)}")
        ie = indexed_versions[v]
        log(f"Deleting corrupt entry v={v} (run {ie.get('runNumber')})")
        log(_folder_stat_summary(folder_path))
        if not dryRun:
            if os.path.isdir(folder_path):
                shutil.rmtree(folder_path)
                log(f"  deleted folder.")
            indexEntries = [e for e in indexEntries if int(e["version"]) != v]
            log(f"  removed index entry for version {v}.")

    # ------------------------------------------------------------------
    # Step 4: Remove orphaned index entries (no folder)
    # ------------------------------------------------------------------
    if orphaned_entries:
        log(f"Removing orphaned index entries for versions: {orphaned_entries}")
        if not dryRun:
            remove_set = set(orphaned_entries)
            indexEntries = [ie for ie in indexEntries if int(ie["version"]) not in remove_set]

    # ------------------------------------------------------------------
    # Step 5: Re-version remaining entries and folders
    # ------------------------------------------------------------------
    # Sort by current version
    indexEntries.sort(key=lambda ie: int(ie["version"]))

    old_to_new = {}
    for new_v, ie in enumerate(indexEntries):
        old_v = int(ie["version"])
        if old_v != new_v:
            old_to_new[old_v] = new_v

    if old_to_new:
        log(f"Re-versioning: {old_to_new}")

        if not dryRun:
            # Rename folders: use a temporary name first to avoid collisions
            # e.g. v_0003 -> v_0003_tmp -> v_0001
            temp_names = {}
            for old_v, new_v in old_to_new.items():
                old_folder = os.path.join(base_dir, f"v_{str(old_v).zfill(4)}")
                tmp_folder = os.path.join(base_dir, f"v_{str(old_v).zfill(4)}_tmp")
                if os.path.isdir(old_folder):
                    os.rename(old_folder, tmp_folder)
                    temp_names[new_v] = tmp_folder
                    log(f"  renamed v_{str(old_v).zfill(4)} → v_{str(old_v).zfill(4)}_tmp")

            for new_v, tmp_folder in temp_names.items():
                new_folder = os.path.join(base_dir, f"v_{str(new_v).zfill(4)}")
                os.rename(tmp_folder, new_folder)
                log(f"  renamed {os.path.basename(tmp_folder)} → v_{str(new_v).zfill(4)}")

        # Update version in index entries
        for new_v, ie in enumerate(indexEntries):
            old_v = int(ie["version"])
            if old_v != new_v:
                log(f"  index entry version {old_v} → {new_v}")
            ie["version"] = new_v

        # Update records inside re-versioned folders
        if not dryRun:
            for new_v, ie in enumerate(indexEntries):
                old_v_for_rec = None
                for ov, nv in old_to_new.items():
                    if nv == new_v:
                        old_v_for_rec = ov
                        break

                folder_path = os.path.join(base_dir, f"v_{str(new_v).zfill(4)}")
                rec_fp = os.path.join(folder_path, recName[calType])
                if os.path.isfile(rec_fp):
                    try:
                        with open(rec_fp, "r") as fh:
                            rec = json.load(fh)
                        rec["version"] = new_v
                        rec["indexEntry"] = ie
                        if "calculationParameters" in rec and isinstance(rec["calculationParameters"], dict):
                            rec["calculationParameters"]["indexEntry"] = ie
                            rec["calculationParameters"]["version"] = new_v

                        # Update workspace names: replace old version tag with new
                        if old_v_for_rec is not None and "workspaces" in rec and isinstance(rec["workspaces"], dict):
                            old_vtag = f"_v{str(old_v_for_rec).zfill(4)}"
                            new_vtag = f"_v{str(new_v).zfill(4)}"
                            for ws_key, ws_names in rec["workspaces"].items():
                                if isinstance(ws_names, list):
                                    rec["workspaces"][ws_key] = [
                                        name.replace(old_vtag, new_vtag) if isinstance(name, str) else name
                                        for name in ws_names
                                    ]
                            log(f"  updated workspace names in v_{str(new_v).zfill(4)}: {old_vtag} → {new_vtag}")

                        with open(rec_fp, "w") as fh:
                            json.dump(rec, fh, indent=4)
                        log(f"  updated record in v_{str(new_v).zfill(4)}")
                    except Exception as e:
                        log(f"  WARNING: could not update record in v_{str(new_v).zfill(4)}: {e}")

            # Rename data files inside re-versioned folders
            for old_v, new_v in old_to_new.items():
                folder_path = os.path.join(base_dir, f"v_{str(new_v).zfill(4)}")
                if not os.path.isdir(folder_path):
                    continue
                for fname in os.listdir(folder_path):
                    old_tag = f"_v{str(old_v).zfill(4)}"
                    new_tag = f"_v{str(new_v).zfill(4)}"
                    if old_tag in fname:
                        new_fname = fname.replace(old_tag, new_tag)
                        os.rename(os.path.join(folder_path, fname),
                                  os.path.join(folder_path, new_fname))
                        log(f"  renamed {fname} → {new_fname}")

    # ------------------------------------------------------------------
    # Write updated index
    # ------------------------------------------------------------------
    if not dryRun:
        with open(indexPath, "w") as fh:
            json.dump(indexEntries, fh, indent=4)
        log(f"Saved updated index: {indexPath}")

    # ------------------------------------------------------------------
    # Post-flight validation
    # ------------------------------------------------------------------
    post_report = validateIndex(runNumber=None, stateID=stateID,
                                isLite=isLite, calType=calType)
    if post_report["ok"]:
        log("Post-repair validation: PASS ✓")
    else:
        log("Post-repair validation: FAIL — some issues remain:")
        for issue in post_report["issues"]:
            log(f"  {issue}")
        for er in post_report.get("entries", []):
            for issue in er["issues"]:
                log(f"  Entry {er['index']}: {issue}")

    # ------------------------------------------------------------------
    # Write log file
    # ------------------------------------------------------------------
    logPath = None
    if not dryRun:
        logPath = os.path.join(sessionDir, "fix_log.txt")
        with open(logPath, "w") as fh:
            fh.write(f"fixIndex log  {datetime.now().isoformat()}\n")
            fh.write(f"stateID: {stateID}  calType: {calType}  isLite: {isLite}\n")
            fh.write(f"indexPath: {indexPath}\n")
            fh.write("=" * 72 + "\n")
            for line in actions:
                fh.write(line + "\n")
        log(f"Log written to {logPath}")
    else:
        log("(dry run – no files modified)")

    return {"actions": actions, "logFile": logPath, "backupDir": sessionDir}
