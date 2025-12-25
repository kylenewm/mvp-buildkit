# Context State — Agentic MVP Factory Implementation Status

**Generated:** 2025-12-24  
**Last Updated:** 2025-12-25 (Artifact Dependency Law added)  
**Build ID:** B01  
**Purpose:** Comprehensive status of all phases and their implementation state

---

## Overview

This document provides a complete status report for all phases of the Agentic MVP Factory system, including what's implemented, what's missing, and how each phase integrates with the overall workflow.

---

## Phase -1: Build Commitment + Research Bounds

### Purpose
Lock the build you are about to do and bound the research needed before any "planning council" or repo-writing begins. Prevents scope drift, planning without evidence, schema drift, and surprise repo overwrites.

### Implementation Status: ✅ **FULLY IMPLEMENTED**

#### What's Implemented

1. **Guard Implementation** (`src/agentic_mvp_factory/phase_minus_1/guard.py`):
   - ✅ Two modes: `draft` (TBDs allowed) and `commit` (strict validation)
   - ✅ Schema validation (JSON Schema Draft-07)
   - ✅ Size cap enforcement (max_lines, max_words)
   - ✅ Build ID cross-file matching
   - ✅ TBD detection (blocking in commit mode)
   - ✅ Commit-mode checks:
     - `retrieved_at` must be non-null and valid ISO timestamp
     - `sufficiency.status` must not be "unknown"
   - ✅ Exception packet generation (`phase_minus_1/exception_packet.md`)
   - ✅ Proper exit codes (0 = READY, nonzero = NOT READY)

2. **CLI Command** (`council phase-1-guard`):
   - ✅ Command exists: `council phase-1-guard --mode {draft|commit}`
   - ✅ Writes exception packet automatically
   - ✅ Detailed error reporting
   - ✅ HITL questions in exception packet

3. **Integration with Planning Flow**:
   - ✅ `--phase-1-check` flag in `council run plan`
   - ✅ Runs guard in commit mode before council starts
   - ✅ Blocks council execution if Phase -1 not READY
   - ✅ Shows error summary (schema errors, TBD fields, commit blockers)

4. **Directory Structure**:
   - ✅ `phase_minus_1/build_candidate.yaml` (canonical, human-edited)
   - ✅ `phase_minus_1/research_snapshot.yaml` (canonical, human-edited)
   - ✅ `phase_minus_1/exception_packet.md` (generated, NOT canonical)
   - ✅ `schemas/build_candidate.schema.json`
   - ✅ `schemas/research_snapshot.schema.json`

#### Current Workflow

```bash
# Step 1: Generate drafts from prompt (NEW!)
council intake --project <slug> --prompt "Build a CLI that..." --mode draft

# Step 2: Run web research to fill findings (NEW!)
council research --project <slug> --provider tavily --mark-sufficient

# Step 3: Iterate in draft mode
council phase-1-guard --mode draft

# Step 4: Validate in commit mode
council phase-1-guard --mode commit

# Step 5: Use in planning (optional but recommended)
council run plan --phase-1-check --project test --packet ... --models ... --chair ...
```

#### New Capabilities (Added Dec 25)

1. **`council intake`**: Generate draft `build_candidate.yaml` and `research_snapshot.yaml` from a prompt using LLM.
2. **`council research`**: Bounded web search (Tavily/Exa) to fill research findings automatically.

#### What Phase -1 Does NOT Do (Correctly)
- ❌ Does not write `spec/spec.yaml`
- ❌ Does not write tracker files
- ❌ Does not write prompts
- ❌ Does not touch `src/` except Phase -1 module itself
- ✅ Only writes `phase_minus_1/exception_packet.md` (as designed)

#### Status
**READY FOR USE** — Phase -1 guard is fully functional and integrated. The `--phase-1-check` flag is optional (defaults to False), but when used, it properly gates the planning council.

---

## Phase 0: Context Pack (Lite)

### Purpose
Inject bounded context into planning prompts without bloating. Provides a curated, factual summary of build commitment, constraints, research conclusions, and unknowns.

### Implementation Status: ✅ **FULLY IMPLEMENTED**

#### What's Implemented

1. **Files Exist**:
   - ✅ `phase_0/context_pack_lite.md` — Contains build context, constraints, research links, assumptions, unknowns
   - ✅ `phase_0/spec_lite.yaml` — Lightweight spec summary

2. **Content Structure**:
   - ✅ What we're building
   - ✅ Key constraints
   - ✅ Research links (with findings)
   - ✅ Assumptions
   - ✅ Unknowns (carry forward)

3. **CLI Integration** (Implemented Dec 25):
   - ✅ `--context <path>` flag in `council run plan` command
   - ✅ Context pack injected into Draft, Critique, and Chair prompts
   - ✅ Context appears as `## Context Pack (Phase 0 Lite)` section

#### Current Workflow

```bash
# Context injection in planning
council run plan \
  --project <slug> \
  --packet council/packets/plan_packet.md \
  --context phase_0/context_pack_lite.md \
  --models m1,m2 \
  --chair m1
```

#### Status
**FULLY INTEGRATED** — The `--context` flag works end-to-end. Context is injected into all planning prompts.

---

## Phase 1: Planning Council

### Purpose
Generate one executable plan with multi-perspective critique. Uses multiple models to draft, critique, and synthesize a final plan that requires human approval before proceeding.

### Implementation Status: ✅ **FULLY IMPLEMENTED**

#### What's Implemented

1. **CLI Command** (`council run plan`):
   - ✅ Command exists with all required options:
     - `--project` (required)
     - `--packet` (required, path to planning packet)
     - `--models` (required, comma-separated list)
     - `--chair` (required, model ID for synthesis)
     - `--phase-1-check` (optional flag)
   - ✅ Validates environment variables (DATABASE_URL, OPENROUTER_API_KEY)
   - ✅ Parses models and validates minimum count (>= 2)
   - ✅ Progress reporting during execution

2. **LangGraph Workflow** (`src/agentic_mvp_factory/graph.py`):
   - ✅ `load_packet` — Loads planning packet file and stores as artifact
   - ✅ `draft_generate` — Parallel draft generation from multiple models
   - ✅ `critique_generate` — Parallel critique generation (each model critiques all drafts)
   - ✅ `chair_synthesize` — Chair model synthesizes final plan from drafts + critiques
   - ✅ `pause_for_approval` — HITL checkpoint, sets status to `waiting_for_approval`

3. **Plan Artifact Storage**:
   - ✅ Plan artifact written with `kind="plan"` (stored verbatim from chair synthesis)
   - ✅ Also stores `kind="synthesis"` and `kind="decision_packet"`
   - ✅ All artifacts persisted to database with proper metadata

4. **Approval Flow** (`council approve`):
   - ✅ `--approve` — Approve plan as-is
   - ✅ `--edit` — Edit plan in $EDITOR then approve
   - ✅ `--reject` — Reject and create new run with feedback
   - ✅ Sets status to `ready_to_commit` after approval
   - ✅ Runs validation before finalizing status
   - ✅ Stores approval decision and metadata

5. **Integration**:
   - ✅ Phase -1 guard integration (optional `--phase-1-check`)
   - ✅ Phase 2 spec council can read plan artifacts (`kind="plan"` or fallback to `kind="synthesis"`)
   - ✅ Plan artifacts retrievable via `council show <run_id> --section plan`
   - ✅ Full artifact inspection via `council show <run_id> --section all`

#### Current Workflow

```bash
# Step 1: Run planning council
council run plan \
  --project <slug> \
  --packet council/packets/plan_packet.md \
  --models <m1>,<m2>,<m3> \
  --chair <m1> \
  [--phase-1-check]

# Workflow executes:
# 1. Load packet → store as artifact
# 2. Generate drafts (parallel) → store artifacts
# 3. Generate critiques (parallel) → store artifacts
# 4. Chair synthesis → store plan artifact
# 5. Status: waiting_for_approval

# Step 2: Approve plan
council approve <run_id> --approve
# or
council approve <run_id> --edit

# Sets status: ready_to_commit

# Step 3: Commit (if needed)
council commit <run_id> --repo <path>
```

#### Status (Updated Dec 25)

According to `plan/B01_plan.yaml`:
- ✅ **S02**: `--context` flag to inject Phase 0 context pack (IMPLEMENTED)
- ⚠️ **S02**: `--dry-run` flag to skip persistence (not yet implemented)
- ✅ **S03**: Plan artifact storage (already implemented)

**FULLY FUNCTIONAL** — Phase 1 planning council works end-to-end with context injection.

---

## Phase 2: Artifact Councils (Sequential)

### Purpose
Turn an approved plan into a **canonical artifact pack** you can execute with. Each artifact is generated sequentially via council (drafts + critiques + chair synthesis) with HITL approval before proceeding to the next.

### Implementation Status: ✅ **FULLY IMPLEMENTED** (Dec 25)

#### All Artifact Councils Complete

1. **Spec update** (`spec/spec.yaml`) ✅ **IMPLEMENTED**
2. **Tracker steps** (`tracker/factory_tracker.yaml`) ✅ **IMPLEMENTED**
3. **Prompts** (4 files via YAML envelope) ✅ **IMPLEMENTED**
   - `prompts/step_template.md`
   - `prompts/review_template.md`
   - `prompts/patch_template.md`
   - `prompts/chair_synthesis_template.md`
4. **Cursor rules** (2 files via YAML envelope) ✅ **IMPLEMENTED**
   - `.cursor/rules/00_global.md`
   - `.cursor/rules/10_invariants.md`
5. **Invariants** (`invariants/invariants.md`) ✅ **IMPLEMENTED**

#### What's Implemented: Spec Council

1. **CLI Command** (`council run spec`):
   - ✅ Command exists: `council run spec --from-plan <plan_run_id> --project <slug> --models <list> --chair <model>`
   - ✅ Validates plan run ID format
   - ✅ Validates plan is approved (`ready_to_commit` or `completed` status)
   - ✅ Validates minimum model count (>= 2)
   - ✅ Progress reporting during execution

2. **Council Workflow** (`src/agentic_mvp_factory/phase2/spec_council.py`):
   - ✅ Loads approved plan artifact (`kind="plan"` or fallback to `kind="synthesis"`)
   - ✅ Creates new run with `task_type="spec"` and `parent_run_id` linkage
   - ✅ Generates 3+ spec drafts in parallel (YAML format)
   - ✅ Generates 3+ critiques in parallel
   - ✅ Chair synthesis produces final YAML
   - ✅ YAML validation (syntax, schema_version, required keys)
   - ✅ Strips markdown fences if present
   - ✅ Stores as `kind="output"` artifact (validated, cleaned)
   - ✅ Also stores `kind="synthesis"` (raw chair output)
   - ✅ Sets status to `waiting_for_approval`

3. **Integration**:
   - ✅ Can be approved via `council approve <run_id> --approve`
   - ✅ Can be committed via `council commit <run_id> --repo <path>`
   - ✅ Spec council outputs are written to `spec/spec.yaml` on commit

#### All Councils Implemented

1. **Tracker Council** (`src/agentic_mvp_factory/phase2/tracker_council.py`):
   - ✅ `council run tracker --from-plan <id> --project <slug> --models m1,m2 --chair m1`
   - ✅ Generates `tracker/factory_tracker.yaml`
   - ✅ Validates `schema_version` and `steps` list
   - ✅ **Loads spec + invariants** (enforced dependency chain)

2. **Prompts Council** (`src/agentic_mvp_factory/phase2/prompts_council.py`):
   - ✅ `council run prompts --from-plan <id> --project <slug> --models m1,m2 --chair m1`
   - ✅ Generates YAML envelope with 4 prompt templates
   - ✅ Commit unpacks envelope to individual files
   - ✅ **Loads spec + invariants + tracker** (enforced dependency chain)

3. **Cursor Rules Council** (`src/agentic_mvp_factory/phase2/cursor_rules_council.py`):
   - ✅ `council run cursor-rules --from-plan <id> --project <slug> --models m1,m2 --chair m1`
   - ✅ Generates YAML envelope with 2 rule files
   - ✅ Commit unpacks envelope to `.cursor/rules/` directory
   - ✅ **Loads spec + invariants** (enforced dependency chain)

4. **Invariants Council** (`src/agentic_mvp_factory/phase2/invariants_council.py`):
   - ✅ `council run invariants --from-plan <id> --project <slug> --models m1,m2 --chair m1`
   - ✅ Generates `invariants/invariants.md` (plain markdown)
   - ✅ **Loads spec** (enforced dependency chain)

#### Artifact Dependency Law (V0) — Enforced

**Dependency Chain (Logical Flow):**
```
Plan → Spec → Invariants → Tracker → Prompts
                    ↘ Cursor-Rules
```

**Enforcement Mechanism** (`src/agentic_mvp_factory/artifact_deps.py`):
- ✅ Centralized validation module (`validate_allowed_inputs()`)
- ✅ Each council validates inputs before any LLM calls
- ✅ Prevents skipping the dependency chain (e.g., tracker cannot read plan directly)
- ✅ Blocks forbidden inputs (context packs, generated outputs as inputs)
- ✅ Enumerated error messages (lists ALL violations)

**Allowed Inputs Per Council:**
- **spec**: `plan` only
- **invariants**: `spec` only (not plan directly)
- **tracker**: `spec` + `invariants` (not plan directly)
- **prompts**: `spec` + `invariants` + `tracker`
- **cursor_rules**: `spec` + `invariants` (not tracker)

**Forbidden (All Councils):**
- ❌ `phase_0/*` (context packs are Phase 1 only)
- ❌ `.cursor/rules/*` (outputs cannot be inputs)
- ❌ `prompts/*` (outputs cannot be inputs)

**Tests:**
- ✅ 21 unit tests in `tests/test_artifact_deps.py`
- ✅ Self-test runner: `python -m agentic_mvp_factory.artifact_deps`

#### Current Workflow (Full Pipeline)

**Important:** Phase 2 councils must run in dependency order. Each council automatically loads its required inputs from previous approved runs.

```bash
# Step 1: Approve plan (Phase 1)
council approve <plan_run_id> --approve

# Step 2: Run all Phase 2 councils sequentially (dependency-enforced)
# Spec: reads plan
council run spec --from-plan <plan_run_id> --project <slug> --models m1,m2 --chair m1
council approve <spec_run_id> --approve

# Invariants: reads spec (dependency enforced)
council run invariants --from-plan <plan_run_id> --project <slug> --models m1,m2 --chair m1
council approve <invariants_run_id> --approve

# Tracker: reads spec + invariants (dependency enforced)
council run tracker --from-plan <plan_run_id> --project <slug> --models m1,m2 --chair m1
council approve <tracker_run_id> --approve

# Prompts: reads spec + invariants + tracker (dependency enforced)
council run prompts --from-plan <plan_run_id> --project <slug> --models m1,m2 --chair m1
council approve <prompts_run_id> --approve

# Cursor Rules: reads spec + invariants (dependency enforced)
council run cursor-rules --from-plan <plan_run_id> --project <slug> --models m1,m2 --chair m1
council approve <rules_run_id> --approve

# Step 3: Commit full pack in one go (NEW!)
council commit-pack --project <slug> --from-plan <plan_run_id> --repo <path>
```

**Note:** If you try to run a council before its dependencies are approved, you'll get a clear error:
```
ValueError: No approved spec run found for plan <id>. Run spec council first.
```

#### Automation Script

```bash
# Run the full Phase 2 pipeline with one script
scripts/run_phase2_pipeline.sh <approved_plan_run_id> "m1,m2" m1
```

#### Commit Safety Rails (S01, S02)

All commits enforce:
- ✅ Target must be a Git repo
- ✅ Fail if dirty (uncommitted changes)
- ✅ Registry-driven allowlist (`docs/ARTIFACT_REGISTRY.md`)
- ✅ Additive-only (no overwrites by default)
- ✅ Snapshots written to `versions/<timestamp>_<run_id>/`
- ✅ Manifest written with every commit

#### Status
**FULLY FUNCTIONAL** — All 5 Phase 2 artifact councils are implemented and tested. Full pack commit verified on `tmp/toy_repo`.

---

## Summary: Overall System Status

### All Phases Complete! ✅
- ✅ **Phase -1**: Build commitment + research bounds guard (+ `intake` + `research` commands)
- ✅ **Phase 0**: Context pack integration (`--context` flag)
- ✅ **Phase 1**: Planning council (full workflow)
- ✅ **Phase 2**: All 5 artifact councils (Spec, Tracker, Prompts, Cursor Rules, Invariants)

### Integration Status

```
Phase -1 → Phase 0 → Phase 1 → Phase 2
   ✅         ✅        ✅        ✅
```

- **Phase -1 → Phase 1**: ✅ Integrated (optional `--phase-1-check` flag)
- **Phase 0 → Phase 1**: ✅ Integrated (`--context` flag)
- **Phase 1 → Phase 2**: ✅ Integrated (all councils read plan artifacts)

### Workflow Completeness

**Full End-to-End Flow (VERIFIED):**
```
Intake → Research → Phase -1 guard → Context pack → Planning council → Approve plan → 
  ✅        ✅            ✅              ✅               ✅                 ✅

→ Spec council → Approve → Tracker council → Approve → Prompts council → Approve →
       ✅           ✅            ✅              ✅            ✅            ✅

→ Cursor rules council → Approve → Invariants council → Approve → Full pack commit
          ✅                ✅              ✅              ✅            ✅
```

### New CLI Commands (Dec 25)

| Command | Description |
| :--- | :--- |
| `council intake` | Generate draft Phase -1 YAMLs from a prompt |
| `council research` | Run web search (Tavily/Exa) to fill research snapshot |
| `council commit-pack` | Commit ALL latest approved Phase 2 outputs in one operation |
| `council exec-aid` | Generate a step-specific Cursor prompt from the tracker |

### Remaining Enhancements (Nice-to-Have)

1. `--dry-run` flag for testing without persistence
2. Step execution from tracker (`council exec --step S01`)
3. E2E automated tests with mocked models

---

## File Locations Reference

### Phase -1
- Guard: `src/agentic_mvp_factory/phase_minus_1/guard.py`
- Intake: `src/agentic_mvp_factory/phase_minus_1/intake.py`
- Research: `src/agentic_mvp_factory/research_runner.py`
- Search Clients: `src/agentic_mvp_factory/search_clients.py`
- Files: `phase_minus_1/build_candidate.yaml`, `phase_minus_1/research_snapshot.yaml`
- Schemas: `schemas/build_candidate.schema.json`, `schemas/research_snapshot.schema.json`

### Phase 0
- Files: `phase_0/context_pack_lite.md`, `phase_0/spec_lite.yaml`
- Integration: `--context` flag in `cli.py`, injection in `graph.py`

### Phase 1
- Graph: `src/agentic_mvp_factory/graph.py`
- CLI: `src/agentic_mvp_factory/cli.py`

### Phase 2
- Spec Council: `src/agentic_mvp_factory/phase2/spec_council.py`
- Tracker Council: `src/agentic_mvp_factory/phase2/tracker_council.py`
- Prompts Council: `src/agentic_mvp_factory/phase2/prompts_council.py`
- Cursor Rules Council: `src/agentic_mvp_factory/phase2/cursor_rules_council.py`
- Invariants Council: `src/agentic_mvp_factory/phase2/invariants_council.py`
- Dependency Enforcement: `src/agentic_mvp_factory/artifact_deps.py` (Artifact Dependency Law)
- Commit Writer: `src/agentic_mvp_factory/repo_writer.py`
- Exec Aid Generator: `src/agentic_mvp_factory/exec_aid.py`

### Scripts
- Drift Checker: `scripts/check_artifacts.py`
- Toy Dogfood: `scripts/toy_dogfood.sh`
- Phase 2 Pipeline: `scripts/run_phase2_pipeline.sh`

### Tests
- Artifact Dependency Tests: `tests/test_artifact_deps.py` (21 tests)

### Registry
- Artifact Registry: `docs/ARTIFACT_REGISTRY.md` (Single Source of Truth for allowed/forbidden paths)

---

**Last Updated:** 2025-12-25  
**Status:** ✅ V1 Complete — All phases implemented and verified

