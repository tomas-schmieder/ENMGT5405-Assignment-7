"""Independent test oracles (share no code with src/tools/tax_calculations.py).

* Taxable Social Security via the closed-form Pub. 915 relationship:
  taxable = min(0.85*B, 0.5*min(B, max(0, PI - base1)) capped at half the
  base gap, plus 0.85*max(0, PI - base2)), written from the worksheet's
  algebra rather than line by line.
* Tax for taxable income >= $100,000 from the Tax Computation Worksheet's
  printed multiplication and subtraction amounts (2025 Instructions p. 80).
"""

from decimal import ROUND_HALF_UP, Decimal

D = Decimal


def ss_taxable(status: str, benefits: D, other_income: D, tax_exempt: D, adjustments: D = D(0),
               mfs_lived_apart: bool = False) -> D:
    pi = other_income + tax_exempt + benefits / 2 - adjustments
    if status == "mfs" and not mfs_lived_apart:
        return min(D("0.85") * max(D(0), pi), D("0.85") * benefits)
    base1, base2 = (D(32000), D(44000)) if status == "mfj" else (D(25000), D(34000))
    if pi <= base1:
        return D(0)
    tier1 = min(benefits / 2, min(pi - base1, base2 - base1) / 2)
    tier2 = D("0.85") * max(D(0), pi - base2)
    return min(tier1 + tier2, D("0.85") * benefits)


TCW = {  # status -> [(upper, rate, subtraction)]
    "single": [(103350, "0.22", "5086.00"), (197300, "0.24", "7153.00"), (250525, "0.32", "22937.00"),
               (626350, "0.35", "30452.75"), (10**12, "0.37", "42979.75")],
    "mfj": [(206700, "0.22", "10172.00"), (394600, "0.24", "14306.00"), (501050, "0.32", "45874.00"),
            (751600, "0.35", "60905.50"), (10**12, "0.37", "75937.50")],
    "mfs": [(103350, "0.22", "5086.00"), (197300, "0.24", "7153.00"), (250525, "0.32", "22937.00"),
            (375800, "0.35", "30452.75"), (10**12, "0.37", "37968.75")],
    "hoh": [(103350, "0.22", "6825.00"), (197300, "0.24", "8892.00"), (250500, "0.32", "24676.00"),
            (626350, "0.35", "32191.00"), (10**12, "0.37", "44718.00")],
}
TCW["qss"] = TCW["mfj"]


def tcw_tax(status: str, taxable_income: int) -> int:
    for upper, rate, sub in TCW[status]:
        if taxable_income <= upper:
            tax = D(taxable_income) * D(rate) - D(sub)
            return int(tax.quantize(D(1), rounding=ROUND_HALF_UP))
    raise AssertionError("unreachable")
