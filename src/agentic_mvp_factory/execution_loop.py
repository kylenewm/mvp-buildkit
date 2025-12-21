"""Phase 3 execution loop - standalone, no LangGraph, no Postgres."""

import shlex
import subprocess
from pathlib import Path

from agentic_mvp_factory.execution_state import ExecutionState


REFACTOR_SYSTEM_PROMPT = """You are a senior Python engineer.
Your job is to fix the code so it runs successfully.

Rules:
- Only output the full corrected file.
- Do NOT explain.
- Do NOT refactor.
- Fix only what the error requires."""


def execution_node(state: ExecutionState) -> ExecutionState:
    """
    Run the file at state.file_path using subprocess.
    
    Captures stdout, stderr, and returncode.
    Sets status to SUCCESS if returncode == 0, else FAILED.
    Never retries. Never raises.
    """
    try:
        cmd = shlex.split(f"python {state.file_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        state.last_stdout = result.stdout
        state.last_stderr = result.stderr
        state.exit_code = result.returncode
        
        if result.returncode == 0:
            state.status = "SUCCESS"
        else:
            state.status = "FAILED"
            
    except subprocess.TimeoutExpired:
        state.last_stderr = "Execution timed out after 60 seconds"
        state.exit_code = -1
        state.status = "FAILED"
    except Exception as e:
        state.last_stderr = str(e)
        state.exit_code = -1
        state.status = "FAILED"
    
    return state


def refactor_node(state: ExecutionState, model_client) -> ExecutionState:
    """
    Attempt to fix the code using the model client.
    
    Only runs if state.status == FAILED and state.retries < state.max_retries.
    Overwrites the file at state.file_path with the corrected code.
    Increments state.retries.
    Does NOT re-execute.
    """
    if state.status != "FAILED":
        return state
    
    if state.retries >= state.max_retries:
        return state
    
    # Read current file contents
    file_path = Path(state.file_path)
    current_contents = file_path.read_text()
    
    # Build the user prompt
    user_prompt = f"""CODE:
{current_contents}

ERROR:
{state.last_stderr}"""
    
    # Call the model
    from agentic_mvp_factory.model_client import Message
    from agentic_mvp_factory.constants import DEFAULT_CHAIR_MODEL
    
    messages = [
        Message(role="system", content=REFACTOR_SYSTEM_PROMPT),
        Message(role="user", content=user_prompt),
    ]
    
    result = model_client.complete(messages=messages, model=DEFAULT_CHAIR_MODEL)
    
    # Extract code from response (strip markdown fences if present)
    fixed_code = result.content
    if fixed_code.startswith("```python"):
        fixed_code = fixed_code[9:]
    if fixed_code.startswith("```"):
        fixed_code = fixed_code[3:]
    if fixed_code.endswith("```"):
        fixed_code = fixed_code[:-3]
    fixed_code = fixed_code.strip()
    
    # Overwrite the file
    file_path.write_text(fixed_code)
    
    # Increment retries
    state.retries += 1
    
    return state


def run_execution_loop(state: ExecutionState, model_client) -> ExecutionState:
    """
    Main execution loop.
    
    Logic:
    1. Set status to RUNNING
    2. Call execution_node
    3. If SUCCESS → return
    4. If FAILED and retries available:
       - Call refactor_node
       - Call execution_node one final time
    5. Return final state
    
    No loops. No recursion. Exactly one retry maximum.
    """
    # Set status to RUNNING
    state.status = "RUNNING"
    
    # First execution attempt
    state = execution_node(state)
    
    # If success, we're done
    if state.status == "SUCCESS":
        return state
    
    # If failed and retries available, try refactor + re-execute
    if state.status == "FAILED" and state.retries < state.max_retries:
        state = refactor_node(state, model_client)
        state = execution_node(state)
    
    return state

