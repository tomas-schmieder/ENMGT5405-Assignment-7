"""Deterministic 2025 Form 1040-SR calculations.

These pure functions are the *only* place SilverFile performs monetary
arithmetic. They are exposed to the agents exclusively through the MCP server
in ``mcp_server/server.py``; agents never import this module directly.

Every public function returns a ``ToolResult`` dictionary containing:

* ``tool`` / ``version`` - identity of the calculation
* ``inputs`` - the validated inputs, as strings
* ``outputs`` - computed values (line id -> whole-dollar string)
* ``trace`` - ordered, human-readable worksheet steps
* ``rule_ids`` - rule records in ``data/rule_registry.json`` that ground it

Sources (verified copies live in ``data/reference_tax_forms``):

* Standard deduction chart: Form 1040-SR (2025) page 4; assignment §3.2(2)
* Social Security Benefits Worksheet: 2025 Instructions for Form 1040, p. 32
* Tax Table / Tax Computation Worksheet: 2025 Instructions, pp. 68-80
* Qualified Dividends and Capital Gain Tax Worksheet: 2025 Instructions, p. 38
* Enhanced deduction for seniors: Schedule 1-A (2025) Part V; assignment §3.2(3)
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any, Iterable

from src.money import CENT, parse_money, round_dollar, to_cents_str, to_dollar_str

TOOL_VERSION = "2025.1"

FILING_STATUSES = ("single", "mfj", "mfs", "hoh", "qss")
STATUS_LABELS = {
    "single": "Single",
    "mfj": "Married filing jointly",
    "mfs": "Married filing separately",
    "hoh": "Head of household",
    "qss": "Qualifying surviving spouse",
}

# ---------------------------------------------------------------------------
# 2025 constants
# ---------------------------------------------------------------------------

BASE_STANDARD_DEDUCTION = {
    "single": Decimal("15750"),
    "mfs": Decimal("15750"),
    "mfj": Decimal("31500"),
    "qss": Decimal("31500"),
    "hoh": Decimal("23625"),
}
# Additional amount per checked box on line 12d.
ADDITIONAL_PER_BOX = {
    "single": Decimal("2000"),
    "hoh": Decimal("2000"),
    "mfj": Decimal("1600"),
    "mfs": Decimal("1600"),
    "qss": Decimal("1600"),
}
MAX_BOXES = {"single": 2, "hoh": 2, "qss": 2, "mfj": 4, "mfs": 4}

INF = Decimal("Infinity")
BRACKETS: dict[str, list[tuple[Decimal, Decimal]]] = {
    "single": [
        (Decimal("11925"), Decimal("0.10")),
        (Decimal("48475"), Decimal("0.12")),
        (Decimal("103350"), Decimal("0.22")),
        (Decimal("197300"), Decimal("0.24")),
        (Decimal("250525"), Decimal("0.32")),
        (Decimal("626350"), Decimal("0.35")),
        (INF, Decimal("0.37")),
    ],
    "mfj": [
        (Decimal("23850"), Decimal("0.10")),
        (Decimal("96950"), Decimal("0.12")),
        (Decimal("206700"), Decimal("0.22")),
        (Decimal("394600"), Decimal("0.24")),
        (Decimal("501050"), Decimal("0.32")),
        (Decimal("751600"), Decimal("0.35")),
        (INF, Decimal("0.37")),
    ],
    "mfs": [
        (Decimal("11925"), Decimal("0.10")),
        (Decimal("48475"), Decimal("0.12")),
        (Decimal("103350"), Decimal("0.22")),
        (Decimal("197300"), Decimal("0.24")),
        (Decimal("250525"), Decimal("0.32")),
        (Decimal("375800"), Decimal("0.35")),
        (INF, Decimal("0.37")),
    ],
    "hoh": [
        (Decimal("17000"), Decimal("0.10")),
        (Decimal("64850"), Decimal("0.12")),
        (Decimal("103350"), Decimal("0.22")),
        (Decimal("197300"), Decimal("0.24")),
        (Decimal("250500"), Decimal("0.32")),
        (Decimal("626350"), Decimal("0.35")),
        (INF, Decimal("0.37")),
    ],
}
BRACKETS["qss"] = BRACKETS["mfj"]

# Qualified Dividends and Capital Gain Tax Worksheet thresholds (lines 6 and 13)
QDCG_ZERO_RATE_MAX = {
    "single": Decimal("48350"),
    "mfs": Decimal("48350"),
    "mfj": Decimal("96700"),
    "qss": Decimal("96700"),
    "hoh": Decimal("64750"),
}
QDCG_FIFTEEN_RATE_MAX = {
    "single": Decimal("533400"),
    "mfs": Decimal("300000"),
    "mfj": Decimal("600050"),
    "qss": Decimal("600050"),
    "hoh": Decimal("566700"),
}

SENIOR_DEDUCTION_PER_PERSON = Decimal("6000")
SENIOR_PHASEOUT_THRESHOLD = {"mfj": Decimal("150000")}  # everyone else eligible: 75,000
SENIOR_PHASEOUT_DEFAULT = Decimal("75000")
SENIOR_PHASEOUT_RATE = Decimal("0.06")


class ToolInputError(ValueError):
    """Invalid input to a calculation tool. Never silently defaulted."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _status(value: str) -> str:
    status = (value or "").strip().lower()
    if status not in FILING_STATUSES:
        raise ToolInputError(f"filing_status must be one of {FILING_STATUSES}, got {value!r}")
    return status


def _money(name: str, value: Any, allow_negative: bool = False) -> Decimal:
    try:
        amount = parse_money(value)
    except ValueError as exc:
        raise ToolInputError(f"{name}: {exc}") from exc
    if amount < 0 and not allow_negative:
        raise ToolInputError(f"{name} may not be negative in this scope")
    return amount


def _whole(name: str, value: Any) -> Decimal:
    """A line value that must already be whole dollars."""
    amount = _money(name, value)
    if amount != round_dollar(amount):
        raise ToolInputError(f"{name} must be a whole-dollar line amount, got {value!r}")
    return round_dollar(amount)


def _result(tool: str, inputs: dict, outputs: dict, trace: list[str], rule_ids: list[str],
            extra: dict | None = None) -> dict:
    res = {
        "tool": tool,
        "version": TOOL_VERSION,
        "inputs": inputs,
        "outputs": outputs,
        "trace": trace,
        "rule_ids": rule_ids,
    }
    if extra:
        res.update(extra)
    return res


def _d(amount: Decimal) -> str:
    return f"${amount:,.2f}"


# ---------------------------------------------------------------------------
# aggregation and comparison
# ---------------------------------------------------------------------------

def aggregate_amounts(line: str, items: list[dict]) -> dict:
    """Sum source amounts for one line, cents kept, total rounded.

    ``items`` is a list of ``{"source_id": str, "amount": "1234.56"}``. A
    repeated ``source_id`` is rejected so the same document box can never be
    counted twice.
    """
    seen: set[str] = set()
    total = Decimal("0.00")
    trace = []
    clean = []
    for item in items:
        sid = str(item.get("source_id", "")).strip()
        if not sid:
            raise ToolInputError("every item needs a source_id")
        if sid in seen:
            raise ToolInputError(f"duplicate source_id {sid!r}; refusing to double count")
        seen.add(sid)
        amount = _money(f"amount[{sid}]", item.get("amount"))
        total += amount
        clean.append({"source_id": sid, "amount": to_cents_str(amount)})
        trace.append(f"+ {_d(amount)} from {sid}")
    rounded = round_dollar(total)
    trace.append(f"= {_d(total)} total; rounded to whole dollars = ${rounded:,.0f}")
    if not items:
        trace = ["No source amounts for this line; total is $0 (confirmed none)."]
    return _result(
        "aggregate_amounts",
        {"line": line, "items": clean},
        {line: to_dollar_str(rounded)},
        trace,
        ["R-ROUND-01"],
        {"exact_total": to_cents_str(total)},
    )


def compare_amounts(label: str, document_amount: Any, stated_amount: Any,
                    abs_tolerance: Any = "1000", rel_tolerance: Any = "0.10") -> dict:
    """Decide whether a taxpayer statement materially differs from a document.

    Material if the absolute difference exceeds BOTH ``abs_tolerance`` and
    ``rel_tolerance`` x document amount (i.e. the larger of the two limits).
    """
    doc = _money("document_amount", document_amount)
    stated = _money("stated_amount", stated_amount)
    abs_tol = _money("abs_tolerance", abs_tolerance)
    rel_tol = Decimal(str(rel_tolerance))
    diff = abs(doc - stated)
    limit = max(abs_tol, (doc * rel_tol).quantize(CENT))
    material = diff > limit
    trace = [
        f"Document shows {_d(doc)}; taxpayer stated {_d(stated)}.",
        f"Difference = {_d(diff)}; tolerance = larger of {_d(abs_tol)} or {rel_tol:.0%} of document = {_d(limit)}.",
        "Material conflict." if material else "Within tolerance; not a conflict.",
    ]
    return _result(
        "compare_amounts",
        {"label": label, "document_amount": to_cents_str(doc), "stated_amount": to_cents_str(stated),
         "abs_tolerance": to_cents_str(abs_tol), "rel_tolerance": str(rel_tol)},
        {"difference": to_cents_str(diff), "limit": to_cents_str(limit), "material": material},
        trace,
        ["R-CONFLICT-01"],
    )


def ira_distributions(gross_items: list[dict], taxable_items: list[dict], qcd_amount: Any = "0") -> dict:
    """Lines 4a/4b. 4a = total gross IRA distributions; 4b = total box 2a
    taxable amounts less any qualified charitable distribution, not below 0."""
    gross = aggregate_amounts("4a", gross_items)
    taxable = aggregate_amounts("4b_before_qcd", taxable_items)
    qcd = _money("qcd_amount", qcd_amount)
    g_exact = Decimal(gross["exact_total"])
    t_exact = Decimal(taxable["exact_total"])
    if qcd > g_exact:
        raise ToolInputError("QCD cannot exceed the gross IRA distribution")
    net = max(Decimal("0"), t_exact - qcd)
    out_4a, out_4b = round_dollar(g_exact), round_dollar(net)
    trace = ["Gross IRA distributions (box 1): " + "; ".join(gross["trace"]),
             "Taxable amounts (box 2a): " + "; ".join(taxable["trace"])]
    if qcd > 0:
        trace.append(f"Less qualified charitable distribution {_d(qcd)} -> {_d(net)}")
    trace.append(f"Line 4a = ${out_4a:,.0f}; line 4b = ${out_4b:,.0f}")
    return _result("ira_distributions",
                   {"gross_items": gross["inputs"]["items"], "taxable_items": taxable["inputs"]["items"],
                    "qcd_amount": to_cents_str(qcd)},
                   {"4a": str(out_4a), "4b": str(out_4b), "qcd": "yes" if qcd > 0 else "no"}, trace,
                   ["R-IRA-01", "R-IRA-02", "R-ROUND-01"])


# ---------------------------------------------------------------------------
# Social Security
# ---------------------------------------------------------------------------

def taxable_social_security(filing_status: str, benefits_box5: Any, line_1z: Any, line_2b: Any,
                            line_3b: Any, line_4b: Any, line_5b: Any, line_7a: Any, line_8: Any,
                            line_2a: Any, schedule1_line26: Any, schedule1_line21: Any,
                            mfs_lived_apart_all_year: bool = False) -> dict:
    """Social Security Benefits Worksheet - Lines 6a and 6b (2025 Instr. p. 32).

    Requires every other income line first; this is the ordering dependency
    the graph enforces (taxable benefits feed line 9 and therefore AGI).
    Worksheet line 6 (Schedule 1 lines 11-20, 23 and 25) is Schedule 1 line 26
    less line 21 (student loan interest); line 22 is reserved and line 25 already
    totals lines 24a-24z.
    """
    status = _status(filing_status)
    l1 = _money("benefits_box5", benefits_box5, allow_negative=True)
    if l1 < 0:
        raise ToolInputError("Net benefits (box 5) are negative: repayment cases are out of scope")
    other = {k: _whole(k, v) for k, v in {
        "line_1z": line_1z, "line_2b": line_2b, "line_3b": line_3b, "line_4b": line_4b,
        "line_5b": line_5b, "line_7a": line_7a, "line_8": line_8}.items()}
    l4 = _whole("line_2a", line_2a)
    s1_26 = _money("schedule1_line26", schedule1_line26)
    s1_21 = _money("schedule1_line21", schedule1_line21)
    if s1_21 > s1_26:
        raise ToolInputError("Schedule 1 line 21 cannot exceed line 26")
    l6 = s1_26 - s1_21
    trace: list[str] = []
    lines: dict[str, str] = {}

    def rec(n: int, value: Decimal, text: str) -> None:
        lines[str(n)] = to_cents_str(value)
        trace.append(f"Line {n}: {text} = {_d(value)}")

    rec(1, l1, "Total of box 5 of all Forms SSA-1099")
    l2 = (l1 * Decimal("0.50")).quantize(CENT)
    rec(2, l2, "Line 1 x 50%")
    l3 = sum(other.values(), Decimal("0"))
    rec(3, l3, "Form 1040-SR lines 1z + 2b + 3b + 4b + 5b + 7a + 8")
    rec(4, l4, "Tax-exempt interest, line 2a")
    l5 = l2 + l3 + l4
    rec(5, l5, "Lines 2 + 3 + 4 (provisional income)")
    rec(6, l6, f"Schedule 1 lines 11-20, 23 and 25 (line 26 {_d(s1_26)} - line 21 {_d(s1_21)})")
    taxable = Decimal("0")
    if not l6 < l5:
        trace.append("Line 7: line 6 is not less than line 5 -> none of the benefits are taxable.")
    else:
        l7 = l5 - l6
        rec(7, l7, "Line 5 - line 6")
        mfs_lived_with = status == "mfs" and not mfs_lived_apart_all_year
        if mfs_lived_with:
            l16 = (l7 * Decimal("0.85")).quantize(CENT)
            trace.append("Married filing separately and lived with spouse: skip lines 8-15.")
            rec(16, l16, "Line 7 x 85%")
        else:
            l8 = Decimal("32000") if status == "mfj" else Decimal("25000")
            rec(8, l8, "Base amount ($32,000 MFJ; $25,000 otherwise)")
            if not l8 < l7:
                trace.append("Line 9: line 8 is not less than line 7 -> none of the benefits are taxable.")
                l16 = None
            else:
                l9 = l7 - l8
                rec(9, l9, "Line 7 - line 8")
                l10 = Decimal("12000") if status == "mfj" else Decimal("9000")
                rec(10, l10, "$12,000 MFJ; $9,000 otherwise")
                l11 = max(Decimal("0"), l9 - l10)
                rec(11, l11, "Line 9 - line 10, not less than zero")
                l12 = min(l9, l10)
                rec(12, l12, "Smaller of line 9 or line 10")
                l13 = (l12 / 2).quantize(CENT)
                rec(13, l13, "One-half of line 12")
                l14 = min(l2, l13)
                rec(14, l14, "Smaller of line 2 or line 13")
                l15 = (l11 * Decimal("0.85")).quantize(CENT)
                rec(15, l15, "Line 11 x 85%")
                l16 = l14 + l15
                rec(16, l16, "Lines 14 + 15")
        if l16 is not None:
            l17 = (l1 * Decimal("0.85")).quantize(CENT)
            rec(17, l17, "Line 1 x 85%")
            taxable = min(l16, l17)
            rec(18, taxable, "Smaller of line 16 or line 17 (taxable benefits)")
    out_6a = round_dollar(l1)
    out_6b = round_dollar(taxable)
    trace.append(f"Form line 6a = ${out_6a:,.0f}; line 6b = ${out_6b:,.0f} (whole dollars)")
    return _result(
        "taxable_social_security",
        {"filing_status": status, "benefits_box5": to_cents_str(l1),
         **{k: str(v) for k, v in other.items()}, "line_2a": str(l4),
         "schedule1_line26": to_cents_str(s1_26), "schedule1_line21": to_cents_str(s1_21),
         "mfs_lived_apart_all_year": bool(mfs_lived_apart_all_year)},
        {"6a": str(out_6a), "6b": str(out_6b)},
        trace,
        ["R-SS-01", "R-SS-02", "R-ROUND-01"],
        {"worksheet": lines},
    )


# ---------------------------------------------------------------------------
# income, AGI, deductions
# ---------------------------------------------------------------------------

def total_income(line_1z: Any, line_2b: Any, line_3b: Any, line_4b: Any, line_5b: Any,
                 line_6b: Any, line_7a: Any, line_8: Any) -> dict:
    vals = {k: _whole(k, v) for k, v in {
        "1z": line_1z, "2b": line_2b, "3b": line_3b, "4b": line_4b, "5b": line_5b,
        "6b": line_6b, "7a": line_7a, "8": line_8}.items()}
    total = sum(vals.values(), Decimal("0"))
    trace = [" + ".join(f"line {k} ${v:,.0f}" for k, v in vals.items()) + f" = ${total:,.0f}"]
    return _result("total_income", {k: str(v) for k, v in vals.items()}, {"9": str(total)}, trace,
                   ["R-LINE9-01"])


def adjusted_gross_income(line_9: Any, line_10: Any) -> dict:
    l9 = _whole("line_9", line_9)
    l10 = _whole("line_10", line_10)
    agi = l9 - l10
    trace = [f"Line 9 ${l9:,.0f} - line 10 ${l10:,.0f} = ${agi:,.0f} (line 11a, carried to 11b)"]
    return _result("adjusted_gross_income", {"line_9": str(l9), "line_10": str(l10)},
                   {"11a": str(agi), "11b": str(agi)}, trace, ["R-AGI-01"])


def standard_deduction(filing_status: str, taxpayer_65_or_older: bool, taxpayer_blind: bool,
                       spouse_65_or_older: bool, spouse_blind: bool,
                       can_be_claimed_as_dependent: bool, spouse_itemizes_separately: bool,
                       dual_status_alien: bool) -> dict:
    """Standard Deduction Chart (Form 1040-SR page 4; assignment §3.2(2))."""
    status = _status(filing_status)
    exceptions = []
    if can_be_claimed_as_dependent:
        exceptions.append("taxpayer_can_be_claimed_as_dependent")
    if spouse_itemizes_separately:
        exceptions.append("spouse_itemizes_on_separate_return")
    if dual_status_alien:
        exceptions.append("dual_status_alien")
    inputs = {"filing_status": status, "taxpayer_65_or_older": bool(taxpayer_65_or_older),
              "taxpayer_blind": bool(taxpayer_blind), "spouse_65_or_older": bool(spouse_65_or_older),
              "spouse_blind": bool(spouse_blind), "can_be_claimed_as_dependent": bool(can_be_claimed_as_dependent),
              "spouse_itemizes_separately": bool(spouse_itemizes_separately),
              "dual_status_alien": bool(dual_status_alien)}
    if exceptions:
        return _result("standard_deduction", inputs, {}, [
            "The Standard Deduction Chart does not apply: " + ", ".join(exceptions) + ".",
            "This is an escalation condition; no amount is produced."], ["R-SD-02"],
            {"exception": exceptions})
    boxes = [taxpayer_65_or_older, taxpayer_blind]
    if status in {"mfj", "mfs"}:
        boxes += [spouse_65_or_older, spouse_blind]
    elif spouse_65_or_older or spouse_blind:
        raise ToolInputError(f"spouse boxes cannot be checked for filing status {status}")
    count = sum(1 for b in boxes if b)
    if count > MAX_BOXES[status]:  # pragma: no cover - guarded above
        raise ToolInputError("too many boxes")
    base = BASE_STANDARD_DEDUCTION[status]
    per = ADDITIONAL_PER_BOX[status]
    amount = base + per * count
    trace = [
        f"Boxes checked on line 12d: {count}",
        f"Base amount for {STATUS_LABELS[status]}: ${base:,.0f}",
        f"Additional ${per:,.0f} x {count} box(es) = ${per * count:,.0f}",
        f"Standard deduction (line 12e) = ${amount:,.0f}",
    ]
    return _result("standard_deduction", inputs, {"12d_box_count": str(count), "12e": str(amount)},
                   trace, ["R-SD-01", "R-SD-03"])


def enhanced_senior_deduction(filing_status: str, magi: Any, taxpayer_qualifies: bool,
                              spouse_qualifies: bool) -> dict:
    """Schedule 1-A Part V, carried to line 13b (assignment §3.2(3)).

    ``*_qualifies`` already reflects: born before Jan 2 1961 and a valid
    (here: fictional 900-series) SSN. Married filing separately cannot claim.
    """
    status = _status(filing_status)
    m = _whole("magi", magi)
    inputs = {"filing_status": status, "magi": str(m), "taxpayer_qualifies": bool(taxpayer_qualifies),
              "spouse_qualifies": bool(spouse_qualifies)}
    if status == "mfs":
        return _result("enhanced_senior_deduction", inputs,
                       {"sch1a_31": str(m), "sch1a_37": "0", "sch1a_38": "0", "13b": "0"},
                       ["Married filing separately: the enhanced deduction for seniors cannot be claimed "
                        "(Schedule 1-A Part V caution: married taxpayers must file jointly)."],
                       ["R-ESD-02"])
    if spouse_qualifies and status != "mfj":
        raise ToolInputError("a spouse can only qualify on a joint return")
    threshold = SENIOR_PHASEOUT_THRESHOLD.get(status, SENIOR_PHASEOUT_DEFAULT)
    trace = [f"Line 31 (MAGI = Schedule 1-A line 3 = Form 1040-SR line 11b; no foreign exclusions in scope): ${m:,.0f}",
             f"Line 32 threshold: ${threshold:,.0f}"]
    excess = m - threshold
    if excess <= 0:
        line33 = Decimal("0")
        line34 = Decimal("0")
        line35 = SENIOR_DEDUCTION_PER_PERSON
        trace.append("Line 33: MAGI does not exceed the threshold -> line 35 = $6,000")
    else:
        line33 = excess
        line34 = (excess * SENIOR_PHASEOUT_RATE).quantize(CENT)
        line35 = max(Decimal("0"), SENIOR_DEDUCTION_PER_PERSON - line34)
        trace += [f"Line 33: ${m:,.0f} - ${threshold:,.0f} = ${excess:,.0f}",
                  f"Line 34: line 33 x 6% = {_d(line34)}",
                  f"Line 35: $6,000 - line 34 (not less than zero) = {_d(line35)}"]
    l36a = line35 if taxpayer_qualifies else Decimal("0")
    l36b = line35 if spouse_qualifies else Decimal("0")
    trace.append(f"Line 36a (you qualify: {'yes' if taxpayer_qualifies else 'no'}) = {_d(l36a)}")
    if status == "mfj":
        trace.append(f"Line 36b (spouse qualifies: {'yes' if spouse_qualifies else 'no'}) = {_d(l36b)}")
    l37 = l36a + l36b
    l37r = round_dollar(l37)
    trace.append(f"Line 37 = {_d(l37)}; line 38 (other Schedule 1-A parts are out of scope, $0) -> line 13b = ${l37r:,.0f}")
    outputs = {
        "sch1a_31": str(m), "sch1a_32": str(threshold), "sch1a_33": str(round_dollar(line33)),
        "sch1a_34": str(round_dollar(line34)), "sch1a_35": str(round_dollar(line35)),
        "sch1a_36a": str(round_dollar(l36a)), "sch1a_36b": str(round_dollar(l36b)),
        "sch1a_37": str(l37r), "sch1a_38": str(l37r), "13b": str(l37r),
    }
    return _result("enhanced_senior_deduction", inputs, outputs, trace, ["R-ESD-01", "R-ESD-02", "R-ESD-03"])


def deductions_and_taxable_income(line_11b: Any, line_12e: Any, line_13a: Any, line_13b: Any) -> dict:
    agi = _whole("line_11b", line_11b)
    sd = _whole("line_12e", line_12e)
    qbi = _whole("line_13a", line_13a)
    esd = _whole("line_13b", line_13b)
    l14 = sd + qbi + esd
    l15 = max(Decimal("0"), agi - l14)
    trace = [f"Line 14 = line 12e ${sd:,.0f} + line 13a ${qbi:,.0f} + line 13b ${esd:,.0f} = ${l14:,.0f}",
             f"Line 15 = line 11b ${agi:,.0f} - line 14 ${l14:,.0f}, not less than zero = ${l15:,.0f}"]
    return _result("deductions_and_taxable_income",
                   {"line_11b": str(agi), "line_12e": str(sd), "line_13a": str(qbi), "line_13b": str(esd)},
                   {"14": str(l14), "15": str(l15)}, trace, ["R-LINE14-01"])


# ---------------------------------------------------------------------------
# tax
# ---------------------------------------------------------------------------

def bracket_tax(amount: Decimal, status: str) -> Decimal:
    """Exact progressive tax on ``amount`` using the 2025 rate schedule."""
    tax = Decimal("0")
    lower = Decimal("0")
    for upper, rate in BRACKETS[status]:
        if amount <= lower:
            break
        taxed = min(amount, upper) - lower
        tax += taxed * rate
        lower = upper
    return tax


def _tax_table_midpoint(ti: Decimal) -> Decimal | None:
    """Midpoint of the Tax Table row containing ``ti`` (ti < 100,000)."""
    if ti < 5:
        return None
    if ti < 15:
        return Decimal("10")
    if ti < 25:
        return Decimal("20")
    if ti < 3000:
        lower = ((ti - 25) / 25).to_integral_value(rounding=ROUND_FLOOR) * 25 + 25
        return lower + Decimal("12.5")
    lower = (ti / 50).to_integral_value(rounding=ROUND_FLOOR) * 50
    return lower + 25


def tax_on_amount(amount: Any, filing_status: str) -> tuple[Decimal, str]:
    """Tax Table (< $100,000) or Tax Computation Worksheet (>= $100,000)."""
    status = _status(filing_status)
    ti = _money("amount", amount)
    if ti < Decimal("100000"):
        mid = _tax_table_midpoint(ti)
        if mid is None:
            return Decimal("0"), f"Tax Table: ${ti:,.0f} is under $5 -> tax $0"
        tax = round_dollar(bracket_tax(mid, status))
        return tax, f"Tax Table row containing ${ti:,.0f} (computed at row midpoint ${mid:,.2f}) -> ${tax:,.0f}"
    tax = bracket_tax(ti, status)
    rate = next(r for upper, r in BRACKETS[status] if ti <= upper)
    return round_dollar(tax), (f"Tax Computation Worksheet: ${ti:,.0f} in the {rate:.0%} bracket -> "
                               f"{_d(tax)}, rounded ${round_dollar(tax):,.0f}")


def income_tax(filing_status: str, taxable_income: Any, qualified_dividends: Any,
               capital_gain_7a: Any = "0") -> dict:
    """Line 16. Uses the Qualified Dividends and Capital Gain Tax Worksheet when
    line 3a or 7a is positive, otherwise the Tax Table / Tax Computation Worksheet."""
    status = _status(filing_status)
    l1 = _whole("taxable_income", taxable_income)
    qd = _whole("qualified_dividends", qualified_dividends)
    cg = _whole("capital_gain_7a", capital_gain_7a)
    inputs = {"filing_status": status, "taxable_income": str(l1), "qualified_dividends": str(qd),
              "capital_gain_7a": str(cg)}
    if qd <= 0 and cg <= 0:
        tax, how = tax_on_amount(l1, status)
        return _result("income_tax", inputs, {"16": str(tax)}, [how, f"Line 16 = ${tax:,.0f}"],
                       ["R-TAX-01"], {"method": "tax_table" if l1 < 100000 else "tax_computation_worksheet"})
    trace = ["Qualified Dividends and Capital Gain Tax Worksheet (2025 Instructions p. 38):"]
    ws: dict[str, str] = {}

    def rec(n: str, value: Decimal, text: str) -> None:
        ws[n] = to_cents_str(value)
        trace.append(f"Line {n}: {text} = {_d(value)}")

    rec("1", l1, "Taxable income, line 15")
    rec("2", qd, "Qualified dividends, line 3a")
    rec("3", cg, "Line 7a (no Schedule D in scope)")
    l4 = qd + cg
    rec("4", l4, "Lines 2 + 3")
    l5 = max(Decimal("0"), l1 - l4)
    rec("5", l5, "Line 1 - line 4, not less than zero")
    l6 = QDCG_ZERO_RATE_MAX[status]
    rec("6", l6, "0% rate threshold")
    l7 = min(l1, l6)
    rec("7", l7, "Smaller of line 1 or line 6")
    l8 = min(l5, l7)
    rec("8", l8, "Smaller of line 5 or line 7")
    l9 = l7 - l8
    rec("9", l9, "Line 7 - line 8 (taxed at 0%)")
    l10 = min(l1, l4)
    rec("10", l10, "Smaller of line 1 or line 4")
    rec("11", l9, "Amount from line 9")
    l12 = l10 - l9
    rec("12", l12, "Line 10 - line 11")
    l13 = QDCG_FIFTEEN_RATE_MAX[status]
    rec("13", l13, "15% rate threshold")
    l14 = min(l1, l13)
    rec("14", l14, "Smaller of line 1 or line 13")
    l15 = l5 + l9
    rec("15", l15, "Lines 5 + 9")
    l16 = max(Decimal("0"), l14 - l15)
    rec("16", l16, "Line 14 - line 15, not less than zero")
    l17 = min(l12, l16)
    rec("17", l17, "Smaller of line 12 or line 16")
    l18 = (l17 * Decimal("0.15")).quantize(CENT)
    rec("18", l18, "Line 17 x 15%")
    l19 = l9 + l17
    rec("19", l19, "Lines 9 + 17")
    l20 = l10 - l19
    rec("20", l20, "Line 10 - line 19")
    l21 = (l20 * Decimal("0.20")).quantize(CENT)
    rec("21", l21, "Line 20 x 20%")
    t22, how22 = tax_on_amount(l5, status)
    trace.append(f"Line 22: tax on line 5 - {how22}")
    ws["22"] = to_cents_str(t22)
    l23 = l18 + l21 + t22
    rec("23", l23, "Lines 18 + 21 + 22")
    t24, how24 = tax_on_amount(l1, status)
    trace.append(f"Line 24: tax on line 1 - {how24}")
    ws["24"] = to_cents_str(t24)
    l25 = min(l23, t24)
    rec("25", l25, "Smaller of line 23 or line 24")
    tax = round_dollar(l25)
    trace.append(f"Line 16 = ${tax:,.0f}")
    return _result("income_tax", inputs, {"16": str(tax)}, trace, ["R-TAX-01", "R-TAX-02"],
                   {"method": "qualified_dividends_worksheet", "worksheet": ws})


def total_tax(line_16: Any, schedule2_line3: Any, line_19: Any, schedule3_line8: Any,
              schedule2_line21: Any) -> dict:
    l16 = _whole("line_16", line_16)
    l17 = _whole("schedule2_line3", schedule2_line3)
    l19 = _whole("line_19", line_19)
    l20 = _whole("schedule3_line8", schedule3_line8)
    l23 = _whole("schedule2_line21", schedule2_line21)
    l18 = l16 + l17
    l21 = l19 + l20
    l22 = max(Decimal("0"), l18 - l21)
    l24 = l22 + l23
    trace = [f"Line 18 = line 16 ${l16:,.0f} + line 17 ${l17:,.0f} = ${l18:,.0f}",
             f"Line 21 = line 19 ${l19:,.0f} + line 20 ${l20:,.0f} = ${l21:,.0f}",
             f"Line 22 = line 18 - line 21, not less than zero = ${l22:,.0f}",
             f"Line 24 = line 22 ${l22:,.0f} + line 23 ${l23:,.0f} = ${l24:,.0f}"]
    return _result("total_tax", {"line_16": str(l16), "schedule2_line3": str(l17), "line_19": str(l19),
                                 "schedule3_line8": str(l20), "schedule2_line21": str(l23)},
                   {"17": str(l17), "18": str(l18), "19": str(l19), "20": str(l20), "21": str(l21),
                    "22": str(l22), "23": str(l23), "24": str(l24)}, trace, ["R-LINE24-01"])


def total_payments(line_25a: Any, line_25b: Any, line_25c: Any, line_26: Any,
                   schedule3_line15: Any) -> dict:
    a = _whole("line_25a", line_25a)
    b = _whole("line_25b", line_25b)
    c = _whole("line_25c", line_25c)
    est = _whole("line_26", line_26)
    s3 = _whole("schedule3_line15", schedule3_line15)
    d = a + b + c
    l32 = s3  # lines 27a-30 (credits) are out of scope and blank
    l33 = d + est + l32
    trace = [f"Line 25d = 25a ${a:,.0f} + 25b ${b:,.0f} + 25c ${c:,.0f} = ${d:,.0f}",
             f"Line 32 = line 31 (Schedule 3 line 15) ${s3:,.0f}; lines 27a-30 not in scope",
             f"Line 33 = 25d ${d:,.0f} + 26 ${est:,.0f} + 32 ${l32:,.0f} = ${l33:,.0f}"]
    return _result("total_payments", {"line_25a": str(a), "line_25b": str(b), "line_25c": str(c),
                                      "line_26": str(est), "schedule3_line15": str(s3)},
                   {"25d": str(d), "31": str(s3), "32": str(l32), "33": str(l33)}, trace, ["R-PAY-01"])


def refund_or_amount_owed(line_24: Any, line_33: Any) -> dict:
    tax = _whole("line_24", line_24)
    pay = _whole("line_33", line_33)
    over = max(Decimal("0"), pay - tax)
    owe = max(Decimal("0"), tax - pay)
    if over > 0:
        trace = [f"Line 33 ${pay:,.0f} is more than line 24 ${tax:,.0f}: overpaid ${over:,.0f} (line 34)"]
    elif owe > 0:
        trace = [f"Line 24 ${tax:,.0f} is more than line 33 ${pay:,.0f}: amount owed ${owe:,.0f} (line 37)"]
    else:
        trace = ["Line 24 equals line 33: no overpayment and nothing owed."]
    return _result("refund_or_amount_owed", {"line_24": str(tax), "line_33": str(pay)},
                   {"34": str(over), "35a": str(over), "37": str(owe)}, trace, ["R-PAY-02"])


# ---------------------------------------------------------------------------
# verification (used by the Review / Audit agent)
# ---------------------------------------------------------------------------

def verify_return(lines: dict, filing_status: str, box_count: int) -> dict:
    """Independent consistency checks over a proposed set of line values.

    Recomputes totals from the supplied lines and checks the relationships
    the assignment highlights (e.g. 6b may not exceed 6a). The standard
    deduction is re-read from a literal copy of the Form 1040-SR page 4 chart
    rather than the formula used in :func:`standard_deduction`.
    """
    status = _status(filing_status)
    v = {k: _whole(f"line {k}", val) for k, val in lines.items() if val not in (None, "")}

    def g(k: str) -> Decimal:
        return v.get(k, Decimal("0"))

    findings: list[dict] = []
    trace: list[str] = []

    def check(rule: str, lines_: list[str], ok: bool, expect: str) -> None:
        trace.append(f"{'OK  ' if ok else 'FAIL'} {expect}")
        if not ok:
            findings.append({"check": rule, "lines": lines_, "expected": expect})

    check("line9_sum", ["9"], g("9") == sum(g(k) for k in ["1z", "2b", "3b", "4b", "5b", "6b", "7a", "8"]),
          f"line 9 (${g('9'):,.0f}) = 1z+2b+3b+4b+5b+6b+7a+8")
    check("line11_agi", ["11a"], g("11a") == g("9") - g("10"), "line 11a = line 9 - line 10")
    check("line11b_copy", ["11b"], g("11b") == g("11a"), "line 11b = line 11a")
    check("line14_sum", ["14"], g("14") == g("12e") + g("13a") + g("13b"), "line 14 = 12e + 13a + 13b")
    check("line15_floor", ["15"], g("15") == max(Decimal("0"), g("11b") - g("14")),
          "line 15 = max(0, 11b - 14)")
    check("line6b_cap", ["6b", "6a"], g("6b") <= round_dollar(g("6a") * Decimal("0.85")),
          "line 6b <= 85% of line 6a")
    check("line6b_le_6a", ["6b", "6a"], g("6b") <= g("6a"), "line 6b <= line 6a")
    check("line3a_subset", ["3a", "3b"], g("3a") <= g("3b"), "qualified dividends 3a <= ordinary dividends 3b")
    check("line4b_le_4a", ["4b", "4a"], g("4b") <= g("4a"), "line 4b <= line 4a")
    check("line5b_le_5a", ["5b", "5a"], g("5b") <= g("5a"), "line 5b <= line 5a")
    check("line18_sum", ["18"], g("18") == g("16") + g("17"), "line 18 = 16 + 17")
    check("line22_floor", ["22"], g("22") == max(Decimal("0"), g("18") - g("21")), "line 22 = max(0, 18 - 21)")
    check("line24_sum", ["24"], g("24") == g("22") + g("23"), "line 24 = 22 + 23")
    check("line25d_sum", ["25d"], g("25d") == g("25a") + g("25b") + g("25c"), "line 25d = 25a + 25b + 25c")
    check("line33_sum", ["33"], g("33") == g("25d") + g("26") + g("32"), "line 33 = 25d + 26 + 32")
    check("line34_37", ["34", "37"],
          g("34") == max(Decimal("0"), g("33") - g("24")) and g("37") == max(Decimal("0"), g("24") - g("33")),
          "line 34 / 37 = difference between 33 and 24")
    chart = _STANDARD_DEDUCTION_CHART.get((status, int(box_count)))
    if chart is not None:
        check("line12e_chart", ["12e"], g("12e") == chart,
              f"line 12e = Standard Deduction Chart value ${chart:,.0f} for {box_count} box(es)")
    # Tax re-check with the independent bracket path.
    if g("3a") <= 0 and g("7a") <= 0:
        expect_tax, _ = tax_on_amount(g("15"), status)
        check("line16_tax", ["16"], g("16") == expect_tax, f"line 16 = tax on line 15 (${expect_tax:,.0f})")
    return _result("verify_return", {"filing_status": status, "box_count": int(box_count),
                                     "lines": {k: str(x) for k, x in v.items()}},
                   {"passed": not findings, "findings": findings}, trace, ["R-AUDIT-01"])


# Literal transcription of Form 1040-SR (2025) page 4, plus the base amounts
# for zero boxes from assignment §3.2(2).
_STANDARD_DEDUCTION_CHART: dict[tuple[str, int], Decimal] = {
    ("single", 0): Decimal("15750"), ("single", 1): Decimal("17750"), ("single", 2): Decimal("19750"),
    ("mfj", 0): Decimal("31500"), ("mfj", 1): Decimal("33100"), ("mfj", 2): Decimal("34700"),
    ("mfj", 3): Decimal("36300"), ("mfj", 4): Decimal("37900"),
    ("qss", 0): Decimal("31500"), ("qss", 1): Decimal("33100"), ("qss", 2): Decimal("34700"),
    ("hoh", 0): Decimal("23625"), ("hoh", 1): Decimal("25625"), ("hoh", 2): Decimal("27625"),
    ("mfs", 0): Decimal("15750"), ("mfs", 1): Decimal("17350"), ("mfs", 2): Decimal("18950"),
    ("mfs", 3): Decimal("20550"), ("mfs", 4): Decimal("22150"),
}


def sum_whole(values: Iterable[Any]) -> Decimal:  # pragma: no cover - convenience for tests
    return sum((_whole("v", x) for x in values), Decimal("0"))
