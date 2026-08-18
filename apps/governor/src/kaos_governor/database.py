from __future__ import annotations

import os
import time
from pathlib import Path


MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS governor_schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def connection_parameters() -> dict[str, object]:
    return {
        "host": os.environ.get("GOVERNOR_DB_HOST") or os.environ.get("BRAIN_DB_HOST", "governor-postgres"),
        "port": int(os.environ.get("GOVERNOR_DB_PORT") or os.environ.get("BRAIN_DB_PORT", "5432")),
        "dbname": os.environ.get("GOVERNOR_DB_NAME") or os.environ.get("POSTGRES_DB", "kaos_governor"),
        "user": os.environ.get("GOVERNOR_DB_USER") or os.environ.get("POSTGRES_USER", "kaos_governor"),
        "password": os.environ.get("GOVERNOR_DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD", ""),
        "connect_timeout": int(os.environ.get("GOVERNOR_DB_CONNECT_TIMEOUT_SECONDS", "5")),
    }


def connect():
    import psycopg

    return psycopg.connect(**connection_parameters())


def migration_files(directory: str | Path):
    return sorted(Path(directory).glob("[0-9][0-9][0-9]_*.sql"))


def apply_migrations(directory: str | Path) -> None:
    with connect() as connection:
        connection.execute(MIGRATION_TABLE_SQL)
        applied = {
            row[0]
            for row in connection.execute("SELECT version FROM governor_schema_migrations ORDER BY version").fetchall()
        }
        for path in migration_files(directory):
            version = path.stem.split("_", 1)[0]
            if version in applied:
                continue
            with connection.transaction():
                connection.execute(path.read_text(encoding="utf-8"))
                connection.execute("INSERT INTO governor_schema_migrations (version) VALUES (%s)", (version,))


def wait_for_database_and_migrate(directory: str | Path) -> None:
    attempts = int(os.environ.get("GOVERNOR_DB_STARTUP_ATTEMPTS", "20"))
    delay = float(os.environ.get("GOVERNOR_DB_STARTUP_DELAY_SECONDS", "1.5"))
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            apply_migrations(directory)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError("governor database did not become ready") from last_error


def database_status() -> dict[str, object]:
    try:
        with connect() as connection:
            row = connection.execute(
                """
                SELECT current_database(), current_user,
                       COALESCE((SELECT max(version) FROM governor_schema_migrations), '')
                """
            ).fetchone()
        return {"ok": True, "database": row[0], "user": row[1], "migration": row[2]}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
