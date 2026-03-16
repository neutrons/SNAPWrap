# some tools to operate on spectra of reduced data in workspaces

import numpy as np
from mantid.simpleapi import *
from snapwrap.utils import workspaceHandles

def excludeROI(wsName, wsIndex, roiList, createExcludedWS=False):
    # takes a list of [xMin,xMax] values and for specified index in WS sets corresponding Y-values
    # to NAN

    ws = mtd[wsName]
    x = ws.readX(wsIndex)  # bin edges length = nBins+1
    y = ws.dataY(wsIndex).copy()  # work on a copy

    if createExcludedWS:
        y_excl = np.full_like(y, np.nan)

    excludedPoints = 0
    original_y = ws.dataY(wsIndex)  # keep original for excluded_ws

    # use x[:-1] to align with y (bins)
    x_bin_edges = x[:-1]

    for roi in roiList:
        # boolean mask for bins whose left-edge falls inside ROI
        mask = (x_bin_edges >= roi[0]) & (x_bin_edges <= roi[1])
        if not np.any(mask):
            continue
        indices = np.where(mask)[0]  # 1D index array
        y[indices] = np.nan
        excludedPoints += len(indices)
        if createExcludedWS:
            y_excl[indices] = original_y[indices]

    # write back once
    ws.setY(wsIndex, y)

    if createExcludedWS:
        out_name = "excluded_" + wsName
        CloneWorkspace(InputWorkspace=wsName, OutputWorkspace=out_name)
        excluded_ws = mtd[out_name]  # get workspace object
        excluded_ws.setY(wsIndex, y_excl)
        excluded_ws.setX(wsIndex, x)
        excluded_ws.setTitle("Excluded data from " + wsName)
        excluded_ws.setPlotType("marker")
        excluded_ws.setMarkerStyle("circle")

    # print(f"Debug: excluded {excludedPoints} points in total from spectrum {wsIndex} of workspace {wsName}")

def replacePrefix(wsName,newPrefix):
    #update SNAPRed style ws name
    newWsName = newPrefix + "_" + wsName.split('_',1)[1]
    return newWsName
    
def runningAverage(arr, window_size):

    #returns the running average of input array with averaging calculated over window_size
    kernel = np.ones(window_size) / window_size
    return np.convolve(arr, kernel, mode='same')  # or 'valid', or 'full'

def deNAN(wsName,wsIndex,N):

    # a spectrum specified by its mantid workspace name and workspace index is searched
    # for regions of NAN (these occur e.g. when stripping peaks). The NAN are then replaced with
    # a linear interpolation that uses the N points on either side of the NAN region.
    # TODO: ensure that spectrum doesnt begin with NAN
    # TODO: handle when N points overlap with another region of NAN.
    
    from scipy.stats import linregress
    
    #linearly interpolate between regions of NAN using the N y values beyond the NAN region
    
    ws = mtd[wsName]
    x = ws.dataX(wsIndex)
    y = ws.dataY(wsIndex)
    isnan = np.isnan(y)
    n = len(y)
    
    y_filled = y.copy()
    
    i = 0
    while i < n:
        
        if isnan[i]:
            start = i
            while i < n and isnan[i]:
                i += 1
            end = i #end is the first non-NaN after the Nan block
            
            left_idx = np.where(~isnan[:start])[0][-N:] if start >= N else np.where(~isnan[:start])[0]
            right_idx = np.where(~isnan[end:])[0][:N] + end if (n - end) >= N else np.where(~isnan[end:])[0] + end

            if len(left_idx) == 0 or len(right_idx) == 0:
                continue  # skip if not enough data on either side

            x_known = np.concatenate((x[left_idx], x[right_idx]))
            y_known = np.concatenate((y[left_idx], y[right_idx]))

            # Linear regression
            slope, intercept, *_ = linregress(x_known, y_known)

            # Fill in missing values
            for j in range(start, end):
                y_filled[j] = slope * x[j] + intercept
        else:
            i += 1
            
    ws.setY(wsIndex,y_filled)

def compatibleWorkspaces(handles):

    #need to check that all handles in list have same number of spectra and that these
    #all have equal binning

    allowedNumberOfHistograms = handles[0].nHist 
    for handle in handles:
        if handle.nHist != allowedNumberOfHistograms:
            print("Error! all histograms must have the same size")
            print("reference workspace {handles[0].wsName} has {handles[0].nHist} spectra")
            print("submitted workspace {handle.wsName} has {handle.nHist} spectra")
            return False
    
    # check input histograms have identical binning
    for h in range(allowedNumberOfHistograms):
        for i,handle in enumerate(handles):
            ws = mtd[handle.wsName]
            xVals = ws.readX(h)
            if i == 0: 
                referenceLength = len(xVals)
            else:
                length = len(xVals)
                if length != referenceLength:
                    print("Error: histogram bins are not equal") #TODO: make error more insightful 
                    return False
                
    return True


def compositeBackground(handles,dMin=0.65,
                        dMax=10.0,
                        minFractionOfMaxIntensity=0.00,
                        extentScale=1.0,
                        createExcludedWS=False):

    #calculate exclusion ROI's using crystalSpecies
    #calculation runs as a for loop over number of input spectra that are specified by the handles list 

    # Need to ensure all input workspaces have same number of spectra
    if not compatibleWorkspaces(handles):
        print("compositeBackground: Submitted workspaces not compatible")
        return
    else:
        print("compositeBackground: workspaces are compatible")

    #create clones of input workspace to hold the de-peaked spectra 
    # calculate the exclusion regions for each spectrum and set the corresponding
    # y-values to NAN.

    for runID,handle in enumerate(handles):
        wsName = handle.wsName
        runInt = handle.runNumber
        
        dePeakWS = replacePrefix(wsName,"dePeak")
        CloneWorkspace(InputWorkspace=wsName,
            OutputWorkspace=dePeakWS)

        #confirm that crystalSpeciesList is defined
        print(f"workspace {wsName} has {len(handle.crystalSpeciesList)} crystal species")
        if len(handle.crystalSpeciesList) > 0:
            for creature in handle.crystalSpeciesList:
                print(f"species {creature.name} has EOP {creature.extentOverPosition}")
        #now loop through all spectra in the input workspaces
        nSpec = handles[0].nHist
        
        for specID in range(nSpec):

            excludeList = []
            for creature in handle.crystalSpeciesList:

                print(f"\nProcessing species {creature.name} for spectrum {specID} of run {runInt}")
                
                #apply dLimit override if specified taking care to retain original dMin,dMax values        
                if creature.dLimits is not None:
                    print(f"applying dLimits for species {creature.name}")
                    dMinOverride = creature.dLimits[0]
                    dMaxOverride = creature.dLimits[1]
                else:
                    dMinOverride = dMin
                    dMaxOverride = dMax

                print(f"using dMin: {dMinOverride} and dMax: {dMaxOverride} for d-spacing calculation")
                creature.calcDSpacings(dMin=dMinOverride,
                                        dMax=dMaxOverride,
                                        minFractionOfMaxIntensity=minFractionOfMaxIntensity)
                
                for d in creature.dSpacings:
                    extent = extentScale*d*creature.extentOverPosition
                    roi = [d-extent/2,d+extent/2]
                    excludeList.append(roi)      

            excludeROI(dePeakWS,specID,excludeList,createExcludedWS=createExcludedWS) #will set x-ranges in excludeList in spectrum specID to NAN
            print(f"for spec: {specID}, {len(excludeList)} regions were excluded")              

    #now need to determine the average of all depeaked spectra ignoring NAN values
    #first need handles on the dePeaked workspaces

    dePeakedHandles = workspaceHandles(prefix="dePeak",
                                            PGS = handles[0].pixelGroup)
       
    CloneWorkspace(InputWorkspace=handles[0].wsName,
        OutputWorkspace="avgBgnd")
    wsOut = mtd["avgBgnd"]

    #create lists to hold all y-values for each spectrum
    listOfYValues = []

    for specID in range(nSpec):

        stack = [] #stack arrays of y-values for each spectrum
        for handle in dePeakedHandles:
            ws = mtd[handle.wsName]
            stack.append(ws.dataY(specID))

        stack = np.stack(stack)
        print(f"for spec: {specID} dimensions of state are: {stack.shape}")
        #average the stack, ignoring NAN values
        avg = np.nanmean(stack,axis=0)
        #set the y-values of the output workspace to the average
        wsOut.setY(specID,avg)

    #linearly interpoloate over any NAN values in the average
    CloneWorkspace(InputWorkspace="avgBgnd",
                   OutputWorkspace="avgBgnd_interp")
    
    for specID in range(nSpec):
        deNAN("avgBgnd_interp",specID,5)
    
    # wsBgd = mtd["avgBgnd"]
    # bgnd = wsBgd.dataY(0)
    
    # #Finally export data for refinement
    # for handle in handles:
    #     wsName = handle.wsName
    #     runNo = handle.runNumber
    #     runInt = int(runNo.strip())
    
    #     if runInt in runs:
    #         wsName_bs = replacePrefix(wsName,"backSub")
    #         CloneWorkspace(InputWorkspace=wsName,
    #             OutputWorkspace=wsName_bs)
    #         ws = mtd[wsName_bs]
    #         y0 = ws.dataY(0)
    #         e0 = ws.dataE(0)
            
    #         ws.setY(0,100*(y0-bgnd)+1.0) #rb. scale factor and adding 1.0 to avoid zeros from back sub
    #         ws.setE(0,100*e0)