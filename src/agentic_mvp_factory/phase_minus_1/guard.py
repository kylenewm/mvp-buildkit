"""Phase -1 Guard: validates build_candidate.yaml and research_snapshot.yaml.

Standalone module. No hidden coupling to other validators.
Uses jsonschema for Draft-07 validation, PyYAML for YAML reading.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

import jsonschema
import yaml


# --- Constants ---

RERUN_CMD = "council phase-1-guard"


@dataclass
class GuardResult:
    """Result of Phase -1 guard check."""
    is_ready: bool = True
    mode: str = "draft"
    
    # Errors (cause failure)
    schema_errors: List[str] = field(default_factory=list)
    size_violations: List[str] = field(default_factory=list)
    build_id_mismatch: Optional[str] = None
    commit_blockers: List[str] = field(default_factory=list)
    
    # Warnings (informational)
    tbd_fields: List[str] = field(default_factory=list)
    
    # Metadata
    build_id: Optional[str] = None
    hitl_questions: List[str] = field(default_factory=list)


# --- Schema resolution ---

SCHEMA_MAP = {
    "build_candidate.yaml": "build_candidate.schema.json",
    "research_snapshot.yaml": "research_snapshot.schema.json",
}


def _load_yaml_safe(file_path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """
    Load YAML file, handling empty files and parse errors safely.
    
    Returns:
        (data, error) - data is None if parse failed, error contains details
    """
    try:
        content = file_path.read_text()
        data = yaml.safe_load(content)
        if data is None:
            return None, "File is empty"
        if not isinstance(data, dict):
            return None, f"Expected dict, got {type(data).__name__}"
        return data, None
    except yaml.YAMLError as e:
        # Extract line/column info from YAML error
        if hasattr(e, 'problem_mark') and e.problem_mark:
            mark = e.problem_mark
            error_detail = f"YAML parse error at line {mark.line + 1}, column {mark.column + 1}: {e.problem or 'syntax error'}"
        else:
            error_detail = f"YAML parse error: {str(e)}"
        return None, error_detail


def _load_json_schema(schema_path: Path) -> Optional[dict]:
    """Load JSON schema file."""
    try:
        return json.loads(schema_path.read_text())
    except (json.JSONDecodeError, IOError):
        return None


# --- Validation helpers ---

def _validate_schema(
    data: dict,
    schema: dict,
    filename: str,
) -> List[str]:
    """
    Validate data against JSON schema, return ALL errors (not just first).
    
    Uses Draft7Validator.iter_errors() to collect all validation errors.
    """
    errors = []
    try:
        validator = jsonschema.Draft7Validator(schema)
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "(root)"
            errors.append(f"{filename}: {error.message} at {path}")
    except jsonschema.SchemaError as e:
        errors.append(f"{filename}: Schema error - {e.message}")
    return errors


def _count_lines_words(file_path: Path) -> tuple[int, int]:
    """Count lines and words in a file."""
    content = file_path.read_text()
    lines = len(content.splitlines())
    words = len(content.split())
    return lines, words


def _check_size_caps(
    file_path: Path,
    data: dict,
) -> List[str]:
    """Check if file exceeds its declared size caps."""
    violations = []
    size_caps = data.get("size_caps", {})
    max_lines = size_caps.get("max_lines")
    max_words = size_caps.get("max_words")
    
    if max_lines is None and max_words is None:
        return violations
    
    actual_lines, actual_words = _count_lines_words(file_path)
    
    if max_lines and actual_lines > max_lines:
        violations.append(
            f"{file_path.name}: {actual_lines} lines exceeds cap of {max_lines}"
        )
    
    if max_words and actual_words > max_words:
        violations.append(
            f"{file_path.name}: {actual_words} words exceeds cap of {max_words}"
        )
    
    return violations


def _find_tbd_values(data: dict, prefix: str = "") -> List[str]:
    """Recursively find all fields containing 'TBD'."""
    tbd_fields = []
    
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str) and value.strip().upper() == "TBD":
                tbd_fields.append(path)
            elif isinstance(value, (dict, list)):
                tbd_fields.extend(_find_tbd_values(value, path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            path = f"{prefix}[{i}]"
            if isinstance(item, str) and item.strip().upper() == "TBD":
                tbd_fields.append(path)
            elif isinstance(item, (dict, list)):
                tbd_fields.extend(_find_tbd_values(item, path))
    
    return tbd_fields


def _parse_iso_timestamp(value: str) -> bool:
    """
    Validate ISO 8601 timestamp format.
    
    Handles both standard format and trailing 'Z' (UTC).
    Returns True if valid, False otherwise.
    """
    if not isinstance(value, str):
        return False
    
    # Handle trailing Z (UTC) by converting to +00:00
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _check_commit_readiness(
    research_data: dict,
) -> List[str]:
    """Check commit-mode specific requirements."""
    blockers = []
    
    retrieved_at = research_data.get("retrieved_at")
    
    # research_snapshot.retrieved_at must be non-null
    if retrieved_at is None:
        blockers.append("research_snapshot.retrieved_at is null (research not retrieved)")
    elif not _parse_iso_timestamp(retrieved_at):
        # retrieved_at must be valid ISO 8601
        blockers.append(
            f"research_snapshot.retrieved_at is not valid ISO 8601: '{retrieved_at}'"
        )
    
    # sufficiency.status cannot be "unknown"
    sufficiency = research_data.get("sufficiency", {})
    if sufficiency.get("status") == "unknown":
        blockers.append("research_snapshot.sufficiency.status is 'unknown' (not evaluated)")
    
    return blockers


# --- Main guard function ---

def check_phase_minus_1(
    phase_dir: Path,
    schemas_dir: Path,
    mode: Literal["draft", "commit"] = "draft",
) -> GuardResult:
    """
    Run Phase -1 guard checks.
    
    Args:
        phase_dir: Path to phase_minus_1/ directory
        schemas_dir: Path to schemas/ directory
        mode: "draft" allows TBDs, "commit" requires no TBDs + research retrieved
        
    Returns:
        GuardResult with all findings
    """
    result = GuardResult(mode=mode)
    
    build_file = phase_dir / "build_candidate.yaml"
    research_file = phase_dir / "research_snapshot.yaml"
    
    # Check files exist
    if not build_file.exists():
        result.schema_errors.append(f"File not found: {build_file}")
        result.is_ready = False
    if not research_file.exists():
        result.schema_errors.append(f"File not found: {research_file}")
        result.is_ready = False
    
    if not result.is_ready:
        return result
    
    # Load YAML files (with detailed error reporting)
    build_data, build_error = _load_yaml_safe(build_file)
    research_data, research_error = _load_yaml_safe(research_file)
    
    if build_data is None:
        result.schema_errors.append(f"build_candidate.yaml: {build_error}")
        result.is_ready = False
    if research_data is None:
        result.schema_errors.append(f"research_snapshot.yaml: {research_error}")
        result.is_ready = False
    
    if not result.is_ready:
        return result
    
    # Load and validate schemas
    for yaml_file, yaml_data in [
        (build_file, build_data),
        (research_file, research_data),
    ]:
        schema_filename = SCHEMA_MAP.get(yaml_file.name)
        if not schema_filename:
            result.schema_errors.append(f"No schema defined for {yaml_file.name}")
            result.is_ready = False
            continue
        
        schema_path = schemas_dir / schema_filename
        if not schema_path.exists():
            result.schema_errors.append(f"Schema not found: {schema_path}")
            result.is_ready = False
            continue
        
        schema = _load_json_schema(schema_path)
        if schema is None:
            result.schema_errors.append(f"Invalid schema: {schema_path}")
            result.is_ready = False
            continue
        
        # Validate against schema (collects ALL errors)
        errors = _validate_schema(yaml_data, schema, yaml_file.name)
        result.schema_errors.extend(errors)
        if errors:
            result.is_ready = False
    
    # Size cap checks (blocking)
    for yaml_file, yaml_data in [
        (build_file, build_data),
        (research_file, research_data),
    ]:
        violations = _check_size_caps(yaml_file, yaml_data)
        result.size_violations.extend(violations)
        if violations:
            result.is_ready = False
    
    # Cross-file consistency: build_id must match
    build_id_candidate = build_data.get("build_id")
    build_id_research = research_data.get("build_id")
    result.build_id = build_id_candidate
    
    if build_id_candidate != build_id_research:
        result.build_id_mismatch = (
            f"build_id mismatch: build_candidate has '{build_id_candidate}', "
            f"research_snapshot has '{build_id_research}'"
        )
        result.is_ready = False
    
    # TBD detection
    for yaml_file, yaml_data in [
        (build_file, build_data),
        (research_file, research_data),
    ]:
        tbd_fields = _find_tbd_values(yaml_data)
        for field in tbd_fields:
            result.tbd_fields.append(f"{yaml_file.name}: {field}")
    
    # Mode-specific checks
    if mode == "commit":
        # TBDs not allowed in commit mode
        if result.tbd_fields:
            result.is_ready = False
        
        # Commit readiness checks (includes ISO timestamp validation)
        blockers = _check_commit_readiness(research_data)
        result.commit_blockers.extend(blockers)
        if blockers:
            result.is_ready = False
    
    # HITL questions
    result.hitl_questions = [
        f"Commit to build {result.build_id}?",
        "Is research sufficient to proceed to planning?",
    ]
    
    return result


# --- Exception packet generation ---

def generate_exception_packet(
    result: GuardResult,
    output_path: Path,
) -> Path:
    """
    Generate Phase -1 exception packet (markdown).
    
    Args:
        result: GuardResult from check_phase_minus_1
        output_path: Where to write the packet
        
    Returns:
        Path to generated packet
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines = [
        "# Phase -1 Exception Packet",
        "",
        f"Generated: {datetime.now().isoformat()}",
        f"Mode: {result.mode}",
        f"Build ID: {result.build_id or 'unknown'}",
        "",
    ]
    
    # Status
    if result.is_ready:
        lines.append("## Status: ✅ READY")
    else:
        lines.append("## Status: ❌ NOT READY")
    lines.append("")
    
    # Schema errors
    if result.schema_errors:
        lines.append("## Schema Violations (blocking)")
        lines.append("")
        for error in result.schema_errors:
            lines.append(f"- ❌ {error}")
        lines.append("")
    
    # Size violations (blocking - use ❌)
    if result.size_violations:
        lines.append("## Size Cap Violations (blocking)")
        lines.append("")
        for violation in result.size_violations:
            lines.append(f"- ❌ {violation}")
        lines.append("")
    
    # Build ID mismatch
    if result.build_id_mismatch:
        lines.append("## Build ID Mismatch (blocking)")
        lines.append("")
        lines.append(f"- ❌ {result.build_id_mismatch}")
        lines.append("")
    
    # Commit blockers
    if result.commit_blockers:
        lines.append("## Commit Blockers")
        lines.append("")
        for blocker in result.commit_blockers:
            lines.append(f"- 🚫 {blocker}")
        lines.append("")
    
    # TBD fields
    if result.tbd_fields:
        if result.mode == "commit":
            status = "❌ (blocking in commit mode)"
        else:
            status = "📝 (allowed in draft mode)"
        lines.append(f"## Incomplete Fields (TBD) {status}")
        lines.append("")
        for field in result.tbd_fields:
            lines.append(f"- {field}")
        lines.append("")
    
    # HITL questions
    lines.append("## HITL Questions")
    lines.append("")
    for q in result.hitl_questions:
        lines.append(f"- [ ] {q}")
    lines.append("")
    
    # Next actions (use RERUN_CMD constant)
    lines.append("## Next Actions")
    lines.append("")
    if not result.is_ready:
        action_num = 1
        if result.schema_errors:
            lines.append(f"{action_num}. Fix schema violations")
            action_num += 1
        if result.size_violations:
            lines.append(f"{action_num}. Reduce file size to within caps")
            action_num += 1
        if result.build_id_mismatch:
            lines.append(f"{action_num}. Ensure build_id matches in both files")
            action_num += 1
        if result.commit_blockers:
            lines.append(f"{action_num}. Complete research (set valid retrieved_at, evaluate sufficiency)")
            action_num += 1
        if result.tbd_fields and result.mode == "commit":
            lines.append(f"{action_num}. Fill in all TBD fields")
            action_num += 1
        lines.append(f"{action_num}. Re-run: `{RERUN_CMD} --mode {result.mode}`")
    else:
        if result.tbd_fields:
            lines.append("1. (Optional) Fill remaining TBD fields")
        lines.append("2. Answer HITL questions above")
        lines.append("3. Proceed to Phase 0 intent capture")
    lines.append("")
    
    content = "\n".join(lines)
    output_path.write_text(content)
    
    return output_path
