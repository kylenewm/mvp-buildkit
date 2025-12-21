# Hotfix Sync Prompt (V0)

## Context
A manual hotfix was applied directly in the repo (outside the automation loop).
Your job is to synchronize the “source of truth” docs so future automation does not drift.

This is NOT a rewrite of everything.
It is a minimal reconciliation.

## Inputs Required
1. Intent Note (from human)
2. Git diff or a list of changed files
3. Current key artifacts (if they exist):
   - `spec/spec.yaml`
   - `tracker/tracker.yaml`
   - `invariants/invariants.md`
   - `.cursor/rules/*`

## Intent Note
{{INTENT_NOTE}}

## Changed Files / Diff
{{DIFF_OR_FILE_LIST}}

## Requirements
### Update Rules
- Do not invent intent beyond the human’s Intent Note
- Only update the minimum docs needed to reflect the change
- If intent note is too vague for the diff, ask for clarification (one question)

### What to Update
- `spec/spec.yaml`: only if the hotfix changes scope/constraints/decisions
- `tracker/tracker.yaml`: mark affected steps, add a patch step if needed
- `invariants/invariants.md`: only if the hotfix reveals a new invariant that should be explicit
- `.cursor/rules/*`: only if the hotfix indicates a missing rule or recurring failure pattern

## Output Format (strict)
1. Summary
2. What Changed (from diff)
3. Spec Updates (if any)
4. Tracker Updates (if any)
5. Invariant Updates (if any)
6. Cursor Rule Updates (if any)
7. Open Questions (if clarification needed)

## Deliverables
- Provide exact patch-style edits (copy-pastable blocks) for each file you update
- Keep edits minimal and easy to review
