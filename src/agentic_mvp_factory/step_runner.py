"""Thin execution runner for Phase 3.

Loads a step definition, runs the execution loop, writes a report.
No LangGraph, no Postgres, no automation.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from agentic_mvp_factory.execution_state import ExecutionState
from agentic_mvp_factory.execution_loop import run_execution_loop
from agentic_mvp_factory.model_client import get_openrouter_client


def load_step_definition(step_file: Path) -> dict:
    """
    Load a step definition from YAML or JSON.
    
    Required fields:
        - task_id: str
        - file_path: str (path to Python file to execute)
    
    Optional fields:
        - max_retries: int (default 1)
    """
    content = step_file.read_text()
    
    if step_file.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(content)
    elif step_file.suffix == ".json":
        data = json.loads(content)
    else:
        raise ValueError(f"Unsupported file type: {step_file.suffix}. Use .yaml, .yml, or .json")
    
    # Validate required fields
    if "task_id" not in data:
        raise ValueError("Step definition missing required field: task_id")
    if "file_path" not in data:
        raise ValueError("Step definition missing required field: file_path")
    
    return data


def build_execution_state(step_def: dict) -> ExecutionState:
    """Construct an ExecutionState from a step definition."""
    return ExecutionState(
        task_id=step_def["task_id"],
        file_path=step_def["file_path"],
        max_retries=step_def.get("max_retries", 1),
    )


def write_execution_report(
    state: ExecutionState,
    step_file: Path,
    output_dir: Path,
    start_time: datetime,
    end_time: datetime,
) -> Path:
    """
    Write a structured execution report to disk.
    
    Report format: JSON with all execution details.
    Filename: {task_id}_{timestamp}.json
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = end_time.strftime("%Y%m%d_%H%M%S")
    report_filename = f"{state.task_id}_{timestamp}.json"
    report_path = output_dir / report_filename
    
    report = {
        "task_id": state.task_id,
        "step_file": str(step_file),
        "file_path": state.file_path,
        "status": state.status,
        "exit_code": state.exit_code,
        "retries": state.retries,
        "max_retries": state.max_retries,
        "stdout": state.last_stdout,
        "stderr": state.last_stderr,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": (end_time - start_time).total_seconds(),
    }
    
    report_path.write_text(json.dumps(report, indent=2))
    
    return report_path


def run_step(
    step_file: Path,
    output_dir: Optional[Path] = None,
    use_graph: bool = True,
) -> ExecutionState:
    """
    Main entry point: load step, run execution loop, write report.
    
    Args:
        step_file: Path to step definition (YAML or JSON)
        output_dir: Directory for execution reports (default: ./execution/reports/)
        use_graph: If True, use LangGraph for tracing visibility (default: True)
    
    Returns:
        Final ExecutionState
    """
    if output_dir is None:
        output_dir = Path("execution/reports")
    
    # Load step definition
    step_def = load_step_definition(step_file)
    
    # Get model client
    client = get_openrouter_client()
    
    # Record start time
    start_time = datetime.now()
    
    # Run execution - with or without graph tracing
    if use_graph:
        from agentic_mvp_factory.execution_graph import run_execution_graph
        final_state = run_execution_graph(
            task_id=step_def["task_id"],
            file_path=step_def["file_path"],
            model_client=client,
            max_retries=step_def.get("max_retries", 1),
        )
    else:
        state = build_execution_state(step_def)
        final_state = run_execution_loop(state, client)
    
    # Record end time
    end_time = datetime.now()
    
    # Write report
    report_path = write_execution_report(
        state=final_state,
        step_file=step_file,
        output_dir=output_dir,
        start_time=start_time,
        end_time=end_time,
    )
    
    print(f"Execution complete.")
    print(f"  Status: {final_state.status}")
    print(f"  Exit code: {final_state.exit_code}")
    print(f"  Retries: {final_state.retries}")
    print(f"  Report: {report_path}")
    
    return final_state

