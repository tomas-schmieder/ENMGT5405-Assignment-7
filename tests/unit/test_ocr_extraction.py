"""Offline image extraction reads the *pixels* of W-2 / 1099 images.

The OCR path never sees fixture metadata: these tests pass only the image
bytes. Values are compared with the amounts printed on the fixtures.
"""

from pathlib import Path

import pytest

from src.agents.document_extraction import build_record
from src.tools.ocr_reader import extract

FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures"


def read(case, name, doc_type):
    return extract((FIX / case / name).read_bytes(), doc_type)


def boxes(ex):
    return {f.box: f.text for f in ex.fields if f.text}


def test_w2_image_eval_case_1():
    ex = read("eval_case_1", "w2_maple_grove.png", "W-2")
    assert ex.form_type_seen == "W-2" and ex.tax_year == "2025" and ex.recipient_ssn == "900-55-1234"
    assert boxes(ex)["1"] == "46,850.00" and boxes(ex)["2"] == "3,980.00"


def test_w2_image_unseen_with_cents():
    ex = read("grader_style_unseen", "w2_seneca_transit.png", "W-2")
    assert boxes(ex)["1"] == "61,320.75" and boxes(ex)["2"] == "6,875.40"
    rec = build_record({"doc_id": "d", "doc_type": "W-2", "revision": 0}, ex, "offline", None, "now")
    assert rec["fields"]["1"]["value"] == "61320.75" and rec["issues"] == []


def test_1099r_checkboxes_and_code():
    ira = read("case_single_retiree_mixed", "r_ira_lakeside.png", "1099-R")
    pension = read("case_single_retiree_mixed", "r_pension_teachers.png", "1099-R")
    twob = read("stop_1099r_2b", "r_novak_2b.png", "1099-R")
    assert "IRA/SEP/SIMPLE" in ira.checkboxes and ira.distribution_code == "7"
    assert pension.checkboxes == []
    assert "Taxable amount not determined" in twob.checkboxes


def test_ssa_and_interest():
    ssa = read("eval_case_2", "ssa1099_benson.png", "SSA-1099")
    assert boxes(ssa)["5"] == "21,600.00"
    intr = read("case_single_retiree_mixed", "int_first_ithaca.png", "1099-INT")
    assert boxes(intr) == {"1": "1,250.00", "8": "300.00"}


def test_non_test_ssn_flagged_without_keeping_digits():
    ex = read("stop_real_ssn_w2", "w2_real_looking_ssn.png", "W-2")
    rec = build_record({"doc_id": "d", "doc_type": "W-2", "revision": 0}, ex, "offline", None, "now")
    assert any(i["code"] == "non_test_ssn" for i in rec["issues"])
    assert rec["recipient_ssn"]["last4"] is None and "6789" not in str(rec)


@pytest.mark.parametrize("doc_type", ["W-2"])
def test_wrong_year_is_an_issue(doc_type):
    from src.contracts import DocumentExtraction, ExtractedField

    ex = DocumentExtraction(form_type_seen="W-2", tax_year="2024", recipient_name="x", recipient_ssn="900-11-2222",
                            payer_name="E", fields=[ExtractedField(box="1", text="10.00", readable=True)],
                            checkboxes=[], distribution_code=None, notes="")
    rec = build_record({"doc_id": "d", "doc_type": doc_type, "revision": 0}, ex, "offline", None, "now")
    assert any(i["code"] == "wrong_year" for i in rec["issues"])
