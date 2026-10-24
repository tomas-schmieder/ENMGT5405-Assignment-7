"""Orchestrator: decides which agent acts next and owns termination.

The orchestrator never extracts, computes, or converses. Its routing policy is
deterministic code over the shared state, so every hop is explainable and
termination is guaranteed (docs/IMPLEMENTATION_NOTES.md, "Why a rule-based
orchestrator"). The next hop depends on state, not on a fixed sequence:

  pending escalation        -> human_review (LangGraph interrupt)
  queued documents          -> parallel extract_document x N (Send) -> aggregate
  stale rules check         -> rules
  open question / follow-up -> intake (interrupt for the taxpayer)
  stale calculation         -> computation
  audit not passed          -> review, or the agent the audit sent work back to
  draft not assembled       -> assembly
  everything current        -> intake asks whether to submit; then END

Loop guard (assignment §4.1): every automated hand-off is counted per
processing run (reset whenever a person answers). A run is stopped and
escalated when it exceeds MAX_HANDOFFS_PER_RUN, or when the same routing
signature (next agent, open issues, facts version, calculation, sources)
repeats MAX_SIGNATURE_REPEATS times - i.e. agents are passing work back and
forth without progress. Waiting for a human never consumes the budget.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Send

from src.agents.base import Runtime
from src.agents.eligibility_rules import source_version
from src.agents.intake import next_step
from src.config import MAX_HANDOFFS_PER_RUN, MAX_SIGNATURE_REPEATS
from src.hitl import make_escalation
from src.state import TERMINAL_STATUSES

AGENT = "orchestrator"
NODES = ["intake", "extract", "aggregate_extractions", "rules", "computation", "review", "assembly",
         "human_review", "end"]


def _human_marker(state: dict) -> int:
    """Changes whenever a person (taxpayer or reviewer) has provided input."""
    users = sum(1 for t in state.get("transcript") or [] if t.get("role") == "user")
    resolved = sum(1 for e in state.get("human_events") or [] if e.get("status") == "resolved")
    return users * 1000 + resolved


def decide(state: dict) -> tuple[str, str]:
    """Pure routing policy: (next node, reason)."""
    status = state.get("status")
    if status in TERMINAL_STATUSES:
        return "end", f"case is {status}"
    if state.get("escalation"):
        return "human_review", f"escalation requested: {state['escalation']['reason']}"
    docs = state.get("documents") or {}
    if any(d.get("status") in {"queued", "extracting"} for d in docs.values()):
        return "extract", "documents waiting to be read"
    if (state.get("extraction_summary") or {}).get("stale"):
        return "aggregate_extractions", "a reviewer corrected a document record"
    intake = state.get("intake") or {}
    fv = int(state.get("facts_version") or 0)
    sv = source_version(state)
    elig = state.get("eligibility") or {}
    rules_mode_should_be_final = bool(intake.get("complete")) and next_step(state) is None
    if (elig.get("facts_version") != fv or elig.get("source_version") != sv
            or (rules_mode_should_be_final and elig.get("mode") != "final")):
        return "rules", "facts or documents changed since the last rules check"
    step = next_step(state)
    if step is not None and step.get("question_id") != "submit_draft":
        return "intake", f"need taxpayer input ({step.get('question_id')})"
    if not intake.get("complete"):
        return "intake", "intake not yet marked complete"
    if elig.get("status") != "ok":
        return "rules", f"rules status is {elig.get('status')}"
    calc = state.get("calc") or {}
    if calc.get("facts_version") != fv or calc.get("source_version") != sv:
        return "computation", "calculation is stale"
    review = state.get("review") or {}
    if review.get("for_calc") != calc.get("calc_id"):
        return "review", "new calculation needs an audit"
    if review.get("status") == "revision_requested":
        target = (review.get("targets") or ["computation"])[0]
        node = {"document_extraction": "extract", "eligibility_rules": "rules"}.get(target, target)
        if node == "extract" and not any(d.get("status") == "queued" for d in docs.values()):
            node = "computation"
        return node, f"audit sent work back to {target}"
    assembly = state.get("assembly") or {}
    if assembly.get("status") == "gaps" and assembly.get("calc") == calc.get("calc_id"):
        return "computation", "assembly found lineage gaps"
    if assembly.get("status") != "ready" or assembly.get("calc") != calc.get("calc_id"):
        return "assembly", "draft not yet assembled for this calculation"
    if intake.get("submitted"):
        return "end", "submitted internally for human review"
    return "intake", "draft ready; ask the taxpayer whether to submit it for Kushim review"


def orchestrator_node(state: dict, rt: Runtime) -> dict:
    now = rt.now()
    routing = dict(state.get("routing") or {})
    marker = _human_marker(state)
    if routing.get("marker") != marker:
        routing.update(handoffs_this_run=0, signature_counts={}, marker=marker, run=int(routing.get("run") or 0) + 1)
    nxt, reason = decide(state)
    update: dict[str, Any] = {}

    # status shown on the dashboard
    status = state.get("status")
    if nxt == "end":
        if (state.get("intake") or {}).get("submitted") and status not in TERMINAL_STATUSES:
            status = "submitted_for_internal_review"
    elif nxt == "human_review":
        status = "needs_human_review"
    elif nxt == "intake":
        step = next_step(state)
        if step and step.get("question_id") == "submit_draft":
            status = "draft_ready"
        elif step and step.get("kind") == "upload":
            status = "awaiting_documents"
        else:
            status = "intake"
    else:
        status = "revising" if (state.get("review") or {}).get("status") == "revision_requested" else "processing"
    update["status"] = status

    if nxt not in {"end", "human_review", "intake"}:
        routing["handoffs_this_run"] = int(routing.get("handoffs_this_run") or 0) + 1
        review = state.get("review") or {}
        sig = "|".join([nxt, ",".join(sorted(i["id"] for i in review.get("open_issues") or [])),
                        str(state.get("facts_version")), str((state.get("calc") or {}).get("calc_id")),
                        source_version(state), str((state.get("eligibility") or {}).get("status"))])
        counts = dict(routing.get("signature_counts") or {})
        counts[sig] = counts.get(sig, 0) + 1
        routing["signature_counts"] = counts
        tripped = None
        if routing["handoffs_this_run"] > MAX_HANDOFFS_PER_RUN:
            tripped = f"more than {MAX_HANDOFFS_PER_RUN} automatic hand-offs without human input"
        elif counts[sig] >= MAX_SIGNATURE_REPEATS:
            tripped = f"the same hand-off to '{nxt}' repeated {counts[sig]} times with no progress"
        if tripped:
            history = (routing.get("history") or [])[-10:]
            update["escalation"] = make_escalation(
                "loop_guard", f"Loop guard stopped automatic processing: {tripped}.", raised_by=AGENT,
                evidence=[{"type": "routing_history", "hops": history}],
                details={"signature": sig, "handoffs_this_run": routing["handoffs_this_run"]},
                taxpayer_message=("Thank you for your patience. Something needs a person's attention, so a Kushim "
                                  "volunteer will look at your case. Your information is saved."))
            nxt, reason = "human_review", f"loop guard: {tripped}"
            update["status"] = "needs_human_review"

    if nxt == "extract":
        docs = state.get("documents") or {}
        update["documents"] = {d: {"status": "extracting"} for d, rec in docs.items() if rec.get("status") == "queued"}
    hop = {"at": now, "next": nxt, "reason": reason, "run": routing.get("run")}
    routing["history"] = (list(routing.get("history") or []) + [hop])[-60:]
    routing["next"] = nxt
    update["routing"] = routing
    update["trace"] = [{"at": now, "agent": AGENT, "outcome": "route", "summary": f"-> {nxt}: {reason}"}]
    return update


def route(state: dict):
    """Conditional edge: the orchestrator's decision, or a parallel fan-out."""
    nxt = (state.get("routing") or {}).get("next", "end")
    if nxt == "extract":
        docs = state.get("documents") or {}
        sends = [Send("extract_document", {"doc": {**rec, "doc_id": doc_id}, "case_id": state.get("case_id")})
                 for doc_id, rec in sorted(docs.items()) if rec.get("status") == "extracting"]
        return sends or "aggregate_extractions"
    return nxt
