import sys
import time
import importlib

import snapwrap.utils as wrap
import snapwrap.snapStateMgr as ssm
importlib.reload(snapwrap)
from mantid import config
config.setLogLevel(3, quiet=True)

t0 = time.time()

#IF STATE DOESN'T EXIST SNAPRED WILL FAIL!!!!!!!!!
#
#ssm.checkStateExists(64413) # checks if state exists for run 64413
#
#ssm.createState(64413) will create a state for run 64413. # Currently this only works for instrument scientists with write permissions
#                                                          # to the Calibration.home directory                  

# Data are reduced with wrap.reduce Minimum input is a run-number but
# various options can be set as described here: 

wrap.reduce(64413,
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
)

print(f"\n Complete! execution took: {time.time()-t0:.1f}s")