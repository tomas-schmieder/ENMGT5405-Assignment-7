"""Human-review node: the LangGraph interrupt for all escalations (§4.4).

Builds a deterministic event from the pending escalation, pauses the graph
with ``interrupt``, and on resume validates and applies the reviewer decision
from the dashboard. Every decision is recorded (who, when, action, rationale,
evidence, prior and new values) and the same case/thread continues.

Replay safety: LangGraph re-executes this node from the top on resume, so
everything before ``interrupt`` is pure and the event id is a hash of its
inputs. Resolving the same event twice is impossible: the service checks the
pending event id, and the event is marked resolved in state.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from src.agents.base import Runtime, flat_facts
from src.agents.intake_script import QUESTIONS, Invalid
from src.hitl import DecisionError, build_event, validate_decision
from src.provenance import fact_key, reviewer_record

AGENT = "human_review"

CONTINUE_MESSAGE = ("A Kushim volunteer has reviewed your case. We can carry on where we left off.")
REFER_MESSAGE = ("A Kushim volunteer has reviewed your case. Because it includes something SilverFile can't handle, "
                 "a volunteer will help you directly. Your SilverFile case is now closed, and nothing has been filed.")


def _validate_fact_value(fact_id: str, value: Any) -> Any:
    for q in QUESTIONS:
        if q.fact == fact_id:
            return q.validator(str(value))
    return value


def human_review_node(state: dict, rt: Runtime) -> dict:
    esc = state.get("escalation")
    if not esc:
        return {}
    events = state.get("human_events") or []
    event = build_event(state["case_id"], esc, int(state.get("facts_version") or 0), len(events))
    decision = interrupt({"kind": "human_review", "event": event})
    now = rt.now()
    try:
        clean = validate_decision(event, decision)
    except DecisionError as exc:
        # Keep the escalation; the orchestrator will interrupt again with the same event.
        return {"trace": [{"at": now, "agent": AGENT, "outcome": "error", "summary": f"Rejected decision: {exc}"}]}

    facts = dict(state.get("facts") or {})
    fv = int(state.get("facts_version") or 0)
    patch: dict[str, Any] = {"escalation": None}
    new_facts: dict[str, dict] = {}
    provenance: dict[str, dict] = {}
    intake = dict(state.get("intake") or {})
    message = CONTINUE_MESSAGE
    change: dict[str, Any] = {}
    action = clean["action"]

    def set_fact(fact_id: str, value: Any) -> None:
        prior = facts.get(fact_id) or {}
        history = list(prior.get("history") or [])
        if prior:
            history.append({"value": prior.get("value"), "at": (prior.get("source") or {}).get("at"), "replaced_at": now})
        new_facts[fact_id] = {"value": value, "status": "confirmed", "history": history,
                              "source": {"kind": "reviewer_correction", "entered_by": clean["reviewer"], "at": now,
                                         "question_id": None, "question_text": f"Review event {event['id']}",
                                         "raw_answer": clean["rationale"]}}
        provenance[fact_key(fact_id)] = reviewer_record(key=fact_key(fact_id), prior_value=prior.get("value"),
                                                        new_value=value, reviewer=clean["reviewer"], at=now,
                                                        rationale=clean["rationale"], evidence=clean["evidence"],
                                                        event_id=event["id"])
        change.setdefault("changes", []).append({"fact": fact_id, "prior": prior.get("value"), "new": value})

    def clear(reason: str) -> None:
        cleared = list((flat_facts(state).get("review.cleared") or []))
        if reason not in cleared:
            set_fact("review.cleared", cleared + [reason])

    if action == "refer_out_of_scope":
        patch["status"] = "referred_out_of_scope"
        message = REFER_MESSAGE
    elif action == "correct_fact":
        fact_id = clean["fact_id"]
        if fact_id.startswith("doc:"):
            _, doc_id, *rest = fact_id.split(":")
            rec = dict((state.get("extractions") or {}).get(doc_id) or {})
            if not rec:
                return {"trace": [{"at": now, "agent": AGENT, "outcome": "error",
                                   "summary": f"Unknown document {doc_id}"}]}
            rec["revision"] = int(rec.get("revision", 0)) + 1
            rec["by"] = f"reviewer:{clean['reviewer']}"
            rec["issues"] = []
            if rest[:1] == ["flag"]:
                flags = dict(rec.get("flags") or {})
                prior = flags.get(rest[1])
                flags[rest[1]] = str(clean["new_value"]).strip().lower() in {"true", "yes", "1", "checked"}
                rec["flags"] = flags
                change["changes"] = [{"fact": fact_id, "prior": prior, "new": flags[rest[1]]}]
            else:
                box = rest[0]
                fields = dict(rec.get("fields") or {})
                from src.money import parse_money, to_cents_str
                prior = (fields.get(box) or {}).get("value")
                fields[box] = {**(fields.get(box) or {"label": f"Box {box}"}), "raw": str(clean["new_value"]),
                               "value": to_cents_str(parse_money(clean["new_value"])), "blank": False,
                               "readable": True, "reviewer_corrected": True}
                rec["fields"] = fields
                change["changes"] = [{"fact": fact_id, "prior": prior, "new": fields[box]["value"]}]
            patch["extractions"] = {doc_id: rec}
            patch["documents"] = {doc_id: {"status": "extracted"}}
            patch["extraction_summary"] = {**(state.get("extraction_summary") or {}), "stale": True}
            patch["provenance"] = {f"review:{event['id']}": reviewer_record(
                key=fact_id, prior_value=change["changes"][0]["prior"], new_value=change["changes"][0]["new"],
                reviewer=clean["reviewer"], at=now, rationale=clean["rationale"], evidence=clean["evidence"],
                event_id=event["id"])}
        else:
            try:
                value = _validate_fact_value(fact_id, clean["new_value"])
            except Invalid as exc:
                return {"trace": [{"at": now, "agent": AGENT, "outcome": "error", "summary": f"Invalid value: {exc}"}]}
            set_fact(fact_id, value)
    elif action == "confirm_document_value":
        set_fact("conflict.wages.resolution", "reviewer_confirmed_document")
    elif action == "note_and_continue":
        intake["notes_for_volunteer"] = list(intake.get("notes_for_volunteer") or []) + [
            {"text": f"Reviewer note ({clean['reviewer']}): {clean['rationale']}", "at": now}]
        if event["reason"] == "taxpayer_needs_help":
            clear("taxpayer_needs_help")
    elif action == "set_filing_status":
        set_fact("filing_status", clean["filing_status"])
        clear("filing_status_ambiguity")
    elif action == "cleared_continue":
        clear(event["reason"])
    elif action == "request_more_info":
        fid = f"rq-{event['id']}"
        intake["followups"] = list(intake.get("followups") or []) + [{
            "id": fid, "text": f"A Kushim volunteer asks: {clean['question']}", "kind": "text", "options": [],
            "fact": clean.get("fact_id") or f"reviewer_question.{event['id']}", "status": "open",
            "created_by": f"reviewer:{clean['reviewer']}", "created_at": now}]
        message = "A Kushim volunteer has a question for you."
    elif action == "retry_processing":
        routing = dict(state.get("routing") or {})
        routing.update(handoffs_this_run=0, signature_counts={})
        patch["routing"] = routing
        review = dict(state.get("review") or {})
        review["passes"] = 0
        patch["review"] = review

    resolved = {**event, "status": "resolved",
                "resolution": {"action": action, "reviewer": clean["reviewer"], "at": now,
                               "rationale": clean["rationale"], "evidence": clean["evidence"], **change}}
    patch["human_events"] = [resolved]
    patch["intake"] = intake
    patch["transcript"] = [{"role": "assistant", "text": message, "at": now, "source": "review"}]
    if new_facts:
        patch["facts"] = new_facts
        patch["facts_version"] = fv + 1
        patch["provenance"] = {**patch.get("provenance", {}), **provenance}
    patch["trace"] = [{"at": now, "agent": AGENT, "outcome": "success",
                       "summary": f"Reviewer {clean['reviewer']} resolved {event['reason']} with {action}."}]
    return patch
