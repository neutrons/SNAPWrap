import sys
import time
import importlib
sys.path.append("/SNS/SNAP/shared/code/SNAPBlue")
import snapblue.blueUtils as blue
importlib.reload(blue)
from mantid import config
config.setLogLevel(3, quiet=True)
t0 = time.time()

#IF STATE DOESN'T EXIST SNAPRED WILL FAIL!!!!!!!!!
# STATE CAN BE CREATED WITH THE TEST PANEL (YOU JUST NEED A RUN NUMBER)

# Data are reduced with blue.reduceSNAP. Minimum input is a run-number but
# various options can be set as described here 
# 
blue.reduce(64413,#)#,
# pixelMaskIndex=1,
verbose=True,keepUnfocussed=True,
lambdaCrop=False)


# blue.indexStates()

# blue.reduce(64687,
# # pixelMaskIndex=1,
# verbose=True,keepUnfocussed=True)
# blue.reduce(64687,
# # pixelMaskIndex=1,
# verbose=True,keepUnfocussed=True)

#Other optional arguments with their default values

# sampleEnv='none', location of .yml file specifying a sample environment (NOT WORKING YET)
# pixelMaskIndex='none', index "m" of an existing maskworkspace, must have name "MaskWorkspace_m"
# YMLOverride='none', location of .yml file that will override default .yml
# continueNoDifcal = False, if True, allows diagnostic reduction using IDF when no difcal exists
# continueNoVan = False, if True, allows diagnostic reduction with artificial normalisation (from extracted background)
# verbose=False, if True reports useful info about reduction parameters
# reduceData=True, if False data will not be reduced (but reduction parameters can be gathered for inspection)
# lambdaCrop=True, #if True removes all events outside of allowed rang (temporarily needed until SNAPRed can do this during reduction).
# emptyTrash=True, #if True removes all intermediate workspaces during reduction leaving a clean tree (except the unfocussed vanadium)
# cisMode=False): $if True intermediate workspaces retained (WARNING: this can use a lot of RAM)


# Examples 

# #example run with full calibration the "Happy Path"
# 
# blue.reduce(64431
#     )

#example run where state exists but has no difcal or normcal

# blue.reduce(63424,
#     continueNoVan=True,
#     continueNoDifcal=True
#     )    

#example run where difcal exists but normcal doesn't

# blue.reduce(58882,
#    continueNoVan=True
#    ) 

#example using override yml

# blue.reduce(61991,
#     YMLOverride = "/SNS/SNAP/shared/Malcolm/SNAPBlue/override.yml", # set to retain unfocussed ws
#     pixelMaskIndex = [2]
#     )

print(f"\n Complete! execution took: {time.time()-t0:.1f}s")