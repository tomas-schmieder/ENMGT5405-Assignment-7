"""Field map: SilverFile line ids -> field names in the official 2025 PDFs.

Derived by inspecting ``2025_Form_1040-SR.pdf`` and
``2025_Schedule_1-A_Form_1040.pdf`` (widget names, positions and the printed
labels next to them); see docs/IMPLEMENTATION_NOTES.md. Short names are the
last component of the fully qualified field name.
"""

from __future__ import annotations

F1040SR_TEXT = {
    # page 1 - identity
    "tp_first": "f1_14[0]", "tp_last": "f1_15[0]", "tp_ssn": "f1_16[0]",
    "sp_first": "f1_17[0]", "sp_last": "f1_18[0]", "sp_ssn": "f1_19[0]",
    "mfs_spouse_name": "f1_28[0]",
    # dependents 1-4: first, last, ssn, relationship
    "dep1_first": "f1_31[0]", "dep2_first": "f1_32[0]", "dep3_first": "f1_33[0]", "dep4_first": "f1_34[0]",
    "dep1_last": "f1_35[0]", "dep2_last": "f1_36[0]", "dep3_last": "f1_37[0]", "dep4_last": "f1_38[0]",
    "dep1_ssn": "f1_39[0]", "dep2_ssn": "f1_40[0]", "dep3_ssn": "f1_41[0]", "dep4_ssn": "f1_42[0]",
    "dep1_rel": "f1_43[0]", "dep2_rel": "f1_44[0]", "dep3_rel": "f1_45[0]", "dep4_rel": "f1_46[0]",
    # income
    "1a": "f1_47[0]", "1z": "f1_57[0]",
    "2a": "f2_01[0]", "2b": "f2_02[0]", "3a": "f2_03[0]", "3b": "f2_04[0]",
    "4a": "f2_05[0]", "4b": "f2_06[0]", "5a": "f2_08[0]", "5b": "f2_09[0]",
    "6a": "f2_11[0]", "6b": "f2_12[0]", "7a": "f2_13[0]", "8": "f2_15[0]", "9": "f2_16[0]",
    "10": "f2_17[0]", "11a": "f2_18[0]", "11b": "f2_19[0]",
    "12e": "f2_20[0]", "13a": "f2_21[0]", "13b": "f2_22[0]", "14": "f2_23[0]", "15": "f2_24[0]",
    "16": "f2_26[0]", "17": "f2_27[0]", "18": "f2_28[0]", "19": "f2_29[0]", "20": "f2_30[0]",
    "21": "f2_31[0]", "22": "f2_32[0]", "23": "f2_33[0]", "24": "f2_34[0]",
    # payments
    "25a": "f3_01[0]", "25b": "f3_02[0]", "25c": "f3_03[0]", "25d": "f3_04[0]", "26": "f3_05[0]",
    "31": "f3_11[0]", "32": "f3_12[0]", "33": "f3_13[0]", "34": "f3_14[0]", "35a": "f3_15[0]", "37": "f3_19[0]",
    # page 4 chart
    "chart_box_count": "f4_01[0]",
}

F1040SR_CHECKBOX = {
    "4c_qcd": "c2_4[0]",
    "12d_tp_born_before": "c2_17[0]", "12d_tp_blind": "c2_18[0]",
    "12d_sp_born_before": "c2_19[0]", "12d_sp_blind": "c2_20[0]",
    "6d_mfs_lived_apart": "c2_10[0]",
}

# Filing status radio group "c1_8": the five widgets identified by position
# (x0, y0) in PyMuPDF page coordinates (origin top-left) on page 1.
FILING_STATUS_WIDGETS = {
    "single": (95, 236), "mfj": (95, 248), "mfs": (95, 260), "hoh": (361, 236), "qss": (361, 248),
}
DIGITAL_ASSETS_NO = ("c1_10", (550, 372))  # second widget of c1_10 = "No"

SCH1A_TEXT = {
    "name": "f1_01[0]", "ssn": "f1_02[0]",
    "sch1a_1": "f1_03[0]", "sch1a_2e": "f1_08[0]", "sch1a_3": "f1_09[0]",
    "sch1a_31": "f2_15[0]", "sch1a_32": "f2_16[0]", "sch1a_33": "f2_17[0]", "sch1a_34": "f2_18[0]",
    "sch1a_35": "f2_19[0]", "sch1a_36a": "f2_20[0]", "sch1a_36b": "f2_21[0]", "sch1a_37": "f2_22[0]",
    "sch1a_38": "f2_23[0]",
}

DRAFT_BANNER = "DRAFT - NOT FILED - FOR KUSHIM HUMAN REVIEW ONLY - FICTIONAL CLASSROOM SAMPLE"
