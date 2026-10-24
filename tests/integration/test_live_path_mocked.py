"""Live-mode plumbing with a fake Anthropic client (no network, no key).

The fake implements ``client.beta.messages.create`` / ``client.messages.create``
with the same response shape as the SDK (content blocks, usage with cache
fields, stop_reason, model). It answers each agent's structured-output request
deterministically (OCR for images, the offline parser for replies) and reports
a token count proportional to the request size. This checks request building,
schema validation, retries, metrics and the context strategy in live mode. It
does NOT replace the real-API tests in tests/live (run when a key is set).
"""

import json
import re
from types import SimpleNamespace

import pytest

from src.contracts import AuditCritique, CoverNote, DocumentExtraction, IntakeInterpretation, LineExplanations
from src.driver import load_case, run_case
from src.llm import AnthropicLLM


class FakeMessages:
    def __init__(self, log, fail_first_json=False):
        self.log = log
        self.fail_first_json = fail_first_json

    def create(self, **kw):
        self.log.append(kw)
        system = kw["system"]
        msgs = kw["messages"]
        assert "temperature" not in kw and kw["output_config"]["format"]["type"] == "json_schema"
        size = len(json.dumps(msgs, default=str)) + len(system)
        images = sum(1 for m in msgs if isinstance(m["content"], list)
                     for b in m["content"] if isinstance(b, dict) and b.get("type") == "image")
        if "Document Extraction agent" in system:
            import base64

            from src.tools.ocr_reader import extract

            block = [b for b in msgs[-1]["content"] if b.get("type") == "image"][-1]
            want = re.search(r"Form (\S+) for", [b for b in msgs[-1]["content"] if b.get("type") == "text"][-1]["text"])
            data = extract(base64.b64decode(block["source"]["data"]), want.group(1)).model_dump()
        elif "Intake agent" in system:
            from src.agents.intake import offline_interpret

            text = msgs[-1]["content"] if isinstance(msgs[-1]["content"], str) else ""
            q = re.search(r"CURRENT QUESTION: \[([^\]]+)\] \((\w+)\)", text)
            reply = re.search(r"TAXPAYER'S REPLY: (.*)\n", text).group(1)
            step = {"question_id": q.group(1), "kind": q.group(2)}
            data = offline_interpret(step, reply).model_dump()
            data["reply"] = "Thank you."
        elif "Review / Audit" in system:
            data = AuditCritique(findings=[], summary="No contradictions found.").model_dump()
        elif "Computation agent" in system:
            data = LineExplanations(explanations=[{"line": "16", "text": "Tax from the Tax Table row."}]).model_dump()
        elif "Return Assembly" in system:
            data = CoverNote(note="Draft for review; nothing has been filed.").model_dump()
        else:
            data = {"findings": []}
        text = json.dumps(data)
        if self.fail_first_json:
            self.fail_first_json = False
            text = "not json"
        usage = SimpleNamespace(input_tokens=size // 4 + images * 1500, output_tokens=len(text) // 4,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], usage=usage, stop_reason="end_turn",
                               model=kw["model"])


class FakeClient:
    def __init__(self, fail_first_json=False):
        self.log = []
        self.messages = FakeMessages(self.log, fail_first_json)
        self.beta = SimpleNamespace(messages=self.messages)


def make_llm(**kw):
    llm = AnthropicLLM("claude-opus-5-5", effort="low", use_fallbacks=True, client=FakeClient(**kw))
    return llm


def test_live_mode_runs_case_1_with_model_calls(service_factory):
    llm = make_llm()
    svc = service_factory()
    svc.llm = llm
    svc.runtime.llm = llm
    view = run_case(svc, load_case("eval_case_1"))
    assert view["status"] == "submitted_for_internal_review"
    assert view["lines"]["16"]["value"] == "2537"
    calls = [m for m in view["metrics"] if m.get("kind") == "model_call" and m.get("mode") == "anthropic"]
    agents = {m["agent"] for m in calls}
    assert {"intake", "document_extraction", "review_audit", "computation", "return_assembly"} <= agents
    assert all(m["input_tokens"] > 0 for m in calls)
    sent = llm.client.log
    assert all(k["betas"] == ["server-side-fallback-2026-07-01"] and k["fallbacks"] == "default" for k in sent)
    assert view["provenance"]["line:16"]["explanation"] == "Tax from the Tax Table row."


def test_invalid_structured_output_is_retried_once():
    llm = make_llm(fail_first_json=True)
    call = llm.structured(agent="t", system="You are the Return Assembly agent", schema=CoverNote,
                          messages=[{"role": "user", "content": "x"}], offline=lambda: None, purpose="p")
    assert call.data.note and call.record["attempts"] == 2


def test_context_strategy_flattens_intake_tokens(service_factory, monkeypatch):
    usage = {}
    for strategy in (True, False):
        llm = make_llm()
        svc = service_factory(var_dir=None)
        svc.settings.context_strategy = strategy
        svc.llm = llm
        svc.runtime.llm = llm
        spec = load_case("eval_case_1")
        view = run_case(svc, {**spec, "documents": spec["documents"]})
        intake = [m["input_tokens"] for m in view["metrics"] if m.get("agent") == "intake" and m.get("mode") == "anthropic"]
        usage[strategy] = intake
    on, off = usage[True], usage[False]
    assert len(on) == len(off) > 10
    assert off[-1] > 3 * off[0]                      # full replay grows with the conversation
    assert (on[-1] - on[0]) < (off[-1] - off[0]) / 2  # selective recall grows far more slowly
