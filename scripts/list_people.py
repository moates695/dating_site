#!/usr/bin/env python3.12
"""List everyone, their URL, and whether they have replied.

    uv run scripts/list_people.py
    uv run scripts/list_people.py --env-file .env.prod
    uv run scripts/list_people.py --responses <token>
"""

from __future__ import annotations

import argparse
import json

from _common import add_env_argument, settings_from_args

from app.admin import connect, list_people, list_responses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", metavar="TOKEN", help="show full answers for one person")
    add_env_argument(parser)
    args = parser.parse_args()

    settings = settings_from_args(args)

    with connect(settings.database_url) as conn:
        if args.responses:
            _print_responses(conn, args.responses)
            return
        _print_people(conn, settings)


def _print_people(conn, settings) -> None:
    rows = list_people(conn)
    if not rows:
        print("no people yet; add one with scripts/add_person.py")
        return

    for row in rows:
        version = f"v{row['live_version']}" if row["live_version"] else "no live page"
        replied = (
            f"{row['responses']} reply/replies, last {row['latest_at']:%Y-%m-%d %H:%M}"
            if row["responses"]
            else "no reply yet"
        )
        print(f"{row['display_name']}")
        print(f"  {settings.page_url(row['token'])}")
        print(f"  {version} · {replied}")
        print()


def _print_responses(conn, token: str) -> None:
    rows = list_responses(conn, token)
    if not rows:
        print("no responses")
        return

    for row in rows:
        notified = "notified" if row["notified_at"] else "NOT NOTIFIED"
        print(f"[{row['created_at']:%Y-%m-%d %H:%M}] v{row['version']} · {notified}")
        if row["summary"]:
            print(f"  {row['summary']}")
        print("  " + json.dumps(row["answers"], indent=2, ensure_ascii=False).replace("\n", "\n  "))
        print()


if __name__ == "__main__":
    main()
