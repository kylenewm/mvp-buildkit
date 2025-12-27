"""Phase 2 Cursor Rules Council - generates .cursor/rules files from an approved plan.

Usage:
    council run cursor-rules --from-plan <plan_run_id> --project <slug> --models <list> --chair <model>

Generates:
- .cursor/rules/00_global.md
- .cursor/rules/10_invariants.md
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
REQUIRED_RULES_KEYS = [
    ".cursor/rules/00_global.md",
    ".cursor/rules/10_invariants.md",
]


# =============================================================================
# PROMPTS
# =============================================================================

CURSOR_RULES_SYSTEM_PROMPT = """You are a council member generating Cursor IDE rules files.

Your job is to produce a YAML envelope containing EXACTLY 2 rule files.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY valid YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing
- The YAML must have this EXACT structure:

schema_version: "0.1"
updated_at: <YYYY-MM-DD>
outputs:
  .cursor/rules/00_global.md: |
    <markdown content for global rules>
  .cursor/rules/10_invariants.md: |
    <markdown content for invariants reference>

Content guidelines for 00_global.md (global rules):
- Keep it short (50-100 lines)
- Emphasize: patch-only edits, allowed_files only, proof commands required
- No surprise refactors or scope creep
- Always consult tracker/factory_tracker.yaml for step details
- Always check invariants/invariants.md before changes
- Reference canonical paths only (NOT tracker/tracker.yaml, NOT hotfix_sync.md, NOT build_guide.md)

Content guidelines for 10_invariants.md:
- Keep it very short (20-40 lines)
- Just a quick reference pointing to the canonical source
- State: "Canonical invariants are defined in invariants/invariants.md"
- Do NOT duplicate or redefine invariants here
- List 3-5 key invariant categories as reminders

Output ONLY the YAML envelope, nothing else.
"""

CURSOR_RULES_CRITIQUE_PROMPT = """You are reviewing a cursor rules envelope draft.

Check for:
1. Valid YAML syntax (no markdown fences)
2. Envelope has schema_version, updated_at, and outputs keys
3. outputs contains EXACTLY these 2 keys:
   - .cursor/rules/00_global.md
   - .cursor/rules/10_invariants.md
4. Each rule file is non-empty markdown
5. NO deprecated paths mentioned:
   - tracker/tracker.yaml (should be tracker/factory_tracker.yaml)
   - prompts/hotfix_sync.md (should not exist)
   - docs/build_guide.md (should not exist)
6. 00_global.md emphasizes patch-only, allowed_files, proof commands
7. 10_invariants.md references invariants/invariants.md and does NOT duplicate invariants
8. Both files are concise (not bloated)

Provide specific, actionable feedback. Be concise - 3-5 key points maximum."""

CURSOR_RULES_CHAIR_PROMPT = """You are the Chair synthesizing cursor rules drafts and critiques.

Your task: produce the FINAL cursor rules envelope.

CRITICAL FORMAT REQUIREMENTS:
- Output ONLY raw YAML (NO markdown fences, NO ``` anywhere, NO explanations)
- Start directly with YAML content, not with ```yaml
- The output must be valid YAML that can be parsed directly
- Do NOT use single quotes (') or backticks (`) inside YAML strings - they break parsing

REQUIRED STRUCTURE (use EXACTLY these keys):
schema_version: "0.1"
updated_at: <YYYY-MM-DD>
outputs:
  .cursor/rules/00_global.md: |
    ...markdown rules...
  .cursor/rules/10_invariants.md: |
    ...markdown reference...

IMPORTANT:
- Include EXACTLY 2 rule files
- 00_global.md should be 50-100 lines, emphasizing patch-only and allowed_files
- 10_invariants.md should be 20-40 lines, pointing to invariants/invariants.md
- Use canonical paths only (tracker/factory_tracker.yaml, NOT tracker/tracker.yaml)
- AVOID deprecated paths (tracker/tracker.yaml, hotfix_sync.md, build_guide.md)
- 10_invariants.md must NOT redefine invariants, just reference the canonical source

Incorporate the best elements from all drafts. Address critique feedback.
Output the complete YAML envelope and NOTHING else."""


# =============================================================================
# COUNCIL FUNCTIONS
# =============================================================================

def _generate_cursor_rules_draft(
    run_id: str,
    model: str,
    spec_content: str,
    invariants_content: str,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a single cursor rules envelope draft.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=CURSOR_RULES_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

---

Generate the complete cursor rules envelope with both rule files.
Rules should enforce the invariants and reference the spec.
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
            phase="cursor_rules_draft",
            run_id=run_id,
            stage="cursor_rules",
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
            content=f"Cursor rules draft failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def _generate_cursor_rules_critique(
    run_id: str,
    model: str,
    spec_content: str,
    invariants_content: str,
    drafts_text: str,
    n_models: int = 3,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Generate a cursor rules critique.
    
    Returns:
        (model, artifact_id or None, error or None)
    """
    client = get_openrouter_client()
    
    messages = [
        Message(role="system", content=CURSOR_RULES_CRITIQUE_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Cursor Rules Envelope Drafts

{drafts_text}

---

Provide your critique of these cursor rules envelope drafts.""",
        ),
    ]
    
    try:
        result = traced_complete(
            client=client,
            messages=messages,
            model=model,
            timeout=120.0,
            phase="cursor_rules_critique",
            run_id=run_id,
            stage="cursor_rules",
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
            content=f"Cursor rules critique failed for {model}: {str(e)}",
            model=model,
        )
        return (model, None, str(e))


def run_cursor_rules_council(
    plan_run_id: UUID,
    project_slug: str,
    models: List[str],
    chair_model: str,
) -> Tuple[str, List[str]]:
    """Run a cursor rules generation council.
    
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
    
    # Validate inputs against dependency law (cursor_rules takes spec + invariants)
    validate_allowed_inputs("cursor_rules", {
        "spec": f"kind=output from spec run {spec_run.id}",
        "invariants": f"kind=output from invariants run {inv_run.id}",
    })
    
    # 4. Create new run for cursor rules generation
    rules_run = create_run(
        project_slug=project_slug,
        task_type="cursor_rules",
        parent_run_id=plan_run_id,
    )
    run_id = str(rules_run.id)
    
    # Store the inputs as reference artifacts
    write_artifact(
        run_id=rules_run.id,
        kind="packet",
        content=f"# Source Spec\n\n{spec_content}\n\n---\n\n# Source Invariants\n\n{invariants_content}",
        model=None,
    )
    
    failed_models: List[str] = []
    n_models = len(models)
    
    # 3. Generate drafts in parallel
    update_run_status(rules_run.id, "drafting")
    
    draft_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_cursor_rules_draft, run_id, model, spec_content, invariants_content, n_models): model
            for model in models
        }
        
        for future in as_completed(futures):
            model, artifact_id, error = future.result()
            if artifact_id:
                draft_ids.append(artifact_id)
            else:
                failed_models.append(model)
    
    if len(draft_ids) < 2:
        update_run_status(rules_run.id, "failed")
        raise ValueError(f"Only {len(draft_ids)} draft(s) succeeded. Need at least 2.")
    
    # 4. Generate critiques in parallel
    update_run_status(rules_run.id, "critiquing")
    
    # Format drafts for critique (no code fences to reduce chair mirroring fences)
    drafts = get_artifacts(rules_run.id, kind="draft")
    drafts_text = ""
    for i, draft in enumerate(drafts, 1):
        drafts_text += f"\n=== DRAFT {i} (model={draft.model}) ===\n{draft.content}\n=== END DRAFT {i} ===\n"
    
    critique_ids: List[str] = []
    with ThreadPoolExecutor(max_workers=n_models) as executor:
        futures = {
            executor.submit(_generate_cursor_rules_critique, run_id, model, spec_content, invariants_content, drafts_text, n_models): model
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
    update_run_status(rules_run.id, "synthesizing")
    
    critiques = get_artifacts(rules_run.id, kind="critique")
    critiques_text = ""
    for i, critique in enumerate(critiques, 1):
        critiques_text += f"\n### Critique {i} (from {critique.model})\n\n{critique.content}\n\n---\n"
    
    client = get_openrouter_client()
    
    today = date.today().isoformat()
    
    messages = [
        Message(role="system", content=CURSOR_RULES_CHAIR_PROMPT),
        Message(
            role="user",
            content=f"""## Project Spec (spec/spec.yaml)

{spec_content}

## Project Invariants (invariants/invariants.md)

{invariants_content}

## Cursor Rules Envelope Drafts

{drafts_text}

## Critiques

{critiques_text}

---

Produce the final cursor rules envelope with both rule files.
Rules should enforce invariants and reference the spec.
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
            phase="cursor_rules_chair",
            run_id=run_id,
            stage="cursor_rules",
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
            
            # Check for EXACTLY the required 2 keys
            missing_keys = [k for k in REQUIRED_RULES_KEYS if k not in outputs]
            if missing_keys:
                raise ValueError(f"Missing required output keys: {missing_keys}")
            
            extra_keys = [k for k in outputs.keys() if k not in REQUIRED_RULES_KEYS]
            if extra_keys:
                raise ValueError(f"Unexpected output keys: {extra_keys}")
            
            # Each value must be a non-empty string
            for key in REQUIRED_RULES_KEYS:
                val = outputs[key]
                if not isinstance(val, str):
                    raise ValueError(f"outputs['{key}'] must be a string, got {type(val).__name__}")
                if not val.strip():
                    raise ValueError(f"outputs['{key}'] is empty")
                
        except yaml.YAMLError as ye:
            # YAML parse error - write error artifact and fail
            error_msg = f"Chair output is not valid YAML:\n{ye}\n\nRaw output (first 2000 chars):\n{envelope_content[:2000]}"
            write_artifact(
                run_id=rules_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(rules_run.id, "failed")
            raise ValueError(f"Chair produced invalid YAML: {ye}")
        except ValueError as ve:
            # Validation error
            error_msg = f"Chair output failed validation:\n{ve}\n\nRaw output (first 2000 chars):\n{envelope_content[:2000]}"
            write_artifact(
                run_id=rules_run.id,
                kind="error",
                content=error_msg,
                model=chair_model,
            )
            update_run_status(rules_run.id, "failed")
            raise ValueError(f"Chair output failed validation: {ve}")
        
        # Store synthesis (raw chair output)
        write_artifact(
            run_id=rules_run.id,
            kind="synthesis",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        # Store as output artifact (validated, cleaned envelope)
        write_artifact(
            run_id=rules_run.id,
            kind="output",
            content=envelope_content,
            model=result.model,
        )
        
    except Exception as e:
        # Only handle unexpected errors here; YAML validation errors already handled above
        if "Chair produced invalid YAML" in str(e) or "Chair output failed validation" in str(e):
            raise
        write_artifact(
            run_id=rules_run.id,
            kind="error",
            content=f"Cursor rules chair synthesis failed: {str(e)}",
            model=chair_model,
        )
        update_run_status(rules_run.id, "failed")
        raise ValueError(f"Chair synthesis failed: {e}")
    
    # 6. Set to waiting for approval
    update_run_status(rules_run.id, "waiting_for_approval")
    
    return run_id, failed_models

