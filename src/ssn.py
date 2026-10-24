"""Fictional Social Security number handling (classroom security rule).

Assignment §3.2: the system may ONLY accept SSNs in the 900-999 test series,
so that a real SSN is never captured by accident. This module is the single
place that rule lives. It is a classroom constraint, not a statement about
which real SSNs are valid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Any 9-digit group that looks like an SSN, with or without separators.
SSN_LIKE = re.compile(r"(?<!\d)(\d{3})[-\s.]?(\d{2})[-\s.]?(\d{4})(?!\d)")


@dataclass(frozen=True)
class SSNCheck:
    ok: bool
    normalized: str | None
    reason: str


def validate_fictional_ssn(text: str) -> SSNCheck:
    """Validate and normalise a user-entered SSN.

    Returns ``normalized`` as ``"9XX-XX-XXXX"`` only when the number is nine
    digits with a 900-999 prefix. The rejected value is never echoed back in
    ``reason`` so it cannot leak into logs or transcripts.
    """
    if text is None:
        return SSNCheck(False, None, "No number was entered.")
    digits = re.sub(r"[\s\-.]", "", str(text).strip())
    if not digits.isdigit() or len(digits) != 9:
        return SSNCheck(False, None, "A Social Security number has exactly nine digits.")
    prefix = int(digits[:3])
    if not 900 <= prefix <= 999:
        return SSNCheck(
            False,
            None,
            "For this classroom demo SilverFile only accepts test numbers that start "
            "with 900 to 999 (for example 900-12-3456). This protects you from "
            "typing in a real Social Security number.",
        )
    return SSNCheck(True, f"{digits[:3]}-{digits[3:5]}-{digits[5:]}", "ok")


def mask_ssn(ssn: str | None) -> str:
    if not ssn:
        return ""
    digits = re.sub(r"\D", "", ssn)
    return f"XXX-XX-{digits[-4:]}" if len(digits) >= 4 else "XXX-XX-XXXX"


def redact_ssns(text: str) -> tuple[str, int]:
    """Replace every SSN-like number in ``text`` with a placeholder.

    Used before any free text is stored in the transcript or sent to a model
    when an SSN was not requested (assignment §4.3, "no unnecessary PII").
    """
    count = 0

    def _sub(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "[number removed for privacy]"

    return SSN_LIKE.sub(_sub, text or ""), count
