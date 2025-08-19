from snapwrap.SEEMeta import utils

#check if a material exists in the database
utils.materialInDatabase("tizr")

#add a new column to the table
utils.add_column_to_materials_table("isSingleCrystal", column_type="BOOLEAN", default_value=False)

#check this worked
utils.list_columns_in_table()

#update a material's column
utils.update_entry("singleCrystalDiamond", "isSingleCrystal", True)
#check the update worked
matprop = utils.get_material_details("singleCrystalDiamond")

print("isSingleCrystal for singleCrystalDiamond:", matprop["isSingleCrystal"])

