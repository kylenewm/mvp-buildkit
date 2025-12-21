# Patch Prompt Template (V0)

## Context
You are applying a **surgical patch** to an existing codebase.
This patch is triggered by:
- failing tests
- runtime errors
- integration mismatch
- spec drift discovered during execution

Your goal is to fix the issue with the **minimum change** while preserving existing behavior.

## Patch Metadata (fill in)
- Patch ID: {{PATCH_ID}}
- Trigger: {{TRIGGER}} (e.g., "tests failing", "OpenRouter 429", "resume broken")
- Severity: {{SEVERITY}} (low | medium | high)
- Repo Root: {{REPO_ROOT}}
- Files Suspected: {{FILES_SUSPECTED}}

## Inputs
Provide:
- Error logs / stack traces
- Failing test output (if any)
- The relevant spec constraint or invariant (if any)
- The exact commit / diff context (if available)

## Requirements
### Must Fix
- Describe the concrete broken behavior to eliminate

### Must Not Break
- List any behaviors that must remain unchanged

### Constraints
- Keep patch minimal
- Avoid refactors unless required to resolve the bug

## Diagnosis
Explain:
- Root cause hypothesis (with evidence from logs)
- Alternative hypotheses you ruled out

## Patch Plan
- What to change
- Why this is the minimal fix
- Which files will be touched

## Patch Implementation
Provide exact edits.

## Verification
Provide exact commands to confirm the fix.
- Re-run failing test(s)
- Or run a minimal reproduction script
- Include expected output

## Post-Patch Notes
- Any tech debt created
- Any new invariant or guard you recommend adding later (optional)
