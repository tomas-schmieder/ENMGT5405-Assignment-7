"""Independent test oracle: the printed 2025 IRS Tax Table.

Parses the Tax Table pages of the 2025 Instructions for Form 1040 (pp. 68-79)
from the PDF in ``data/reference_tax_forms``. Used only by tests to check the
production tax function against the IRS's own published numbers; it shares no
code with ``src/tools/tax_calculations.py``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

INSTRUCTIONS = (Path(__file__).resolve().parents[2] / "data" / "reference_tax_forms" / "reference"
                / "2025_Instructions_Form_1040_and_1040-SR.pdf")
STATUS_ORDER = ("single", "mfj", "mfs", "hoh")


@lru_cache(maxsize=1)
def load_tax_table() -> dict[int, tuple[int, dict[str, int]]]:
    """Return ``{at_least: (but_less_than, {status: tax})}`` for 0 <= TI < 100,000."""
    import pymupdf

    doc = pymupdf.open(str(INSTRUCTIONS))
    rows: dict[int, tuple[int, dict[str, int]]] = {}
    for page in doc:
        text = page.get_text()
        if "Tax Table" not in text or "Your tax is" not in text:
            continue
        # skip the worked "Sample Table" block on the first page
        if "Sample Table" in text:
            text = text[text.find("on Form 1040, line 16."):]
        tokens = [int(t.replace(",", "")) for t in re.findall(r"(?<![\d,])\d{1,3}(?:,\d{3})*(?![\d,])", text)]
        i = 0
        while i + 5 < len(tokens):
            lo, hi = tokens[i], tokens[i + 1]
            taxes = tokens[i + 2:i + 6]
            if hi - lo in (5, 10, 25, 50) and lo < 100000 and all(0 <= t <= hi * 0.3 + 5 for t in taxes):
                rows.setdefault(lo, (hi, dict(zip(STATUS_ORDER, taxes))))
                i += 6
            else:
                i += 1
    # contiguity check so a parse error can never silently weaken a test
    expected = 0
    for lo in sorted(rows):
        if lo != expected:
            raise AssertionError(f"tax table parse gap at {expected} (next row starts {lo})")
        expected = rows[lo][0]
    if expected != 100000:
        raise AssertionError(f"tax table parse ended at {expected}, expected 100000")
    return rows
