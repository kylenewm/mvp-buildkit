"""Artifact Dependency Law (V0) — Centralized enforcement of allowed inputs per Phase 2 task.

This module defines what each Phase 2 artifact council is allowed to read/reference.
Any attempt to use disallowed inputs will raise a ValueError with enumerated violations.

Dependency Matrix (V0) — Logical Flow:
    Plan → Spec → Invariants → Tracker → Prompts
                        ↘ Cursor-Rules

- spec:         plan (transforms plan into structured requirements)
- invariants:   spec (defines rules for what the spec describes)
- tracker:      spec + invariants (creates steps respecting invariants)
- prompts:      spec + invariants + tracker (templates for executing steps)
- cursor_rules: spec + invariants (IDE guidance for respecting rules)

FORBIDDEN (never allowed as Phase 2 inputs):
- phase_0/* (context packs are Phase 1 only)
- phase_minus_1/* (Phase -1 artifacts are spec council input only)
- .cursor/rules/* (cursor rules are outputs, not inputs)
- prompts/* (prompts are outputs, not inputs)
- tracker/* (tracker is an output, only prompts can read it)
"""

from typing import Dict, List, Set


# Canonical input names for validation
PLAN_ARTIFACT = "plan"  # kind="plan" or "synthesis" artifact from approved plan run
SPEC = "spec"  # kind="output" artifact from approved spec run (maps to spec/spec.yaml)
INVARIANTS = "invariants"  # kind="output" artifact from approved invariants run
TRACKER = "tracker"  # kind="output" artifact from approved tracker run

# Phase -1 artifacts - ONLY allowed for spec council
BUILD_CANDIDATE = "phase_minus_1/build_candidate.yaml"
RESEARCH_SNAPSHOT = "phase_minus_1/research_snapshot.yaml"

# Context packs (Phase 0) - NEVER allowed in Phase 2
CONTEXT_PACK_LITE = "phase_0/context_pack_lite.md"
SPEC_LITE = "phase_0/spec_lite.yaml"

# Generated outputs - NEVER allowed as inputs to any council
CURSOR_RULES_GLOBAL = ".cursor/rules/00_global.md"
CURSOR_RULES_INVARIANTS = ".cursor/rules/10_invariants.md"
PROMPTS_STEP = "prompts/step_template.md"
PROMPTS_REVIEW = "prompts/review_template.md"
PROMPTS_PATCH = "prompts/patch_template.md"
PROMPTS_CHAIR = "prompts/chair_synthesis_template.md"


# === ALLOWED INPUTS BY TASK TYPE ===
# Each key is a task_type, value is a set of allowed input identifiers
# This enforces the logical dependency chain

ALLOWED_INPUTS_BY_TASK_TYPE: Dict[str, Set[str]] = {
    # Spec: first in chain, takes plan
    "spec": {
        PLAN_ARTIFACT,
    },
    # Invariants: takes spec (refined requirements)
    "invariants": {
        SPEC,
    },
    # Tracker: takes spec + invariants (NOT plan directly)
    "tracker": {
        SPEC,
        INVARIANTS,
    },
    # Prompts: takes spec + invariants + tracker
    "prompts": {
        SPEC,
        INVARIANTS,
        TRACKER,
    },
    # Cursor rules: takes spec + invariants
    "cursor_rules": {
        SPEC,
        INVARIANTS,
    },
}


# === EXPLICITLY FORBIDDEN INPUTS (Phase 2 never reads these) ===
# Patterns that are always rejected, regardless of task type

FORBIDDEN_INPUT_PATTERNS: Set[str] = {
    # Phase 0 context packs (Phase 1 only)
    "phase_0/",
    "context_pack",
    
    # Generated outputs (cannot be inputs to any council)
    ".cursor/rules/",
    "prompts/step_template",
    "prompts/review_template",
    "prompts/patch_template",
    "prompts/chair_synthesis",
}

# Task-specific forbidden patterns (in addition to global forbidden)
# These prevent "skipping" the dependency chain
TASK_SPECIFIC_FORBIDDEN: Dict[str, Set[str]] = {
    # Invariants cannot read plan directly (must go through spec)
    "invariants": {"plan"},
    # Tracker cannot read plan directly (must go through spec)
    "tracker": {"plan", "phase_minus_1/"},
    # Prompts cannot read plan directly
    "prompts": {"plan", "phase_minus_1/"},
    # Cursor rules cannot read plan or tracker directly
    "cursor_rules": {"plan", "tracker", "phase_minus_1/"},
}


def _is_forbidden_pattern(input_name: str, task_type: str = None) -> bool:
    """Check if an input matches any forbidden pattern.
    
    Args:
        input_name: The input identifier to check
        task_type: Optional task type for task-specific forbidden checks
    
    Returns:
        True if the input is forbidden
    """
    # Check global forbidden patterns
    for pattern in FORBIDDEN_INPUT_PATTERNS:
        if pattern in input_name:
            return True
    
    # Check task-specific forbidden patterns
    if task_type and task_type in TASK_SPECIFIC_FORBIDDEN:
        for pattern in TASK_SPECIFIC_FORBIDDEN[task_type]:
            if pattern in input_name or input_name == pattern:
                return True
    
    return False


def validate_allowed_inputs(task_type: str, inputs: Dict[str, str]) -> None:
    """
    Validate that all inputs are allowed for the given task type.
    
    Enforces the dependency chain:
        Plan → Spec → Invariants → Tracker → Prompts
                            ↘ Cursor-Rules
    
    Args:
        task_type: The Phase 2 task type (spec, invariants, tracker, prompts, cursor_rules)
        inputs: Dict mapping logical input name -> source description
                e.g. {"plan": "kind=plan from run xyz", "spec": "kind=output from run abc"}
    
    Raises:
        ValueError: If any inputs are not allowed, listing ALL violations
    """
    if task_type not in ALLOWED_INPUTS_BY_TASK_TYPE:
        raise ValueError(f"Unknown task type for dependency validation: {task_type}")
    
    allowed = ALLOWED_INPUTS_BY_TASK_TYPE[task_type]
    violations: List[str] = []
    
    for input_name, source in inputs.items():
        # Check explicitly forbidden patterns (global + task-specific)
        if _is_forbidden_pattern(input_name, task_type):
            violations.append(
                f"FORBIDDEN: '{input_name}' violates dependency chain for {task_type} (source: {source})"
            )
            continue
        
        # Check if input is in allowed set
        if input_name not in allowed:
            violations.append(
                f"NOT ALLOWED for {task_type}: '{input_name}' (source: {source}). "
                f"Allowed inputs: {sorted(allowed)}"
            )
    
    if violations:
        error_lines = [
            f"Artifact Dependency Violation in {task_type} council:",
            f"  Found {len(violations)} illegal input(s):",
        ]
        for v in violations:
            error_lines.append(f"    - {v}")
        raise ValueError("\n".join(error_lines))


def get_allowed_inputs(task_type: str) -> Set[str]:
    """Return the set of allowed inputs for a task type."""
    if task_type not in ALLOWED_INPUTS_BY_TASK_TYPE:
        raise ValueError(f"Unknown task type: {task_type}")
    return ALLOWED_INPUTS_BY_TASK_TYPE[task_type].copy()


# === SELF-TEST ===

def _self_test():
    """Run self-tests to verify dependency enforcement."""
    print("Running artifact_deps self-tests...")
    print("=" * 60)
    
    errors = []
    
    # Test 1: Context pack should be rejected for ALL Phase 2 tasks
    print("\n[Test 1] Context pack rejection (all task types):")
    for task_type in ALLOWED_INPUTS_BY_TASK_TYPE:
        try:
            validate_allowed_inputs(task_type, {
                "phase_0/context_pack_lite.md": "test_source"
            })
            errors.append(f"FAIL: {task_type} should reject context pack")
        except ValueError as e:
            if "FORBIDDEN" in str(e):
                print(f"  ✓ {task_type} correctly rejects context pack")
            else:
                errors.append(f"FAIL: {task_type} wrong error for context pack: {e}")
    
    # Test 2: Cursor rules should be rejected as input to prompts council
    print("\n[Test 2] Cursor rules rejected as input to prompts:")
    try:
        validate_allowed_inputs("prompts", {
            ".cursor/rules/00_global.md": "test_source"
        })
        errors.append("FAIL: prompts should reject cursor rules as input")
    except ValueError as e:
        if "FORBIDDEN" in str(e):
            print("  ✓ prompts correctly rejects cursor rules input")
        else:
            errors.append(f"FAIL: prompts wrong error for cursor rules: {e}")
    
    # Test 3: Spec council accepts plan
    print("\n[Test 3] Spec council accepts plan:")
    try:
        validate_allowed_inputs("spec", {
            "plan": "kind=plan from run xyz",
        })
        print("  ✓ spec accepts valid input (plan)")
    except ValueError as e:
        errors.append(f"FAIL: spec should accept plan: {e}")
    
    # Test 4: Tracker should NOT accept plan directly (dependency chain violation)
    print("\n[Test 4] Tracker rejects plan (must use spec instead):")
    try:
        validate_allowed_inputs("tracker", {
            "plan": "kind=plan"
        })
        errors.append("FAIL: tracker should not accept plan as input")
    except ValueError as e:
        if "FORBIDDEN" in str(e) or "NOT ALLOWED" in str(e):
            print("  ✓ tracker correctly rejects plan (dependency chain)")
        else:
            errors.append(f"FAIL: tracker wrong error for plan: {e}")
    
    # Test 5: Tracker accepts spec + invariants
    print("\n[Test 5] Tracker accepts spec + invariants:")
    try:
        validate_allowed_inputs("tracker", {
            "spec": "kind=output from spec run",
            "invariants": "kind=output from invariants run",
        })
        print("  ✓ tracker accepts spec + invariants")
    except ValueError as e:
        errors.append(f"FAIL: tracker should accept spec + invariants: {e}")
    
    # Test 6: Invariants should accept spec but NOT plan
    print("\n[Test 6] Invariants accepts spec, rejects plan:")
    try:
        validate_allowed_inputs("invariants", {
            "spec": "kind=output from spec run"
        })
        print("  ✓ invariants accepts spec")
    except ValueError as e:
        errors.append(f"FAIL: invariants should accept spec: {e}")
    
    try:
        validate_allowed_inputs("invariants", {
            "plan": "kind=plan"
        })
        errors.append("FAIL: invariants should not accept plan directly")
    except ValueError as e:
        if "FORBIDDEN" in str(e):
            print("  ✓ invariants correctly rejects plan (must go through spec)")
        else:
            errors.append(f"FAIL: invariants wrong error for plan: {e}")
    
    # Test 7: Invariants should NOT accept tracker
    print("\n[Test 7] Invariants rejects tracker (wrong direction):")
    try:
        validate_allowed_inputs("invariants", {
            "tracker": "kind=output"
        })
        errors.append("FAIL: invariants should not accept tracker")
    except ValueError as e:
        if "NOT ALLOWED" in str(e):
            print("  ✓ invariants correctly rejects tracker")
        else:
            errors.append(f"FAIL: invariants wrong error for tracker: {e}")
    
    # Test 8: Prompts accepts spec + invariants + tracker
    print("\n[Test 8] Prompts accepts spec + invariants + tracker:")
    try:
        validate_allowed_inputs("prompts", {
            "spec": "kind=output",
            "invariants": "kind=output",
            "tracker": "kind=output",
        })
        print("  ✓ prompts accepts spec + invariants + tracker")
    except ValueError as e:
        errors.append(f"FAIL: prompts should accept spec + invariants + tracker: {e}")
    
    # Test 9: Cursor rules accepts spec + invariants but NOT tracker
    print("\n[Test 9] Cursor rules accepts spec + invariants, rejects tracker:")
    try:
        validate_allowed_inputs("cursor_rules", {
            "spec": "kind=output",
            "invariants": "kind=output",
        })
        print("  ✓ cursor_rules accepts spec + invariants")
    except ValueError as e:
        errors.append(f"FAIL: cursor_rules should accept spec + invariants: {e}")
    
    try:
        validate_allowed_inputs("cursor_rules", {
            "tracker": "kind=output"
        })
        errors.append("FAIL: cursor_rules should not accept tracker")
    except ValueError as e:
        if "FORBIDDEN" in str(e) or "NOT ALLOWED" in str(e):
            print("  ✓ cursor_rules correctly rejects tracker")
        else:
            errors.append(f"FAIL: cursor_rules wrong error for tracker: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"FAILED: {len(errors)} test(s)")
        for err in errors:
            print(f"  {err}")
        return False
    else:
        print("All self-tests passed!")
        return True


if __name__ == "__main__":
    import sys
    success = _self_test()
    sys.exit(0 if success else 1)

