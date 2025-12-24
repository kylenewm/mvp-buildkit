#!/usr/bin/env python3
"""Drift guard: checks that deprecated paths are not referenced in canonical artifacts.

Exit codes:
  0 = clean (no deprecated references found)
  1 = drift detected (deprecated paths referenced)
"""

import re
import sys
from pathlib import Path

# Deprecated paths that should NOT be referenced
DEPRECATED_PATHS = [
    "prompts/hotfix_sync.md",
    "docs/build_guide.md",
    "tracker/tracker.yaml",  # Common typo for factory_tracker.yaml
]

# Canonical files to check for deprecated references
CANONICAL_GLOBS = [
    "prompts/*.md",
    ".cursor/rules/*.md",
    "spec/*.yaml",
    "invariants/*.md",
    "docs/*.md",
    "README.md",
]


def find_references(file_path: Path, deprecated: list[str]) -> list[tuple[str, int, str]]:
    """Find references to deprecated paths in a file.
    
    Returns list of (deprecated_path, line_number, line_content)
    """
    findings = []
    try:
        content = file_path.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            for dep_path in deprecated:
                # Match the path literally or as part of a longer path
                if dep_path in line:
                    findings.append((dep_path, i, line.strip()))
    except Exception:
        pass
    return findings


def main():
    repo_root = Path(__file__).parent.parent
    
    # Hard failure: tracker/tracker.yaml must NOT exist (common typo)
    typo_tracker = repo_root / "tracker" / "tracker.yaml"
    if typo_tracker.exists():
        print("❌ HARD FAILURE: tracker/tracker.yaml exists!")
        print("   This file is deprecated. Use tracker/factory_tracker.yaml instead.")
        print("   Delete tracker/tracker.yaml to proceed.")
        return 1
    
    # Collect all canonical files
    canonical_files = []
    for glob_pattern in CANONICAL_GLOBS:
        canonical_files.extend(repo_root.glob(glob_pattern))
    
    # Check each file
    all_findings = []
    for file_path in canonical_files:
        if "archive" in str(file_path):
            continue  # Skip archived files
        if "ARTIFACT_REGISTRY" in str(file_path):
            continue  # Skip the registry itself (it documents deprecated paths)
        findings = find_references(file_path, DEPRECATED_PATHS)
        if findings:
            all_findings.append((file_path, findings))
    
    # Report
    if not all_findings:
        print("✅ No deprecated artifact references found")
        print(f"   Checked {len(canonical_files)} canonical files")
        print(f"   Against {len(DEPRECATED_PATHS)} deprecated paths")
        return 0
    
    print("❌ Deprecated artifact references detected!")
    print()
    for file_path, findings in all_findings:
        rel_path = file_path.relative_to(repo_root)
        print(f"  {rel_path}:")
        for dep_path, line_num, line_content in findings:
            print(f"    L{line_num}: references '{dep_path}'")
            print(f"          {line_content[:80]}")
        print()
    
    print(f"Fix these references or update ARTIFACT_REGISTRY.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())

