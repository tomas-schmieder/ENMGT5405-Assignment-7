"""SilverFile deterministic tax-tool MCP server (stdio transport).

The Computation, Rules and Review agents obtain every derived dollar amount
by calling these tools through an MCP client session (see
``src/tools/mcp_client.py``). The tools wrap the pure functions in
``src/tools/tax_calculations.py`` and stamp each response with a unique
``call_id`` so provenance records can cite the exact tool run.

Run directly for debugging:  ``python -m mcp_server.server``
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # allow ``python mcp_server/server.py``
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from src.tools import tax_calculations as tc  # noqa: E402

server = MCPServer(
    name="silverfile-tax-tools",
    instructions=(
        "Deterministic 2025 Form 1040-SR calculations. Every monetary result in a "
        "SilverFile draft must come from one of these tools."
    ),
    version=tc.TOOL_VERSION,
)


def _run(compute) -> dict:
    """Run a calculation; anticipated input problems reach the client as ToolError text."""
    try:
        result = compute()
    except tc.ToolInputError as exc:
        raise ToolError(str(exc)) from exc
    return _stamp(result)


def _stamp(result: dict) -> dict:
    result["call_id"] = f"mcp-{uuid.uuid4().hex[:12]}"
    result["called_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["transport"] = "mcp-stdio"
    return result


@server.tool(description="Sum source document amounts for one form line (cents kept, total rounded). Rejects duplicate source ids.")
def aggregate_amounts(line: str, items: list[dict[str, str]]) -> dict[str, Any]:
    return _run(lambda: tc.aggregate_amounts(line, items))


@server.tool(description="Compare a taxpayer-stated amount with a document amount and report whether the difference is material.")
def compare_amounts(label: str, document_amount: str, stated_amount: str,
                    abs_tolerance: str = "1000", rel_tolerance: str = "0.10") -> dict[str, Any]:
    return _run(lambda: tc.compare_amounts(label, document_amount, stated_amount, abs_tolerance, rel_tolerance))


@server.tool(description="Social Security Benefits Worksheet (lines 6a/6b). Needs every other income line first.")
def taxable_social_security(filing_status: str, benefits_box5: str, line_1z: str, line_2b: str,
                            line_3b: str, line_4b: str, line_5b: str, line_7a: str, line_8: str,
                            line_2a: str, schedule1_line26: str, schedule1_line21: str,
                            mfs_lived_apart_all_year: bool = False) -> dict[str, Any]:
    return _run(lambda: tc.taxable_social_security(filing_status, benefits_box5, line_1z, line_2b, line_3b,
                                                   line_4b, line_5b, line_7a, line_8, line_2a,
                                                   schedule1_line26, schedule1_line21, mfs_lived_apart_all_year))


@server.tool(description="Lines 4a/4b IRA distributions, less any qualified charitable distribution.")
def ira_distributions(gross_items: list[dict[str, str]], taxable_items: list[dict[str, str]],
                      qcd_amount: str = "0") -> dict[str, Any]:
    return _run(lambda: tc.ira_distributions(gross_items, taxable_items, qcd_amount))


@server.tool(description="Line 9 total income.")
def total_income(line_1z: str, line_2b: str, line_3b: str, line_4b: str, line_5b: str,
                 line_6b: str, line_7a: str, line_8: str) -> dict[str, Any]:
    return _run(lambda: tc.total_income(line_1z, line_2b, line_3b, line_4b, line_5b, line_6b, line_7a, line_8))


@server.tool(description="Lines 11a/11b adjusted gross income.")
def adjusted_gross_income(line_9: str, line_10: str) -> dict[str, Any]:
    return _run(lambda: tc.adjusted_gross_income(line_9, line_10))


@server.tool(description="Line 12d box count and line 12e standard deduction from the Standard Deduction Chart.")
def standard_deduction(filing_status: str, taxpayer_65_or_older: bool, taxpayer_blind: bool,
                       spouse_65_or_older: bool, spouse_blind: bool, can_be_claimed_as_dependent: bool,
                       spouse_itemizes_separately: bool, dual_status_alien: bool) -> dict[str, Any]:
    return _run(lambda: tc.standard_deduction(filing_status, taxpayer_65_or_older, taxpayer_blind,
                                        spouse_65_or_older, spouse_blind, can_be_claimed_as_dependent,
                                        spouse_itemizes_separately, dual_status_alien))


@server.tool(description="Schedule 1-A Part V enhanced deduction for seniors, carried to line 13b.")
def enhanced_senior_deduction(filing_status: str, magi: str, taxpayer_qualifies: bool,
                              spouse_qualifies: bool) -> dict[str, Any]:
    return _run(lambda: tc.enhanced_senior_deduction(filing_status, magi, taxpayer_qualifies, spouse_qualifies))


@server.tool(description="Line 14 total deductions and line 15 taxable income.")
def deductions_and_taxable_income(line_11b: str, line_12e: str, line_13a: str, line_13b: str) -> dict[str, Any]:
    return _run(lambda: tc.deductions_and_taxable_income(line_11b, line_12e, line_13a, line_13b))


@server.tool(description="Line 16 tax (Tax Table, Tax Computation Worksheet, or Qualified Dividends worksheet).")
def income_tax(filing_status: str, taxable_income: str, qualified_dividends: str,
               capital_gain_7a: str = "0") -> dict[str, Any]:
    return _run(lambda: tc.income_tax(filing_status, taxable_income, qualified_dividends, capital_gain_7a))


@server.tool(description="Lines 17-24 total tax, using direct Schedule 2/3 inputs.")
def total_tax(line_16: str, schedule2_line3: str, line_19: str, schedule3_line8: str,
              schedule2_line21: str) -> dict[str, Any]:
    return _run(lambda: tc.total_tax(line_16, schedule2_line3, line_19, schedule3_line8, schedule2_line21))


@server.tool(description="Lines 25d, 31-33 total payments.")
def total_payments(line_25a: str, line_25b: str, line_25c: str, line_26: str,
                   schedule3_line15: str) -> dict[str, Any]:
    return _run(lambda: tc.total_payments(line_25a, line_25b, line_25c, line_26, schedule3_line15))


@server.tool(description="Lines 34/35a/37 overpayment or amount owed.")
def refund_or_amount_owed(line_24: str, line_33: str) -> dict[str, Any]:
    return _run(lambda: tc.refund_or_amount_owed(line_24, line_33))


@server.tool(description="Independent consistency checks over a proposed return, for the audit agent.")
def verify_return(lines: dict[str, str], filing_status: str, box_count: int) -> dict[str, Any]:
    return _run(lambda: tc.verify_return(lines, filing_status, box_count))


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
