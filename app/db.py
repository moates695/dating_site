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
    # A public page many strangers open, rather than one person's invitation.
    # Never notifies, never shows anyone else's answer back to them, and meters
    # submissions per visitor instead of per page.
    is_demo: bool = False


@dataclass(frozen=True)
class ResponseStats:
    count: int
    latest_at: datetime | None


@dataclass(frozen=True)
class StoredResponse:
    response_id: int
    created_at: datetime
    is_first: bool


@dataclass(frozen=True)
class RecordedView:
    view_id: int
    # True when no notifiable view of this page had been recorded before this
    # one. Only meaningful for a notifiable view; see record_view.
    is_first: bool


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
                       pg.bundle_dir,
                       pe.is_demo
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
    ) -> StoredResponse:
        """Store a response. Committed on return.

        The prior count is taken in the same statement as the insert, so
        `is_first` cannot be thrown off by a second submission racing this one:
        the CTE sees the snapshot from before this row existed.
        """
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                """
                with prior as (
                    select count(*) as earlier from responses where page_id = %s
                )
                insert into responses (page_id, summary, answers)
                     values (%s, %s, %s)
                  returning id, created_at, (select earlier from prior) = 0 as is_first
                """,
                (page_id, page_id, summary or None, Jsonb(answers)),
            )
            row = await cursor.fetchone()
        return StoredResponse(
            response_id=row["id"],
            created_at=row["created_at"],
            is_first=row["is_first"],
        )

    async def mark_notified(self, response_id: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "update responses set notified_at = now() where id = %s",
                (response_id,),
            )

    async def record_view(
        self,
        page_id: int,
        kind: str,
        *,
        is_self: bool,
        ip_hash: str | None,
        user_agent: str | None,
    ) -> RecordedView:
        """Store one view and report whether it is the first worth telling you about.

        `is_first` counts only notifiable views (a 'load' that is not the
        owner's), so opening the page yourself, or a messaging app fetching the
        HTML to build a link preview, never uses up the one notification. The
        count is taken in the same statement as the insert, the same way
        insert_response does it, so this row cannot count itself.
        """
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                """
                with prior as (
                    select count(*) as earlier
                      from page_views
                     where page_id = %s and kind = 'load' and not is_self
                )
                insert into page_views (page_id, kind, is_self, ip_hash, user_agent)
                     values (%s, %s, %s, %s, %s)
                  returning id, (select earlier from prior) = 0 as is_first
                """,
                (page_id, page_id, kind, is_self, ip_hash, user_agent),
            )
            row = await cursor.fetchone()
        return RecordedView(view_id=row["id"], is_first=row["is_first"])

    async def mark_view_notified(self, view_id: int) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "update page_views set notified_at = now() where id = %s",
                (view_id,),
            )
