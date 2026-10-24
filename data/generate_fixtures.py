"""Generate fictional 2025 test cases and document images.

Every document is made by filling the official blank IRS PDF in
``data/reference_tax_forms/forms`` (W-2 Copy B, 1099-INT/DIV/R Copy B) and
rendering it to PNG. There is no blank SSA-1099 in the pack, so an SSA-1099
style statement is drawn with the same box numbers as the real form.

All names, SSNs (900-series test numbers), employers and amounts are
fictional. Each image carries a "FICTIONAL CLASSROOM SAMPLE - DO NOT FILE"
banner. Expected results are NOT produced here: they are hand-worked in
``evals/expected_results`` and checked by an independent oracle in tests.

Run:  python data/generate_fixtures.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORMS = ROOT / "data" / "reference_tax_forms" / "forms"
OUT = ROOT / "data" / "fixtures"
DEMO = ROOT / "demo"
BANNER = "FICTIONAL CLASSROOM SAMPLE - DO NOT FILE"


def _money(v: str | None) -> str:
    if v in (None, ""):
        return ""
    whole, _, cents = f"{float(v):.2f}".partition(".")
    return f"{int(whole):,}.{cents}"


def _fill_official(pdf_name: str, page_index: int, values: dict[str, str], checks: set[str],
                   clip_height: float) -> bytes:
    import pymupdf

    src = pymupdf.open(str(FORMS / pdf_name))
    doc = pymupdf.open()
    doc.insert_pdf(src, from_page=page_index, to_page=page_index)
    page = doc[0]
    for w in page.widgets():
        name = w.field_name.split(".")[-1]
        if name in values:
            w.field_value = values[name]
            w.update()
        elif name in checks:
            w.field_value = True
            w.update()
    page.insert_text((180, 14), BANNER, fontsize=9, fontname="helv", color=(0.75, 0, 0))
    pix = page.get_pixmap(dpi=200, clip=pymupdf.Rect(0, 0, 612, clip_height))
    return pix.tobytes("png")


def build_w2(d: dict) -> bytes:
    values = {
        "f2_01[0]": d["ssn"], "f2_02[0]": d.get("ein", "12-3456789"),
        "f2_03[0]": d["employer"] + "\n" + d.get("employer_address", "100 Main Street\nIthaca, NY 14850"),
        "f2_05[0]": d["first"], "f2_06[0]": d["last"],
        "f2_08[0]": d.get("address", "45 Elm Road\nIthaca, NY 14850"),
        "f2_09[0]": _money(d["box1"]), "f2_10[0]": _money(d["box2"]),
        "f2_11[0]": _money(d.get("box3", d["box1"])), "f2_12[0]": _money(d.get("box4")),
        "f2_13[0]": _money(d.get("box5", d["box1"])), "f2_14[0]": _money(d.get("box6")),
    }
    checks = {"c2_3[0]"} if d.get("retirement_plan") else set()
    return _fill_official("2025_Form_W-2.pdf", 3, values, checks, 400)


def build_1099int(d: dict) -> bytes:
    values = {
        "CalendarYear2_1[0]": d.get("year2", "25"),
        "f2_1[0]": d["payer"] + "\n" + d.get("payer_address", "200 State Street\nIthaca, NY 14850"),
        "f2_2[0]": d.get("payer_tin", "16-1122334"), "f2_3[0]": d["ssn"],
        "f2_4[0]": d["name"], "f2_9[0]": _money(d.get("box1")), "f2_11[0]": _money(d.get("box3")),
        "f2_12[0]": _money(d.get("box4")), "f2_16[0]": _money(d.get("box8")),
    }
    return _fill_official("Form_1099-INT_Rev_Jan_2024.pdf", 3, values, set(), 380)


def build_1099div(d: dict) -> bytes:
    values = {
        "f2_1[0]": d.get("year2", "25"),
        "f2_2[0]": d["payer"] + "\n" + d.get("payer_address", "1 Fund Plaza\nBoston, MA 02110"),
        "f2_3[0]": d.get("payer_tin", "04-5566778"), "f2_4[0]": d["ssn"], "f2_5[0]": d["name"],
        "f2_9[0]": _money(d.get("box1a")), "f2_10[0]": _money(d.get("box1b")),
        "f2_11[0]": _money(d.get("box2a")), "f2_18[0]": _money(d.get("box4")),
        "f2_25[0]": _money(d.get("box12")),
    }
    return _fill_official("Form_1099-DIV_Rev_Jan_2024.pdf", 3, values, set(), 380)


def build_1099r(d: dict) -> bytes:
    values = {
        "f2_01[0]": d["payer"] + "\n" + d.get("payer_address", "500 Pension Way\nAlbany, NY 12207"),
        "f2_02[0]": d.get("payer_tin", "22-3344556"), "f2_03[0]": d["ssn"], "f2_04[0]": d["name"],
        "f2_08[0]": _money(d.get("box1")), "f2_09[0]": _money(d.get("box2a")),
        "f2_11[0]": _money(d.get("box4")), "f2_14[0]": d.get("code", "7"),
    }
    checks = set()
    if d.get("ira"):
        checks.add("c2_4[0]")
    if d.get("box2b"):
        checks.add("c2_2[0]")
    return _fill_official("2025_Form_1099-R.pdf", 3, values, checks, 380)


def build_ssa1099(d: dict) -> bytes:
    """SSA-1099 style statement (same box numbers as the real form)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=330)
    blue = (0.05, 0.05, 0.55)
    page.insert_text((180, 14), BANNER, fontsize=9, fontname="helv", color=(0.75, 0, 0))
    page.draw_rect(pymupdf.Rect(30, 24, 582, 318), width=1)
    page.insert_text((40, 44), "FORM SSA-1099 - SOCIAL SECURITY BENEFIT STATEMENT", fontsize=12, fontname="hebo")
    page.insert_text((470, 44), "2025", fontsize=20, fontname="hebo")
    page.insert_text((40, 60), "PART OF YOUR SOCIAL SECURITY BENEFITS SHOWN IN BOX 5 MAY BE TAXABLE INCOME.",
                     fontsize=7, fontname="helv")
    rows = [
        (70, "Box 1. Name", d["name"], 30, 340),
        (70, "Box 2. Beneficiary's Social Security Number", d["ssn"], 340, 582),
        (130, "Box 3. Benefits Paid in 2025", _money(d["box3"]), 30, 340),
        (130, "Box 4. Benefits Repaid to SSA in 2025", _money(d.get("box4", "0")), 340, 582),
        (190, "Box 5. Net Benefits for 2025 (Box 3 minus Box 4)", _money(d["box5"]), 30, 340),
        (190, "Box 6. Voluntary Federal Income Tax Withheld", _money(d.get("box6", "0")), 340, 582),
        (250, "Box 7. Address", d.get("address", "45 Elm Road, Ithaca, NY 14850"), 30, 340),
        (250, "Box 8. Claim Number", d.get("claim", "FICTIONAL-CLAIM-01"), 340, 582),
    ]
    for top, label, value, x0, x1 in rows:
        page.draw_rect(pymupdf.Rect(x0, top, x1, top + 60), width=0.6)
        page.insert_text((x0 + 6, top + 14), label, fontsize=8, fontname="helv")
        page.insert_text((x0 + 12, top + 42), value, fontsize=13, fontname="helv", color=blue)
    pix = page.get_pixmap(dpi=200)
    return pix.tobytes("png")


BUILDERS = {"W-2": build_w2, "1099-INT": build_1099int, "1099-DIV": build_1099div, "1099-R": build_1099r,
            "SSA-1099": build_ssa1099}

# ---------------------------------------------------------------------------
# cases: intake answers by question id + documents. No expected values here.
# ---------------------------------------------------------------------------

BASE_ANSWERS = {
    "answerer": "I'm answering for myself", "return_type_ok": "yes", "spouse_died_2025": "no", "tp_blind": "no",
    "tp_claimable": "no", "us_resident": "yes", "dependents_any": "no", "has_w2": "0", "has_1099int": "0",
    "has_1099div": "0", "has_1099r": "0", "has_ssa1099": "0", "other_income": "no", "itemize": "no",
    "est_any": "no", "sched_any": "no", "refund_method": "check", "upload_docs": "done", "confirm_summary": "yes",
    "dep_more": "no",
}


def case(**kw) -> dict:
    answers = dict(BASE_ANSWERS)
    answers.update(kw.pop("answers"))
    return {"answers": answers, **kw}


CASES: dict[str, dict] = {
    "eval_case_1": case(
        purpose="Clean minimal run: single filer, one W-2 image, nonzero tax, refund.",
        answers={"tp_first_name": "Eleanor", "tp_last_name": "Whitfield", "tp_dob": "March 14, 1957",
                 "filing_status": "Single", "tp_ssn": "900-55-1234", "has_w2": "1", "stated_wages": "about 46,000"},
        documents=[{"type": "W-2", "file": "w2_maple_grove.png",
                    "data": {"ssn": "900-55-1234", "first": "Eleanor", "last": "Whitfield",
                             "employer": "Maple Grove Public Library", "ein": "12-3456789",
                             "box1": "46850.00", "box2": "3980.00", "box4": "2904.70", "box6": "679.33"}}],
    ),
    "eval_case_2": case(
        purpose="HITL run: taxpayer's stated wages conflict with the W-2; resolved by a reviewer.",
        answers={"tp_first_name": "Harold", "tp_last_name": "Benson", "tp_dob": "November 2, 1958",
                 "filing_status": "Married filing jointly", "tp_ssn": "900-71-4402", "sp_first_name": "Margaret",
                 "sp_last_name": "Benson", "sp_dob": "April 20, 1962", "sp_ssn": "900-71-4403", "sp_blind": "no",
                 "sp_claimable": "no", "has_w2": "1", "stated_wages": "about 54,000", "has_ssa1099": "1",
                 "est_any": "yes", "est_amount": "400", "refund_method": "direct deposit",
                 "refund_account_own": "yes"},
        followup_answers={"conflict-wages": "My number is right"},
        reviewer_actions=[{"reason": "user_document_conflict", "action": "confirm_document_value",
                           "reviewer": "Kushim reviewer (demo)",
                           "rationale": "Spoke with the taxpayer; the W-2 amount is correct.",
                           "evidence": "Phone call with Harold Benson: he confirmed W-2 box 1 shows $45,200.00. "
                                       "His estimate of $54,000 included his Social Security."}],
        documents=[{"type": "W-2", "file": "w2_fingerlakes_hardware.png",
                    "data": {"ssn": "900-71-4402", "first": "Harold", "last": "Benson",
                             "employer": "Fingerlakes Hardware Co.", "ein": "16-2468101",
                             "box1": "45200.00", "box2": "3100.00", "box4": "2802.40", "box6": "655.40"}},
                   {"type": "SSA-1099", "file": "ssa1099_benson.png",
                    "data": {"name": "HAROLD BENSON", "ssn": "900-71-4402", "box3": "21600.00", "box4": "0.00",
                             "box5": "21600.00", "box6": "0.00"}}],
    ),
    "case_single_retiree_mixed": case(
        purpose="Coverage: SS + 1099-INT (incl. tax-exempt) + 1099-DIV qualified + IRA with QCD + pension + estimates.",
        answers={"tp_first_name": "Dorothy", "tp_last_name": "Kim", "tp_dob": "June 30, 1953", "filing_status": "single",
                 "tp_ssn": "900-21-7788", "has_1099int": "1", "has_1099div": "1", "has_1099r": "2", "qcd_any": "yes",
                 "qcd_amount": "2,000", "has_ssa1099": "1", "est_any": "yes", "est_amount": "1,000"},
        documents=[
            {"type": "1099-INT", "file": "int_first_ithaca.png",
             "data": {"payer": "First Ithaca Savings Bank", "ssn": "900-21-7788", "name": "DOROTHY KIM",
                      "box1": "1250.00", "box8": "300.00"}},
            {"type": "1099-DIV", "file": "div_cayuga_fund.png",
             "data": {"payer": "Cayuga Index Fund", "ssn": "900-21-7788", "name": "DOROTHY KIM",
                      "box1a": "3400.00", "box1b": "2900.00"}},
            {"type": "1099-R", "file": "r_ira_lakeside.png",
             "data": {"payer": "Lakeside IRA Custodian", "ssn": "900-21-7788", "name": "DOROTHY KIM",
                      "box1": "12000.00", "box2a": "12000.00", "box4": "1200.00", "code": "7", "ira": True}},
            {"type": "1099-R", "file": "r_pension_teachers.png",
             "data": {"payer": "NY Teachers Pension Fund", "ssn": "900-21-7788", "name": "DOROTHY KIM",
                      "box1": "18000.00", "box2a": "18000.00", "box4": "1800.00", "code": "7"}},
            {"type": "SSA-1099", "file": "ssa_kim.png",
             "data": {"name": "DOROTHY KIM", "ssn": "900-21-7788", "box3": "24000.00", "box5": "24000.00",
                      "box6": "1200.00"}}],
    ),
    "case_mfj_high_income": case(
        purpose="Coverage: MFJ, two W-2s (parallel extraction), 3 boxes, senior deduction phaseout, Tax Computation Worksheet.",
        answers={"tp_first_name": "Robert", "tp_last_name": "Ostrowski", "tp_dob": "February 10, 1955",
                 "filing_status": "mfj", "tp_ssn": "900-33-1001", "sp_first_name": "Linda", "sp_last_name": "Ostrowski",
                 "sp_dob": "September 5, 1958", "sp_ssn": "900-33-1002", "sp_blind": "yes", "sp_claimable": "no",
                 "has_w2": "2", "stated_wages": "about 192,000", "has_1099int": "1"},
        documents=[
            {"type": "W-2", "file": "w2_robert.png",
             "data": {"ssn": "900-33-1001", "first": "Robert", "last": "Ostrowski", "employer": "Cayuga Medical Group",
                      "box1": "168000.00", "box2": "26000.00", "box3": "168000.00", "box4": "10416.00"}},
            {"type": "W-2", "file": "w2_linda.png",
             "data": {"ssn": "900-33-1002", "first": "Linda", "last": "Ostrowski", "employer": "Ithaca City Schools",
                      "box1": "24500.00", "box2": "2400.00", "box4": "1519.00"}},
            {"type": "1099-INT", "file": "int_ostrowski.png",
             "data": {"payer": "Tompkins Community Bank", "ssn": "900-33-1001", "name": "ROBERT OSTROWSKI",
                      "box1": "2750.00"}}],
    ),
    "case_hoh_dependent": case(
        purpose="Coverage: head of household with a dependent grandchild.",
        answers={"tp_first_name": "Gloria", "tp_last_name": "Ramos", "tp_dob": "July 21, 1959",
                 "filing_status": "head of household", "hoh_person": "yes", "tp_ssn": "900-44-2020",
                 "dependents_any": "yes", "dep_first": "Mateo", "dep_last": "Ramos", "dep_ssn": "900-44-2021",
                 "dep_relationship": "grandson", "line19": "0", "has_w2": "1", "stated_wages": "38,000"},
        documents=[{"type": "W-2", "file": "w2_ramos.png",
                    "data": {"ssn": "900-44-2020", "first": "Gloria", "last": "Ramos", "employer": "Hilltop Bakery LLC",
                             "box1": "38400.00", "box2": "2100.00"}}],
    ),
    "case_mfs_lived_apart": case(
        purpose="Coverage: married filing separately, lived apart (SS worksheet), no senior deduction for MFS.",
        answers={"tp_first_name": "Walter", "tp_last_name": "Price", "tp_dob": "January 15, 1956",
                 "filing_status": "married filing separately", "tp_ssn": "900-62-3300", "sp_first_name": "Joan",
                 "sp_last_name": "Price", "sp_ssn": "900-62-3301", "mfs_itemizes": "no", "mfs_apart": "yes",
                 "mfs_spouse_no_income": "no", "has_1099r": "1", "qcd_any": "no", "has_ssa1099": "1"},
        documents=[
            {"type": "1099-R", "file": "r_price_pension.png",
             "data": {"payer": "Empire Rail Pension Plan", "ssn": "900-62-3300", "name": "WALTER PRICE",
                      "box1": "20000.00", "box2a": "20000.00", "box4": "2000.00", "code": "7"}},
            {"type": "SSA-1099", "file": "ssa_price.png",
             "data": {"name": "WALTER PRICE", "ssn": "900-62-3300", "box3": "30000.00", "box5": "30000.00"}}],
    ),
    "case_qss": case(
        purpose="Coverage: qualifying surviving spouse (spouse died 2024) with dependent son.",
        answers={"tp_first_name": "Beatrice", "tp_last_name": "Hall", "tp_dob": "December 1, 1958",
                 "filing_status": "qualifying surviving spouse", "qss_death_year": "2024", "qss_child": "yes",
                 "tp_ssn": "900-81-5151", "dependents_any": "yes", "dep_first": "Owen", "dep_last": "Hall",
                 "dep_ssn": "900-81-5152", "dep_relationship": "son", "line19": "0", "has_1099r": "1",
                 "qcd_any": "no"},
        documents=[{"type": "1099-R", "file": "r_hall_pension.png",
                    "data": {"payer": "Finger Lakes Utility Pension", "ssn": "900-81-5151", "name": "BEATRICE HALL",
                             "box1": "52000.00", "box2a": "52000.00", "box4": "5200.00", "code": "7"}}],
    ),
    "grader_style_unseen": case(
        purpose="Grader-style unseen input: a different W-2 (cents, age-65 boundary DOB) through the same path.",
        answers={"tp_first_name": "Samuel", "tp_last_name": "Ortega", "tp_dob": "12/31/1960", "filing_status": "single",
                 "tp_ssn": "900-90-6060", "has_w2": "1", "stated_wages": "61,000"},
        documents=[{"type": "W-2", "file": "w2_seneca_transit.png",
                    "data": {"ssn": "900-90-6060", "first": "Samuel", "last": "Ortega",
                             "employer": "Seneca Valley Transit Authority", "ein": "16-9081726",
                             "box1": "61320.75", "box2": "6875.40", "box4": "3801.89", "box6": "889.15",
                             "retirement_plan": True}}],
    ),
    # --- mandatory stop cases ---
    "stop_1099r_2b": case(
        purpose="Stop: 1099-R with box 2b 'taxable amount not determined' checked.",
        answers={"tp_first_name": "Irene", "tp_last_name": "Novak", "tp_dob": "May 9, 1950", "filing_status": "single",
                 "tp_ssn": "900-12-0001", "has_1099r": "1", "qcd_any": "no"},
        documents=[{"type": "1099-R", "file": "r_novak_2b.png",
                    "data": {"payer": "Old Mill Annuity Co.", "ssn": "900-12-0001", "name": "IRENE NOVAK",
                             "box1": "15000.00", "box2a": None, "box2b": True, "box4": "1500.00", "code": "7"}}],
        expect_escalation="form_1099r_2b",
    ),
    "stop_advice": case(
        purpose="Stop: taxpayer asks for tax advice.",
        answers={"tp_first_name": "Frank", "tp_last_name": "Lee", "tp_dob": "1952-02-02",
                 "filing_status": "Should I convert my IRA to a Roth first?", "tp_ssn": "900-12-0002"},
        documents=[], expect_escalation="advice_request",
    ),
    "stop_spouse_died": case(
        purpose="Stop: spouse died during 2025 (filing-status ambiguity).",
        answers={"tp_first_name": "Rose", "tp_last_name": "Marino", "tp_dob": "1951-08-08", "filing_status": "mfj",
                 "spouse_died_2025": "yes", "tp_ssn": "900-12-0003"},
        documents=[], expect_escalation="filing_status_ambiguity",
    ),
    "stop_exploitation": case(
        purpose="Stop: refund routed to someone else's account.",
        answers={"tp_first_name": "Agnes", "tp_last_name": "Byrne", "tp_dob": "1944-03-03", "filing_status": "single",
                 "tp_ssn": "900-12-0004", "refund_method": "direct deposit",
                 "refund_account_own": "No, it goes to my nephew's account, he handles my money now"},
        documents=[], expect_escalation="exploitation_concern",
    ),
    "stop_crypto": case(
        purpose="Stop: out-of-scope other income (digital assets).",
        answers={"tp_first_name": "Victor", "tp_last_name": "Hughes", "tp_dob": "1955-05-05", "filing_status": "single",
                 "tp_ssn": "900-12-0005", "other_income": "yes", "other_income_kind": "I sold some bitcoin"},
        documents=[], expect_escalation="out_of_scope",
    ),
    "stop_itemize": case(
        purpose="Stop: wants to itemize deductions.",
        answers={"tp_first_name": "Helen", "tp_last_name": "Ford", "tp_dob": "1949-09-09", "filing_status": "single",
                 "tp_ssn": "900-12-0006", "itemize": "yes"},
        documents=[], expect_escalation="out_of_scope",
    ),
    "stop_too_young": case(
        purpose="Stop: not eligible for Form 1040-SR (born after January 1, 1961).",
        answers={"tp_first_name": "Paul", "tp_last_name": "Young", "tp_dob": "1965-06-06", "filing_status": "single",
                 "tp_ssn": "900-12-0007"},
        documents=[], expect_escalation="out_of_scope",
    ),
    "stop_third_party": case(
        purpose="Stop: third party answering without stated authority.",
        answers={"tp_first_name": "Martha", "tp_last_name": "Quinn", "answerer": "Someone is helping me answer",
                 "helper_authority": "no"},
        documents=[], expect_escalation="exploitation_concern",
    ),
    "stop_capital_gain_dist": case(
        purpose="Stop: 1099-DIV with capital gain distributions (needs line 7a).",
        answers={"tp_first_name": "Leon", "tp_last_name": "Park", "tp_dob": "1950-10-10", "filing_status": "single",
                 "tp_ssn": "900-12-0008", "has_1099div": "1"},
        documents=[{"type": "1099-DIV", "file": "div_park_capgain.png",
                    "data": {"payer": "Seneca Growth Fund", "ssn": "900-12-0008", "name": "LEON PARK",
                             "box1a": "2200.00", "box1b": "1800.00", "box2a": "950.00"}}],
        expect_escalation="out_of_scope",
    ),
    "stop_real_ssn_w2": case(
        purpose="Security: a W-2 showing a non-test SSN is rejected and never stored.",
        answers={"tp_first_name": "Nora", "tp_last_name": "Bell", "tp_dob": "1953-01-01", "filing_status": "single",
                 "tp_ssn": "900-12-0009", "has_w2": "1", "stated_wages": "30,000"},
        documents=[{"type": "W-2", "file": "w2_real_looking_ssn.png",
                    "data": {"ssn": "123-45-6789", "first": "Nora", "last": "Bell", "employer": "Example Employer Inc.",
                             "box1": "30000.00", "box2": "2500.00"}}],
        expect_document_rejection=True,
    ),
    # --- context benchmark: ten distinct documents for one taxpayer ---
    "bench_ten_docs": case(
        purpose="Context-window benchmark (assignment §4.5): ten 2025 documents processed sequentially in one thread.",
        answers={"tp_first_name": "Ruth", "tp_last_name": "Alvarez", "tp_dob": "1954-04-04", "filing_status": "single",
                 "tp_ssn": "900-77-1010", "has_w2": "2", "stated_wages": "31,000", "has_1099int": "3",
                 "has_1099div": "2", "has_1099r": "2", "qcd_any": "no", "has_ssa1099": "1"},
        documents=[
            {"type": "W-2", "file": "b01_w2_library.png",
             "data": {"ssn": "900-77-1010", "first": "Ruth", "last": "Alvarez", "employer": "Ithaca Public Library",
                      "box1": "18200.00", "box2": "1100.00"}},
            {"type": "1099-INT", "file": "b02_int_bank_a.png",
             "data": {"payer": "Lakeview Credit Union", "ssn": "900-77-1010", "name": "RUTH ALVAREZ", "box1": "410.25"}},
            {"type": "1099-DIV", "file": "b03_div_fund_a.png",
             "data": {"payer": "Gorge Dividend Fund", "ssn": "900-77-1010", "name": "RUTH ALVAREZ",
                      "box1a": "1325.00", "box1b": "1100.00"}},
            {"type": "1099-R", "file": "b04_r_ira.png",
             "data": {"payer": "Cascadilla IRA Trust", "ssn": "900-77-1010", "name": "RUTH ALVAREZ",
                      "box1": "6000.00", "box2a": "6000.00", "box4": "600.00", "code": "7", "ira": True}},
            {"type": "W-2", "file": "b05_w2_market.png",
             "data": {"ssn": "900-77-1010", "first": "Ruth", "last": "Alvarez", "employer": "Commons Farmers Market",
                      "box1": "12650.00", "box2": "700.00"}},
            {"type": "1099-INT", "file": "b06_int_bank_b.png",
             "data": {"payer": "Taughannock Savings", "ssn": "900-77-1010", "name": "RUTH ALVAREZ",
                      "box1": "88.40", "box8": "120.00"}},
            {"type": "SSA-1099", "file": "b07_ssa.png",
             "data": {"name": "RUTH ALVAREZ", "ssn": "900-77-1010", "box3": "19800.00", "box5": "19800.00",
                      "box6": "900.00"}},
            {"type": "1099-DIV", "file": "b08_div_fund_b.png",
             "data": {"payer": "Six Mile Creek Income Fund", "ssn": "900-77-1010", "name": "RUTH ALVAREZ",
                      "box1a": "640.00", "box1b": "500.00", "box4": "0.00"}},
            {"type": "1099-INT", "file": "b09_int_treasury.png",
             "data": {"payer": "US Treasury Direct (fictional)", "ssn": "900-77-1010", "name": "RUTH ALVAREZ",
                      "box3": "275.00"}},
            {"type": "1099-R", "file": "b10_r_pension.png",
             "data": {"payer": "Cornell Area Retirement Plan (fictional)", "ssn": "900-77-1010", "name": "RUTH ALVAREZ",
                      "box1": "9600.00", "box2a": "9600.00", "box4": "960.00", "code": "7"}}],
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for case_id, spec in CASES.items():
        folder = OUT / case_id
        folder.mkdir(parents=True, exist_ok=True)
        docs = []
        for d in spec["documents"]:
            png = BUILDERS[d["type"]](d["data"])
            (folder / d["file"]).write_bytes(png)
            docs.append({"type": d["type"], "file": f"data/fixtures/{case_id}/{d['file']}"})
        record = {k: v for k, v in spec.items() if k != "documents"}
        record["documents"] = docs
        (folder / "case.json").write_text(json.dumps(record, indent=2) + "\n")
        manifest[case_id] = {"purpose": spec["purpose"], "documents": len(docs)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    DEMO.mkdir(exist_ok=True)
    shutil.copy(OUT / "eval_case_1" / "w2_maple_grove.png", DEMO / "w2_image_1.png")
    shutil.copy(OUT / "eval_case_2" / "w2_fingerlakes_hardware.png", DEMO / "w2_image_2.png")
    shutil.copy(OUT / "eval_case_2" / "ssa1099_benson.png", DEMO / "ssa1099_case_2.png")
    shutil.copy(OUT / "grader_style_unseen" / "w2_seneca_transit.png", DEMO / "w2_image_unseen.png")
    print(f"wrote {len(CASES)} cases to {OUT.relative_to(ROOT)} and demo images to {DEMO.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
