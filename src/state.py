"""Shared LangGraph state for a SilverFile case.

The state is a ``TypedDict`` of JSON-serialisable values so the SQLite
checkpointer can persist it between sessions. Money is stored as strings.
Fields written by parallel branches use reducers that merge by stable ids
and give the same result whatever order the workers finish in.

Ownership (who may write each field) is documented in docs/STATE_CONTRACT.md.
"""

from __future__ import annotations

import hashlib
import json
import operator
from typing import Annotated, Any, TypedDict

# ---------------------------------------------------------------------------
# reducers
# ---------------------------------------------------------------------------


def merge_dict(left: dict | None, right: dict | None) -> dict:
    """Key-wise merge; the update wins for keys it names."""
    out = dict(left or {})
    out.update(right or {})
    return out


def _fingerprint(record: dict) -> str:
    body = {k: v for k, v in record.items() if k not in {"conflict", "candidates"}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def merge_extractions(left: dict | None, right: dict | None) -> dict:
    """Merge extraction records by document id, independent of arrival order.

    * new document id -> added
    * same id, identical record -> unchanged (duplicate delivery is harmless)
    * same id, higher ``revision`` -> the newer revision wins (re-extraction)
    * same id and revision but different content -> both candidates kept,
      sorted by fingerprint, and the record is flagged as a conflict so the
      aggregator escalates instead of silently picking one.
    """
    out = dict(left or {})
    for doc_id, rec in (right or {}).items():
        cur = out.get(doc_id)
        if cur is None:
            out[doc_id] = rec
            continue
        if _fingerprint(cur) == _fingerprint(rec):
            continue
        r_cur, r_new = int(cur.get("revision", 0)), int(rec.get("revision", 0))
        if r_new > r_cur:
            out[doc_id] = rec
        elif r_cur > r_new:
            continue
        else:
            cands = list(cur.get("candidates") or [cur]) + list(rec.get("candidates") or [rec])
            uniq = {(_fingerprint(c)): c for c in cands}
            ordered = [uniq[k] for k in sorted(uniq)]
            out[doc_id] = {**ordered[0], "conflict": True, "candidates": ordered}
    return out


_DOC_STATUS_RANK = {"uploaded": 0, "queued": 1, "extracting": 2, "extracted": 3, "needs_attention": 3,
                    "rejected": 4, "duplicate": 4}


def merge_documents(left: dict | None, right: dict | None) -> dict:
    """Merge document records by id; status only moves forward unless the
    update carries a higher ``revision`` (an explicit re-queue)."""
    out = dict(left or {})
    for doc_id, rec in (right or {}).items():
        cur = out.get(doc_id)
        if cur is None:
            out[doc_id] = rec
            continue
        merged = {**cur, **rec}
        if int(rec.get("revision", 0)) <= int(cur.get("revision", 0)):
            if _DOC_STATUS_RANK.get(rec.get("status"), 0) < _DOC_STATUS_RANK.get(cur.get("status"), 0):
                merged["status"] = cur.get("status")
        out[doc_id] = merged
    return out


def append_unique(left: list | None, right: list | None) -> list:
    """Append records, replacing any existing record with the same ``id``."""
    out = list(left or [])
    index = {r.get("id"): i for i, r in enumerate(out) if isinstance(r, dict)}
    for rec in right or []:
        rid = rec.get("id") if isinstance(rec, dict) else None
        if rid is not None and rid in index:
            out[index[rid]] = rec
        else:
            index[rid] = len(out)
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# state schema
# ---------------------------------------------------------------------------


class CaseState(TypedDict, total=False):
    # identity
    case_id: str
    tax_year: int
    schema_version: int
    created_at: str
    status: str

    # taxpayer facts from intake / reviewers: fact_id -> Fact dict
    facts: Annotated[dict, merge_dict]
    facts_version: int
    intake: dict

    # documents and extraction (parallel writers -> reducers)
    documents: Annotated[dict, merge_documents]
    extractions: Annotated[dict, merge_extractions]
    source_facts: dict          # written only by the extraction aggregator
    extraction_summary: dict

    # rules, computation, review, assembly
    eligibility: dict
    lines: Annotated[dict, merge_dict]
    provenance: Annotated[dict, merge_dict]
    calc: dict
    review: dict
    assembly: dict

    # human review
    escalation: dict | None
    human_events: Annotated[list, append_unique]

    # conversation (persistent transcript; model context is built separately)
    transcript: Annotated[list, operator.add]

    # routing / loop guard
    routing: dict

    # observability
    metrics: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    error: dict | None


STATUS_LABELS = {
    "intake": "Intake in progress",
    "awaiting_documents": "Waiting for documents",
    "processing": "Processing",
    "needs_human_review": "Needs human review",
    "revising": "Revising after audit",
    "draft_ready": "Draft ready for review",
    "submitted_for_internal_review": "Submitted internally for human review",
    "referred_out_of_scope": "Referred: out of scope",
    "closed": "Closed",
    "error": "Error - needs attention",
}

TERMINAL_STATUSES = {"referred_out_of_scope", "closed", "submitted_for_internal_review"}


def new_case_state(case_id: str, created_at: str, tax_year: int, schema_version: int) -> CaseState:
    return CaseState(
        case_id=case_id,
        tax_year=tax_year,
        schema_version=schema_version,
        created_at=created_at,
        status="intake",
        facts={},
        facts_version=0,
        intake={"asked": [], "complete": False, "followups": [], "notes_for_volunteer": [],
                "rejected_ssn_attempts": 0, "cursor_override": None, "followup_attempts": {}},
        documents={},
        extractions={},
        source_facts={},
        extraction_summary={},
        eligibility={},
        lines={},
        provenance={},
        calc={"facts_version": -1, "status": "not_started"},
        review={"passes": 0, "history": []},
        assembly={},
        escalation=None,
        human_events=[],
        transcript=[],
        routing={"handoffs_this_run": 0, "signature_counts": {}, "history": [], "run": 0},
        metrics=[],
        trace=[],
        error=None,
    )


def fact_value(state: dict, fact_id: str, default: Any = None) -> Any:
    fact = (state.get("facts") or {}).get(fact_id)
    if not fact or fact.get("status") != "confirmed":
        return default
    return fact.get("value")
