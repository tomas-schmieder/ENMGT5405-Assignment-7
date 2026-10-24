"""Computation agent.

Populates every derived line by calling the deterministic MCP tax tools. It
never does arithmetic itself: inputs are gathered from validated state (source
document facts and confirmed direct inputs) and every number written to a line
is copied from an MCP tool result, together with a provenance record that
names the tool, its call id, its inputs (by provenance key) and its trace.

Dependency order (R-SS-02): source aggregates (1z, 2a/2b, 3a/3b, 4a/4b, 5a/5b,
8, 25a/25b) -> taxable Social Security (6b) -> total income (9) -> AGI (11a/b)
-> standard deduction (12e) -> enhanced senior deduction (13b, needs 11b)
-> 14/15 -> tax (16) -> total tax (24) -> payments (33) -> refund/owed (34/37).

In live mode a model writes a plain-language explanation for each line from
the tool trace. Explanations that contain any number not present in the
trace are discarded.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from src.agents.base import Runtime, flat_facts
from src.agents.eligibility_rules import source_version, usable_docs
from src.contracts import AgentResult, LineExplanations, Outcome
from src.provenance import derived_record, fact_key

AGENT = "computation"

EXPLAIN_PROMPT = """You are the Computation agent of SilverFile. For each form line below, write one or two plain-language sentences explaining how the amount was worked out, for a Kushim reviewer. Use ONLY numbers that appear in that line's trace. Do not add advice or new calculations."""


def _fact_amount(facts: dict, fact_id: str) -> str | None:
    v = facts.get(fact_id)
    return None if v in (None, "") else str(v)


def computation_node(state: dict, rt: Runtime) -> dict:
    now = rt.now()
    facts = flat_facts(state)
    fv = int(state.get("facts_version") or 0)
    fs = facts["filing_status"]
    boxes = (state.get("eligibility") or {}).get("boxes") or {}
    metrics: list[dict] = []
    lines: dict[str, dict] = {}
    prov: dict[str, dict] = {}
    calls: list[str] = []

    def call(tool: str, args: dict) -> dict:
        res = rt.tool(tool, args, metrics)
        calls.append(res["call_id"])
        return res

    def put(line: str, result: dict, inputs: dict[str, dict], out_key: str | None = None) -> str:
        value = str(result["outputs"][out_key or line])
        lines[line] = {"value": value, "calc_id": result["call_id"], "facts_version": fv, "status": "current"}
        prov[f"line:{line}"] = derived_record(line=line, value=value, tool_result=result, inputs=inputs,
                                              facts_version=fv, computed_at=now)
        return value

    def ref_line(line: str) -> dict:
        return {"value": lines[line]["value"], "ref": f"line:{line}"}

    def aggregate(line: str, items: list[tuple[str, str]], none_ref: str | None, none_note: str) -> str:
        """Sum source items (key, amount) into a line through the MCP tool."""
        res = call("aggregate_amounts", {"line": line, "items": [{"source_id": k, "amount": a} for k, a in items]})
        if items:
            inputs = {"items": {"value": [a for _, a in items], "refs": [k for k, _ in items]}}
        else:
            res = dict(res)
            res["trace"] = [none_note]
            inputs = {"confirmed_none": {"value": "0", "ref": none_ref}} if none_ref else {}
        return put(line, res, inputs)

    def doc_items(doc_type: str, boxes_: list[str], pred=lambda r: True) -> list[tuple[str, str]]:
        out = []
        for rec in usable_docs(state, doc_type):
            if not pred(rec):
                continue
            for b in boxes_:
                f = (rec.get("fields") or {}).get(b)
                if f and f.get("value") not in (None, "0.00"):
                    out.append((f"doc:{rec['doc_id']}:{b}", f["value"]))
        return out

    def direct(line: str, fact_id: str, gate_fact: str, label: str) -> str:
        """A line that is a confirmed direct input (or confirmed none)."""
        amount = _fact_amount(facts, fact_id)
        if amount is not None and facts.get(gate_fact) is not False:
            return aggregate(line, [(fact_key(fact_id), amount)], None, "")
        return aggregate(line, [], fact_key(gate_fact), f"Taxpayer confirmed no {label} (direct input).")

    is_ira = lambda r: bool((r.get("flags") or {}).get("ira_sep_simple"))  # noqa: E731
    not_ira = lambda r: not is_ira(r)  # noqa: E731

    # 1. source aggregates ------------------------------------------------------------
    w2_gate = fact_key("docs.w2.count")
    aggregate("1a", doc_items("W-2", ["1"]), w2_gate, "No Form W-2 reported (taxpayer confirmed 0 W-2s).")
    put("1z", {**_copy_result(prov["line:1a"], "1z")}, {"line_1a": ref_line("1a")})
    aggregate("2a", doc_items("1099-INT", ["8"]) + doc_items("1099-DIV", ["12"]), fact_key("docs.1099int.count"),
              "No tax-exempt interest on any Form 1099-INT or 1099-DIV.")
    aggregate("2b", doc_items("1099-INT", ["1", "3"]), fact_key("docs.1099int.count"),
              "No taxable interest (no Form 1099-INT amounts).")
    aggregate("3a", doc_items("1099-DIV", ["1b"]), fact_key("docs.1099div.count"),
              "No qualified dividends (no Form 1099-DIV amounts).")
    aggregate("3b", doc_items("1099-DIV", ["1a"]), fact_key("docs.1099div.count"),
              "No ordinary dividends (no Form 1099-DIV amounts).")
    ira_gross = doc_items("1099-R", ["1"], is_ira)
    ira_taxable = doc_items("1099-R", ["2a"], is_ira)
    qcd = _fact_amount(facts, "qcd.amount") if facts.get("qcd.any") is True else None
    ira = call("ira_distributions", {"gross_items": [{"source_id": k, "amount": a} for k, a in ira_gross],
                                     "taxable_items": [{"source_id": k, "amount": a} for k, a in ira_taxable],
                                     "qcd_amount": qcd or "0"})
    ira_inputs = {"gross": {"value": [a for _, a in ira_gross], "refs": [k for k, _ in ira_gross]},
                  "taxable": {"value": [a for _, a in ira_taxable], "refs": [k for k, _ in ira_taxable]}}
    if not ira_gross:
        ira_inputs = {"confirmed_none": {"value": "0", "ref": fact_key("docs.1099r.count")}}
    if qcd:
        ira_inputs["qcd_amount"] = {"value": qcd, "ref": fact_key("qcd.amount")}
    put("4a", ira, ira_inputs)
    put("4b", ira, ira_inputs)
    aggregate("5a", doc_items("1099-R", ["1"], not_ira), fact_key("docs.1099r.count"), "No pension or annuity Form 1099-R.")
    aggregate("5b", doc_items("1099-R", ["2a"], not_ira), fact_key("docs.1099r.count"), "No pension or annuity Form 1099-R.")
    aggregate("7a", [], fact_key("other_income.any"),
              "No capital gains: the taxpayer confirmed no other income and no capital gain distributions were found "
              "(capital gains are out of scope and would have been escalated).")
    direct("8", "s1.l10", "sched.any", "Schedule 1 additional income")
    direct("10", "s1.l26", "sched.any", "Schedule 1 adjustments")
    w_items = (doc_items("W-2", ["2"]))
    aggregate("25a", w_items, w2_gate, "No federal income tax withheld on any Form W-2.")
    b_items = (doc_items("1099-INT", ["4"]) + doc_items("1099-DIV", ["4"]) + doc_items("1099-R", ["4"])
               + doc_items("SSA-1099", ["6"]))
    aggregate("25b", b_items, fact_key("docs.ssa1099.count"),
              "No federal income tax withheld on any Form 1099 or SSA-1099.")
    aggregate("25c", [], None, "No other withholding forms are in SilverFile's scope (W-2G, 8959, K-1, 1042-S); "
                               "line 25c is $0 (rule R-WH-01).")

    # 2. Social Security (after every other income line) -------------------------------------
    ssa = doc_items("SSA-1099", ["5"])
    ssa_total = call("aggregate_amounts", {"line": "6a_box5_total",
                                          "items": [{"source_id": k, "amount": a} for k, a in ssa]})
    s1_26 = _fact_amount(facts, "s1.l26") if facts.get("sched.any") else None
    s1_21 = _fact_amount(facts, "s1.l21") if facts.get("sched.any") and s1_26 not in (None, "0.00") else None
    ss = call("taxable_social_security", {
        "filing_status": fs, "benefits_box5": ssa_total["exact_total"],
        "line_1z": lines["1z"]["value"], "line_2b": lines["2b"]["value"], "line_3b": lines["3b"]["value"],
        "line_4b": lines["4b"]["value"], "line_5b": lines["5b"]["value"], "line_7a": lines["7a"]["value"],
        "line_8": lines["8"]["value"], "line_2a": lines["2a"]["value"],
        "schedule1_line26": s1_26 or "0", "schedule1_line21": s1_21 or "0",
        "mfs_lived_apart_all_year": bool(facts.get("mfs.lived_apart"))})
    ss_inputs = {"benefits_box5": {"value": [a for _, a in ssa], "refs": [k for k, _ in ssa]} if ssa else
                 {"value": "0", "ref": fact_key("docs.ssa1099.count")},
                 **{f"line_{x}": ref_line(x) for x in ["1z", "2b", "3b", "4b", "5b", "7a", "8", "2a"]},
                 "filing_status": {"value": fs, "ref": fact_key("filing_status")}}
    if s1_26:
        ss_inputs["schedule1_line26"] = {"value": s1_26, "ref": fact_key("s1.l26")}
    if s1_21:
        ss_inputs["schedule1_line21"] = {"value": s1_21, "ref": fact_key("s1.l21")}
    if fs == "mfs":
        ss_inputs["lived_apart"] = {"value": facts.get("mfs.lived_apart"), "ref": fact_key("mfs.lived_apart")}
    put("6a", ss, ss_inputs)
    put("6b", ss, ss_inputs)

    # 3. totals and AGI -------------------------------------------------------------------
    ti = call("total_income", {f"line_{x}": lines[x]["value"] for x in ["1z", "2b", "3b", "4b", "5b", "6b", "7a", "8"]})
    put("9", ti, {f"line_{x}": ref_line(x) for x in ["1z", "2b", "3b", "4b", "5b", "6b", "7a", "8"]})
    agi = call("adjusted_gross_income", {"line_9": lines["9"]["value"], "line_10": lines["10"]["value"]})
    agi_in = {"line_9": ref_line("9"), "line_10": ref_line("10")}
    put("11a", agi, agi_in)
    put("11b", agi, {"line_11a": ref_line("11a")})

    # 4. deductions ------------------------------------------------------------------------
    sd = call("standard_deduction", {
        "filing_status": fs, "taxpayer_65_or_older": bool(boxes.get("tp_65")), "taxpayer_blind": bool(boxes.get("tp_blind")),
        "spouse_65_or_older": bool(boxes.get("sp_65")), "spouse_blind": bool(boxes.get("sp_blind")),
        "can_be_claimed_as_dependent": bool(facts.get("tp.claimable_dependent") or facts.get("sp.claimable_dependent")),
        "spouse_itemizes_separately": bool(facts.get("mfs.spouse_itemizes")),
        "dual_status_alien": facts.get("us_resident_all_year") is False})
    if sd.get("exception"):
        raise ValueError("Standard deduction exception reached computation; rules should have escalated.")
    sd_in = {"filing_status": {"value": fs, "ref": fact_key("filing_status")},
             "taxpayer_dob": {"value": facts.get("tp.dob"), "ref": fact_key("tp.dob")},
             "taxpayer_blind": {"value": facts.get("tp.blind"), "ref": fact_key("tp.blind")}}
    if boxes.get("sp_65") or boxes.get("sp_blind") or fs == "mfj":
        sd_in["spouse_dob"] = {"value": facts.get("sp.dob"), "ref": fact_key("sp.dob")}
        sd_in["spouse_blind"] = {"value": facts.get("sp.blind"), "ref": fact_key("sp.blind")}
    put("12e", sd, sd_in)
    esd = call("enhanced_senior_deduction", {"filing_status": fs, "magi": lines["11b"]["value"],
                                             "taxpayer_qualifies": bool(boxes.get("tp_senior_deduction")),
                                             "spouse_qualifies": bool(boxes.get("sp_senior_deduction"))})
    esd_in = {"magi_line_11b": ref_line("11b"), "taxpayer_dob": {"value": facts.get("tp.dob"), "ref": fact_key("tp.dob")},
              "filing_status": {"value": fs, "ref": fact_key("filing_status")}}
    if fs == "mfj":
        esd_in["spouse_dob"] = {"value": facts.get("sp.dob"), "ref": fact_key("sp.dob")}
    put("13b", esd, esd_in)
    schedule_1a = {k: v for k, v in esd["outputs"].items() if k.startswith("sch1a_")}
    zero13a = call("aggregate_amounts", {"line": "13a", "items": []})
    zero13a = {**zero13a, "trace": ["Qualified business income deduction is out of scope; line 13a is $0."]}
    put("13a", zero13a, {})
    dti = call("deductions_and_taxable_income", {"line_11b": lines["11b"]["value"], "line_12e": lines["12e"]["value"],
                                                 "line_13a": lines["13a"]["value"], "line_13b": lines["13b"]["value"]})
    put("14", dti, {"line_12e": ref_line("12e"), "line_13a": ref_line("13a"), "line_13b": ref_line("13b")})
    put("15", dti, {"line_11b": ref_line("11b"), "line_14": ref_line("14")})

    # 5. tax ----------------------------------------------------------------------------------
    tax = call("income_tax", {"filing_status": fs, "taxable_income": lines["15"]["value"],
                              "qualified_dividends": lines["3a"]["value"], "capital_gain_7a": lines["7a"]["value"]})
    put("16", tax, {"line_15": ref_line("15"), "line_3a": ref_line("3a"),
                    "filing_status": {"value": fs, "ref": fact_key("filing_status")}})
    if rt.settings.fault_injection and _should_inject(state, rt.settings.fault_injection):
        bad = str(int(lines["16"]["value"]) + 100)
        lines["16"]["value"] = bad
        prov["line:16"]["value"] = bad
        prov["line:16"]["trace"] = prov["line:16"]["trace"] + ["[FAULT INJECTION: +$100 added for testing]"]
    direct("17", "s2.l3", "sched.any", "Schedule 2 line 3 amount")
    direct("19", "line19.amount", "dependents.any", "credit for dependents")
    direct("20", "s3.l8", "sched.any", "Schedule 3 line 8 amount")
    direct("23", "s2.l21", "sched.any", "Schedule 2 line 21 amount")
    tt = call("total_tax", {"line_16": lines["16"]["value"], "schedule2_line3": lines["17"]["value"],
                            "line_19": lines["19"]["value"], "schedule3_line8": lines["20"]["value"],
                            "schedule2_line21": lines["23"]["value"]})
    put("18", tt, {"line_16": ref_line("16"), "line_17": ref_line("17")})
    put("21", tt, {"line_19": ref_line("19"), "line_20": ref_line("20")})
    put("22", tt, {"line_18": ref_line("18"), "line_21": ref_line("21")})
    put("24", tt, {"line_22": ref_line("22"), "line_23": ref_line("23")})

    # 6. payments and result -------------------------------------------------------------------
    direct("26", "est.amount", "est.any", "estimated tax payments")
    direct("31", "s3.l15", "sched.any", "Schedule 3 line 15 amount")
    pay = call("total_payments", {"line_25a": lines["25a"]["value"], "line_25b": lines["25b"]["value"],
                                  "line_25c": lines["25c"]["value"], "line_26": lines["26"]["value"],
                                  "schedule3_line15": lines["31"]["value"]})
    put("25d", pay, {"line_25a": ref_line("25a"), "line_25b": ref_line("25b"), "line_25c": ref_line("25c")})
    put("32", pay, {"line_31": ref_line("31")})
    put("33", pay, {"line_25d": ref_line("25d"), "line_26": ref_line("26"), "line_32": ref_line("32")})
    res = call("refund_or_amount_owed", {"line_24": lines["24"]["value"], "line_33": lines["33"]["value"]})
    io = {"line_24": ref_line("24"), "line_33": ref_line("33")}
    put("34", res, io)
    put("35a", res, {"line_34": ref_line("34")})
    put("37", res, io)

    _explain(prov, rt, metrics)
    runs = int((state.get("calc") or {}).get("runs") or 0) + 1
    calc = {"calc_id": f"calc-{runs}-{uuid.uuid4().hex[:6]}", "facts_version": fv,
            "source_version": source_version(state), "status": "current", "computed_at": now,
            "tool_calls": calls, "schedule_1a": schedule_1a, "box_count": sd["outputs"]["12d_box_count"],
            "tax_method": tax.get("method"), "ss_worksheet": ss.get("worksheet"),
            "fault_applied": bool(rt.settings.fault_injection) and _should_inject(state, rt.settings.fault_injection),
            "runs": runs}
    patch: dict[str, Any] = {"lines": lines, "provenance": prov, "calc": calc, "metrics": metrics}
    return AgentResult(agent=AGENT, outcome=Outcome.SUCCESS,
                       summary=f"Computed {len(lines)} lines with {len(calls)} MCP tool calls.",
                       patch=patch).to_update(now)


def _copy_result(record: dict, line: str) -> dict:
    """Line 1z repeats 1a (lines 1b-1h are not used); reuse 1a's tool run."""
    return {"tool": record["tool"], "version": record["tool_version"], "call_id": record["call_id"],
            "transport": record.get("transport"), "called_at": record.get("called_at"),
            "outputs": {line: record["value"]}, "trace": ["Line 1z = line 1a (lines 1b-1h are not used by SilverFile)."],
            "rule_ids": ["R-W2-01"]}


def _should_inject(state: dict, mode: str) -> bool:
    runs = int((state.get("calc") or {}).get("runs") or 0)
    if mode == "line16_once":
        return runs == 0
    return mode == "line16_always"


def _explain(prov: dict, rt: Runtime, metrics: list) -> None:
    """Optional model-written explanations (live mode only), number-checked."""
    if rt.llm.mode == "offline":
        return
    keys = [k for k in prov if k.startswith("line:")]
    body = "\n\n".join(f"{k[5:]}: value {prov[k]['value']}\nTRACE: " + " | ".join(prov[k]["trace"]) for k in keys)
    try:
        call = rt.llm.structured(agent=AGENT, system=EXPLAIN_PROMPT, schema=LineExplanations,
                                 messages=[{"role": "user", "content": body}],
                                 offline=lambda: LineExplanations(explanations=[]), purpose="explain_lines",
                                 max_tokens=6000)
        metrics.append(call.record)
    except Exception:
        return
    for exp in call.data.explanations:
        key = f"line:{exp.line}"
        if key not in prov:
            continue
        allowed = set(re.findall(r"\d[\d,]*(?:\.\d+)?", " ".join(prov[key]["trace"]) + " " + str(prov[key]["value"])))
        allowed |= {a.replace(",", "") for a in allowed}
        used = set(re.findall(r"\d[\d,]*(?:\.\d+)?", exp.text))
        if all(u in allowed or u.replace(",", "") in allowed or len(u) <= 2 for u in used):
            prov[key]["explanation"] = exp.text
