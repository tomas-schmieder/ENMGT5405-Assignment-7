"""Eligibility & Rules decision table: one row per rule boundary.

Each case builds a minimal state, runs the rules agent (with in-process tool
stub), and checks the decision and the escalation reason. Every decision must
carry citations from the registry.
"""

import pytest

from src.agents.eligibility_rules import compute_boxes, registry, rules_node


def fact(v):
    return {"value": v, "status": "confirmed", "source": {}}


def state_with(facts: dict, complete: bool = False, extractions: dict | None = None, documents: dict | None = None):
    return {"case_id": "T", "facts": {k: fact(v) for k, v in facts.items()}, "facts_version": 1,
            "intake": {"complete": complete, "followups": []}, "documents": documents or {},
            "extractions": extractions or {}, "source_facts": {}}


BASE = {"tp.first_name": "A", "tp.last_name": "B", "tp.dob": "1955-01-01", "filing_status": "single",
        "tp.ssn": "900-11-2222", "return_type_ok": True, "answerer": "self", "us_resident_all_year": True,
        "tp.claimable_dependent": False, "spouse_died_2025": False, "itemize": False, "other_income.any": False}


@pytest.mark.parametrize("overrides,reason", [
    ({"tp.dob": "1961-01-01"}, None),                                   # born before Jan 2, 1961: eligible
    ({"tp.dob": "1961-01-02"}, "out_of_scope"),                         # on the cutoff: not eligible
    ({"tp.dob": "1965-05-05", "filing_status": "mfj", "sp.dob": "1958-03-03"}, None),  # joint: one spouse suffices
    ({"tp.dob": "1965-05-05", "filing_status": "mfj", "sp.dob": "1962-03-03"}, "out_of_scope"),
    ({"itemize": True}, "out_of_scope"),
    ({"return_type_ok": False}, "out_of_scope"),
    ({"other_income.any": True, "other_income.kinds": "rental property"}, "out_of_scope"),
    ({"tp.claimable_dependent": True}, "out_of_scope"),
    ({"filing_status": "mfs", "mfs.spouse_itemizes": True}, "out_of_scope"),
    ({"us_resident_all_year": False}, "out_of_scope"),
    ({"spouse_died_2025": True, "filing_status": "mfj"}, "filing_status_ambiguity"),
    ({"filing_status": "qss", "qss.spouse_death_year": "2025", "qss.dependent_child": True}, "filing_status_ambiguity"),
    ({"filing_status": "qss", "qss.spouse_death_year": "2024", "qss.dependent_child": False}, "filing_status_ambiguity"),
    ({"filing_status": "hoh", "hoh.qualifying_person": False}, "filing_status_ambiguity"),
    ({"answerer": "helper", "helper.authority": False}, "exploitation_concern"),
    ({"answerer": "helper", "helper.authority": True}, None),
    ({"refund.method": "direct_deposit", "refund.account_own": False}, "exploitation_concern"),
    ({"dependents": [{"first": str(i)} for i in range(5)], "dependents.any": True}, "out_of_scope"),
])
def test_screening_decisions(runtime, overrides, reason):
    out = rules_node(state_with({**BASE, **overrides}), runtime)
    got = (out.get("escalation") or {}).get("reason")
    assert got == reason
    for d in out["eligibility"]["decisions"]:
        assert d["citations"], d


def test_exploitation_outranks_other_escalations(runtime):
    out = rules_node(state_with({**BASE, "itemize": True, "refund.account_own": False}), runtime)
    assert out["escalation"]["reason"] == "exploitation_concern"
    assert out["escalation"]["details"]["also"]


def test_reviewer_clearance_never_overrides_hard_exclusion(runtime):
    facts = {**BASE, "itemize": True, "review.cleared": ["out_of_scope"]}
    assert rules_node(state_with(facts), runtime)["escalation"]["reason"] == "out_of_scope"
    facts = {**BASE, "refund.account_own": False, "review.cleared": ["exploitation_concern"]}
    assert rules_node(state_with(facts), runtime).get("escalation") is None


def _r_doc(doc_id, flags=None, code="7", box2a="1000.00", ira=False):
    rec = {"doc_id": doc_id, "doc_type": "1099-R", "payer": "P", "distribution_code": code,
           "flags": {"taxable_not_determined": False, "ira_sep_simple": ira, **(flags or {})},
           "fields": {"1": {"value": "1000.00"}, "2a": {"value": box2a, "blank": box2a is None},
                      "4": {"value": "0.00"}}}
    return {doc_id: rec}, {doc_id: {"status": "extracted", "owner": "taxpayer"}}


@pytest.mark.parametrize("flags,code,box2a,reason", [
    ({"taxable_not_determined": True}, "7", None, "form_1099r_2b"),
    ({}, "G", "1000.00", "out_of_scope"),
    ({}, "1", "1000.00", "out_of_scope"),
    ({}, "7", None, "document_problem"),
    ({}, "7", "1000.00", None),
])
def test_1099r_document_rules(runtime, flags, code, box2a, reason):
    ex, docs = _r_doc("r1", flags, code, box2a)
    out = rules_node(state_with({**BASE, "docs.1099r.count": 1, "qcd.any": False}, complete=True,
                                extractions=ex, documents=docs), runtime)
    assert (out.get("escalation") or {}).get("reason") == reason


def test_capital_gain_distribution_escalates(runtime):
    ex = {"d1": {"doc_id": "d1", "doc_type": "1099-DIV", "payer": "Fund", "fields": {"1a": {"value": "100.00"},
                                                                                    "2a": {"value": "50.00"}}}}
    out = rules_node(state_with({**BASE}, complete=True, extractions=ex,
                                documents={"d1": {"status": "extracted"}}), runtime)
    assert out["escalation"]["reason"] == "out_of_scope"


def test_qcd_requires_age_70_and_a_half(runtime):
    ex, docs = _r_doc("r1", ira=True)
    young = {**BASE, "tp.dob": "1956-03-03", "qcd.any": True, "qcd.amount": "100.00"}
    out = rules_node(state_with(young, complete=True, extractions=ex, documents=docs), runtime)
    assert out["escalation"]["reason"] == "taxpayer_needs_help"
    old = {**BASE, "tp.dob": "1950-03-03", "qcd.any": True, "qcd.amount": "100.00"}
    assert rules_node(state_with(old, complete=True, extractions=ex, documents=docs), runtime).get("escalation") is None


def _w2(value):
    return ({"w": {"doc_id": "w", "doc_type": "W-2", "payer": "E", "fields": {"1": {"value": value},
                                                                               "2": {"value": "0.00"}}}},
            {"w": {"status": "extracted", "owner": "taxpayer"}})


def test_conflict_asks_follow_up_then_escalates(runtime):
    ex, docs = _w2("45200.00")
    facts = {**BASE, "docs.w2.count": 1, "stated_wages": "54000.00"}
    out = rules_node(state_with(facts, complete=True, extractions=ex, documents=docs), runtime)
    assert out["eligibility"]["status"] == "need_input"
    follow = out["intake"]["followups"][0]
    assert follow["id"] == "conflict-wages" and "$45,200.00" in follow["text"] and "$54,000.00" in follow["text"]
    out2 = rules_node(state_with({**facts, "conflict.wages.answer": "stated"}, complete=True, extractions=ex,
                                 documents=docs), runtime)
    assert out2["escalation"]["reason"] == "user_document_conflict"
    out3 = rules_node(state_with({**facts, "conflict.wages.answer": "document"}, complete=True, extractions=ex,
                                 documents=docs), runtime)
    assert out3["eligibility"]["status"] == "ok"


def test_no_conflict_within_tolerance(runtime):
    ex, docs = _w2("46850.00")
    out = rules_node(state_with({**BASE, "docs.w2.count": 1, "stated_wages": "46000.00"}, complete=True,
                                extractions=ex, documents=docs), runtime)
    assert out["eligibility"]["status"] == "ok"


@pytest.mark.parametrize("facts,expected", [
    ({"filing_status": "single", "tp.dob": "1955-01-01", "tp.blind": True}, (True, True, False, False)),
    ({"filing_status": "mfj", "tp.dob": "1955-01-01", "sp.dob": "1958-01-01", "sp.blind": True},
     (True, False, True, True)),
    ({"filing_status": "mfj", "tp.dob": "1955-01-01", "sp.dob": "1962-01-01"}, (True, False, False, False)),
    ({"filing_status": "hoh", "tp.dob": "1955-01-01", "sp.dob": "1955-01-01"}, (True, False, False, False)),
    ({"filing_status": "mfs", "tp.dob": "1955-01-01", "sp.dob": "1950-01-01", "mfs.spouse_no_income": False},
     (True, False, False, False)),
    ({"filing_status": "mfs", "tp.dob": "1955-01-01", "sp.dob": "1950-01-01", "mfs.spouse_no_income": True},
     (True, False, True, False)),
    ({"filing_status": "single", "tp.dob": "1960-12-31"}, (True, False, False, False)),
])
def test_line_12d_boxes(facts, expected):
    b = compute_boxes(facts)
    assert (b["tp_65"], b["tp_blind"], b["sp_65"], b["sp_blind"]) == expected


def test_every_rule_cites_a_source():
    for rule_id, rule in registry().items():
        assert rule["citations"], rule_id
        for c in rule["citations"]:
            assert c["doc"] == "assignment" or c.get("page"), (rule_id, c)
