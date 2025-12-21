"""Execution state for Phase 3 execution loop."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionState:
    task_id: str
    file_path: str
    retries: int = 0
    max_retries: int = 1
    last_stdout: Optional[str] = None
    last_stderr: Optional[str] = None
    exit_code: Optional[int] = None
    status: str = "PENDING"  # PENDING | RUNNING | SUCCESS | FAILED

