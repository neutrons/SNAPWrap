# Transmission monitor for notches

This document gives an overview of using transmission montitor to identify notch parameters and create a swisscheese from these.

# Accessing transmission monitor data

monitor data are stored in the main nexus file and are accessed using mantid `LoadNexusMonitors` (mantid algorithm). Depending on run collection date, SNAP has 2 or 3 different physical monitors, the transmission monitor of interest has workspace index = 1 (and spectrum number = 2). The monitor data are stored in events, but we need a histogram of these as a function of wavelength. We need to follow this recipe, which also requires SNAPRed (we have both mantid and snapred in our pixi environment):

```
#0. Determine IPTS and stateID from runNumber

import snapwrap.snapStateMgr as ssm

runNumber = 65891
[stateID,stateDict] = ssm.stateDef(runNumber)
ipts = GetIPTS(Instrument="SNAP",RunNumber=runNumber)
useLiteMode = True (this is the default)


#1. Determine wavelength limits for current state from SNAPRed:

from snapred.backend.dao.request.FarmFreshIngredients import FarmFreshIngredients
from snapred.backend.service.SousChef import SousChef

# obtain useful values from instrument state

farmFresh = FarmFreshIngredients(
    runNumber=runNumber,
    useLiteMode=useLiteMode,
    focusGroups=[{"name":"All", "definition":""}], #pixel group irrelevant, so just choose one.
    state=stateID)

instrumentState = SousChef().prepInstrumentState(farmFresh)

lamMin = instrumentState.particleBounds.wavelength.minimum
lamMax = instrumentState.particleBounds.wavelength.maximum

#2. Load monitor data, convertUnits and then Rebin using wavelength limits:

## Load monitor data
LoadNexusMonitors(Filename='/SNS/SNAP/IPTS-33219/nexus/SNAP_65891.nxs.h5', 
    OutputWorkspace='monitors', LoadOnly='Events')

## Convert Units

ConvertUnits(InputWorkspace="monitors",
    OutputWorkspace="monitors",
    target="Wavelength")

##Rebin and discard events

Rebin(InputWorkspace='monitors', 
    OutputWorkspace=f'{artefactName}', 
    Params=f'{lamMin},-0.015,{lamMax}', # the -0.015 number is based on experience, but may need to be changed.
    PreserveEvents=False, 
    FullBinsOnly=True)

```
## Identifying notches.

The specific monitor we want (id==1) is the one downstream of the sample. It's spectrum consists of a broadly varying shape reflecting the incident flux profile (and detector efficiency) as a function of wavelength. Superimposed on this are sharp "notches": dips in intensity due to neutrons scattered into diamond Bragg peaks. 

Currently, this is done by manual inspection, a dip is visually identified and its limiting wavelengths determined. This is done for all notches to create a complete list of notches consists of a list of lists containing [wavelength_min,wavelength_max] for each notch. This list could be viewed as an asset. That list is then used to build a swiss cheese artefact using the snapwrap.maskUtils.swissCheese.notchFromList function

The goal of this work is to automatically idenfify notches and create the swissCheese artefact in one step (analogous to how we are building it from UB).

## Pit falls

Often notches are not nicely separated, but overlap to create continous regions of wavelength space that need to be notched out. The exact number of notches depends on how close the diamond lattice vectors align with the beam: if this angle is exactly zero degrees every equivalent reflection shares the same wavelength and merge into a single notch; as the angle increases, equivalents split and are seen at different wavelengths. 

Also, generally, the density of notches increases as wavelength decreases and, no matter how well aligned the diamonds are, the intrinsic width of the transmission dips means they all overlap below a certain wavelength, and all wavelengths below that must be notched out.

## Technical suggestion

A notch looks very similar to a peak with negative intensity, given the monitor spectrum y(wavelength), we could example -y and apply the exact same approach we have to peak identification used for our crystal strain determinations. If we used the "clip peaks" algorithm, we could divide by its output and get a flat line retaining notches.Then a simple threshold may be enough to identify the notch locations

Challenges: how to determine input params for clip peaks? there is no instprm file for the monitor.

Another potential approach is to use the UB matrices to obtain a list of expected wavelengths and then explictly search there in the monitor spectrum to identify if a notch is present and what its width is.

## Testing

I can provide an example spectrum and corresponding manual notch list, we could use that to test different implementations to see what works best.