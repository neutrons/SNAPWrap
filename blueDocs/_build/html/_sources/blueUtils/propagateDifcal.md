# `propagateDifcal`

## Overview

It is fequently useful (and sometimes necessary) to copy a diffraction calibration (difcal) from one state to another. This is a valid operation when the donor and destination states have identical detector positions. When provided with the run number of an existing difcal operation, `propagateDifcal` automatically identifies (existing) compatible states and copies the calibration across, while also updating the calibration indices used by SNAPRed to locate the new calibration.

```{note}
If you need to create a state in order to subsequently copy a difcal into it, this can be done with a separate utility called `SNAPStateManage` TODO: create docs for this too
```
Typical usage would be 

```
import sys
sys.path.append("/SNS/SNAP/shared/code/SNAPBlue")

import blueUtils as blue

blue.propagateDifcal(64431)
```

If necessary, it is possible to create a new state first, making it available to propage the difcal to. This can be done with a separate module called `SNAPStateMgr` which has a function called `createState` (TODO: need docs for this). 

For example: 
```
import sys
sys.path.append("/SNS/SNAP/shared/code/SNAPBlue")

import blueUtils as blue
import SNAPStateMgr as ssm

ssm.createState(64433) #creates 6.4Å state
blue.propagateDifcal(64431) #propagates an existing calibration made using run 64431 to this state
```

## `isLite`

Calibrations are lite/native dependent and must be conducted separately for each mode. Since propagation of a difcal relies on it existing, the corresponding calibration must have been conducted. 

By default `isLite=True` but, if an existing `native` calibration needs to be transferred, this can be done by specifying `isLite=False`.

## `propagate`

It is considered good practice to examine the expected outcome of propagation _without actually propagating any data_. Consequently, this is the default behaviour and the parameter `propagate` set equal `False`.

Once you are sure everything looks good, setting `propagate=True` will actually propagate the calibration
