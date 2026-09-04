# some tools to operate on spectra of reduced data in workspaces

import numpy as np
from mantid.simpleapi import *
from scipy.interpolate import make_smoothing_spline
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

def smoothBackground(wsName, roiList, smoothing_parameter, outputWorkspace=None):
    """
    Produce a smooth background estimate by excluding peak regions and fitting a spline.

    For every spectrum in the input workspace the bins that fall inside any ROI
    are masked out, a smoothing spline is fitted to the surviving points, and the
    spline is evaluated over the full x-range.  The result is a histogram workspace
    with identical binning to the input — suitable for direct subtraction.

    Parameters
    ----------
    wsName : str
        Name of the input histogram workspace (units typically dSpacing).
    roiList : list of [float, float]
        Exclusion regions ``[[xMin, xMax], ...]``.  Bins whose left edge
        falls inside any region are excluded from the spline fit.
    smoothing_parameter : float
        The ``lam`` parameter passed to ``scipy.interpolate.make_smoothing_spline``.
        Larger values produce smoother backgrounds.
    outputWorkspace : str or None
        Name for the output workspace.  If *None*, defaults to
        ``"smooth_" + wsName``.

    Returns
    -------
    str
        The name of the output workspace held in the Mantid ADS.
    """

    if outputWorkspace is None:
        outputWorkspace = "smooth_" + wsName

    CloneWorkspace(InputWorkspace=wsName, OutputWorkspace=outputWorkspace)

    ws_in = mtd[wsName]
    ws_out = mtd[outputWorkspace]
    nSpec = ws_in.getNumberHistograms()

    for idx in range(nSpec):
        x = ws_in.readX(idx)
        y = ws_in.readY(idx).copy()
        xMid = (x[:-1] + x[1:]) / 2.0

        # build mask: True = keep, False = exclude
        mask = np.ones(len(y), dtype=bool)
        for roi in roiList:
            mask &= ~((xMid >= roi[0]) & (xMid <= roi[1]))

        x_keep = xMid[mask]
        y_keep = y[mask]

        if len(y_keep) == 0:
            print(f"Warning: all data excluded for spectrum {idx}, output set to zero.")
            ws_out.setY(idx, np.zeros_like(y))
            continue

        tck = make_smoothing_spline(x_keep, y_keep, lam=smoothing_parameter)
        smoothed = tck(xMid, extrapolate=False)

        # replace any NaN from extrapolation and negative artifacts with zero
        smoothed = np.nan_to_num(smoothed, nan=0.0)
        smoothed[smoothed < 0] = 0.0

        ws_out.setY(idx, smoothed)

    return outputWorkspace

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
                        createExcludedWS=False,
                        splineSmooth=1e-4):

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

                creatureTickWS = f"ticks_{creature.name}_run{runInt}_spec{specID}"

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
                
                tickYPos = 0.005*np.ones_like(creature.dSpacings) #how to set this?
                CreateWorkspace(OutputWorkspace=creatureTickWS,
                                DataX=creature.dSpacings,
                                DataY=tickYPos)

                tickws = mtd[creatureTickWS]
                tickws.setPlotType("marker")

                for d in creature.dSpacings:
                    extent = extentScale*d*creature.extentOverPosition
                    roi = [d-extent/2,d+extent/2]
                    excludeList.append(roi)

            smoothWS = replacePrefix(wsName,"smooth")
            smoothBackground(wsName,excludeList,smoothing_parameter=splineSmooth,outputWorkspace=smoothWS)
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

    #finally apply some gentle smoothing

    SmoothData(InputWorkspace="avgBgnd_interp",
               OutputWorkspace="avgBgnd_interp",
               NPoints=5)