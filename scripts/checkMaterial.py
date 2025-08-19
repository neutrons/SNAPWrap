import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from snapwrap.SEEMeta import utils

#check that a material exists
utils.materialInDatabase("TiZr")
# get details
deets = utils.get_material_details("TiZr")
print("TiZr details:", deets)