# Step Prompt Template (V0)

## Context
You are implementing a single, scoped step in a larger build tracked by `tracker/factory_tracker.yaml`.
Your job is to produce **working code** and **local proof** for this step, while staying aligned with:
- `spec/spec.yaml`
- `invariants/invariants.md`
- `.cursor/rules/*` (if present)

## Step Metadata (fill in)
- Step ID: {{STEP_ID}}
- Step Title: {{STEP_TITLE}}
- Goal (one sentence): {{STEP_GOAL}}
- Repo Root: {{REPO_ROOT}}
- Files Allowed to Touch (optional): {{FILES_ALLOWED}}
- External Tools Allowed: {{TOOLS_ALLOWED}} (e.g., "none", "OpenRouter API", "Postgres")

## Inputs
Paste or reference:
- Relevant tracker entry for {{STEP_ID}}
- Any existing code paths or files that must be respected
- Any required environment variables for running locally

## Requirements
### Functional
List concrete behaviors the code must implement for this step.

### Non-Functional
- Keep changes minimal and reviewable
- Prefer boring, maintainable solutions
- Do not invent new architecture beyond what this step needs

### Safety / Invariants
List the **specific** invariants that apply to this step (copy from `invariants/invariants.md`).
If none apply, say “None referenced.”

## Plan
Write a short plan with:
- Files to create/update
- Key functions/classes
- Any DB/schema changes
- How you will validate locally

## Implementation
### Files to Create / Update
For each file:
- Path
- Purpose
- Key content overview

### Code Changes
Provide the code edits needed.
If you are in Cursor, you can describe exactly what to implement and where.
Do not hand-wave.

## Local Verification (Proof)
Provide **exact commands** to run locally to validate this step.

Include:
- Command(s)
- Expected output or success criteria
- Any setup steps (env vars, docker compose, etc.)

If tests are not applicable, define a manual proof (but keep it concrete).

## Deliverables Checklist
- [ ] Code compiles / runs
- [ ] Verification commands provided
- [ ] Tracker step can be marked done
- [ ] No unexplained changes outside step scope

## Notes / Risks
Call out:
- Anything uncertain
- Follow-ups for later steps
- Any edge cases you intentionally deferred
