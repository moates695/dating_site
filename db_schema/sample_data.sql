-- Synthetic sample rows for reference only.
--
-- IMPORTANT: this repo is public. Everything in this file is invented. Never
-- paste real names, tokens or responses here. Use `scripts/list_people.py`
-- against the database if you want to see actual data.

insert into people (token, display_name) values
    ('aaaa1111bbbb', 'Test Person One'),
    ('cccc2222dddd', 'Test Person Two');

insert into pages (person_id, version, bundle_dir, is_live) values
    ((select id from people where token = 'aaaa1111bbbb'), 1, 'aaaa1111bbbb/v1', true),
    ((select id from people where token = 'cccc2222dddd'), 1, 'cccc2222dddd/v1', true);

insert into responses (page_id, summary, answers) values
    (
        (select id from pages where bundle_dir = 'aaaa1111bbbb/v1'),
        'Placeholder Activity · Friday evening',
        '{"main": "placeholder_activity", "when": ["fri_pm"], "note": "Sample note."}'::jsonb
    );
