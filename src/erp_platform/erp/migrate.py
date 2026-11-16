import logging
from pathlib import Path

import psycopg
from psycopg import sql

from erp_platform.config import Settings
from erp_platform.db import connect

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_migrations(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending `*.sql` files in filename order; `conn` must be in autocommit mode."""
    conn.execute("create schema if not exists erp")
    conn.execute(
        "create table if not exists erp.schema_migrations ("
        "filename text primary key, applied_at timestamptz not null default now())"
    )
    applied = {row[0] for row in conn.execute("select filename from erp.schema_migrations")}
    newly_applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in applied:
            continue
        # One transaction per file: a failing statement rolls back the whole migration.
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into erp.schema_migrations (filename) values (%s)", (path.name,))
        newly_applied.append(path.name)
        log.info("applied migration %s", path.name)
    log.info("migrations applied=%d already_applied=%d", len(newly_applied), len(applied))
    return newly_applied


def ensure_reader_role(conn: psycopg.Connection, settings: Settings) -> None:
    """Create or update the read-only login role used by extraction."""
    # Role DDL takes no bind parameters, so the statements are composed with psycopg.sql.
    role = sql.Identifier(settings.erp_reader_user)
    exists = conn.execute(
        "select 1 from pg_roles where rolname = %s", (settings.erp_reader_user,)
    ).fetchone()
    with conn.transaction():
        conn.execute(
            sql.SQL("{} role {} login password {}").format(
                sql.SQL("alter" if exists else "create"),
                role,
                sql.Literal(settings.erp_reader_password),
            )
        )
        conn.execute(sql.SQL("grant usage on schema erp to {}").format(role))
        conn.execute(sql.SQL("grant select on all tables in schema erp to {}").format(role))
        # Covers tables that later migrations create, so no migration has to grant anything.
        conn.execute(
            sql.SQL("alter default privileges in schema erp grant select on tables to {}").format(
                role
            )
        )
    log.info("reader role %s ready", settings.erp_reader_user)


def migrate(settings: Settings) -> None:
    with connect(settings, autocommit=True) as conn:
        apply_migrations(conn)
        ensure_reader_role(conn, settings)
