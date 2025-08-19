import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from snapwrap.SEEMeta import utils

#check that a material exists
utils.materialInDatabase("TiZr")
# get details
for material in ["TiZr", "singleCrystalDiamond"]:
    if utils.materialInDatabase(material):
        print(f"{material} exists in the database.")
    else:
        print(f"{material} does not exist in the database.")

    deets = utils.get_material_details(material)
    print(f"{material} details:", deets)