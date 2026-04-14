# This contains utilities to export data to other packages e.g. GSAS-II also contains 
# tools to manipulate workspaces.

import numpy as np 
import re
import sys
import glob
import os
import shutil
from mantid.simpleapi import *
from mantid.api import WorkspaceGroup
import mantid.kernel

import datetime
import json
from snapred.meta.Config import Config

import snapwrap.snapStateMgr as ssm
import snapwrap.maskUtils as mut
from .wrapConfig import WrapConfig

#Mantid interface

class redObject:

    #class that takes a workspace name and, if the name matches an expected pattern for 
    #a SNAPRed-created reduced data workspace, extracts attributes from this name
    #and then builds further attributes from these


    def __init__(self, wsName,
                 requiredPrefix='reduced',
                 requiredUnits='dsp', #allow override of expected units
                 requiredPGS=None, #allow processing of specific pixel groups only
                 requiredRunNumber=None, #allow processing of specific run numbers only
                 iptsOverride=None,
                 exportFormats=[],
                 fileTag=None,
                 cleanTreeOverride=None,
                 allowSuffix=False,
                 requiredSuffix=None):

        if WrapConfig.get("cleanTree"): #new variable to ignore timestamps
            cleanTree = True
        else:
            cleanTree = False

        if cleanTreeOverride is not None:
            cleanTree = cleanTreeOverride

        self.wsName = wsName #need to keep this too

        # reject everything that is inconsistent with the schema
        # and requested filters

        # schema 
        # cleanTree: 
        #     <prefix>_<units>_<pixelGroup>_<runNumber> (4 elements)
        # not cleanTree:
        #    <prefix>_<units>_<pixelGroup>_<runNumber>_<timestamp> (5 elements)

        if '_' not in wsName:
            self.isReducedDataWorkspace = False #necessary by not sufficient condition
            return

        #manage special case where a hidden workspace prefix is specified
        if requiredPrefix.startswith('__'):
            parsed = wsName[2:].split('_')
            parsed[0] = '__' + parsed[0] #ensure dunder is included in prefix
        else:
            parsed = wsName.split('_')

        if cleanTree:
            nElem = 4
        else:
            nElem = 5

        #process prefix
        # prefix = parsed[0]
        if parsed[0] != requiredPrefix:
            self.isReducedDataWorkspace = False
            return
        else:
            self.prefix = parsed[0]

        #process units
        units = parsed[1]
        if units != requiredUnits:
            self.isReducedDataWorkspace = False
            return
        else:
            self.units = parsed[1]
        
        # AT THIS POINT need to manage 2_4 instances. A terrible mistake where PGS has an underscore in its name :( 
        if parsed[2] == "2" and parsed[3] == "4":
            twoFour = True
            nElem += 1 # this adds an additional element to total count.
            indexShift = 1
        else:
            twoFour = False
            indexShift = 0  

        # filter on parsed length
        # Instead of demanding an exact element count, require _at least_
        # nElem tokens.  Extra tokens are treated as a potential suffix.
        if len(parsed) < nElem:
            self.isReducedDataWorkspace = False
            return

        #process pixel group
        if twoFour:
            self.pixelGroup = "2_4"
        else:
            self.pixelGroup = parsed[2]

        if requiredPGS is not None:
            if self.pixelGroup != requiredPGS:
                self.isReducedDataWorkspace = False
                return

        # ── Process run number and detect suffix ─────────────────
        # The run-number token sits at parsed[3+indexShift].
        # In the canonical case it is exactly 6 digits ("056056").
        # A suffix may follow the run number in several ways:
        #   - same token, no delimiter:   "056056mySuffix"
        #   - same token, dash/dot:       "056056-bgd_sub" or "056056.v2"
        #   - extra tokens after nElem:   "..._056056_made_a_change"
        #
        # Strategy: pull the first 6 digits as runNumber, then
        # reconstruct everything after the canonical elements as
        # the raw suffix string.

        runToken = parsed[3 + indexShift]

        # Extract the 6-digit run number from the front of the token
        m = re.match(r'^(\d{6})(.*)', runToken)
        if m is None:
            self.isReducedDataWorkspace = False
            return

        self.runNumberString = m.group(1)
        inlineRemainder = m.group(2)  # text after digits in same token

        # Determine which tokens are "extra" beyond the canonical schema
        if cleanTree:
            # canonical: prefix_units_pgs_run  → 4 tokens (or 5 with 2_4)
            extraStart = 4 + indexShift
        else:
            # canonical: prefix_units_pgs_run_timestamp  → 5 tokens (or 6 with 2_4)
            extraStart = 5 + indexShift

        extraTokens = parsed[extraStart:]

        # Build the suffix: inline remainder + any extra tokens,
        # stripped of a single leading delimiter character.
        suffixParts = []
        if inlineRemainder:
            # Strip a single leading delimiter [-._] from the inline part
            stripped = re.sub(r'^[-._]', '', inlineRemainder)
            if stripped:
                suffixParts.append(stripped)
        if extraTokens:
            suffixParts.append('_'.join(extraTokens))

        rawSuffix = '_'.join(suffixParts) if suffixParts else None
        self.suffix = rawSuffix

        # ── Suffix policy ────────────────────────────────────────
        # By default (allowSuffix=False, requiredSuffix=None):
        #   suffix detected → reject
        # allowSuffix=True, requiredSuffix=None:
        #   any suffix (or none) is accepted
        # requiredSuffix=<string>:
        #   implicitly allows suffixes, but only this exact one
        if requiredSuffix is not None:
            # requiredSuffix implies allowSuffix
            if not allowSuffix:
                mantid.kernel.Logger("redObject").warning(
                    f"requiredSuffix='{requiredSuffix}' was set "
                    "but allowSuffix=False — allowSuffix is being ignored."
                )
            if rawSuffix != requiredSuffix:
                self.isReducedDataWorkspace = False
                return
        elif rawSuffix is not None and not allowSuffix:
            self.isReducedDataWorkspace = False
            return
        
        self.runNumber=int(self.runNumberString)

        if requiredRunNumber is not None:
            if self.runNumber != int(requiredRunNumber):
                self.isReducedDataWorkspace = False
                return  

        # At this point we have passed all available filters

        # aquire timestamp only if it exists
        if cleanTree:
            self.timeStamp = None
        else:       
            self.timeStamp = parsed[4+indexShift]

        #get useful workspace spectral properties (e.g. number histograms, binning etc)
        self.wsProperties(wsName)
        if not self.isReducedDataWorkspace:
            return
        
        self.isReducedDataWorkspace = True

        # self.suffix = f"{parsed[2]}_{parsed[3]}_{parsed[4]}"
        
        if iptsOverride is None:
            self.ipts = GetIPTS(RunNumber=self.runNumber,
                                Instrument='SNAP')
        else:
            self.ipts = f"/SNS/SNAP/IPTS-{iptsOverride}/"
        
        self.fileTag = fileTag

        runNumber = str(int(self.runNumber)) # strips leading zero if necessary
        self.stateID = ssm.stateDef(runNumber)[0]

        self.exportFormats = exportFormats
        self.exportPaths = self.buildExportPaths()

        if self.timeStamp is not None:      
            self.dateTime = datetime.datetime.strptime(self.timeStamp,'%Y-%m-%dT%H%M%S')
        else:
            self.dateTime = None

        #create a dictionary to hold metadata to include as a comment in output files

        if self.isLite:
            self.redRecord = (f"{self.ipts}shared/SNAPRed/{self.stateID}/"
                              f"lite/{runNumber}/"
                              f"{self.timeStamp}/ReductionRecord.json")
        else:
            self.redRecord = (f"{self.ipts}shared/SNAPRed/{self.stateID}/"
                              f"native/{runNumber}/"
                              f"{self.timeStamp}/ReductionRecord.json")

        self.meta = {
            "redRecord" : self.redRecord, 
            "attenuationMethod": None,
            "backgroundMethod":None
        }

        self.crystalSpecies = [] #an empty list to hold a list ocf mantid crystal structure representing the crystal "species"
                                 #contributing to the data in the redObject.

    def wsProperties(self,wsName):
        #gets some useful attributes of workspace

        ws = mtd[wsName]
        nPix = ws.getInstrument().getNumberDetectors(True)
        if nPix == Config["instrument.lite.pixelResolution"]:
            self.isLite = True
            self.instName = "SNAPLite"
            self.isReducedDataWorkspace = True
        elif nPix == Config["instrument.native.pixelResolution"]:
            self.isLite = False
            self.instName = "SNAP"
            self.isReducedDataWorkspace = True
        else:
            print("ERROR: these data aren\'t from a recognised SNAP instrument")
            print(f"found {nPix} pixels in instrument for workspace {wsName}")
            self.isReducedDataWorkspace=False
            return
        
        self.nHist = ws.getNumberHistograms()

        self.xMin = np.zeros(self.nHist)
        self.xMax = np.zeros(self.nHist)
        self.delta = np.zeros(self.nHist)
        for h in range(self.nHist):
            x = ws.readX(h)
            self.xMin[h] = np.min(x)
            self.xMax[h] = np.max(x)
            binSizes = x[:-1]-x[1:] #array of bin sizes, one smaller than x array
            if binSizes[0] == binSizes[-2]:
                self.binType = "linear"
                self.delta[h]=binSizes[0]
            else:
                self.binType = "logarithmic" #this is not particularly safe...
                self.delta[h] = -(x[1]/x[0]-1)
        

    def buildExportPaths(self):

        #TODO: use elements of paths defined in SNAPInstPrm instead of hardwiring here
        #TODO: allow for overrides?
        #TODO: save reduction metadata? Link to reduction

        #constructs export filepaths according to exportFormats requested

        useStateID = False #TODO how to pass options?

        if useStateID:
            redPath = f'{self.ipts}shared/SNAPRed/{self.stateID[0]}/export/'
        else:
            redPath = f'{self.ipts}shared/SNAPRed/export/'

        filePrefix = 'SNAP'

        #create a dictionary for each supported export type

        # if useTS:
        gsaDict = {"subPath" : f'{redPath}gsa/{self.pixelGroup}/',
                    "prefix" : (f'{filePrefix}{str(self.runNumber).zfill(6)}_'
                                f'{self.pixelGroup}'),
                    "ext" : '.gsa'
                    }
        
        xyeDict = {"subPath" : f'{redPath}xye/{self.pixelGroup}/',
                    "prefix" : (f'{filePrefix}{str(self.runNumber).zfill(6)}_'
                                f'{self.pixelGroup}'),
                    "ext" : '.xye'
                    }
        
        csvDict = {"subPath" : f'{redPath}csv/{self.pixelGroup}/',
                    "prefix" : (f'{filePrefix}{str(self.runNumber).zfill(6)}_'
                                f'{self.pixelGroup}'),
                    "ext" : '.csv'
                    }
        
        if self.fileTag is not None:

            for dict in [gsaDict,xyeDict,csvDict]:

                dict["prefix"] = dict["prefix"] + f"_{self.fileTag}"
            

        exportPaths = []
        # print("requested export formats: ",self.exportFormats)
        for format in self.exportFormats:

            if format.lower() == 'gsa': # gsas export requested
                exportPaths.append(gsaDict)

            elif format.lower() == 'xye': # gsas export requested
                exportPaths.append(xyeDict)

            elif format.lower() == 'csv': # gsas export requested
                exportPaths.append(csvDict)

            else:
                print("WARNING: requested export type not defined")


        return exportPaths


class reductionGroup:
    #instantiated with a list of redObject classes and a run number, it reparses the list into
    #a dictionary where the keys are the pixel group and the values are a list of redObjects
    # if a timestamp is present these are ordered with latest first. 


    def __init__(self,runNumber,redObjectList,cleanTreeOverride = None,verbose=False):

        self.runNumber = runNumber
        
        #extract all objects in list corresponding to this run
        redRunList = []
        for redObject in redObjectList:
            if redObject.runNumber == runNumber:
                redRunList.append(redObject)

        #extract list of pixel groups used for this run
        pgsList = []
        for run in redRunList:
            pgsList.append(run.pixelGroup)
        
        allPixelGroups = set(pgsList)
        if verbose:
            print(f"run {runNumber} has {len(allPixelGroups)} pixel group(s)")

        redObjects = {}
        #populate dictionaries with empty lists to hold contents
        for pgs in allPixelGroups:
            redObjects[pgs] = []

        #populate lists in these
        for run in redRunList:
            key = run.pixelGroup
            redObjects[key].append(run)

        cleanTree = WrapConfig.get("cleanTree")
        if cleanTreeOverride is not None:
            cleanTree = cleanTreeOverride # need this option so tree can be cleaned

        #if not cleanTree need to sort lists for each key in order of decreasing time
        for pgs in allPixelGroups:
            if not cleanTree:
                objects = redObjects[pgs] # a list of redObjects un sorted in time
                sortedObjects = sorted(
                    objects,
                    key = lambda obj: obj.timeStamp,
                    reverse=True
                ) #This list sorted according to timestamp of objects            
                redObjects[pgs]=sortedObjects #replace list with sorted list

        self.objectDict = redObjects

def convertToQ():

    allWorkspaces = mtd.getObjectNames()

    
    for ws in allWorkspaces:
        red = redObject(ws,[])
        if red.isReducedDataWorkspace:

            outName = f"reduced_qsp_{red.pixelGroup}_{red.runNumber}_{red.timeStamp}"
            ConvertUnits(InputWorkspace=red.wsName,
                        OutputWorkspace=outName,
                        Target="MomentumTransfer")
            
    #TODO: rebin S(Q) once I know how to do this

def reducedRuns(prefix='reduced',
                units = 'dsp',
                PGS = None,
                runNumber = None,
                iptsOverride=None,
                exportFormats=[], 
                fileTag=None,
                cleanTreeOverride=None,
                verbose=False):#,latestOnly=True,gsaInstPrm=True):

    #generates a list of reductionGroups. Each of these has a `runNumber` attribute
    #and contains a dictionary with keys for each pixel groups. The corresponding values
    #are a list of available reduction object for that group (each with all attributes needed
    #to export requested files)

    # if prefix starts with dunder then assume we need to check hidden workspaces
    if prefix.startswith('__'):
        # print("looking for hidden")
        # with mantid.kernel.amend_config(**{"InvisibleWorkspaces": "1"}):  # TODO: try to fix this.
        config.setString('MantidOptions.InvisibleWorkspaces','1')
        allWorkspaces = mtd.getObjectNames()
            # print(allWorkspaces)
        config.setString('MantidOptions.InvisibleWorkspaces','0')
    else: 
        allWorkspaces = mtd.getObjectNames()

    #filter out and parse reduced workspaces
    redObjectList = []
    redRuns = []
    for ws in allWorkspaces:

        red = redObject(ws,
                        requiredPrefix=prefix,
                        requiredUnits=units,
                        requiredPGS=PGS,
                        requiredRunNumber=runNumber,
                        iptsOverride=iptsOverride,
                        exportFormats=exportFormats,
                        fileTag=fileTag,
                        cleanTreeOverride=cleanTreeOverride) 

        if red.isReducedDataWorkspace:
            redObjectList.append(red)
            redRuns.append(red.runNumber)
    
    nReduced = len(redObjectList)
    uniqueRuns = set(redRuns)
    nUnique = len(uniqueRuns)
    if verbose:
        print(f"Found total of {nReduced} reduced workspaces these were parsed into {nUnique} run reduction group(s)")

    #parse these creating "reductionGroup" for each run numbner
    reducedGroups = []
    for run in uniqueRuns: 
        redGroup = reductionGroup(run,redObjectList)
        reducedGroups.append(redGroup)

    return reducedGroups

def exportReducedGroups(reducedGroups,latestOnly=True,gsaInstPrm=True):
    #works through a reducedGroups list and exports these. Required export formats
    #must be specified when creating the reducedGroups list

    for redGroup in reducedGroups:
        exportReducedGroup(redGroup,latestOnly,gsaInstPrm)

def exportReducedGroup(redGroup,latestOnly,gsaInstPrm):

    runNumber = redGroup.runNumber
    runDict = redGroup.objectDict #contains reduction objects for all workspaces associated with runNumber

    print(f"Exporting run: {runNumber} with {len(runDict)} pixel group(s)")
    for pgs in runDict.keys():
        #each key is a pixel group and each pixel group has a list of objects (each is a workspace)
        print(f"processing pixel group {pgs} with {len(runDict[pgs])} associated workspaces")
        if latestOnly:
            processIndices = [0]
        else:
            processIndices = np.arange(len(runDict[pgs])).tolist()

        exportRecipe(runDict,pgs,processIndices,gsaInstPrm)

def exportRecipe(runDict,pgs,processIndices,gsaInstPrm):

    #Finally, the recipe to output the data

    if len(processIndices) == 1:
        excludeTimestamp = True
    else:
        excludeTimestamp = False

    for index in processIndices:

        redObj = runDict[pgs][index]
        wsName = redObj.wsName
        print("processing workspace: ",wsName)
        # print(redObj.exportPaths) #each export path corresponds do different output format

        ConvertUnits(InputWorkspace=wsName,
                     OutputWorkspace=wsName,
                     Target='TOF')
        
        scaleFactor=1e4
        Scale(InputWorkspace=wsName,
                OutputWorkspace=wsName,
                Factor = scaleFactor,
                Operation='Multiply')

        exportFormats = [x["ext"] for x in redObj.exportPaths]
        # print("exportFormats to use are:", exportFormats)        
        if '.gsa' in exportFormats:
            gsaIndex = exportFormats.index('.gsa')
            exportDict = redObj.exportPaths[gsaIndex]

            if excludeTimestamp:

                fName = (f"{exportDict['subPath']}"
                         f"{exportDict['prefix']}"
                         f"{exportDict['ext']}")

            else:

                fName = (f"{exportDict['subPath']}"
                         f"{exportDict['prefix']}"
                         f"_{redObj.timeStamp}"
                         f"{exportDict['ext']}")

            SaveGSS(InputWorkspace=wsName,
                    Filename=fName,
                    SplitFiles=False,
                    Append=False,
                    Format="SLOG",
                    MultiplyByBinWidth=True,
                    UseSpectrumNumberAsBankID=True,
                    OverwriteStandardHeader=True,
                    UserSpecifiedGSASHeader=json.dumps(redObj.meta))

            if gsaInstPrm:
                createGSASInstPrm(fName)
            
            print("GSA file written to:",fName) 
            
        if '.xye' in exportFormats:

            xyeIndex = exportFormats.index('.xye')
            exportDict = redObj.exportPaths[xyeIndex]

            if excludeTimestamp:

                fName = (f"{exportDict['subPath']}"
                         f"{exportDict['prefix']}"
                         f"{exportDict['ext']}")

            else:

                fName = (f"{exportDict['subPath']}"
                         f"{exportDict['prefix']}"
                         f"_{redObj.timeStamp}"
                         f"{exportDict['ext']}")

            
            
            
            SaveFocusedXYE(InputWorkspace=wsName,
                    Filename=fName,
                    SplitFiles=True,
                    Append=False,
                    includeHeader=False,
                    Format="TOPAS")
            
            
            
            print("XYE file written to:",fName) 

        ConvertUnits(InputWorkspace=wsName,
                     OutputWorkspace=wsName,
                     Target='dSpacing')    

        if '.csv' in exportFormats: #not really csv

            csvIndex = exportFormats.index('.csv')
            exportDict = redObj.exportPaths[csvIndex]

            if excludeTimestamp:

                fName = (f"{exportDict['subPath']}"
                         f"{exportDict['prefix']}"
                         f"{exportDict['ext']}")

            else:

                fName = (f"{exportDict['subPath']}"
                         f"{exportDict['prefix']}"
                         f"_{redObj.timeStamp}"
                         f"{exportDict['ext']}")

            SaveFocusedXYE(InputWorkspace=wsName,
                    Filename=fName,
                    SplitFiles=True,
                    Append=False,
                    includeHeader=True)
            
            print("CSV file written to:",fName) 

        Scale(InputWorkspace=wsName,
                  OutputWorkspace=wsName,
                  Factor = (1.0/scaleFactor),
                  Operation='Multiply')
    
class diskObject:

    def __init__(self,runNumber,isLite):
        
        #This is a class to retrieve information about reduced files that are saved to disk
        stateID,stateDict = ssm.stateDef(runNumber)
        if isLite:
            instType = 'lite'
        else:
            instType = 'native'

        self.runNumber = runNumber
        ipts = GetIPTS(RunNumber=runNumber,
                            Instrument='SNAP')
        
        self.runString = str(runNumber).strip()

        redPath = f"{ipts}shared/SNAPRed/{stateID}/{instType}/{self.runString}/"
        
        self.isReduced = os.path.exists(redPath) 
        if not self.isReduced:
            self.nReduced = 0
            return
        
        #if this folder exists, then data have been reduced N times with each reduction
        #stored in a folder with named with its timestamp
        ts = os.listdir(redPath)

        self.ts = sorted(ts, key=lambda x: datetime.datetime.strptime(x,'%Y-%m-%dT%H%M%S'))

        self.nReduced = len(self.ts)
        self.redDir = []
        self.record = []
        self.dataPath = []
        self.maskPath = []
        self.isMasked = []
        self.dateTime = []
        self.maskWorkspaceName = []
        self.groupWorkspaceName = []

        for ts in self.ts:
            self.dateTime.append(datetime.datetime.strptime(ts,'%Y-%m-%dT%H%M%S'))
            dir = f"{redPath}{ts}/"
            self.redDir.append(f"{redPath}{ts}/")
            with open(f"{dir}ReductionRecord.json",'r') as file:
                recordDict = json.load(file)
            self.record.append(recordDict)
            self.dataPath.append(f"{dir}reduced_{self.runString.zfill(6)}_{ts}.nxs")
            self.maskWorkspaceName.append(f"pixelmask_{self.runString.zfill(6)}_{ts}")
            mp = f"{dir}{self.maskWorkspaceName[-1]}.h5"
            self.isMasked.append(os.path.exists(mp))
            self.maskPath.append(mp)
            self.groupWorkspaceName.append(f"reloaded_{self.runString.zfill(6)}_{ts}")

    def info(self):
        #sometimes useful to output information on reduction status
        if self.isReduced:
            print(f"Run: {self.runNumber} has been reduced {self.nReduced} times")
            print(f"latestReduction was: {self.ts[-1]}")
            for ind,ts in enumerate(self.ts):
                print(f"""

    time stamp: {ts}
    dataPath: {self.dataPath[ind]}
    mask: {self.maskPath[ind]}
    isMasked: {self.isMasked[ind]} 
                        """)
             
        else:
            print(f"Run: {self.runNumber} has not been reduced")

    def degroup(self,ind,keepMask=False,pixelGroup=None):

        #first need to check if this is the expected workspace group. A weird bug
        #was observed one time where the reduction record only contained the pixel
        #mask

        ws = mtd[self.groupWorkspaceName[ind]]
        if not isinstance(ws, WorkspaceGroup):
            print(f"WARNING: {self.groupWorkspaceName[ind]} is not a workspace group so could not be unpacked. skipping.")
            return

        #keep a list of the group contents thata are reduced data
        
        groupContents = ws.getNames()
        redGroups = []
        for ws in groupContents:
            if "pixel" not in ws:
                redGroups.append(ws)

        #then ungroup input workspace. 
        UnGroupWorkspace(self.groupWorkspaceName[ind])  
            
        
        #if a pixelGroup is specified, delete all workspaces apart from that one
        if pixelGroup != None:
        
            for ws in redGroups:
                if pixelGroup.lower() not in ws:
                    DeleteWorkspace(ws)

        #if mask exists and request to keep, clone before deleting
        if self.isMasked[ind]:
            if keepMask:
                CloneWorkspace(InputWorkspace=self.maskWorkspaceName[ind],
                                OutputWorkspace=mut.nextMaskWSName())
            DeleteWorkspace(Workspace=self.maskWorkspaceName[ind])
        else:
            print("WARNING: Requested to keep mask, but mask does not exist")

    def reload(self,all=False,unpack=True,keepMask=False,pixelGroup=None):
        #will reload reduced data by default loading only the latest reduction
        #if requested will reload all reductions
        if not self.isReduced:
            print("No reduced data to reload for run: {self.runNumber}")
            return
        
        if all:
            for ind,ts in enumerate(self.ts):
                LoadNexus(Filename=self.dataPath[ind],
                          OutputWorkspace=self.groupWorkspaceName[ind])
                if unpack:
                    self.degroup(ind,keepMask=keepMask,pixelGroup=pixelGroup)
        else:
            LoadNexus(Filename=self.dataPath[-1],
                          OutputWorkspace=self.groupWorkspaceName[-1])
            if unpack:
                self.degroup(-1,keepMask=keepMask,pixelGroup=pixelGroup)

#GSAS2 specific utilities

def buildBankDict(bankID,Ltot,ttheta,difc):
    #create a dictionary containing all of the items required to describe a bank in gsas instptm
    #file, updating these with known values
    bankDict = {
        "Type":"PNT",
        "beta-0":0.0235,
        "fltPath":Ltot,
        "alpha":0.986512012223,
        "sig-1":66, #TODO: calculate an estimate from 2theta
        "2-theta":ttheta,
        "sig-q":0.0,
        "sig-0":0.0,
        "sig-2":0.0,
        "Zero":0.0,
        "difA":0.0,
        "difB":0.0,
        "Azimuth":0.0,
        "Y":0.0,
        "X":0.0,
        "beta-1":0.0300,
        "Z":0.0,
        "difC":difc,
        "beta-q":0.0,
        "Bank":f"{int(bankID)}" #MUST BE AN INTEGER!
                }

            
    return bankDict

def readGSASFXYE(fname,gsasKeyWords):
    
# Reads GSAS FXYE format file and searches header for specific key words specified as a list of strings.
# It returns lists:
#     allBankData - a list of np arrays containing X,Y,E for each bank, 
#     mainHead - a list of strings for the main header 
#     bankHead - a list of bank header strings
#     foundKeywords - a dictionary with key:value pairs for the requested header keywords

#   20240807 modified for how mantid writes data with special comment line for each bank
#   containing tth LTot and DIFC

    # print(f'reading file: {fname}')

    with open(fname,'r') as f:
        lines = f.readlines()

    mainHead = []
    bankHead = []
    bankLoc = []
    bankInfo = {"bankID":[],
                "ttheta":[],
                "Ltot":[],
                "DIFC":[]} #dictionary of empty lists to store bank info
    

    for i,line in enumerate(lines):
        if i==1:
            mainHead.append(line)
        elif line[0]=='#': #comment line
            mainHead.append(line)
        elif line[0:4]=='BANK':
            bankHead.append(line)
            bankLoc.append(i)
    
    bankLoc.append(i+1) #psuedo bank label after final data point
    nBank = len(bankLoc)-1 #
    # print(f'found {nBank} banks at {bankLoc}')

    #get mantid bank info from header
    for i,bankHeadLine in enumerate(bankLoc[:-1]):

        bankNo = i+1 
        bankInfoLineID = bankHeadLine-2
        bankInfoLine = lines[bankInfoLineID]
        # print(f"Bank {bankNo}, infoline: {bankInfoLine}")
        bankInfoItems = bankInfoLine.split(' ')
        # print(bankInfoItems)
        ttheta = float(bankInfoItems[6][:-4])
        Ltot = float(bankInfoItems[4][:-2])
        DIFCVal=float(bankInfoItems[8][:-1])
        bankInfo["bankID"].append(bankNo)
        bankInfo["ttheta"].append(ttheta)
        bankInfo["Ltot"].append(Ltot)
        bankInfo["DIFC"].append(DIFCVal)

    bankInfo["nBank"]=(i+1)
    #process header and extract useful info on the basis of pre-defined keywords:
    # gsasKeyWords = ['IPTS','normalized by','GSAS file name','GSAS IPARM file: ']
    foundKeywords = bankInfo
    for head in mainHead:
        foundKey = [x for x in gsasKeyWords if x in head]
        if len(foundKey) != 0:
            val = head.strip().split(':')[1].strip()
            # print(f'key {foundKey} found, value: {val}')
            foundKeywords.update({foundKey[0]:val})
      

    allBankData = []
    for i in range(nBank):
        nData = bankLoc[i+1]-bankLoc[i]-1#number of data points
#         print(f'Bank {i+1}, expecting {nData} points, starting line {bankLoc[i]+1}, ending line {bankLoc[i+1]-1}')
        bankData = np.zeros([nData,3])
        for row,j in enumerate(range(bankLoc[i]+1,bankLoc[i+1])):
            if lines[j][0] != '#':    #sometimes bank info given as comment in data block.
                dataRec = lines[j].strip().split()
                bankData[row,:]= [dataRec[0],dataRec[1],dataRec[2]]
        allBankData.append(bankData)
    
    # print(allBankData[0])
    # print(f'number of dimensions: {data.ndim}')
    # print(f'shape of array: {data.shape}')
    return allBankData,mainHead,bankHead,foundKeywords

def writeGSASFXYE(fname,allBankData,mainHead,bankHead):

#using lists returned from readGSASFXYE to create a GSAS FXYE format file
    #open file
    f = open(fname, 'w')
    #write main file header
    f.writelines(mainHead)
    # get number of banks
    nBank = len(bankHead)
    #write bank headers and data
    for bank in range(nBank):
        f.write(bankHead[bank])
        nrows = len(allBankData[bank][:,0])
        for row in range(nrows):
            f.write(f'{allBankData[bank][row,0]:12.1f}{allBankData[bank][row,1]:12.1f}{allBankData[bank][row,2]:12.2f}'.ljust(80)+'\n')
    f.close()
    return fname

def processResolutionWS(resWSName,bankID):

    # accepts a resolution workspace and returns a string containing 
    # the resolution data in "pdabc" format that can be written to the 
    # instprm file.

    ws = mtd[resWSName]
    # # difc = ws.getSpectrumInfo().difcUncalibrated(bankID)
    # difc = 5241.5467662253222443 # UGH!!!! I can't figure out how to extract this!!!!!!!
    d = ws.dataX(bankID)
    sig = ws.dataY(bankID)
    bet = np.zeros_like(sig)
    alp = np.zeros_like(sig)
    ConvertUnits(InputWorkspace=resWSName,
                OutputWorkspace="tmp",
                Target="TOF")
    ws = mtd["tmp"]
    tof = ws.dataX(bankID)

    DeleteWorkspace("tmp")

    # all arrays have to be identical size
    assert all(len(d) == len(a) for a in (tof, sig, bet, alp))
    # print(f"Found {len(d)} entries")

    # GSAS uses sig in TOF, so need to convert from d-space here:
    sig = (tof/d)*sig

    i = 0
    resString = f"pdabc:\"\"\"{d[i]:.4f}, {tof[i]:8.1f}, {alp[i]:8.6f}, {bet[i]:8.6f}, {sig[i]:8.6f}\n"
    for i in range(1,len(d)-1):
        resString+=f"{d[i]:7.4f}, {tof[i]:8.1f}, {alp[i]:8.6f}, {bet[i]:8.6f}, {sig[i]:8.6f}\n"

    resString+=f"{d[-1]:7.4f}, {tof[-1]:8.1f}, {alp[-1]:8.6f}, {bet[-1]:8.6f}, {sig[-1]:8.6f}\"\"\"\n"

    return resString


def createGSASInstPrm(gsaPath):

    allBankData,mainHead,bankHead,bankInfo=readGSASFXYE(gsaPath,[])

    iPath = os.path.splitext(gsaPath)[0] + ".instprm"
    baseName = os.path.splitext(os.path.basename(gsaPath))[0]
    pgs = baseName.split("_")[1] #should always be pgs
    runNumber =  baseName.split("_")[0][4:]
    resWSName = f"resolution_dsp_{pgs.lower()}_{runNumber.zfill(6)}"

    print(f"export test: basename:{baseName}, pgs: {pgs}, runNumber: {runNumber}")
    
    if resWSName in mtd.getObjectNames():
        print("found resolution workspace, adding to instprm")
        resExists = True
    else:
        resExists = False

    print(f"Resolution ws name: {resWSName}, exists: {resExists}")

    f = open(iPath,'w')
    
    for i in range(bankInfo["nBank"]):
        f.write(f'#Bank {i+1}: GSAS-II instrument parameter file. do not add/delete items!\n')
        #loop through all located banks
        bankDict = buildBankDict(bankInfo["bankID"][i],
                                bankInfo["Ltot"][i],
                                bankInfo["ttheta"][i],
                                bankInfo["DIFC"][i])
        

        for key in bankDict:
            if key != "Bank": #this needs to be the final entry
                f.write(f'{key}:{bankDict[key]}\n')


    # if user has created resolution files, assume that these are to be used and include them in 
    # InstPrm file.

    # first decompose gsaPath to get pgs and run number
        if resExists:

            resString = processResolutionWS(resWSName,i)
            f.write(resString)

    # finally write bank ID entry
        f.write(f"Bank:{bankDict['Bank']}\n")

    f.close()
    print(f'created instPrm file: {iPath}')