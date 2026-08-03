"""Async database access for the request path.

Admin/CLI queries live in app/admin.py instead: different access pattern, and
keeping them apart means the web app never carries write-heavy admin SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class LivePage:
    page_id: int
    person_id: int
    token: str
    display_name: str
    bundle_dir: str


@dataclass(frozen=True)
class ResponseStats:
    count: int
    latest_at: datetime | None


class Database:
    """Thin query layer. Tests substitute a fake with the same methods."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, database_url: str) -> "Database":
        pool = AsyncConnectionPool(
            database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await pool.open(wait=True, timeout=10)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def get_live_page(self, token: str) -> LivePage | None:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                """
                select pg.id   as page_id,
                       pe.id   as person_id,
                       pe.token,
                       pe.display_name,
                       pg.bundle_dir
                  from people pe
                  join pages  pg on pg.person_id = pe.id and pg.is_live
                 where pe.token = %s
                """,
                (token,),
            )
            row = await cursor.fetchone()
        return LivePage(**row) if row else None

    async def response_stats(self, page_id: int) -> ResponseStats:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "select count(*) as count, max(created_at) as latest_at"
                "  from responses where page_id = %s",
                (page_id,),
            )
            row = await cursor.fetchone()
        return ResponseStats(count=row["count"], latest_at=row["latest_at"])

    async def insert_response(
        self, page_id: int, summary: str, answers: dict[str, Any]
    ) -> tuple[int, datetime]:
        """Store a response and return (id, created_at). Committed on return."""
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "insert into responses (page_id, summary, answers)"
                " values (%s, %s, %s) returning id, created_at",
                (page_id, summary or None, Jsonb(answers)),
            )
            row = await cursor.fetchone()
        return row["id"], row["created_at"]

    async def mark_notified(self, response_id: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "update responses set notified_at = now() where id = %s",
                (response_id,),
            )
