"""Parallel-write reducers give the same result in any completion order (§4.1)."""

import itertools

from src.state import append_unique, merge_documents, merge_extractions


def _rec(doc_id, value, revision=0):
    return {doc_id: {"doc_id": doc_id, "revision": revision, "fields": {"1": {"value": value}}}}


def test_distinct_documents_union_in_any_order():
    updates = [_rec("a", "100.00"), _rec("b", "200.00"), _rec("c", "300.00")]
    results = []
    for perm in itertools.permutations(updates):
        state = {}
        for u in perm:
            state = merge_extractions(state, u)
        results.append(state)
    assert all(r == results[0] for r in results)
    assert set(results[0]) == {"a", "b", "c"}


def test_duplicate_delivery_is_harmless():
    state = merge_extractions({}, _rec("a", "100.00"))
    assert merge_extractions(state, _rec("a", "100.00")) == state


def test_conflicting_same_revision_is_flagged_identically_in_both_orders():
    x, y = _rec("a", "100.00"), _rec("a", "999.00")
    ab = merge_extractions(merge_extractions({}, x), y)
    ba = merge_extractions(merge_extractions({}, y), x)
    assert ab == ba
    assert ab["a"]["conflict"] is True
    assert len(ab["a"]["candidates"]) == 2


def test_higher_revision_wins_regardless_of_order():
    old, new = _rec("a", "100.00", 0), _rec("a", "150.00", 1)
    assert merge_extractions(merge_extractions({}, old), new)["a"]["fields"]["1"]["value"] == "150.00"
    assert merge_extractions(merge_extractions({}, new), old)["a"]["fields"]["1"]["value"] == "150.00"


def test_document_status_only_moves_forward_without_new_revision():
    state = merge_documents({}, {"d": {"status": "queued", "revision": 0}})
    state = merge_documents(state, {"d": {"status": "extracted"}})
    state = merge_documents(state, {"d": {"status": "queued"}})  # stale writer
    assert state["d"]["status"] == "extracted"
    state = merge_documents(state, {"d": {"status": "queued", "revision": 1}})  # explicit re-read
    assert state["d"]["status"] == "queued"


def test_append_unique_replaces_by_id():
    events = append_unique([], [{"id": "e1", "status": "pending"}])
    events = append_unique(events, [{"id": "e1", "status": "resolved"}, {"id": "e2", "status": "pending"}])
    assert [e["status"] for e in events] == ["resolved", "pending"]
