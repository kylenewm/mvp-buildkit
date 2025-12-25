"""Repository layer for runs and artifacts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from agentic_mvp_factory.db import get_cursor


@dataclass
class Run:
    """A council run."""
    id: UUID
    project_slug: str
    task_type: str
    status: str
    parent_run_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime


@dataclass
class Artifact:
    """An artifact produced during a run."""
    id: UUID
    run_id: UUID
    kind: str
    model: Optional[str]
    content: str
    usage_json: Optional[Dict[str, Any]]
    created_at: datetime


def create_run(
    project_slug: str,
    task_type: str = "plan",
    parent_run_id: Optional[UUID] = None,
) -> Run:
    """
    Create a new run and return it.
    
    Args:
        project_slug: Project namespace (required for I4 isolation)
        task_type: Type of task (default: "plan")
        parent_run_id: Optional parent run for reruns
    
    Returns:
        The created Run object
    """
    # Convert UUID to string for psycopg2
    parent_id_str = str(parent_run_id) if parent_run_id else None
    
    with get_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO runs (project_slug, task_type, parent_run_id)
            VALUES (%s, %s, %s)
            RETURNING id, project_slug, task_type, status, parent_run_id, created_at, updated_at
            """,
            (project_slug, task_type, parent_id_str),
        )
        row = cursor.fetchone()
    
    return Run(
        id=row["id"],
        project_slug=row["project_slug"],
        task_type=row["task_type"],
        status=row["status"],
        parent_run_id=row["parent_run_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def write_artifact(
    run_id: UUID,
    kind: str,
    content: str,
    model: Optional[str] = None,
    usage_json: Optional[Dict[str, Any]] = None,
) -> Artifact:
    """
    Write an artifact for a run.
    
    Args:
        run_id: The run this artifact belongs to
        kind: Artifact kind (packet, draft, critique, synthesis, etc.)
        content: The artifact content
        model: Optional model identifier
        usage_json: Optional usage metadata (tokens, cost)
    
    Returns:
        The created Artifact object
    """
    import json
    
    # Convert UUID to string for psycopg2
    run_id_str = str(run_id)
    
    with get_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO artifacts (run_id, kind, model, content, usage_json)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, run_id, kind, model, content, usage_json, created_at
            """,
            (
                run_id_str,
                kind,
                model,
                content,
                json.dumps(usage_json) if usage_json else None,
            ),
        )
        row = cursor.fetchone()
    
    return Artifact(
        id=row["id"],
        run_id=row["run_id"],
        kind=row["kind"],
        model=row["model"],
        content=row["content"],
        usage_json=row["usage_json"],
        created_at=row["created_at"],
    )


def list_runs(
    project_slug: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Run]:
    """
    List runs with optional filters.
    
    Args:
        project_slug: Filter by project
        status: Filter by status
        limit: Maximum number of runs to return
    
    Returns:
        List of Run objects
    """
    conditions = []
    params = []
    
    if project_slug:
        conditions.append("project_slug = %s")
        params.append(project_slug)
    
    if status:
        conditions.append("status = %s")
        params.append(status)
    
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    params.append(limit)
    
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            f"""
            SELECT id, project_slug, task_type, status, parent_run_id, created_at, updated_at
            FROM runs
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cursor.fetchall()
    
    return [
        Run(
            id=row["id"],
            project_slug=row["project_slug"],
            task_type=row["task_type"],
            status=row["status"],
            parent_run_id=row["parent_run_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def get_run(run_id: UUID) -> Optional[Run]:
    """Get a run by ID."""
    # Convert UUID to string for psycopg2
    run_id_str = str(run_id)
    
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT id, project_slug, task_type, status, parent_run_id, created_at, updated_at
            FROM runs
            WHERE id = %s
            """,
            (run_id_str,),
        )
        row = cursor.fetchone()
    
    if not row:
        return None
    
    return Run(
        id=row["id"],
        project_slug=row["project_slug"],
        task_type=row["task_type"],
        status=row["status"],
        parent_run_id=row["parent_run_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_artifacts(run_id: UUID, kind: Optional[str] = None) -> List[Artifact]:
    """Get artifacts for a run, optionally filtered by kind."""
    # Convert UUID to string for psycopg2
    run_id_str = str(run_id)
    
    conditions = ["run_id = %s"]
    params = [run_id_str]
    
    if kind:
        conditions.append("kind = %s")
        params.append(kind)
    
    where_clause = " AND ".join(conditions)
    
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            f"""
            SELECT id, run_id, kind, model, content, usage_json, created_at
            FROM artifacts
            WHERE {where_clause}
            ORDER BY created_at ASC
            """,
            params,
        )
        rows = cursor.fetchall()
    
    return [
        Artifact(
            id=row["id"],
            run_id=row["run_id"],
            kind=row["kind"],
            model=row["model"],
            content=row["content"],
            usage_json=row["usage_json"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@dataclass
class Approval:
    """An approval decision for a run."""
    id: UUID
    run_id: UUID
    decision: str  # approve, edit_approve, reject
    edited_content: Optional[str]
    feedback: Optional[str]
    created_at: datetime


def create_approval(
    run_id: UUID,
    decision: str,
    edited_content: Optional[str] = None,
    feedback: Optional[str] = None,
) -> Approval:
    """
    Create an approval record for a run.
    
    Args:
        run_id: The run being approved
        decision: One of "approve", "edit_approve", "reject"
        edited_content: Edited synthesis content (for edit_approve)
        feedback: Human feedback (for reject)
    
    Returns:
        The created Approval object
    """
    run_id_str = str(run_id)
    
    with get_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO approvals (run_id, decision, edited_content, feedback)
            VALUES (%s, %s, %s, %s)
            RETURNING id, run_id, decision, edited_content, feedback, created_at
            """,
            (run_id_str, decision, edited_content, feedback),
        )
        row = cursor.fetchone()
    
    return Approval(
        id=row["id"],
        run_id=row["run_id"],
        decision=row["decision"],
        edited_content=row["edited_content"],
        feedback=row["feedback"],
        created_at=row["created_at"],
    )


def update_run_status(run_id: UUID, status: str) -> None:
    """Update the status of a run."""
    run_id_str = str(run_id)
    
    with get_cursor() as cursor:
        cursor.execute(
            "UPDATE runs SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, run_id_str),
        )


def get_approval(run_id: UUID) -> Optional[Approval]:
    """Get the approval record for a run."""
    run_id_str = str(run_id)
    
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT id, run_id, decision, edited_content, feedback, created_at
            FROM approvals
            WHERE run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (run_id_str,),
        )
        row = cursor.fetchone()
    
    if not row:
        return None
    
    return Approval(
        id=row["id"],
        run_id=row["run_id"],
        decision=row["decision"],
        edited_content=row["edited_content"],
        feedback=row["feedback"],
        created_at=row["created_at"],
    )


def get_latest_approved_run_by_task_type(
    task_type: str,
    parent_run_id: UUID,
) -> Optional[Run]:
    """
    Get the latest approved run for a given task_type and parent_run_id.
    
    An approved run has status IN ('ready_to_commit', 'completed').
    
    Args:
        task_type: The task type (spec, tracker, prompts, cursor_rules, invariants)
        parent_run_id: The parent plan run ID
        
    Returns:
        The latest approved Run or None if not found
    """
    parent_id_str = str(parent_run_id)
    
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            """
            SELECT id, project_slug, task_type, status, parent_run_id, created_at, updated_at
            FROM runs
            WHERE task_type = %s
              AND parent_run_id = %s
              AND status IN ('ready_to_commit', 'completed')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (task_type, parent_id_str),
        )
        row = cursor.fetchone()
    
    if not row:
        return None
    
    return Run(
        id=row["id"],
        project_slug=row["project_slug"],
        task_type=row["task_type"],
        status=row["status"],
        parent_run_id=row["parent_run_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

