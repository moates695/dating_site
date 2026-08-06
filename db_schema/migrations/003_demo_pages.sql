-- Demo pages.
--
-- One page is public: it is linked from a GitHub profile, so strangers open it
-- rather than one invited recipient. That breaks three assumptions this schema was
-- built on, all of which follow from "a page belongs to one person":
--
--   the confirmation screen is shown to anyone visiting a page that has any
--   response, which would put every visitor after the first on it;
--
--   the first real open is worth a notification, which here would be a stream
--   of them;
--
--   the submission allowance is per page, which strangers would share.
--
-- The flag lives on people rather than pages because it describes the link, not
-- one published version of it, and so republishing cannot silently drop it.

alter table people add column is_demo boolean not null default false;

-- Partial rather than plain: there is one demo row among all the real ones, so
-- the index stays tiny and the planner can find it without a scan.
create index people_demo on people (id) where is_demo;
