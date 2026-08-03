"""In-process rate limiting for submissions.

A page URL is a bearer credential, so a leaked link would otherwise let someone
spam Telegram indefinitely. This is a fixed-window counter held in memory,
adequate for a single container, and Cloudflare sits in front of it anyway.

The clock is injected so the behaviour is testable without sleeping.
"""

from __future__ import annotations

from collections import defaultdict

DEFAULT_MAX_PER_WINDOW = 10
DEFAULT_WINDOW_SECONDS = 3600.0


class RateLimiter:
    def __init__(
        self,
        max_per_window: int = DEFAULT_MAX_PER_WINDOW,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, now: float) -> bool:
        """Record an attempt for `key`; return False once the window is full."""
        cutoff = now - self.window_seconds
        recent = [stamp for stamp in self._hits[key] if stamp > cutoff]

        if len(recent) >= self.max_per_window:
            self._hits[key] = recent
            return False

        recent.append(now)
        self._hits[key] = recent
        return True
