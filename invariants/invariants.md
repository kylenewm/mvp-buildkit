# Invariants (V0)

These are contracts the build must obey. V0 uses them primarily for human review.
Automated enforcement can be added later.

## I1 — No Secrets in Repo
**Contract**
No API keys, tokens, or credentials may be committed to the repository.

**Allowed**
- `.env.example` with placeholder values only
- environment variables provided at runtime

## I2 — Durable References for External Claims (future)
**Contract**
If the system stores an external “fact” (e.g., research result), it must include a durable pointer.
(V0: placeholder; deep research not implemented.)

## I3 — Single Approval Checkpoint (V0)
**Contract**
V0 uses exactly one human approval checkpoint per run: after chair synthesis, before commit.

## I4 — Namespace Isolation
**Contract**
Runs must be namespaced by `project_slug` and must not mix artifacts across projects.
