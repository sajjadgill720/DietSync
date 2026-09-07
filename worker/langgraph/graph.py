"""
worker/langgraph/graph.py
LangGraph workflow for DietSync's clinical drug interaction checker.

Architecture per PROJECT_SPEC.md:
- Explicit state graph enforcing safety gates structurally rather than via prompt-level agent loops.
- Flow:
  START -> fetch_context -> check_interaction -> verify_groundedness
  Conditional edge on is_grounded:
    True  -> format_grounded_answer -> END
    False -> format_unverifiable_answer -> END
- Deliberately NOT cyclic: a failed verification terminates to 'unverifiable'
  instead of looping back to hallucinate another answer.
"""

from langgraph.graph import END, START, StateGraph
from worker.langgraph.nodes import (
    InteractionState,
    check_allergy,
    check_food_interaction,
    check_interaction,
    fetch_context,
    format_grounded_answer,
    format_unverifiable_answer,
    verify_groundedness,
)


def route_groundedness(state: InteractionState) -> str:
    """
    Conditional routing function:
    - If is_grounded is True, route to format_grounded_answer
    - Otherwise, route to format_unverifiable_answer
    """
    if state.get("is_grounded") is True:
        return "format_grounded_answer"
    return "format_unverifiable_answer"


def build_graph():
    """
    Constructs and compiles the interaction checker StateGraph.
    Flow per PROJECT_SPEC.md lines 111-123:
    START -> fetch_context -> check_interaction -> check_food_interaction -> check_allergy -> verify_groundedness
    Conditional edge on is_grounded:
      True  -> format_grounded_answer -> END
      False -> format_unverifiable_answer -> END
    """
    builder = StateGraph(InteractionState)

    # Register all nodes
    builder.add_node("fetch_context", fetch_context)
    builder.add_node("check_interaction", check_interaction)
    builder.add_node("check_food_interaction", check_food_interaction)
    builder.add_node("check_allergy", check_allergy)
    builder.add_node("verify_groundedness", verify_groundedness)
    builder.add_node("format_grounded_answer", format_grounded_answer)
    builder.add_node("format_unverifiable_answer", format_unverifiable_answer)

    # Core flow
    builder.add_edge(START, "fetch_context")
    builder.add_edge("fetch_context", "check_interaction")
    builder.add_edge("check_interaction", "check_food_interaction")
    builder.add_edge("check_food_interaction", "check_allergy")
    builder.add_edge("check_allergy", "verify_groundedness")

    # Conditional routing based on independent verification outcome
    builder.add_conditional_edges(
        "verify_groundedness",
        route_groundedness,
        {
            "format_grounded_answer": "format_grounded_answer",
            "format_unverifiable_answer": "format_unverifiable_answer",
        },
    )

    # Terminal edges
    builder.add_edge("format_grounded_answer", END)
    builder.add_edge("format_unverifiable_answer", END)

    return builder.compile()


# Default compiled graph instance
interaction_graph = build_graph()
graph = interaction_graph  # Alias


# ------------------------------------------------------------------------------
# LangSmith Tracing Wrapper
# ------------------------------------------------------------------------------
import os
from typing import Any, Dict, Optional
from langsmith import traceable

# Set default LangChain / LangSmith project if not specified
os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "dietsync"))


@traceable(
    name="dietsync_interaction_checker",
    run_type="chain",
    tags=["dietsync", "interaction_check", "clinical_safety"],
)
def invoke_interaction_graph(
    state: InteractionState,
    config: Optional[Dict[str, Any]] = None,
) -> InteractionState:
    """
    Executes the interaction checking StateGraph with LangSmith tracing enabled.
    Attaches drug metadata (names, RxCUIs) to the LangSmith trace run for observability.
    """
    cfg = dict(config or {})
    metadata = cfg.setdefault("metadata", {})
    drug_a = state.get("drug_a", {})
    drug_b = state.get("drug_b", {})
    metadata.setdefault("drug_a_name", drug_a.get("generic_name") or drug_a.get("brand_name"))
    metadata.setdefault("drug_a_rxcui", drug_a.get("rxcui"))
    metadata.setdefault("drug_b_name", drug_b.get("generic_name") or drug_b.get("brand_name"))
    metadata.setdefault("drug_b_rxcui", drug_b.get("rxcui"))

    return graph.invoke(state, config=cfg)


# Convenient alias
run_interaction_graph = invoke_interaction_graph

