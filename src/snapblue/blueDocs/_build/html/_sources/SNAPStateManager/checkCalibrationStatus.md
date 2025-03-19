# `checkCalibrationStatus`

This function requires three arguments: 

1. `stateID`: which state to check the calibration status of
2. `isLite`: whether to check lite or native calibration status
3. `calType`: one of two strings: "difcal" or "normcal" to specify whether diffraction or normalisation calibration is to be checked

It returns a dictionary with full information regarding the requested calibration status

Example:
```
import SNAPStateMgr as ssm

isLite = True
calDict = ssm.checkCalibrationStatus("3c7b8c841d10a16b",isLite,"difcal")
for key in calDict:
    if key != "calibIndex":
        print(key,":",calDict[key])
    else:
        print("\nCalibration Index entries:\n")
        for calibEntry in calDict[key]:
            for key2 in calibEntry:
                print(key2,":",calibEntry[key2])
```
returns
```
stateID : 3c7b8c841d10a16b
calibrationType : difcal
isLite : True
isCalibrated : True
numberCalibrations : 1
latestCalibration : 2025-02-17 14:31:11
calibRuns : ['64437']
indexPath : /SNS/SNAP/shared/Calibration_testing/Powder/3c7b8c841d10a16b/lite/diffraction/CalibrationIndex.json

Calibration Index entries:

version : 0
runNumber : 64437
useLiteMode : True
appliesTo : >=0
comments : The default configuration when loading StateConfig if none other is found
author : SNAPRed Internal
timestamp : 1739820536.8264458
version : 1
runNumber : 64437
useLiteMode : True
appliesTo : >=0
comments : test
author : C Ridley
timestamp : 1739820671.918172
mostRecentCalib : {'version': 1, 'runNumber': '64437', 'useLiteMode': True, 'appliesTo': '>=0', 'comments': 'test', 'author': 'C Ridley', 'timestamp': 1739820671.918172}
```
note that `calDict["calibIndex"]` is a list of dictionaries, one for each calibration that exists in the index.
