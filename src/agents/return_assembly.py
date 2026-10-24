"""Return Assembly & Provenance agent (the sixth functional agent).

Added deliberately: the assignment names six agents plus orchestration but
lists five functional roles; this agent owns the final "every number has a
source" gate and the official-form output (docs/ASSUMPTIONS.md A-01).

It verifies that every required line is present, current and has a complete
provenance chain, then places the values on the official 2025 Form 1040-SR
(and Schedule 1-A) through the deterministic PDF writer, checks the filled
fields logically and visually, renders previews, and exports the audit
record. It cannot recalculate or repair anything: a missing or inconsistent
line goes back to the agent that produced it.

In live mode a model drafts a short cover note for the Kushim reviewer; any
note containing a number that is not on the return is discarded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.agents.base import Runtime, flat_facts
from src.contracts import AgentResult, CoverNote, Outcome
from src.hitl import make_escalation
from src.output.pdf_writer import build_field_values, render_previews, write_draft
from src.provenance import MONEY_LINES_REQUIRED, lineage_gaps
from src.tools.tax_calculations import STATUS_LABELS

AGENT = "return_assembly"

NOTE_PROMPT = """You are the Return Assembly agent of SilverFile. Write a short cover note (at most 6 sentences) for the Kushim volunteer who will review this DRAFT Form 1040-SR: what is on it, the main sources, and anything flagged. Use only numbers given below. No advice. State clearly that nothing has been filed."""


def _template_note(facts: dict, lines: dict, review: dict) -> str:
    fs = STATUS_LABELS.get(facts.get("filing_status"), facts.get("filing_status"))
    v = {k: lines.get(k, {}).get("value", "0") for k in ["9", "11b", "15", "24", "33", "34", "37"]}
    result = (f"an overpayment of ${int(v['34']):,}" if int(v["34"]) > 0 else
              f"an amount owed of ${int(v['37']):,}" if int(v["37"]) > 0 else "no refund and nothing owed")
    adv = len(review.get("advisory") or [])
    return (f"Draft Form 1040-SR ({fs}) for {facts.get('tp.first_name', '')} {facts.get('tp.last_name', '')}. "
            f"Total income ${int(v['9']):,}; AGI ${int(v['11b']):,}; taxable income ${int(v['15']):,}; "
            f"total tax ${int(v['24']):,}; total payments ${int(v['33']):,}, giving {result}. "
            f"Every amount links to a document box, a dated answer, or an MCP tool run. "
            f"{adv} advisory audit note(s). Nothing has been filed.")


def assembly_node(state: dict, rt: Runtime) -> dict:
    now = rt.now()
    facts = flat_facts(state)
    fv = int(state.get("facts_version") or 0)
    lines = state.get("lines") or {}
    prov = state.get("provenance") or {}
    calc = state.get("calc") or {}
    review = state.get("review") or {}
    metrics: list[dict] = []

    gaps = lineage_gaps(lines, prov, MONEY_LINES_REQUIRED)
    stale = [k for k, v in lines.items() if v.get("facts_version") != fv]
    if gaps or stale:
        assembly = {"status": "gaps", "gaps": gaps, "stale": stale, "checked_at": now, "facts_version": fv,
                    "calc": calc.get("calc_id")}
        return AgentResult(agent=AGENT, outcome=Outcome.REVISION, revision_targets=["computation"],
                           summary=f"Assembly blocked: {len(gaps)} lineage gap(s), {len(stale)} stale line(s).",
                           patch={"assembly": assembly}).to_update(now)

    version = int((state.get("assembly") or {}).get("version") or 0) + 1
    out_dir = rt.settings.outputs_dir / state["case_id"]
    pdf_path = out_dir / f"draft_1040sr_v{version}.pdf"
    values = build_field_values(facts, lines, (state.get("eligibility") or {}).get("boxes") or {},
                                calc.get("schedule_1a") or {}, calc.get("box_count"))
    try:
        check = write_draft(values, pdf_path)
        previews = render_previews(pdf_path, out_dir / "previews")
    except Exception as exc:
        esc = make_escalation("system_error", f"The draft PDF could not be produced: {type(exc).__name__}: {exc}",
                              raised_by=AGENT)
        return AgentResult(agent=AGENT, outcome=Outcome.ERROR, summary="PDF writing failed.",
                           patch={"assembly": {"status": "error", "error": str(exc)[:300], "calc": calc.get("calc_id")}},
                           escalation=esc).to_update(now)
    if not (check["logical_ok"] and check["visible_ok"]):
        esc = make_escalation("system_error", "The filled PDF did not show every value it was given "
                                              f"(missing: {check['logical_missing'] + check['visible_missing']}).",
                              raised_by=AGENT)
        return AgentResult(agent=AGENT, outcome=Outcome.ERROR, summary="PDF verification failed.",
                           patch={"assembly": {"status": "error", "check": check, "calc": calc.get("calc_id")}},
                           escalation=esc).to_update(now)

    note = _template_note(facts, lines, review)
    if rt.llm.mode != "offline":
        body = json.dumps({"filing_status": facts.get("filing_status"),
                           "lines": {k: v["value"] for k, v in lines.items()},
                           "advisory": review.get("advisory") or []})
        try:
            call = rt.llm.structured(agent=AGENT, system=NOTE_PROMPT, schema=CoverNote,
                                     messages=[{"role": "user", "content": body}],
                                     offline=lambda: CoverNote(note=note), purpose="cover_note", max_tokens=800)
            metrics.append(call.record)
            allowed = {str(int(v["value"])) for v in lines.values() if str(v.get("value", "")).lstrip("-").isdigit()}
            allowed |= {f"{int(a):,}" for a in allowed} | {"2025", "1040", "1040-SR", "1-A", "1"}
            used = set(re.findall(r"\d[\d,]*", call.data.note))
            if all(u in allowed or u.replace(",", "") in allowed for u in used):
                note = call.data.note
        except Exception:
            pass

    audit_path = out_dir / f"audit_record_v{version}.json"
    audit = {"case_id": state["case_id"], "version": version, "generated_at": now, "facts_version": fv,
             "status": "DRAFT - not filed", "filing_status": facts.get("filing_status"),
             "lines": lines, "provenance": prov, "eligibility_decisions": (state.get("eligibility") or {}).get("decisions"),
             "review": {k: review.get(k) for k in ("status", "passes", "advisory", "history")},
             "human_events": state.get("human_events") or [], "pdf_check": check}
    audit_path.write_text(json.dumps(audit, indent=2, default=str))
    assembly = {"status": "ready", "version": version, "facts_version": fv, "calc": calc.get("calc_id"),
                "pdf_path": str(pdf_path),
                "audit_path": str(audit_path), "previews": previews, "pdf_check": {k: v for k, v in check.items()
                                                                                   if k != "written"},
                "fields_written": len(check["written"]), "cover_note": note, "assembled_at": now}
    return AgentResult(agent=AGENT, outcome=Outcome.SUCCESS,
                       summary=f"Draft v{version} assembled: {len(check['written'])} fields, {check['pages']} pages, "
                               "values verified logically and visually.",
                       patch={"assembly": assembly, "metrics": metrics}).to_update(now)
