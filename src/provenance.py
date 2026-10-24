"""Provenance records: where every number on the draft came from.

Keys:

* ``doc:<doc_id>:<box>`` - a value read from a document box
* ``fact:<fact_id>``     - a direct user input (or reviewer correction)
* ``line:<line>``        - a form line produced by an MCP tool call

A derived record lists its inputs by key, so a reviewer can walk from any
line down to the original document boxes and dated answers (assignment §4.2).
"""

from __future__ import annotations

from typing import Any

MONEY_LINES_REQUIRED = [
    "1z", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b", "6a", "6b", "9", "10", "11a", "11b",
    "12e", "13b", "14", "15", "16", "24", "25a", "25b", "25c", "25d", "26", "33", "34", "37",
]


def doc_key(doc_id: str, box: str) -> str:
    return f"doc:{doc_id}:{box}"


def fact_key(fact_id: str) -> str:
    return f"fact:{fact_id}"


def line_key(line: str) -> str:
    return f"line:{line}"


def document_record(*, doc: dict, box: str, label: str, raw_text: str | None, value: str,
                    extraction: dict) -> dict:
    return {
        "kind": "document",
        "key": doc_key(doc["doc_id"], box),
        "doc_id": doc["doc_id"],
        "doc_type": doc.get("doc_type"),
        "file_name": doc.get("file_name"),
        "sha256": doc.get("sha256"),
        "source": doc.get("source", "upload"),
        "page": 1,
        "box": box,
        "label": label,
        "raw_text": raw_text,
        "value": value,
        "owner": extraction.get("owner"),
        "tax_year": extraction.get("tax_year"),
        "extracted_by": extraction.get("by"),
        "extraction_call_id": extraction.get("call_id"),
        "extracted_at": extraction.get("at"),
    }


def direct_input_record(*, fact_id: str, value: Any, entered_by: str, entered_at: str,
                        question_id: str | None, question_text: str | None, raw_answer: str | None) -> dict:
    return {
        "kind": "direct_input",
        "key": fact_key(fact_id),
        "fact_id": fact_id,
        "value": value,
        "entered_by": entered_by,
        "entered_at": entered_at,
        "question_id": question_id,
        "question_text": question_text,
        "raw_answer": raw_answer,
        "label": "Direct user input",
    }


def reviewer_record(*, key: str, prior_value: Any, new_value: Any, reviewer: str, at: str,
                    rationale: str, evidence: str, event_id: str) -> dict:
    return {
        "kind": "reviewer_correction",
        "key": key,
        "value": new_value,
        "prior_value": prior_value,
        "reviewer": reviewer,
        "entered_at": at,
        "rationale": rationale,
        "evidence": evidence,
        "event_id": event_id,
        "label": "Human reviewer correction",
    }


def derived_record(*, line: str, value: str, tool_result: dict, inputs: dict[str, dict],
                   facts_version: int, computed_at: str) -> dict:
    """``inputs`` maps an argument name to ``{"value": ..., "ref": key-or-None}``."""
    return {
        "kind": "derived",
        "key": line_key(line),
        "line": line,
        "value": value,
        "tool": tool_result.get("tool"),
        "tool_version": tool_result.get("version"),
        "call_id": tool_result.get("call_id"),
        "transport": tool_result.get("transport"),
        "called_at": tool_result.get("called_at"),
        "inputs": inputs,
        "trace": tool_result.get("trace", []),
        "rule_ids": tool_result.get("rule_ids", []),
        "facts_version": facts_version,
        "computed_at": computed_at,
        "explanation": None,
    }


def resolve(provenance: dict, key: str, depth: int = 0, max_depth: int = 8, seen: set | None = None) -> dict:
    """Return a nested tree for ``key`` for display (cycles and depth guarded)."""
    seen = set() if seen is None else seen
    rec = provenance.get(key)
    if rec is None:
        return {"key": key, "missing": True}
    node = {"key": key, "record": rec, "children": []}
    if key in seen or depth >= max_depth:
        return node
    seen = seen | {key}
    for name, inp in (rec.get("inputs") or {}).items():
        refs = inp.get("refs") or ([inp["ref"]] if inp.get("ref") else [])
        for ref in refs:
            child = resolve(provenance, ref, depth + 1, max_depth, seen)
            child["as_input"] = name
            node["children"].append(child)
    return node


def lineage_gaps(lines: dict, provenance: dict, required: list[str] | None = None) -> list[dict]:
    """Every populated money line must have a record whose value matches and
    whose input references all resolve to existing records."""
    gaps: list[dict] = []
    for line in required or MONEY_LINES_REQUIRED:
        entry = lines.get(line)
        if entry is None or entry.get("value") in (None, ""):
            gaps.append({"line": line, "problem": "line has no value"})
            continue
        rec = provenance.get(line_key(line))
        if rec is None:
            gaps.append({"line": line, "problem": "no provenance record"})
            continue
        if str(rec.get("value")) != str(entry.get("value")):
            gaps.append({"line": line, "problem": "provenance value differs from line value"})
        for name, inp in (rec.get("inputs") or {}).items():
            refs = inp.get("refs") or ([inp["ref"]] if inp.get("ref") else [])
            for ref in refs:
                if ref not in provenance:
                    gaps.append({"line": line, "problem": f"input {name} references missing record {ref}"})
    return gaps
