#!/usr/bin/env python3.12
"""Add a person, scaffold their page bundle from the starter, and print the URL.

    uv run scripts/add_person.py "Their Name"

Creates pages/<token>/ as a copy of pages/_base/. That directory is gitignored:
it holds personal content and must never be committed.
"""

from __future__ import annotations

import argparse
import shutil

from _common import add_env_argument, settings_from_args

from app.admin import add_person, connect, publish_page

BASE_BUNDLE = "_base"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="display name, shown on their page")
    add_env_argument(parser)
    args = parser.parse_args()

    settings = settings_from_args(args)
    base_dir = settings.pages_dir / BASE_BUNDLE
    if not (base_dir / "index.html").is_file():
        raise SystemExit(f"starter bundle missing: {base_dir / 'index.html'}")

    with connect(settings.database_url) as conn:
        person = add_person(conn, args.name)
        token = person["token"]

        target_dir = settings.pages_dir / token
        if target_dir.exists():
            raise SystemExit(f"refusing to overwrite existing directory: {target_dir}")
        shutil.copytree(base_dir, target_dir)

        # Register version 1 immediately so the token resolves straight away.
        # Locally the app serves pages/<token> regardless of what this records.
        publish_page(conn, person["id"], bundle_dir=token, version=1)

    print(f"name   {person['display_name']}")
    print(f"token  {token}")
    print(f"bundle {target_dir}")
    print(f"url    {settings.page_url(token)}")


if __name__ == "__main__":
    main()
