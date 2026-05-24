"""
Lightweight migration runner for memeco.

Tracks applied migrations in a `schema_migrations` table and applies any
pending .sql files from the `migrations/` directory in filename order.

Usage:
    # Via console script (after pip install -e .):
    memeco-migrate

    # Or directly:
    python -m app.apply_migrations

    # Dry-run (show pending, apply nothing):
    memeco-migrate --dry-run

Environment:
    DATABASE_URL  — asyncpg-compatible connection string (required).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    filename    TEXT        NOT NULL,
    checksum    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _discover_migrations(directory: Path) -> list[tuple[str, Path]]:
    """Return sorted list of (version_key, path) for all .sql files."""
    files = sorted(directory.glob("*.sql"))
    results = []
    for f in files:
        # Version key is the filename stem, e.g. "001_initial_schema"
        results.append((f.stem, f))
    return results


def _file_checksum(path: Path) -> str:
    """SHA-256 hex digest of a migration file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _ensure_tracking_table(conn: asyncpg.Connection) -> None:
    await conn.execute(BOOTSTRAP_SQL)


async def _get_applied(conn: asyncpg.Connection) -> dict[str, str]:
    """Return {version: checksum} for all applied migrations."""
    rows = await conn.fetch(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    )
    return {r["version"]: r["checksum"] for r in rows}


async def _apply_migration(
    conn: asyncpg.Connection, version: str, path: Path, checksum: str
) -> None:
    """Apply a single migration file inside a transaction."""
    sql = path.read_text(encoding="utf-8")

    # Some TimescaleDB statements cannot run in a transaction block.
    # Detect that case and run without an explicit transaction wrapper.
    needs_no_tx = any(
        kw in sql.lower()
        for kw in (
            "create_hypertable",
            "add_retention_policy",
            "add_continuous_aggregate_policy",
            "refresh_continuous_aggregate",
        )
    )

    if needs_no_tx:
        # Run statements outside an explicit transaction
        await conn.execute(sql)
    else:
        async with conn.transaction():
            await conn.execute(sql)

    # Record the migration
    await conn.execute(
        """
        INSERT INTO schema_migrations (version, filename, checksum)
        VALUES ($1, $2, $3)
        ON CONFLICT (version) DO NOTHING
        """,
        version,
        path.name,
        checksum,
    )


async def run_migrations(dry_run: bool = False) -> list[str]:
    """
    Apply all pending migrations and return the list of newly applied versions.

    If dry_run is True, print pending migrations but don't apply them.
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is not set. Check your .env file.", file=sys.stderr)
        sys.exit(1)

    if not MIGRATIONS_DIR.is_dir():
        print(f"ERROR: migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    try:
        await _ensure_tracking_table(conn)
        applied = await _get_applied(conn)
        discovered = _discover_migrations(MIGRATIONS_DIR)

        pending: list[tuple[str, Path, str]] = []
        for version, path in discovered:
            checksum = _file_checksum(path)
            if version in applied:
                # Verify checksum hasn't changed
                if applied[version] != checksum:
                    print(
                        f"WARNING: checksum mismatch for already-applied "
                        f"migration {path.name}. Was it modified after being applied?",
                        file=sys.stderr,
                    )
                continue
            pending.append((version, path, checksum))

        if not pending:
            print("All migrations are up to date.")
            return []

        if dry_run:
            print(f"Pending migrations ({len(pending)}):")
            for _version, path, _ in pending:
                print(f"  [ ] {path.name}")
            return [v for v, _, _ in pending]

        applied_versions: list[str] = []
        for version, path, checksum in pending:
            print(f"Applying {path.name} ... ", end="", flush=True)
            try:
                await _apply_migration(conn, version, path, checksum)
                print("OK")
                applied_versions.append(version)
            except Exception as exc:
                print(f"FAILED\n  Error: {exc}", file=sys.stderr)
                sys.exit(1)

        print(f"\nDone. Applied {len(applied_versions)} migration(s).")
        return applied_versions
    finally:
        await conn.close()


def main() -> None:
    """CLI entry point for memeco-migrate."""
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    asyncio.run(run_migrations(dry_run=dry_run))


if __name__ == "__main__":
    main()
