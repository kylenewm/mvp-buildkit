"""Phase 2 Prompts Council - generates prompt templates from an approved plan.

Usage:
    council run prompts --from-plan <plan_run_id> --project <slug> --models <list> --chair <model>

Generates:
- prompts/step_template.md
- prompts/review_template.md
- prompts/patch_template.md
- prompts/chair_synthesis_template.md
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


# Required output keys in the envelope
REQUIRED_PROMPT_KEYS = [
    "prompts/step_template.md",
    "prompts/review_template.md",
    "prompts/patch_template.md",
    "prompts/chair_synthesis_template.md",
]


# =============================================================================
# PROMPTS
# =============================================================================

PROMPTS_SYSTEM_PROMPT = """You are a council member generating prompt templates for a code assistant workflow.

Your job is to produce a YAML envelope containing EXACTLY 4 prompt templates.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY valid YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing
- The YAML must have this EXACT structure:

schema_version: "0.1"
updated_at: <YYYY-MM-DD>
outputs:
  prompts/step_template.md: |
    <markdown content for step execution prompt>
  prompts/review_template.md: |
    <markdown content for review/critique prompt>
  prompts/patch_template.md: |
    <markdown content for patch/fix prompt>
  prompts/chair_synthesis_template.md: |
    <markdown content for chair synthesis prompt>

Template content guidelines:
1. Each template should be 50-150 lines of markdown
2. Use placeholders like {{step_id}}, {{allowed_files}}, {{proof_commands}}
3. Reference ONLY canonical paths:
   - tracker/factory_tracker.yaml (NOT tracker/tracker.yaml)
   - docs/ARTIFACT_REGISTRY.md
4. Emphasize "patch-only", "allowed_files", "proof commands"
5. AVOID deprecated paths:
   - tracker/tracker.yaml (WRONG)
   - prompts/hotfix_sync.md (WRONG)
   - docs/build_guide.md (WRONG)

Output ONLY the YAML envelope, nothing else.
"""

PROMPTS_CRITIQUE_PROMPT = """You are reviewing a prompts envelope draft.

Check for:
1. Valid YAML syntax (no markdown fences)
2. Envelope has schema_version, updated_at, and outputs keys
3. outputs contains EXACTLY these 4 keys:
   - prompts/step_template.md
   - prompts/review_template.md
   - prompts/patch_template.md
   - prompts/chair_synthesis_template.md
4. Each template is non-empty markdown
5. NO deprecated paths mentioned:
   - tracker/tracker.yaml (should be tracker/factory_tracker.yaml)
   - prompts/hotfix_sync.md (should not exist)
   - docs/build_guide.md (should not exist)
6. Templates emphasize patch-only, allowed_files, proof commands
7. Placeholders are consistent and useful

Provide specific, actionable feedback. Be concise - 3-5 key points maximum."""

PROMPTS_CHAIR_PROMPT = """You are the Chair synthesizing prompt template drafts and critiques.

Your task: produce the FINAL prompts envelope.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY raw YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Start directly with YAML content, not with ```yaml
- The output must be valid YAML that can be parsed directly
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing

REQUIRED STRUCTURE (use EXACTLY these keys):
schema_version: "0.1"
updated_at: <YYYY-MM-DD>
outputs:
  prompts/step_template.md: |
    ...markdown template...
  prompts/review_template.md: |
    ...markdown template...
  prompts/patch_template.md: |
    ...markdown template...
  prompts/chair_synthesis_template.md: |
    ...markdown template...

IMPORTANT:
- Include ALL 4 templates
- Each template should be 50-150 lines
- Use canonical paths only (tracker/factory_tracker.yaml, docs/ARTIFACT_REGISTRY.md)
- AVOID deprecated paths (tracker/tracker.yaml, hotfix_sync.md, build_guide.md)

Incorporate the best elements from all drafts. Address critique feedback.
Output the complete YAML envelope and NOTHING else."""


# =============================================================================
# COUNCIL FUNCTIONS
# =============================================================================

def _generate_prompts_draft(
    run_id: str,
    model: str,
    spec_content: str,
    invariants_content: str,
    tracker_content: str,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single prompts envelope draft.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=PROMPTS_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Project Tracker (tracker/factory_tracker.yaml)

{tracker_content}

---

Generate the complete prompts envelope with all 4 templates.
Templates should reference the tracker steps and enforce invariants.
Use updated_at: {today}
Output ONLY valid YAML.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=180.0,
            phase="prompts_draft",
            run_id=run_id,
            stage="prompts",
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
            content=f"Prompts draft failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def _generate_prompts_critique(
    run_id: str,
    model: str,
    spec_content: str,
    invariants_content: str,
    tracker_content: str,
    drafts_text: str,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a prompts critique.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=PROMPTS_CRITIQUE_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Project Tracker (tracker/factory_tracker.yaml)

{tracker_content}

## Prompts Envelope Drafts

{drafts_text}

---

Provide your critique of these prompts envelope drafts.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="prompts_critique",
            run_id=run_id,
            stage="prompts",
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
            content=f"Prompts critique failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def run_prompts_council(
    plan_run_id: UUID,
    project_slug: str,
    models: List[str],
    chair_model: str,
) -> Tuple[str, List[str]]:
    """Run a prompts generation council.
    
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
    
    # 2. Load SPEC artifact
    spec_run = get_latest_approved_run_by_task_type("spec", plan_run_id)
    if not spec_run:
        raise ValueError(
            f"No approved spec run found for plan {plan_run_id}. "
            f"Run spec council first."
        )
    
    spec_artifacts = get_artifacts(spec_run.id, kind="output")
    if not spec_artifacts:
        raise ValueError(f"No spec output artifact found for spec run: {spec_run.id}")
    
    spec_content = spec_artifacts[0].content
    
    # 3. Load INVARIANTS artifact
    inv_run = get_latest_approved_run_by_task_type("invariants", plan_run_id)
    if not inv_run:
        raise ValueError(
            f"No approved invariants run found for plan {plan_run_id}. "
            f"Run invariants council first."
        )
    
    inv_artifacts = get_artifacts(inv_run.id, kind="output")
    if not inv_artifacts:
        raise ValueError(f"No invariants output artifact found for invariants run: {inv_run.id}")
    
    invariants_content = inv_artifacts[0].content
    
    # 4. Load TRACKER artifact
    tracker_run = get_latest_approved_run_by_task_type("tracker", plan_run_id)
    if not tracker_run:
        raise ValueError(
            f"No approved tracker run found for plan {plan_run_id}. "
            f"Run tracker council first."
        )
    
    tracker_artifacts = get_artifacts(tracker_run.id, kind="output")
    if not tracker_artifacts:
        raise ValueError(f"No tracker output artifact found for tracker run: {tracker_run.id}")
    
    tracker_content = tracker_artifacts[0].content
    
    # Validate inputs against dependency law (prompts takes spec + invariants + tracker)
    validate_allowed_inputs("prompts", {
        "spec": f"kind=output from spec run {spec_run.id}",
        "invariants": f"kind=output from invariants run {inv_run.id}",
        "tracker": f"kind=output from tracker run {tracker_run.id}",
    })
    
    # 5. Create new run for prompts generation
    prompts_run = create_run(
        project_slug=project_slug,
        task_type="prompts",
        parent_run_id=plan_run_id,
    )
    run_id = str(prompts_run.id)
    
    # Store the inputs as reference artifacts
    write_artifact(
        run_id=prompts_run.id,
        kind="packet",
        content=f"# Source Spec\n\n{spec_content}\n\n---\n\n# Source Invariants\n\n{invariants_content}\n\n---\n\n# Source Tracker\n\n{tracker_content}",
        model=None,
    )
    
    failed_models: List[str] = []
    n_models = len(models)
    
    # 3. Generate drafts in parallel
    update_run_status(prompts_run.id, "drafting")
    
    draft_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_prompts_draft, run_id, model, spec_content, invariants_content, tracker_content, n_models): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                draft_ids.append(artifact_id)
            else:
                failed_models.append(model)
    
    if len(draft_ids) < 2:
        update_run_status(prompts_run.id, "failed")
        raise ValueError(f"Only {len(draft_ids)} draft(s) succeeded. Need at least 2.")
    
    # 4. Generate critiques in parallel
    update_run_status(prompts_run.id, "critiquing")
    
    # Format drafts for critique (no code fences to reduce chair mirroring fences)
    drafts = get_artifacts(prompts_run.id, kind="draft")
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n=== DRAFT {i} (model={draft.model}) ===\n{draft.content}\n=== END DRAFT {i} ===\n"
    
    critique_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_prompts_critique, run_id, model, spec_content, invariants_content, tracker_content, drafts_text, n_models): model
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
    update_run_status(prompts_run.id, "synthesizing")
    
    critiques = get_artifacts(prompts_run.id, kind="critique")
    critiques_text = ""
    for i, critique in enumerate(critiques, 1):
        critiques_text += f"\n### Critique {i} (from {critique.model})\n\n{critique.content}\n\n---\n"
    
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=PROMPTS_CHAIR_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Project Tracker (tracker/factory_tracker.yaml)

{tracker_content}

## Prompts Envelope Drafts

{drafts_text}

## Critiques

{critiques_text}

---

Produce the final prompts envelope with all 4 templates.
Templates should reference tracker steps and enforce invariants.
Use updated_at: {today}
Output ONLY valid YAML, no markdown fences.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=chair_model,
            timeout=240.0,  # Longer timeout for 4 templates
            phase="prompts_chair",
            run_id=run_id,
            stage="prompts",
            role="chair",
            n_models=n_models,
        )
        
        # Validate chair output is valid YAML before storing
        envelope_content = result.content
        
        # Strip markdown fences if present (```yaml ... ``` or ``` ... ```)
        envelope_content = envelope_content.strip()
        if envelope_content.startswith("```"):
            lines = envelope_content.split("\n")
            # Remove opening fence line (```yaml or ```)
            lines = lines[1:]
            # Remove closing fence if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            envelope_content = "\n".join(lines).strip()
        
        try:
            parsed = yaml.safe_load(envelope_content)
            
            # Require top-level dict
            if not isinstance(parsed, dict):
                raise ValueError("YAML must be a mapping/dict at top level")
            
            # Require schema_version
            sv = parsed.get("schema_version")
            if sv not in ("0.1", 0.1):
                raise ValueError(f"schema_version must be 0.1, got: {sv}")
            
            # Require outputs key
            if "outputs" not in parsed:
                raise ValueError("Missing required top-level key: outputs")
            
            outputs = parsed["outputs"]
            if not isinstance(outputs, dict):
                raise ValueError("outputs must be a dict")
            
            # Check for EXACTLY the required 4 keys
            missing_keys = [k for k in REQUIRED_PROMPT_KEYS if k not in outputs]
            if missing_keys:
                raise ValueError(f"Missing required output keys: {missing_keys}")
            
            extra_keys = [k for k in outputs.keys() if k not in REQUIRED_PROMPT_KEYS]
            if extra_keys:
                raise ValueError(f"Unexpected output keys: {extra_keys}")
            
            # Each value must be a non-empty string
            for key in REQUIRED_PROMPT_KEYS:
                val = outputs[key]
                if not isinstance(val, str):
                    raise ValueError(f"outputs['{key}'] must be a string, got {type(val).__name__}")
                if not val.strip():
                    raise ValueError(f"outputs['{key}'] is empty")
                
        except yaml.YAMLError as ye:
            # YAML parse error - write error artifact and fail
            error_msg = f"Chair output is not valid YAML:\n{ye}\n\nRaw output (first 2000 chars):\n{envelope_content[:2000]}"
            write_artifact(
                run_id=prompts_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(prompts_run.id, "failed")
            raise ValueError(f"Chair produced invalid YAML: {ye}")
        except ValueError as ve:
            # Validation error
            error_msg = f"Chair output failed validation:\n{ve}\n\nRaw output (first 2000 chars):\n{envelope_content[:2000]}"
            write_artifact(
                run_id=prompts_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(prompts_run.id, "failed")
            raise ValueError(f"Chair output failed validation: {ve}")
        
        # Store synthesis (raw chair output)
        write_artifact(
            run_id=prompts_run.id,
            kind="synthesis",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        # Store as output artifact (validated, cleaned envelope)
        write_artifact(
            run_id=prompts_run.id,
            kind="output",
            content=envelope_content,
            model=result.model,
        )
        
    except Exception as e:
        # Only handle unexpected errors here; YAML validation errors already handled above
        if "Chair produced invalid YAML" in str(e) or "Chair output failed validation" in str(e):
            raise
        write_artifact(
            run_id=prompts_run.id,
            kind="error",
            content=f"Prompts chair synthesis failed: {str(e)}",
            model=chair_model,
        )
        update_run_status(prompts_run.id, "failed")
        raise ValueError(f"Chair synthesis failed: {e}")
    
    # 6. Set to waiting for approval
    update_run_status(prompts_run.id, "waiting_for_approval")
    
    return run_id, failed_models

