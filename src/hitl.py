"""Human-in-the-loop escalation: reason codes, event payloads and the
reviewer actions each reason allows.

An agent never pauses the graph itself. It returns an *escalation request*;
the orchestrator routes to the ``human_review`` node, which raises a real
LangGraph ``interrupt`` with the event below. The dashboard resumes the graph
with a reviewer decision, which is validated here before it changes state.

There is intentionally no generic "approve everything" action. Hard scope
exclusions can only be referred out, or have a mis-recorded fact corrected
with evidence (after which the rules run again).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

REASONS: dict[str, dict[str, Any]] = {
    "out_of_scope": {
        "label": "Out of scope for SilverFile",
        "assignment": "§4.4(1)",
        "actions": ["refer_out_of_scope", "correct_fact", "request_more_info"],
    },
    "user_document_conflict": {
        "label": "Taxpayer statement conflicts with a document",
        "assignment": "§4.4(2)",
        "actions": ["confirm_document_value", "correct_fact", "request_more_info", "refer_out_of_scope"],
    },
    "form_1099r_2b": {
        "label": "1099-R taxable amount not determined (box 2b)",
        "assignment": "§4.4(3)",
        "actions": ["refer_out_of_scope", "correct_fact"],
    },
    "advice_request": {
        "label": "Taxpayer asked for tax advice",
        "assignment": "§4.4(4)",
        "actions": ["note_and_continue", "refer_out_of_scope"],
    },
    "filing_status_ambiguity": {
        "label": "Filing status is ambiguous",
        "assignment": "§4.4(5)",
        "actions": ["set_filing_status", "request_more_info", "refer_out_of_scope"],
    },
    "exploitation_concern": {
        "label": "Possible financial exploitation or third-party pressure",
        "assignment": "§4.4(6)",
        "actions": ["cleared_continue", "request_more_info", "refer_out_of_scope"],
    },
    "taxpayer_needs_help": {
        "label": "Taxpayer is unsure or asked for a person",
        "assignment": "§4.3 (honest uncertainty)",
        "actions": ["correct_fact", "request_more_info", "note_and_continue", "refer_out_of_scope"],
    },
    "document_problem": {
        "label": "A document could not be used as-is",
        "assignment": "§2 (never assert an unsourced amount)",
        "actions": ["correct_fact", "request_more_info", "refer_out_of_scope"],
    },
    "loop_guard": {
        "label": "Automatic processing stopped by the loop guard",
        "assignment": "§4.1 (loop guard)",
        "actions": ["retry_processing", "refer_out_of_scope"],
    },
    "review_bound": {
        "label": "Audit could not be satisfied within the revision limit",
        "assignment": "§4.1 (bounded review cycle)",
        "actions": ["retry_processing", "refer_out_of_scope"],
    },
    "system_error": {
        "label": "A system component failed",
        "assignment": "Engineering quality",
        "actions": ["retry_processing", "refer_out_of_scope"],
    },
}

ACTION_LABELS = {
    "refer_out_of_scope": "Refer out of scope and close the SilverFile case",
    "correct_fact": "Correct a recorded fact (evidence required)",
    "request_more_info": "Ask the taxpayer a question through SilverFile",
    "confirm_document_value": "Confirm the document value is correct (evidence required)",
    "note_and_continue": "Note it for the volunteer preparer and continue",
    "set_filing_status": "Set the filing status after speaking with the taxpayer",
    "cleared_continue": "Concern checked privately with the taxpayer; continue",
    "retry_processing": "Retry automatic processing once",
}

# Facts a reviewer may correct, and which escalations they could resolve.
CORRECTABLE_FACT_PREFIXES = ("tp.", "sp.", "stated_wages", "filing_status", "other_income", "itemize",
                             "return_type_ok", "refund.", "answerer", "helper.", "dependents", "est.",
                             "s1.", "s2.", "s3.", "qcd.", "docs.", "us_resident_all_year", "mfs.",
                             "spouse_died_2025", "doc:")


class DecisionError(ValueError):
    """Reviewer decision is not allowed for this event."""


def make_escalation(reason: str, summary: str, *, raised_by: str, evidence: list[dict] | None = None,
                    affected: list[str] | None = None, taxpayer_message: str | None = None,
                    details: dict | None = None) -> dict:
    if reason not in REASONS:
        raise ValueError(f"unknown escalation reason {reason}")
    return {
        "reason": reason,
        "summary": summary,
        "raised_by": raised_by,
        "evidence": evidence or [],
        "affected": affected or [],
        "taxpayer_message": taxpayer_message or (
            "Thank you. I've flagged this for a Kushim volunteer to look at. "
            "Your answers are saved, and you can come back after they have reviewed it."),
        "details": details or {},
    }


def build_event(case_id: str, escalation: dict, facts_version: int, seq: int) -> dict:
    """Deterministic event (same inputs -> same id), so node replay after a
    resume reproduces the identical event instead of a duplicate."""
    basis = json.dumps({"case": case_id, "reason": escalation["reason"], "summary": escalation["summary"],
                        "v": facts_version, "seq": seq}, sort_keys=True)
    event_id = "hr-" + hashlib.sha256(basis.encode()).hexdigest()[:12]
    reason = REASONS[escalation["reason"]]
    return {
        "id": event_id,
        "case_id": case_id,
        "reason": escalation["reason"],
        "reason_label": reason["label"],
        "assignment_ref": reason["assignment"],
        "summary": escalation["summary"],
        "raised_by": escalation.get("raised_by"),
        "evidence": escalation.get("evidence", [])[:10],
        "affected": escalation.get("affected", [])[:20],
        "details": escalation.get("details", {}),
        "allowed_actions": list(reason["actions"]),
        "facts_version": facts_version,
        "status": "pending",
    }


def validate_decision(event: dict, decision: dict) -> dict:
    """Check a reviewer decision against the event. Returns the cleaned decision."""
    if not isinstance(decision, dict) or decision.get("kind") != "reviewer_decision":
        raise DecisionError("Only a reviewer decision from the dashboard can resume a human-review event.")
    if decision.get("event_id") != event["id"]:
        raise DecisionError("This decision is for a different (or already resolved) event.")
    action = decision.get("action")
    if action not in event["allowed_actions"]:
        raise DecisionError(f"Action {action!r} is not allowed for {event['reason_label']}.")
    reviewer = (decision.get("reviewer") or "").strip()
    if not reviewer:
        raise DecisionError("Reviewer name is required.")
    rationale = (decision.get("rationale") or "").strip()
    if not rationale:
        raise DecisionError("A short rationale is required for the audit record.")
    clean = {"action": action, "reviewer": reviewer, "rationale": rationale,
             "evidence": (decision.get("evidence") or "").strip(), "at": decision.get("at")}
    if action in {"correct_fact", "confirm_document_value"}:
        if not clean["evidence"]:
            raise DecisionError("Evidence is required to correct or confirm a value.")
    if action == "correct_fact":
        fact_id = (decision.get("fact_id") or "").strip()
        if not fact_id.startswith(CORRECTABLE_FACT_PREFIXES):
            raise DecisionError(f"Fact {fact_id!r} cannot be corrected from the dashboard.")
        if decision.get("new_value") in (None, ""):
            raise DecisionError("A new value is required.")
        clean["fact_id"] = fact_id
        clean["new_value"] = decision.get("new_value")
    if action == "set_filing_status":
        status = (decision.get("filing_status") or "").strip().lower()
        if status not in {"single", "mfj", "mfs", "hoh", "qss"}:
            raise DecisionError("Choose one of the five filing statuses.")
        clean["filing_status"] = status
    if action == "request_more_info":
        question = (decision.get("question") or "").strip()
        if not question:
            raise DecisionError("Type the question to send to the taxpayer.")
        clean["question"] = question
        clean["fact_id"] = (decision.get("fact_id") or "").strip() or None
    return clean
