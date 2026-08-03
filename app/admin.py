"""Synchronous database helpers for the CLI scripts.

Kept apart from app/db.py because the access pattern is different: these run
once from a terminal, manage their own transactions, and are never on the
request path.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.tokens import generate_token

TOKEN_COLLISION_RETRIES = 5


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


def add_person(conn: psycopg.Connection, display_name: str) -> dict[str, Any]:
    """Create a person with a fresh token. Returns the inserted row."""
    for _ in range(TOKEN_COLLISION_RETRIES):
        token = generate_token()
        try:
            with conn.transaction():
                cursor = conn.execute(
                    "insert into people (token, display_name) values (%s, %s)"
                    " returning id, token, display_name, created_at",
                    (token, display_name),
                )
                return cursor.fetchone()
        except psycopg.errors.UniqueViolation:
            continue
    raise RuntimeError("could not generate a unique token")


def create_person_with_token(
    conn: psycopg.Connection, token: str, display_name: str
) -> dict[str, Any]:
    """Create a person with a caller-supplied token.

    Used when publishing to a second database (prod) so the token (and
    therefore the local bundle directory name and the URL) stays identical
    across environments.
    """
    with conn.transaction():
        cursor = conn.execute(
            "insert into people (token, display_name) values (%s, %s)"
            " returning id, token, display_name, created_at",
            (token, display_name),
        )
        return cursor.fetchone()


def get_person(conn: psycopg.Connection, token: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        "select id, token, display_name, created_at from people where token = %s",
        (token,),
    )
    return cursor.fetchone()


def next_version(conn: psycopg.Connection, person_id: int) -> int:
    cursor = conn.execute(
        "select coalesce(max(version), 0) + 1 as version from pages where person_id = %s",
        (person_id,),
    )
    return cursor.fetchone()["version"]


def publish_page(conn: psycopg.Connection, person_id: int, bundle_dir: str, version: int) -> dict[str, Any]:
    """Insert a new page version and make it the live one.

    The old live row is cleared first because a partial unique index enforces at
    most one live page per person.
    """
    with conn.transaction():
        conn.execute(
            "update pages set is_live = false where person_id = %s and is_live",
            (person_id,),
        )
        cursor = conn.execute(
            "insert into pages (person_id, version, bundle_dir, is_live)"
            " values (%s, %s, %s, true) returning id, version, bundle_dir, published_at",
            (person_id, version, bundle_dir),
        )
        return cursor.fetchone()


def list_people(conn: psycopg.Connection) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        select pe.token,
               pe.display_name,
               pe.created_at,
               live.version                as live_version,
               live.bundle_dir             as live_bundle_dir,
               coalesce(counts.total, 0)   as responses,
               counts.latest_at
          from people pe
          left join pages live
                 on live.person_id = pe.id and live.is_live
          left join lateral (
                 select count(*) as total, max(r.created_at) as latest_at
                   from responses r
                   join pages p on p.id = r.page_id
                  where p.person_id = pe.id
               ) counts on true
         order by pe.created_at
        """
    )
    return cursor.fetchall()


def list_responses(conn: psycopg.Connection, token: str) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        select r.id, r.summary, r.answers, r.created_at, r.notified_at, pg.version
          from responses r
          join pages  pg on pg.id = r.page_id
          join people pe on pe.id = pg.person_id
         where pe.token = %s
         order by r.created_at desc
        """,
        (token,),
    )
    return cursor.fetchall()
