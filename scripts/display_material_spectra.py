from snapwrap.SEEMeta import utils,material
from snapwrap.wrapConfig import WrapConfig

spectraPath = WrapConfig.get("SEE/materials/spectra")

materials = ["zta", "TiZr","wc", "sinteredDiamond"]

for mat in materials:

    dbEntry = material.material(name=mat)
    matID = dbEntry.get_id()

    # look at current spectra associated with this material
    print(f"Current spectra for {dbEntry.name} (ID: {matID}):")
    if not dbEntry.hasSpectra:
        print("  No spectra associated with this material.")
    else:
        for spec in dbEntry.spectra:
            print(spec)
