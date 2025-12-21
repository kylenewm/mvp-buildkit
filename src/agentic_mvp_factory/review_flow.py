"""Manual review and delta recording for Phase 3.

No AI, no LangGraph, no Postgres.
Pure human governance surface.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def load_execution_report(report_path: Path) -> dict:
    """Load an execution report JSON file."""
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")
    
    return json.loads(report_path.read_text())


def print_review_template(report: dict) -> None:
    """Print a review template for the human to evaluate."""
    print("=" * 60)
    print("STEP REVIEW")
    print("=" * 60)
    print()
    print(f"Task ID:     {report['task_id']}")
    print(f"File:        {report['file_path']}")
    print(f"Status:      {report['status']}")
    print(f"Exit Code:   {report['exit_code']}")
    print(f"Retries:     {report['retries']}")
    print(f"Duration:    {report['duration_seconds']:.2f}s")
    print()
    
    if report.get("stdout"):
        print("--- STDOUT ---")
        print(report["stdout"][:500])
        if len(report["stdout"]) > 500:
            print(f"... ({len(report['stdout'])} chars total)")
        print()
    
    if report.get("stderr"):
        print("--- STDERR ---")
        print(report["stderr"][:500])
        if len(report["stderr"]) > 500:
            print(f"... ({len(report['stderr'])} chars total)")
        print()
    
    print("=" * 60)
    print("REVIEW CHECKLIST")
    print("=" * 60)
    print()
    print("[ ] Code executed successfully (exit code 0)")
    print("[ ] Output matches expected behavior")
    print("[ ] No unintended side effects")
    print("[ ] Ready for next step")
    print()


def prompt_review_decision() -> tuple[str, Optional[str]]:
    """
    Prompt the human for ACCEPT or REJECT decision.
    
    Returns:
        (decision, notes) where decision is "ACCEPT" or "REJECT"
    """
    print("Decision: [A]ccept / [R]eject")
    
    while True:
        choice = input("> ").strip().upper()
        if choice in ("A", "ACCEPT"):
            decision = "ACCEPT"
            break
        elif choice in ("R", "REJECT"):
            decision = "REJECT"
            break
        else:
            print("Invalid choice. Enter A or R.")
    
    print()
    print("Notes (optional, press Enter to skip):")
    notes = input("> ").strip() or None
    
    return decision, notes


def write_delta(
    report: dict,
    decision: str,
    notes: Optional[str],
    report_path: Path,
    delta_dir: Path,
) -> Optional[Path]:
    """
    Write a delta JSON file on ACCEPT.
    
    Returns:
        Path to delta file if ACCEPT, None if REJECT
    """
    if decision != "ACCEPT":
        return None
    
    delta_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    delta_filename = f"{report['task_id']}_{timestamp}_delta.json"
    delta_path = delta_dir / delta_filename
    
    delta = {
        "task_id": report["task_id"],
        "decision": decision,
        "notes": notes,
        "reviewed_at": datetime.now().isoformat(),
        "execution_report": str(report_path),
        "file_path": report["file_path"],
        "status": report["status"],
        "exit_code": report["exit_code"],
        "retries": report["retries"],
    }
    
    delta_path.write_text(json.dumps(delta, indent=2))
    
    return delta_path


def run_review(
    report_path: Path,
    delta_dir: Optional[Path] = None,
) -> tuple[str, Optional[Path]]:
    """
    Main entry point: load report, show template, prompt decision, write delta.
    
    Args:
        report_path: Path to execution report JSON
        delta_dir: Directory for delta files (default: execution/deltas/)
    
    Returns:
        (decision, delta_path) where delta_path is None if REJECT
    """
    if delta_dir is None:
        delta_dir = Path("execution/deltas")
    
    # Load report
    report = load_execution_report(report_path)
    
    # Show review template
    print_review_template(report)
    
    # Get human decision
    decision, notes = prompt_review_decision()
    
    # Write delta on ACCEPT
    delta_path = write_delta(
        report=report,
        decision=decision,
        notes=notes,
        report_path=report_path,
        delta_dir=delta_dir,
    )
    
    print()
    if decision == "ACCEPT":
        print(f"ACCEPTED")
        print(f"  Delta written: {delta_path}")
    else:
        print(f"REJECTED")
        print(f"  No delta written.")
        if notes:
            print(f"  Notes: {notes}")
    
    return decision, delta_path

