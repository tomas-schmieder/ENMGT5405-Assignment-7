"""Intake accessibility behaviours, privacy, and guardrails (§4.3, §2, §3.2)."""

import pytest

from src.agents.intake import guardrail_signals, handle_reply, next_step, offline_interpret
from src.agents.intake_script import (QUESTIONS, Invalid, v_count, v_date, v_money, v_name, v_ssn, v_yes_no,
                                      V_FILING_STATUS)
from src.hitl import DecisionError, REASONS, build_event, make_escalation, validate_decision
from src.memory import build_intake_context, session_summary
from src.money import parse_money
from src.provenance import lineage_gaps
from src.ssn import redact_ssns, validate_fictional_ssn
from src.state import new_case_state


# --- fictional SSN rule ----------------------------------------------------------------
@pytest.mark.parametrize("text,ok", [("900-12-3456", True), ("900123456", True), ("999 99 9999", True),
                                     ("899-12-3456", False), ("123-45-6789", False), ("90012345", False),
                                     ("9001234567", False), ("abc", False)])
def test_fictional_ssn(text, ok):
    check = validate_fictional_ssn(text)
    assert check.ok is ok
    if ok:
        assert check.normalized.count("-") == 2
    else:
        assert "123" not in check.reason  # never echo the rejected number


def test_redaction():
    text, n = redact_ssns("my number is 123-45-6789 and also 900 12 3456")
    assert n == 2 and "6789" not in text and "3456" not in text


# --- validators -------------------------------------------------------------------------
def test_validators():
    assert v_yes_no("Yes.") is True and v_yes_no("nope") is False
    with pytest.raises(Invalid):
        v_yes_no("maybe")
    assert v_date("March 5, 1955") == "1955-03-05" == v_date("3/5/1955") == v_date("1955-03-05")
    with pytest.raises(Invalid):
        v_date("February 30, 1950")
    assert v_money("about 54,000") == "54000.00" and v_money("$1,250.75") == "1250.75" and v_money("none") == "0.00"
    assert v_count("two") == 2 and v_count("1 W-2") == 1
    assert V_FILING_STATUS("Married filing jointly") == "mfj" and V_FILING_STATUS("head of household") == "hoh"
    assert v_name("my name is eleanor") == "Eleanor"
    assert v_ssn("900-55-1234") == "900-55-1234"
    with pytest.raises(Invalid):
        v_ssn("123-45-6789")


def test_money_parsing_is_exact():
    assert str(parse_money("1,234.5")) == "1234.50"
    with pytest.raises(ValueError):
        parse_money(12.5)  # floats refused


# --- one question at a time & plain language ------------------------------------------------
def test_each_question_is_a_single_question():
    for q in QUESTIONS:
        assert q.text.count("?") <= 1, q.id
        assert len(q.text) < 260, q.id


def test_first_step_is_one_question():
    state = new_case_state("T", "2026-01-01", 2025, 1)
    step = next_step(state)
    assert step["question_id"] == "tp_first_name" and step["text"].count("?") == 1


# --- interpretation ---------------------------------------------------------------------
@pytest.mark.parametrize("text,intent", [
    ("Should I convert my IRA to a Roth?", "advice"),
    ("Would we pay less if we filed separately?", "advice"),
    ("Can I deduct my medications?", "advice"),
    ("I'm not sure", "unsure"),
    ("can we go back to the previous question", "go_back"),
    ("Could you repeat that?", "repeat"),
    ("I want to talk to a real person", "help"),
    ("Actually my date of birth is May 2, 1950", "correction"),
    ("no", "answer"),
])
def test_offline_intents(text, intent):
    step = {"question_id": "itemize", "kind": "yes_no"}
    assert offline_interpret(step, text).intent == intent


def test_unsure_is_not_stored_as_a_name():
    assert offline_interpret({"question_id": "tp_first_name", "kind": "text"}, "not sure").intent == "unsure"


def test_negated_mentions_are_not_scope_signals():
    assert guardrail_signals("No, I have no rental income and I didn't sell any crypto").out_of_scope == []
    assert "rental_income" in guardrail_signals("I rent out my basement apartment").out_of_scope
    assert guardrail_signals("My nephew wants the refund sent to his account").exploitation_concern
    assert guardrail_signals("My husband passed away in March this year").spouse_died_2025


def _answer(state, runtime, text, uploads=None):
    step = next_step(state)
    patch = handle_reply(state, step, {"kind": "taxpayer_message", "text": text, "uploads": uploads or []}, runtime)
    merged = dict(state)
    for k, v in patch.items():
        if k in {"facts", "provenance"}:
            merged[k] = {**(state.get(k) or {}), **v}
        elif k in {"transcript", "trace", "metrics"}:
            merged[k] = list(state.get(k) or []) + v
        else:
            merged[k] = v
    return merged, patch


def test_volunteered_ssn_is_removed_and_not_stored(runtime):
    state = new_case_state("T", "2026-01-01", 2025, 1)
    state, patch = _answer(state, runtime, "Eleanor, my SSN is 123-45-6789")
    joined = " ".join(t["text"] for t in state["transcript"])
    assert "6789" not in joined and "privacy" in joined
    assert "tp.ssn" not in state["facts"]


def test_corrections_keep_history_and_go_back_keeps_answers(runtime):
    state = new_case_state("T", "2026-01-01", 2025, 1)
    for text in ["Eleanor", "Whitfield", "I'm answering for myself", "yes", "March 14, 1957"]:
        state, _ = _answer(state, runtime, text)
    assert state["facts"]["tp.dob"]["value"] == "1957-03-14"
    state, _ = _answer(state, runtime, "Actually my date of birth is March 15, 1957")
    dob = state["facts"]["tp.dob"]
    assert dob["value"] == "1957-03-15" and dob["history"][0]["value"] == "1957-03-14"
    state, _ = _answer(state, runtime, "go back")
    assert next_step(state)["question_id"] == "tp_dob"
    assert state["facts"]["tp.first_name"]["value"] == "Eleanor"   # nothing lost


def test_advice_request_escalates_and_is_noted(runtime):
    state = new_case_state("T", "2026-01-01", 2025, 1)
    _, patch = _answer(state, runtime, "Should I convert my IRA to a Roth first?")
    assert patch["escalation"]["reason"] == "advice_request"
    assert patch["intake"]["notes_for_volunteer"]


def test_invalid_ssn_entry_is_never_echoed(runtime):
    state = new_case_state("T", "2026-01-01", 2025, 1)
    answers = ["Eleanor", "Whitfield", "self", "yes", "1957-03-14", "single", "no"]
    for a in answers:
        state, _ = _answer(state, runtime, a)
    assert next_step(state)["question_id"] == "tp_ssn"
    state, patch = _answer(state, runtime, "123-45-6789")
    assert "6789" not in str(patch["transcript"]) and "tp.ssn" not in state["facts"]
    assert state["intake"]["rejected_ssn_attempts"] == 1


# --- human review decisions ----------------------------------------------------------------
def test_reviewer_decisions_are_constrained():
    event = build_event("C", make_escalation("form_1099r_2b", "box 2b", raised_by="t"), 3, 0)
    base = {"kind": "reviewer_decision", "event_id": event["id"], "reviewer": "R", "rationale": "x"}
    with pytest.raises(DecisionError):
        validate_decision(event, {**base, "action": "note_and_continue"})       # cannot continue a 2b case
    with pytest.raises(DecisionError):
        validate_decision(event, {**base, "kind": "taxpayer_message", "action": "refer_out_of_scope"})
    with pytest.raises(DecisionError):
        validate_decision(event, {**base, "event_id": "other", "action": "refer_out_of_scope"})
    with pytest.raises(DecisionError):
        validate_decision(event, {**base, "action": "correct_fact", "fact_id": "doc:x:flag:taxable_not_determined",
                                  "new_value": "false"})                          # evidence required
    assert validate_decision(event, {**base, "action": "refer_out_of_scope"})["action"] == "refer_out_of_scope"


def test_no_reason_has_a_generic_approve():
    for code, reason in REASONS.items():
        assert "approve" not in " ".join(reason["actions"])


def test_event_ids_are_deterministic():
    esc = make_escalation("advice_request", "asked", raised_by="intake")
    assert build_event("C", esc, 1, 0)["id"] == build_event("C", esc, 1, 0)["id"]
    assert build_event("C", esc, 1, 0)["id"] != build_event("C", esc, 1, 1)["id"]


# --- memory / context strategy -----------------------------------------------------------------
def test_context_strategy_bounds_model_input():
    state = new_case_state("T", "2026-01-01", 2025, 1)
    state["transcript"] = [{"role": r, "text": f"turn {i} " + "x" * 200} for i in range(60)
                           for r in ("assistant", "user")]
    on = build_intake_context(state, "Q?", "A", strategy_enabled=True, recent_turns=4, labels={})
    off = build_intake_context(state, "Q?", "A", strategy_enabled=False, recent_turns=4, labels={})
    assert len(on) == 1 and len(str(on)) < len(str(off)) / 5
    assert "ANSWERED QUESTION IDS" in on[0]["content"]
    assert len(off) > 50
    assert "CONFIRMED FACTS" in session_summary(state)


def test_lineage_gap_detection():
    lines = {"9": {"value": "100"}}
    prov = {"line:9": {"value": "100", "inputs": {"line_1z": {"ref": "line:1z"}}}}
    gaps = lineage_gaps(lines, prov, ["9", "16"])
    problems = {(g["line"], g["problem"].split(" ")[0]) for g in gaps}
    assert ("16", "line") in problems and ("9", "input") in problems
