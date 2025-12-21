# Build Guide (V0)

This repo is a CLI-first “council runner” that helps you build projects using a repeatable loop:
council → plan → tracker steps → step execution → review → patch (if needed) → hotfix sync (if manual changes).

## Manual workflow (before the runner is finished)
1. Start with `spec/spec.yaml` and the packet in `council/packets/plan_packet.md`.
2. Use your preferred LLM setup (OpenAI/Gemini/Claude) to generate drafts and critiques.
3. Use `prompts/chair_synthesis_template.md` to produce a single executable plan + tracker steps.
4. Execute tracker steps using `prompts/step_template.md`.
5. Review each step using `prompts/review_template.md`.
6. If review fails, apply `prompts/patch_template.md` and re-run proof.
7. If you manually hotfix outside the loop, reconcile docs using `prompts/hotfix_sync.md`.

## Outputs (what “commit” will eventually write)
- Spec: `spec/spec.yaml`
- Tracker: `tracker/tracker.yaml`
- Invariants: `invariants/invariants.md`
- Cursor rules: `.cursor/rules/*`
- Prompts: `prompts/*`
- Snapshot versions: `versions/<timestamp>_<run_id>/...`

## Environment variables (runner)
- DATABASE_URL
- OPENROUTER_API_KEY
