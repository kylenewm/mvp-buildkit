#!/usr/bin/env python3
"""Drift guard: checks that forbidden paths are not referenced in canonical artifacts.

Uses docs/ARTIFACT_REGISTRY.md as the single source of truth.

Exceptions (only two):
  A) docs/ARTIFACT_REGISTRY.md is skipped entirely (it defines forbidden paths)
  B) tracker/factory_tracker.yaml may list forbidden paths ONLY under `forbidden_paths:` key

Exit codes:
  0 = clean (no forbidden references found)
  1 = drift detected (forbidden paths referenced in canonical files)
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple


def parse_registry(registry_path: Path) -> Tuple[List[str], List[str]]:
    """
    Parse docs/ARTIFACT_REGISTRY.md and extract canonical and forbidden paths.
    
    Returns:
        (canonical_paths, forbidden_paths)
    """
    canonical = []
    forbidden = []
    
    if not registry_path.exists():
        print(f"ERROR: Registry file not found: {registry_path}")
        sys.exit(1)
    
    content = registry_path.read_text()
    lines = content.splitlines()
    
    current_section = None
    
    for line in lines:
        stripped = line.strip()
        
        # Detect section headers
        if stripped == "## Canonical":
            current_section = "canonical"
            continue
        elif stripped == "## Generated":
            current_section = "generated"
            continue
        elif stripped == "## Forbidden":
            current_section = "forbidden"
            continue
        elif stripped.startswith("## ") or stripped.startswith("---"):
            current_section = None
            continue
        
        # Parse list items in sections
        if current_section and stripped.startswith("- "):
            path = stripped[2:].strip()
            # Skip glob patterns
            if "**" in path or "*" in path:
                continue
            if current_section == "canonical":
                canonical.append(path)
            elif current_section == "forbidden":
                forbidden.append(path)
    
    return canonical, forbidden


def find_forbidden_references_strict(
    file_path: Path,
    forbidden_paths: List[str],
    is_tracker_file: bool = False,
) -> List[Tuple[str, int, str]]:
    """
    Find references to forbidden paths in a file. STRICT MODE.
    
    Only exception for tracker: skip matches inside `forbidden_paths:` YAML block.
    
    Returns list of (forbidden_path, line_number, line_content)
    """
    findings = []
    
    try:
        content = file_path.read_text()
        lines = content.splitlines()
        
        # For tracker file: track if we're inside the forbidden_paths YAML block
        in_forbidden_block = False
        forbidden_block_indent = 0
        
        for i, line in enumerate(lines, 1):
            # Calculate leading whitespace
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            
            if is_tracker_file:
                # Detect entering forbidden_paths block
                if re.match(r'^\s*forbidden_paths:\s*$', line):
                    in_forbidden_block = True
                    forbidden_block_indent = indent
                    continue
                
                # Detect exiting forbidden_paths block
                if in_forbidden_block:
                    # Exit if: blank line, or non-blank line with indent <= block indent that's not a list item
                    if stripped == "":
                        # Blank line - stay in block (YAML allows blank lines in lists)
                        pass
                    elif indent <= forbidden_block_indent and not stripped.startswith("-"):
                        # New key at same or lesser indent - exit block
                        in_forbidden_block = False
                    elif indent <= forbidden_block_indent and not stripped.startswith("- "):
                        # Something else at same indent - exit block
                        in_forbidden_block = False
                
                # Skip this line if we're in the forbidden_paths block
                if in_forbidden_block:
                    continue
            
            # Check for forbidden paths
            for forbidden in forbidden_paths:
                if forbidden in line:
                    # Exception: if forbidden path appears after "versions/" it's okay
                    # (versions/** is in Generated, so references to things inside versions are fine)
                    idx = line.find(forbidden)
                    prefix = line[:idx]
                    if "versions/" in prefix or "versions\\" in prefix:
                        continue
                    findings.append((forbidden, i, line.strip()))
                    
    except Exception as e:
        print(f"WARNING: Could not read {file_path}: {e}")
    
    return findings


def main():
    repo_root = Path(__file__).parent.parent
    registry_path = repo_root / "docs" / "ARTIFACT_REGISTRY.md"
    
    # Parse registry
    canonical_paths, forbidden_paths = parse_registry(registry_path)
    
    print(f"Registry: {registry_path.relative_to(repo_root)}")
    print(f"  Canonical paths: {len(canonical_paths)}")
    print(f"  Forbidden paths: {len(forbidden_paths)}")
    print()
    
    if not forbidden_paths:
        print("WARNING: No forbidden paths defined in registry")
    
    # Hard failure: check if any forbidden path file actually exists
    existing_forbidden = []
    for forbidden in forbidden_paths:
        forbidden_file = repo_root / forbidden
        if forbidden_file.exists():
            existing_forbidden.append(forbidden)
    
    if existing_forbidden:
        print("❌ HARD FAILURE: Forbidden files exist in repo!")
        for path in existing_forbidden:
            print(f"   - {path}")
        print()
        print("Delete these files to proceed.")
        return 1
    
    # Scan canonical files for forbidden references
    all_findings = []
    missing_files = []
    
    for canonical in canonical_paths:
        canonical_file = repo_root / canonical
        
        # Exception A: Skip the registry itself (it defines forbidden paths)
        if canonical == "docs/ARTIFACT_REGISTRY.md":
            continue
        
        if not canonical_file.exists():
            missing_files.append(canonical)
            continue
        
        # Exception B: Tracker file gets special handling for forbidden_paths block
        is_tracker = (canonical == "tracker/factory_tracker.yaml")
        
        findings = find_forbidden_references_strict(
            canonical_file, 
            forbidden_paths,
            is_tracker_file=is_tracker,
        )
        if findings:
            all_findings.append((canonical, findings))
    
    # Report missing files (warning only)
    if missing_files:
        print(f"WARNING: {len(missing_files)} canonical files not found:")
        for path in missing_files:
            print(f"   - {path}")
        print()
    
    # Report violations
    if not all_findings:
        print("✅ No forbidden artifact references found")
        checked_count = len(canonical_paths) - len(missing_files) - 1  # -1 for registry
        print(f"   Checked {checked_count} canonical files")
        print(f"   Against {len(forbidden_paths)} forbidden paths")
        return 0
    
    print("❌ Forbidden artifact references detected!")
    print()
    
    total_violations = 0
    for file_path, findings in all_findings:
        print(f"  {file_path}:")
        for forbidden, line_num, line_content in findings:
            print(f"    L{line_num}: contains forbidden '{forbidden}'")
            # Truncate long lines
            display_line = line_content[:80] + ("..." if len(line_content) > 80 else "")
            print(f"          {display_line}")
            total_violations += 1
        print()
    
    print(f"Total violations: {total_violations}")
    print(f"Fix these references to use canonical paths only.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
