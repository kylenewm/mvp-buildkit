"""Phase 2 Spec Council - generates spec/spec.yaml from an approved plan.

Usage:
    council run spec --from-plan <plan_run_id> --project <slug> --models <list> --chair <model>
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import List, Optional, Tuple
from uuid import UUID

import yaml

from agentic_mvp_factory.artifact_deps import validate_allowed_inputs
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

SPEC_SYSTEM_PROMPT = """You are a council member generating a project specification.

Your job is to produce a valid YAML document for spec/spec.yaml based on the approved plan.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY valid YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing
- The YAML must start with these EXACT top-level keys in this order:
  schema_version: "0.1"
  updated_at: <today's date as YYYY-MM-DD>
  project:
    name: <project name>
    slug: <project slug>
    ...

Required top-level keys:
- schema_version (must be "0.1")
- updated_at (must be at TOP LEVEL, not nested)
- project (contains name, slug, north_star, done_enough_v0)
- constraints
- non_goals_v0

Optional keys: v0_mode, core_entities, cli_v0, storage_v0, open_questions, milestones_v0

Stay within V0 scope. Keep it concise and actionable.
"""

SPEC_CRITIQUE_PROMPT = """You are reviewing a spec/spec.yaml draft.

Check for:
1. Valid YAML syntax
2. All required sections present
3. Alignment with the approved plan
4. V0 scope constraints respected
5. Clarity and actionability

Provide specific, actionable feedback. Focus on correctness, not style."""

SPEC_CHAIR_PROMPT = """You are the Chair synthesizing spec drafts and critiques.

Your task: produce the FINAL spec/spec.yaml content.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY raw YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Start directly with YAML content, not with ```yaml
- The output must be valid YAML that can be written directly to a file
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing

REQUIRED STRUCTURE (use these exact top-level keys):
schema_version: "0.1"
updated_at: <YYYY-MM-DD>
project:
  name: ...
  slug: ...
  north_star: ...
  done_enough_v0: ...
constraints:
  ...
non_goals_v0:
  - ...

Incorporate the best elements from all drafts. Address critique feedback.
Output the complete YAML content and NOTHING else - no fences, no explanation."""


# =============================================================================
# COUNCIL FUNCTIONS
# =============================================================================

def _generate_spec_draft(
    run_id: str,
    model: str,
    plan_content: str,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single spec draft.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=SPEC_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"""## Approved Plan

{plan_content}

---

Generate the complete spec/spec.yaml content.
Use updated_at: {today}
Output ONLY valid YAML.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="spec_draft",
            run_id=run_id,
            stage="spec",
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
        # Store error artifact
        write_artifact(
            run_id=UUID(run_id),
            kind="error",
            content=f"Spec draft failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def _generate_spec_critique(
    run_id: str,
    model: str,
    plan_content: str,
    drafts_text: str,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a spec critique.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=SPEC_CRITIQUE_PROMPT),
        Message(
            role="user",
            content=f"""## Approved Plan

{plan_content}

## Spec Drafts

{drafts_text}

---

Provide your critique of these spec drafts.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="spec_critique",
            run_id=run_id,
            stage="spec",
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
            content=f"Spec critique failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def run_spec_council(
    plan_run_id: UUID,
    project_slug: str,
    models: List[str],
    chair_model: str,
) -> Tuple[str, List[str]]:
    """Run a spec generation council.
    
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
    
    # Validate inputs against dependency law (spec only takes plan)
    validate_allowed_inputs("spec", {
        "plan": f"kind={plan_artifacts[0].kind} from run {plan_run_id}",
    })
    
    # 2. Create new run for spec generation
    spec_run = create_run(
        project_slug=project_slug,
        task_type="spec",
        parent_run_id=plan_run_id,
    )
    run_id = str(spec_run.id)
    
    # Store the plan as a reference artifact
    write_artifact(
        run_id=spec_run.id,
        kind="packet",
        content=f"# Source Plan (from run {plan_run_id})\n\n{plan_content}",
        model=None,
    )
    
    failed_models: List[str] = []
    n_models = len(models)
    
    # 3. Generate drafts in parallel
    update_run_status(spec_run.id, "drafting")
    
    draft_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_spec_draft, run_id, model, plan_content, n_models): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                draft_ids.append(artifact_id)
            else:
                failed_models.append(model)
    
    if len(draft_ids) < 2:
        update_run_status(spec_run.id, "failed")
        raise ValueError(f"Only {len(draft_ids)} draft(s) succeeded. Need at least 2.")
    
    # 4. Generate critiques in parallel
    update_run_status(spec_run.id, "critiquing")
    
    # Format drafts for critique (no code fences to reduce chair mirroring fences)
    drafts = get_artifacts(spec_run.id, kind="draft")
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n=== DRAFT {i} (model={draft.model}) ===\n{draft.content}\n=== END DRAFT {i} ===\n"
    
    critique_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_spec_critique, run_id, model, plan_content, drafts_text, n_models): model
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
    update_run_status(spec_run.id, "synthesizing")
    
    critiques = get_artifacts(spec_run.id, kind="critique")
    critiques_text = ""
    for i, critique in enumerate(critiques, 1):
        critiques_text += f"\n### Critique {i} (from {critique.model})\n\n{critique.content}\n\n---\n"
    
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=SPEC_CHAIR_PROMPT),
        Message(
            role="user",
            content=f"""## Approved Plan

{plan_content}

## Spec Drafts

{drafts_text}

## Critiques

{critiques_text}

---

Produce the final spec/spec.yaml content.
Use updated_at: {today}
Output ONLY valid YAML, no markdown fences.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=chair_model,
            timeout=180.0,
            phase="spec_chair",
            run_id=run_id,
            stage="spec",
            role="chair",
            n_models=n_models,
        )
        
        # Validate chair output is valid YAML before storing
        spec_content = result.content
        
        # S04: Strip markdown fences if present (```yaml ... ``` or ``` ... ```)
        spec_content = spec_content.strip()
        if spec_content.startswith("```"):
            lines = spec_content.split("\n")
            # Remove opening fence line (```yaml or ```)
            lines = lines[1:]
            # Remove closing fence if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            spec_content = "\n".join(lines).strip()
        
        try:
            parsed = yaml.safe_load(spec_content)
            
            # Require top-level dict
            if not isinstance(parsed, dict):
                raise ValueError("YAML must be a mapping/dict at top level")
            
            # Require schema_version
            sv = parsed.get("schema_version")
            if sv not in ("0.1", 0.1):
                raise ValueError(f"schema_version must be 0.1, got: {sv}")
            
            # Require project key
            if "project" not in parsed:
                raise ValueError("Missing required top-level key: project")
            
            # S04: Require updated_at key
            if "updated_at" not in parsed:
                raise ValueError("Missing required top-level key: updated_at")
                
        except yaml.YAMLError as ye:
            # YAML parse error - write error artifact and fail
            error_msg = f"Chair output is not valid YAML:\n{ye}\n\nRaw output (first 2000 chars):\n{spec_content[:2000]}"
            write_artifact(
                run_id=spec_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(spec_run.id, "failed")
            raise ValueError(f"Chair produced invalid YAML: {ye}")
        except ValueError as ve:
            # Validation error
            error_msg = f"Chair output failed validation:\n{ve}\n\nRaw output (first 2000 chars):\n{spec_content[:2000]}"
            write_artifact(
                run_id=spec_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(spec_run.id, "failed")
            raise ValueError(f"Chair output failed validation: {ve}")
        
        # Store synthesis (raw chair output)
        write_artifact(
            run_id=spec_run.id,
            kind="synthesis",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        # Store as output artifact (validated, cleaned spec content)
        write_artifact(
            run_id=spec_run.id,
            kind="output",
            content=spec_content,
            model=result.model,
        )
        
    except Exception as e:
        # Only handle unexpected errors here; YAML validation errors already handled above
        if "Chair produced invalid YAML" in str(e) or "Chair output failed validation" in str(e):
            raise
        write_artifact(
            run_id=spec_run.id,
            kind="error",
            content=f"Spec chair synthesis failed: {str(e)}",
            model=chair_model,
        )
        update_run_status(spec_run.id, "failed")
        raise ValueError(f"Chair synthesis failed: {e}")
    
    # 6. Set to waiting for approval
    update_run_status(spec_run.id, "waiting_for_approval")
    
    return run_id, failed_models

