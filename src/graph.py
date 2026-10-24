"""The SilverFile LangGraph.

Topology (hub and spoke around a deterministic orchestrator):

    START -> orchestrator --(conditional, state-based)--> one of:
        intake ............................. -> orchestrator   (interrupt: taxpayer)
        extract_document x N  (Send, parallel) -> aggregate_extractions -> orchestrator
        rules .............................. -> orchestrator
        computation ........................ -> orchestrator   (MCP tool calls)
        review ............................. -> orchestrator   (may send work back: cycle)
        assembly ........................... -> orchestrator
        human_review ....................... -> orchestrator   (interrupt: reviewer)
        END

The review -> computation/extraction -> review cycle is bounded by
MAX_REVIEW_PASSES; all automated hand-offs are bounded by the loop guard.
State is persisted by a SQLite checkpointer keyed by the case's thread id.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.base import Runtime
from src.agents.computation import computation_node
from src.agents.document_extraction import aggregate_extractions_node, extract_document_node
from src.agents.eligibility_rules import rules_node
from src.agents.human_review import human_review_node
from src.agents.intake import intake_node
from src.agents.orchestrator import orchestrator_node, route
from src.agents.return_assembly import assembly_node
from src.agents.review_audit import review_node
from src.state import CaseState

# Keeps LangGraph's own recursion limit well above the business loop guard
# (30 hand-offs ~ 60 super-steps), so the loop guard is what actually trips.
RECURSION_LIMIT = 250

AGENT_NODES = {
    "intake": intake_node,
    "extract_document": extract_document_node,
    "aggregate_extractions": aggregate_extractions_node,
    "rules": rules_node,
    "computation": computation_node,
    "review": review_node,
    "assembly": assembly_node,
    "human_review": human_review_node,
}


def build_graph(rt: Runtime, checkpointer=None):
    g = StateGraph(CaseState)

    def bind(name, fn):
        impl = rt.overrides.get(name, fn)
        return lambda state: impl(state, rt)

    g.add_node("orchestrator", bind("orchestrator", orchestrator_node))
    for name, fn in AGENT_NODES.items():
        g.add_node(name, bind(name, fn))
    g.add_edge(START, "orchestrator")
    g.add_conditional_edges(
        "orchestrator", route,
        {"intake": "intake", "extract_document": "extract_document", "aggregate_extractions": "aggregate_extractions",
         "rules": "rules", "computation": "computation", "review": "review", "assembly": "assembly",
         "human_review": "human_review", "end": END},
    )
    g.add_edge("extract_document", "aggregate_extractions")
    for name in ["intake", "aggregate_extractions", "rules", "computation", "review", "assembly", "human_review"]:
        g.add_edge(name, "orchestrator")
    return g.compile(checkpointer=checkpointer)


def mermaid(rt: Runtime) -> str:
    return build_graph(rt).get_graph().draw_mermaid()
