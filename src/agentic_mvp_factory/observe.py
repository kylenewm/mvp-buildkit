"""Minimal observation surface for Phase 3.

Read-only. No Postgres, no LangGraph, no interactivity.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def find_reports(task_id: str, reports_dir: Path) -> list[dict]:
    """Find all execution reports for a task_id."""
    reports = []
    
    if not reports_dir.exists():
        return reports
    
    for f in reports_dir.glob(f"{task_id}_*.json"):
        try:
            data = json.loads(f.read_text())
            data["_report_file"] = str(f)
            reports.append(data)
        except (json.JSONDecodeError, IOError):
            pass
    
    # Sort by start_time descending (most recent first)
    reports.sort(key=lambda r: r.get("start_time", ""), reverse=True)
    return reports


def find_deltas(task_id: str, deltas_dir: Path) -> list[dict]:
    """Find all deltas for a task_id."""
    deltas = []
    
    if not deltas_dir.exists():
        return deltas
    
    for f in deltas_dir.glob(f"{task_id}_*_delta.json"):
        try:
            data = json.loads(f.read_text())
            data["_delta_file"] = str(f)
            deltas.append(data)
        except (json.JSONDecodeError, IOError):
            pass
    
    # Sort by reviewed_at descending
    deltas.sort(key=lambda d: d.get("reviewed_at", ""), reverse=True)
    return deltas


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.0f}s"


def print_summary(
    task_id: str,
    reports_dir: Optional[Path] = None,
    deltas_dir: Optional[Path] = None,
) -> None:
    """
    Print a human-readable summary of a task's execution history.
    
    Goal: understand the full run in under 30 seconds.
    """
    if reports_dir is None:
        reports_dir = Path("execution/reports")
    if deltas_dir is None:
        deltas_dir = Path("execution/deltas")
    
    reports = find_reports(task_id, reports_dir)
    deltas = find_deltas(task_id, deltas_dir)
    
    # Header
    print("=" * 60)
    print(f"TASK SUMMARY: {task_id}")
    print("=" * 60)
    print()
    
    if not reports and not deltas:
        print("No execution records found.")
        print()
        print(f"Searched:")
        print(f"  Reports: {reports_dir}")
        print(f"  Deltas:  {deltas_dir}")
        return
    
    # Latest execution
    if reports:
        latest = reports[0]
        print("LATEST EXECUTION")
        print("-" * 40)
        print(f"  Status:      {latest['status']}")
        print(f"  Exit code:   {latest['exit_code']}")
        print(f"  Retries:     {latest['retries']}/{latest['max_retries']}")
        print(f"  Duration:    {format_duration(latest['duration_seconds'])}")
        print(f"  File:        {latest['file_path']}")
        print(f"  Time:        {latest['start_time'][:19]}")
        print()
        
        # Output preview
        if latest.get("stdout"):
            stdout = latest["stdout"].strip()
            if stdout:
                print("  Output:")
                for line in stdout.split("\n")[:3]:
                    print(f"    {line[:60]}")
                if len(stdout.split("\n")) > 3:
                    print(f"    ... ({len(stdout)} chars)")
                print()
        
        if latest.get("stderr") and latest["status"] == "FAILED":
            stderr = latest["stderr"].strip()
            if stderr:
                print("  Error:")
                for line in stderr.split("\n")[:3]:
                    print(f"    {line[:60]}")
                print()
    
    # Review status
    print("REVIEW STATUS")
    print("-" * 40)
    if deltas:
        latest_delta = deltas[0]
        print(f"  Decision:    {latest_delta['decision']}")
        print(f"  Reviewed:    {latest_delta['reviewed_at'][:19]}")
        if latest_delta.get("notes"):
            print(f"  Notes:       {latest_delta['notes'][:50]}")
        print()
    else:
        print("  Not yet reviewed.")
        print()
    
    # History
    if len(reports) > 1 or len(deltas) > 1:
        print("HISTORY")
        print("-" * 40)
        print(f"  Executions:  {len(reports)}")
        print(f"  Reviews:     {len(deltas)}")
        
        # Show execution history
        for i, r in enumerate(reports[:5]):
            status_icon = "✓" if r["status"] == "SUCCESS" else "✗"
            print(f"    {status_icon} {r['start_time'][:16]} - {r['status']}")
        
        if len(reports) > 5:
            print(f"    ... and {len(reports) - 5} more")
        print()
    
    # Final verdict
    print("VERDICT")
    print("-" * 40)
    if reports and deltas:
        if reports[0]["status"] == "SUCCESS" and deltas[0]["decision"] == "ACCEPT":
            print("  ✓ COMPLETE - Executed successfully and accepted")
        elif reports[0]["status"] == "SUCCESS":
            print("  ◐ PENDING REVIEW - Executed successfully, awaiting review")
        elif deltas[0]["decision"] == "REJECT":
            print("  ✗ REJECTED - Needs rework")
        else:
            print("  ✗ FAILED - Execution failed")
    elif reports:
        if reports[0]["status"] == "SUCCESS":
            print("  ◐ PENDING REVIEW - Executed successfully, awaiting review")
        else:
            print("  ✗ FAILED - Execution failed, no review")
    else:
        print("  ? UNKNOWN - No execution records")
    print()

