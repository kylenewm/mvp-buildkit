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

# Resolve registry path relative to repo root (not CWD)
# repo_writer.py is at src/agentic_mvp_factory/repo_writer.py
# parents[2] gets us to repo root
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "docs" / "ARTIFACT_REGISTRY.md"

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
    
    # 3. S05: Spec-only allowlist - only write spec/spec.yaml and docs/ARTIFACT_REGISTRY.md
    spec_paths_to_write = ["spec/spec.yaml"]
    registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
    
    # Check if registry needs to be written (only if missing)
    registry_dest = repo_path / registry_dest_path
    if not registry_dest.exists():
        spec_paths_to_write.append(registry_dest_path)
    
    # Validate all paths against registry allowlist
    for path in spec_paths_to_write:
        # Check forbidden first
        if registry.is_forbidden(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is forbidden.\n"
                f"  Reason: forbidden path (from registry)\n"
                f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
            )
        
        # Check it's in canonical list
        if not registry.is_allowed(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is not in allowlist.\n"
                f"  Reason: non-canonical write (not in registry)\n"
                f"  Offending paths: [{path}]\n"
                f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
            )
    
    # 4. Additive-only: fail if spec/spec.yaml already exists
    existing = _check_existing_files(repo_path, ["spec/spec.yaml"])
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
        spec_path = "spec/spec.yaml"
        spec_file = repo_path / spec_path
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        spec_file.write_text(spec_content)
        
        # Write to snapshot
        snapshot_spec = snapshot_dir / spec_path
        snapshot_spec.parent.mkdir(parents=True, exist_ok=True)
        snapshot_spec.write_text(spec_content)
        
        # Record in manifest
        manifest.stable_paths_written.append(spec_path)
        manifest.file_hashes[spec_path] = _compute_sha256(spec_content)
        
        # S05: Copy docs/ARTIFACT_REGISTRY.md to target repo if missing
        registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
        registry_dest = repo_path / registry_dest_path
        if not registry_dest.exists():
            # Copy from factory's registry
            factory_registry = Path(REGISTRY_PATH)
            if factory_registry.exists():
                registry_content = factory_registry.read_text()
                registry_dest.parent.mkdir(parents=True, exist_ok=True)
                registry_dest.write_text(registry_content)
                
                # Record in manifest
                manifest.stable_paths_written.append(registry_dest_path)
                manifest.file_hashes[registry_dest_path] = _compute_sha256(registry_content)
                
                # Also write to snapshot
                snapshot_registry = snapshot_dir / registry_dest_path
                snapshot_registry.parent.mkdir(parents=True, exist_ok=True)
                snapshot_registry.write_text(registry_content)
        
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


def commit_tracker_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit tracker outputs to target repository (S07).
    
    Writes ONLY:
    - tracker/factory_tracker.yaml (from kind="output" artifact)
    - docs/ARTIFACT_REGISTRY.md (copied from factory if missing)
    - versions/<timestamp>_<run_id>/... (snapshot + manifest)
    
    Args:
        run_id: The approved tracker run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit or not a tracker run
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
    """
    from agentic_mvp_factory.repo import get_run, get_artifacts, write_artifact, update_run_status
    
    # Validate run exists and is ready
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    
    if run.status != "ready_to_commit":
        raise ValueError(f"Run is not ready to commit (status: {run.status})")
    
    if run.task_type != "tracker":
        raise ValueError(f"Run is not a tracker run (task_type: {run.task_type})")
    
    # Get output artifact (validated tracker content) or fallback to synthesis
    tracker_artifacts = get_artifacts(run_id, kind="output")
    if not tracker_artifacts:
        # Fallback to synthesis_edited or synthesis
        edited_artifacts = get_artifacts(run_id, kind="synthesis_edited")
        if edited_artifacts:
            tracker_content = edited_artifacts[0].content
        else:
            synthesis_artifacts = get_artifacts(run_id, kind="synthesis")
            if synthesis_artifacts:
                tracker_content = synthesis_artifacts[0].content
            else:
                raise ValueError("No tracker candidate or synthesis artifact found")
    else:
        tracker_content = tracker_artifacts[0].content
    
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
    
    # 3. S07: Tracker-only allowlist - only write tracker/factory_tracker.yaml and docs/ARTIFACT_REGISTRY.md
    tracker_path = "tracker/factory_tracker.yaml"
    registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
    paths_to_write = [tracker_path]
    
    # Check if registry needs to be written (only if missing)
    registry_dest = repo_path / registry_dest_path
    if not registry_dest.exists():
        paths_to_write.append(registry_dest_path)
    
    # Validate all paths against registry allowlist
    for path in paths_to_write:
        # Check forbidden first
        if registry.is_forbidden(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is forbidden.\n"
                f"  Reason: forbidden path (from registry)\n"
                f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
            )
        
        # Check it's in canonical list
        if not registry.is_allowed(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is not in allowlist.\n"
                f"  Reason: non-canonical write (not in registry)\n"
                f"  Offending paths: [{path}]\n"
                f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
            )
    
    # 4. Additive-only: fail if tracker/factory_tracker.yaml already exists
    existing = _check_existing_files(repo_path, [tracker_path])
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: {tracker_path} already exists (additive-only mode).\n"
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
        
        # Write tracker/factory_tracker.yaml
        tracker_file = repo_path / tracker_path
        tracker_file.parent.mkdir(parents=True, exist_ok=True)
        tracker_file.write_text(tracker_content)
        
        # Write to snapshot
        snapshot_tracker = snapshot_dir / tracker_path
        snapshot_tracker.parent.mkdir(parents=True, exist_ok=True)
        snapshot_tracker.write_text(tracker_content)
        
        # Record in manifest
        manifest.stable_paths_written.append(tracker_path)
        manifest.file_hashes[tracker_path] = _compute_sha256(tracker_content)
        
        # S07: Copy docs/ARTIFACT_REGISTRY.md to target repo if missing
        if not registry_dest.exists():
            # Copy from factory's registry
            factory_registry = Path(REGISTRY_PATH)
            if factory_registry.exists():
                registry_content = factory_registry.read_text()
                registry_dest.parent.mkdir(parents=True, exist_ok=True)
                registry_dest.write_text(registry_content)
                
                # Record in manifest
                manifest.stable_paths_written.append(registry_dest_path)
                manifest.file_hashes[registry_dest_path] = _compute_sha256(registry_content)
                
                # Also write to snapshot
                snapshot_registry = snapshot_dir / registry_dest_path
                snapshot_registry.parent.mkdir(parents=True, exist_ok=True)
                snapshot_registry.write_text(registry_content)
        
        # Write manifest to snapshot directory only (not repo root)
        manifest_path = snapshot_dir / "COMMIT_MANIFEST.md"
        manifest_path.write_text(manifest.to_markdown())
        
        # Also write JSON manifest to snapshot
        manifest_json_path = snapshot_dir / "manifest.json"
        manifest_json_path.write_text(manifest.to_json())
        
        # Store manifest as artifact in DB
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


# Required prompt paths for prompts envelope
REQUIRED_PROMPT_PATHS = [
    "prompts/step_template.md",
    "prompts/review_template.md",
    "prompts/patch_template.md",
    "prompts/chair_synthesis_template.md",
]


def commit_prompts_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit prompts outputs to target repository (S09).
    
    Writes ONLY:
    - prompts/step_template.md
    - prompts/review_template.md
    - prompts/patch_template.md
    - prompts/chair_synthesis_template.md
    (extracted from the YAML envelope in kind="output" artifact)
    - docs/ARTIFACT_REGISTRY.md (copied from factory if missing)
    - versions/<timestamp>_<run_id>/... (snapshot + manifest)
    
    Args:
        run_id: The approved prompts run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit or not a prompts run
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
    """
    import yaml
    from agentic_mvp_factory.repo import get_run, get_artifacts, write_artifact, update_run_status
    
    # Validate run exists and is ready
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    
    if run.status != "ready_to_commit":
        raise ValueError(f"Run is not ready to commit (status: {run.status})")
    
    if run.task_type != "prompts":
        raise ValueError(f"Run is not a prompts run (task_type: {run.task_type})")
    
    # Get output artifact (validated prompts envelope)
    prompts_artifacts = get_artifacts(run_id, kind="output")
    if not prompts_artifacts:
        raise ValueError("No prompts envelope (kind='output') artifact found")
    
    envelope_content = prompts_artifacts[0].content
    
    # Parse YAML envelope
    try:
        envelope = yaml.safe_load(envelope_content)
    except yaml.YAMLError as ye:
        raise ValueError(f"Failed to parse prompts envelope YAML: {ye}")
    
    if not isinstance(envelope, dict):
        raise ValueError("Prompts envelope must be a YAML dict")
    
    if "outputs" not in envelope:
        raise ValueError("Prompts envelope missing 'outputs' key")
    
    outputs = envelope["outputs"]
    if not isinstance(outputs, dict):
        raise ValueError("Prompts envelope 'outputs' must be a dict")
    
    # Validate EXACTLY the 4 required paths
    missing_keys = [k for k in REQUIRED_PROMPT_PATHS if k not in outputs]
    if missing_keys:
        raise ValueError(f"Prompts envelope missing required paths: {missing_keys}")
    
    extra_keys = [k for k in outputs.keys() if k not in REQUIRED_PROMPT_PATHS]
    if extra_keys:
        raise ValueError(f"Prompts envelope has unexpected paths: {extra_keys}")
    
    # Extract content for each prompt file
    prompt_contents = {}
    for path in REQUIRED_PROMPT_PATHS:
        content = outputs[path]
        if not isinstance(content, str):
            raise ValueError(f"Prompts envelope outputs['{path}'] must be a string")
        if not content.strip():
            raise ValueError(f"Prompts envelope outputs['{path}'] is empty")
        prompt_contents[path] = content
    
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
    
    # 3. S09: Prompts-only allowlist - write 4 prompt files + registry if missing
    registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
    paths_to_write = list(REQUIRED_PROMPT_PATHS)
    
    # Check if registry needs to be written (only if missing)
    registry_dest = repo_path / registry_dest_path
    if not registry_dest.exists():
        paths_to_write.append(registry_dest_path)
    
    # Validate all paths against registry allowlist
    for path in paths_to_write:
        # Check forbidden first
        if registry.is_forbidden(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is forbidden.\n"
                f"  Reason: forbidden path (from registry)\n"
                f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
            )
        
        # Check it's in canonical list
        if not registry.is_allowed(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is not in allowlist.\n"
                f"  Reason: non-canonical write (not in registry)\n"
                f"  Offending paths: [{path}]\n"
                f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
            )
    
    # 4. Additive-only: fail if any prompt file already exists
    existing = _check_existing_files(repo_path, REQUIRED_PROMPT_PATHS)
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: Prompt files already exist (additive-only mode).\n"
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
        
        # Write each prompt file
        for prompt_path, content in prompt_contents.items():
            # Write to stable location
            prompt_file = repo_path / prompt_path
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(content)
            
            # Write to snapshot
            snapshot_file = snapshot_dir / prompt_path
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            snapshot_file.write_text(content)
            
            # Record in manifest
            manifest.stable_paths_written.append(prompt_path)
            manifest.file_hashes[prompt_path] = _compute_sha256(content)
        
        # S09: Copy docs/ARTIFACT_REGISTRY.md to target repo if missing
        if not registry_dest.exists():
            # Copy from factory's registry
            factory_registry = Path(REGISTRY_PATH)
            if factory_registry.exists():
                registry_content = factory_registry.read_text()
                registry_dest.parent.mkdir(parents=True, exist_ok=True)
                registry_dest.write_text(registry_content)
                
                # Record in manifest
                manifest.stable_paths_written.append(registry_dest_path)
                manifest.file_hashes[registry_dest_path] = _compute_sha256(registry_content)
                
                # Also write to snapshot
                snapshot_registry = snapshot_dir / registry_dest_path
                snapshot_registry.parent.mkdir(parents=True, exist_ok=True)
                snapshot_registry.write_text(registry_content)
        
        # Write manifest to snapshot directory only (not repo root)
        manifest_path = snapshot_dir / "COMMIT_MANIFEST.md"
        manifest_path.write_text(manifest.to_markdown())
        
        # Also write JSON manifest to snapshot
        manifest_json_path = snapshot_dir / "manifest.json"
        manifest_json_path.write_text(manifest.to_json())
        
        # Store manifest as artifact in DB
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


# Required cursor rules paths for cursor_rules envelope
REQUIRED_CURSOR_RULES_PATHS = [
    ".cursor/rules/00_global.md",
    ".cursor/rules/10_invariants.md",
]


def commit_cursor_rules_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit cursor rules outputs to target repository (S11).
    
    Writes ONLY:
    - .cursor/rules/00_global.md
    - .cursor/rules/10_invariants.md
    (extracted from the YAML envelope in kind="output" artifact)
    - docs/ARTIFACT_REGISTRY.md (copied from factory if missing)
    - versions/<timestamp>_<run_id>/... (snapshot + manifest)
    
    Args:
        run_id: The approved cursor_rules run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit or not a cursor_rules run
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
    """
    import yaml
    from agentic_mvp_factory.repo import get_run, get_artifacts, write_artifact, update_run_status
    
    # Validate run exists and is ready
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    
    if run.status != "ready_to_commit":
        raise ValueError(f"Run is not ready to commit (status: {run.status})")
    
    if run.task_type != "cursor_rules":
        raise ValueError(f"Run is not a cursor_rules run (task_type: {run.task_type})")
    
    # Get output artifact (validated cursor_rules envelope)
    rules_artifacts = get_artifacts(run_id, kind="output")
    if not rules_artifacts:
        raise ValueError("No cursor_rules envelope (kind='output') artifact found")
    
    envelope_content = rules_artifacts[0].content
    
    # Parse YAML envelope
    try:
        envelope = yaml.safe_load(envelope_content)
    except yaml.YAMLError as ye:
        raise ValueError(f"Failed to parse cursor_rules envelope YAML: {ye}")
    
    if not isinstance(envelope, dict):
        raise ValueError("Cursor rules envelope must be a YAML dict")
    
    if "outputs" not in envelope:
        raise ValueError("Cursor rules envelope missing 'outputs' key")
    
    outputs = envelope["outputs"]
    if not isinstance(outputs, dict):
        raise ValueError("Cursor rules envelope 'outputs' must be a dict")
    
    # Validate EXACTLY the 2 required paths
    missing_keys = [k for k in REQUIRED_CURSOR_RULES_PATHS if k not in outputs]
    if missing_keys:
        raise ValueError(f"Cursor rules envelope missing required paths: {missing_keys}")
    
    extra_keys = [k for k in outputs.keys() if k not in REQUIRED_CURSOR_RULES_PATHS]
    if extra_keys:
        raise ValueError(f"Cursor rules envelope has unexpected paths: {extra_keys}")
    
    # Extract content for each rule file
    rules_contents = {}
    for path in REQUIRED_CURSOR_RULES_PATHS:
        content = outputs[path]
        if not isinstance(content, str):
            raise ValueError(f"Cursor rules envelope outputs['{path}'] must be a string")
        if not content.strip():
            raise ValueError(f"Cursor rules envelope outputs['{path}'] is empty")
        rules_contents[path] = content
    
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
    
    # 3. S11: Cursor rules-only allowlist - write 2 rule files + registry if missing
    registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
    paths_to_write = list(REQUIRED_CURSOR_RULES_PATHS)
    
    # Check if registry needs to be written (only if missing)
    registry_dest = repo_path / registry_dest_path
    if not registry_dest.exists():
        paths_to_write.append(registry_dest_path)
    
    # Validate all paths against registry allowlist
    for path in paths_to_write:
        # Check forbidden first
        if registry.is_forbidden(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is forbidden.\n"
                f"  Reason: forbidden path (from registry)\n"
                f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
            )
        
        # Check it's in canonical list
        if not registry.is_allowed(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is not in allowlist.\n"
                f"  Reason: non-canonical write (not in registry)\n"
                f"  Offending paths: [{path}]\n"
                f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
            )
    
    # 4. Additive-only: fail if any cursor rule file already exists
    existing = _check_existing_files(repo_path, REQUIRED_CURSOR_RULES_PATHS)
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: Cursor rule files already exist (additive-only mode).\n"
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
        
        # Write each cursor rule file
        for rule_path, content in rules_contents.items():
            # Write to stable location (ensure parent dirs exist)
            rule_file = repo_path / rule_path
            rule_file.parent.mkdir(parents=True, exist_ok=True)
            rule_file.write_text(content)
            
            # Write to snapshot
            snapshot_file = snapshot_dir / rule_path
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            snapshot_file.write_text(content)
            
            # Record in manifest
            manifest.stable_paths_written.append(rule_path)
            manifest.file_hashes[rule_path] = _compute_sha256(content)
        
        # S11: Copy docs/ARTIFACT_REGISTRY.md to target repo if missing
        if not registry_dest.exists():
            # Copy from factory's registry
            factory_registry = Path(REGISTRY_PATH)
            if factory_registry.exists():
                registry_content = factory_registry.read_text()
                registry_dest.parent.mkdir(parents=True, exist_ok=True)
                registry_dest.write_text(registry_content)
                
                # Record in manifest
                manifest.stable_paths_written.append(registry_dest_path)
                manifest.file_hashes[registry_dest_path] = _compute_sha256(registry_content)
                
                # Also write to snapshot
                snapshot_registry = snapshot_dir / registry_dest_path
                snapshot_registry.parent.mkdir(parents=True, exist_ok=True)
                snapshot_registry.write_text(registry_content)
        
        # Write manifest to snapshot directory only (not repo root)
        manifest_path = snapshot_dir / "COMMIT_MANIFEST.md"
        manifest_path.write_text(manifest.to_markdown())
        
        # Also write JSON manifest to snapshot
        manifest_json_path = snapshot_dir / "manifest.json"
        manifest_json_path.write_text(manifest.to_json())
        
        # Store manifest as artifact in DB
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


# Invariants output path
INVARIANTS_PATH = "invariants/invariants.md"


def commit_invariants_outputs(
    run_id: UUID,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit invariants outputs to target repository (S13).
    
    Writes ONLY:
    - invariants/invariants.md (from kind="output" markdown artifact)
    - docs/ARTIFACT_REGISTRY.md (copied from factory if missing)
    - versions/<timestamp>_<run_id>/... (snapshot + manifest)
    
    Args:
        run_id: The approved invariants run to commit
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If run is not ready to commit or not an invariants run
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
    """
    from agentic_mvp_factory.repo import get_run, get_artifacts, write_artifact, update_run_status
    
    # Validate run exists and is ready
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run not found: {run_id}")
    
    if run.status != "ready_to_commit":
        raise ValueError(f"Run is not ready to commit (status: {run.status})")
    
    if run.task_type != "invariants":
        raise ValueError(f"Run is not an invariants run (task_type: {run.task_type})")
    
    # Get output artifact (validated invariants markdown)
    inv_artifacts = get_artifacts(run_id, kind="output")
    if not inv_artifacts:
        raise ValueError("No invariants (kind='output') artifact found")
    
    invariants_content = inv_artifacts[0].content
    
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
    
    # 3. S13: Invariants-only allowlist - write invariants + registry if missing
    registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
    paths_to_write = [INVARIANTS_PATH]
    
    # Check if registry needs to be written (only if missing)
    registry_dest = repo_path / registry_dest_path
    if not registry_dest.exists():
        paths_to_write.append(registry_dest_path)
    
    # Validate all paths against registry allowlist
    for path in paths_to_write:
        # Check forbidden first
        if registry.is_forbidden(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is forbidden.\n"
                f"  Reason: forbidden path (from registry)\n"
                f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
            )
        
        # Check it's in canonical list
        if not registry.is_allowed(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is not in allowlist.\n"
                f"  Reason: non-canonical write (not in registry)\n"
                f"  Offending paths: [{path}]\n"
                f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
            )
    
    # 4. Additive-only: fail if invariants file already exists
    existing = _check_existing_files(repo_path, [INVARIANTS_PATH])
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: Invariants file already exists (additive-only mode).\n"
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
        
        # Write invariants file
        inv_file = repo_path / INVARIANTS_PATH
        inv_file.parent.mkdir(parents=True, exist_ok=True)
        inv_file.write_text(invariants_content)
        
        # Write to snapshot
        snapshot_inv = snapshot_dir / INVARIANTS_PATH
        snapshot_inv.parent.mkdir(parents=True, exist_ok=True)
        snapshot_inv.write_text(invariants_content)
        
        # Record in manifest
        manifest.stable_paths_written.append(INVARIANTS_PATH)
        manifest.file_hashes[INVARIANTS_PATH] = _compute_sha256(invariants_content)
        
        # S13: Copy docs/ARTIFACT_REGISTRY.md to target repo if missing
        if not registry_dest.exists():
            # Copy from factory's registry
            factory_registry = Path(REGISTRY_PATH)
            if factory_registry.exists():
                registry_content = factory_registry.read_text()
                registry_dest.parent.mkdir(parents=True, exist_ok=True)
                registry_dest.write_text(registry_content)
                
                # Record in manifest
                manifest.stable_paths_written.append(registry_dest_path)
                manifest.file_hashes[registry_dest_path] = _compute_sha256(registry_content)
                
                # Also write to snapshot
                snapshot_registry = snapshot_dir / registry_dest_path
                snapshot_registry.parent.mkdir(parents=True, exist_ok=True)
                snapshot_registry.write_text(registry_content)
        
        # Write manifest to snapshot directory only (not repo root)
        manifest_path = snapshot_dir / "COMMIT_MANIFEST.md"
        manifest_path.write_text(manifest.to_markdown())
        
        # Also write JSON manifest to snapshot
        manifest_json_path = snapshot_dir / "manifest.json"
        manifest_json_path.write_text(manifest.to_json())
        
        # Store manifest as artifact in DB
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


# Task types required for a full pack commit
PACK_TASK_TYPES = ["spec", "tracker", "prompts", "cursor_rules", "invariants"]

# Mapping from task_type to the canonical paths they produce
TASK_TYPE_TO_PATHS = {
    "spec": ["spec/spec.yaml"],
    "tracker": ["tracker/factory_tracker.yaml"],
    "prompts": [
        "prompts/step_template.md",
        "prompts/review_template.md",
        "prompts/patch_template.md",
        "prompts/chair_synthesis_template.md",
    ],
    "cursor_rules": [
        ".cursor/rules/00_global.md",
        ".cursor/rules/10_invariants.md",
    ],
    "invariants": ["invariants/invariants.md"],
}


def commit_pack(
    plan_run_id: UUID,
    project_slug: str,
    repo_path: Path,
) -> CommitManifest:
    """
    Commit a full canonical pack to target repository (S14).
    
    Selects the latest approved Phase 2 outputs for each artifact type
    (spec, tracker, prompts, cursor_rules, invariants) and writes them all
    in a single commit operation.
    
    Args:
        plan_run_id: The approved plan run ID (parent for all artifacts)
        project_slug: Project namespace
        repo_path: Target repository path
        
    Returns:
        CommitManifest with details of written files
        
    Raises:
        ValueError: If any artifact type is missing an approved run
        RuntimeError: If lock cannot be acquired, repo is dirty, or not a git repo
    """
    import yaml
    from agentic_mvp_factory.repo import (
        get_run, get_artifacts, write_artifact, update_run_status,
        create_run, get_latest_approved_run_by_task_type
    )
    
    # Validate plan run exists
    plan_run = get_run(plan_run_id)
    if not plan_run:
        raise ValueError(f"Plan run not found: {plan_run_id}")
    
    # Collect all approved runs for each task type
    approved_runs = {}
    missing_types = []
    
    for task_type in PACK_TASK_TYPES:
        run = get_latest_approved_run_by_task_type(task_type, plan_run_id)
        if run:
            # Verify it has an output artifact
            outputs = get_artifacts(run.id, kind="output")
            if outputs:
                approved_runs[task_type] = (run, outputs[0])
            else:
                missing_types.append(f"{task_type} (run {run.id} has no output artifact)")
        else:
            missing_types.append(task_type)
    
    if missing_types:
        raise ValueError(
            f"PACK COMMIT BLOCKED: Missing approved artifacts.\n"
            f"  Missing: {missing_types}\n"
            f"  Fix: Run the missing councils with --from-plan {plan_run_id} and approve them."
        )
    
    # Build the unified write-set
    files_to_write = {}  # path -> content
    
    for task_type, (run, artifact) in approved_runs.items():
        content = artifact.content
        
        if task_type == "spec":
            files_to_write["spec/spec.yaml"] = content
            
        elif task_type == "tracker":
            files_to_write["tracker/factory_tracker.yaml"] = content
            
        elif task_type == "prompts":
            # Parse YAML envelope and extract 4 prompt files
            try:
                envelope = yaml.safe_load(content)
                outputs = envelope.get("outputs", {})
                for path in TASK_TYPE_TO_PATHS["prompts"]:
                    if path not in outputs:
                        raise ValueError(f"Prompts envelope missing {path}")
                    files_to_write[path] = outputs[path]
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse prompts envelope: {e}")
                
        elif task_type == "cursor_rules":
            # Parse YAML envelope and extract 2 rule files
            try:
                envelope = yaml.safe_load(content)
                outputs = envelope.get("outputs", {})
                for path in TASK_TYPE_TO_PATHS["cursor_rules"]:
                    if path not in outputs:
                        raise ValueError(f"Cursor rules envelope missing {path}")
                    files_to_write[path] = outputs[path]
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse cursor_rules envelope: {e}")
                
        elif task_type == "invariants":
            files_to_write["invariants/invariants.md"] = content
    
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
    
    # 3. Check if registry needs to be written
    registry_dest_path = "docs/ARTIFACT_REGISTRY.md"
    registry_dest = repo_path / registry_dest_path
    paths_to_write = list(files_to_write.keys())
    if not registry_dest.exists():
        paths_to_write.append(registry_dest_path)
    
    # 4. Validate all paths against registry allowlist
    for path in paths_to_write:
        if registry.is_forbidden(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is forbidden.\n"
                f"  Reason: forbidden path (from registry)\n"
                f"  Forbidden (per docs/ARTIFACT_REGISTRY.md): {registry.forbidden}"
            )
        
        if not registry.is_allowed(path):
            raise ValueError(
                f"COMMIT BLOCKED: {path} is not in allowlist.\n"
                f"  Reason: non-canonical write (not in registry)\n"
                f"  Offending paths: [{path}]\n"
                f"  Allowed (per docs/ARTIFACT_REGISTRY.md): {registry.canonical}"
            )
    
    # 5. Additive-only: fail if any destination already exists
    all_canonical_paths = list(files_to_write.keys())
    existing = _check_existing_files(repo_path, all_canonical_paths)
    if existing:
        raise ValueError(
            f"COMMIT BLOCKED: Destination files already exist (additive-only mode).\n"
            f"  Reason: overwrite\n"
            f"  Offending files: {existing}\n"
            f"  Fix: Remove these files or use a fresh repo to proceed."
        )
    
    # === END FAIL-SAFE CHECKS ===
    
    # Create a new run for the pack commit
    pack_run = create_run(
        project_slug=project_slug,
        task_type="commit_pack",
        parent_run_id=plan_run_id,
    )
    pack_run_id = pack_run.id
    
    # Acquire lock
    if not _acquire_lock(repo_path):
        raise RuntimeError(f"Cannot acquire lock - another commit may be in progress. Check {repo_path / LOCK_FILE}")
    
    try:
        # Update status to committing
        update_run_status(pack_run_id, "committing")
        
        # Prepare manifest
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest = CommitManifest(
            run_id=str(pack_run_id),
            timestamp=timestamp,
        )
        
        # Create snapshot directory
        snapshot_dir = repo_path / "versions" / f"{timestamp}_{pack_run_id}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest.snapshot_path = str(snapshot_dir.relative_to(repo_path))
        
        # Write all files
        for file_path, content in files_to_write.items():
            # Write to stable location (ensure parent dirs exist)
            dest_file = repo_path / file_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(content)
            
            # Write to snapshot
            snapshot_file = snapshot_dir / file_path
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            snapshot_file.write_text(content)
            
            # Record in manifest
            manifest.stable_paths_written.append(file_path)
            manifest.file_hashes[file_path] = _compute_sha256(content)
        
        # Copy docs/ARTIFACT_REGISTRY.md if missing
        if not registry_dest.exists():
            factory_registry = Path(REGISTRY_PATH)
            if factory_registry.exists():
                registry_content = factory_registry.read_text()
                registry_dest.parent.mkdir(parents=True, exist_ok=True)
                registry_dest.write_text(registry_content)
                
                manifest.stable_paths_written.append(registry_dest_path)
                manifest.file_hashes[registry_dest_path] = _compute_sha256(registry_content)
                
                snapshot_registry = snapshot_dir / registry_dest_path
                snapshot_registry.parent.mkdir(parents=True, exist_ok=True)
                snapshot_registry.write_text(registry_content)
        
        # Write manifest to snapshot directory
        manifest_path = snapshot_dir / "COMMIT_MANIFEST.md"
        manifest_path.write_text(manifest.to_markdown())
        
        manifest_json_path = snapshot_dir / "manifest.json"
        manifest_json_path.write_text(manifest.to_json())
        
        # Store commit manifest as artifact
        write_artifact(
            run_id=pack_run_id,
            kind="commit_manifest",
            content=manifest.to_json(),
            model=None,
        )
        
        # Update status to completed
        update_run_status(pack_run_id, "completed")
        
        return manifest
        
    finally:
        # Always release lock
        _release_lock(repo_path)
