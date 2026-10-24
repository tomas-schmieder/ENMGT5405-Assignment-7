"""Scripted case runner used by the CLI demo, the evaluation suite and tests.

It plays the taxpayer from a fixture's answer sheet (keyed by question id, so
it works whatever order the intake asks in), uploads the fixture's document
images through the normal upload path when asked, and - only when a fixture
says so - plays the Kushim reviewer by resolving human-review events through
the same service call the dashboard uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.service import SilverFileService


class ScriptError(RuntimeError):
    pass


def load_case(case_id: str) -> dict:
    return json.loads((PROJECT_ROOT / "data" / "fixtures" / case_id / "case.json").read_text())


def run_case(service: SilverFileService, spec: dict, max_turns: int = 150, stop_on_review: bool = False,
             log: list | None = None) -> dict:
    """Run a fixture to completion (or to an unresolved escalation)."""
    answers: dict[str, Any] = dict(spec["answers"])
    followups = dict(spec.get("followup_answers") or {})
    reviewer = list(spec.get("reviewer_actions") or [])
    log = log if log is not None else []
    case_id = service.create_case()
    uploaded = False
    for _ in range(max_turns):
        pend = service.pending(case_id)
        if pend is None:
            break
        if pend["kind"] == "taxpayer_question":
            step = pend["step"]
            qid = step["question_id"]
            uploads: list[dict] = []
            if qid.startswith("followup:"):
                fid = qid.split(":", 1)[1]
                answer = next((v for k, v in followups.items() if fid.startswith(k)), "not sure")
            elif qid == "upload_docs":
                if uploaded:
                    raise ScriptError(f"documents still missing after upload: {step.get('missing')}")
                for d in spec.get("documents", []):
                    path = PROJECT_ROOT / d["file"]
                    uploads.append(service.add_upload(case_id, path.name, path.read_bytes(), d["type"]))
                uploaded = True
                answer = "done"
            elif qid == "submit_draft":
                answer = "Send it to Kushim for review"
            elif qid in answers:
                answer = answers[qid]
            else:
                raise ScriptError(f"fixture has no answer for question {qid!r}: {step.get('text')}")
            log.append({"q": qid, "a": answer if step.get("kind") != "ssn" else "[ssn]", "uploads": len(uploads)})
            service.send_message(case_id, str(answer), uploads)
        elif pend["kind"] == "human_review":
            event = pend["event"]
            log.append({"review": event["reason"], "summary": event["summary"]})
            if stop_on_review:
                break
            action = next((a for a in reviewer if a["reason"] == event["reason"]), None)
            if action is None:
                break
            reviewer.remove(action)
            service.resolve_review(case_id, event["id"], action=action["action"], reviewer=action["reviewer"],
                                   rationale=action["rationale"], evidence=action.get("evidence", ""),
                                   fact_id=action.get("fact_id"), new_value=action.get("new_value"),
                                   filing_status=action.get("filing_status"), question=action.get("question"))
        else:  # pragma: no cover
            raise ScriptError(f"unknown interrupt kind {pend['kind']}")
    view = service.view(case_id)
    view["script_log"] = log
    return view


def summarize(view: dict) -> dict:
    lines = {k: v["value"] for k, v in sorted(view["lines"].items(), key=lambda kv: _line_order(kv[0]))}
    return {"case_id": view["case_id"], "status": view["status"], "lines": lines,
            "pending": (view["pending"] or {}).get("event", {}).get("reason") if view["pending"] else None,
            "events": [(e["reason"], e.get("resolution", {}).get("action")) for e in view["human_events"]],
            "draft": (view["assembly"] or {}).get("pdf_path")}


def _line_order(line: str) -> tuple:
    import re

    m = re.match(r"(\d+)([a-z]*)", line)
    return (int(m.group(1)), m.group(2)) if m else (999, line)
