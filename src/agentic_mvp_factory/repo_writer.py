"""Repo writer module for committing outputs to target repo (S08)."""

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID


# Canonical stable paths (allowlist for commit outputs)
ALLOWED_PATHS = [
    "spec/spec.yaml",
    "tracker/factory_tracker.yaml",
    "invariants/invariants.md",
    ".cursor/rules/00_global.md",
    ".cursor/rules/10_invariants.md",
    "prompts/step_template.md",
    "prompts/patch_template.md",
    "prompts/review_template.md",
    "prompts/chair_synthesis_template.md",
    "docs/workflow.md",
]

# Explicitly disallowed paths
DISALLOWED_PATHS = [
    "prompts/hotfix_sync.md",
    "tracker/tracker.yaml",
]

LOCK_FILE = ".factory-lock"


@dataclass
class CommitManifest:
    """Manifest of files written during commit."""
    run_id: str
    timestamp: str
    stable_paths_written: List[str] = field(default_factory=list)
    snapshot_path: str = ""
    file_hashes: Dict[str, str] = field(default_factory=dict)
    
    def to_json(self) -> str:
        return json.dumps({
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "stable_paths_written": self.stable_paths_written,
            "snapshot_path": self.snapshot_path,
            "file_hashes": self.file_hashes,
        }, indent=2)
    
    def to_markdown(self) -> str:
        lines = [
            "# Commit Manifest",
            "",
            f"**Run ID:** {self.run_id}",
            f"**Timestamp:** {self.timestamp}",
            f"**Snapshot Path:** {self.snapshot_path}",
            "",
            "## Files Written",
            "",
        ]
        for path in self.stable_paths_written:
            hash_val = self.file_hashes.get(path, "n/a")
            lines.append(f"- `{path}` (sha256: {hash_val[:16]}...)")
        return "\n".join(lines)


def _compute_sha256(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _acquire_lock(repo_path: Path) -> bool:
    """Acquire commit lock. Returns True if lock acquired, False if already locked."""
    lock_file = repo_path / LOCK_FILE
    if lock_file.exists():
        return False
    lock_file.write_text(f"locked at {datetime.now().isoformat()}")
    return True


def _release_lock(repo_path: Path) -> None:
    """Release commit lock."""
    lock_file = repo_path / LOCK_FILE
    if lock_file.exists():
        lock_file.unlink()


def _generate_stub_content(path: str, synthesis: str, decision_packet: str, run_id: str) -> str:
    """Generate content for a stable path based on council outputs."""
    
    # Map paths to content generators
    if path == "docs/workflow.md":
        return f"""# Workflow Guide

> Auto-generated from council run: {run_id}

{synthesis}
"""
    
    elif path == "spec/spec.yaml":
        return f"""# Project Specification
# Auto-generated from council run: {run_id}

schema_version: "0.1"
generated_at: "{datetime.now().isoformat()}"
run_id: "{run_id}"

# Decision Packet Summary
# See docs/workflow.md for full synthesis

{decision_packet}
"""
    
    elif path == "tracker/factory_tracker.yaml":
        return f"""# Project Tracker
# Auto-generated from council run: {run_id}

schema_version: "0.1"
generated_at: "{datetime.now().isoformat()}"
run_id: "{run_id}"

steps:
  - id: S01
    title: "Implementation step 1"
    status: todo
    notes: "See docs/workflow.md for details"
"""
    
    elif path == "invariants/invariants.md":
        return f"""# Project Invariants

> Auto-generated from council run: {run_id}

## Core Invariants

1. **No Secrets in Repo** - Never commit API keys or credentials
2. **Single Source of Truth** - Spec and tracker are authoritative
3. **Minimal Changes** - Keep implementations boring and simple

---

*See docs/workflow.md for full implementation guidance.*
"""
    
    elif path == ".cursor/rules/00_global.md":
        return f"""# Global Cursor Rules

> Auto-generated from council run: {run_id}

## Guidelines

1. Follow the spec/spec.yaml for project requirements
2. Use tracker/factory_tracker.yaml to track progress
3. Check invariants/invariants.md before making changes
4. Keep implementations minimal and boring

## References

- Workflow Guide: docs/workflow.md
- Tracker: tracker/factory_tracker.yaml
"""
    
    elif path == ".cursor/rules/10_invariants.md":
        return f"""# Invariant Enforcement Rules

> Auto-generated from council run: {run_id}

## Before Any Change

1. Read invariants/invariants.md
2. Verify change doesn't violate any invariant
3. If unsure, ask for clarification

## After Any Change

1. Run tests
2. Verify invariants still hold
"""
    
    elif path == "prompts/step_template.md":
        return f"""# Step Implementation Template

> Auto-generated from council run: {run_id}

## Step: [STEP_ID]

### Goal
[What this step accomplishes]

### Deliverables
- [ ] Deliverable 1
- [ ] Deliverable 2

### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

### Implementation Notes
[Any special considerations]
"""
    
    elif path == "prompts/patch_template.md":
        return f"""# Patch Template

> Auto-generated from council run: {run_id}

## Patch: [PATCH_ID]

### Issue
[What problem this fixes]

### Changes
[What files are modified]

### Verification
[How to verify the fix]
"""
    
    elif path == "prompts/review_template.md":
        return f"""# Review Template

> Auto-generated from council run: {run_id}

## Review Checklist

### Code Quality
- [ ] Follows project conventions
- [ ] No obvious bugs
- [ ] Error handling present

### Invariants
- [ ] No secrets committed
- [ ] Spec alignment verified
- [ ] Tests pass

### Documentation
- [ ] Changes documented
- [ ] README updated if needed
"""
    
    elif path == "prompts/chair_synthesis_template.md":
        return f"""# Chair Synthesis Template

> Auto-generated from council run: {run_id}

## Council Synthesis

### Unified Direction
[The agreed-upon approach]

### Key Decisions
1. [Decision 1]
2. [Decision 2]

### Tradeoffs Acknowledged
[What we're giving up]

### Next Actions
1. [Action 1]
2. [Action 2]
"""
    
    else:
        return f"""# {Path(path).stem}

> Auto-generated from council run: {run_id}

*Content placeholder - see docs/workflow.md for details.*
"""


def commit_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit council outputs to target repo.
    
    Args:
        run_id: The approved run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit
        RuntimeError: If lock cannot be acquired
    """
    from agentic_mvp_factory.repo import get_run, get_artifacts, write_artifact, update_run_status
    
    # Validate run exists and is ready
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    
    if run.status != "ready_to_commit":
        raise ValueError(f"Run is not ready to commit (status: {run.status})")
    
    # Get synthesis and decision_packet
    synthesis_artifacts = get_artifacts(run_id, kind="synthesis")
    decision_artifacts = get_artifacts(run_id, kind="decision_packet")
    
    # Also check for edited synthesis
    edited_artifacts = get_artifacts(run_id, kind="synthesis_edited")
    if edited_artifacts:
        synthesis_content = edited_artifacts[0].content
    elif synthesis_artifacts:
        synthesis_content = synthesis_artifacts[0].content
    else:
        raise ValueError("No synthesis artifact found")
    
    decision_content = decision_artifacts[0].content if decision_artifacts else ""
    
    # Ensure repo path exists
    repo_path = Path(repo_path).resolve()
    repo_path.mkdir(parents=True, exist_ok=True)
    
    # Acquire lock
    if not _acquire_lock(repo_path):
        raise RuntimeError(f"Cannot acquire lock - another commit may be in progress. Check {repo_path / LOCK_FILE}")
    
    try:
        # Update status to committing
        update_run_status(run_id, "committing")
        
        # Prepare manifest
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest = CommitManifest(
            run_id=str(run_id),
            timestamp=timestamp,
        )
        
        # Create snapshot directory
        snapshot_dir = repo_path / "versions" / f"{timestamp}_{run_id}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest.snapshot_path = str(snapshot_dir.relative_to(repo_path))
        
        # Validate: only write from allowlist (enforced by using ALLOWED_PATHS directly)
        # This guard ensures no deprecated paths slip through
        paths_to_write = ALLOWED_PATHS.copy()
        for path in paths_to_write:
            if path in DISALLOWED_PATHS:
                raise ValueError(
                    f"Commit blocked: path '{path}' is in disallowed list. "
                    f"Allowed paths: {ALLOWED_PATHS}"
                )
            # Check for deprecated patterns in path
            if any(disallowed in path for disallowed in ["hotfix_sync.md", "tracker/tracker.yaml"]):
                raise ValueError(
                    f"Commit blocked: path '{path}' contains deprecated pattern. "
                    f"Allowed paths: {ALLOWED_PATHS}"
                )
        
        # Write stable paths (all from allowlist)
        for path in paths_to_write:
            content = _generate_stub_content(
                path=path,
                synthesis=synthesis_content,
                decision_packet=decision_content,
                run_id=str(run_id),
            )
            
            # Write to stable path
            stable_file = repo_path / path
            stable_file.parent.mkdir(parents=True, exist_ok=True)
            stable_file.write_text(content)
            
            # Write to snapshot
            snapshot_file = snapshot_dir / path
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            snapshot_file.write_text(content)
            
            # Record in manifest
            manifest.stable_paths_written.append(path)
            manifest.file_hashes[path] = _compute_sha256(content)
        
        # Write manifest to snapshot directory (required)
        manifest_path = snapshot_dir / "COMMIT_MANIFEST.md"
        manifest_path.write_text(manifest.to_markdown())
        
        # Also write JSON manifest to snapshot
        manifest_json_path = snapshot_dir / "manifest.json"
        manifest_json_path.write_text(manifest.to_json())
        
        # Store manifest as artifact
        write_artifact(
            run_id=run_id,
            kind="commit_log",
            content=manifest.to_json(),
            model=None,
        )
        
        # Update status to completed
        update_run_status(run_id, "completed")
        
        return manifest
        
    finally:
        # Always release lock
        _release_lock(repo_path)

