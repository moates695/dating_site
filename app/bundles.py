"""Resolving files inside a person's page bundle.

Bundle directories are recorded in the database as paths relative to PAGES_DIR.
Everything here exists to guarantee a request can never escape that root.
"""

from __future__ import annotations

from pathlib import Path

INDEX_FILENAME = "index.html"


class BundleError(Exception):
    """Raised when a requested path is unsafe or missing."""


def resolve_bundle_dir(pages_dir: Path, bundle_dir: str) -> Path:
    """Resolve a bundle directory recorded in the database."""
    return _resolve_within(pages_dir, bundle_dir)


def resolve_asset(pages_dir: Path, bundle_dir: str, asset_path: str) -> Path:
    """Resolve an asset request against a bundle, rejecting traversal.

    Returns the resolved file path. Raises BundleError if the path escapes the
    bundle, is not a regular file, or does not exist.
    """
    root = _resolve_within(pages_dir, bundle_dir)
    candidate = _resolve_within(root, asset_path)

    if not candidate.is_file():
        raise BundleError(f"asset not found: {asset_path}")
    return candidate


def _resolve_within(root: Path, relative: str) -> Path:
    """Join `relative` onto `root`, ensuring the result stays inside it."""
    if relative.startswith("/") or "\x00" in relative:
        raise BundleError("absolute or malformed path rejected")

    root = root.resolve()
    # strict=False so a missing file still resolves; existence is checked by the
    # caller. Symlinks are resolved here, so a link pointing outside the root is
    # caught by the containment check below.
    candidate = (root / relative).resolve()

    if candidate != root and not candidate.is_relative_to(root):
        raise BundleError("path escapes the bundle directory")
    return candidate
