# Set up

There are two main prerequisites for running SNAPBlue: 

1. you should have the SNAPRed conda environment set up and activated
2. you should have a local copy of the SNAPRed repo available. For now, "nightly" version of SNAPRed is available at `/SNS/SNAP/shared/code/SNAPRed` this will be treated as the default version of SNAPRed for now. 

Hopefully, soon, a formal deployment will negate the need to worry about 1. & 2.

## Set up conda environment

Important note: These instructions presume that you have a local instal of conda. If this is **not** the case, then easiest is to probably sit down with Malcolm to set that up.

With conda available, open a terminal and navigate to the SNAPRed repo.

```
cd /SNS/SNAP/SNS/shared/code/SNAPRed
```

inside this location is an `environment.yml` file. To create the necessary conda environment, the command is:

```
conda env create -f environment.yml
```

Once conda has done its thing, the environment can then be activated using:
```
conda activate SNAPRed
```
Occasionally, updates to mantid (or other software dependencies) may require updating of this environment. To do this, the command is: 
```
conda env update --file environment.yml  --prune
```
(note: this presupposes the repo itself has been updated)

## Open (the right version of) mantid workbench

The SNAPRed environment has a pre-installed version of mantid workbench that has SNAPRed built in. This is the specific version we want to run.

In addition, we want to make sure that the SNAPRed repo is on our path. The following commands should make this all happen:

```
conda activate SNAPRed
cd /SNS/SNAP/shared/code/SNAPRed/src
python -m workbench
```
This will open a "normal"-looking version of mantidworkbench, but it has SNAPRed inside it

## running SNAPBlue

if you have followed the instructions above, SNAPRed is available inside mantid workbench. However we will access SNAPRed using the SNAPBlue scripting layer.

This is typically done by running simple python scripts inside the workbench script editor. In order to access SNAPBlue functions, you have first ensure that the repo is on your path and then you have to import the various SNAPBlue modules. The core module is called `blueUtils` it can be imported inside your python script using: 
```
import sys
sys.path.append("/SNS/SNAP/shared/code/SNAPBlue") # this makes sure the repo is on the path

import blueUtils as blue
```