"""Tests for S07 validation (no OpenRouter calls, fixture-based)."""

import pytest

from agentic_mvp_factory.validator import (
    ValidationResult,
    validate_content_standalone,
    REQUIRED_SYNTHESIS_SECTIONS,
    REQUIRED_DECISION_KEYS,
)


# =============================================================================
# FIXTURES - Valid and invalid content samples
# =============================================================================

VALID_SYNTHESIS = """
# Council Synthesis

## SYNTHESIS

This is the unified implementation plan synthesized from all council members.

Key decisions:
- Use PostgreSQL for persistence
- CLI-first approach
- LangGraph for orchestration

## DECISION_PACKET

```yaml
decisions:
  - Use Postgres over SQLite for production readiness
  - OpenRouter as default model gateway
next_actions:
  - Implement S08 commit logic
  - Add status command
risks:
  - Model API rate limits
  - Schema migrations on upgrade
```

## Next Steps

1. Run validation
2. Commit to repo
"""

VALID_SYNTHESIS_NO_STRUCTURED = """
# Council Synthesis

## SYNTHESIS

This is the unified implementation plan.

## DECISION_PACKET

Key decisions made:
- Use PostgreSQL
- CLI-first

Next actions:
- Implement commit
- Add tests
"""

INVALID_SYNTHESIS_MISSING_SECTIONS = """
# Council Synthesis

This is some content but missing required sections.

The plan is to do things.
"""

INVALID_SYNTHESIS_BAD_YAML = """
# Council Synthesis

## SYNTHESIS

Some valid synthesis content.

## DECISION_PACKET

```yaml
decisions:
  - item one
  - item two
next_actions  # Missing colon - invalid YAML
  - action one
```
"""

INVALID_SYNTHESIS_BAD_JSON = """
# Council Synthesis

## SYNTHESIS

Some valid synthesis content.

## DECISION_PACKET

```json
{
  "decisions": ["one", "two"],
  "next_actions": ["action"
}
```
"""

VALID_DECISION_PACKET = """
# Decision Packet

```yaml
decisions:
  - Use PostgreSQL for persistence
  - CLI-first approach
next_actions:
  - Implement S08 commit logic
  - Add status command
risks:
  - Model API rate limits
```
"""

VALID_DECISION_PACKET_PLAIN = """
# Decision Packet

This is a plain markdown decision packet without structured data.

## Key Decisions

- Use PostgreSQL
- CLI-first

## Next Actions

- Commit to repo
"""

INVALID_DECISION_PACKET_MISSING_KEYS = """
# Decision Packet

```yaml
decisions:
  - Use PostgreSQL
# Missing next_actions key
risks:
  - Some risk
```
"""

EMPTY_CONTENT = ""
WHITESPACE_ONLY = "   \n\t\n   "


# =============================================================================
# TESTS - Synthesis validation
# =============================================================================

class TestSynthesisValidation:
    """Tests for synthesis content validation."""
    
    def test_valid_synthesis_with_structured_yaml(self):
        """Valid synthesis with YAML block should pass."""
        is_valid, error = validate_content_standalone(VALID_SYNTHESIS, "synthesis")
        assert is_valid is True
        assert error == ""
    
    def test_valid_synthesis_without_structured_data(self):
        """Valid synthesis with plain markdown should pass."""
        is_valid, error = validate_content_standalone(VALID_SYNTHESIS_NO_STRUCTURED, "synthesis")
        assert is_valid is True
        assert error == ""
    
    def test_invalid_synthesis_missing_sections(self):
        """Synthesis missing required sections should fail."""
        is_valid, error = validate_content_standalone(INVALID_SYNTHESIS_MISSING_SECTIONS, "synthesis")
        assert is_valid is False
        assert "Missing required sections" in error
        # Should mention at least one missing section
        assert any(section in error for section in REQUIRED_SYNTHESIS_SECTIONS)
    
    def test_invalid_synthesis_bad_yaml(self):
        """Synthesis with invalid YAML should fail."""
        is_valid, error = validate_content_standalone(INVALID_SYNTHESIS_BAD_YAML, "synthesis")
        assert is_valid is False
        assert "YAML" in error and "parse error" in error
    
    def test_invalid_synthesis_bad_json(self):
        """Synthesis with invalid JSON should fail."""
        is_valid, error = validate_content_standalone(INVALID_SYNTHESIS_BAD_JSON, "synthesis")
        assert is_valid is False
        assert "JSON" in error and "parse error" in error
    
    def test_empty_synthesis(self):
        """Empty synthesis should fail."""
        is_valid, error = validate_content_standalone(EMPTY_CONTENT, "synthesis")
        assert is_valid is False
        assert "empty" in error.lower()
    
    def test_whitespace_only_synthesis(self):
        """Whitespace-only synthesis should fail."""
        is_valid, error = validate_content_standalone(WHITESPACE_ONLY, "synthesis")
        assert is_valid is False
        assert "empty" in error.lower()


# =============================================================================
# TESTS - Decision packet validation
# =============================================================================

class TestDecisionPacketValidation:
    """Tests for decision packet content validation."""
    
    def test_valid_decision_packet_with_yaml(self):
        """Valid decision packet with YAML should pass."""
        is_valid, error = validate_content_standalone(VALID_DECISION_PACKET, "decision_packet")
        assert is_valid is True
        assert error == ""
    
    def test_valid_decision_packet_plain_markdown(self):
        """Valid plain markdown decision packet should pass."""
        is_valid, error = validate_content_standalone(VALID_DECISION_PACKET_PLAIN, "decision_packet")
        assert is_valid is True
        assert error == ""
    
    def test_invalid_decision_packet_missing_keys(self):
        """Decision packet with YAML missing required keys should fail."""
        is_valid, error = validate_content_standalone(INVALID_DECISION_PACKET_MISSING_KEYS, "decision_packet")
        assert is_valid is False
        assert "missing keys" in error.lower()
        assert "next_actions" in error
    
    def test_empty_decision_packet(self):
        """Empty decision packet should fail."""
        is_valid, error = validate_content_standalone(EMPTY_CONTENT, "decision_packet")
        assert is_valid is False
        assert "empty" in error.lower()


# =============================================================================
# TESTS - Edge cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""
    
    def test_unknown_content_type(self):
        """Unknown content type should fail."""
        is_valid, error = validate_content_standalone("some content", "unknown_type")
        assert is_valid is False
        assert "Unknown content type" in error
    
    def test_synthesis_case_insensitive_sections(self):
        """Section detection should be case-insensitive."""
        content = """
# synthesis

## Synthesis

Some content here.

## decision_packet

More content.
"""
        is_valid, error = validate_content_standalone(content, "synthesis")
        assert is_valid is True
    
    def test_synthesis_with_different_heading_levels(self):
        """Should detect sections with different heading levels."""
        content = """
### SYNTHESIS

Content.

# DECISION_PACKET

More content.
"""
        is_valid, error = validate_content_standalone(content, "synthesis")
        assert is_valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

