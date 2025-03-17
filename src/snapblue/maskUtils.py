# a module with some protoype functions for the generation and management of SEE masks in 
# mantid workbench.
#
# since this is just at the prototype stage, these function should only be expected to work with Lite SNAP

#Note the environment autoMask should be activated!

import copy
import importlib

from mantid.simpleapi import *
import matplotlib.pyplot as plt
import numpy as np
import skimage as ski

import sys

class sliceImage:

    def __init__(self,wsName,xMin=0,xMax=100):
    
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

    inputMask = sliceImage.image

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
    Create a `MaskWorkspace` compatible with a template workspace
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