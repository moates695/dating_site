"""Synchronous database helpers for the CLI scripts.

Kept apart from app/db.py because the access pattern is different: these run
once from a terminal, manage their own transactions, and are never on the
request path.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import ENV_LOCAL
from app.tokens import generate_token

TOKEN_COLLISION_RETRIES = 5


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


INSERT_PERSON = (
    "insert into people (token, display_name, is_demo) values (%s, %s, %s)"
    " returning id, token, display_name, is_demo, created_at"
)


def add_person(
    conn: psycopg.Connection, display_name: str, *, is_demo: bool = False
) -> dict[str, Any]:
    """Create a person with a fresh token. Returns the inserted row."""
    for _ in range(TOKEN_COLLISION_RETRIES):
        token = generate_token()
        try:
            with conn.transaction():
                cursor = conn.execute(INSERT_PERSON, (token, display_name, is_demo))
                return cursor.fetchone()
        except psycopg.errors.UniqueViolation:
            continue
    raise RuntimeError("could not generate a unique token")


def create_person_with_token(
    conn: psycopg.Connection, token: str, display_name: str, *, is_demo: bool = False
) -> dict[str, Any]:
    """Create a person with a caller-supplied token.

    Used when publishing to a second database (prod) so the token (and
    therefore the local bundle directory name and the URL) stays identical
    across environments, and for the demo page, whose token is meant to be
    readable rather than unguessable.
    """
    with conn.transaction():
        cursor = conn.execute(INSERT_PERSON, (token, display_name, is_demo))
        return cursor.fetchone()


def get_person(conn: psycopg.Connection, token: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        "select id, token, display_name, is_demo, created_at from people where token = %s",
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
               counts.latest_at,
               coalesce(views.opens, 0)    as opens,
               views.first_open,
               views.last_open
          from people pe
          left join pages live
                 on live.person_id = pe.id and live.is_live
          left join lateral (
                 select count(*) as total, max(r.created_at) as latest_at
                   from responses r
                   join pages p on p.id = r.page_id
                  where p.person_id = pe.id
               ) counts on true
          left join lateral (
                 -- Only real opens: your own visits and link-preview fetches
                 -- would otherwise read as someone looking at the page.
                 select count(*)         as opens,
                        min(v.viewed_at) as first_open,
                        max(v.viewed_at) as last_open
                   from page_views v
                   join pages p on p.id = v.page_id
                  where p.person_id = pe.id
                    and v.kind = 'load'
                    and not v.is_self
               ) views on true
         order by pe.created_at
        """
    )
    return cursor.fetchall()


def list_views(conn: psycopg.Connection, token: str) -> list[dict[str, Any]]:
    """Every recorded view of one person's pages, newest first.

    Includes your own visits and the HTML fetches that link previews make, both
    labelled, because the reason to look at this list is usually to work out
    which of those an unexpected view was.
    """
    cursor = conn.execute(
        """
        select v.kind, v.is_self, v.ip_hash, v.user_agent, v.viewed_at, v.notified_at, pg.version
          from page_views v
          join pages  pg on pg.id = v.page_id
          join people pe on pe.id = pg.person_id
         where pe.token = %s
         order by v.viewed_at desc
        """,
        (token,),
    )
    return cursor.fetchall()


def count_views(conn: psycopg.Connection, token: str | None = None) -> int:
    """How many recorded views a reset would remove."""
    if token is None:
        cursor = conn.execute("select count(*) as total from page_views")
    else:
        cursor = conn.execute(
            """
            select count(*) as total
              from page_views v
              join pages  pg on pg.id = v.page_id
              join people pe on pe.id = pg.person_id
             where pe.token = %s
            """,
            (token,),
        )
    return cursor.fetchone()["total"]


def delete_views(conn: psycopg.Connection, token: str | None = None) -> int:
    """Delete recorded views so the next visit counts as a first open again.

    Without this a reset page would open silently: the notification fires once
    per page and the row saying it already fired would still be there.
    """
    with conn.transaction():
        if token is None:
            cursor = conn.execute("delete from page_views")
        else:
            cursor = conn.execute(
                """
                delete from page_views v
                 using pages pg, people pe
                 where v.page_id = pg.id
                   and pg.person_id = pe.id
                   and pe.token = %s
                """,
                (token,),
            )
        return cursor.rowcount


def ensure_local(app_env: str) -> None:
    """Refuse a destructive command anywhere but the local dev database.

    Both databases are reached over localhost (dev on 5433, prod through an SSH
    tunnel on 25432), so the connection string is not a safe way to tell them
    apart. APP_ENV is, and it is the one thing .env.prod always sets. A prod
    response is a real reply from a real person and there is no undo.
    """
    if app_env != ENV_LOCAL:
        raise SystemExit(
            f"refusing to delete responses with APP_ENV={app_env!r}. "
            f"This only ever runs against the local dev database."
        )


def count_responses(conn: psycopg.Connection, token: str | None = None) -> int:
    """How many stored replies a reset would remove."""
    if token is None:
        cursor = conn.execute("select count(*) as total from responses")
    else:
        cursor = conn.execute(
            """
            select count(*) as total
              from responses r
              join pages  pg on pg.id = r.page_id
              join people pe on pe.id = pg.person_id
             where pe.token = %s
            """,
            (token,),
        )
    return cursor.fetchone()["total"]


def delete_responses(conn: psycopg.Connection, token: str | None = None) -> int:
    """Delete stored replies so a page opens as if it had never been answered.

    Scoped to one person when a token is given, otherwise every response in the
    database. People and pages are deliberately left alone: the token, the URL
    and the bundle directory all stay valid, so the same link can be reopened.
    Returns the number of rows removed.
    """
    with conn.transaction():
        if token is None:
            cursor = conn.execute("delete from responses")
        else:
            cursor = conn.execute(
                """
                delete from responses r
                 using pages pg, people pe
                 where r.page_id = pg.id
                   and pg.person_id = pe.id
                   and pe.token = %s
                """,
                (token,),
            )
        return cursor.rowcount


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
