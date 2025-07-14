from snapwrap.SEEMeta import utils,material
from snapwrap.wrapConfig import WrapConfig

spectraPath = WrapConfig.get("SEE/materials/spectra")

# add all spectra. Note this scripts is set up to  Each material has a name (link to material in database)
# and a set of spectral data. These are both stored in a dictionay for each materials, 
# added to a list and then the list is processed.

removeExisting = True # This will clear all existing spectra and overwrite with the new ones.

#define spectral attributes as dictionary
mat_zta = {"name":"ZTA",
           "spectrum_data":{
            # "material_id": 16, # need to allocate this dynamically
            "spectrum_type": "experimental",
            "x_axis_name" : "Wavelength",
            "y_axis_name" : "Linear attenuation coefficient",
            "y_axis_units": "mm^-1",
            "data_format": "dat", #TODO consolidate to csv?
            "comment": "ISIS files from Chris R. ",
            "file_path": spectraPath + "/ZTA_MU.DAT"}
           }
mat_TiZr = {"name":"TiZr",
           "spectrum_data":{
            "spectrum_type": "experimental",
            "x_axis_name" : "Wavelength",
            "y_axis_name" : "Linear attenuation coefficient",
            "y_axis_units": "mm^-1",
            "data_format": "dat", #TODO consolidate to csv?
            "comment": "ISIS files from Chris R. ",
            "file_path": spectraPath + "/TIZR7054_MU.DAT"}
           }
mat_wc = {"name":"WC",
           "spectrum_data":{
            "spectrum_type": "experimental",
            "x_axis_name" : "Wavelength",
            "y_axis_name" : "Linear attenuation coefficient",
            "y_axis_units": "mm^-1",
            "data_format": "dat", #TODO consolidate to csv?
            "comment": "ISIS files from Chris R. ",
            "file_path": spectraPath + "/WC_HOYBIDE_NK_MU.DAT"}
           }

mat_sinteredDiamond = {"name":"SinteredDiamond",
           "spectrum_data":{
            "spectrum_type": "experimental",
            "x_axis_name" : "Wavelength",
            "y_axis_name" : "Linear attenuation coefficient",
            "y_axis_units": "mm^-1",
            "data_format": "dat", #TODO consolidate to csv?
            "comment": "ISIS files from Chris R. ",
            "file_path": spectraPath + "/DIAM_DEBEERS_MU.DAT"}
           }

materials = [mat_zta, mat_TiZr, mat_wc, mat_sinteredDiamond]

# add spectra to database
for mat in materials:

    dbEntry = material.material(name=mat["name"])
    matID = dbEntry.get_id()

    # look at current spectra associated with this material
    print(f"Current spectra for {dbEntry.name} (ID: {matID}):")
    if not dbEntry.hasSpectra:
        print("  No spectra associated with this material.")
    else:
        for spec in dbEntry.spectra:
            print(spec)
            if removeExisting:
                # remove existing spectra if requested
                utils.remove_spectrum_from_material(matID, spec["id"])

    # allocate material ID to spectrum_data dictionary
    mat["spectrum_data"]["material_id"] = matID
    # link spectral_data to material
    utils.link_spectrum_to_material(matID, mat["spectrum_data"])
