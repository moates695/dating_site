"""Telegram notification.

Notification is strictly a side effect: the response is already committed to
Postgres before this runs, so a failure here never costs a submission. Failed
sends leave responses.notified_at null, which is how you find them later.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.submissions import MAX_STRING_CHARS, clean_text

LOGGER = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 3500
SEND_TIMEOUT_SECONDS = 10.0


def format_notification(display_name: str, summary: str, answers: dict, *, is_first: bool) -> str:
    """Build the message body.

    A revised answer gets its own headline so a repeat notification is never
    mistaken for a fresh reply, but the details below it are the full picture
    every time: the new answers stand alone, with no diff to piece together.

    Sent as plain text with no parse_mode, so nothing needs escaping: a note
    full of underscores or asterisks cannot break or reformat the message.
    """
    name = clean_text(display_name, 100)
    headline = f"💌 {name} replied" if is_first else f"🔄 {name} changed their answer"
    lines = [headline]

    if summary:
        lines.append("")
        lines.append(clean_text(summary, 500))

    detail = json.dumps(answers, indent=2, ensure_ascii=False, sort_keys=True)
    lines.append("")
    lines.append(clean_text(detail, MAX_STRING_CHARS))

    message = "\n".join(lines)
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[: MAX_MESSAGE_CHARS - 1] + "…"
    return message


def format_view_notification(display_name: str) -> str:
    """Build the message for a first open.

    One line and nothing else. It is still only ever sent once per page, but
    saying so in the message meant every open arrived with a paragraph
    explaining itself; the full history is in page_views if you want it
    (scripts/list_people.py --views <token>).
    """
    name = clean_text(display_name, 100)
    return f"👀 {name} opened the page"


async def send_notification(bot_token: str, chat_id: str, message: str) -> bool:
    """Send to Telegram. Returns True on success; never raises."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
            )
        if response.status_code != 200:
            LOGGER.error("telegram send failed: %s %s", response.status_code, response.text[:400])
            return False
        return True
    except Exception:
        LOGGER.exception("telegram send raised")
        return False
