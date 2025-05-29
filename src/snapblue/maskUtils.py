# a module with some protoype functions for the generation and management of SEE masks in 
# mantid workbench.
#
# since this is just at the prototype stage, these function should only be expected to work with Lite SNAP

#Note the environment autoMask should be activated!

import copy
import importlib

from mantid.simpleapi import *
from mantid.kernel import UnitFactoryImpl
import matplotlib.pyplot as plt
import numpy as np
import skimage as ski
import json

import sys

class sliceImage:

    def __init__(self,wsName,xMin=0.5,xMax=30000):
    
        self.wsName = wsName
        self.xMin = xMin #minimum x-value of slice
        self.xMax = xMax #maximum x-value of slice
        self.mask = None
        self.combineMasks = False
        
    
        #create slice image
        wsIn = mtd[self.wsName]
        inputX = wsIn.dataX(0) #take first spectrum (and assume others are the same)
        inputX_min = min(inputX)
        inputX_max = max(inputX)

        if self.xMin< inputX_min:
            print(f"requested xMin: {xMin} <= mimimum of input data {inputX_min}. Reseting")
            self.xMin = inputX_min
            

        if self.xMax> inputX_max:
            print(f"requested xMax: {xMax} <= mimimum of input data {inputX_max}. Reseting")
            self.xMax = inputX_max

        # print(f"limiting x-values are: {inputX_min:.4f} and {inputX_max:.4f}")
        #choose a binning parameter that gives only one bin
        xBin = np.abs(xMax-xMin)

        #create a workspace with only the requested slice in it
        tempSlice = Rebin(InputWorkspace=self.wsName,
                        Params=f'{self.xMin},{xBin},{self.xMax}',
                        PreserveEvents=False)
        # build image from slice of data
        ws = mtd['tempSlice']

        #get units (TODO: handle more elegantly)
        self.xUnits = ws.getAxis(0).getUnit().caption()
        if self.xUnits == 'd-Spacing':
            self.xUnits = 'dSpacing' #inconsistent naming in mantid
        if self.xUnits == 'Time-of-flight':
            self.xUnits = 'TOF' #inconsistent naming in mantid
        
        self.image = np.empty((96,192))  #empty array to hold data
        for spec in range(ws.getNumberHistograms()):
        
            i,j = rowCol(spec) #returns indices
            
            self.image[i,j] = ws.dataY(spec)[0] #assign y value of pixel to image array

        DeleteWorkspace(Workspace=tempSlice)

    def clearMask(self):

        if self.mask != None:
            self.mask[:]=False #nothing is masked

    def maskStats(self):

        self.nMaskedPixels = np.sum(self.mask)
        self.percentMasked = 100*self.nMaskedPixels/self.image.size

def rowCol(specID):
    # need a function to transform from pixel ID to i,j coordinates to build an image
    
    #there are two detectors. 
    #each detector is a 3 x 3 (= 9) array of modules

    NRowModule = 3      # number of rows of modules in a detector
    NColumnModule = 3   # number of columns of modules in a detector
    NModule = NRowModule*NColumnModule # total number of modules in a detector

    #Each module is comprised of 32 x 32 (=1024) array of pixels

    NRowPixel = 32 # number of rows of pixels in a module
    NColumnPixel = 32 # number of columns of pixels in a module
    NPixel = NRowPixel*NColumnPixel # total number of pixels in a module

    #in the following, coordinates are generically given by (i,j) tuples where
    #i is the row index and j is the column index.

    # step 1: useful to get coordinates i,j of modules.

    #row and column indices for the module containing specID are obtained from
    idModule = specID // NPixel
    jModule = idModule // NColumnModule # column index of module containing specID
    iModule = idModule % NRowModule # row index of module containing specID

    #step 2: equivalently get row and column indices for the pixel within the module:
    firstPixelInModule = idModule*NPixel
    idPixel = int(specID - firstPixelInModule) #ID running from 0 to 1024 for each pixel in a module
    jPixel =  idPixel // NColumnPixel
    iPixel = specID % NRowPixel
    
    #step 3: Transform coordinates to create the image I want. This has the west and east banks side by side 
    #(with west on left) and both detectors as viewed from the sample position. 
    #The resultant images will be 96x192 (=18432) pixels
    
    #need to remap module indices to put the columns of modules in the right order corresponding to 
    #desired viewing direction (from sample)
    jModuleMap=[3,4,5,0,1,2]
    jModule = jModuleMap.index(jModule)
    
    j = jModule*NColumnPixel+jPixel
    i = (iModule)*NRowPixel+iPixel

    #image row index increases from top to bottom, versus convention of images being bottom to top, so need to invert
    i = NRowPixel*NRowModule-i-1
    
    return i,j

def coordSpecIDMap(wsName):
    #This builds an ndarray that is identical to the image of sliceImage, but populates this with the 
    #input spectrum numbers. The resultant array provides a convenient way to recover the
    #spectrum ID of any pair of image (i,j) coordinates.

    ws = mtd[wsName]
    
    mapImage = np.empty((96,192))  #empty array to hold data

    nSpectra = ws.getNumberHistograms()

    for spec in range(nSpectra):
    
        i,j = rowCol(spec) #returns indices
        
        mapImage[i,j] = spec #assign y value of pixel to image array

    return mapImage

#Following Sci-Kit an image mask will be a numpy of same dimensions as the image it applies to
# but it shall have Boolean values instead of floats, with False indicating a pixel should not
# be used i.e. is masked. 

def maskGrid(sliceImage,gridWidth=0):
    #This is a function to mask (by setting to zero) all pixels that lie on the module edge
    #these edges are clearly 

    inputImage = sliceImage.image
    outputMask = np.empty_like(inputImage,dtype=bool)

    #set all values to False
    outputMask[:]=False
    
    #process rows
    for row in range(96):
        
        if np.logical_or((row%32)<=gridWidth,(row%32)>=32-gridWidth):
            outputMask[row,:]=True
    
    #columns
    for col in range(192):
        if np.logical_or((col%32)<=gridWidth,(col%32)>=32-gridWidth):
            outputMask[:,col]=True

    if sliceImage.combineMasks:
        sliceImage.mask = np.logical_or(sliceImage.mask,outputMask)
    else:
        sliceImage.mask = outputMask
    
    sliceImage.maskStats()

def threshMask(sliceImage,thresh):
    #a simple threshold mask, currently defined as a multiple of the mean y-value of the input image

    inputImage = slice.image

    outputMask = np.empty_like(inputImage,dtype=bool)
    outputMask[:] = False

    mask_vals = inputImage > thresh*inputImage.mean()
    # print(f"original{len(outputMask)} no. masked: {len(mask_vals)}")
    outputMask[mask_vals]=True

    if sliceImage.combineMasks:
        sliceImage.mask = np.logical_or(sliceImage.mask,outputMask)
    else:
        sliceImage.mask = outputMask

    sliceImage.maskStats()

def nextMaskWSName():
        #returns the next mask workspace name to use

        allWS = mtd.getObjectNames()
        maskWS = []
        for ws in allWS: 
            if "MaskWorkspace" in ws:
                maskWS.append(ws)
        
        if len(maskWS) == 0:
            return "MaskWorkspace"
        
        maskIndices = []
        for mask in maskWS:

            if '_' not in mask:
                maskIndices.append(1)
            else:
                maskIndices.append(int(mask.split('_')[-1]))

        latest = max(maskIndices)+1
        nextName = f"MaskWorkspace_{latest}"
        return nextName

def latestMaskIndex():
        #returns the latest index of any present mask workspaces

        allWS = mtd.getObjectNames()
        maskWS = []
        for ws in allWS: 
            if "MaskWorkspace" in ws:
                maskWS.append(ws)
        
        if len(maskWS) == 0:
            print("error: no mask workspace exists")
            return False
        
        maskIndices = []
        for mask in maskWS:

            if '_' not in mask:
                maskIndices.append(1)
            else:
                maskIndices.append(int(mask.split('_')[-1]))

        latestIndex = max(maskIndices)

        return latestIndex

def liLee(sliceImage,removeDark=True):
    #generates a mask by applying Li thresholding https://scikit-image.org/docs/stable/auto_examples/developers/plot_threshold_li.html
    # a scikit-image filter
    #can optionally mask dark regions or light regions
    #
    #note: mask==0 means keep, mask==1 means remove

    inputImage = sliceImage.image

    if removeDark:
        outputMask = inputImage < ski.filters.threshold_li(inputImage)
    else:
        outputMask = inputImage > ski.filters.threshold_li(inputImage)

    if sliceImage.combineMasks:
        sliceImage.mask = np.logical_or(sliceImage.mask,outputMask)
    else:
        sliceImage.mask = outputMask

    sliceImage.maskStats()

def mask2mantid(sliceImage,donorWS,outWS):
    #takes a 2d image mask and converts it to a mantid mask workspace

    inputMask = sliceImage.mask

    #get image coordinate to pixelID map
    map = coordSpecIDMap(donorWS)

    #flatten
    flat = np.ndarray.flatten(map)
    
    #get indices that arrange pixels in order
    mapIndex = np.argsort(flat)

    #flatten input image
    flat = np.ndarray.flatten(inputMask)
    #apply indexing to put spectra in order. These should be a list of 18432 booleans.
    mantidMaskData = flat[mapIndex]

    #create Mask
    maskHandle = createCompatibleMask(outWS,donorWS,mantidMaskData)

    return maskHandle

def createCompatibleMask(maskWSName: str, templateWSName: str, maskInfo):
    """
    Create a `MaskWorkspace` compatible with a template (or "donor") workspace
    """
    pixelCount = mtd[templateWSName].getNumberHistograms()
    mask = CreateWorkspace(
        OutputWorkspace=maskWSName,
        NSpec=pixelCount,
        DataX=list(np.zeros((pixelCount,))),
        DataY=list(np.zeros((pixelCount,))),
        ParentWorkspace=templateWSName,
    )
    
    si = mask.spectrumInfo()

    for id_ in range(pixelCount):
        si.setMasked(int(id_),bool(maskInfo[id_]))

    mask = ExtractMask(InputWorkspace=mask,
                       OutputWorkspace=maskWSName)

    return mask

class eye:

    #an "eye" is a single bubble in a swiss cheese 
    def __init__(self,xUnits,xMin,xMax,inputWorkspaceIndexSet,isLite):

        self.xUnits = xUnits
        self.standardiseXUnits()

        self.xMin = float(xMin)
        self.xMax = float(xMax)
        self.inputWorkspaceIndexSet = inputWorkspaceIndexSet
        self.isLite = isLite

    def standardiseXUnits(self):

        #annoyingly mantid history records units with different names than those understood
        #by maskbins, fix this here: 

        if self.xUnits == 'd-Spacing':
            self.xUnits = 'dSpacing' #inconsistent naming in mantid
        if self.xUnits == 'Time-of-flight':
            self.xUnits = 'TOF' #inconsistent naming in mantid

        #TODO: Pete said I need to validate that this works: 

        # try:
        # print(f"units: {self.xUnits}")
        # UnitFactoryImpl.create(self.xUnits)
        # except:
        #     print("warning: Mantid UnitFactory couldn\'t instantiate")

class swissCheese:

    def __init__(self):

        self.eyeList = []

    def load(self,filename):
        # copies ancient snapmask json implementation

        #TODO: validate file exists


        with open(filename, "r") as json_file:
            mskBinsDict = json.load(json_file)

        mask_xmins = mskBinsDict['xmins']
        mask_xmaxs = mskBinsDict['xmaxs']        
        mask_spectraLsts = mskBinsDict['spectraLsts']
        mask_units = mskBinsDict['units']

        #TODO: add islite as property to file
        isLite = True

        for i in range(len(mask_xmins)):
            xMin = mask_xmins[i]
            xMax = mask_xmaxs[i]
            spectraLsts = mask_spectraLsts[i]
            units = mask_units

            #create eye
            oneEye = eye(xMin=xMin,xMax=xMax,xUnits=units,inputWorkspaceIndexSet=spectraLsts,isLite=isLite)
            
            #add to list
            self.eyeList.append(oneEye)

        self.processCheese()

    def notchFromList(self,xUnits,notchList,isLite):
        #this function creates a swiss cheese from a list of notches
        #the notches are defined as a list of tuples (xMin,xMax)

        for i in range(len(notchList)):
            xMin = notchList[i][0]
            xMax = notchList[i][1]
            #TODO: check notches sort notchlist[i]
            units = xUnits
            if isLite:
                inputWorkspaceIndexSet = '0-18431'
            else:
                inputWorkspaceIndexSet = '0-1179647'        

            #create eye
            oneEye = eye(xMin=xMin,
                         xMax=xMax,
                         xUnits=units,
                         inputWorkspaceIndexSet=inputWorkspaceIndexSet,
                         isLite=isLite)
            
            #add to list
            self.eyeList.append(oneEye)

        self.processCheese()

    def notchFromUB(self,wsName,UBPath,widthCoef,isLite,lamMin=0.5):

        # accepts a path to an ISAW UB file and creates a swiss cheese
        # wavelengths are calculated from the UB and notch widths are
        # calculated with a simple polynomical of the form 
        # a0+a1*lam+a2*lam**2+... widthCoef is the list [a0,a1,a2,...]

        from mantid.geometry import CrystalStructure, ReflectionGenerator   
    
        #Define diamond crystal structure object (note, origin choice 1 is needed)
        diamond = CrystalStructure('3.567 3.567 3.567', 
        'F d -3 m',   
        'C 0.000 0.000 0.000 1.0 0.00843')

        print("WSName is: ", wsName)
        ws = mtd[wsName]
        ws.sample().setCrystalStructure(diamond)

        #load UB into peaks workspace
        LoadIsawUB(InputWorkspace=wsName,
            Filename=UBPath)
    
        SetGoniometer(Workspace=wsName, Axis0='omega, 0,1,0,1')
    

        generator = ReflectionGenerator(diamond)
        hkls = generator.getHKLs(0.5,2.5) #complete list of all HKL
        UB = ws.sample().getOrientedLattice().getUB()
        print("Input UB" )
        print(f"{UB[0,0]:.5f} {UB[0,1]:.5f} {UB[0,2]:.5f}")
        print(f"{UB[1,0]:.5f} {UB[1,1]:.5f} {UB[1,2]:.5f}")
        print(f"{UB[2,0]:.5f} {UB[2,1]:.5f} {UB[2,2]:.5f}")

        reflections = []
        for hkl in hkls:
            QLab = 2*np.pi*np.dot(UB, hkl)
            magQ = np.linalg.norm(QLab) #note ISAW convention i.e. `Q=1/d`
            alp = np.degrees(np.arccos(-QLab[2]/magQ))
            ttheta = np.radians(-(180 - 2*alp))
            d = 2*np.pi/magQ #d = 1/Q
            lam = 2*d*np.sin(ttheta/2.0) #Bragg's Law lam = 2dsin(theta) = 2sin(theta)/Q
            if lam >= lamMin:  
                ref = {
                'hkl': hkl,
                'd': d,
                'wavelength': lam,
                'QLab': QLab,
                }
                reflections.append(ref)
        print(f"found {len(reflections)} reflections for wavelength >= {lamMin}")

        #create eyes

        for ref in reflections:
            lam = ref['wavelength'] 
            #calculate width
            width = 0
            for i in range(len(widthCoef)):
                width += widthCoef[i]*lam**i

            #create eye
            if isLite:
                inputWorkspaceIndexSet = '0-18431'
            else:
                inputWorkspaceIndexSet = '0-1179647'

            oneEye = eye(xMin=lam-width/2,
                         xMax=lam+width/2,
                         xUnits='Wavelength',
                         inputWorkspaceIndexSet=inputWorkspaceIndexSet,
                         isLite=True)
            
            #add to list
            self.eyeList.append(oneEye)
        
        print(f"calculated {len(reflections)} notches in {UBPath}")
        self.processCheese()

    def inspectInWavelength(self,wsName):

        sumWS = f"{wsName}_sum"
        sumWS_notch = f"{wsName}_notched_sum" 
        
        ConvertUnits(InputWorkspace=wsName,
                     OutputWorkspace=sumWS,
                     Target='Wavelength')
        
        Rebin(InputWorkspace=sumWS,
                OutputWorkspace=sumWS,
                Params='0.5,-0.001,4.5',
                PreserveEvents=False)

        CloneWorkspace(InputWorkspace=sumWS,
                        OutputWorkspace=sumWS_notch)

        SumSpectra(InputWorkspace=sumWS,
                    OutputWorkspace=sumWS)
        
        #apply the notches

        for oneEye in self.eyeList:
            try:
                MaskBins(InputWorkspace=sumWS_notch,
                    XMin=oneEye.xMin,
                    XMax=oneEye.xMax,
                    InputWorkspaceIndexSet=oneEye.inputWorkspaceIndexSet,
                    OutputWorkspace=sumWS_notch)
            except:
                pass

        SumSpectra(InputWorkspace=sumWS_notch,
                    OutputWorkspace=sumWS_notch)
        
        #create ticks workspace
        allWavelengths = []
        for oneEye in self.eyeList:
            allWavelengths.append(0.5*(oneEye.xMin+oneEye.xMax))
        allWavelengths = np.array(allWavelengths)
        #get range of y values in summed data
        ws = mtd[sumWS]
        yMin = min(ws.dataY(0))
        yMax = max(ws.dataY(0))
        #create ticks workspace
        tickYval = (yMin+0.1*(yMax-yMin))*np.ones_like(allWavelengths)
        CreateWorkspace(OutputWorkspace='ticks',
                        DataX=allWavelengths,
                        DataY=tickYval,
                        NSpec=1,
                        UnitX='Wavelength')
        ws = mtd["ticks"]
        ws.setPlotType("marker")
        
    def extractFromWorkspaceHistory(self,wsName):
        #this function supports extracting the swiss cheese from a workspace where a user
        #has manually created a mask in showInstrument view

        ws = mtd[wsName]
        mask_units = ws.getAxis(0).getUnit().caption()
        mask_xmins = []
        mask_xmaxs = []
        mask_spectraLsts = []
        if ws.getNumberHistograms() == 96*192:
            isLite=True
        elif ws.getNumberHistograms() == 1179648:
            isLite=False
        else:
            raise ValueError(f"workspace {wsName} has unexpected number of spectra {ws.getNumberHistograms()}")
        
        #get the history of the workspace
        h = ws.getHistory().getAlgorithmHistories()
        #loop over the history and extract the MaskBins operations
        for hi in h:
            if hi.name() == 'MaskBins':
                #get the xMin, xMax and spectraList for each MaskBins operation
                mask_xmins.append(hi.getPropertyValue('XMin'))
                mask_xmaxs.append(hi.getPropertyValue('XMax'))
                mask_spectraLsts.append(hi.getPropertyValue('InputWorkspaceIndexSet'))

        #create the eyes and append to eyeList
        for i in range(len(mask_xmins)):
            
            try:
                xMin = mask_xmins[i]
                xMax = mask_xmaxs[i]
                spectraLsts = mask_spectraLsts[i]
                units = mask_units
                isLite = isLite

                #create eye
                oneEye = eye(xMin=xMin,xMax=xMax,xUnits=units,inputWorkspaceIndexSet=spectraLsts,isLite=isLite)
                
                #add to list
                self.eyeList.append(oneEye)
            except:
                pass
    
        print(f"found {len(mask_xmins)} eyes in {wsName} history")
        self.processCheese()

    def processCheese(self):

        self.eyeList = sorted(self.eyeList, key=lambda x: x.xUnits)
        self.numberOfEyes = len(self.eyeList)
        allUnits = [eye.xUnits for eye in self.eyeList] 
        self.uniqueUnits = list(set(allUnits))
        self.uniqueUnits.sort()
        self.unitCount = len(self.uniqueUnits)

        #todo confirm all eyes are same isLite
        allLiteStatus = [eye.isLite for eye in self.eyeList]
        liteSet = set(allLiteStatus)
        if len(liteSet) > 1:
            raise ValueError(f"swiss cheese contains eyes with different isLite status: {liteSet}")
        self.isLite = allLiteStatus[0]

    def makeMaskBinsTables(self):
        #create maskBins Tables for use by maskBins 

        for unit in self.uniqueUnits:
            unitEyes = [eye for eye in self.eyeList if eye.xUnits == unit]
            unitEyes.sort(key=lambda x: x.xMin)
            unitXmins = [eye.xMin for eye in unitEyes]
            unitXmaxs = [eye.xMax for eye in unitEyes]
            unitSpectraLsts = [eye.inputWorkspaceIndexSet for eye in unitEyes]

            #create a maskBins table
            binTable = CreateEmptyTableWorkspace(OutputWorkspace=f"maskBins_{unit}")
            binTable.addColumn('double','XMin')
            binTable.addColumn('double','XMax')
            binTable.addColumn('str','SpectraList')
            # binTable.addColumn('str','units')
            #add the data to the table
            for i in range(len(unitXmins)):
                # print(unitXmins[i],unitXmaxs[i],unitSpectraLsts[i],unit)
                # print(type(unitXmins[i]),type(unitXmaxs[i]),type(unitSpectraLsts[i]))
                binTable.addRow([unitXmins[i],unitXmaxs[i],unitSpectraLsts[i]])

    def save(self,filePath,filePrefix):
        
        for unit in self.uniqueUnits:
            unitEyes = [eye for eye in self.eyeList if eye.xUnits == unit]
            unitEyes.sort(key=lambda x: x.xMin)
            unitXmins = [eye.xMin for eye in unitEyes]
            unitXmaxs = [eye.xMax for eye in unitEyes]
            unitSpectraLsts = [eye.inputWorkspaceIndexSet for eye in unitEyes]

            #create file path
            if filePath[-1] != '/':
                filePath += '/'
            fileName = f"{filePath}{filePrefix}_{unit}.json"

            #create dictionary
            maskBinsTable = {
                'units': unit,
                'isLite': self.isLite,
                'xmins': unitXmins,
                'xmaxs': unitXmaxs,
                'spectraLsts': unitSpectraLsts
            }
            with open(fileName, "w") as outfile:
            
                json.dump(maskBinsTable, outfile, indent=2)

            print(f"saved mask to: {fileName}")

 