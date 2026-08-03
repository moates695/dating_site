"""FastAPI application.

The server is deliberately ignorant of what any page contains. It resolves a
token to a live bundle, serves that bundle's files, and accepts whatever JSON
the bundle posts back. Adding a new page, however different it looks or
behaves, never requires a change in here.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)

from app.bundles import INDEX_FILENAME, BundleError, resolve_asset
from app.config import Settings, load_settings
from app.db import Database, LivePage
from app.notifications import format_notification, send_notification
from app.ratelimit import RateLimiter
from app.submissions import MAX_PAYLOAD_BYTES, SubmissionError, parse_submission
from app.tokens import is_valid_token

LOGGER = logging.getLogger(__name__)

ASSET_CACHE_SECONDS = 300
NOT_FOUND_HTML = "<!doctype html><meta charset=utf-8><title>Not found</title><p>Not found."


def create_app(settings: Settings, db: Database | None = None) -> FastAPI:
    """Build the application. Passing `db` skips pool creation (used by tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_pool = db is None
        app.state.settings = settings
        app.state.db = db or await Database.connect(settings.database_url)
        app.state.limiter = RateLimiter()
        try:
            yield
        finally:
            if owns_pool:
                await app.state.db.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        # A page URL is a credential: never let it leak in a Referer header,
        # and keep these pages out of search indexes entirely.
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/robots.txt")
    async def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.get("/")
    async def root() -> HTMLResponse:
        return HTMLResponse(NOT_FOUND_HTML, status_code=404)

    @app.get("/d/{token}")
    async def redirect_to_slash(token: str):
        # Bundles use relative asset paths, which only resolve correctly when
        # the page itself is served from a directory-style URL.
        return RedirectResponse(f"/d/{token}/", status_code=308)

    @app.get("/d/{token}/{asset_path:path}")
    async def serve_bundle(request: Request, token: str, asset_path: str):
        page = await _lookup(request, token)
        if page is None:
            return HTMLResponse(NOT_FOUND_HTML, status_code=404)

        settings: Settings = request.app.state.settings
        is_index = asset_path in ("", "/")

        try:
            path = resolve_asset(
                settings.pages_dir,
                _effective_bundle_dir(settings, page),
                INDEX_FILENAME if is_index else asset_path,
            )
        except BundleError:
            if is_index:
                LOGGER.error("live page %s has no %s on disk", page.page_id, INDEX_FILENAME)
            return HTMLResponse(NOT_FOUND_HTML, status_code=404)

        if is_index or settings.is_local:
            # The page asks for its own state on load, so a cached copy would
            # show the wrong submitted/not-submitted view.
            cache = "no-store"
        else:
            cache = f"private, max-age={ASSET_CACHE_SECONDS}"
        return FileResponse(path, headers={"Cache-Control": cache})

    @app.get("/api/d/{token}/context")
    async def page_context(request: Request, token: str):
        page = await _lookup(request, token)
        if page is None:
            return JSONResponse({"error": "not_found"}, status_code=404)

        stats = await request.app.state.db.response_stats(page.page_id)
        return JSONResponse(
            {
                "display_name": page.display_name,
                "submitted": stats.count > 0,
                "submitted_at": stats.latest_at.isoformat() if stats.latest_at else None,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/d/{token}/submit")
    async def submit(request: Request, token: str, background: BackgroundTasks):
        page = await _lookup(request, token)
        if page is None:
            return JSONResponse({"error": "not_found"}, status_code=404)

        limiter: RateLimiter = request.app.state.limiter
        if not limiter.allow(token, time.monotonic()):
            LOGGER.warning("rate limit hit for token ending %s", token[-4:])
            return JSONResponse({"error": "too_many_requests"}, status_code=429)

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_PAYLOAD_BYTES:
            return JSONResponse({"error": "payload too large"}, status_code=413)

        try:
            submission = parse_submission(await request.body())
        except SubmissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Postgres is the source of truth: commit first, notify afterwards, so a
        # Telegram outage can never cost a submission.
        response_id, created_at = await request.app.state.db.insert_response(
            page.page_id, submission.summary, submission.answers
        )

        background.add_task(
            _notify,
            request.app.state.settings,
            request.app.state.db,
            response_id,
            page.display_name,
            submission.summary,
            submission.answers,
        )

        return JSONResponse(
            {"ok": True, "submitted_at": created_at.isoformat()},
            headers={"Cache-Control": "no-store"},
        )

    return app


async def _lookup(request: Request, token: str) -> LivePage | None:
    """Resolve a token to its live page, rejecting malformed tokens cheaply."""
    if not is_valid_token(token):
        return None
    return await request.app.state.db.get_live_page(token)


def _effective_bundle_dir(settings: Settings, page: LivePage) -> str:
    """Which directory to serve for this page.

    Locally we always serve the working directory `pages/<token>` so edits show
    up on refresh, regardless of what the row happens to record. In production
    the published snapshot (e.g. `<token>/v3`) is authoritative.
    """
    return page.token if settings.is_local else page.bundle_dir


def create_default_app() -> FastAPI:
    """Entry point for uvicorn: `uvicorn --factory app.main:create_default_app`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app(load_settings())


async def _notify(
    settings: Settings,
    db: Database,
    response_id: int,
    display_name: str,
    summary: str,
    answers: dict[str, Any],
) -> None:
    message = format_notification(display_name, summary, answers)

    if not settings.telegram_enabled:
        LOGGER.info("telegram not configured; message would have been:\n%s", message)
        return

    if await send_notification(settings.telegram_bot_token, settings.telegram_chat_id, message):
        await db.mark_notified(response_id)
    else:
        LOGGER.error("response %s stored but not notified", response_id)
