"""Opaque URL tokens.

Possession of the token is the only credential, so it must be unguessable.
Twelve characters of the alphabet below is roughly 59 bits of entropy, which is
far beyond anything brute-forceable against a rate-limited endpoint.
"""

from __future__ import annotations

import secrets

# Lowercase alphanumerics with the ambiguous glyphs removed (0/o, 1/l/i), so a
# token survives being read aloud or retyped from a screenshot.
TOKEN_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
TOKEN_LENGTH = 12


def generate_token(length: int = TOKEN_LENGTH) -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


def is_valid_token(token: str) -> bool:
    """Cheap shape check so obviously bogus tokens never reach the database."""
    if not token or len(token) > 64:
        return False
    return all(character in TOKEN_ALPHABET for character in token)
