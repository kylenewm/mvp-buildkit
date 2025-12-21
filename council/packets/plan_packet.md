# Council Packet — V0 Implementation Plan (agentic-mvp-factory)

## Objective
Generate a concrete, buildable V0 implementation plan for a CLI-first “council runner” that:
- runs multi-model drafts + critiques + chair synthesis
- pauses for human approval (approve | edit+approve | reject)
- resumes across CLI sessions via Postgres persistence
- on approval, commits a minimal artifact pack stub into a target repo

## Inputs You Must Respect
Read and follow:
- `spec/spec.yaml` (canonical V0 scope and constraints)

Assume:
- Runner is local CLI
- Persistence is remote Postgres (Railway-style `DATABASE_URL`)
- Model gateway is OpenRouter first (OpenAI + Gemini + Claude)
- Chair is configurable per run
- No UI in V0 (CLI only)
- V0 validation is minimal (parsing + required keys only)

## Deliverable Format (strict)
Produce a single plan with the following sections, in this exact order:

1. **Architecture Overview**
   - components and responsibilities
   - where LangGraph sits
   - what lives in Postgres vs filesystem

2. **Data Model**
   - Postgres tables and key columns
   - how artifacts are stored and retrieved
   - how runs are namespaced by `project_slug`

3. **LangGraph Workflow**
   - state object fields (minimal)
   - node list and edges
   - how HITL interrupt works and how resume works
   - rerun behavior: reject creates a NEW run_id (parent linkage optional)

4. **Model Gateway**
   - ModelClient interface
   - OpenRouter client behavior (timeouts, retries as placeholders are ok)
   - how chair and non-chair models are configured

5. **CLI UX**
   - exact commands for: init, run, status, show, approve, commit
   - what each command prints/returns
   - how edit+approve works (EDITOR-based)

6. **Repo Output Writer**
   - exact files written on commit (stable paths)
   - snapshot version folder strategy: `versions/<timestamp>_<run_id>/`
   - commit manifest structure

7. **Milestones and Implementation Order**
   - M0 → M6, with concrete acceptance criteria per milestone
   - identify the “hard parts” explicitly (interrupt/resume)

8. **Risks and Simplifications**
   - what you are intentionally punting to V1
   - how the design keeps an upgrade path open

## Council Protocol (how to respond)
You are one council member. Output:
- one coherent plan
- explicit tradeoffs
- no fluff

If you need to make assumptions, list them under “Risks and Simplifications”.

## Output Quality Bar
The plan should be detailed enough that an engineer can implement it without inventing missing pieces, but must stay inside V0 scope (no web UI, no deep research, no full state guard).
