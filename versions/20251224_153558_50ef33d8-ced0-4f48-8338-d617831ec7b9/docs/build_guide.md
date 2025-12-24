# Build Guide

> Auto-generated from council run: 50ef33d8-ced0-4f48-8338-d617831ec7b9

SYNTHESIS: Final unified V0 implementation plan

High-level decision (why this direction)
- We adopt the council’s pragmatic V0 that performs an actual local git commit into the target repo on approval (not “stage-only”). Reason: the Original Packet requires "on approval, commits a minimal artifact pack stub into a target repo." We keep Draft 2’s safer UX and Draft 3’s concrete commit mechanics, while importing Draft 1/2 robustness suggestions: transactional commit flow, row-level locking/claiming, JSON-serializable minimal state (not LangGraph internals), node-level idempotency, and clear resume semantics. This choice increases V0 complexity slightly but meets spec and gives a clear, automatable outcome for downstream CI.

1 — Architecture Overview
Components and responsibilities
- CLI (council): parse commands, run orchestration, show status, launch editor, claim/resume runs.
- Runner Orchestrator (LangGraph embedded): defines linear graph nodes (drafts → critiques → chair → approval → commit), executes node handlers, updates minimal JSON state, persists checkpoints to Postgres between nodes.
- Model Gateway: ModelClient interface + OpenRouterClient implementation. Handles timeouts, retries, metadata logging.
- Persistence Layer (Postgres): projects, runs, workflow_state, model_calls, artifacts, commits. Single source of truth for run lifecycle and metadata.
- Workspace (filesystem): workspace_root/<project_slug>/runs/<run_id>/ node artifact files; temp dirs for atomic commit staging.
- Repo Output Writer: takes final state & artifacts, writes versions/<timestamp>_<run_id>/ in target repo, runs git add + git commit, records commit SHA.
- Short-lived CLI editor flow: open $EDITOR for edit+approve, write back to workspace.

Where LangGraph sits
- Embedded in the CLI process as orchestration engine. LangGraph executes node handlers that call ModelClient and update a minimal JSON-serializable state object. Internal LangGraph runtime is not persisted; only node outputs and required metadata are persisted.

What lives in Postgres vs filesystem
- Postgres: projects table (spec + repo path), runs (lifecycle/status), workflow_state snapshots (minimal JSON state versioned), model_calls (prompt/response metadata/tokens), artifacts table (relative paths + checksums + metadata), commits table (manifest + commit SHA + timestamps), claim/lock and approvals metadata.
- Filesystem: workspace artifacts (drafts, critiques, synthesis text), temp commit staging directories, target repo working tree where versions/ folders are created and committed.
- Policy: artifacts stored on FS under project workspace; DB stores relative path and checksum (sha256) for integrity and reproducibility.

2 — Data Model (Postgres tables & key columns)
- projects
  - project_slug TEXT PRIMARY KEY
  - spec JSONB NOT NULL (raw parsed spec.yaml; minimal validation)
  - repo_path TEXT NOT NULL (local path to target repo)
  - created_at timestamptz
- runs
  - run_id UUID PRIMARY KEY
  - project_slug TEXT REFERENCES projects(project_slug)
  - parent_run_id UUID NULL
  - status TEXT NOT NULL  -- enum: pending | running | waiting_human | claimed | committing | committed | rejected | failed
  - current_node TEXT NULL
  - created_by TEXT NULL (git user or CLI user)
  - created_at timestamptz
  - updated_at timestamptz
  - claim_owner TEXT NULL  -- who claimed for resume/approve
  - version INT NOT NULL DEFAULT 1 -- optimistic locking for updates
- workflow_state
  - state_id UUID PRIMARY KEY
  - run_id UUID REFERENCES runs(run_id)
  - node_name TEXT NOT NULL
  - state_json JSONB NOT NULL -- minimal JSON-serializable state snapshot (see below)
  - created_at timestamptz
  - schema_version INT NOT NULL DEFAULT 1
- model_calls
  - call_id UUID PRIMARY KEY
  - run_id UUID REFERENCES runs(run_id)
  - node_name TEXT
  - model_name TEXT
  - prompt TEXT
  - response TEXT
  - tokens_in INT NULL
  - tokens_out INT NULL
  - latency_ms INT NULL
  - created_at timestamptz
- artifacts
  - artifact_id UUID PRIMARY KEY
  - run_id UUID REFERENCES runs(run_id)
  - node_name TEXT -- e.g., draft:gpt-4, critique:gemini
  - role TEXT -- draft | critique | synthesis | manifest | other
  - rel_path TEXT NOT NULL -- path relative to project repo root or workspace root (always stored relative)
  - sha256 TEXT NOT NULL
  - size_bytes INT
  - metadata JSONB NULL (model_used, edited_by, edited_at)
  - created_at timestamptz
- commits
  - commit_id UUID PRIMARY KEY
  - run_id UUID REFERENCES runs(run_id)
  - commit_sha TEXT NULL
  - manifest JSONB NOT NULL
  - status TEXT NOT NULL  -- committing | committed | commit_failed
  - created_at timestamptz

How artifacts are stored and retrieved
- Files written under WORKSPACE_ROOT/<project_slug>/runs/<run_id>/<node_name>/<filename>
- artifacts.rel_path stores path relative to project repo root on commit, or workspace relative path pre-commit.
- On commit, Repo Writer stages to a temp staging dir inside the target repo, computes checksums, moves into final versions/<timestamp>_<run_id>/ atomically (rename), then runs git add & git commit. After commit, artifacts rows point to final repo-relative paths and their checksums.

How runs are namespaced by project_slug
- runs.project_slug column and filesystem layout enforces separation. Queries filter by project_slug. Workspace is organized per project_slug.

3 — LangGraph Workflow
Minimal JSON-serializable state object fields (V0 minimal)
- run_id (UUID)
- project_slug (string)
- spec (minimal parsed spec keys only: chair, drafters, critique_models, repo_path, commit_message_template)
- models_config (chair + draft list + critique list and per-model params)
- node_outputs: { node_name: { artifacts: [ { rel_path, sha256, metadata } ], summary: string } }
- current_node: string
- approval: { status: "pending" | "approved" | "rejected" | "edited", editor_note: string|null, approved_by: string|null, approved_at: timestamptz|null }
- parent_run_id: UUID|null
- created_at, updated_at (timestamps)

Node list and edges (V0 linear graph with parallel draft nodes)
- Start -> Drafts (parallel per-drafter) -> WaitForDraftsBarrier -> Critiques (parallel) -> SynthesizeChair -> Approval(HITL) -> CommitArtifacts -> End
- Nodes:
  - DraftNode(s): one execution per configured drafter model; writes draft artifact file, persists model_calls and artifact entry.
  - CritiqueNode(s): run critiques against drafts; outputs critique artifacts.
  - SynthesizeChair: chair model synthesizes final content from drafts + critiques; writes chair_synthesis artifact and updates state.
  - ApprovalNode (HITL): persist state and exit; waits for user action (approve | edit+approve | reject).
  - CommitArtifacts: collects artifacts, creates versions/<timestamp>_<run_id>/ in repo, git commit, record commit.
  - RejectedRerun: when rejected, create new run with parent_run_id set, start Drafts.

How HITL interrupt works and how resume works
- When ApprovalNode reached:
  - Runner persists current workflow_state and sets runs.status = waiting_human, runs.current_node = "ApprovalNode", writes artifacts (chair_synthesis etc.) to workspace and artifacts table (sha256), commits a workflow_state row, returns control to CLI and exits with message: run paused for approval <run_id>.
  - CLI prints explicit instructions: "inspect with `council show --run-id` then `council approve --run-id` or `council approve --run-id --edit` or `council reject --run-id`."
- Approval flow (resume):
  - Approve command first acquires a claim: transaction SELECT FOR UPDATE on runs row, ensure status == waiting_human, set claim_owner to current CLI user (from env or git config) and status = claimed.
  - If --edit: CLI opens chair_synthesis file via $EDITOR. On save, CLI recomputes sha256 and updates artifacts table metadata (edited_by, edited_at), updates workflow_state.approval.editor_note and status = edited.
  - Approve then sets workflow_state.approval.status = approved and approved_by+approved_at, persists state, and invokes Runner to continue: Runner loads latest state_json, checks node_outputs and node-level completed flags, and runs remaining nodes (CommitArtifacts). Node handlers are idempotent: they check if node already produced artifacts (exists with checksum) and skip re-execution.
  - Reject: CLI acquires claim, sets runs.status = rejected, records reason in workflow_state.metadata, creates new run row new_run_id with parent_run_id = old run_id, copies spec/models_config into new run, and starts it immediately (or prints run id for user to start). Original run remains recorded.
- Resume semantics:
  - Resume as explicit action invoked by approve/reject; there is no implicit auto-resume when `council run` is invoked without run-id. `council run --resume --run-id` can be supported for operator workflows, but main resume path is approve/edit/reject commands.

Rerun behavior
- REJECT creates a NEW run (always set parent_run_id), with fresh run_id and status pending or running. The new run uses the same spec (snapshot at run creation); if user edited spec file between runs, the new run uses the snapshot of original run unless user explicitly re-initializes.

Idempotency / node-completed markers
- Each node writes a workflow_state snapshot and artifacts rows on completion. Node handlers must check for existing artifacts entries (by node_name + run_id + expected filename + checksum) and skip work if present to avoid duplication on resume.

4 — Model Gateway
ModelClient interface (Python-style pseudocode)
- class ModelClient:
    async def generate(self, model: str, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024) -> dict:
        # returns { "text": str, "tokens_in": int, "tokens_out": int, "latency_ms": int, "model": model }
    async def generate_batch(self, requests: list[dict]) -> list[dict]:
        # parallel calls; each request: { model, messages, params }
    async def close(self): pass

OpenRouter client behavior (V0)
- Uses OPENROUTER_API_KEY and base_url (configurable; default https://api.openrouter.ai/v1)
- Uses httpx.AsyncClient with:
  - timeout = 60s per request (configurable)
  - retries: up to 3 attempts on network errors and HTTP 5xx, and exponential backoff with jitter (0.5s, 1s, 2s) for 429/5xx
  - on 4xx other than 429, fail and bubble error
  - record latency, tokens if available in provider response; store model_calls row
- Non-streaming, blocking response for simplicity (V0).
- Implementation must include a simple health_check() to allow quick preflight.

How chair and non-chair models are configured
- spec/spec.yaml (project-level) defines:
  - chair: { model: "openrouter:gpt-4o", params: { temperature: 0.2 } }
  - drafters: [ { name: "drafterA", model: "openrouter:gpt-4o-mini", params: {...} }, ... ]
  - critique_models: [ { name: "criticA", model: "openrouter:gemini", params: {...} } ]
- CLI `council run` supports --chair and --drafter overrides; models_config is stored in runs.models_config JSONB per-run.

5 — CLI UX (exact commands & outputs)
Assume binary name `council`. All commands return exit code 0 on success.

1) init
- Usage:
  council init <project_slug> --repo-path <path-to-local-repo> [--spec <spec.yaml>]
- Behavior:
  - Validate repo_path exists and is a git repo (git rev-parse OK). Create projects row with parsed spec.yaml (if provided) or generate spec/spec.yaml template in repo_path/spec/spec.yaml.
  - Print:
    "Project '<project_slug>' initialized. Repo: <repo_path>. Edit spec/spec.yaml and run 'council run --project <project_slug>'."

2) run (start a new run)
- Usage:
  council run --project <project_slug> [--chair <model>] [--dry-run]
- Behavior:
  - Creates a new run row (run_id), snapshot spec & models_config into runs.
  - Executes LangGraph nodes sequentially (drafts parallel internally), persisting workflow_state after each node.
  - On hitting ApprovalNode, persist state, update runs.status = waiting_human, print:
    "Run <run_id> paused at approval. Inspect: council show --run-id <run_id>. Approve: council approve --run-id <run_id> [--edit]. Reject: council reject --run-id <run_id>."
  - If --dry-run, run up to ApprovalNode without writing artifacts to repo filesystem (still persists state).
  - Output progress lines during execution (e.g., "Drafts: drafterA -> OK", "Critiques -> OK", "Synthesis (chair) -> OK").

3) status
- Usage:
  council status --project <project_slug> [--run-id <run_id>]
- Behavior:
  - If run_id specified, print full run status JSON summary: run_id, project_slug, status, current_node, created_at, updated_at, artifacts summary (counts), commit info if any.
  - If not specified, list recent runs for project (table style): run_id | status | created_at | current_node | parent_run_id

4) show
- Usage:
  council show --run-id <run_id> [--section drafts|critiques|synthesis|all]
- Behavior:
  - Fetch artifacts for run_id and print content to stdout with headers:
    "=== <node_name> / <filename> ===\n<content>\n"
  - For large artifacts > N bytes show trimmed first/last chunks and indicate path.

5) approve
- Usage:
  council approve --run-id <run_id> [--edit]
- Behavior:
  - Acquire claim: transactional SELECT FOR UPDATE on runs; ensure status == waiting_human. Set claim_owner and status = claimed.
  - If --edit:
    - Copy chair synthesis artifact to temp file and open $EDITOR (respect $VISUAL then $EDITOR).
    - After editor closes, compute new sha256, update workspace file, update artifacts table (set edited_by, edited_at) and workflow_state.approval.editor_note.
    - Persist updated workflow_state.
  - Mark approval: update workflow_state.approval.status = approved, approved_by = current user, approved_at = now.
  - Resume Runner: set runs.status = running and invoke Runner to perform CommitArtifacts node (Runner re-loads state_json and proceeds).
  - CLI prints progress then final commit result: "Approved. Committed run <run_id> -> commit <sha> at versions/<timestamp>_<run_id>/"
  - Exit code 0 on success. On commit failure, runs.status set to failed and CLI prints error.

6) reject
- Usage:
  council reject --run-id <run_id> --reason "<short text>"
- Behavior:
  - Acquire claim as in approve. Set runs.status = rejected and persist rejection reason in workflow_state.
  - Create new run row new_run_id with parent_run_id = run_id, snapshot spec/models_config (from original run), status = pending.
  - Optionally auto-start new run (print instructions): "Rejected. New run created: <new_run_id>. Start with: council run --project <project_slug> --run-id <new_run_id> or council run --project <project_slug> to create a new run."
  - Print "Rejected. New run id: <new_run_id>."

7) commit (manual, rarely needed)
- Usage:
  council commit --run-id <run_id> --message "<commit message template>"
- Behavior:
  - Similar to the commit step invoked by approve. Use for manual re-commit of previously approved run if commit previously failed. Requires runs.status in committing/claimed and a claim.

Notes on outputs and UX details
- All commands log structured logs to stderr, human messages to stdout. For example, `council run` shows progress lines and at approval prints the paused message and returns exit status 0.
- CLI determines current user for claim_owner via env var COUNCIL_USER or git config user.email fallback.

6 — Repo Output Writer (exact files written on commit)
Stable paths (inside target repo_path)
- versions/<timestamp>_<run_id>/manifest.json
- versions/<timestamp>_<run_id>/chair_synthesis.md
- versions/<timestamp>_<run_id>/drafts/<drafter_name>.md (one per draft)
- versions/<timestamp>_<run_id>/critiques/<draft_name>__critique.md
- versions/<timestamp>_<run_id>/decision.txt (contains approval info: approved_by, approved_at, editor_note)
- versions/<timestamp>_<run_id>/_run_metadata.json (includes model_calls, token usage, node outputs raw text)
- top-level index.json updated: { latest: "<timestamp>_<run_id>", versions: [ ... ] }

Snapshot version folder naming
- versions/<YYYYMMDDTHHMMSSZ>_<short-run-id>/
  - Timestamp: UTC ISO8601 compact (e.g., 20251224T153045Z)
  - short-run-id: first 8 characters of run_id for readability
  - Example: versions/20251224T153045Z_550e8400/

Commit manifest structure (manifest.json)
- {
    "version": "v0",
    "run_id": "<UUID>",
    "project_slug": "<slug>",
    "timestamp": "2025-12-24T15:30:45Z",
    "chair_model": { "name": "openrouter:gpt-4o", "params": { ... } },
    "drafters": [ { "name": "drafterA", "model":"...", "file":"drafts/drafterA.md", "sha256":"..." }, ... ],
    "critiques": [ ... ],
    "files": [ { "path":"chair_synthesis.md", "sha256":"...", "size": 1234, "role":"synthesis" }, ... ],
    "approval": { "approved_by":"<user>", "approved_at":"<ts>", "editor_note":"..." },
    "generated_by_run": "<run_id>"
  }

Commit mechanics & atomicity
- Steps (transactional outline):
  1. Create a temp staging dir inside repo_path: repo_path/.council_staging/<run_id>_<random>
  2. Write all files into staging dir; compute sha256 for each; create manifest.json and _run_metadata.json.
  3. Atomic move: rename staging dir -> repo_path/versions/<timestamp>_<run_id> (rename is atomic on same filesystem).
  4. In DB transaction: insert commit row with status = committing and manifest JSON.
  5. Run: git add versions/<timestamp>_<run_id>/ ; git commit -m "<auto> Council commit: <project_slug> <run_id> <timestamp>"
     - Capture commit SHA.
  6. Update commits row with commit_sha and status = committed; set runs.status = committed; set runs.current_node = commit_artifacts.
- Failure handling:
  - If git commit fails, update commit row status = commit_failed and runs.status = failed; keep versions/<timestamp>_<run_id>/ in repo with a marker file commit_failed.txt and leave manual recovery instructions in CLI output.

7 — Milestones and Implementation Order (M0 → M6) with acceptance criteria
Estimate: experienced engineer or pair.

M0 — Foundation & DB schema + CLI skeleton (3–4 days)
- Implement CLI skeleton and config loader.
- Implement Postgres migrations (projects, runs, workflow_state, artifacts, model_calls, commits).
- Acceptance: `council init` creates project row and writes spec template; `council status` shows project. Unit tests for DB migrations pass.

M1 — ModelClient & OpenRouter integration (2–3 days)
- Implement ModelClient interface and OpenRouterClient (httpx), retries/backoff, health_check.
- Acceptance: mock tests return expected strings; model_calls table records entries for sample calls.

M2 — LangGraph workflow in-memory (drafts → critiques → synth) & file outputs (3–4 days)
- Implement node handlers, write draft/critique/synthesis artifacts to workspace, create workflow_state snapshots at node completion, persist artifacts table rows.
- Acceptance: `council run` produces chair_synthesis.md and draft files locally and prints waiting_human state at approval.

M3 — HITL pause + persist + resume/claim primitives (4 days) — HARD PART
- Implement ApprovalNode persist-and-exit behavior, runs.status = waiting_human, workflow_state snapshot persisted.
- Implement claim/lock semantics with SELECT FOR UPDATE and claim_owner.
- Acceptance: run pauses and exits with run_id; `council status` shows waiting_human; attempting to approve without claim fails; claim ensures only one approver proceeds.

M4 — Approve / edit+approve / reject flows (4 days) — HARD PART
- Implement `council approve --edit` with $EDITOR flow; update artifacts metadata; implement `council reject` creating a new run parent linkage.
- Acceptance: `approve` resumes and triggers commit; `edit` opens editor, edits persisted, and resume commits; `reject` creates new run row with parent_run_id set.

M5 — Repo Output Writer & atomic git commit (3 days)
- Implement staging dir, manifest generation, atomic rename, git add + commit, commit SHA capture, DB commits row updates, failure handling.
- Acceptance: approved run ends with a git commit adding versions/<timestamp>_<run_id>/ with manifest.json and files; commits table populated with commit_sha.

M6 — Polish, tests, docs, minimal validation (2–3 days)
- Add minimal spec validation (required keys: project_slug, chair, drafters list), logging, error messages, integration tests (mock model client and local test repo).
- Acceptance: full end-to-end test: init → run → approve → commit → status shows committed run; reject+rerun path works; edit+approve works.

Hard parts explicitly
- Interrupt/resume correctness: serialize minimal state only, ensure nodes idempotent and maintain node-completed markers to avoid double-run artifacts.
- Concurrency: implement claim/lock (SELECT FOR UPDATE) and optimistic locking (runs.version) to prevent simultaneous approves/resumes.
- Atomic commit: staging dir + rename + transactional DB update + git commit with clear rollback semantics.

8 — Risks and Simplifications (what is punted to V1 and upgrade path)
Punted to V1 (intentional)
- Web UI: V0 CLI-only.
- Distributed or queued orchestration: single-process LangGraph in CLI only.
- Role-based access control and multi-user workflow beyond claim_owner metadata.
- Advanced model fallback/circuit-breakers and provider multiplexing; V0 uses OpenRouter primarily.
- Streaming model output (token-level streaming).
- Large artifact storage in object store (S3); V0 uses local FS.
- Complex semantic spec validation (only minimal required fields validated).
- Cost/cap tracking beyond per-call token logging.

Design keeps upgrade path open
- ModelClient abstraction makes adding new gateways trivial.
- State JSON schema with schema_version allows migrations.
- Filesystem layout and manifest format stable and versioned to allow downstream automation.
- DB tables allow adding RBAC/approver identity later.

Assumptions (call out)
- DATABASE_URL, OPENROUTER_API_KEY, WORKSPACE_ROOT env vars provided.
- Target repo is local and writable; git present and usable.
- Single operator concurrency pattern expected (claim prevents races).
- LangGraph internal runtime not serialized; only JSON state snapshot persisted.
- Model outputs are text artifacts (no large binaries).

Explicit tradeoffs
- Commit-in-V0 vs stage-only: we commit in V0 to satisfy the Original Packet; to mitigate risk we implement atomic staging+rename and robust failure handling rather than staging-only. Tradeoff: slightly higher implementation complexity, but clearer end-state for users and CI.
- Persist minimal state (safe, simple) vs full LangGraph serialization (complex). Chosen: minimal state + idempotent nodes — simpler and reliable for V0.

DECISION_PACKET: compact summary with key decisions, next actions, and risks

Key decisions (final, compact)
1. V0 will perform a local git commit into the target repo on approval (not stage-only).
2. LangGraph runs embedded in CLI; only a small, JSON-serializable minimal state is persisted (node outputs + metadata). LangGraph internal runtime is not persisted.
3. HITL: Approval pauses by persisting state and setting runs.status = waiting_human and exiting; resume happens via explicit CLI approve (or reject) command which claims the run and resumes execution.
4. Reject creates a NEW run_id and MUST set parent_run_id for traceability.
5. Concurrency is handled with DB claim semantics (SELECT FOR UPDATE + runs.version optimistic lock + claim_owner field).
6. Commit atomicity: staging dir -> atomic rename -> git add & commit -> update commits row; failures mark run failed and leave artifacts for manual recovery.

Immediate next actions (practical checklist)
1. Spike (1 day): implement minimal LangGraph state round-trip tests — create a very small state JSON, persist & reload, ensure Runner can re-run remaining nodes idempotently. If issues surface, refactor nodes to be idempotent with node-completed checks.
2. Implement DB schema migrations (projects, runs, workflow_state, model_calls, artifacts, commits). Add runs.version int and claim_owner. (M0)
3. Implement ModelClient and OpenRouterClient with retry/backoff (M1).
4. Implement draft/critique/synthesize node handlers, persist artifacts and model_calls, write workspace files, and persist workflow_state snapshots (M2).
5. Implement ApprovalNode pause semantics: persist state and exit; add CLI messaging for approve/edit/reject (M3).
6. Implement claim/approve/edit/reject flows with SELECT FOR UPDATE and resume into commit node; implement atomic commit mechanics and commit SHA capture (M4–M5).
7. End-to-end integration tests for run → pause → approve (with edit) → commit and reject→rerun. (M6)

Top risks and mitigations
1. LangGraph serialization risk (state cannot be round-tripped)
   - Mitigation: Persist only minimal state fields (node outputs, paths, checksums); keep nodes idempotent and re-run from persistent inputs.
2. Race conditions on approval/resume (two humans claim same run)
   - Mitigation: Implement DB claim using SELECT FOR UPDATE and the runs.version optimistic lock; reject second claimer with clear message.
3. Git commit failures leaving partial artifacts
   - Mitigation: Use staging dir + atomic rename; commit row status indicates committing/committed/commit_failed; on commit failure leave marker file and instruct manual recovery.
4. Model-provider unreliability (timeouts/429)
   - Mitigation: Implement 3 retries with exponential backoff + jitter for 429/5xx; log model_calls and surface failures as run failed.
5. Artifact loss if workspace deleted
   - Mitigation: record sha256 in artifacts and persist synthesis text in workflow_state JSON as backup for small artifacts; recommend backups for workspace in ops docs.
6. Secret leakage via artifacts or logs
   - Mitigation: Do not log API keys; sanitize editor flows; warn users not to include secrets in artifacts in README.

Compact acceptance criteria for first delivery (M0–M3)
- DB schema applied and CLI init works.
- ModelClient stub and OpenRouter mocked calls work and model_calls recorded.
- Full run from `council run` executes draft->critique->chair, persists workflow_state after each node, and pauses at approval with runs.status = waiting_human.
- `council show` prints chair synthesis; `council approve --run-id --edit` opens editor, saves edits, and prints "approved" (commit step may be implemented in M5 but approve flow continues).

If you approve this direction I will:
- Produce initial SQL migration files for the Postgres schema above and pseudocode for claim/approve/resume transaction flows.
- Provide a minimal example of the ModelClient/OpenRouter implementation and the Runner node pseudo-implementations (draft, critique, synth) with idempotency checks.
