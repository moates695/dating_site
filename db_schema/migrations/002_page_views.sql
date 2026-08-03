-- Page views.
--
-- Two kinds of view are recorded and they are not equivalent. A 'fetch' is a
-- request for the page HTML, which any link-preview crawler makes the moment
-- the URL is sent in a message. A 'load' is the context call the page makes
-- from JavaScript once it is running in a real browser. Only a 'load' is
-- evidence that a person opened the page, and only a 'load' is ever notified.
--
-- Views the owner made are stored too, flagged rather than dropped, so a
-- mis-flagged visit is visible after the fact instead of vanishing.

create table page_views (
    id          bigserial   primary key,
    page_id     bigint      not null references pages (id) on delete cascade,
    -- 'fetch' (page HTML requested) | 'load' (JavaScript ran and asked for context)
    kind        text        not null,
    -- True when the request carried the owner's marker in its query string.
    is_self     boolean     not null default false,
    -- sha256 of the page token and the address, never the address itself.
    ip_hash     text,
    user_agent  text,
    viewed_at   timestamptz not null default now(),
    -- Set only on the one view that triggered a notification.
    notified_at timestamptz
);

create index page_views_page_time on page_views (page_id, viewed_at desc);

-- Supports the "has anyone but me really opened this yet" count taken on every
-- load, which is the question the whole table exists to answer.
create index page_views_notifiable on page_views (page_id) where kind = 'load' and not is_self;
