"""Review / Audit agent.

Adversarially checks the proposed return before any human sees it, and sends
work back instead of fixing anything itself (assignment §4):

1. Independent recomputation through the MCP ``verify_return`` tool - totals,
   6b <= 6a (and <= 85% of 6a), 3a <= 3b, 4b <= 4a, 5b <= 5a, the standard
   deduction against a literal copy of the printed chart, tax on line 15.
2. Provenance: every money line has a record, values match, and every input
   reference resolves (down to document boxes and dated answers).
3. Source re-verification: each document value used by a derived line still
   equals the published source fact (catches stale or tampered values).
4. Staleness: lines were computed from the current facts and documents.
5. Scope: the final rules check passed with nothing out of scope.
6. In live mode, a model critique looks for anything implausible. Its findings
   are advisory for the human reviewer, except "recheck_source", which sends a
   specific document back for one re-read.

Failures become issues with a target agent; the orchestrator routes them and
the bounded review cycle (MAX_REVIEW_PASSES) prevents endless loops.
"""

from __future__ import annotations

import json
from typing import Any

from src.agents.base import Runtime, flat_facts
from src.agents.eligibility_rules import source_version
from src.config import MAX_REVIEW_PASSES
from src.contracts import AgentResult, AuditCritique, Outcome
from src.hitl import make_escalation
from src.provenance import MONEY_LINES_REQUIRED, lineage_gaps

AGENT = "review_audit"

CRITIQUE_PROMPT = """You are the Review / Audit agent of SilverFile. Try to falsify this draft 2025 Form 1040-SR. Look for internal contradictions, implausible values, values that do not match their sources, and anything that looks out of scope. Report findings only; do not propose new numbers. Use severity "recheck_source" only when a specific document box looks misread (give doc_id and box); otherwise "advisory"."""

CHECK_TARGET = {
    "line16_tax": "computation", "line9_sum": "computation", "line11_agi": "computation", "line11b_copy": "computation",
    "line14_sum": "computation", "line15_floor": "computation", "line18_sum": "computation", "line22_floor": "computation",
    "line24_sum": "computation", "line25d_sum": "computation", "line33_sum": "computation", "line34_37": "computation",
    "line12e_chart": "computation", "line6b_cap": "computation", "line6b_le_6a": "computation",
    "line3a_subset": "document_extraction", "line4b_le_4a": "document_extraction", "line5b_le_5a": "document_extraction",
}


def review_node(state: dict, rt: Runtime) -> dict:
    now = rt.now()
    facts = flat_facts(state)
    fv = int(state.get("facts_version") or 0)
    lines = state.get("lines") or {}
    prov = state.get("provenance") or {}
    calc = state.get("calc") or {}
    review = dict(state.get("review") or {})
    metrics: list[dict] = []
    issues: list[dict] = []

    def issue(check: str, target: str, detail: str, lines_: list[str] | None = None, **extra: Any) -> None:
        issues.append({"id": f"{check}:{','.join(lines_ or [])}", "check": check, "target": target,
                       "detail": detail, "lines": lines_ or [], **extra})

    # 1. independent recomputation ---------------------------------------------------------
    values = {k: v["value"] for k, v in lines.items() if v.get("value") not in (None, "")}
    ver = rt.tool("verify_return", {"lines": values, "filing_status": facts.get("filing_status"),
                                    "box_count": int(calc.get("box_count") or 0)}, metrics)
    for f in ver["outputs"]["findings"]:
        issue(f["check"], CHECK_TARGET.get(f["check"], "computation"), f"Failed: {f['expected']}", f["lines"],
              tool_call=ver["call_id"])

    # 2. provenance -------------------------------------------------------------------------
    for gap in lineage_gaps(lines, prov, MONEY_LINES_REQUIRED):
        issue("provenance", "computation", gap["problem"], [gap["line"]])

    # 3. source re-verification ----------------------------------------------------------------
    sf = state.get("source_facts") or {}
    for key, rec in prov.items():
        if not key.startswith("line:"):
            continue
        for name, inp in (rec.get("inputs") or {}).items():
            for ref in inp.get("refs") or ([inp["ref"]] if inp.get("ref") else []):
                if ref.startswith("doc:") and ref in sf and str(sf[ref].get("value")) != str(prov.get(ref, {}).get("value")):
                    issue("source_mismatch", "document_extraction", f"{ref} differs from its source record",
                          [rec["line"]], doc_key=ref)
                if ref.startswith("doc:") and ref not in sf:
                    issue("source_missing", "computation", f"{ref} is no longer a usable source", [rec["line"]])

    # 4. staleness ----------------------------------------------------------------------------
    if calc.get("facts_version") != fv or calc.get("source_version") != source_version(state):
        issue("stale", "computation", "Lines were computed from older facts or documents.", [])
    stale_lines = [k for k, v in lines.items() if v.get("facts_version") != calc.get("facts_version")]
    if stale_lines:
        issue("stale_lines", "computation", "Some lines are from an earlier calculation.", stale_lines[:10])

    # 5. scope ------------------------------------------------------------------------------------
    elig = state.get("eligibility") or {}
    if elig.get("status") != "ok" or elig.get("mode") != "final" or elig.get("facts_version") != fv:
        issue("scope", "eligibility_rules", "The final rules check is not current and passing.", [])

    # 6. model critique (live mode) ---------------------------------------------------------------
    advisory: list[dict] = []
    rechecks: list[dict] = []
    if rt.llm.mode != "offline" and not issues:
        summary = {k: v["value"] for k, v in sorted(lines.items())}
        sources = {k: {"value": v.get("value"), "doc_type": v.get("doc_type"), "box": v.get("box"), "payer": v.get("payer")}
                   for k, v in sf.items() if not k.endswith(":meta")}
        body = json.dumps({"filing_status": facts.get("filing_status"), "lines": summary, "sources": sources,
                           "box_count": calc.get("box_count")}, indent=1)
        try:
            call = rt.llm.structured(agent=AGENT, system=CRITIQUE_PROMPT, schema=AuditCritique,
                                     messages=[{"role": "user", "content": body}],
                                     offline=lambda: AuditCritique(findings=[], summary=""), purpose="critique",
                                     max_tokens=2500)
            metrics.append(call.record)
            done = set(review.get("rechecked_docs") or [])
            for f in call.data.findings:
                if f.severity == "recheck_source" and f.doc_id and f.doc_id in (state.get("documents") or {}) \
                        and f.doc_id not in done:
                    rechecks.append({"doc_id": f.doc_id, "box": f.box, "concern": f.concern})
                else:
                    advisory.append(f.model_dump())
        except Exception as exc:
            advisory.append({"line": "-", "concern": f"Model critique unavailable: {type(exc).__name__}",
                             "severity": "advisory"})

    passes = int(review.get("passes") or 0)
    history = list(review.get("history") or [])
    entry = {"at": now, "facts_version": fv, "issues": issues, "rechecks": rechecks, "advisory": advisory,
             "verify_call": ver["call_id"]}
    if not issues and not rechecks:
        review.update({"status": "passed", "for_calc": calc.get("calc_id"), "passes": 0,
                       "passed_for": {"facts_version": fv, "calc": calc.get("calc_id")},
                       "advisory": advisory, "open_issues": [], "history": history + [entry]})
        return AgentResult(agent=AGENT, outcome=Outcome.SUCCESS,
                           summary=f"Audit passed ({len(ver['trace'])} checks, {len(advisory)} advisory notes).",
                           patch={"review": review, "metrics": metrics}).to_update(now)

    passes += 1
    targets = sorted({i["target"] for i in issues} | ({"document_extraction"} if rechecks else set()))
    review.update({"status": "revision_requested", "for_calc": calc.get("calc_id"), "passes": passes,
                   "open_issues": issues, "advisory": advisory,
                   "targets": targets, "history": history + [entry]})
    patch: dict[str, Any] = {"review": review, "metrics": metrics}
    if rechecks:
        docs = state.get("documents") or {}
        review["rechecked_docs"] = sorted(set(review.get("rechecked_docs") or []) | {r["doc_id"] for r in rechecks})
        patch["documents"] = {r["doc_id"]: {"status": "queued", "revision": int(docs[r["doc_id"]].get("revision", 0)) + 1}
                              for r in rechecks}
    if passes > MAX_REVIEW_PASSES:
        esc = make_escalation("review_bound",
                              f"The audit still found {len(issues) + len(rechecks)} problem(s) after "
                              f"{MAX_REVIEW_PASSES} revision passes.", raised_by=AGENT,
                              evidence=[{"type": "audit_issue", **i} for i in issues[:5]],
                              taxpayer_message=("Thank you for your patience. A Kushim volunteer needs to look at your "
                                                "draft before it is ready. Your information is saved."))
        return AgentResult(agent=AGENT, outcome=Outcome.ESCALATION,
                           summary=f"Review bound reached after {passes - 1} revision passes.",
                           patch=patch, escalation=esc).to_update(now)
    return AgentResult(agent=AGENT, outcome=Outcome.REVISION, revision_targets=targets,
                       summary=f"Audit failed (pass {passes}): {len(issues)} issue(s) -> {', '.join(targets)}.",
                       patch=patch).to_update(now)
