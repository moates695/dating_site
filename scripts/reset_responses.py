#!/usr/bin/env python3.12
"""Wipe stored replies and views from the local dev database so a page opens fresh.

    uv run scripts/reset_responses.py                 # everyone
    uv run scripts/reset_responses.py <token>         # just one person
    uv run scripts/reset_responses.py --dry-run       # count, delete nothing

A page shows its confirmation screen on every visit once a reply exists, so
testing the form a second time means clearing that reply. Recorded views go
with it, otherwise a reset page opens silently: the first-open notification
fires once per page and the row saying it already fired would survive.

People, pages and bundle directories are untouched: every token, URL and
pages/<token>/ directory keeps working, only the responses and page_views rows
go.

Refuses to run unless APP_ENV is local. Production replies are real and there
is no undo.
"""

from __future__ import annotations

import argparse

from _common import add_env_argument, settings_from_args

from app.admin import (
    connect,
    count_responses,
    count_views,
    delete_responses,
    delete_views,
    ensure_local,
    get_person,
    list_people,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "token",
        nargs="?",
        help="only reset this person (default: everyone in the dev database)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted without deleting it",
    )
    add_env_argument(parser)
    args = parser.parse_args()

    settings = settings_from_args(args)
    ensure_local(settings.app_env)

    with connect(settings.database_url) as conn:
        # A mistyped token would otherwise report "0 deleted" and look like a
        # page that was already clean.
        if args.token and not get_person(conn, args.token):
            raise SystemExit(f"no person with token {args.token!r} in the dev database")

        if args.dry_run:
            responses = count_responses(conn, args.token)
            views = count_views(conn, args.token)
            print(f"would delete {responses} response(s) and {views} view(s)")
            return

        deleted_responses = delete_responses(conn, args.token)
        deleted_views = delete_views(conn, args.token)
        print(f"deleted {deleted_responses} response(s) and {deleted_views} view(s)")

        for row in list_people(conn):
            if args.token and row["token"] != args.token:
                continue
            print(f"  {row['display_name']}: {settings.page_url(row['token'])}")


if __name__ == "__main__":
    main()
