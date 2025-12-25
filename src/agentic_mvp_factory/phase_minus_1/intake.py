"""Phase -1 Intake: Fast front door to generate draft build_candidate and research_snapshot.

Turns a user's initial request into draft Phase -1 artifacts via a single LLM call.
NO web/search in this step - just structured generation.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Optional, Tuple

import yaml

from ..model_client import Message, OpenRouterClient, get_openrouter_client


@dataclass
class IntakeResult:
    """Result from intake generation."""
    build_candidate_path: Path
    research_snapshot_path: Path
    build_id: str
    success: bool
    error: Optional[str] = None


# Default model for intake (fast, cheap)
DEFAULT_INTAKE_MODEL = "google/gemini-3-flash-preview"

INTAKE_SYSTEM_PROMPT = """You are a structured project intake assistant. Your job is to turn a user's initial project idea into two structured YAML artifacts:

1. build_candidate.yaml - A scope lock for a single build
2. research_snapshot.yaml - Research questions to bound uncertainty

You MUST output EXACTLY two YAML documents using these delimiters:

=== build_candidate.yaml ===
<YAML content>
=== research_snapshot.yaml ===
<YAML content>

IMPORTANT RULES:
- Output ONLY the YAML content, no markdown fences, no explanations
- Follow the exact schema structure shown below
- Keep strings within character limits
- In draft mode, use "TBD" for unknowns; in commit mode, make reasonable guesses
- build_id pattern: B followed by 2 digits (e.g., B01, B02)
- research question id pattern: RQ followed by digits (RQ1, RQ2, etc.)

BUILD_CANDIDATE.YAML SCHEMA:
```yaml
schema_version: "0.1"
build_id: "BXX"  # Use provided or generate new
state_version: 1  # Increment if updating existing
title: "Short title (max 120 chars)"
problem: "What problem are we solving (max 240 chars)"
target_user: "Who is this for (max 160 chars)"
wow_slice: "Demo-able in <30s, one sentence (max 200 chars)"
done_enough:
  - "Measurable completion criteria (max 200 chars each)"
  - "3-6 bullets"
constraints:
  - "Hard constraints (max 200 chars each)"
non_goals:
  - "Explicit non-goals to prevent scope creep"
risks:
  - "Known risks"
open_questions:
  - "Questions that need answers"
size_caps:
  max_lines: 100
  max_words: 800
```

RESEARCH_SNAPSHOT.YAML SCHEMA:
```yaml
schema_version: "0.1"
build_id: "BXX"  # Must match build_candidate
state_version: 1
retrieved_at: null  # null in draft mode (no search yet)
research_questions:
  - id: "RQ1"
    question: "What needs to be researched (max 240 chars)"
    recency_days: 365  # How fresh must the info be
  # 3-6 questions
findings: []  # Empty initially (no search yet)
unknowns:
  - "Things we don't know yet (max 200 chars each)"
  # 3-6 items
decision_recommendations: []  # Empty initially (need findings first)
sufficiency:
  status: "unknown"  # unknown|sufficient|insufficient
  rationale: "Research not yet conducted (max 600 chars)"
size_caps:
  max_lines: 150
  max_words: 1200
```
"""


def _parse_intake_output(raw_output: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse the model's output into two YAML documents.
    
    Returns:
        (build_yaml, research_yaml, error)
    """
    # Find the delimiters
    build_match = re.search(
        r"===\s*build_candidate\.yaml\s*===\s*\n(.*?)(?====\s*research_snapshot\.yaml\s*===|$)",
        raw_output,
        re.DOTALL | re.IGNORECASE,
    )
    research_match = re.search(
        r"===\s*research_snapshot\.yaml\s*===\s*\n(.*?)$",
        raw_output,
        re.DOTALL | re.IGNORECASE,
    )
    
    if not build_match:
        return None, None, "Could not find '=== build_candidate.yaml ===' delimiter in output"
    if not research_match:
        return None, None, "Could not find '=== research_snapshot.yaml ===' delimiter in output"
    
    build_yaml = build_match.group(1).strip()
    research_yaml = research_match.group(1).strip()
    
    # Strip any markdown fences if present
    for fence in ["```yaml", "```yml", "```"]:
        build_yaml = build_yaml.replace(fence, "")
        research_yaml = research_yaml.replace(fence, "")
    build_yaml = build_yaml.strip()
    research_yaml = research_yaml.strip()
    
    return build_yaml, research_yaml, None


def _validate_build_candidate(data: dict) -> Optional[str]:
    """Minimal validation for build_candidate.yaml."""
    required = [
        "schema_version", "build_id", "state_version", "title", "problem",
        "target_user", "wow_slice", "done_enough", "constraints", "non_goals",
        "risks", "open_questions", "size_caps",
    ]
    for key in required:
        if key not in data:
            return f"Missing required key: {key}"
    
    if not re.match(r"^B[0-9]+$", data.get("build_id", "")):
        return f"Invalid build_id format: {data.get('build_id')} (expected B followed by digits)"
    
    if not isinstance(data.get("done_enough"), list) or len(data["done_enough"]) < 1:
        return "done_enough must be a non-empty list"
    
    size_caps = data.get("size_caps", {})
    if "max_lines" not in size_caps or "max_words" not in size_caps:
        return "size_caps must contain max_lines and max_words"
    
    return None


def _validate_research_snapshot(data: dict, expected_build_id: str) -> Optional[str]:
    """Minimal validation for research_snapshot.yaml."""
    required = [
        "schema_version", "build_id", "state_version", "retrieved_at",
        "research_questions", "findings", "unknowns", "decision_recommendations",
        "sufficiency", "size_caps",
    ]
    for key in required:
        if key not in data:
            return f"Missing required key: {key}"
    
    if data.get("build_id") != expected_build_id:
        return f"build_id mismatch: expected {expected_build_id}, got {data.get('build_id')}"
    
    if not isinstance(data.get("research_questions"), list) or len(data["research_questions"]) < 1:
        return "research_questions must be a non-empty list"
    
    # Check research question structure
    for rq in data["research_questions"]:
        if not isinstance(rq, dict):
            return "Each research_question must be an object"
        if "id" not in rq or "question" not in rq or "recency_days" not in rq:
            return "Each research_question must have id, question, recency_days"
    
    sufficiency = data.get("sufficiency", {})
    if "status" not in sufficiency or "rationale" not in sufficiency:
        return "sufficiency must contain status and rationale"
    
    return None


def _get_existing_build_id(out_dir: Path) -> Optional[str]:
    """Check if build_candidate.yaml exists and return its build_id."""
    build_file = out_dir / "build_candidate.yaml"
    if build_file.exists():
        try:
            with open(build_file) as f:
                data = yaml.safe_load(f)
                return data.get("build_id") if data else None
        except Exception:
            pass
    return None


def _get_existing_state_version(file_path: Path) -> int:
    """Get current state_version from a YAML file, or 0 if not found."""
    if file_path.exists():
        try:
            with open(file_path) as f:
                data = yaml.safe_load(f)
                return data.get("state_version", 0) if data else 0
        except Exception:
            pass
    return 0


def generate_intake(
    prompt: str,
    out_dir: Path,
    mode: Literal["draft", "commit"] = "draft",
    model: str = DEFAULT_INTAKE_MODEL,
    existing_build_id: Optional[str] = None,
) -> IntakeResult:
    """
    Generate Phase -1 artifacts from a user prompt.
    
    Args:
        prompt: User's project idea/request
        out_dir: Directory to write artifacts to
        mode: "draft" allows TBD, "commit" tries to fill everything
        model: Model to use for generation
        existing_build_id: If provided, reuse this build_id instead of generating new
    
    Returns:
        IntakeResult with paths to generated files
    """
    # Determine build_id
    build_id = existing_build_id or _get_existing_build_id(out_dir)
    if not build_id:
        # Generate a new build_id
        build_id = "B01"
    
    # Get state versions for potential increment
    build_file = out_dir / "build_candidate.yaml"
    research_file = out_dir / "research_snapshot.yaml"
    build_state = _get_existing_state_version(build_file) + 1
    research_state = _get_existing_state_version(research_file) + 1
    
    # Build the user prompt
    user_content = f"""Generate Phase -1 artifacts for this project:

PROJECT REQUEST:
{prompt}

CONFIGURATION:
- build_id: {build_id}
- build_candidate state_version: {build_state}
- research_snapshot state_version: {research_state}
- mode: {mode}
- today's date: {date.today().isoformat()}

{"In draft mode, use 'TBD' for things you're uncertain about." if mode == "draft" else "In commit mode, make reasonable guesses for all fields - no TBD values allowed."}

Output the two YAML documents using the exact delimiter format specified."""

    messages = [
        Message(role="system", content=INTAKE_SYSTEM_PROMPT),
        Message(role="user", content=user_content),
    ]
    
    # Call the model
    try:
        client = get_openrouter_client()
        result = client.complete(messages=messages, model=model, timeout=60.0)
    except Exception as e:
        return IntakeResult(
            build_candidate_path=build_file,
            research_snapshot_path=research_file,
            build_id=build_id,
            success=False,
            error=f"Model call failed: {e}",
        )
    
    # Parse the output
    build_yaml, research_yaml, parse_error = _parse_intake_output(result.content)
    if parse_error:
        return IntakeResult(
            build_candidate_path=build_file,
            research_snapshot_path=research_file,
            build_id=build_id,
            success=False,
            error=f"Parse error: {parse_error}\n\nRaw output:\n{result.content[:500]}...",
        )
    
    # Parse and validate YAML
    try:
        build_data = yaml.safe_load(build_yaml)
    except yaml.YAMLError as e:
        return IntakeResult(
            build_candidate_path=build_file,
            research_snapshot_path=research_file,
            build_id=build_id,
            success=False,
            error=f"Invalid YAML in build_candidate: {e}",
        )
    
    try:
        research_data = yaml.safe_load(research_yaml)
    except yaml.YAMLError as e:
        return IntakeResult(
            build_candidate_path=build_file,
            research_snapshot_path=research_file,
            build_id=build_id,
            success=False,
            error=f"Invalid YAML in research_snapshot: {e}",
        )
    
    # Validate structure
    build_error = _validate_build_candidate(build_data)
    if build_error:
        return IntakeResult(
            build_candidate_path=build_file,
            research_snapshot_path=research_file,
            build_id=build_id,
            success=False,
            error=f"build_candidate validation failed: {build_error}",
        )
    
    research_error = _validate_research_snapshot(research_data, build_data["build_id"])
    if research_error:
        return IntakeResult(
            build_candidate_path=build_file,
            research_snapshot_path=research_file,
            build_id=build_id,
            success=False,
            error=f"research_snapshot validation failed: {research_error}",
        )
    
    # Write files
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(build_file, "w") as f:
        yaml.dump(build_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    with open(research_file, "w") as f:
        yaml.dump(research_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    return IntakeResult(
        build_candidate_path=build_file,
        research_snapshot_path=research_file,
        build_id=build_data["build_id"],
        success=True,
    )

