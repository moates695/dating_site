"""Shared bootstrap for the CLI scripts.

Each script takes --env-file so you can point it at dev or prod:
    uv run scripts/list_people.py
    uv run scripts/list_people.py --env-file .env.prod
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ENV_FILE = ".env"

from dotenv import load_dotenv  # noqa: E402

from app.config import Settings, load_settings  # noqa: E402


def add_env_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"environment file to load (default: {DEFAULT_ENV_FILE})",
    )


def settings_from_args(args: argparse.Namespace) -> Settings:
    env_path = (REPO_ROOT / args.env_file).resolve()

    if env_path.is_file():
        # override=True so an explicit --env-file always beats anything already
        # exported in the shell; switching to prod must never half-apply.
        load_dotenv(env_path, override=True)
    elif args.env_file != DEFAULT_ENV_FILE:
        # An explicitly named file must exist; silently falling back would be a
        # good way to run a prod command against the dev database.
        raise SystemExit(f"env file not found: {env_path}")
    # Otherwise fall back to the ambient environment: in the container the
    # variables come from docker's env_file, so there is no .env on disk.

    return load_settings()


def deploy_target() -> tuple[str, str]:
    """SSH host and remote pages directory for publishing."""
    host = (os.environ.get("DEPLOY_SSH_HOST") or "").strip()
    remote_dir = (os.environ.get("DEPLOY_PAGES_DIR") or "").strip()
    if not host or not remote_dir:
        raise SystemExit("DEPLOY_SSH_HOST and DEPLOY_PAGES_DIR must be set to publish to prod")
    return host, remote_dir
