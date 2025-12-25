# Context State — Agentic MVP Factory Implementation Status

**Generated:** 2025-12-24  
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
# Step 1: Iterate in draft mode
council phase-1-guard --mode draft

# Step 2: Complete research, remove TBDs
# Edit phase_minus_1/research_snapshot.yaml

# Step 3: Validate in commit mode
council phase-1-guard --mode commit

# Step 4: Use in planning (optional but recommended)
council run plan --phase-1-check --project test --packet ... --models ... --chair ...
```

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

### Implementation Status: ⚠️ **PARTIALLY IMPLEMENTED**

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

#### What's Missing

1. **CLI Integration**:
   - ❌ No `--context` flag in `council run plan` command
   - ❌ Context pack is not injected into planning prompts
   - ❌ Planning prompts only use `packet_content`, not context pack

2. **Prompt Integration**:
   - ❌ `graph.py` draft generation doesn't include context pack
   - ❌ Chair synthesis doesn't include context pack
   - ❌ No mechanism to pass context to model calls

#### Planned Implementation (Per B01 Plan S02)

According to `plan/B01_plan.yaml` Step S02:
- **Title**: "Add --context and --dry-run flags to council run plan"
- **Description**: "Accept context pack file; add --dry-run to emit artifacts without persistence"
- **Files to touch**: `src/agentic_mvp_factory/cli.py`, `src/agentic_mvp_factory/graph.py`
- **Verification**: `council run plan --context phase_0/context_pack_lite.md --dry-run`
- **Done when**: "Context injected in prompts; --dry-run skips persistence"

#### Current Workflow Gap

```
Current:  Packet → Council → Plan
Should be: Phase -1 → Phase 0 (context pack) → Packet + Context → Council → Plan
```

#### Status
**NOT INTEGRATED** — Phase 0 files exist and contain useful context, but they are not automatically injected into the planning workflow. This is a planned feature (S02) that needs implementation.

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

#### Missing Features (Per B01 Plan)

According to `plan/B01_plan.yaml`:
- ❌ **S02**: `--context` flag to inject Phase 0 context pack (not implemented)
- ❌ **S02**: `--dry-run` flag to skip persistence (not implemented)
- ✅ **S03**: Plan artifact storage (already implemented)

#### Status
**FULLY FUNCTIONAL** — Phase 1 planning council works end-to-end. The core workflow is complete and production-ready. Missing features are enhancements (context injection, dry-run) that don't block basic functionality.

---

## Phase 2: Artifact Councils (Sequential)

### Purpose
Turn an approved plan into a **canonical artifact pack** you can execute with. Each artifact is generated sequentially via council (drafts + critiques + chair synthesis) with HITL approval before proceeding to the next.

### Implementation Status: ⚠️ **PARTIALLY IMPLEMENTED**

#### What Should Be Generated (Per README)

According to README (lines 268-287), Phase 2 should generate artifacts in this order:

1. **Spec update** (`spec/spec.yaml`) ✅ **IMPLEMENTED**
2. **Tracker steps** (`tracker/factory_tracker.yaml`) ❌ **NOT IMPLEMENTED**
3. **Step prompts** (`prompts/step_template.md` and variants) ❌ **NOT IMPLEMENTED**
4. **Review + patch prompts** (`prompts/review_template.md`, `prompts/patch_template.md`) ❌ **NOT IMPLEMENTED**
5. **Cursor rules** (`.cursor/rules/00_global.md`, `.cursor/rules/10_invariants.md`) ❌ **NOT IMPLEMENTED**
6. **Invariants** (`invariants/invariants.md`) ❌ **NOT IMPLEMENTED**

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

#### What's Missing: Other Artifact Councils

1. **Tracker Council**:
   - ❌ No `council run tracker` command
   - ❌ No tracker council implementation
   - ❌ No YAML generation for `tracker/factory_tracker.yaml`

2. **Prompts Council**:
   - ❌ No `council run prompts` command
   - ❌ No prompt template generation
   - ❌ No support for multiple prompt files

3. **Cursor Rules Council**:
   - ❌ No `council run cursor-rules` command
   - ❌ No Cursor rules generation

4. **Invariants Council**:
   - ❌ No `council run invariants` command
   - ❌ No invariants markdown generation

#### Current Workflow

```bash
# Step 1: Approve plan (Phase 1)
council approve <plan_run_id> --approve

# Step 2: Generate spec (Phase 2, artifact 1)
council run spec \
  --from-plan <plan_run_id> \
  --project <slug> \
  --models <m1>,<m2>,<m3> \
  --chair <m1>

# Step 3: Approve spec
council approve <spec_run_id> --approve

# Step 4: Commit spec
council commit <spec_run_id> --repo <path>

# Step 5: Generate other artifacts (NOT IMPLEMENTED)
# council run tracker --from-plan <plan_run_id> ...
# council run prompts --from-plan <plan_run_id> ...
# etc.
```

#### Implementation Pattern (For Future Artifacts)

The spec council (`spec_council.py`) provides a template for implementing other artifact councils:

1. Create new module: `src/agentic_mvp_factory/phase2/<artifact>_council.py`
2. Implement council function: `run_<artifact>_council(plan_run_id, project_slug, models, chair_model)`
3. Add CLI command: `@run.command("<artifact>")` in `cli.py`
4. Follow same pattern:
   - Load approved plan
   - Create new run with `task_type="<artifact>"`
   - Generate drafts (parallel)
   - Generate critiques (parallel)
   - Chair synthesis
   - Validate output format
   - Store as `kind="output"`
   - Set status to `waiting_for_approval`

#### Status
**PARTIALLY FUNCTIONAL** — Phase 2 infrastructure exists and works for spec generation. The pattern is established and can be replicated for other artifacts. Only 1 of 6 planned artifact types is implemented.

---

## Summary: Overall System Status

### Fully Implemented Phases
- ✅ **Phase -1**: Build commitment + research bounds guard
- ✅ **Phase 1**: Planning council (full workflow)

### Partially Implemented Phases
- ⚠️ **Phase 0**: Context pack files exist but not integrated into planning flow
- ⚠️ **Phase 2**: Spec council implemented; 5 other artifact councils missing

### Integration Status

```
Phase -1 → Phase 0 → Phase 1 → Phase 2
   ✅         ⚠️        ✅        ⚠️
```

- **Phase -1 → Phase 1**: ✅ Integrated (optional `--phase-1-check` flag)
- **Phase 0 → Phase 1**: ❌ Not integrated (no `--context` flag)
- **Phase 1 → Phase 2**: ✅ Integrated (spec council reads plan artifacts)

### Key Missing Features

1. **Phase 0 Integration** (Plan S02):
   - `--context` flag for `council run plan`
   - Context injection into planning prompts
   - `--dry-run` flag for testing without persistence

2. **Phase 2 Artifact Councils**:
   - Tracker council (`tracker/factory_tracker.yaml`)
   - Prompts council (step_template, review_template, patch_template)
   - Cursor rules council (`.cursor/rules/*.md`)
   - Invariants council (`invariants/invariants.md`)

### Workflow Completeness

**Current End-to-End Flow:**
```
Phase -1 guard → Planning council → Approve plan → Spec council → Approve spec → Commit spec
     ✅              ✅                  ✅            ✅              ✅           ✅
```

**Target End-to-End Flow:**
```
Phase -1 guard → Context pack → Planning council → Approve plan → 
     ✅              ⚠️              ✅                  ✅

→ Spec council → Approve → Tracker council → Approve → Prompts council → 
     ✅            ✅          ❌              ❌          ❌

→ Approve → Cursor rules council → Approve → Invariants council → Approve → 
   ❌            ❌                    ❌            ❌

→ Full artifact pack commit
   ⚠️
```

### Recommendations

1. **Immediate Priority**: Implement Phase 0 context injection (Plan S02) to improve plan quality
2. **Next Priority**: Implement remaining Phase 2 artifact councils following the spec council pattern
3. **Future Enhancement**: Add `--dry-run` mode for testing workflows without persistence

---

## File Locations Reference

### Phase -1
- Guard: `src/agentic_mvp_factory/phase_minus_1/guard.py`
- CLI: `src/agentic_mvp_factory/cli.py` (lines 1190-1299)
- Files: `phase_minus_1/build_candidate.yaml`, `phase_minus_1/research_snapshot.yaml`
- Schemas: `schemas/build_candidate.schema.json`, `schemas/research_snapshot.schema.json`

### Phase 0
- Files: `phase_0/context_pack_lite.md`, `phase_0/spec_lite.yaml`
- Integration: Not yet implemented (planned in Plan S02)

### Phase 1
- Graph: `src/agentic_mvp_factory/graph.py`
- CLI: `src/agentic_mvp_factory/cli.py` (lines 144-277)
- Approval: `src/agentic_mvp_factory/cli.py` (lines 732-920)

### Phase 2
- Spec Council: `src/agentic_mvp_factory/phase2/spec_council.py`
- CLI: `src/agentic_mvp_factory/cli.py` (lines 280-395)
- Other councils: Not yet implemented

---

**Last Updated:** 2025-12-24  
**Next Review:** After Plan S02-S08 implementation

