#!/usr/bin/env python3
"""Proof script for Phase 3 execution loop."""

import os
import tempfile
from pathlib import Path

# Ensure .env is loaded
from dotenv import load_dotenv
load_dotenv()

from agentic_mvp_factory.execution_state import ExecutionState
from agentic_mvp_factory.execution_loop import run_execution_loop
from agentic_mvp_factory.model_client import get_openrouter_client


def main():
    # Check for API key
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY not set")
        return
    
    # Create a temp file with a syntax error (missing parenthesis)
    broken_code = '''# Broken Python file
def greet(name):
    print("Hello, " + name  # Missing closing parenthesis

greet("World")
'''
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        prefix="execution_test_"
    ) as f:
        f.write(broken_code)
        temp_path = f.name
    
    print(f"Created broken file: {temp_path}")
    print(f"\n=== ORIGINAL CODE ===")
    print(broken_code)
    
    # Create execution state
    state = ExecutionState(
        task_id="proof-001",
        file_path=temp_path,
    )
    
    print(f"\n=== INITIAL STATE ===")
    print(f"  task_id: {state.task_id}")
    print(f"  file_path: {state.file_path}")
    print(f"  status: {state.status}")
    print(f"  retries: {state.retries}")
    
    # Get model client
    client = get_openrouter_client()
    
    print(f"\n=== RUNNING EXECUTION LOOP ===")
    
    # Run the loop
    final_state = run_execution_loop(state, client)
    
    print(f"\n=== FINAL STATE ===")
    print(f"  task_id: {final_state.task_id}")
    print(f"  status: {final_state.status}")
    print(f"  exit_code: {final_state.exit_code}")
    print(f"  retries: {final_state.retries}")
    print(f"  last_stdout: {final_state.last_stdout}")
    print(f"  last_stderr: {final_state.last_stderr[:200] if final_state.last_stderr else None}")
    
    # Show fixed code if successful
    if final_state.status == "SUCCESS":
        print(f"\n=== FIXED CODE ===")
        print(Path(temp_path).read_text())
    
    # Cleanup
    os.unlink(temp_path)
    print(f"\nCleaned up temp file.")
    
    # Final verdict
    print(f"\n{'='*40}")
    if final_state.status == "SUCCESS" and final_state.retries == 1:
        print("PROOF PASSED: Syntax error fixed in one retry.")
    elif final_state.status == "SUCCESS":
        print("PROOF PARTIAL: Succeeded but retries != 1")
    else:
        print(f"PROOF FAILED: Final status = {final_state.status}")


if __name__ == "__main__":
    main()

