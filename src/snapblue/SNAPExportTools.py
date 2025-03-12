# Some tools to support outputing data to various Rietveld packages
import numpy as np 
import sys
import glob
import os
import shutil
from mantid.simpleapi import *
import datetime
import json
from snapred.meta.Config import Config

import snapblue.SNAPStateMgr as ssm

#Mantid interface

class redObject:

    #class that takes a workspace name and, if the name matches an expected pattern four 
    #a SNAPRed-created reduced data workspace, extracts attributes from this name
    #and then builds further attributes from these


    def __init__(self, wsName,exportFormats,requiredPrefix='reduced_dsp'):

        if '_' not in wsName:
            self.isReducedDataWorkspace = False
            return

        parsed = wsName.split('_')
        prefix = f"{parsed[0]}_{parsed[1]}"
        
        # print(f"prefix: {prefix}, required prefix: {requiredPrefix}")

        if prefix != requiredPrefix:
            self.isReducedDataWorkspace = False
            return
        
        self.suffix = f"{parsed[2]}_{parsed[3]}_{parsed[4]}"
        self.isReducedDataWorkspace = True
        self.pixelGroup = parsed[2]
        self.runNumber = parsed[3]
        self.timeStamp = parsed[4]
        self.wsName = wsName #need to keep this too
        self.ipts = GetIPTS(RunNumber=self.runNumber,
                            Instrument='SNAP')
        runNumber = str(int(self.runNumber)) # strips leading zero if necessary
        self.stateID = ssm.stateDef(runNumber)[0]

        self.exportFormats = exportFormats
        self.exportPaths = self.buildExportPaths()
        self.dateTime = datetime.datetime.strptime(self.timeStamp,'%Y-%m-%dT%H%M%S')

        #get useful workspace properties
        self.wsProperties(wsName)

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

    def wsProperties(self,wsName):
        #gets some useful attributes of workspace

        ws = mtd[wsName]
        nPix = ws.getInstrument().getNumberDetectors(True)
        if nPix == Config["instrument.lite.pixelResolution"]:
            self.isLite = True
            self.instName = "SNAPLite"
        elif nPix == Config["instrument.native.pixelResolution"]:
            self.isLite = False
            self.instName = "SNAP"
        else:
            print("ERROR: these data aren\'t from a recognised SNAP instrument")
            assert False
        
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
        #TODO: save reduction metadata? Link to reduction record?

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


    def __init__(self,runNumber,redObjectList):

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
        print(f"run {runNumber} has {len(allPixelGroups)} pixel groups")

        redObjects = {}
        #populate dictionaries with empty lists to hold contents
        for pgs in allPixelGroups:
            redObjects[pgs] = []

        #populate lists in these
        for run in redRunList:
            key = run.pixelGroup
            redObjects[key].append(run)

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

def reducedRuns(exportFormats,prefix):#,latestOnly=True,gsaInstPrm=True):

    #generates a list of reductionGroups. Each of these has a .runNumber attribute
    #and contains a dictionary with keys for each pixel groups. The corresponding values
    #are a list of available reduction object for that group (each with all attributes needed
    #to export requested files)


    allWorkspaces = mtd.getObjectNames()

    #filter out and parse reduced workspaces
    redObjectList = []
    redRuns = []
    for ws in allWorkspaces:

        red = redObject(ws,exportFormats,prefix) 
        if red.isReducedDataWorkspace:
            redObjectList.append(red)
            redRuns.append(red.runNumber)
    
    nReduced = len(redObjectList)
    uniqueRuns = set(redRuns)
    nUnique = len(uniqueRuns)
    print(f"Found total of {nReduced} reduced workspaces these were parsed into {nUnique} run reduction groups")

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
        print(f"processing {pgs} with {len(runDict[pgs])} associated workspaces")
        listOfDates = [x.dateTime for x in runDict[pgs]]
        mostRecent = max(listOfDates)
        mostRecentIndex = listOfDates.index(mostRecent)
        if latestOnly:
            processIndices = [mostRecentIndex]
        else:
            processIndices = np.arange(len(listOfDates))

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
        "Bank":f"{bankID}" #MUST BE AN INTEGER!
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

def createGSASInstPrm(gsaPath):

    allBankData,mainHead,bankHead,bankInfo=readGSASFXYE(gsaPath,[])

    iPath = os.path.splitext(gsaPath)[0] + ".instprm"

    f = open(iPath,'w')
    
    for i in range(bankInfo["nBank"]):
        f.write(f'#Bank {i+1}: GSAS-II instrument parameter file. do not add/delete items!\n')
        #loop through all located banks
        bankDict = buildBankDict(bankInfo["bankID"][i],
                                bankInfo["Ltot"][i],
                                bankInfo["ttheta"][i],
                                bankInfo["DIFC"][i])
        

        for key in bankDict:
            f.write(f'{key}:{bankDict[key]}\n')
    f.close()
    print(f'created instPrm file: {iPath}')