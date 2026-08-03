"""Shared fixtures.

Every test here is stateless: no database, no network. The request-path tests
substitute a fake implementing the same methods as app.db.Database.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import LivePage, ResponseStats  # noqa: E402

TEST_TOKEN = "abcdefgh2345"


class FakeDatabase:
    """In-memory stand-in for app.db.Database."""

    def __init__(self, pages: dict[str, LivePage] | None = None) -> None:
        self.pages = pages or {}
        self.responses: list[dict] = []
        self.notified: list[int] = []

    async def get_live_page(self, token: str) -> LivePage | None:
        return self.pages.get(token)

    async def response_stats(self, page_id: int) -> ResponseStats:
        rows = [r for r in self.responses if r["page_id"] == page_id]
        latest = max((r["created_at"] for r in rows), default=None)
        return ResponseStats(count=len(rows), latest_at=latest)

    async def insert_response(self, page_id: int, summary: str, answers: dict):
        created_at = datetime.now(UTC)
        row = {
            "id": len(self.responses) + 1,
            "page_id": page_id,
            "summary": summary,
            "answers": answers,
            "created_at": created_at,
        }
        self.responses.append(row)
        return row["id"], created_at

    async def mark_notified(self, response_id: int) -> None:
        self.notified.append(response_id)

    async def close(self) -> None:
        return None


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    """A pages directory holding one bundle named after TEST_TOKEN."""
    bundle = tmp_path / TEST_TOKEN
    bundle.mkdir()
    (bundle / "index.html").write_text("<h1>hello</h1>", encoding="utf-8")
    (bundle / "style.css").write_text("body { color: red; }", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("must not be served", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings(bundle_dir: Path) -> Settings:
    return Settings(
        app_env="local",
        database_url="postgresql://unused",
        pages_dir=bundle_dir,
        site_base_url="http://testserver",
        telegram_bot_token=None,
        telegram_chat_id=None,
    )


@pytest.fixture
def live_page() -> LivePage:
    return LivePage(
        page_id=1,
        person_id=1,
        token=TEST_TOKEN,
        display_name="Test Person One",
        bundle_dir=f"{TEST_TOKEN}/v1",
    )


@pytest.fixture
def fake_db(live_page: LivePage) -> FakeDatabase:
    return FakeDatabase({TEST_TOKEN: live_page})


@pytest.fixture
def client(settings: Settings, fake_db: FakeDatabase):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings, db=fake_db)) as test_client:
        yield test_client
