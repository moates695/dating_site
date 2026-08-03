---
name: reset-test-page
description: Wipe stored replies and recorded views from the local dev database so a date page opens as a first-time visitor again. Use when asked to reset or wipe a test user, clear responses or views, see the form instead of the "Lovely" confirmation screen, or make the first-open notification fire again.
---

# Reset a local test page

Once a person has replied, `app.js` sends every later visit straight to the
confirmation view, so the form is unreachable except through "Change my
answer". Clearing that person's `responses` rows puts the page back to how a
first-time visitor sees it.

## How to run

```bash
uv run scripts/reset_responses.py                 # everyone in the dev database
uv run scripts/reset_responses.py <token>         # just one person
uv run scripts/reset_responses.py --dry-run       # count only, deletes nothing
```

The token is the directory name under `pages/` and the last path segment of the
page URL, for example `pages/eh9ankpbvuhs/` serves
`http://127.0.0.1:8000/d/eh9ankpbvuhs/`.

After it runs, hard-refresh the page. The reset changes database rows, not
files, so a stale tab keeps showing the confirmation screen until it refetches
`/api/d/<token>/context`.

## What it does and does not touch

Deletes `responses` and `page_views` rows. People, pages, tokens, live-version
pointers and `pages/<token>/` directories are all left alone, so the same URL
keeps working and the bundle is unchanged. Nothing needs republishing
afterwards.

Views go with the replies because the first-open notification fires once per
page. Leaving the view rows behind would mean a freshly reset page opens
silently, which looks like broken notifications rather than a page that has
already been seen.

## Safety

The script calls `ensure_local()` before it opens a connection and exits if
`APP_ENV` is anything but `local`. Do not work around that refusal, and do not
reach for `psql` or the postgres MCP to delete responses instead.

Both databases are reached over localhost (dev on 5433, prod through an SSH
tunnel on 25432), so the connection string cannot tell them apart and `APP_ENV`
is the only reliable signal. A production response is a real reply from a real
person and there is no undo.

If a production page genuinely needs clearing, that is a deliberate manual job
for the user, not this skill.

## Checking the result

```bash
uv run scripts/list_people.py
```

Shows each person with their URL and either "no reply yet" or a reply count.
After a successful reset every affected person reads "no reply yet".
