from snapwrap.SEEMeta import utils,material
from snapwrap.wrapConfig import WrapConfig

utils.add_column_to_spectra_table (column_name="comment", column_type="TEXT", default_value="")
utils.add_column_to_spectra_table (column_name="x_axis_name", column_type="TEXT", default_value="")
utils.add_column_to_spectra_table (column_name="y_axis_name", column_type="TEXT", default_value="")
utils.add_column_to_spectra_table (column_name="y_axis_units", column_type="TEXT", default_value="")
utils.add_column_to_spectra_table (column_name="data_format", column_type="TEXT", default_value="")

