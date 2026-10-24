"""Deterministic tax tools checked against independent sources.

* every row of the printed 2025 IRS Tax Table (parsed from the PDF)
* the Tax Computation Worksheet's printed amounts (independent oracle)
* a closed-form Social Security oracle on a grid of inputs
* boundary values for every rule the assignment calls out
"""

from decimal import Decimal as D

import pytest

from src.tools import tax_calculations as tc
from tests.oracles.independent_calc import ss_taxable, tcw_tax
from tests.oracles.irs_tax_table import load_tax_table


def test_tax_table_matches_every_printed_row():
    rows = load_tax_table()
    assert len(rows) > 2000
    mismatches = []
    for lo, (hi, taxes) in rows.items():
        for status, expected in taxes.items():
            for ti in {lo, hi - 1}:
                got, _ = tc.tax_on_amount(str(ti), status)
                if int(got) != expected:
                    mismatches.append((lo, status, ti, int(got), expected))
    assert mismatches == []


def test_qss_uses_joint_column():
    rows = load_tax_table()
    for lo, (hi, taxes) in list(rows.items())[::97]:
        got, _ = tc.tax_on_amount(str(lo), "qss")
        assert int(got) == taxes["mfj"]


@pytest.mark.parametrize("status", ["single", "mfj", "mfs", "hoh", "qss"])
@pytest.mark.parametrize("ti", [100000, 103350, 103351, 152380, 197300, 206700, 250500, 250525, 375800, 501050,
                                626350, 751600, 900000])
def test_tax_computation_worksheet(status, ti):
    got, _ = tc.tax_on_amount(str(ti), status)
    assert int(got) == tcw_tax(status, ti)


@pytest.mark.parametrize("status,boxes,expected", [
    ("single", 0, 15750), ("single", 1, 17750), ("single", 2, 19750),
    ("mfj", 1, 33100), ("mfj", 2, 34700), ("mfj", 3, 36300), ("mfj", 4, 37900),
    ("qss", 1, 33100), ("qss", 2, 34700), ("hoh", 1, 25625), ("hoh", 2, 27625),
    ("mfs", 1, 17350), ("mfs", 2, 18950), ("mfs", 3, 20550), ("mfs", 4, 22150),
])
def test_standard_deduction_chart(status, boxes, expected):
    flags = [False, False, False, False]
    order = [0, 1, 2, 3] if status in {"mfj", "mfs"} else [0, 1]
    for i in order[:boxes]:
        flags[i] = True
    res = tc.standard_deduction(status, flags[0], flags[1], flags[2], flags[3], False, False, False)
    assert res["outputs"]["12e"] == str(expected)
    assert res["outputs"]["12d_box_count"] == str(boxes)


@pytest.mark.parametrize("dependent,itemizes,dual", [(True, False, False), (False, True, False), (False, False, True)])
def test_standard_deduction_exceptions_produce_no_amount(dependent, itemizes, dual):
    res = tc.standard_deduction("single", True, False, False, False, dependent, itemizes, dual)
    assert res["outputs"] == {}
    assert res["exception"]


def test_spouse_boxes_rejected_for_single():
    with pytest.raises(tc.ToolInputError):
        tc.standard_deduction("single", True, False, True, False, False, False, False)


@pytest.mark.parametrize("status,magi,tp,sp,expected", [
    ("single", 75000, True, False, 6000),
    ("single", 75001, True, False, 6000),     # 6,000 - 0.06 -> 5,999.94 rounds to 6,000
    ("single", 75009, True, False, 5999),     # 6,000 - 0.54 = 5,999.46
    ("single", 100000, True, False, 4500),
    ("single", 175000, True, False, 0),
    ("single", 300000, True, False, 0),
    ("mfj", 150000, True, True, 12000),
    ("mfj", 195250, True, True, 6570),
    ("mfj", 250000, True, True, 0),
    ("mfj", 61400, True, False, 6000),        # only one spouse qualifies
    ("mfs", 30000, True, False, 0),           # married filing separately cannot claim
    ("hoh", 80000, True, False, 5700),
    ("single", 50000, False, False, 0),
])
def test_enhanced_senior_deduction(status, magi, tp, sp, expected):
    res = tc.enhanced_senior_deduction(status, str(magi), tp, sp)
    assert res["outputs"]["13b"] == str(expected)


def test_enhanced_deduction_is_separate_from_additional_standard_deduction():
    sd = tc.standard_deduction("single", True, False, False, False, False, False, False)
    esd = tc.enhanced_senior_deduction("single", "40000", True, False)
    assert sd["outputs"]["12e"] == "17750" and esd["outputs"]["13b"] == "6000"


@pytest.mark.parametrize("status", ["single", "mfj", "hoh", "qss", "mfs"])
@pytest.mark.parametrize("benefits,other", [(0, 0), (20000, 5000), (21600, 25200), (21600, 45200), (24000, 32650),
                                            (30000, 20000), (40000, 60000), (18000, 90000), (35000, 1000)])
def test_social_security_matches_independent_oracle(status, benefits, other):
    apart = status == "mfs" and benefits % 2 == 0
    res = tc.taxable_social_security(status, f"{benefits}.00", str(other), "0", "0", "0", "0", "0", "0", "0",
                                     "0", "0", mfs_lived_apart_all_year=apart)
    expected = ss_taxable(status, D(benefits), D(other), D(0), D(0), apart)
    assert res["outputs"]["6b"] == str(int(expected.quantize(D(1), rounding="ROUND_HALF_UP")))
    assert D(res["outputs"]["6b"]) <= D(res["outputs"]["6a"]) * D("0.85") + 1


def test_social_security_counts_tax_exempt_interest_and_adjustments():
    base = tc.taxable_social_security("single", "24000", "0", "1250", "3400", "10000", "18000", "0", "0", "0", "0", "0")
    with_exempt = tc.taxable_social_security("single", "24000", "0", "1250", "3400", "10000", "18000", "0", "0", "300",
                                             "0", "0")
    with_adj = tc.taxable_social_security("single", "24000", "0", "1250", "3400", "10000", "18000", "0", "0", "300",
                                          "2000", "500")
    assert int(with_exempt["outputs"]["6b"]) > int(base["outputs"]["6b"])
    assert with_exempt["outputs"]["6b"] == "13808"
    assert int(with_adj["outputs"]["6b"]) < int(with_exempt["outputs"]["6b"])
    assert with_adj["worksheet"]["6"] == "1500.00"


def test_social_security_rejects_negative_benefits():
    with pytest.raises(tc.ToolInputError):
        tc.taxable_social_security("single", "-50.00", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0")


def test_qualified_dividends_worksheet_hand_worked_case():
    res = tc.income_tax("single", "22708", "2900")
    assert res["method"] == "qualified_dividends_worksheet"
    assert res["outputs"]["16"] == "2141"
    plain = tc.income_tax("single", "22708", "0")
    assert plain["outputs"]["16"] == "2489"   # treating dividends as ordinary would overstate tax


def test_qualified_dividends_never_increase_tax():
    for ti in [5000, 40000, 60000, 120000, 700000]:
        for status in ["single", "mfj", "hoh", "mfs"]:
            with_qd = int(tc.income_tax(status, str(ti), str(min(ti, 8000)))["outputs"]["16"])
            without = int(tc.income_tax(status, str(ti), "0")["outputs"]["16"])
            assert with_qd <= without


def test_aggregate_rounds_total_only_and_rejects_duplicates():
    res = tc.aggregate_amounts("1z", [{"source_id": "a", "amount": "100.40"}, {"source_id": "b", "amount": "100.40"}])
    assert res["outputs"]["1z"] == "201"   # 200.80 -> 201 (not 100 + 100)
    half = tc.aggregate_amounts("x", [{"source_id": "a", "amount": "0.50"}])
    assert half["outputs"]["x"] == "1"
    with pytest.raises(tc.ToolInputError):
        tc.aggregate_amounts("1z", [{"source_id": "a", "amount": "1"}, {"source_id": "a", "amount": "1"}])


def test_ira_with_qcd():
    res = tc.ira_distributions([{"source_id": "d:1", "amount": "12000.00"}],
                               [{"source_id": "d:2a", "amount": "12000.00"}], "2000")
    assert res["outputs"] == {"4a": "12000", "4b": "10000", "qcd": "yes"}
    with pytest.raises(tc.ToolInputError):
        tc.ira_distributions([{"source_id": "d:1", "amount": "100"}], [], "500")


def test_compare_amounts_tolerance():
    assert tc.compare_amounts("w", "45200.00", "54000")["outputs"]["material"] is True
    assert tc.compare_amounts("w", "46850.00", "46000")["outputs"]["material"] is False
    assert tc.compare_amounts("w", "5000.00", "5900")["outputs"]["material"] is False  # within $1,000
    assert tc.compare_amounts("w", "50000.00", "54900")["outputs"]["material"] is False  # within 10%


def test_verify_return_detects_contradictions():
    good = {"1z": "100", "2b": "0", "3b": "0", "4b": "0", "5b": "0", "6a": "0", "6b": "0", "7a": "0", "8": "0",
            "9": "100", "10": "0", "11a": "100", "11b": "100", "12e": "17750", "13a": "0", "13b": "6000",
            "14": "23750", "15": "0", "16": "0", "17": "0", "18": "0", "21": "0", "22": "0", "23": "0", "24": "0",
            "25a": "0", "25b": "0", "25c": "0", "25d": "0", "26": "0", "32": "0", "33": "0", "34": "0", "37": "0",
            "3a": "0", "4a": "0", "5a": "0"}
    assert tc.verify_return(good, "single", 1)["outputs"]["passed"] is True
    bad = dict(good, **{"6a": "1000", "6b": "1500"})
    checks = {f["check"] for f in tc.verify_return(bad, "single", 1)["outputs"]["findings"]}
    assert {"line6b_le_6a", "line6b_cap", "line9_sum"} <= checks
    bad2 = dict(good, **{"3a": "500", "3b": "100"})
    assert "line3a_subset" in {f["check"] for f in tc.verify_return(bad2, "single", 1)["outputs"]["findings"]}
    bad3 = dict(good, **{"12e": "17000"})
    assert "line12e_chart" in {f["check"] for f in tc.verify_return(bad3, "single", 1)["outputs"]["findings"]}


def test_inputs_are_validated_not_defaulted():
    with pytest.raises(tc.ToolInputError):
        tc.total_income("100.50", "0", "0", "0", "0", "0", "0", "0")  # line values must be whole dollars
    with pytest.raises(tc.ToolInputError):
        tc.income_tax("married", "1000", "0")
    with pytest.raises(tc.ToolInputError):
        tc.aggregate_amounts("x", [{"source_id": "a", "amount": "about 5k"}])
