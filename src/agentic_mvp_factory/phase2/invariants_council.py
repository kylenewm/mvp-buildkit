"""Phase 2 Invariants Council - generates invariants/invariants.md from an approved plan.

Usage:
    council run invariants --from-plan <plan_run_id> --project <slug> --models <list> --chair <model>

Generates:
- invariants/invariants.md (canonical invariants file)
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import List, Optional, Tuple
from uuid import UUID

from agentic_mvp_factory.model_client import Message, get_openrouter_client, traced_complete
from agentic_mvp_factory.repo import (
    create_run,
    get_artifacts,
    get_run,
    update_run_status,
    write_artifact,
)


# =============================================================================
# PROMPTS
# =============================================================================

INVARIANTS_SYSTEM_PROMPT = """You are a council member generating project invariants.

Your job is to produce the CANONICAL invariants file for a software project.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY markdown content (NO YAML, NO code fences, NO ```markdown)
- Start directly with: # Invariants (V0)
- Keep it concise: under 200 lines total

REQUIRED STRUCTURE:
```
# Invariants (V0)

## Scope
<1-2 sentence description of what these invariants cover>

---

## I1: <Invariant Title>
**Contract**: <what must always be true>
**Rules**:
- <rule 1>
- <rule 2>
**Rationale**: <why this matters>

## I2: ...
```

REQUIRED INVARIANTS (at minimum):
- I1: No secrets in repo (credentials, API keys must be in env vars)
- I2: Patch-only edits (no sweeping refactors)
- I3: Deterministic + scoped writes (only write to allowed paths)
- I4: Namespace isolation (project_slug scoping)
- I5: Single approval checkpoint per run (V0 HITL)
- I6: Commit safety (dirty repo fail + additive-only + registry allowlist)

Each invariant must have: Contract, Rules, and Rationale.

IMPORTANT:
- This file (invariants/invariants.md) is the CANONICAL source
- .cursor/rules/10_invariants.md is only a quick reference that points here
- Keep invariants concrete and testable, not vague

Output ONLY the markdown content, nothing else."""

INVARIANTS_CRITIQUE_PROMPT = """You are reviewing an invariants file draft.

Check for:
1. Starts with "# Invariants (V0)" exactly
2. Has a Scope section
3. Includes at least I1-I6 (the required invariants)
4. Each invariant has Contract, Rules, and Rationale
5. Concise (under 200 lines)
6. No YAML or code fences wrapping the content
7. No contradictions between invariants
8. Invariants are concrete and testable, not vague platitudes
9. Mentions that invariants/invariants.md is the canonical source

Provide specific, actionable feedback. Be concise - 3-5 key points maximum."""

INVARIANTS_CHAIR_PROMPT = """You are the Chair synthesizing invariants drafts and critiques.

Your task: produce the FINAL invariants/invariants.md file.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY raw markdown (NO code fences, NO ```markdown, NO YAML)
- Start directly with: # Invariants (V0)
- Keep it under 200 lines

REQUIRED STRUCTURE:
# Invariants (V0)

## Scope
<description>

---

## I1: <Title>
**Contract**: ...
**Rules**: ...
**Rationale**: ...

(continue for I2-I6+)

REQUIRED INVARIANTS:
- I1: No secrets in repo
- I2: Patch-only edits
- I3: Deterministic + scoped writes
- I4: Namespace isolation
- I5: Single approval checkpoint (V0 HITL)
- I6: Commit safety rails

Include a note that this file (invariants/invariants.md) is the canonical source.

Incorporate the best elements from all drafts. Address critique feedback.
Output the complete markdown and NOTHING else."""


# =============================================================================
# COUNCIL FUNCTIONS
# =============================================================================

def _generate_invariants_draft(
    run_id: str,
    model: str,
    plan_content: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single invariants markdown draft.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=INVARIANTS_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"""## Approved Plan

{plan_content}

---

Generate the complete invariants/invariants.md file.
Output ONLY markdown, starting with # Invariants (V0).""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="invariants_draft",
            run_id=run_id,
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
        # Store error artifact
        write_artifact(
            run_id=UUID(run_id),
            kind="error",
            content=f"Invariants draft failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def _generate_invariants_critique(
    run_id: str,
    model: str,
    plan_content: str,
    drafts_text: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate an invariants critique.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=INVARIANTS_CRITIQUE_PROMPT),
        Message(
            role="user",
            content=f"""## Approved Plan

{plan_content}

## Invariants Drafts

{drafts_text}

---

Provide your critique of these invariants drafts.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="invariants_critique",
            run_id=run_id,
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
            content=f"Invariants critique failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def run_invariants_council(
    plan_run_id: UUID,
    project_slug: str,
    models: List[str],
    chair_model: str,
) -> Tuple[str, List[str]]:
    """Run an invariants generation council.
    
    Args:
        plan_run_id: The approved plan run ID
        project_slug: Project namespace
        models: List of model IDs for drafts/critiques
        chair_model: Model ID for chair synthesis
        
    Returns:
        (new_run_id, failed_models)
        
    Raises:
        ValueError: If plan is missing, not approved, or models < 2
    """
    # 0. Fast preflight: require at least 2 models
    if len(models) < 2:
        raise ValueError(f"At least 2 models required, got {len(models)}")
    
    # 1. Load and validate the plan
    plan_run = get_run(plan_run_id)
    if not plan_run:
        raise ValueError(f"Plan run not found: {plan_run_id}")
    
    # Check plan is approved (ready_to_commit or completed)
    if plan_run.status not in ("ready_to_commit", "completed"):
        raise ValueError(
            f"Plan run is not approved (status: {plan_run.status}). "
            f"Approve it first with: council approve {plan_run_id} --approve"
        )
    
    # Get the plan artifact
    plan_artifacts = get_artifacts(plan_run_id, kind="plan")
    if not plan_artifacts:
        # Fallback to synthesis if plan artifact doesn't exist
        plan_artifacts = get_artifacts(plan_run_id, kind="synthesis")
    if not plan_artifacts:
        raise ValueError(f"No plan artifact found for run: {plan_run_id}")
    
    plan_content = plan_artifacts[0].content
    
    # 2. Create new run for invariants generation
    inv_run = create_run(
        project_slug=project_slug,
        task_type="invariants",
        parent_run_id=plan_run_id,
    )
    run_id = str(inv_run.id)
    
    # Store the plan as a reference artifact
    write_artifact(
        run_id=inv_run.id,
        kind="packet",
        content=f"# Source Plan (from run {plan_run_id})\n\n{plan_content}",
        model=None,
    )
    
    failed_models: List[str] = []
    
    # 3. Generate drafts in parallel
    update_run_status(inv_run.id, "drafting")
    
    draft_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {
            executor.submit(_generate_invariants_draft, run_id, model, plan_content): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                draft_ids.append(artifact_id)
            else:
                failed_models.append(model)
    
    if len(draft_ids) < 2:
        update_run_status(inv_run.id, "failed")
        raise ValueError(f"Only {len(draft_ids)} draft(s) succeeded. Need at least 2.")
    
    # 4. Generate critiques in parallel
    update_run_status(inv_run.id, "critiquing")
    
    # Format drafts for critique (no code fences to reduce chair mirroring fences)
    drafts = get_artifacts(inv_run.id, kind="draft")
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n=== DRAFT {i} (model={draft.model}) ===\n{draft.content}\n=== END DRAFT {i} ===\n"
    
    critique_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {
            executor.submit(_generate_invariants_critique, run_id, model, plan_content, drafts_text): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                critique_ids.append(artifact_id)
            else:
                if model not in failed_models:
                    failed_models.append(model)
    
    # 5. Chair synthesis
    update_run_status(inv_run.id, "synthesizing")
    
    critiques = get_artifacts(inv_run.id, kind="critique")
    critiques_text = ""
    for i, critique in enumerate(critiques, 1):
        critiques_text += f"\n### Critique {i} (from {critique.model})\n\n{critique.content}\n\n---\n"
    
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=INVARIANTS_CHAIR_PROMPT),
        Message(
            role="user",
            content=f"""## Approved Plan

{plan_content}

## Invariants Drafts

{drafts_text}

## Critiques

{critiques_text}

---

Produce the final invariants/invariants.md file.
Output ONLY markdown, starting with # Invariants (V0).""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=chair_model,
            timeout=180.0,
            phase="invariants_chair",
            run_id=run_id,
        )
        
        # Clean chair output
        invariants_content = result.content.strip()
        
        # Strip markdown fences if present (```markdown ... ``` or ``` ... ```)
        if invariants_content.startswith("```"):
            lines = invariants_content.split("\n")
            # Remove opening fence line
            lines = lines[1:]
            # Remove closing fence if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            invariants_content = "\n".join(lines).strip()
        
        # Validate minimal requirements
        if "# Invariants (V0)" not in invariants_content:
            error_msg = f"Chair output missing required header '# Invariants (V0)'.\n\nRaw output (first 1000 chars):\n{invariants_content[:1000]}"
            write_artifact(
                run_id=inv_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(inv_run.id, "failed")
            raise ValueError("Chair output missing required header '# Invariants (V0)'")
        
        if "invariants/invariants.md" not in invariants_content.lower():
            error_msg = f"Chair output does not mention 'invariants/invariants.md' as canonical.\n\nRaw output (first 1000 chars):\n{invariants_content[:1000]}"
            write_artifact(
                run_id=inv_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(inv_run.id, "failed")
            raise ValueError("Chair output does not mention 'invariants/invariants.md' as canonical source")
        
        # Store synthesis (raw chair output)
        write_artifact(
            run_id=inv_run.id,
            kind="synthesis",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        # Store as output artifact (validated, cleaned markdown)
        write_artifact(
            run_id=inv_run.id,
            kind="output",
            content=invariants_content,
            model=result.model,
        )
        
    except Exception as e:
        # Only handle unexpected errors here
        if "Chair output missing" in str(e) or "does not mention" in str(e):
            raise
        write_artifact(
            run_id=inv_run.id,
            kind="error",
            content=f"Invariants chair synthesis failed: {str(e)}",
            model=chair_model,
        )
        update_run_status(inv_run.id, "failed")
        raise ValueError(f"Chair synthesis failed: {e}")
    
    # 6. Set to waiting for approval
    update_run_status(inv_run.id, "waiting_for_approval")
    
    return run_id, failed_models

