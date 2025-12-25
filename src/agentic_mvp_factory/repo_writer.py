"""Repo writer module for committing outputs to target repo (S08).

S02: Registry-driven allowlist - reads canonical/forbidden paths from
docs/ARTIFACT_REGISTRY.md instead of hardcoding.
"""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID


# --- Registry Parser (S02) ---

REGISTRY_PATH = "docs/ARTIFACT_REGISTRY.md"

# Fallback constants (used if registry is missing/unparsable)
_FALLBACK_CANONICAL = [
    "spec/spec.yaml",
    "tracker/factory_tracker.yaml",
    "invariants/invariants.md",
    ".cursor/rules/00_global.md",
    ".cursor/rules/10_invariants.md",
    "prompts/step_template.md",
    "prompts/patch_template.md",
    "prompts/review_template.md",
    "prompts/chair_synthesis_template.md",
    "docs/ARTIFACT_REGISTRY.md",
]

_FALLBACK_GENERATED = ["versions/**"]

_FALLBACK_FORBIDDEN = [
    "prompts/hotfix_sync.md",
    "tracker/tracker.yaml",
    "docs/build_guide.md",
    "COMMIT_MANIFEST.md",
]


@dataclass
class ArtifactRegistry:
    """Parsed artifact registry with canonical, generated, and forbidden paths."""
    canonical: List[str] = field(default_factory=list)
    generated: List[str] = field(default_factory=list)  # glob patterns
    forbidden: List[str] = field(default_factory=list)
    source: str = "fallback"  # "file" or "fallback"
    
    def is_allowed(self, path: str) -> bool:
        """Check if path is allowed (canonical or matches generated glob)."""
        if path in self.canonical:
            return True
        for pattern in self.generated:
            if fnmatch.fnmatch(path, pattern):
                return True
        return False
    
    def is_forbidden(self, path: str) -> bool:
        """Check if path is forbidden."""
        return path in self.forbidden


def parse_artifact_registry(registry_path: Path) -> Tuple[ArtifactRegistry, Optional[str]]:
    """Parse docs/ARTIFACT_REGISTRY.md to extract canonical/generated/forbidden paths.
    
    Args:
        registry_path: Path to the registry file
        
    Returns:
        (ArtifactRegistry, error_message or None)
    """
    if not registry_path.exists():
        return ArtifactRegistry(
            canonical=_FALLBACK_CANONICAL.copy(),
            generated=_FALLBACK_GENERATED.copy(),
            forbidden=_FALLBACK_FORBIDDEN.copy(),
            source="fallback",
        ), f"Registry file not found: {registry_path}"
    
    try:
        content = registry_path.read_text()
    except Exception as e:
        return ArtifactRegistry(
            canonical=_FALLBACK_CANONICAL.copy(),
            generated=_FALLBACK_GENERATED.copy(),
            forbidden=_FALLBACK_FORBIDDEN.copy(),
            source="fallback",
        ), f"Failed to read registry: {e}"
    
    # Parse sections
    canonical: List[str] = []
    generated: List[str] = []
    forbidden: List[str] = []
    
    current_section = None
    
    for line in content.splitlines():
        line = line.strip()
        
        # Detect section headers
        if line == "## Canonical":
            current_section = "canonical"
            continue
        elif line == "## Generated":
            current_section = "generated"
            continue
        elif line == "## Forbidden":
            current_section = "forbidden"
            continue
        elif line.startswith("## ") or line.startswith("---"):
            current_section = None
            continue
        
        # Parse bullet items
        if current_section and line.startswith("- "):
            item = line[2:].strip()
            if item:
                if current_section == "canonical":
                    canonical.append(item)
                elif current_section == "generated":
                    generated.append(item)
                elif current_section == "forbidden":
                    forbidden.append(item)
    
    # Validate we got something
    if not canonical:
        return ArtifactRegistry(
            canonical=_FALLBACK_CANONICAL.copy(),
            generated=_FALLBACK_GENERATED.copy(),
            forbidden=_FALLBACK_FORBIDDEN.copy(),
            source="fallback",
        ), "No canonical paths found in registry"
    
    return ArtifactRegistry(
        canonical=canonical,
        generated=generated,
        forbidden=forbidden,
        source="file",
    ), None


# Legacy constants for backward compatibility (used by _validate_paths_allowed, etc.)
# These will be populated from registry at runtime
ALLOWED_PATHS = _FALLBACK_CANONICAL.copy()
DISALLOWED_PATHS = _FALLBACK_FORBIDDEN.copy()

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


def _is_git_repo(repo_path: Path) -> tuple[bool, str]:
    """Check if path is a git repository using git rev-parse.
    
    Returns:
        (is_git_repo, error_message)
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            return True, ""
        return False, result.stderr.strip() or "Not a git repository"
    except subprocess.TimeoutExpired:
        return False, "git rev-parse timed out"
    except FileNotFoundError:
        return False, "git command not found"
    except Exception as e:
        return False, f"git check failed: {e}"


def _has_uncommitted_changes(repo_path: Path) -> tuple[bool, str]:
    """Check if repo has uncommitted changes.
    
    Returns:
        (has_changes, status_output)
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status_output = result.stdout.strip()
        return bool(status_output), status_output
    except subprocess.TimeoutExpired:
        return True, "git status timed out"
    except Exception as e:
        return True, f"git status failed: {e}"


def _check_existing_files(repo_path: Path, paths: List[str]) -> List[str]:
    """Check which canonical paths already exist in the repo.
    
    Returns:
        List of paths that already exist
    """
    existing = []
    for path in paths:
        full_path = repo_path / path
        if full_path.exists():
            existing.append(path)
    return existing


def _validate_paths_allowed(paths: List[str]) -> List[str]:
    """Validate that all paths are in the allowlist.
    
    Returns:
        List of paths that are NOT allowed
    """
    not_allowed = []
    for path in paths:
        # Check if path is in allowlist or under versions/
        if path not in ALLOWED_PATHS and not path.startswith("versions/"):
            not_allowed.append(path)
    return not_allowed


def _validate_paths_not_disallowed(paths: List[str]) -> List[str]:
    """Validate that no paths match disallowed patterns.
    
    Returns:
        List of paths that are disallowed
    """
    disallowed = []
    for path in paths:
        if path in DISALLOWED_PATHS:
            disallowed.append(path)
        elif any(d in path for d in DISALLOWED_PATHS):
            disallowed.append(path)
    return disallowed


def _generate_stub_content(path: str, synthesis: str, decision_packet: str, run_id: str) -> str:
    """Generate content for a stable path based on council outputs."""
    
    # Map paths to content generators
    if path == "docs/ARTIFACT_REGISTRY.md":
        return f"""# Artifact Registry

> Auto-generated from council run: {run_id}

## Canonical Artifacts

These files are the source of truth for this project.

### Specification & Planning
- `spec/spec.yaml`
- `tracker/factory_tracker.yaml`
- `invariants/invariants.md`

### Cursor Rules
- `.cursor/rules/00_global.md`
- `.cursor/rules/10_invariants.md`

### Prompt Templates
- `prompts/chair_synthesis_template.md`
- `prompts/step_template.md`
- `prompts/review_template.md`
- `prompts/patch_template.md`

## Deprecated (do not reference)
- `tracker/tracker.yaml`
- `docs/build_guide.md`
- `prompts/hotfix_sync.md`
"""
    
    elif path == "spec/spec.yaml":
        return f"""# Project Specification
# Auto-generated from council run: {run_id}

schema_version: "0.1"
generated_at: "{datetime.now().isoformat()}"
run_id: "{run_id}"

# Decision Packet Summary
# See docs/ARTIFACT_REGISTRY.md for canonical artifacts

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
    notes: "See spec/spec.yaml for details"
"""
    
    elif path == "invariants/invariants.md":
        return f"""# Project Invariants

> Auto-generated from council run: {run_id}

## Core Invariants

1. **No Secrets in Repo** - Never commit API keys or credentials
2. **Single Source of Truth** - Spec and tracker are authoritative
3. **Minimal Changes** - Keep implementations boring and simple

---

*See invariants/invariants.md for full details.*
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

- Spec: spec/spec.yaml
- Tracker: tracker/factory_tracker.yaml
- Artifact Registry: docs/ARTIFACT_REGISTRY.md
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

*Content placeholder - see spec/spec.yaml for details.*
"""


def commit_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit council outputs to target repo (additive-only mode).
    
    Args:
        run_id: The approved run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit, paths are invalid, or files exist
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
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
    
    # === S02: Load Registry (single source of truth) ===
    
    # Try to load from the source repo's registry first (where council is run from)
    source_registry_path = Path(REGISTRY_PATH)
    registry, registry_error = parse_artifact_registry(source_registry_path)
    
    # Debug: show registry info
    print(f"[S02] Registry loaded from: {registry.source}")
    print(f"[S02] Canonical paths: {len(registry.canonical)}")
    print(f"[S02] Generated patterns: {registry.generated}")
    print(f"[S02] Forbidden paths: {registry.forbidden}")
    
    if registry_error and registry.source == "fallback":
        raise RuntimeError(
            f"COMMIT BLOCKED: ARTIFACT_REGISTRY missing or unparsable.\n"
            f"  Path: {source_registry_path.resolve()}\n"
            f"  Error: {registry_error}\n"
            f"  Fix: Ensure docs/ARTIFACT_REGISTRY.md exists with ## Canonical section."
        )
    
    # === FAIL-SAFE CHECKS (S01: Commit Safety Rails) ===
    
    # 1. Verify target is a git repo
    is_git, git_error = _is_git_repo(repo_path)
    if not is_git:
        raise RuntimeError(
            f"COMMIT BLOCKED: Target path is not a git repository.\n"
            f"  Reason: non-git\n"
            f"  Path: {repo_path}\n"
            f"  Detail: {git_error}\n"
            f"  Fix: Initialize with 'git init'"
        )
    
    # 2. Check for uncommitted changes (dirty repo)
    has_changes, status_output = _has_uncommitted_changes(repo_path)
    if has_changes:
        raise RuntimeError(
            f"COMMIT BLOCKED: Target repo has uncommitted changes.\n"
            f"  Reason: dirty repo\n"
            f"  Path: {repo_path}\n"
            f"  Offending files:\n{status_output}\n"
            f"  Fix: Commit or stash changes before running council commit."
        )
    
    # 3. Validate paths to write (using registry)
    paths_to_write = registry.canonical.copy()
    
    # Check for forbidden paths first (takes precedence)
    forbidden_in_write = [p for p in paths_to_write if registry.is_forbidden(p)]
    if forbidden_in_write:
        raise ValueError(
            f"COMMIT BLOCKED: Attempted to write forbidden paths.\n"
            f"  Reason: forbidden path (from registry)\n"
            f"  Offending paths: {forbidden_in_write}\n"
            f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
        )
    
    # Check all paths are allowed (canonical or generated)
    not_allowed = [p for p in paths_to_write if not registry.is_allowed(p)]
    if not_allowed:
        raise ValueError(
            f"COMMIT BLOCKED: Attempted to write non-canonical paths.\n"
            f"  Reason: non-canonical write (not in registry)\n"
            f"  Offending paths: {not_allowed}\n"
            f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
        )
    
    # 4. Additive-only mode: fail if any canonical file already exists
    existing = _check_existing_files(repo_path, paths_to_write)
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: Canonical files already exist (additive-only mode).\n"
            f"  Reason: overwrite\n"
            f"  Offending files: {existing}\n"
            f"  Fix: Remove these files or use a fresh repo to proceed."
        )
    
    # === END FAIL-SAFE CHECKS ===
    
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
        
        # S02: paths_to_write already validated against registry above
        # (forbidden check + allowlist check already done)
        
        # Write stable paths (all from registry canonical list)
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


def commit_spec_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit spec council outputs to target repo (spec-only, additive mode).
    
    This is a specialized commit for Phase 2 spec generation.
    Only writes: spec/spec.yaml + versions/<timestamp>_<run_id>/**
    
    Args:
        run_id: The approved spec run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit or not a spec run
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
    """
    from agentic_mvp_factory.repo import get_run, get_artifacts, write_artifact, update_run_status
    
    # Validate run exists and is ready
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    
    if run.status != "ready_to_commit":
        raise ValueError(f"Run is not ready to commit (status: {run.status})")
    
    if run.task_type != "spec":
        raise ValueError(f"Run is not a spec run (task_type: {run.task_type})")
    
    # Get output artifact (validated spec content) or fallback to synthesis
    spec_artifacts = get_artifacts(run_id, kind="output")
    if not spec_artifacts:
        # Fallback to synthesis_edited or synthesis
        edited_artifacts = get_artifacts(run_id, kind="synthesis_edited")
        if edited_artifacts:
            spec_content = edited_artifacts[0].content
        else:
            synthesis_artifacts = get_artifacts(run_id, kind="synthesis")
            if synthesis_artifacts:
                spec_content = synthesis_artifacts[0].content
            else:
                raise ValueError("No spec candidate or synthesis artifact found")
    else:
        spec_content = spec_artifacts[0].content
    
    # Ensure repo path exists
    repo_path = Path(repo_path).resolve()
    repo_path.mkdir(parents=True, exist_ok=True)
    
    # === S02: Load Registry (single source of truth) ===
    
    source_registry_path = Path(REGISTRY_PATH)
    registry, registry_error = parse_artifact_registry(source_registry_path)
    
    print(f"[S02] Registry loaded from: {registry.source}")
    print(f"[S02] Canonical paths: {len(registry.canonical)}")
    
    if registry_error and registry.source == "fallback":
        raise RuntimeError(
            f"COMMIT BLOCKED: ARTIFACT_REGISTRY missing or unparsable.\n"
            f"  Path: {source_registry_path.resolve()}\n"
            f"  Error: {registry_error}\n"
            f"  Fix: Ensure docs/ARTIFACT_REGISTRY.md exists with ## Canonical section."
        )
    
    # === FAIL-SAFE CHECKS (S01: Commit Safety Rails) ===
    
    # 1. Verify target is a git repo
    is_git, git_error = _is_git_repo(repo_path)
    if not is_git:
        raise RuntimeError(
            f"COMMIT BLOCKED: Target path is not a git repository.\n"
            f"  Reason: non-git\n"
            f"  Path: {repo_path}\n"
            f"  Detail: {git_error}\n"
            f"  Fix: Initialize with 'git init'"
        )
    
    # 2. Check for uncommitted changes (dirty repo)
    has_changes, status_output = _has_uncommitted_changes(repo_path)
    if has_changes:
        raise RuntimeError(
            f"COMMIT BLOCKED: Target repo has uncommitted changes.\n"
            f"  Reason: dirty repo\n"
            f"  Path: {repo_path}\n"
            f"  Offending files:\n{status_output}\n"
            f"  Fix: Commit or stash changes before running council commit."
        )
    
    # 3. Spec-only allowlist (validated against registry)
    spec_allowed_path = "spec/spec.yaml"
    
    # Check forbidden first
    if registry.is_forbidden(spec_allowed_path):
        raise ValueError(
            f"COMMIT BLOCKED: spec/spec.yaml is forbidden.\n"
            f"  Reason: forbidden path (from registry)\n"
            f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
        )
    
    # Check it's in canonical list
    if not registry.is_allowed(spec_allowed_path):
        raise ValueError(
            f"COMMIT BLOCKED: spec/spec.yaml is not in allowlist.\n"
            f"  Reason: non-canonical write (not in registry)\n"
            f"  Offending paths: [{spec_allowed_path}]\n"
            f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
        )
    
    # 4. Additive-only: fail if spec/spec.yaml already exists
    existing = _check_existing_files(repo_path, [spec_allowed_path])
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: spec/spec.yaml already exists (additive-only mode).\n"
            f"  Reason: overwrite\n"
            f"  Offending files: {existing}\n"
            f"  Fix: Remove this file or use a fresh repo to proceed."
        )
    
    # === END FAIL-SAFE CHECKS ===
    
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
        
        # Write spec/spec.yaml
        spec_file = repo_path / spec_allowed_path
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        spec_file.write_text(spec_content)
        
        # Write to snapshot
        snapshot_spec = snapshot_dir / spec_allowed_path
        snapshot_spec.parent.mkdir(parents=True, exist_ok=True)
        snapshot_spec.write_text(spec_content)
        
        # Record in manifest
        manifest.stable_paths_written.append(spec_allowed_path)
        manifest.file_hashes[spec_allowed_path] = _compute_sha256(spec_content)
        
        # Write manifest to snapshot directory only (not repo root)
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

