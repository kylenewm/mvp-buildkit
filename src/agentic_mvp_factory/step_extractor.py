"""Step extractor for Phase 3A execution bridge."""

from pathlib import Path
from uuid import UUID


class RunNotFoundError(ValueError):
    """Raised when run_id doesn't exist."""
    pass


class RunNotApprovedError(ValueError):
    """Raised when run is not in an approved state."""
    pass


class NoSynthesisError(ValueError):
    """Raised when no synthesis artifact exists for the run."""
    pass


# Valid statuses for extraction (run must be approved)
APPROVED_STATUSES = ("ready_to_commit", "completed")


def get_next_step_number(execution_dir: Path) -> int:
    """
    Get the next step number based on existing step files.
    
    Scans execution/steps/ for files matching S(\d+)_*.md,
    picks max+1, zero-pads to 2 digits. Returns 1 if none exist.
    """
    steps_dir = execution_dir / "steps"
    if not steps_dir.exists():
        return 1
    
    existing = list(steps_dir.glob("S[0-9][0-9]_*.md"))
    if not existing:
        return 1
    
    # Extract numbers from filenames like S01_foo.md, S02_bar.md
    numbers = []
    for f in existing:
        name = f.stem  # S01_foo
        if name.startswith("S") and "_" in name:
            try:
                num = int(name[1:3])
                numbers.append(num)
            except ValueError:
                pass
    
    return max(numbers, default=0) + 1


def extract_step_from_run(
    run_id: UUID,
    execution_dir: Path,
    output_slug: str = "extracted",
) -> Path:
    """
    Extract an execution step document from an approved run's synthesis.
    
    Args:
        run_id: The run to extract from
        execution_dir: Path to execution/ directory
        output_slug: Slug for the output filename
        
    Returns:
        Path to the created step document
        
    Raises:
        RunNotFoundError: If run_id doesn't exist (exit code 1)
        RunNotApprovedError: If run status not in APPROVED_STATUSES (exit code 2)
        NoSynthesisError: If no synthesis artifact found (exit code 1)
    """
    from agentic_mvp_factory.repo import get_run, get_artifacts
    
    # Get run and validate existence
    run = get_run(run_id)
    if not run:
        raise RunNotFoundError(f"Run not found: {run_id}")
    
    # Validate approval status
    if run.status not in APPROVED_STATUSES:
        raise RunNotApprovedError(
            f"Run not approved. Status: '{run.status}'. "
            f"Expected one of: {APPROVED_STATUSES}"
        )
    
    # Get synthesis artifact - prefer edited version if available
    edited_artifacts = get_artifacts(run_id, kind="synthesis_edited")
    if edited_artifacts:
        # Use most recent edited synthesis
        synthesis_content = sorted(
            edited_artifacts, 
            key=lambda a: a.created_at, 
            reverse=True
        )[0].content
    else:
        # Fall back to original synthesis
        synthesis_artifacts = get_artifacts(run_id, kind="synthesis")
        if not synthesis_artifacts:
            raise NoSynthesisError(f"No synthesis found for run: {run_id}")
        # Use most recent synthesis
        synthesis_content = sorted(
            synthesis_artifacts,
            key=lambda a: a.created_at,
            reverse=True
        )[0].content
    
    # Get next step number
    step_num = get_next_step_number(execution_dir)
    step_id = f"S{step_num:02d}"
    
    # Generate step document with synthesis included VERBATIM
    step_doc = f"""# Step {step_id} — [EDIT: Add Title]

## Objective

[EDIT: One sentence describing what must be true when this step is done]

## Context

- Project: {run.project_slug}
- Derived from: Council run {run_id}
- Run status: {run.status}
- Dependencies: [EDIT: List prior steps]

## Scope (Hard Boundaries)

- Files allowed to change:
  - [EDIT: List specific files]

- Explicit non-goals:
  - [EDIT: What NOT to do]

## Instructions

[EDIT: Extract concrete, boring actions from the synthesis below]

## Council Synthesis (Reference)

The following synthesis is included **verbatim** from the approved council run:

---

{synthesis_content}

---

## Acceptance Criteria

- [EDIT: Observable behaviors that define "done"]

## Proof Commands (Human-run)

```bash
# [EDIT: Add proof commands]
echo "Step {step_id} proof commands go here"
```

## Stop Condition

After code changes:
1. Output summary
2. Output exact proof commands
3. STOP
"""

    # Ensure directory exists and write step document
    steps_dir = execution_dir / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = steps_dir / f"{step_id}_{output_slug}.md"
    output_path.write_text(step_doc)
    
    return output_path
