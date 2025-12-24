# Agentic MVP Factory (V0) — CLI Council Runner

A **CLI-first, stateful “council runner”** that helps you turn a scoped build intent into:
1) a multi-model plan you can approve,
2) a **canonical artifact pack** (spec, tracker, prompts, Cursor rules, invariants) you can approve,
3) a **package you can unzip into Cursor** to execute steps with tight constraints and proof.

---

## What V0 is (and is not)

### ✅ V0 provides
- **Phase -1**: Build commitment + bounded research snapshot (small, reviewable)
- **Phase 0 (Lite)**: Context pack (human-authored or lightly assisted) used as input to planning
- **Phase 1**: Multi-model planning council (drafts → critiques → chair synthesis) + **HITL approval**
- **Phase 2**: **Artifact-generation councils**, one artifact at a time, each with **HITL approval**
- **Commit**: Writes stable canonical files + snapshots versioned output
- **Provenance**: Run IDs, stored artifacts, and optional LangSmith traces

### ❌ V0 does NOT provide
- Web UI (CLI only)
- Fully autonomous building or execution without approval
- Heavy governance, sentinel enforcement, or “self-healing”
- Deep research automation as a default (see “Deep Research (planned)”)

---

## Core design principles

- **State-first**: runs + artifacts are persisted (Postgres)
- **Small artifacts**: size caps + schema validation before downstream phases
- **One decision at a time**: Phase 2 generates artifacts sequentially; you approve each before continuing
- **Canonical until regenerated**: committed artifacts stay canonical until you explicitly regenerate
- **No surprise refactors**: patch-only behavior is enforced by rules + invariants

---

## High-level flow (end-to-end)

### Execution order (what happens, in order)
1. **Phase -1: Commit the build**
   - Fill `phase_minus_1/build_candidate.yaml`
   - Fill `phase_minus_1/research_snapshot.yaml` (can be light)
   - Run guard → produce exception packet → **HITL: commit build + research sufficiency**
2. **Phase 0 (Lite): Context Pack**
   - Create/update `phase_0/context_pack_lite.md` (or equivalent)
   - This is the “injectable context” for planning prompts (bounded; not a dump)
3. **Phase 1: Planning council**
   - 3 models draft
   - 3 models critique
   - Chair synthesizes one plan
   - **HITL: approve/edit/reject** the plan
   - The approved plan becomes the **canonical “plan” artifact**
4. **Phase 2: Artifact councils (sequential, one-at-a-time)**
   - For each artifact (spec → tracker → prompts → Cursor rules → invariants):
     - Council drafts that artifact
     - Chair synthesizes a single candidate
     - **HITL: approve/edit/reject**
     - Approved result becomes canonical (until regenerated)
5. **Commit / Export**
   - Write canonical artifact pack into stable repo paths
   - Snapshot to `versions/<timestamp>_<run_id>/`
   - (Planned) export a **zip pack** you can unzip in Cursor for execution

### Diagram (V0)
```mermaid
flowchart TD

  %% ======================
  %% PHASE -1
  %% ======================
  A["Phase -1A: Build Commitment<br/>build_candidate.yaml<br/>- problem<br/>- target user<br/>- wow slice<br/>- constraints"] --> B["Phase -1B: Research Bounds<br/>research_snapshot.yaml<br/>- questions<br/>- findings<br/>- unknowns"]
  
  B --> C{"Phase -1 Guard + HITL<br/>Human confirms:<br/>- build is real<br/>- research sufficient"}

  %% ======================
  %% PHASE 0
  %% ======================
  C -->|approved| D["Phase 0: Intent + Context Pack<br/>context_pack_lite.md<br/>Synthesizes:<br/>- spec<br/>- constraints<br/>- research conclusions"]

  %% ======================
  %% PHASE 1 — PLAN COUNCIL
  %% ======================
  D --> E["Phase 1: PLAN COUNCIL<br/>(parallel drafts + critiques)<br/><br/>INPUTS:<br/>- build_candidate<br/>- research_snapshot<br/>- context_pack<br/><br/>PROCESS:<br/>- 3 model drafts<br/>- 3 cross-critiques<br/>- chair synthesis"]

  E --> F{"HITL: PLAN APPROVAL<br/>Human can:<br/>- approve<br/>- edit + approve<br/>- reject or rerun"}

  %% ======================
  %% PHASE 2 — ARTIFACT COUNCIL
  %% ======================
  F -->|approved| G["Phase 2: ARTIFACT COUNCIL<br/>SEQUENTIAL (one artifact at a time)<br/><br/>For EACH artifact:<br/>- 3 model drafts<br/>- critiques<br/>- chair synthesis"]

  G --> H["Artifact build order<br/>(locked sequence)<br/><br/>1 spec/spec.yaml<br/>2 invariants/invariants.md<br/>3 .cursor/rules/00_global.md<br/>4 .cursor/rules/10_invariants.md<br/>5 tracker/factory_tracker.yaml<br/>6 prompts/chair_synthesis_template.md<br/>7 prompts/step_template.md<br/>8 prompts/review_template.md<br/>9 prompts/patch_template.md"]

  %% ======================
  %% HITL PER ARTIFACT
  %% ======================
  H --> I{"HITL PER ARTIFACT<br/>Human approves or edits<br/>EACH artifact before continuing"}

  %% ======================
  %% FINALIZATION
  %% ======================
  I --> J{"Final Pack Approval<br/>Optional but recommended"}

  J -->|approved| K["Commit + Snapshot<br/>- write canonical files<br/>- versions/TIMESTAMP_RUNID/<br/>- COMMIT_MANIFEST.md"]

  K --> L["Optional Export<br/>Zip artifact pack<br/>for Cursor / external use"]
````

---

## Canonical artifacts (source of truth)

These are the **stable, canonical** files the system writes and future runs reference.

### Specification & planning

* `spec/spec.yaml` — project spec, constraints, outputs
* `tracker/factory_tracker.yaml` — step tracker used for execution
* `invariants/invariants.md` — non-negotiable contracts

### Cursor rules

* `.cursor/rules/00_global.md` — global behavior constraints
* `.cursor/rules/10_invariants.md` — invariant quick-reference (no duplication of definitions)

### Prompt templates

* `prompts/chair_synthesis_template.md`
* `prompts/step_template.md`
* `prompts/review_template.md`
* `prompts/patch_template.md`

### Phase -1 artifacts

* `phase_minus_1/build_candidate.yaml`
* `phase_minus_1/research_snapshot.yaml`
* `schemas/build_candidate.schema.json`
* `schemas/research_snapshot.schema.json`

### Generated (not canonical)

* `phase_minus_1/exception_packet.md`
* `versions/<timestamp>_<run_id>/...`
* `COMMIT_MANIFEST.md`
* execution logs / reports

---

## Quickstart (V0)

### Prereqs

* Python environment
* Postgres URL (local or Railway-style)
* OpenRouter API key
* (Optional) LangSmith env vars for tracing

### Environment variables

* `DATABASE_URL`
* `OPENROUTER_API_KEY`

### Typical run (minimal)

1. Phase -1: validate commitment + research snapshot

```bash
council phase-minus-1-guard --mode commit
```

2. Run planning council (Phase 1)

```bash
council run plan \
  --phase-1-check \
  --project <project_slug> \
  --packet council/packets/plan_packet.md \
  --models <m1>,<m2>,<m3> \
  --chair <m1>
```

3. Approve or edit+approve plan

```bash
council approve <run_id> --approve
# or
council approve <run_id> --edit
```

4. Commit canonical outputs

```bash
council commit <run_id> --repo <path_to_target_repo>
```

5. (Planned) Export a zip pack for Cursor

```bash
# not guaranteed implemented in V0 yet:
council pack export <run_id> --out artifact_pack.zip
```

---

## Phase details

## Phase -1: Build selection + bounded research

**Purpose:** stop scope creep before planning.

**Inputs:**

* `phase_minus_1/build_candidate.yaml`
* `phase_minus_1/research_snapshot.yaml`

**Output:**

* `phase_minus_1/exception_packet.md` (generated)
* HITL decisions:

  * commit the build?
  * research sufficient to plan?

**Rule of thumb:** research snapshot should be “enough to not be delusional,” not “complete.”

---

## Phase 0 (Lite): Context pack

**Purpose:** inject context without bloating.

**Inputs:**

* Phase -1 artifacts + whatever you want to include *bounded* (links, constraints, assumptions, unknowns)

**Output:**

* `phase_0/context_pack_lite.md` (human-authored or lightly assisted)

**Important:** the context pack is *not* a dumping ground. Keep it short; keep it factual.

---

## Phase 1: Planning council

**Purpose:** generate one executable plan with multi-perspective critique.

**Mechanics:**

* 3 drafts (different models)
* 3 critiques
* chair synthesis
* **HITL approval** (approve/edit/reject)

**Output:**

* “plan” artifact stored for the run (often verbatim chair synthesis in V0)

**Guardrails:**

* No adding phases
* No widening scope
* Explicit verification per step

---

## Phase 2: Artifact councils (sequential, one approval per artifact)

**Purpose:** turn an approved plan into a **canonical artifact pack** you can execute with.

**Artifacts generated in order (recommended):**

1. **Spec update** (`spec/spec.yaml`)
2. **Tracker steps** (`tracker/factory_tracker.yaml`)
3. **Step prompts** (`prompts/step_template.md` and per-step variants if needed)
4. **Review + patch prompts** (`prompts/review_template.md`, `prompts/patch_template.md`)
5. **Cursor rules** (`.cursor/rules/00_global.md`, `.cursor/rules/10_invariants.md`)
6. **Invariants** (`invariants/invariants.md`)

**Approval model:**

* Each artifact is produced by a council + chair synthesis
* You **approve/edit/reject** each artifact
* Approved artifacts become canonical **until explicitly regenerated**

This keeps complexity from ballooning and prevents “artifact drift” across chats/runs.

---

## Dogfooding (the intended meaning)

Dogfooding means:

> Use this factory to generate artifact packs for **other projects** you want to build in Cursor.

It does **not** mean “the system should recursively build itself” as the primary workflow.

---

## Deep research (planned, not default)

We keep deep research as a **swap-in module**, not a mandatory pipeline step.

Planned knobs:

* **Depth (1–5)**: quick sanity check → deeper synthesis
* **Source tier strictness (1–5)**: open web → official-only
* **Accuracy requirement (1–5)**: casual → decision-grade

In V0:

* Research stays bounded in `research_snapshot.yaml`
* “Claim-level” findings are allowed, but **soft context** should stay in context pack (Phase 0), not in the findings schema.

A future doc will live at:

* `docs/deep_research.md` — research modes, tiering, hallucination minimization strategy

---

## Why CLI (for V0)

CLI is the fastest path to:

* deterministic runs
* versioned outputs
* tight integration with git + Cursor
* low surface area for bugs

Visibility comes from:

* stored artifacts per run (`council show`)
* optional LangSmith traces (external UI)

V0 intentionally punts a custom UI.

---

## Repo layout (typical)

* `src/agentic_mvp_factory/` — runtime code
* `council/packets/` — input packets (what the council is asked to do)
* `phase_minus_1/` — build selection + research snapshot artifacts
* `spec/` `tracker/` `invariants/` `.cursor/rules/` `prompts/` — canonical outputs
* `versions/` — snapshots of committed outputs

---

## Roadmap (brief, non-confusing)

* **V0**: stable plan council + stable artifact pack generation + commit/snapshot
* **V1** (optional): configurable research module + zip export + improved CLI UX
* **V2+**: verification harness, sentinel checks, richer provenance policies (only if needed)

If you’re reading this repo to use it: focus on V0 flow above.