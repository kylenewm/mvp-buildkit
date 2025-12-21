-- Initial schema for council runner
-- Tables: runs, artifacts, approvals, checkpoints (per spec.yaml storage_v0)

-- Runs table
CREATE TABLE IF NOT EXISTS runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_slug VARCHAR(255) NOT NULL,
    task_type VARCHAR(50) NOT NULL DEFAULT 'plan',
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    parent_run_id UUID REFERENCES runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for project namespace isolation (I4)
CREATE INDEX IF NOT EXISTS idx_runs_project_slug ON runs(project_slug);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

-- Artifacts table
-- Kinds: packet, draft, critique, synthesis, decision_packet, approval, output, commit_log, error
CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    content TEXT NOT NULL,
    usage_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON artifacts(kind);

-- Approvals table
CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    decision VARCHAR(50) NOT NULL,  -- approve, edit_approve, reject
    edited_content TEXT,
    feedback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approvals(run_id);

-- Checkpoints table (for LangGraph state persistence)
CREATE TABLE IF NOT EXISTS checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON checkpoints(run_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints(thread_id);

