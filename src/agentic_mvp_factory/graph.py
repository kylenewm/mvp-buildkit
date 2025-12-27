"""LangGraph workflow for council runner.

This module is designed to be importable standalone for LangGraph Studio.
Usage:
    from agentic_mvp_factory.graph import build_council_graph
    graph = build_council_graph()

Workflow: load_packet -> draft_generate -> critique_generate -> chair_synthesize -> pause_for_approval
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, List, Optional, Tuple
from typing_extensions import TypedDict
from uuid import UUID

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph


# =============================================================================
# STATE DEFINITION (Studio-readable typed state)
# =============================================================================

class CouncilState(TypedDict, total=False):
    """Typed state for the council workflow.
    
    All fields are explicit for LangGraph Studio inspection.
    """
    # Run context
    run_id: str  # String for Studio readability
    project_slug: str
    
    # Phase tracking (for Studio visibility)
    phase: str  # created, loading, drafting, critiquing, synthesizing, waiting_for_approval, completed, failed
    
    # Configuration
    models: List[str]
    chair_model: str
    
    # Input
    packet_path: str
    packet_content: str
    
    # S03: Phase 0 context injection
    context_path: Optional[str]
    context_content: Optional[str]
    
    # Artifact IDs (as strings for Studio readability)
    packet_artifact_id: Optional[str]
    draft_artifact_ids: List[str]
    critique_artifact_ids: List[str]
    synthesis_artifact_id: Optional[str]
    decision_artifact_id: Optional[str]
    
    # Counts for Studio visibility
    draft_count: int
    critique_count: int
    
    # Error tracking
    error: Optional[str]
    failed_models: List[str]


# =============================================================================
# HELPER FUNCTIONS (not nodes)
# =============================================================================

def _update_run_status(run_id: str, status: str) -> None:
    """Update the status of a run in the database."""
    from agentic_mvp_factory.db import get_cursor
    
    with get_cursor() as cursor:
        cursor.execute(
            "UPDATE runs SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, run_id),
        )


def _generate_single_draft(
    run_id: str,
    model: str,
    packet_content: str,
    context_content: Optional[str] = None,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single draft for one model.
    
    Args:
        run_id: The run ID
        model: Model ID to use
        packet_content: The planning packet content
        context_content: Optional Phase 0 context pack content (S03)
        n_models: Number of drafter models (for token budget calculation)
    
    Returns:
        Tuple of (model, artifact_id or None, error_message or None)
    """
    from agentic_mvp_factory.model_client import Message, get_openrouter_client, traced_complete
    from agentic_mvp_factory.repo import write_artifact
    
    client = get_openrouter_client()
    
    system_prompt = """You are a council member reviewing a planning packet.
Your job is to produce a concrete, implementable plan based on the packet's requirements.
Be specific, actionable, and stay within the stated constraints.
Output a coherent plan with clear sections."""
    
    # S03: Build user message with optional context
    user_content = f"## Planning Packet\n\n{packet_content}"
    
    if context_content:
        user_content += f"\n\n## Context Pack (Phase 0 Lite)\n\n{context_content}"
    
    user_content += "\n\n---\n\nProduce your implementation plan."
    
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_content),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="draft",
            run_id=run_id,
            stage="plan",
            role="draft",
            n_models=n_models,
        )
        
        artifact = write_artifact(
            run_id=UUID(run_id),
            kind="draft",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        return (model, str(artifact.id), None)
    except Exception as e:
        write_artifact(
            run_id=UUID(run_id),
            kind="error",
            content=f"Draft generation failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def _generate_single_critique(
    run_id: str,
    model: str,
    drafts_text: str,
    context_content: Optional[str] = None,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single critique for one model.
    
    Args:
        run_id: The run ID
        model: Model ID to use
        drafts_text: Formatted text of all drafts
        context_content: Optional Phase 0 context pack content (S03)
        n_models: Number of drafter models (for token budget calculation)
    
    Returns:
        Tuple of (model, artifact_id or None, error_message or None)
    """
    from agentic_mvp_factory.model_client import Message, get_openrouter_client, traced_complete
    from agentic_mvp_factory.repo import write_artifact
    
    client = get_openrouter_client()
    
    system_prompt = """You are a council member critiquing implementation plans.
Review all drafts and provide constructive critique:
- Identify strengths and weaknesses
- Note gaps or unclear areas
- Suggest specific improvements
- Flag any constraint violations
Be direct and specific."""
    
    # S03: Build user message with optional context
    user_content = f"## Drafts to Critique\n{drafts_text}"
    
    if context_content:
        user_content = f"## Context Pack (Phase 0 Lite)\n\n{context_content}\n\n" + user_content
    
    user_content += "\n\nProvide your critique of these drafts."
    
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_content),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="critique",
            run_id=run_id,
            stage="plan",
            role="critique",
            n_models=n_models,
        )
        
        artifact = write_artifact(
            run_id=UUID(run_id),
            kind="critique",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        return (model, str(artifact.id), None)
    except Exception as e:
        write_artifact(
            run_id=UUID(run_id),
            kind="error",
            content=f"Critique generation failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


# =============================================================================
# NODE FUNCTIONS (semantic names for Studio)
# =============================================================================

def load_packet(state: CouncilState) -> CouncilState:
    """Load the packet file and store as artifact."""
    from agentic_mvp_factory.repo import write_artifact
    
    packet_path = state.get("packet_path", "")
    run_id = state.get("run_id", "")
    context_path = state.get("context_path")  # S03: optional context path
    
    # Handle missing required fields (e.g., when invoked from Studio)
    if not packet_path:
        return {
            **state,
            "phase": "failed",
            "error": "packet_path is required",
        }
    if not run_id:
        return {
            **state,
            "phase": "failed",
            "error": "run_id is required",
        }
    
    # Read packet content
    path = Path(packet_path)
    if not path.exists():
        return {
            **state,
            "phase": "failed",
            "error": f"Packet file not found: {packet_path}",
        }
    
    content = path.read_text()
    
    # S03: Append context note if provided
    artifact_content = content
    if context_path:
        artifact_content += f"\n\n---\n(context provided: {context_path})"
    
    # Store as artifact
    artifact = write_artifact(
        run_id=UUID(run_id),
        kind="packet",
        content=artifact_content,
        model=None,
    )
    
    return {
        **state,
        "phase": "loading",
        "packet_content": content,  # Original content for prompts
        "packet_artifact_id": str(artifact.id),
    }


def draft_generate(state: CouncilState) -> CouncilState:
    """Generate drafts from all models in parallel."""
    run_id = state.get("run_id", "")
    models = state.get("models", [])
    packet_content = state.get("packet_content", "")
    context_content = state.get("context_content")  # S03: optional context
    
    # Handle missing required fields
    if not run_id or not models or not packet_content:
        return {
            **state,
            "phase": "failed",
            "error": "Missing required state: run_id, models, or packet_content",
        }
    
    # Update status
    _update_run_status(run_id, "drafting")
    
    draft_ids: List[str] = []
    failed_models: List[str] = []
    
    # Run drafts in parallel (S03: pass context)
    n_models = len(models)
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_single_draft, run_id, model, packet_content, context_content, n_models): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                draft_ids.append(artifact_id)
            else:
                failed_models.append(model)
    
    # Check if we have enough drafts to continue
    if len(draft_ids) < 2:
        error_msg = f"Only {len(draft_ids)} draft(s) succeeded. Need at least 2. Failed: {failed_models}"
        _update_run_status(run_id, "failed")
        return {
            **state,
            "phase": "failed",
            "error": error_msg,
            "draft_artifact_ids": draft_ids,
            "draft_count": len(draft_ids),
            "failed_models": failed_models,
        }
    
    return {
        **state,
        "phase": "drafting",
        "draft_artifact_ids": draft_ids,
        "draft_count": len(draft_ids),
        "failed_models": failed_models,
    }


def critique_generate(state: CouncilState) -> CouncilState:
    """Generate critiques from all models in parallel (each critiques all drafts)."""
    from agentic_mvp_factory.repo import get_artifacts
    
    run_id = state.get("run_id", "")
    models = state.get("models", [])
    failed_models = list(state.get("failed_models", []))
    context_content = state.get("context_content")  # S03: optional context
    
    # Handle missing required fields
    if not run_id or not models:
        return {
            **state,
            "phase": "failed",
            "error": "Missing required state: run_id or models",
        }
    
    # Update status
    _update_run_status(run_id, "critiquing")
    
    # Fetch all drafts
    drafts = get_artifacts(UUID(run_id), kind="draft")
    if not drafts:
        return {
            **state,
            "phase": "failed",
            "error": "No drafts to critique",
        }
    
    # Format drafts for critique
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n## Draft {i} (from {draft.model})\n\n{draft.content}\n\n---\n"
    
    critique_ids: List[str] = []
    n_models = len(models)
    
    # Run critiques in parallel (S03: pass context)
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_single_critique, run_id, model, drafts_text, context_content, n_models): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                critique_ids.append(artifact_id)
            else:
                if model not in failed_models:
                    failed_models.append(model)
    
    return {
        **state,
        "phase": "critiquing",
        "critique_artifact_ids": critique_ids,
        "critique_count": len(critique_ids),
        "failed_models": failed_models,
    }


def chair_synthesize(state: CouncilState) -> CouncilState:
    """Chair synthesizes drafts and critiques into final plan + decision packet."""
    from agentic_mvp_factory.model_client import Message, get_openrouter_client, traced_complete
    from agentic_mvp_factory.repo import get_artifacts, write_artifact
    
    run_id = state.get("run_id", "")
    chair_model = state.get("chair_model", "")
    packet_content = state.get("packet_content", "")
    context_content = state.get("context_content")  # S03: optional context
    n_models = len(state.get("models", []))  # For token budget calculation
    
    # Handle missing required fields
    if not run_id or not chair_model:
        return {
            **state,
            "phase": "failed",
            "error": "Missing required state: run_id or chair_model",
        }
    
    # Update status
    _update_run_status(run_id, "synthesizing")
    
    # Fetch drafts and critiques
    drafts = get_artifacts(UUID(run_id), kind="draft")
    critiques = get_artifacts(UUID(run_id), kind="critique")
    
    # Format for chair
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n### Draft {i} (from {draft.model})\n\n{draft.content}\n\n---\n"
    
    critiques_text = ""
    for i, critique in enumerate(critiques, 1):
        critiques_text += f"\n### Critique {i} (from {critique.model})\n\n{critique.content}\n\n---\n"
    
    client = get_openrouter_client()
    
    # Synthesis prompt
    synthesis_system = """You are the Chair of a multi-model council.
Synthesize the drafts and critiques into a single, coherent implementation plan.

Rules:
- Do not average into mush; pick a direction and justify it
- If council is split, choose one approach and explain the tradeoff
- Be concrete and actionable
- Stay within V0 constraints

Output EXACTLY two markdown sections with these EXACT headings (use ## prefix):

## SYNTHESIS
The final unified plan

## DECISION_PACKET
A compact summary with key decisions, next actions, and risks

Do NOT number the sections. Use ## SYNTHESIS and ## DECISION_PACKET exactly."""
    
    # S03: Build user message with optional context
    user_content = f"## Original Packet\n{packet_content}"
    
    if context_content:
        user_content += f"\n\n## Context Pack (Phase 0 Lite)\n\n{context_content}"
    
    user_content += f"""

## Council Drafts
{drafts_text}

## Council Critiques
{critiques_text}

---

Produce your synthesis and decision packet."""
    
    messages = [
        Message(role="system", content=synthesis_system),
        Message(role="user", content=user_content),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=chair_model,
            timeout=180.0,
            phase="chair",
            run_id=run_id,
            stage="plan",
            role="chair",
            n_models=n_models,
        )
        
        # Store synthesis
        synthesis_artifact = write_artifact(
            run_id=UUID(run_id),
            kind="synthesis",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        # Extract decision packet if present, otherwise duplicate synthesis
        content = result.content
        decision_content = content
        if "DECISION_PACKET" in content:
            parts = content.split("DECISION_PACKET")
            if len(parts) > 1:
                decision_content = "DECISION_PACKET" + parts[-1]
        
        decision_artifact = write_artifact(
            run_id=UUID(run_id),
            kind="decision_packet",
            content=decision_content,
            model=result.model,
        )
        
        # Store synthesis verbatim as plan artifact (no processing)
        plan_artifact = write_artifact(
            run_id=UUID(run_id),
            kind="plan",
            content=result.content,
            model=result.model,
        )
        
        return {
            **state,
            "phase": "synthesizing",
            "synthesis_artifact_id": str(synthesis_artifact.id),
            "decision_artifact_id": str(decision_artifact.id),
        }
        
    except Exception as e:
        write_artifact(
            run_id=UUID(run_id),
            kind="error",
            content=f"Chair synthesis failed: {str(e)}",
            model=chair_model,
        )
        _update_run_status(run_id, "failed")
        return {
            **state,
            "phase": "failed",
            "error": str(e),
        }


def pause_for_approval(state: CouncilState) -> CouncilState:
    """Pause the workflow for human approval (HITL checkpoint)."""
    run_id = state.get("run_id", "")
    
    if not run_id:
        return {
            **state,
            "phase": "failed",
            "error": "Missing required state: run_id",
        }
    
    # Update status to waiting_for_approval
    _update_run_status(run_id, "waiting_for_approval")
    
    return {
        **state,
        "phase": "waiting_for_approval",
    }


# =============================================================================
# GRAPH CONSTRUCTION (Studio-compatible)
# =============================================================================

def build_council_graph() -> CompiledStateGraph:
    """Build the council workflow graph.
    
    This function is designed to be called standalone by LangGraph Studio.
    No CLI context, no sys.exit, no implicit environment reads.
    
    Returns:
        CompiledGraph ready for invocation or Studio inspection.
    """
    # Create graph with typed state
    graph = StateGraph(CouncilState)
    
    # Add nodes with semantic names
    graph.add_node("load_packet", load_packet)
    graph.add_node("draft_generate", draft_generate)
    graph.add_node("critique_generate", critique_generate)
    graph.add_node("chair_synthesize", chair_synthesize)
    graph.add_node("pause_for_approval", pause_for_approval)
    
    # Define edges
    graph.set_entry_point("load_packet")
    graph.add_edge("load_packet", "draft_generate")
    graph.add_edge("draft_generate", "critique_generate")
    graph.add_edge("critique_generate", "chair_synthesize")
    graph.add_edge("chair_synthesize", "pause_for_approval")
    graph.add_edge("pause_for_approval", END)
    
    return graph.compile()


# =============================================================================
# CLI RUNNER (kept separate from graph construction)
# =============================================================================

def run_council(
    project_slug: str,
    packet_path: str,
    models: List[str],
    chair_model: str,
    on_progress: Optional[callable] = None,
    context_content: Optional[str] = None,
    context_path: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    Run the council workflow (CLI entrypoint).
    
    Args:
        project_slug: Project namespace
        packet_path: Path to the planning packet
        models: List of model IDs to use for drafts/critiques
        chair_model: Model ID for chair synthesis
        on_progress: Optional callback for progress updates
        context_content: Optional Phase 0 context pack content (S03)
        context_path: Optional path to context file for artifact note (S03)
    
    Returns:
        Tuple of (run_id as string, list of failed models)
    """
    from agentic_mvp_factory.repo import create_run
    
    # Create run
    run = create_run(project_slug=project_slug, task_type="plan")
    run_id_str = str(run.id)
    
    # Build initial state
    initial_state: CouncilState = {
        "run_id": run_id_str,
        "project_slug": project_slug,
        "phase": "created",
        "models": models,
        "chair_model": chair_model,
        "packet_path": packet_path,
        "packet_content": "",
        "context_content": context_content,  # S03
        "context_path": context_path,  # S03
        "packet_artifact_id": None,
        "draft_artifact_ids": [],
        "critique_artifact_ids": [],
        "synthesis_artifact_id": None,
        "decision_artifact_id": None,
        "plan_artifact_id": None,
        "draft_count": 0,
        "critique_count": 0,
        "error": None,
        "failed_models": [],
    }
    
    # Build and run graph
    graph = build_council_graph()
    
    # Run the graph
    final_state = graph.invoke(initial_state)
    
    failed_models = final_state.get("failed_models", [])
    
    return run_id_str, failed_models


# =============================================================================
# STANDALONE GRAPH INSTANCE (for LangGraph Studio)
# =============================================================================

# This allows Studio to import and visualize the graph directly
graph = build_council_graph()
