"""Exact currency helpers.

Money is always :class:`decimal.Decimal` inside calculations and a string in
graph state (so checkpoints stay JSON-serialisable). Binary floats are never
used as the authoritative representation of an amount.

Rounding policy (see docs/ASSUMPTIONS.md, A-12): every amount entered on the
draft return is rounded to whole dollars, half-up, as permitted by the Form
1040 instructions. When several source amounts feed one line, cents are kept
while adding and only the total is rounded.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
DOLLAR = Decimal("1")


class MoneyParseError(ValueError):
    """Raised when text cannot be read as a dollar amount."""


def parse_money(value: object) -> Decimal:
    """Parse ``value`` into a Decimal rounded to cents.

    Accepts ``"$1,234.56"``, ``"1234.5"``, ``"(12.00)"`` (negative), ints,
    and Decimals. Rejects floats to avoid silent binary rounding, and rejects
    free text such as ``"about 5k"``.
    """
    if isinstance(value, bool):
        raise MoneyParseError("booleans are not amounts")
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    if isinstance(value, int):
        return Decimal(value).quantize(CENT)
    if isinstance(value, float):
        raise MoneyParseError("floats are not accepted for money; pass a string")
    if value is None:
        raise MoneyParseError("no amount given")
    text = str(value).strip()
    if not text:
        raise MoneyParseError("no amount given")
    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.replace("$", "").replace(",", "").replace(" ", "").strip("()")
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:].lstrip("$")
    if not re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?|\.[0-9]{1,2}", cleaned):
        raise MoneyParseError(f"not a dollar amount: {text!r}")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise MoneyParseError(f"not a dollar amount: {text!r}") from exc
    if negative:
        amount = -amount
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents_str(amount: Decimal) -> str:
    return str(amount.quantize(CENT, rounding=ROUND_HALF_UP))


def round_dollar(amount: Decimal) -> Decimal:
    """Round to whole dollars, half-up (IRS whole-dollar rounding)."""
    return amount.quantize(DOLLAR, rounding=ROUND_HALF_UP)


def to_dollar_str(amount: Decimal) -> str:
    return str(round_dollar(amount))


def fmt_money(value: object, cents: bool = False) -> str:
    """Human-readable ``$12,345`` / ``$12,345.67`` for display only."""
    amount = parse_money(value) if not isinstance(value, Decimal) else value
    if cents:
        return f"${amount:,.2f}" if amount >= 0 else f"-${-amount:,.2f}"
    whole = round_dollar(amount)
    return f"${whole:,.0f}" if whole >= 0 else f"-${-whole:,.0f}"
