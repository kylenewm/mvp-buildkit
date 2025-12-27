# Council Command Reference

Complete command sequence for running the full Agentic MVP Factory workflow.

---

## Phase -1: Research & Build Commitment

### 1. Research (Optional - if using automated research)
```bash
council research --project <project-slug> --config <config-path>
```

### 2. Generate Context Pack
```bash
scripts/generate_context_pack.py --phase-dir phase_minus_1 --out phase_0/context_pack_lite.md
```

### 3. Validate Phase -1 Artifacts
```bash
council phase-1-guard --mode commit
```

**Required files:**
- `phase_minus_1/build_candidate.yaml`
- `phase_minus_1/research_snapshot.yaml`

---

## Phase 1: Planning Council

### 1. Run Planning Council
```bash
council run plan \
  --project <project-slug> \
  --packet <path-to-plan-packet.md> \
  [--models <model1,model2>] \
  [--chair <chair-model>] \
  [--phase-1-check] \
  [--context phase_0/context_pack_lite.md]
```

**Defaults (if not specified):**
- `--models`: Uses `DEFAULT_MODELS` from `constants.py`
- `--chair`: Uses `DEFAULT_CHAIR_MODEL` from `constants.py`

**Example:**
```bash
council run plan \
  --project ai-pm-finder \
  --packet tmp/ai_search/council/packets/plan_packet.md \
  --phase-1-check \
  --context tmp/ai_search/phase_0/context_pack_lite.md
```

### 2. Review Plan
```bash
council show [<run-id>]  # Shows latest run if ID omitted
council show <run-id> --section synthesis  # View the plan content
```

### 3. Approve Plan
```bash
council approve [<run-id>] --approve  # Approves latest pending if ID omitted
# OR edit first:
council approve [<run-id>] --edit  # Opens in $EDITOR, then approves
```

### 4. Commit Plan (Optional - saves to repo)
```bash
council commit [<run-id>] --repo <target-repo-path>
```

---

## Phase 2: Artifact Generation (Sequential)

**⚠️ IMPORTANT:** Run these in order. Each depends on the previous ones being **approved**.

### Dependency Graph
```
plan (approved)
  ├─> spec
  │     ├─> invariants
  │     │     ├─> tracker ──┐
  │     │     └─> cursor-rules
  │     └─────────────────────┘
  └─> prompts (needs: spec + invariants + tracker)
```

---

### 1. Spec Council

**Depends on:** Approved plan

```bash
council run spec \
  --project <project-slug> \
  [--from-plan <plan-run-id>] \
  [--models <model1,model2>] \
  [--chair <chair-model>]
```

**Defaults:**
- `--from-plan`: Uses latest approved plan for the project
- `--models`: Uses `DEFAULT_MODELS`
- `--chair`: Uses `DEFAULT_CHAIR_MODEL`

**Example:**
```bash
council run spec --project ai-pm-finder
```

**Then approve & commit:**
```bash
council approve --approve
council commit --repo tmp/ai_search
```

---

### 2. Invariants Council

**Depends on:** Approved spec

```bash
council run invariants \
  --project <project-slug> \
  [--from-plan <plan-run-id>] \
  [--models <model1,model2>] \
  [--chair <chair-model>]
```

**Defaults:** Same as spec (auto-finds latest approved spec for the plan)

**Example:**
```bash
council run invariants --project ai-pm-finder
```

**Then approve & commit:**
```bash
council approve --approve
council commit --repo tmp/ai_search
```

---

### 3. Tracker Council

**Depends on:** Approved spec + Approved invariants

```bash
council run tracker \
  --project <project-slug> \
  [--from-plan <plan-run-id>] \
  [--models <model1,model2>] \
  [--chair <chair-model>]
```

**Example:**
```bash
council run tracker --project ai-pm-finder
```

**Then approve & commit:**
```bash
council approve --approve
council commit --repo tmp/ai_search
```

---

### 4. Prompts Council

**Depends on:** Approved spec + Approved invariants + Approved tracker

```bash
council run prompts \
  --project <project-slug> \
  [--from-plan <plan-run-id>] \
  [--models <model1,model2>] \
  [--chair <chair-model>]
```

**Example:**
```bash
council run prompts --project ai-pm-finder
```

**Then approve & commit:**
```bash
council approve --approve
council commit --repo tmp/ai_search
```

---

### 5. Cursor Rules Council

**Depends on:** Approved spec + Approved invariants

```bash
council run cursor-rules \
  --project <project-slug> \
  [--from-plan <plan-run-id>] \
  [--models <model1,model2>] \
  [--chair <chair-model>]
```

**Example:**
```bash
council run cursor-rules --project ai-pm-finder
```

**Then approve & commit:**
```bash
council approve --approve
council commit --repo tmp/ai_search
```

---

## Quick Reference: Complete Workflow

### Full Sequence (After Phase -1 is ready)

```bash
# 1. Plan
council run plan --project ai-pm-finder --packet <packet> --phase-1-check
council approve --approve
council commit --repo tmp/ai_search

# 2. Spec
council run spec --project ai-pm-finder
council approve --approve
council commit --repo tmp/ai_search

# 3. Invariants
council run invariants --project ai-pm-finder
council approve --approve
council commit --repo tmp/ai_search

# 4. Tracker
council run tracker --project ai-pm-finder
council approve --approve
council commit --repo tmp/ai_search

# 5. Prompts
council run prompts --project ai-pm-finder
council approve --approve
council commit --repo tmp/ai_search

# 6. Cursor Rules
council run cursor-rules --project ai-pm-finder
council approve --approve
council commit --repo tmp/ai_search
```

---

## Utility Commands

### List Runs
```bash
council status [--project <project-slug>] [--status <status>] [--limit <n>]
```

**Examples:**
```bash
council status --project ai-pm-finder --limit 10
council status --status waiting_for_approval
```

### Show Run Details
```bash
council show [<run-id>] [--section <section>] [--full] [--open]
```

**Sections:** `summary`, `all`, `packet`, `drafts`, `critiques`, `synthesis`, `decision`, `plan`, `errors`, `status`, `commit`

**Examples:**
```bash
council show  # Shows latest run summary
council show abc-123 --section synthesis --full
council show --section all --open  # Writes to temp file
```

### Approve/Edit/Reject
```bash
council approve [<run-id>] --approve   # Approve as-is
council approve [<run-id>] --edit       # Edit synthesis, then approve
council approve [<run-id>] --reject    # Reject and create new run with feedback
```

**Note:** If `<run-id>` is omitted, uses latest run with `waiting_for_approval` status.

### Commit to Repository
```bash
council commit [<run-id>] --repo <target-repo-path>
```

**Note:** If `<run-id>` is omitted, uses latest approved run.

**Example:**
```bash
council commit --repo tmp/ai_search
```

---

## Notes

- **All Phase 2 commands** auto-detect the latest approved plan if `--from-plan` is omitted
- **All commands** use default models from `constants.py` if `--models`/`--chair` are omitted
- **Approval is required** before proceeding to the next artifact
- **Commits are optional** but recommended to save artifacts to your repo
- **Reasoning effort** is automatically optimized:
  - Drafts/Critiques: `low` (faster)
  - Chair: `medium` (better quality)

---

## Troubleshooting

### "No approved plan run found"
→ Make sure you've approved the plan: `council approve --approve`

### "No approved spec run found"
→ Run and approve spec first: `council run spec ...` then `council approve --approve`

### "can't adapt type 'UUID'"
→ This was a bug that's been fixed. Make sure you have the latest code.

### Check what's waiting for approval
```bash
council status --status waiting_for_approval
```

### See what artifacts exist for a run
```bash
council show <run-id> --section summary
```

