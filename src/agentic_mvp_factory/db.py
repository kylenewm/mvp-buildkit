"""Database connection handling for council."""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from agentic_mvp_factory.config import load_config


def get_connection_string() -> str:
    """Get DATABASE_URL from environment.
    
    Checks DATABASE_URL environment variable directly first,
    then falls back to config loading (which also loads .env).
    """
    # Direct env var check first (for cases where only DB is needed)
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url
    
    # Try loading from .env via config
    config = load_config(require_all=False)
    if config and config.database_url:
        return config.database_url
    
    raise ValueError(
        "DATABASE_URL environment variable is required.\n"
        "Set it in your environment or create a .env file."
    )


@contextmanager
def get_connection() -> Generator:
    """Get a database connection context manager."""
    conn = psycopg2.connect(get_connection_string())
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(commit: bool = True) -> Generator:
    """Get a database cursor context manager with auto-commit."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def init_schema() -> None:
    """Initialize the database schema from migration files."""
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    
    if not migrations_dir.exists():
        raise FileNotFoundError(f"Migrations directory not found: {migrations_dir}")
    
    # Get all SQL files sorted by name
    sql_files = sorted(migrations_dir.glob("*.sql"))
    
    if not sql_files:
        raise FileNotFoundError(f"No SQL migration files found in {migrations_dir}")
    
    with get_cursor() as cursor:
        for sql_file in sql_files:
            print(f"Applying migration: {sql_file.name}")
            sql = sql_file.read_text()
            cursor.execute(sql)
    
    print("Schema initialized successfully.")

