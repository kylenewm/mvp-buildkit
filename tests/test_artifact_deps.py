"""Unit tests for Artifact Dependency Law enforcement."""

import pytest

from agentic_mvp_factory.artifact_deps import (
    ALLOWED_INPUTS_BY_TASK_TYPE,
    validate_allowed_inputs,
    get_allowed_inputs,
)


class TestDependencyMatrix:
    """Test that the dependency matrix is correctly defined."""

    def test_spec_only_accepts_plan(self):
        """Spec council should only accept plan as input."""
        allowed = get_allowed_inputs("spec")
        assert allowed == {"plan"}

    def test_invariants_only_accepts_spec(self):
        """Invariants council should only accept spec as input."""
        allowed = get_allowed_inputs("invariants")
        assert allowed == {"spec"}

    def test_tracker_accepts_spec_and_invariants(self):
        """Tracker council should accept spec + invariants."""
        allowed = get_allowed_inputs("tracker")
        assert allowed == {"spec", "invariants"}

    def test_prompts_accepts_spec_invariants_tracker(self):
        """Prompts council should accept spec + invariants + tracker."""
        allowed = get_allowed_inputs("prompts")
        assert allowed == {"spec", "invariants", "tracker"}

    def test_cursor_rules_accepts_spec_and_invariants(self):
        """Cursor rules council should accept spec + invariants."""
        allowed = get_allowed_inputs("cursor_rules")
        assert allowed == {"spec", "invariants"}


class TestValidInputs:
    """Test that valid inputs pass validation."""

    def test_spec_accepts_plan(self):
        """Spec should accept plan input."""
        validate_allowed_inputs("spec", {"plan": "kind=plan from run xyz"})

    def test_invariants_accepts_spec(self):
        """Invariants should accept spec input."""
        validate_allowed_inputs("invariants", {"spec": "kind=output from spec run"})

    def test_tracker_accepts_spec_and_invariants(self):
        """Tracker should accept spec + invariants."""
        validate_allowed_inputs("tracker", {
            "spec": "kind=output",
            "invariants": "kind=output",
        })

    def test_prompts_accepts_all_three(self):
        """Prompts should accept spec + invariants + tracker."""
        validate_allowed_inputs("prompts", {
            "spec": "kind=output",
            "invariants": "kind=output",
            "tracker": "kind=output",
        })

    def test_cursor_rules_accepts_spec_and_invariants(self):
        """Cursor rules should accept spec + invariants."""
        validate_allowed_inputs("cursor_rules", {
            "spec": "kind=output",
            "invariants": "kind=output",
        })


class TestForbiddenInputs:
    """Test that forbidden inputs are rejected."""

    def test_context_pack_rejected_for_all_tasks(self):
        """Context pack should be rejected for all Phase 2 task types."""
        for task_type in ALLOWED_INPUTS_BY_TASK_TYPE:
            with pytest.raises(ValueError) as exc_info:
                validate_allowed_inputs(task_type, {
                    "phase_0/context_pack_lite.md": "test"
                })
            assert "FORBIDDEN" in str(exc_info.value)

    def test_cursor_rules_rejected_as_prompts_input(self):
        """Cursor rules output should not be accepted as prompts input."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("prompts", {
                ".cursor/rules/00_global.md": "test"
            })
        assert "FORBIDDEN" in str(exc_info.value)

    def test_prompts_output_rejected_as_input(self):
        """Prompts output should not be accepted as input to any council."""
        for task_type in ALLOWED_INPUTS_BY_TASK_TYPE:
            with pytest.raises(ValueError) as exc_info:
                validate_allowed_inputs(task_type, {
                    "prompts/step_template": "test"
                })
            assert "FORBIDDEN" in str(exc_info.value)


class TestDependencyChainEnforcement:
    """Test that the dependency chain is enforced (no skipping)."""

    def test_invariants_rejects_plan(self):
        """Invariants should reject plan directly (must go through spec)."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("invariants", {"plan": "kind=plan"})
        assert "FORBIDDEN" in str(exc_info.value)

    def test_tracker_rejects_plan(self):
        """Tracker should reject plan directly (must go through spec)."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("tracker", {"plan": "kind=plan"})
        assert "FORBIDDEN" in str(exc_info.value)

    def test_prompts_rejects_plan(self):
        """Prompts should reject plan directly."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("prompts", {"plan": "kind=plan"})
        assert "FORBIDDEN" in str(exc_info.value)

    def test_cursor_rules_rejects_plan(self):
        """Cursor rules should reject plan directly."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("cursor_rules", {"plan": "kind=plan"})
        assert "FORBIDDEN" in str(exc_info.value)

    def test_cursor_rules_rejects_tracker(self):
        """Cursor rules should reject tracker (not in dependency path)."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("cursor_rules", {"tracker": "kind=output"})
        # Either FORBIDDEN (task-specific) or NOT ALLOWED (general)
        error_msg = str(exc_info.value)
        assert "FORBIDDEN" in error_msg or "NOT ALLOWED" in error_msg

    def test_invariants_rejects_tracker(self):
        """Invariants should reject tracker (wrong direction)."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("invariants", {"tracker": "kind=output"})
        assert "NOT ALLOWED" in str(exc_info.value)


class TestErrorMessages:
    """Test that error messages are informative."""

    def test_error_lists_all_violations(self):
        """Error should list ALL violations, not just the first one."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("spec", {
                "phase_0/context_pack_lite.md": "test1",
                "tracker": "test2",
                ".cursor/rules/00_global.md": "test3",
            })
        error_msg = str(exc_info.value)
        # Should mention multiple violations
        assert "3 illegal input" in error_msg

    def test_error_shows_allowed_inputs(self):
        """Error for NOT ALLOWED should show what inputs are allowed."""
        with pytest.raises(ValueError) as exc_info:
            validate_allowed_inputs("spec", {"unknown_input": "test"})
        assert "plan" in str(exc_info.value)  # Should show allowed inputs

