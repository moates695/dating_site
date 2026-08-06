"""The public demo page.

Every other page belongs to one person, and three behaviours follow from that:
the stored answer is shown back as a confirmation, the first real open is worth
a notification, and the submission allowance is per page. A page linked from a
public profile is opened by strangers who share nothing but the URL, so all
three have to be turned off together. These tests pin each one.
"""

import logging

from conftest import TEST_TOKEN

SUBMISSION = {"summary": "Coffee", "answers": {"main": "coffee"}}


def _submit(client, token: str = TEST_TOKEN):
    return client.post(f"/api/e/{token}/submit", json=SUBMISSION)


def test_a_visitor_never_sees_the_previous_one_s_answer(demo_client, demo_db):
    """The failure this exists to prevent: visitor two landing on the done screen."""
    _submit(demo_client)

    context = demo_client.get(f"/api/e/{TEST_TOKEN}/context").json()

    assert len(demo_db.responses) == 1
    assert context["submitted"] is False
    assert context["submitted_at"] is None


def test_a_normal_page_still_shows_the_answer_back(client):
    """The demo is the exception; a personal page must keep its confirmation."""
    _submit(client)
    assert client.get(f"/api/e/{TEST_TOKEN}/context").json()["submitted"] is True


def test_opening_the_demo_never_notifies(demo_client, caplog):
    with caplog.at_level(logging.INFO, logger="app.main"):
        demo_client.get(f"/api/e/{TEST_TOKEN}/context")

    assert "opened the page" not in caplog.text


def test_demo_opens_are_still_recorded(demo_client, demo_db):
    """Silent, not invisible: the traffic stays visible after the fact."""
    demo_client.get(f"/api/e/{TEST_TOKEN}/context")
    assert [v["kind"] for v in demo_db.views] == ["load"]


def test_submitting_to_the_demo_never_notifies(demo_client, caplog):
    with caplog.at_level(logging.INFO, logger="app.main"):
        _submit(demo_client)

    assert "telegram not configured" not in caplog.text


def test_the_demo_still_stores_what_was_sent(demo_client, demo_db):
    assert _submit(demo_client).status_code == 200
    assert demo_db.responses[0]["answers"] == {"main": "coffee"}


def test_one_visitor_cannot_use_up_everyone_s_allowance(demo_client):
    """Metered per visitor, so a stranger hammering it cannot close the page."""
    for _ in range(12):
        _submit(demo_client, TEST_TOKEN)

    # A different address is a different bucket, so it is unaffected.
    other = demo_client.post(
        f"/api/e/{TEST_TOKEN}/submit",
        json=SUBMISSION,
        headers={"cf-connecting-ip": "203.0.113.77"},
    )
    assert other.status_code == 200


def test_a_single_demo_visitor_is_still_limited(demo_client):
    """Per visitor is still a limit; the endpoint does not become a free-for-all."""
    codes = [_submit(demo_client).status_code for _ in range(12)]
    assert codes[-1] == 429
