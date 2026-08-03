# dating_site

Personalised one-page date-idea invitations, served from opaque URLs. No login:
knowing the link is the credential. Replies land in Postgres and ping Telegram.

**This repo is public.** It contains the engine and the shared starter page,
never a name, a token, a page bundle or a response. Those live in the database
and in `pages/<token>/`, which is gitignored.

## How it fits together

```
date.moates.com.au/d/<token>/
        │
        ▼
  nginx-proxy-prod ──► dates-prod (FastAPI) ──► Postgres 16 (host)
                              │
                              └──► Telegram (notification only)
```

The server knows nothing about what any page contains. It resolves a token to a
live bundle, serves that bundle's static files, and accepts whatever JSON the
bundle posts back:

```json
{ "summary": "Rooftop cocktails · Friday evening",
  "answers": { "main": "rooftop_cocktails", "when": ["fri_pm"] } }
```

`answers` is stored verbatim as JSONB and never interpreted. `summary` is the
line that goes to Telegram; the page writes it, because the page is the only
thing that knows what its own answers mean.

The consequence: **a new page never needs a server change.** Different styles,
animations and interactions per person are all just different files.

Postgres is the source of truth. A response is committed before Telegram is
called, so a failed notification leaves `responses.notified_at` null but never
loses the reply. `scripts/list_people.py --responses <token>` shows those.

## Knowing whether a page was opened

Opens are recorded in `page_views`, and the first real one pings Telegram. The
point is to tell *the link never arrived* apart from *she has seen it and is
thinking*, so it deliberately stays at opened / not opened.

Two things make that signal honest:

**Only JavaScript counts as an open.** Messaging apps fetch the page HTML to
build a link preview the moment you send the URL, which would otherwise fire a
notification triggered by your own message. Those fetches are recorded as
`kind = 'fetch'` and never notified. The context call the page makes once it is
running in a browser is `kind = 'load'`, and that is the one that counts.

**Your own visits carry `?mode=test`.** Open
`…/d/<token>/?mode=test` and the visit is stored with `is_self` set and stays
silent. The page passes the query string through to its context call, so the
marker covers both requests. Nothing is stored in the browser, which is the
point: forget the marker and you get a notification you can recognise as
yourself, rather than a browser silently marked as yours forever. If you ever
send someone a URL with the marker still attached, that visit is silent, so
check the link before sending it.

```bash
uv run scripts/list_people.py                 # opened / not opened per person
uv run scripts/list_people.py --views <token> # every view, labelled
```

Only the *first* real open notifies. Coming back later is recorded but silent.
Addresses are stored as a salted hash, never raw, which is enough to tell two
visitors apart and to spot a forwarded link.

## Local setup

Development runs entirely on your machine against a local Postgres container.
The droplet holds production data only and is never touched by local testing.

```bash
uv sync
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d    # Postgres 16 on :5433
uv run scripts/migrate.py
```

Port 5433 rather than 5432 because Docker Desktop forwards through Windows,
where 5432 is already in use.

Leave the Telegram variables blank locally and notifications are logged to the
server console instead of being sent.

Resetting is `docker compose -f docker-compose.dev.yml down -v`, then migrate
again; the data is throwaway.

## Making a page

```bash
uv run scripts/add_person.py "Their Name"
```

Creates the person, generates a token, copies `pages/_base/` to `pages/<token>/`
and prints the URL. Then:

```bash
uv run uvicorn --factory app.main:create_default_app --reload
```

Open the printed URL. Locally the app serves `pages/<token>/` directly, so edits
show up on refresh, with no publish step while you iterate.

Edit anything in that directory. The only contract is the POST body above; see
the comments in `pages/_base/app.js`. The collector there (driven by
`data-question` / `data-value` attributes) is a convenience: delete it and
build `answers` by hand if a page needs something it can't express.

## Publishing

Production commands run from your machine against the droplet's database over
an SSH tunnel, so open one first. Direct connections are not an option: the
`pg_hba.conf` entry is pinned to a home IP your ISP rotates.

```bash
ssh -f -N -L 25432:localhost:5432 do
uv run scripts/publish.py <token> --env-file .env.prod --name "Their Name"
```

Rsyncs `pages/<token>/` to the droplet as `<token>/v<n>`, then flips the live
pointer. `--name` is only needed the first time, when the person does not yet
exist in the production database. The token is reused across both so the URL
and the local directory name stay identical.

Every publish is a new version and nothing is overwritten, so rolling back is
pointing an earlier row's `is_live` back at itself. Responses reference the page
*version*, which is what keeps old answers interpretable after you change a page.

```bash
uv run scripts/list_people.py --env-file .env.prod              # everyone + URLs
uv run scripts/list_people.py --env-file .env.prod --responses <token>
```

## Deploying

Only needed when the app itself changes, not when adding a person or a page.

One-time setup on the droplet:

1. Create `/opt/dating_site/.env`. Same shape as `.env.example`, but the
   container reaches Postgres on the host, not through the tunnel:
   `DATABASE_URL=postgresql://dating:PASSWORD@host.docker.internal:5432/dating`,
   `APP_ENV=prod`, `PAGES_DIR=/srv/pages`, plus the Telegram credentials.
2. Add the server block in `deploy/nginx-dates.conf` to
   `/root/gym_junkie_server/nginx/nginx.conf.template`, then
   `ssh do docker restart nginx-proxy-prod`.
3. Add a proxied A record for `date.moates.com.au` in Cloudflare pointing at
   the droplet. The wildcard `*.moates.com.au` origin certificate already covers
   the subdomain, so there is no certificate work.

Then, for every release:

```bash
deploy/deploy.sh
```

Ships committed HEAD, rebuilds the container, applies migrations and verifies
the public endpoint.

## Tests

```bash
uv run pytest
```

Stateless: no database, no network. The request-path tests use a fake in place
of `app.db.Database`.

## Layout

| Path | |
| --- | --- |
| `app/main.py` | routes: serve bundle, context, submit; view logging |
| `app/submissions.py` | structural validation of posted JSON |
| `app/bundles.py` | path resolution, traversal guards |
| `app/db.py` / `app/admin.py` | request-path queries / CLI queries |
| `db_schema/migrations/` | numbered SQL, applied by `scripts/migrate.py` |
| `pages/_base/` | starter bundle, copied for each new person |
| `docker-compose.dev.yml` | local Postgres for development |
| `deploy/` | compose file, nginx block, deploy script |
