"""CLI entrypoint for the council runner."""

import os
from pathlib import Path
from uuid import UUID

import click
from dotenv import load_dotenv

from agentic_mvp_factory.config import ConfigError, load_config

# Load .env file on CLI startup
load_dotenv()


@click.group()
@click.version_option(package_name="agentic-mvp-factory")
def cli():
    """Council CLI - Multi-model debate with HITL approval."""
    pass


@cli.command()
@click.option(
    "--repo",
    required=True,
    type=click.Path(),
    help="Path to the target repository to initialize.",
)
def init(repo: str):
    """Initialize a new project repository with the expected folder structure."""
    repo_path = Path(repo).resolve()
    
    # Define the folders to create (from spec.yaml repo_outputs_v0)
    folders = [
        "spec",
        "tracker",
        "invariants",
        "prompts",
        ".cursor/rules",
        "docs",
        "versions",
    ]
    
    click.echo(f"Initializing council project at: {repo_path}")
    
    # Create the repo root if it doesn't exist
    repo_path.mkdir(parents=True, exist_ok=True)
    
    # Create each folder
    for folder in folders:
        folder_path = repo_path / folder
        folder_path.mkdir(parents=True, exist_ok=True)
        click.echo(f"  Created: {folder}/")
    
    click.echo(f"\nProject initialized successfully at {repo_path}")
    click.echo("Next steps:")
    click.echo("  1. Set DATABASE_URL and OPENROUTER_API_KEY in your environment")
    click.echo("  2. Run 'council run plan --help' to see available options")


@cli.command()
def check_config():
    """Check if required environment variables are configured."""
    try:
        config = load_config(require_all=True)
        click.echo("Configuration loaded successfully!")
        click.echo(f"  DATABASE_URL: {config.database_url[:20]}..." if len(config.database_url) > 20 else f"  DATABASE_URL: [set]")
        click.echo("  OPENROUTER_API_KEY: [set]")
    except ConfigError as e:
        click.echo(f"Configuration error:\n{e}", err=True)
        raise SystemExit(1)


# Database commands (S02)
@cli.group()
def db():
    """Database commands."""
    pass


@db.command("init")
def db_init():
    """Initialize the database schema."""
    from agentic_mvp_factory.db import init_schema
    
    try:
        init_schema()
        click.echo("Database schema initialized successfully.")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Database error: {e}", err=True)
        raise SystemExit(1)


@db.command("smoke-test")
@click.option("--project", default="smoke-test", help="Project slug for the test run")
def db_smoke_test(project: str):
    """Smoke test: create a run and write a packet artifact."""
    from agentic_mvp_factory.repo import create_run, write_artifact, get_run, get_artifacts
    
    try:
        # Create a run
        run = create_run(project_slug=project, task_type="plan")
        click.echo(f"Created run: {run.id}")
        click.echo(f"  project_slug: {run.project_slug}")
        click.echo(f"  status: {run.status}")
        click.echo(f"  created_at: {run.created_at}")
        
        # Write a packet artifact
        artifact = write_artifact(
            run_id=run.id,
            kind="packet",
            content="# Test Packet\n\nThis is a test packet artifact.",
            model=None,
        )
        click.echo(f"\nCreated artifact: {artifact.id}")
        click.echo(f"  kind: {artifact.kind}")
        click.echo(f"  run_id: {artifact.run_id}")
        
        # Verify by reading back
        retrieved_run = get_run(run.id)
        artifacts = get_artifacts(run.id)
        
        click.echo(f"\nVerification:")
        click.echo(f"  Run retrieved: {retrieved_run is not None}")
        click.echo(f"  Artifacts count: {len(artifacts)}")
        
        click.echo("\nDatabase test passed!")
        
    except Exception as e:
        click.echo(f"Database error: {e}", err=True)
        raise SystemExit(1)


@cli.group()
def run():
    """Run council workflows."""
    pass


@run.command("plan")
@click.option(
    "--project",
    required=True,
    help="Project slug for namespace isolation",
)
@click.option(
    "--packet",
    required=True,
    type=click.Path(exists=True),
    help="Path to the planning packet file",
)
@click.option(
    "--models",
    required=True,
    help="Comma-separated list of model IDs for drafts/critiques",
)
@click.option(
    "--chair",
    required=True,
    help="Model ID for chair synthesis",
)
def run_plan(project: str, packet: str, models: str, chair: str):
    """Run a council planning workflow."""
    import os
    
    # Check required env vars
    if not os.environ.get("DATABASE_URL"):
        click.echo("Error: DATABASE_URL environment variable is required.", err=True)
        raise SystemExit(1)
    if not os.environ.get("OPENROUTER_API_KEY"):
        click.echo("Error: OPENROUTER_API_KEY environment variable is required.", err=True)
        raise SystemExit(1)
    
    # Parse models
    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if len(model_list) < 2:
        click.echo("Error: At least 2 models are required.", err=True)
        raise SystemExit(1)
    
    click.echo(f"Running council plan workflow")
    click.echo(f"  Project: {project}")
    click.echo(f"  Packet: {packet}")
    click.echo(f"  Models: {model_list}")
    click.echo(f"  Chair: {chair}")
    click.echo()
    
    try:
        from agentic_mvp_factory.graph import run_council
        
        click.echo("Starting workflow...")
        click.echo(f"  [1/4] Loading packet...")
        click.echo(f"  [2/4] Generating {len(model_list)} drafts in parallel...")
        click.echo(f"  [3/4] Generating {len(model_list)} critiques in parallel...")
        click.echo(f"  [4/4] Chair synthesis...")
        
        run_id, failed_models = run_council(
            project_slug=project,
            packet_path=packet,
            models=model_list,
            chair_model=chair,
        )
        
        click.echo()
        click.echo(f"Workflow complete!")
        click.echo(f"  Run ID: {run_id}")
        
        if failed_models:
            click.echo(f"  Failed models: {failed_models}", err=True)
        
        # Show artifact counts
        from uuid import UUID as UUIDType
        from agentic_mvp_factory.repo import get_artifacts
        run_uuid = UUIDType(run_id)
        drafts = get_artifacts(run_uuid, kind="draft")
        critiques = get_artifacts(run_uuid, kind="critique")
        errors = get_artifacts(run_uuid, kind="error")
        
        click.echo()
        click.echo(f"Artifacts created:")
        click.echo(f"  Drafts: {len(drafts)}")
        click.echo(f"  Critiques: {len(critiques)}")
        if errors:
            click.echo(f"  Errors: {len(errors)}")
        
        click.echo()
        click.echo(f"To view results:")
        click.echo(f"  council show {run_id} --section synthesis")
        click.echo(f"  council show {run_id} --section all")
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


# Model commands (S03)
@cli.group()
def model():
    """Model client commands."""
    pass


@model.command("test")
@click.option(
    "--model", "model_id",
    default="openai/gpt-4o-mini",
    help="Model identifier (e.g., openai/gpt-4o-mini, anthropic/claude-sonnet-4.5, google/gemini-2.5-flash-lite)",
)
@click.option(
    "--timeout",
    default=30.0,
    help="Request timeout in seconds",
)
@click.option(
    "--project",
    default="model-test",
    help="Project slug for the test run",
)
def model_test(model_id: str, timeout: float, project: str):
    """Test model client by making a single API call and storing the result."""
    from agentic_mvp_factory.model_client import (
        Message,
        ModelClientError,
        get_openrouter_client,
    )
    from agentic_mvp_factory.repo import create_run, write_artifact
    
    click.echo(f"Testing model: {model_id}")
    click.echo(f"Timeout: {timeout}s")
    
    # Check required env vars
    import os
    if not os.environ.get("DATABASE_URL"):
        click.echo("Error: DATABASE_URL environment variable is required.", err=True)
        raise SystemExit(1)
    if not os.environ.get("OPENROUTER_API_KEY"):
        click.echo("Error: OPENROUTER_API_KEY environment variable is required.", err=True)
        raise SystemExit(1)
    
    try:
        # Create a run for this test
        run = create_run(project_slug=project, task_type="model_test")
        click.echo(f"\nCreated run: {run.id}")
        
        # Initialize client and make call
        client = get_openrouter_client()
        
        # Hardcoded test prompt
        messages = [
            Message(
                role="system",
                content="You are a helpful assistant. Respond concisely.",
            ),
            Message(
                role="user",
                content="Say 'Hello from Council CLI!' and nothing else.",
            ),
        ]
        
        click.echo(f"Calling OpenRouter API...")
        result = client.complete(messages=messages, model=model_id, timeout=timeout)
        
        click.echo(f"\nResponse received:")
        click.echo(f"  Model: {result.model}")
        click.echo(f"  Content: {result.content[:100]}{'...' if len(result.content) > 100 else ''}")
        
        if result.usage:
            click.echo(f"  Usage: {result.usage}")
        
        # Store as artifact
        artifact = write_artifact(
            run_id=run.id,
            kind="model_test",
            content=result.content,
            model=result.model,
            usage_json=result.usage,
        )
        
        click.echo(f"\nStored artifact: {artifact.id}")
        click.echo(f"  kind: {artifact.kind}")
        click.echo(f"  model: {artifact.model}")
        click.echo(f"  usage_json: {artifact.usage_json is not None}")
        
        click.echo("\nModel test passed!")
        
    except ModelClientError as e:
        click.echo(f"Model client error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.option(
    "--project",
    default=None,
    help="Filter by project slug",
)
@click.option(
    "--status", "status_filter",
    default=None,
    type=click.Choice([
        "created", "drafting", "critiquing", "synthesizing",
        "waiting_for_approval", "ready_to_commit", "committing",
        "completed", "failed", "validation_failed"
    ]),
    help="Filter by status",
)
@click.option(
    "--limit",
    default=20,
    help="Maximum number of runs to show",
)
def status(project: str, status_filter: str, limit: int):
    """Show status of runs."""
    from agentic_mvp_factory.repo import list_runs
    
    runs = list_runs(project_slug=project, status=status_filter, limit=limit)
    
    if not runs:
        click.echo("No runs found.")
        if project:
            click.echo(f"  (filtered by project: {project})")
        if status_filter:
            click.echo(f"  (filtered by status: {status_filter})")
        return
    
    # Header
    click.echo(f"{'RUN ID':<38} {'PROJECT':<15} {'STATUS':<20} {'CREATED':<20}")
    click.echo("-" * 95)
    
    for run in runs:
        # Format timestamp
        created_str = run.created_at.strftime("%Y-%m-%d %H:%M") if run.created_at else "N/A"
        
        # Truncate project slug if too long
        project_display = run.project_slug[:14] if len(run.project_slug) > 14 else run.project_slug
        
        # Color-code status for readability
        status_display = run.status
        if run.status == "waiting_for_approval":
            status_display = "⏳ waiting_approval"
        elif run.status == "completed":
            status_display = "✓ completed"
        elif run.status == "failed":
            status_display = "✗ failed"
        elif run.status == "validation_failed":
            status_display = "✗ validation_failed"
        elif run.status == "ready_to_commit":
            status_display = "→ ready_to_commit"
        
        click.echo(f"{str(run.id):<38} {project_display:<15} {status_display:<20} {created_str:<20}")
    
    click.echo()
    click.echo(f"Showing {len(runs)} run(s)")
    if project:
        click.echo(f"  Filtered by project: {project}")
    if status_filter:
        click.echo(f"  Filtered by status: {status_filter}")


@cli.command()
@click.argument("run_id")
@click.option(
    "--section",
    type=click.Choice(["summary", "all", "packet", "drafts", "critiques", "synthesis", "decision", "errors", "status", "commit"]),
    default="summary",
    help="Which section to display (default: summary)",
)
@click.option(
    "--open", "open_file",
    is_flag=True,
    help="Write output to temp file and print path",
)
@click.option(
    "--full",
    is_flag=True,
    help="Show full content without truncation",
)
def show(run_id: str, section: str, open_file: bool, full: bool):
    """Show details of a specific run."""
    import tempfile
    from uuid import UUID as UUIDType
    from agentic_mvp_factory.repo import get_run, get_artifacts
    
    try:
        run_uuid = UUIDType(run_id)
    except ValueError:
        click.echo(f"Error: Invalid run ID format: {run_id}", err=True)
        raise SystemExit(1)
    
    run = get_run(run_uuid)
    if not run:
        click.echo(f"Error: Run not found: {run_id}", err=True)
        raise SystemExit(1)
    
    # Collect output lines
    output_lines = []
    
    def add_line(text=""):
        output_lines.append(text)
    
    # Run header
    add_line(f"Run: {run.id}")
    add_line(f"  Project: {run.project_slug}")
    add_line(f"  Status: {run.status}")
    add_line(f"  Created: {run.created_at}")
    if run.parent_run_id:
        add_line(f"  Parent: {run.parent_run_id}")
    add_line()
    
    # Handle summary section (default)
    if section == "summary":
        # Get artifact counts
        all_kinds = ["packet", "draft", "critique", "synthesis", "decision_packet", "error", "commit_log"]
        add_line("=== ARTIFACT SUMMARY ===")
        for kind in all_kinds:
            artifacts = get_artifacts(run_uuid, kind=kind)
            if artifacts:
                add_line(f"  {kind}: {len(artifacts)}")
        add_line()
        
        # Show next action hint based on status
        add_line("=== NEXT ACTION ===")
        if run.status == "waiting_for_approval":
            add_line(f"  Run: council approve {run_id} --approve")
            add_line(f"  Or:  council approve {run_id} --edit")
            add_line(f"  Or:  council approve {run_id} --reject")
        elif run.status == "ready_to_commit":
            add_line(f"  Run: council commit {run_id} --repo <path>")
        elif run.status == "completed":
            add_line("  ✓ Run completed. View with: council show {run_id} --section all")
        elif run.status in ("failed", "validation_failed"):
            add_line(f"  ✗ Run failed. View errors: council show {run_id} --section errors")
        else:
            add_line(f"  Status: {run.status} (in progress)")
        add_line()
        
        # Show synthesis preview if available
        synthesis_artifacts = get_artifacts(run_uuid, kind="synthesis")
        if synthesis_artifacts:
            add_line("=== SYNTHESIS PREVIEW ===")
            content = synthesis_artifacts[0].content
            preview = content[:500] if len(content) > 500 else content
            add_line(preview)
            if len(content) > 500:
                add_line(f"\n... ({len(content)} chars total, use --section synthesis for full)")
            add_line()
        
        _output_result(output_lines, open_file, run_id, section)
        return
    
    # Handle status-only section
    if section == "status":
        add_line(f"=== STATUS ===")
        add_line(f"Status: {run.status}")
        add_line(f"Updated: {run.updated_at}")
        _output_result(output_lines, open_file, run_id, section)
        return
    
    # Map section to artifact kind
    section_to_kind = {
        "packet": "packet",
        "drafts": "draft",
        "critiques": "critique",
        "synthesis": "synthesis",
        "decision": "decision_packet",
        "errors": "error",
        "commit": "commit_log",
    }
    
    if section == "all":
        kinds = ["packet", "draft", "critique", "synthesis", "decision_packet", "error", "commit_log"]
    else:
        kinds = [section_to_kind[section]]
    
    # Truncation limit
    max_content = 2000 if (section == "all" and not full) else None
    
    for kind in kinds:
        artifacts = get_artifacts(run_uuid, kind=kind)
        if not artifacts:
            continue
        
        add_line(f"=== {kind.upper()} ({len(artifacts)}) ===")
        for i, artifact in enumerate(artifacts, 1):
            add_line(f"\n--- {kind} {i} ---")
            if artifact.model:
                add_line(f"Model: {artifact.model}")
            add_line(f"Created: {artifact.created_at}")
            if artifact.usage_json:
                add_line(f"Usage: {artifact.usage_json}")
            add_line()
            
            # Handle content truncation
            content = artifact.content
            if max_content and len(content) > max_content:
                add_line(content[:max_content])
                add_line(f"\n... (truncated, {len(content)} chars total, use --full to see all)")
            else:
                add_line(content)
        add_line()
    
    _output_result(output_lines, open_file, run_id, section)


def _output_result(lines: list, open_file: bool, run_id: str, section: str):
    """Output lines to stdout or temp file."""
    import tempfile
    
    output = "\n".join(lines)
    
    if open_file:
        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=f"_{section}.md",
            prefix=f"council_{run_id[:8]}_",
            delete=False,
        ) as f:
            f.write(output)
            temp_path = f.name
        click.echo(f"Output written to: {temp_path}")
        click.echo(f"  Open with: cat {temp_path}")
        click.echo(f"  Or: $EDITOR {temp_path}")
    else:
        click.echo(output)


@cli.command()
@click.argument("run_id")
@click.option("--approve", "action", flag_value="approve", help="Approve the run as-is")
@click.option("--reject", "action", flag_value="reject", help="Reject and create new run with feedback")
@click.option("--edit", "action", flag_value="edit", help="Edit synthesis in $EDITOR then approve")
def approve(run_id: str, action: str):
    """Approve, edit, or reject a run waiting for approval."""
    import os
    import subprocess
    import tempfile
    from uuid import UUID as UUIDType
    from agentic_mvp_factory.repo import (
        get_run, get_artifacts, create_approval, update_run_status,
        create_run, write_artifact,
    )
    
    if not action:
        click.echo("Error: Must specify one of --approve, --reject, or --edit", err=True)
        raise SystemExit(1)
    
    try:
        run_uuid = UUIDType(run_id)
    except ValueError:
        click.echo(f"Error: Invalid run ID format: {run_id}", err=True)
        raise SystemExit(1)
    
    run = get_run(run_uuid)
    if not run:
        click.echo(f"Error: Run not found: {run_id}", err=True)
        raise SystemExit(1)
    
    if run.status != "waiting_for_approval":
        click.echo(f"Error: Run is not waiting for approval (status: {run.status})", err=True)
        raise SystemExit(1)
    
    # Get synthesis for display/editing
    synthesis_artifacts = get_artifacts(run_uuid, kind="synthesis")
    if not synthesis_artifacts:
        click.echo("Error: No synthesis found for this run", err=True)
        raise SystemExit(1)
    
    synthesis = synthesis_artifacts[0]
    
    if action == "approve":
        # Simple approve
        create_approval(run_id=run_uuid, decision="approve")
        
        # Run validation before setting final status (S07)
        from agentic_mvp_factory.validator import validate_run_outputs
        
        click.echo(f"Validating outputs...")
        validation = validate_run_outputs(run_uuid)
        
        if not validation.is_valid:
            # Validation failed - store error artifact and set status
            write_artifact(
                run_id=run_uuid,
                kind="error",
                content=f"Validation failed:\n{validation.details}\n\nFailed artifacts: {', '.join(validation.failed_artifacts)}",
                model=None,
            )
            update_run_status(run_uuid, "validation_failed")
            
            click.echo(f"VALIDATION_FAILED")
            click.echo(f"  Details: {validation.details}")
            click.echo(f"  Failed: {', '.join(validation.failed_artifacts)}")
            click.echo(f"\nView error: council show {run_id} --section errors")
            raise SystemExit(1)
        
        # Validation passed
        update_run_status(run_uuid, "ready_to_commit")
        
        click.echo(f"READY_TO_COMMIT")
        click.echo(f"Run {run_id} approved and validated!")
        click.echo(f"\nNext: Run 'council commit {run_id} --repo <path>' to write outputs (S08)")
    
    elif action == "edit":
        # Open $EDITOR with synthesis content
        editor = os.environ.get("EDITOR", "nano")
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(synthesis.content)
            temp_path = f.name
        
        click.echo(f"Opening synthesis in {editor}...")
        click.echo("Save and close to approve with edits. Delete all content to cancel.")
        
        try:
            subprocess.run([editor, temp_path], check=True)
            
            with open(temp_path, "r") as f:
                edited_content = f.read()
            
            os.unlink(temp_path)
            
            if not edited_content.strip():
                click.echo("Edit cancelled (empty content).")
                raise SystemExit(0)
            
            # Store edited synthesis as new artifact
            write_artifact(
                run_id=run_uuid,
                kind="synthesis_edited",
                content=edited_content,
                model=None,
            )
            
            create_approval(run_id=run_uuid, decision="edit_approve", edited_content=edited_content)
            
            # Run validation before setting final status (S07)
            from agentic_mvp_factory.validator import validate_run_outputs
            
            click.echo(f"Validating outputs...")
            validation = validate_run_outputs(run_uuid)
            
            if not validation.is_valid:
                # Validation failed - store error artifact and set status
                write_artifact(
                    run_id=run_uuid,
                    kind="error",
                    content=f"Validation failed:\n{validation.details}\n\nFailed artifacts: {', '.join(validation.failed_artifacts)}",
                    model=None,
                )
                update_run_status(run_uuid, "validation_failed")
                
                click.echo(f"VALIDATION_FAILED")
                click.echo(f"  Details: {validation.details}")
                click.echo(f"  Failed: {', '.join(validation.failed_artifacts)}")
                click.echo(f"\nView error: council show {run_id} --section errors")
                raise SystemExit(1)
            
            # Validation passed
            update_run_status(run_uuid, "ready_to_commit")
            
            click.echo(f"\nREADY_TO_COMMIT")
            click.echo(f"Run {run_id} approved with edits and validated!")
            click.echo(f"\nNext: Run 'council commit {run_id} --repo <path>' to write outputs (S08)")
            
        except subprocess.CalledProcessError:
            click.echo("Editor exited with error. Approval cancelled.", err=True)
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise SystemExit(1)
    
    elif action == "reject":
        # Prompt for feedback
        click.echo("Enter rejection feedback (why is this being rejected?):")
        click.echo("(Press Ctrl+D or Ctrl+Z when done)")
        
        try:
            feedback_lines = []
            while True:
                try:
                    line = input()
                    feedback_lines.append(line)
                except EOFError:
                    break
            feedback = "\n".join(feedback_lines)
        except KeyboardInterrupt:
            click.echo("\nRejection cancelled.")
            raise SystemExit(0)
        
        if not feedback.strip():
            click.echo("Error: Feedback is required for rejection", err=True)
            raise SystemExit(1)
        
        # Create approval record for the rejected run
        create_approval(run_id=run_uuid, decision="reject", feedback=feedback)
        update_run_status(run_uuid, "failed")
        
        # Create new run with parent link
        new_run = create_run(
            project_slug=run.project_slug,
            task_type=run.task_type,
            parent_run_id=run_uuid,
        )
        
        # Copy packet from parent run and append feedback
        packet_artifacts = get_artifacts(run_uuid, kind="packet")
        if packet_artifacts:
            original_packet = packet_artifacts[0].content
            augmented_packet = f"{original_packet}\n\n---\n\n## Human Feedback (from rejected run {run_id})\n\n{feedback}"
            
            write_artifact(
                run_id=new_run.id,
                kind="packet",
                content=augmented_packet,
                model=None,
            )
        
        click.echo(f"\nRun {run_id} rejected.")
        click.echo(f"New run created: {new_run.id}")
        click.echo(f"  Parent: {run_id}")
        click.echo(f"  Feedback appended to packet")
        click.echo(f"\nTo rerun with same models, use:")
        click.echo(f"  council run plan --project {run.project_slug} --packet <path> --models <...> --chair <...>")


@cli.command()
@click.argument("run_id")
@click.option(
    "--repo",
    required=True,
    type=click.Path(),
    help="Target repository path to write outputs to",
)
def commit(run_id: str, repo: str):
    """Commit approved run outputs to a target repository."""
    from pathlib import Path
    from uuid import UUID as UUIDType
    from agentic_mvp_factory.repo_writer import commit_outputs
    
    try:
        run_uuid = UUIDType(run_id)
    except ValueError:
        click.echo(f"Error: Invalid run ID format: {run_id}", err=True)
        raise SystemExit(1)
    
    repo_path = Path(repo).resolve()
    
    click.echo(f"Committing run {run_id} to {repo_path}")
    click.echo()
    
    try:
        manifest = commit_outputs(run_uuid, repo_path)
        
        click.echo(f"Commit successful!")
        click.echo()
        click.echo(f"Files written: {len(manifest.stable_paths_written)}")
        for path in manifest.stable_paths_written:
            click.echo(f"  - {path}")
        click.echo()
        click.echo(f"Snapshot: {manifest.snapshot_path}")
        click.echo(f"Manifest: COMMIT_MANIFEST.md")
        click.echo()
        click.echo(f"View with: tree {repo_path} -L 3")
        
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise SystemExit(1)


# Phase 3A: Step extraction
@cli.command()
@click.argument("run_id")
@click.option(
    "--slug",
    default="extracted",
    help="Slug for the output filename (e.g., 'step_extractor' -> S01_step_extractor.md)",
)
@click.option(
    "--execution-dir",
    type=click.Path(),
    default="execution",
    help="Path to execution directory (default: ./execution)",
)
def extract(run_id: str, slug: str, execution_dir: str):
    """Extract an execution step document from an approved run.
    
    Exit codes:
      0 = success
      1 = run not found or no synthesis
      2 = run not approved
    """
    from pathlib import Path
    from uuid import UUID as UUIDType
    from agentic_mvp_factory.step_extractor import (
        extract_step_from_run,
        RunNotFoundError,
        RunNotApprovedError,
        NoSynthesisError,
    )
    
    try:
        run_uuid = UUIDType(run_id)
    except ValueError:
        click.echo(f"Error: Invalid run ID format: {run_id}", err=True)
        raise SystemExit(1)
    
    exec_path = Path(execution_dir).resolve()
    
    try:
        output_path = extract_step_from_run(
            run_id=run_uuid,
            execution_dir=exec_path,
            output_slug=slug,
        )
        
        click.echo(f"Step document created: {output_path}")
        click.echo()
        click.echo("Next steps:")
        click.echo(f"  1. Edit the step document to refine scope and instructions")
        click.echo(f"  2. Have Cursor implement the step")
        click.echo(f"  3. Run proof commands and record delta")
        click.echo()
        click.echo(f"Open with: $EDITOR {output_path}")
        
    except RunNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except NoSynthesisError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except RunNotApprovedError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise SystemExit(1)


# Phase 3: Step runner and review
@cli.command("exec")
@click.argument("step_file", type=click.Path(exists=True))
@click.option(
    "--output-dir",
    type=click.Path(),
    default="execution/reports",
    help="Directory for execution reports (default: execution/reports)",
)
@click.option(
    "--no-trace",
    is_flag=True,
    help="Disable LangGraph tracing (run without graph wrapper)",
)
def exec_step(step_file: str, output_dir: str, no_trace: bool):
    """Execute a single step definition file.
    
    STEP_FILE: Path to step definition (YAML or JSON)
    
    By default, uses LangGraph for tracing visibility in Studio.
    Use --no-trace to run without the graph wrapper.
    
    Step definition format:
    
    \b
        task_id: my-task-001
        file_path: path/to/script.py
        max_retries: 1  # optional
    """
    from pathlib import Path
    from agentic_mvp_factory.step_runner import run_step
    
    step_path = Path(step_file).resolve()
    out_path = Path(output_dir).resolve()
    
    click.echo(f"Executing step: {step_path}")
    if not no_trace:
        click.echo(f"  (LangGraph tracing enabled)")
    click.echo()
    
    try:
        final_state = run_step(step_path, out_path, use_graph=not no_trace)
        
        if final_state.status == "SUCCESS":
            raise SystemExit(0)
        else:
            raise SystemExit(1)
            
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise SystemExit(1)


@cli.command("review")
@click.argument("report_file", type=click.Path(exists=True))
@click.option(
    "--delta-dir",
    type=click.Path(),
    default="execution/deltas",
    help="Directory for delta files (default: execution/deltas)",
)
def review_step(report_file: str, delta_dir: str):
    """Review an execution report and record decision.
    
    REPORT_FILE: Path to execution report JSON
    
    Shows a review template, prompts for ACCEPT/REJECT,
    and writes a delta JSON file on ACCEPT.
    """
    from pathlib import Path
    from agentic_mvp_factory.review_flow import run_review
    
    report_path = Path(report_file).resolve()
    delta_path = Path(delta_dir).resolve()
    
    try:
        decision, _ = run_review(report_path, delta_path)
        
        if decision == "ACCEPT":
            raise SystemExit(0)
        else:
            raise SystemExit(1)
            
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except KeyboardInterrupt:
        click.echo("\nReview cancelled.")
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise SystemExit(1)


@cli.command("observe")
@click.argument("task_id")
@click.option(
    "--reports-dir",
    type=click.Path(),
    default="execution/reports",
    help="Directory for execution reports",
)
@click.option(
    "--deltas-dir",
    type=click.Path(),
    default="execution/deltas",
    help="Directory for delta files",
)
def observe_task(task_id: str, reports_dir: str, deltas_dir: str):
    """Show a summary of a task's execution history.
    
    TASK_ID: The task identifier to observe
    
    Read-only. Displays execution reports and review decisions.
    """
    from pathlib import Path
    from agentic_mvp_factory.observe import print_summary
    
    print_summary(
        task_id=task_id,
        reports_dir=Path(reports_dir),
        deltas_dir=Path(deltas_dir),
    )


if __name__ == "__main__":
    cli()

