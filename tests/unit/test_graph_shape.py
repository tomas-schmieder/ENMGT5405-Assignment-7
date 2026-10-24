"""The compiled graph has the documented topology (README diagram, docs/graph.png)."""

from src.agents.base import Runtime
from src.config import get_settings
from src.graph import build_graph
from src.llm import OfflineLLM


def test_graph_nodes_and_edges():
    g = build_graph(Runtime(llm=OfflineLLM(), tools=None, settings=get_settings())).get_graph()
    nodes = set(g.nodes)
    assert {"orchestrator", "intake", "extract_document", "aggregate_extractions", "rules", "computation", "review",
            "assembly", "human_review"} <= nodes
    edges = {(e.source, e.target, e.conditional) for e in g.edges}
    # every agent returns to the orchestrator; extraction fans in through aggregation
    for n in ["intake", "aggregate_extractions", "rules", "computation", "review", "assembly", "human_review"]:
        assert (n, "orchestrator", False) in edges
    assert ("extract_document", "aggregate_extractions", False) in edges
    # the orchestrator's routes are conditional (state-based), never fixed
    routed = {t for s, t, c in edges if s == "orchestrator"}
    assert {"intake", "extract_document", "rules", "computation", "review", "assembly", "human_review",
            "__end__"} <= routed
    assert all(c for s, t, c in edges if s == "orchestrator")
