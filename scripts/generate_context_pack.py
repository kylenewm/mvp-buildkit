#!/usr/bin/env python3
"""Generate context_pack_lite.md from Phase -1 artifacts.

Reads build_candidate.yaml and research_snapshot.yaml, filters findings by
triage_bucket, and produces a context pack for planning prompts.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    """Load YAML file, return empty dict on error."""
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading {path}: {e}", file=sys.stderr)
        return {}


def bucket_order(bucket: str) -> int:
    """Sort key: high=0, normal=1, low=2, junk=3."""
    return {"high": 0, "normal": 1, "low": 2, "junk": 3}.get(bucket, 1)


def generate_context_pack(phase_dir: Path, output_path: Path) -> bool:
    """Generate context_pack_lite.md from Phase -1 artifacts.
    
    Returns True on success, False on error.
    """
    build_path = phase_dir / "build_candidate.yaml"
    snapshot_path = phase_dir / "research_snapshot.yaml"

    if not build_path.exists():
        print(f"Error: {build_path} not found", file=sys.stderr)
        return False
    if not snapshot_path.exists():
        print(f"Error: {snapshot_path} not found", file=sys.stderr)
        return False

    build = load_yaml(build_path)
    snapshot = load_yaml(snapshot_path)

    if not build or not snapshot:
        return False

    lines = []

    # === 1. Header ===
    build_id = build.get("build_id", "Unknown")
    title = build.get("title", "Unknown Project")
    retrieved_at = snapshot.get("retrieved_at", "Unknown")

    lines.append(f"# Context Pack Lite — {build_id}: {title}")
    lines.append("")
    lines.append(f"**Generated:** {retrieved_at}")
    lines.append("")

    # === 2. Problem & Core Value ===
    lines.append("## What we're building")
    lines.append("")
    problem = build.get("problem", "").strip()
    core_value = build.get("core_value", "").strip()
    if problem:
        lines.append(problem)
        lines.append("")
    if core_value:
        lines.append(f"**Core Value:** {core_value}")
        lines.append("")

    # === 3. Constraints (and assumptions) ===
    lines.append("## Key constraints")
    lines.append("")
    constraints = build.get("constraints", [])
    if constraints:
        for c in constraints:
            lines.append(f"- {c}")
    else:
        lines.append("*No constraints defined.*")
    lines.append("")

    assumptions = build.get("assumptions", [])
    if assumptions:
        lines.append("## Assumptions")
        lines.append("")
        for a in assumptions:
            lines.append(f"- {a}")
        lines.append("")

    # === 4. Research Summaries ===
    # Build answer map from answers list
    answers_list = snapshot.get("answers", [])
    answer_map = {a.get("rq_id"): a.get("answer_summary", "") for a in answers_list}

    research_questions = snapshot.get("research_questions", [])
    if research_questions:
        lines.append("## Research Summaries")
        lines.append("")
        for rq in research_questions:
            rq_id = rq.get("id", "?")
            question = rq.get("question", "").strip()
            summary = answer_map.get(rq_id, "")
            
            lines.append(f"### {rq_id}: {question}")
            lines.append("")
            if summary:
                lines.append(summary)
            else:
                lines.append("*No summary yet.*")
            lines.append("")

    # === 5. Evidence ===
    findings = snapshot.get("findings", [])
    if not findings:
        lines.append("## Evidence")
        lines.append("")
        lines.append("*No findings yet.*")
        lines.append("")
    else:
        # Group by rq_id and sort within each group
        by_rq = defaultdict(list)
        for f in findings:
            rq_id = f.get("rq_id", "UNKNOWN")
            by_rq[rq_id].append(f)

        # Sort each rq group by bucket
        for rq_id in by_rq:
            by_rq[rq_id].sort(key=lambda x: bucket_order(x.get("triage_bucket", "normal")))

        # Collect findings by bucket
        high_findings = []
        normal_findings = []
        skip_counts = defaultdict(lambda: {"low": 0, "junk": 0})

        for rq_id, rq_findings in by_rq.items():
            high_count = 0
            for f in rq_findings:
                bucket = f.get("triage_bucket", "normal")
                if bucket == "high":
                    if high_count < 3:
                        high_findings.append(f)
                        high_count += 1
                elif bucket == "normal":
                    normal_findings.append(f)
                elif bucket == "low":
                    skip_counts[rq_id]["low"] += 1
                elif bucket == "junk":
                    skip_counts[rq_id]["junk"] += 1

        # === HIGH evidence (detailed) ===
        if high_findings:
            lines.append("## High-Signal Evidence")
            lines.append("")
            for f in high_findings:
                rq_id = f.get("rq_id", "?")
                page_title = f.get("page_title", "No Title")
                source_url = f.get("source_url", "")
                claim = f.get("claim", "").strip()
                snippet = f.get("evidence_snippet", "").strip()

                lines.append(f"### [{rq_id}] {page_title}")
                lines.append(f"**Source:** {source_url}")
                lines.append("")
                if claim:
                    lines.append(f"**Claim:** {claim}")
                    lines.append("")
                if snippet:
                    lines.append("**Evidence:**")
                    lines.append("")
                    lines.append(f"> {snippet.replace(chr(10), chr(10) + '> ')}")
                    lines.append("")

        # === NORMAL evidence (detailed) ===
        if normal_findings:
            lines.append("## Supporting Evidence")
            lines.append("")
            for f in normal_findings:
                rq_id = f.get("rq_id", "?")
                fid = f.get("id", "?")
                page_title = f.get("page_title", "No Title")
                source_url = f.get("source_url", "")
                claim = f.get("claim", "").strip()
                snippet = f.get("evidence_snippet", "").strip()

                lines.append(f"### [{rq_id}] {fid}: {page_title}")
                lines.append(f"**Source:** {source_url}")
                lines.append("")
                if claim:
                    lines.append(f"**Claim:** {claim}")
                    lines.append("")
                if snippet:
                    lines.append("**Evidence:**")
                    lines.append("")
                    lines.append(f"> {snippet.replace(chr(10), chr(10) + '> ')}")
                    lines.append("")

        # === Skip counts (low/junk) ===
        total_low = sum(v["low"] for v in skip_counts.values())
        total_junk = sum(v["junk"] for v in skip_counts.values())
        if total_low > 0 or total_junk > 0:
            lines.append("## Skipped Evidence")
            lines.append("")
            for rq_id, counts in skip_counts.items():
                if counts["low"] > 0 or counts["junk"] > 0:
                    parts = []
                    if counts["low"] > 0:
                        parts.append(f"low={counts['low']}")
                    if counts["junk"] > 0:
                        parts.append(f"junk={counts['junk']}")
                    lines.append(f"- **{rq_id}**: {', '.join(parts)}")
            lines.append("")

    # === 6. Unknowns (carry forward) ===
    unknowns = snapshot.get("unknowns", [])
    if unknowns:
        lines.append("## Unknowns (carry forward)")
        lines.append("")
        for u in unknowns:
            lines.append(f"- {u}")
        lines.append("")

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Generated: {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Generate context_pack_lite.md from Phase -1 artifacts."
    )
    parser.add_argument(
        "--phase-dir",
        default="phase_minus_1",
        help="Path to phase_minus_1 directory (default: phase_minus_1)",
    )
    parser.add_argument(
        "--out",
        default="phase_0/context_pack_lite.md",
        help="Output path (default: phase_0/context_pack_lite.md)",
    )
    args = parser.parse_args()

    phase_dir = Path(args.phase_dir)
    output_path = Path(args.out)

    success = generate_context_pack(phase_dir, output_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
