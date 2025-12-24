# Cursor Global Rules (V0)

## Change Discipline
- Prefer minimal, boring changes.
- Do not invent architecture beyond the current tracker step.
- **Touch at most 3 files per step** unless explicitly justified in the task.
- Patch-only: small diffs, targeted edits.

## Source of Truth
- Follow `spec/spec.yaml` and `invariants/invariants.md`.
- Check `docs/ARTIFACT_REGISTRY.md` for canonical artifact paths.

## Verification
- Every step must include local verification commands.
- Include expected success criteria (what "done" looks like).

## Ambiguity
- If something is ambiguous, surface it explicitly as an open question.
- Do not guess. Ask or create a TODO.
