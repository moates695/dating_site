#!/usr/bin/env python3.12
"""Publish a page bundle.

    uv run scripts/publish.py <token> --env-file .env.prod

Against a prod env file this snapshots pages/<token>/ to the droplet as
<token>/v<n>, then flips the live pointer in the database. Rolling back is a
matter of pointing an earlier version's row back at is_live.

Against a local env file it only bumps the version row; locally the app always
serves the working directory so edits appear on refresh.
"""

from __future__ import annotations

import argparse
import subprocess

from _common import add_env_argument, deploy_target, settings_from_args

from app.admin import connect, create_person_with_token, get_person, next_version, publish_page
from app.tokens import is_valid_token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("token", help="the person's token")
    parser.add_argument(
        "--name",
        help="display name, required only when the person does not yet exist in the target database",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "create as the public demo page: never notifies, never shows one visitor's "
            "answer to the next. Only read when the person is being created"
        ),
    )
    add_env_argument(parser)
    args = parser.parse_args()

    if not is_valid_token(args.token):
        raise SystemExit(f"not a valid token: {args.token!r}")

    settings = settings_from_args(args)
    local_bundle = settings.pages_dir / args.token
    if not (local_bundle / "index.html").is_file():
        raise SystemExit(f"bundle has no index.html: {local_bundle}")

    with connect(settings.database_url) as conn:
        person = get_person(conn, args.token)
        if person is None:
            if not args.name:
                raise SystemExit(
                    f"{args.token} does not exist in the target database; "
                    f"pass --name to create them there"
                )
            person = create_person_with_token(
                conn, args.token, args.name, is_demo=args.demo
            )
            kind = "demo page" if person["is_demo"] else "person"
            print(f"created {person['display_name']} in target database ({kind})")
        elif args.demo and not person["is_demo"]:
            # Silently publishing a normal page over a --demo intent would mean
            # strangers' opens ringing a phone, so refuse rather than guess.
            raise SystemExit(
                f"{args.token} already exists in the target database and is not a demo page; "
                f"set people.is_demo there first, or drop --demo"
            )

        version = next_version(conn, person["id"])

        if settings.is_local:
            bundle_dir = args.token
        else:
            bundle_dir = f"{args.token}/v{version}"
            _sync_to_droplet(local_bundle, bundle_dir)

        page = publish_page(conn, person["id"], bundle_dir=bundle_dir, version=version)

    print(f"published v{page['version']} -> {page['bundle_dir']}")
    print(f"url {settings.page_url(args.token)}")


def _sync_to_droplet(local_bundle, bundle_dir: str) -> None:
    host, remote_root = deploy_target()
    remote_path = f"{remote_root.rstrip('/')}/{bundle_dir}"

    subprocess.run(["ssh", host, "mkdir", "-p", remote_path], check=True)
    # Trailing slashes matter: copy the contents of the bundle into the version
    # directory rather than nesting another level.
    subprocess.run(
        ["rsync", "-az", "--delete", f"{local_bundle}/", f"{host}:{remote_path}/"],
        check=True,
    )
    print(f"synced {local_bundle} -> {host}:{remote_path}")


if __name__ == "__main__":
    main()
