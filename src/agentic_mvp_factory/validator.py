"""Minimal validation for run outputs before commit (S07)."""

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from uuid import UUID

import yaml


@dataclass
class ValidationResult:
    """Result of validating run outputs."""
    is_valid: bool
    details: str
    failed_artifacts: List[str]


# Required sections in synthesis (markdown headings)
REQUIRED_SYNTHESIS_SECTIONS = ["SYNTHESIS", "DECISION_PACKET"]

# Required top-level keys if decision_packet is YAML/JSON
REQUIRED_DECISION_KEYS = ["decisions", "next_actions"]


def _extract_yaml_blocks(content: str) -> List[str]:
    """Extract YAML code blocks from markdown content."""
    pattern = r"```ya?ml\s*(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
    return matches


def _extract_json_blocks(content: str) -> List[str]:
    """Extract JSON code blocks from markdown content."""
    pattern = r"```json\s*(.*?)```"
    matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
    return matches


def _validate_synthesis_content(content: str) -> Tuple[bool, str]:
    """
    Validate synthesis artifact content.
    
    Checks:
    1. Content is not empty
    2. Contains required markdown sections
    3. If YAML/JSON blocks exist, they parse correctly
    
    Returns:
        (is_valid, error_message)
    """
    if not content or not content.strip():
        return False, "Synthesis content is empty"
    
    # Check for required sections (case-insensitive, flexible format)
    missing_sections = []
    for section in REQUIRED_SYNTHESIS_SECTIONS:
        # Accept multiple formats:
        # - Markdown headings: ## SYNTHESIS, # SYNTHESIS
        # - Colon format: SYNTHESIS:
        # - Bold format: **SYNTHESIS**
        escaped_section = re.escape(section)
        patterns = [
            rf"^#{{1,6}}\s*{escaped_section}",  # Markdown heading
            rf"^{escaped_section}\s*:",          # Colon format at line start
            rf"\*\*{escaped_section}\*\*",       # Bold format
            rf"^{escaped_section}\b",            # Plain section name at line start
        ]
        found = any(
            re.search(p, content, re.IGNORECASE | re.MULTILINE)
            for p in patterns
        )
        if not found:
            missing_sections.append(section)
    
    if missing_sections:
        return False, f"Missing required sections: {', '.join(missing_sections)}"
    
    # Try to parse any YAML blocks
    yaml_blocks = _extract_yaml_blocks(content)
    for i, block in enumerate(yaml_blocks):
        try:
            yaml.safe_load(block)
        except yaml.YAMLError as e:
            return False, f"YAML block {i+1} parse error: {str(e)[:100]}"
    
    # Try to parse any JSON blocks
    json_blocks = _extract_json_blocks(content)
    for i, block in enumerate(json_blocks):
        try:
            json.loads(block)
        except json.JSONDecodeError as e:
            return False, f"JSON block {i+1} parse error: {str(e)[:100]}"
    
    return True, ""


def _validate_decision_packet_content(content: str) -> Tuple[bool, str]:
    """
    Validate decision_packet artifact content.
    
    Checks:
    1. Content is not empty
    2. If structured (YAML/JSON), parse and check required keys
    
    Returns:
        (is_valid, error_message)
    """
    if not content or not content.strip():
        return False, "Decision packet content is empty"
    
    # Try to parse as YAML first (more permissive)
    yaml_blocks = _extract_yaml_blocks(content)
    json_blocks = _extract_json_blocks(content)
    
    # Check structured blocks for required keys
    for block in yaml_blocks:
        try:
            data = yaml.safe_load(block)
            if isinstance(data, dict):
                missing_keys = [k for k in REQUIRED_DECISION_KEYS if k not in data]
                if missing_keys:
                    return False, f"Decision packet YAML missing keys: {', '.join(missing_keys)}"
        except yaml.YAMLError as e:
            return False, f"Decision packet YAML parse error: {str(e)[:100]}"
    
    for block in json_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                missing_keys = [k for k in REQUIRED_DECISION_KEYS if k not in data]
                if missing_keys:
                    return False, f"Decision packet JSON missing keys: {', '.join(missing_keys)}"
        except json.JSONDecodeError as e:
            return False, f"Decision packet JSON parse error: {str(e)[:100]}"
    
    # If no structured blocks, just ensure it has some content
    # (for V0, we accept plain markdown decision packets)
    return True, ""


def validate_run_outputs(run_id: UUID) -> ValidationResult:
    """
    Validate run outputs before commit.
    
    Checks:
    1. Synthesis artifact exists and is valid
    2. Decision packet artifact exists and is valid
    3. No critical errors that would prevent commit
    
    Args:
        run_id: The run to validate
        
    Returns:
        ValidationResult with is_valid, details, and failed_artifacts
    """
    from agentic_mvp_factory.repo import get_artifacts
    
    failed_artifacts = []
    error_details = []
    
    # Get synthesis artifacts
    synthesis_artifacts = get_artifacts(run_id, kind="synthesis")
    if not synthesis_artifacts:
        failed_artifacts.append("synthesis")
        error_details.append("No synthesis artifact found")
    else:
        is_valid, error = _validate_synthesis_content(synthesis_artifacts[0].content)
        if not is_valid:
            failed_artifacts.append("synthesis")
            error_details.append(f"Synthesis: {error}")
    
    # Get decision_packet artifacts
    decision_artifacts = get_artifacts(run_id, kind="decision_packet")
    if not decision_artifacts:
        failed_artifacts.append("decision_packet")
        error_details.append("No decision_packet artifact found")
    else:
        is_valid, error = _validate_decision_packet_content(decision_artifacts[0].content)
        if not is_valid:
            failed_artifacts.append("decision_packet")
            error_details.append(f"Decision packet: {error}")
    
    # Build result
    if failed_artifacts:
        return ValidationResult(
            is_valid=False,
            details="; ".join(error_details),
            failed_artifacts=failed_artifacts,
        )
    
    return ValidationResult(
        is_valid=True,
        details="All outputs validated successfully",
        failed_artifacts=[],
    )


def validate_content_standalone(
    content: str,
    content_type: str = "synthesis",
) -> Tuple[bool, str]:
    """
    Validate content without database access (for testing).
    
    Args:
        content: The content to validate
        content_type: "synthesis" or "decision_packet"
        
    Returns:
        (is_valid, error_message)
    """
    if content_type == "synthesis":
        return _validate_synthesis_content(content)
    elif content_type == "decision_packet":
        return _validate_decision_packet_content(content)
    else:
        return False, f"Unknown content type: {content_type}"


# --- Phase -1 schema validation ---

def validate_file(file_path: str) -> Tuple[bool, str]:
    """
    Validate a YAML file against its corresponding JSON schema.
    
    Supports Phase -1 artifacts:
    - build_candidate.yaml -> schemas/build_candidate.schema.json
    - research_snapshot.yaml -> schemas/research_snapshot.schema.json
    
    Args:
        file_path: Path to the YAML file to validate
        
    Returns:
        (is_valid, error_message)
        
    Raises:
        FileNotFoundError: If file or schema not found
        ValueError: If file type not supported
    """
    from pathlib import Path
    
    try:
        import jsonschema
    except ImportError:
        return False, "jsonschema package not installed. Run: pip install jsonschema"
    
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Determine schema file based on filename
    schema_map = {
        "build_candidate.yaml": "build_candidate.schema.json",
        "research_snapshot.yaml": "research_snapshot.schema.json",
    }
    
    filename = file_path.name
    if filename not in schema_map:
        raise ValueError(f"No schema defined for file: {filename}")
    
    # Find schema file (relative to repo root)
    schema_filename = schema_map[filename]
    
    # Try multiple schema locations
    possible_schema_paths = [
        file_path.parent.parent / "schemas" / schema_filename,  # phase_minus_1/../schemas/
        Path("schemas") / schema_filename,  # ./schemas/
        file_path.parent / "schemas" / schema_filename,  # same dir/schemas/
    ]
    
    schema_path = None
    for p in possible_schema_paths:
        if p.exists():
            schema_path = p
            break
    
    if schema_path is None:
        raise FileNotFoundError(f"Schema not found: {schema_filename}")
    
    # Load YAML file
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, f"YAML parse error: {str(e)}"
    
    # Load JSON schema
    try:
        with open(schema_path, 'r') as f:
            schema = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Schema JSON parse error: {str(e)}"
    
    # Validate against schema
    try:
        jsonschema.validate(instance=data, schema=schema)
        print(f"✓ {file_path.name} validates against {schema_path.name}")
        return True, ""
    except jsonschema.ValidationError as e:
        error_msg = f"Validation failed: {e.message}"
        if e.absolute_path:
            error_msg += f" at path: {list(e.absolute_path)}"
        print(f"✗ {file_path.name} validation failed: {error_msg}")
        return False, error_msg
    except jsonschema.SchemaError as e:
        return False, f"Schema error: {e.message}"

