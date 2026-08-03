#!/usr/bin/env python3.12
"""Apply SQL migrations in filename order.

Each file runs in its own transaction and is recorded in schema_migrations, so
re-running is safe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _common import REPO_ROOT, add_env_argument, settings_from_args

from app.admin import connect

MIGRATIONS_DIR = REPO_ROOT / "db_schema" / "migrations"

CREATE_TRACKING_TABLE = """
create table if not exists schema_migrations (
    version    text        primary key,
    applied_at timestamptz not null default now()
)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_env_argument(parser)
    parser.add_argument("--dry-run", action="store_true", help="list pending migrations only")
    args = parser.parse_args()

    settings = settings_from_args(args)
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        raise SystemExit(f"no migrations found in {MIGRATIONS_DIR}")

    with connect(settings.database_url) as conn:
        conn.execute(CREATE_TRACKING_TABLE)
        conn.commit()

        cursor = conn.execute("select version from schema_migrations")
        applied = {row["version"] for row in cursor.fetchall()}

        pending = [path for path in migrations if path.stem not in applied]
        if not pending:
            print(f"up to date ({len(applied)} applied)")
            return

        for path in pending:
            if args.dry_run:
                print(f"pending: {path.name}")
                continue
            print(f"applying {path.name} ...", end=" ", flush=True)
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "insert into schema_migrations (version) values (%s)", (path.stem,)
                )
            print("ok")


if __name__ == "__main__":
    main()
