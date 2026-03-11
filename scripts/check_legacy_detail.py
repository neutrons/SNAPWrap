#!/usr/bin/env python
"""Check all 15 legacy states for indexEntry presence across all versions."""

import json
import os

legacy = [
    "094b3bf778349fee", "3621a8676e0e95ae", "62b9099189f81ae8",
    "7297ac31012d83de", "7410ea64254694c9", "7422d766b5893dd4",
    "80f82b45769ad9ec", "81e22e8767d1fc1a", "8f9d8c3d5da04688",
    "a35f211c6bd58df7", "a37270be5816403b", "c61b49105432efb1",
    "c8625d33d276a1f5", "e013e1a9933e9852", "e99bec2493aec83d",
]

calib = "/SNS/SNAP/shared/Calibration/Powder"

for sid in legacy:
    base = f"{calib}/{sid}/lite/diffraction"
    idx = json.load(open(f"{base}/CalibrationIndex.json"))

    version_info = []
    for ie in idx:
        v = ie["version"]
        folder = f"{base}/v_{str(v).zfill(4)}"
        rec_path = f"{folder}/CalibrationRecord.json"
        par_path = f"{folder}/CalibrationParameters.json"

        rec_ie = "-"
        par_ie = "-"
        if os.path.isfile(rec_path):
            rec = json.load(open(rec_path))
            rec_ie = "Y" if "indexEntry" in rec else "N"
        if os.path.isfile(par_path):
            par = json.load(open(par_path))
            par_ie = "Y" if "indexEntry" in par else "N"

        version_info.append(f"v{v}(rec={rec_ie} par={par_ie})")

    # normcal
    norm_path = f"{calib}/{sid}/lite/normalization/NormalizationIndex.json"
    norm_info = "no normcal"
    if os.path.isfile(norm_path):
        nidx = json.load(open(norm_path))
        nv_parts = []
        for nie in nidx:
            nv = nie["version"]
            nf = f"{calib}/{sid}/lite/normalization/v_{str(nv).zfill(4)}"
            nrec_ie = "-"
            npar_ie = "-"
            nrec_p = f"{nf}/NormalizationRecord.json"
            npar_p = f"{nf}/NormalizationParameters.json"
            if os.path.isfile(nrec_p):
                nrec_ie = "Y" if "indexEntry" in json.load(open(nrec_p)) else "N"
            if os.path.isfile(npar_p):
                npar_ie = "Y" if "indexEntry" in json.load(open(npar_p)) else "N"
            nv_parts.append(f"v{nv}(rec={nrec_ie} par={npar_ie})")
        norm_info = " ".join(nv_parts)

    print(f"{sid}  difcal: {' '.join(version_info)}")
    print(f"{'':18s}  normcal: {norm_info}")
