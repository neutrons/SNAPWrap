# SNAPStateMgr

A core concept in SNAPRed is the creation and management of a collection of different instrument configurations (known as "states") and associated orchestration of calibration and reduction tasks. The `SNAPStateMgr` module in `SNAPBlue` is a collection of utilities that exploit this functionality to do useful things inside any python script.

As with `blueUtils` it is intended to be imported into python scripts allowing its functions to be used. I typically import it as `ssm`: 

```
import sys
sys.path.append("/SNS/SNAP/shared/code/SNAPBlue")

import blueUtils as blue
import SNAPStateMgr as ssm
```

```{note}
An important part of the orchestration of SNAPRed is the definition of a home calibration directory. This is defined in a file called `application.yml` that lives inside the SNAPRed repo. Depending on which version of the repo is being used by `SNAPBlue` this _could_ point to different locations. It's important to consider this. The `SNAPStateMgr` utility `printCalibrationHome` can be used to check the current home location.
```

