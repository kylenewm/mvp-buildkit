"""Phase 2 Tracker Council - generates tracker/factory_tracker.yaml from an approved plan.

Usage:
    council run tracker --from-plan <plan_run_id> --project <slug> --models <list> --chair <model>
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
    get_latest_approved_run_by_task_type,
    get_run,
    update_run_status,
    write_artifact,
)


# =============================================================================
# PROMPTS
# =============================================================================

TRACKER_SYSTEM_PROMPT = """You are a council member generating a project tracker (step-by-step implementation plan).

Your job is to produce a valid YAML document for tracker/factory_tracker.yaml based on the approved plan.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY valid YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing
- For command names, write them plain: council run (not 'council run')
- The YAML must start with these EXACT top-level keys:
  schema_version: "0.1"
  build_id: <from plan if available, else use project slug>
  updated_at: <today's date as YYYY-MM-DD>
  steps: [list of implementation steps]

Each step in the steps list MUST have:
- id: S01, S02, etc (incremental)
- title: short name of the step
- intent: what this step accomplishes
- deliverables: list of concrete outputs
- acceptance: list of criteria for step completion
- proof: list of shell commands to verify
- allowed_files: list of files this step may touch

Guidelines:
- Keep steps focused and atomic (1 sitting each)
- Order steps by dependency
- Each step should take 30-60 minutes max
- Proof commands must be runnable and deterministic
- 6-10 steps is typical for a V0 build

Output ONLY valid YAML, nothing else.
"""

TRACKER_CRITIQUE_PROMPT = """You are reviewing a tracker/factory_tracker.yaml draft.

Check for:
1. Valid YAML syntax (no markdown fences, proper indentation)
2. All required fields present for each step (id, title, intent, deliverables, acceptance, proof, allowed_files)
3. Steps are properly ordered by dependency
4. Steps are atomic and achievable in one sitting
5. Proof commands are concrete and runnable
6. No scope creep - stays within V0 bounds
7. Alignment with the approved plan

Provide specific, actionable feedback. Focus on correctness and completeness, not style.
Be concise - 3-5 key points maximum."""

TRACKER_CHAIR_PROMPT = """You are the Chair synthesizing tracker drafts and critiques.

Your task: produce the FINAL tracker/factory_tracker.yaml content.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY raw YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Start directly with YAML content, not with ```yaml
- The output must be valid YAML that can be written directly to a file
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing
- For command names in strings, just write them plain: council run (not 'council run')

REQUIRED STRUCTURE:
schema_version: "0.1"
build_id: <from plan or project>
updated_at: <YYYY-MM-DD>
steps:
  - id: S01
    title: ...
    intent: ...
    deliverables:
      - ...
    acceptance:
      - ...
    proof:
      - ...
    allowed_files:
      - ...
  - id: S02
    ...

Incorporate the best elements from all drafts. Address critique feedback.
Ensure steps are properly ordered, atomic, and verifiable.
Output the complete YAML content and NOTHING else - no fences, no explanation."""


# =============================================================================
# COUNCIL FUNCTIONS
# =============================================================================

def _generate_tracker_draft(
    run_id: str,
    model: str,
    spec_content: str,
    invariants_content: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single tracker draft.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=TRACKER_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

---

Generate the complete tracker/factory_tracker.yaml content.
Each step must respect the invariants listed above.
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
            phase="tracker_draft",
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
            content=f"Tracker draft failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def _generate_tracker_critique(
    run_id: str,
    model: str,
    spec_content: str,
    invariants_content: str,
    drafts_text: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a tracker critique.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=TRACKER_CRITIQUE_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Tracker Drafts

{drafts_text}

---

Provide your critique of these tracker drafts.
Check that each step respects the invariants.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="tracker_critique",
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
            content=f"Tracker critique failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def run_tracker_council(
    plan_run_id: UUID,
    project_slug: str,
    models: List[str],
    chair_model: str,
) -> Tuple[str, List[str]]:
    """Run a tracker generation council.
    
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
    
    # 1. Validate parent plan run exists and is approved
    plan_run = get_run(plan_run_id)
    if not plan_run:
        raise ValueError(f"Plan run not found: {plan_run_id}")
    
    if plan_run.status not in ("ready_to_commit", "completed"):
        raise ValueError(
            f"Plan run is not approved (status: {plan_run.status}). "
            f"Approve it first with: council approve {plan_run_id} --approve"
        )
    
    # 2. Load SPEC artifact (tracker depends on spec, not plan directly)
    spec_run = get_latest_approved_run_by_task_type(plan_run_id, "spec")
    if not spec_run:
        raise ValueError(
            f"No approved spec run found for plan {plan_run_id}. "
            f"Run spec council first: council run spec --from-plan {plan_run_id} ..."
        )
    
    spec_artifacts = get_artifacts(spec_run.id, kind="output")
    if not spec_artifacts:
        raise ValueError(f"No spec output artifact found for spec run: {spec_run.id}")
    
    spec_content = spec_artifacts[0].content
    
    # 3. Load INVARIANTS artifact (tracker also depends on invariants)
    inv_run = get_latest_approved_run_by_task_type(plan_run_id, "invariants")
    if not inv_run:
        raise ValueError(
            f"No approved invariants run found for plan {plan_run_id}. "
            f"Run invariants council first: council run invariants --from-plan {plan_run_id} ..."
        )
    
    inv_artifacts = get_artifacts(inv_run.id, kind="output")
    if not inv_artifacts:
        raise ValueError(f"No invariants output artifact found for invariants run: {inv_run.id}")
    
    invariants_content = inv_artifacts[0].content
    
    # Validate inputs against dependency law (tracker takes spec + invariants)
    validate_allowed_inputs("tracker", {
        "spec": f"kind=output from spec run {spec_run.id}",
        "invariants": f"kind=output from invariants run {inv_run.id}",
    })
    
    # 4. Create new run for tracker generation
    tracker_run = create_run(
        project_slug=project_slug,
        task_type="tracker",
        parent_run_id=plan_run_id,
    )
    run_id = str(tracker_run.id)
    
    # Store the spec + invariants as reference artifacts
    write_artifact(
        run_id=tracker_run.id,
        kind="packet",
        content=f"# Source Spec (from spec run {spec_run.id})\n\n{spec_content}\n\n---\n\n# Source Invariants (from invariants run {inv_run.id})\n\n{invariants_content}",
        model=None,
    )
    
    failed_models: List[str] = []
    
    # 3. Generate drafts in parallel
    update_run_status(tracker_run.id, "drafting")
    
    draft_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {
            executor.submit(_generate_tracker_draft, run_id, model, spec_content, invariants_content): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                draft_ids.append(artifact_id)
            else:
                failed_models.append(model)
    
    if len(draft_ids) < 2:
        update_run_status(tracker_run.id, "failed")
        raise ValueError(f"Only {len(draft_ids)} draft(s) succeeded. Need at least 2.")
    
    # 4. Generate critiques in parallel
    update_run_status(tracker_run.id, "critiquing")
    
    # Format drafts for critique (no code fences to reduce chair mirroring fences)
    drafts = get_artifacts(tracker_run.id, kind="draft")
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n=== DRAFT {i} (model={draft.model}) ===\n{draft.content}\n=== END DRAFT {i} ===\n"
    
    critique_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        futures = {
            executor.submit(_generate_tracker_critique, run_id, model, spec_content, invariants_content, drafts_text): model
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
    update_run_status(tracker_run.id, "synthesizing")
    
    critiques = get_artifacts(tracker_run.id, kind="critique")
    critiques_text = ""
    for i, critique in enumerate(critiques, 1):
        critiques_text += f"\n### Critique {i} (from {critique.model})\n\n{critique.content}\n\n---\n"
    
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=TRACKER_CHAIR_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Tracker Drafts

{drafts_text}

## Critiques

{critiques_text}

---

Produce the final tracker/factory_tracker.yaml content.
Ensure each step respects the invariants.
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
            phase="tracker_chair",
            run_id=run_id,
        )
        
        # Validate chair output is valid YAML before storing
        tracker_content = result.content
        
        # Strip markdown fences if present (```yaml ... ``` or ``` ... ```)
        tracker_content = tracker_content.strip()
        if tracker_content.startswith("```"):
            lines = tracker_content.split("\n")
            # Remove opening fence line (```yaml or ```)
            lines = lines[1:]
            # Remove closing fence if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            tracker_content = "\n".join(lines).strip()
        
        try:
            parsed = yaml.safe_load(tracker_content)
            
            # Require top-level dict
            if not isinstance(parsed, dict):
                raise ValueError("YAML must be a mapping/dict at top level")
            
            # Require schema_version
            sv = parsed.get("schema_version")
            if sv not in ("0.1", 0.1):
                raise ValueError(f"schema_version must be 0.1, got: {sv}")
            
            # Require steps key
            if "steps" not in parsed:
                raise ValueError("Missing required top-level key: steps")
            
            # steps must be a list
            if not isinstance(parsed["steps"], list):
                raise ValueError("steps must be a list")
            
            # Require at least 1 step
            if len(parsed["steps"]) < 1:
                raise ValueError("At least 1 step is required in the tracker")
                
        except yaml.YAMLError as ye:
            # YAML parse error - write error artifact and fail
            error_msg = f"Chair output is not valid YAML:\n{ye}\n\nRaw output (first 2000 chars):\n{tracker_content[:2000]}"
            write_artifact(
                run_id=tracker_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(tracker_run.id, "failed")
            raise ValueError(f"Chair produced invalid YAML: {ye}")
        except ValueError as ve:
            # Validation error
            error_msg = f"Chair output failed validation:\n{ve}\n\nRaw output (first 2000 chars):\n{tracker_content[:2000]}"
            write_artifact(
                run_id=tracker_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(tracker_run.id, "failed")
            raise ValueError(f"Chair output failed validation: {ve}")
        
        # Store synthesis (raw chair output)
        write_artifact(
            run_id=tracker_run.id,
            kind="synthesis",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        # Store as output artifact (validated, cleaned tracker content)
        write_artifact(
            run_id=tracker_run.id,
            kind="output",
            content=tracker_content,
            model=result.model,
        )
        
    except Exception as e:
        # Only handle unexpected errors here; YAML validation errors already handled above
        if "Chair produced invalid YAML" in str(e) or "Chair output failed validation" in str(e):
            raise
        write_artifact(
            run_id=tracker_run.id,
            kind="error",
            content=f"Tracker chair synthesis failed: {str(e)}",
            model=chair_model,
        )
        update_run_status(tracker_run.id, "failed")
        raise ValueError(f"Chair synthesis failed: {e}")
    
    # 6. Set to waiting for approval
    update_run_status(tracker_run.id, "waiting_for_approval")
    
    return run_id, failed_models

