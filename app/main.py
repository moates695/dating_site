"""FastAPI application.

The server is deliberately ignorant of what any page contains. It resolves a
token to a live bundle, serves that bundle's files, and accepts whatever JSON
the bundle posts back. Adding a new page, however different it looks or
behaves, never requires a change in here.
"""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from app.notifications import format_notification, format_view_notification, send_notification
from app.ratelimit import RateLimiter
from app.submissions import MAX_PAYLOAD_BYTES, SubmissionError, parse_submission
from app.tokens import is_valid_token

LOGGER = logging.getLogger(__name__)

ASSET_CACHE_SECONDS = 300
NOT_FOUND_HTML = "<!doctype html><meta charset=utf-8><title>Not found</title><p>Not found."

# Your own visits use the page URL with `-test` stuck on the end of the token,
# e.g. /e/<token>-test/. A suffix rather than a query parameter because it
# survives being retyped by hand and because everything the page then asks for,
# assets and the context call alike, sits under the same prefix and is marked
# without the page having to carry anything across itself. The hyphen is not in
# the token alphabet, so this can never collide with a real token.
#
# Nothing is stored in the browser, so the marker only applies to the visit that
# carries it: forget it and you get a notification you can recognise as
# yourself, which is a far better failure than a browser silently marked as
# yours forever.
OWNER_MODE_SUFFIX = "-test"

# A request for the page HTML. Link-preview crawlers make this the moment the
# URL is sent in a message, so it is recorded but never notified.
VIEW_KIND_FETCH = "fetch"
# The context call the page makes from JavaScript. Crawlers do not run
# JavaScript, so this is the one that means a person opened the page.
VIEW_KIND_LOAD = "load"

MAX_USER_AGENT_CHARS = 300


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

    @app.get("/e/{token}")
    async def redirect_to_slash(token: str):
        # Bundles use relative asset paths, which only resolve correctly when
        # the page itself is served from a directory-style URL.
        return RedirectResponse(f"/e/{token}/", status_code=308)

    @app.get("/e/{token}/{asset_path:path}")
    async def serve_bundle(
        request: Request, token: str, asset_path: str, background: BackgroundTasks
    ):
        token, is_self = _split_owner_marker(token)
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

        if is_index:
            # Assets are not recorded: one page open should be one row, not one
            # per stylesheet.
            background.add_task(
                _record_view,
                settings,
                request.app.state.db,
                page,
                VIEW_KIND_FETCH,
                _visit_facts(request, page, is_self),
            )

        if is_index or settings.is_local:
            # The page asks for its own state on load, so a cached copy would
            # show the wrong submitted/not-submitted view.
            cache = "no-store"
        else:
            cache = f"private, max-age={ASSET_CACHE_SECONDS}"
        return FileResponse(path, headers={"Cache-Control": cache})

    @app.get("/api/e/{token}/context")
    async def page_context(request: Request, token: str, background: BackgroundTasks):
        token, is_self = _split_owner_marker(token)
        page = await _lookup(request, token)
        if page is None:
            return JSONResponse({"error": "not_found"}, status_code=404)

        # JavaScript is running, so this is a real browser rather than a link
        # preview. Recorded after the response so a slow write never delays the
        # page, and so a failure here cannot stop it rendering.
        background.add_task(
            _record_view,
            request.app.state.settings,
            request.app.state.db,
            page,
            VIEW_KIND_LOAD,
            _visit_facts(request, page, is_self),
        )

        stats = await request.app.state.db.response_stats(page.page_id)

        # On a normal page "someone has answered" and "you have answered" are
        # the same thing, so the stored response is shown back as a
        # confirmation. A demo page is opened by strangers who share nothing but
        # the URL, so that would strand everyone after the first on a
        # confirmation screen for an answer that was not theirs.
        submitted = stats.count > 0 and not page.is_demo

        return JSONResponse(
            {
                "display_name": page.display_name,
                "submitted": submitted,
                "submitted_at": stats.latest_at.isoformat() if submitted else None,
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/e/{token}/submit")
    async def submit(request: Request, token: str, background: BackgroundTasks):
        # Submissions are never suppressed, but the page posts from whatever URL
        # it was opened at, so the marker still has to come off first.
        token, _ = _split_owner_marker(token)
        page = await _lookup(request, token)
        if page is None:
            return JSONResponse({"error": "not_found"}, status_code=404)

        # Per page normally, because the allowance exists to stop a leaked link
        # being used to spam Telegram. A demo page is meant to be opened by many
        # people, so metering it per page would let one visitor lock out every
        # other, which is why it falls back to per visitor there.
        limiter: RateLimiter = request.app.state.limiter
        limit_key = token
        if page.is_demo:
            limit_key = f"{token}:{_hash_ip(page.token, _client_ip(request))}"

        if not limiter.allow(limit_key, time.monotonic()):
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
        stored = await request.app.state.db.insert_response(
            page.page_id, submission.summary, submission.answers
        )

        # Stored either way: the demo answers are worth having, they are just
        # not worth a phone buzzing. notified_at stays null, which is already
        # how the CLI shows a response that never announced itself.
        if not page.is_demo:
            background.add_task(
                _notify,
                request.app.state.settings,
                request.app.state.db,
                stored.response_id,
                page.display_name,
                submission.summary,
                submission.answers,
                stored.is_first,
            )

        return JSONResponse(
            {"ok": True, "submitted_at": stored.created_at.isoformat()},
            headers={"Cache-Control": "no-store"},
        )

    return app


@dataclass(frozen=True)
class _Visit:
    """What is worth keeping about one request, extracted before it goes away."""

    is_self: bool
    ip_hash: str | None
    user_agent: str | None


def _split_owner_marker(token: str) -> tuple[str, bool]:
    """Separate a URL token from the `-test` marker you type on the end of it."""
    if token.endswith(OWNER_MODE_SUFFIX):
        return token[: -len(OWNER_MODE_SUFFIX)], True
    return token, False


def _visit_facts(request: Request, page: LivePage, is_self: bool) -> _Visit:
    return _Visit(
        is_self=is_self,
        ip_hash=_hash_ip(page.token, _client_ip(request)),
        user_agent=(request.headers.get("user-agent") or "").strip()[:MAX_USER_AGENT_CHARS] or None,
    )


def _client_ip(request: Request) -> str | None:
    """The visitor's address, as best it can be known.

    In production the socket peer is a Cloudflare edge address, so the real one
    only ever arrives in a header. CF-Connecting-IP is written by Cloudflare
    itself and is trustworthy exactly as long as the origin cannot be reached
    except through Cloudflare, which is why that DNS record stays proxied.
    """
    direct = request.headers.get("cf-connecting-ip")
    if direct:
        return direct.strip() or None

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Left-most entry is the client; everything after it is a proxy hop.
        return forwarded.split(",")[0].strip() or None

    return request.client.host if request.client else None


def _hash_ip(token: str, ip: str | None) -> str | None:
    """Hash an address rather than store it.

    Repeat visits from one connection still group together, but nothing in the
    database is a real person's address. Salted with the page token so the
    hashes cannot be matched up against another page, or against a list of
    guessed addresses without knowing the token.
    """
    if not ip:
        return None
    return hashlib.sha256(f"{token}:{ip}".encode()).hexdigest()


async def _record_view(
    settings: Settings,
    db: Database,
    page: LivePage,
    kind: str,
    visit: _Visit,
) -> None:
    """Store a view and, if it is the first real one, send the notification.

    Runs after the response has been sent. Every failure in here is swallowed:
    knowing a page was opened is never worth breaking the page over.
    """
    try:
        view = await db.record_view(
            page.page_id,
            kind,
            is_self=visit.is_self,
            ip_hash=visit.ip_hash,
            user_agent=visit.user_agent,
        )
    except Exception:
        LOGGER.exception("failed to record %s view of page %s", kind, page.page_id)
        return

    # Demo opens are still recorded, so the traffic is visible after the fact;
    # they are just never announced. A public link would otherwise turn the one
    # notification that means something into a stream of strangers.
    if kind != VIEW_KIND_LOAD or visit.is_self or page.is_demo or not view.is_first:
        return

    message = format_view_notification(page.display_name)

    if not settings.telegram_enabled:
        LOGGER.info("telegram not configured; message would have been:\n%s", message)
        return

    try:
        sent = await send_notification(
            settings.telegram_bot_token, settings.telegram_chat_id, message
        )
    except Exception:
        LOGGER.exception("view notification raised for page %s", page.page_id)
        return

    if sent:
        try:
            await db.mark_view_notified(view.view_id)
        except Exception:
            LOGGER.exception("view %s notified but not marked", view.view_id)
    else:
        LOGGER.error("first view of page %s recorded but not notified", page.page_id)


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
    is_first: bool,
) -> None:
    message = format_notification(display_name, summary, answers, is_first=is_first)

    if not settings.telegram_enabled:
        LOGGER.info("telegram not configured; message would have been:\n%s", message)
        return

    if await send_notification(settings.telegram_bot_token, settings.telegram_chat_id, message):
        await db.mark_notified(response_id)
    else:
        LOGGER.error("response %s stored but not notified", response_id)
