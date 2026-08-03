"""Validation of submitted answers.

The server deliberately knows nothing about any individual page: a bundle's
JavaScript decides what `answers` looks like and writes its own `summary`. So
validation here is structural only: is this sane, bounded JSON that we are
willing to store and put in a Telegram message?
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

MAX_PAYLOAD_BYTES = 32 * 1024
MAX_SUMMARY_CHARS = 500
MAX_STRING_CHARS = 4000
MAX_DEPTH = 8
MAX_KEYS_PER_OBJECT = 100
MAX_ITEMS_PER_ARRAY = 200


class SubmissionError(ValueError):
    """Raised when a payload is malformed or exceeds a limit."""


@dataclass(frozen=True)
class Submission:
    summary: str
    answers: dict[str, Any]


def parse_submission(raw: bytes) -> Submission:
    """Parse and validate a raw request body.

    Raises SubmissionError with a message safe to return to the client.
    """
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise SubmissionError("payload too large")

    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SubmissionError("body is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise SubmissionError("body must be a JSON object")

    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise SubmissionError("'answers' must be a JSON object")
    if not answers:
        raise SubmissionError("'answers' must not be empty")

    _check_value(answers, depth=0)

    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        raise SubmissionError("'summary' must be a string")

    return Submission(summary=clean_text(summary, MAX_SUMMARY_CHARS), answers=answers)


def clean_text(text: str, limit: int) -> str:
    """Strip control characters and truncate.

    Applied to anything that ends up in a Telegram message. Tabs and newlines
    are kept; everything else below 0x20 goes.
    """
    stripped = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    stripped = stripped.strip()
    if len(stripped) > limit:
        stripped = stripped[: limit - 1].rstrip() + "…"
    return stripped


def _check_value(value: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise SubmissionError("payload nested too deeply")

    if isinstance(value, dict):
        if len(value) > MAX_KEYS_PER_OBJECT:
            raise SubmissionError("too many keys in payload")
        for key, item in value.items():
            if not isinstance(key, str):
                raise SubmissionError("object keys must be strings")
            if len(key) > 100:
                raise SubmissionError("object key too long")
            _check_value(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ITEMS_PER_ARRAY:
            raise SubmissionError("too many items in payload")
        for item in value:
            _check_value(item, depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise SubmissionError("a submitted value is too long")
    elif isinstance(value, (int, float, bool)) or value is None:
        return
    else:
        raise SubmissionError("unsupported value type in payload")
