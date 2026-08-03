-- Core schema.
--
-- Only the columns needing an index or a listing are typed. A page's content
-- is a static bundle on disk and a response's shape is whatever that bundle's
-- JavaScript chose to send, so neither is modelled here.

create table people (
    id           bigserial primary key,
    token        text        not null unique,
    display_name text        not null,
    created_at   timestamptz not null default now()
);

create table pages (
    id           bigserial   primary key,
    person_id    bigint      not null references people (id) on delete cascade,
    version      integer     not null,
    -- Path relative to PAGES_DIR, e.g. 'k7m2xq9fh3bd/v3'.
    bundle_dir   text        not null,
    is_live      boolean     not null default false,
    published_at timestamptz not null default now(),
    unique (person_id, version)
);

-- At most one live page per person; publishing is "flip the pointer".
create unique index pages_one_live_per_person on pages (person_id) where is_live;

create table responses (
    id          bigserial   primary key,
    -- Deliberately references the page version, not the person: the answer keys
    -- only mean something in the context of the bundle that produced them.
    page_id     bigint      not null references pages (id) on delete cascade,
    summary     text,
    answers     jsonb       not null,
    created_at  timestamptz not null default now(),
    -- Null means the Telegram send failed; the row is still safely stored.
    notified_at timestamptz
);

create index responses_page_created on responses (page_id, created_at desc);
create index responses_unnotified on responses (created_at) where notified_at is null;
