"""LangGraph wrapper for execution loop - trace harness only.

This wraps the existing execution primitives in a LangGraph StateGraph
so that each phase is visible as a node in LangGraph Studio.

NO new orchestration logic. NO retries beyond what execution_loop already does.
Same semantics, just structured visibility.
"""

from typing import Any, Optional
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END

from agentic_mvp_factory.execution_state import ExecutionState
from agentic_mvp_factory.execution_loop import execution_node, refactor_node


class ExecutionGraphState(TypedDict):
    """State for the execution graph - mirrors ExecutionState fields."""
    task_id: str
    file_path: str
    retries: int
    max_retries: int
    last_stdout: Optional[str]
    last_stderr: Optional[str]
    exit_code: Optional[int]
    status: str
    # Model client reference (passed through state)
    model_client: Any


def state_to_execution_state(state: ExecutionGraphState) -> ExecutionState:
    """Convert graph state to ExecutionState dataclass."""
    return ExecutionState(
        task_id=state["task_id"],
        file_path=state["file_path"],
        retries=state["retries"],
        max_retries=state["max_retries"],
        last_stdout=state.get("last_stdout"),
        last_stderr=state.get("last_stderr"),
        exit_code=state.get("exit_code"),
        status=state["status"],
    )


def execution_state_to_dict(es: ExecutionState, model_client: Any) -> dict:
    """Convert ExecutionState back to graph state dict."""
    return {
        "task_id": es.task_id,
        "file_path": es.file_path,
        "retries": es.retries,
        "max_retries": es.max_retries,
        "last_stdout": es.last_stdout,
        "last_stderr": es.last_stderr,
        "exit_code": es.exit_code,
        "status": es.status,
        "model_client": model_client,
    }


# --- Graph Nodes ---

def node_start(state: ExecutionGraphState) -> ExecutionGraphState:
    """Initialize execution - set status to RUNNING."""
    return {**state, "status": "RUNNING"}


def node_execute(state: ExecutionGraphState) -> ExecutionGraphState:
    """Execute the file via subprocess."""
    es = state_to_execution_state(state)
    es = execution_node(es)
    return execution_state_to_dict(es, state["model_client"])


def node_refactor(state: ExecutionGraphState) -> ExecutionGraphState:
    """Attempt to fix code using model (if failed and retries available)."""
    es = state_to_execution_state(state)
    es = refactor_node(es, state["model_client"])
    return execution_state_to_dict(es, state["model_client"])


def node_retry_execute(state: ExecutionGraphState) -> ExecutionGraphState:
    """Re-execute after refactor."""
    es = state_to_execution_state(state)
    es = execution_node(es)
    return execution_state_to_dict(es, state["model_client"])


# --- Conditional Edges ---

def should_refactor(state: ExecutionGraphState) -> str:
    """Decide whether to refactor or end."""
    if state["status"] == "SUCCESS":
        return "end"
    if state["status"] == "FAILED" and state["retries"] < state["max_retries"]:
        return "refactor"
    return "end"


# --- Graph Builder ---

def build_execution_graph() -> StateGraph:
    """
    Build the execution graph.
    
    Flow:
        start -> execute -> (success?) -> end
                         -> (failed + retries?) -> refactor -> retry_execute -> end
    """
    graph = StateGraph(ExecutionGraphState)
    
    # Add nodes
    graph.add_node("start", node_start)
    graph.add_node("execute", node_execute)
    graph.add_node("refactor", node_refactor)
    graph.add_node("retry_execute", node_retry_execute)
    
    # Set entry point
    graph.set_entry_point("start")
    
    # Add edges
    graph.add_edge("start", "execute")
    graph.add_conditional_edges(
        "execute",
        should_refactor,
        {
            "end": END,
            "refactor": "refactor",
        }
    )
    graph.add_edge("refactor", "retry_execute")
    graph.add_edge("retry_execute", END)
    
    return graph


def run_execution_graph(
    task_id: str,
    file_path: str,
    model_client: Any,
    max_retries: int = 1,
) -> ExecutionState:
    """
    Run the execution graph and return final state.
    
    This is the traced equivalent of run_execution_loop().
    """
    graph = build_execution_graph()
    compiled = graph.compile()
    
    initial_state: ExecutionGraphState = {
        "task_id": task_id,
        "file_path": file_path,
        "retries": 0,
        "max_retries": max_retries,
        "last_stdout": None,
        "last_stderr": None,
        "exit_code": None,
        "status": "PENDING",
        "model_client": model_client,
    }
    
    # Run the graph
    final_state = compiled.invoke(initial_state)
    
    # Convert back to ExecutionState
    return state_to_execution_state(final_state)


# Pre-compiled graph for Studio discovery
execution_graph = build_execution_graph().compile()

