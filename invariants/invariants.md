# Invariants (V0)

These are contracts the build must obey. V0 uses them primarily for human review.
Automated enforcement can be added later.

## I1 — No Secrets in Repo
**Contract**
No API keys, tokens, or credentials may be committed to the repository.

**Allowed**
- `.env.example` with placeholder values only
- environment variables provided at runtime

## I2 — No Sweeping Refactors
**Contract**
Changes must be scoped to the current task. Do not refactor unrelated code.

**Allowed**
- Fixing immediate dependencies of the change
- Renaming if explicitly required by the task

**Not Allowed**
- "While I'm here" cleanups
- Restructuring code not mentioned in the task

## I3 — Deterministic and Scoped Writes
**Contract**
All file writes must be deterministic and scoped to the current step.

**Rules**
- Touch only files required by the task
- Prefer editing existing files over creating new ones
- Generated outputs must be reproducible given the same inputs

## I4 — Namespace Isolation
**Contract**
Runs must be namespaced by `project_slug` and must not mix artifacts across projects.

## I5 — Single Approval Checkpoint (V0)
**Contract**
V0 uses exactly one human approval checkpoint per run: after chair synthesis, before commit.
