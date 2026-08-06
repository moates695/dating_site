"""Page view logging.

The distinction these tests exist to protect: requesting the HTML is not the
same as opening the page. A messaging app fetches the HTML to build a link
preview the moment the URL is sent, so only the JavaScript context call counts
as a person opening it, and only that call can notify.
"""

import hashlib
import logging

from conftest import TEST_TOKEN

UNKNOWN_TOKEN = "zzzzzzzz9999"
OPENED = "👀 Test Person One opened the page"


def _hash(ip: str, token: str = TEST_TOKEN) -> str:
    return hashlib.sha256(f"{token}:{ip}".encode()).hexdigest()


def test_requesting_the_page_records_a_fetch(client, fake_db):
    client.get(f"/e/{TEST_TOKEN}/")
    assert [v["kind"] for v in fake_db.views] == ["fetch"]


def test_assets_are_not_recorded(client, fake_db):
    """One open should be one row, not one per stylesheet."""
    client.get(f"/e/{TEST_TOKEN}/style.css")
    assert fake_db.views == []


def test_the_context_call_records_a_load(client, fake_db):
    client.get(f"/api/e/{TEST_TOKEN}/context")
    assert [v["kind"] for v in fake_db.views] == ["load"]


def test_a_link_preview_never_notifies(client, caplog):
    """A crawler fetches the HTML and stops there; that is not an open."""
    with caplog.at_level(logging.INFO, logger="app.main"):
        client.get(f"/e/{TEST_TOKEN}/")
    assert OPENED not in caplog.text


def test_the_first_load_notifies(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.main"):
        client.get(f"/api/e/{TEST_TOKEN}/context")
    assert OPENED in caplog.text


def test_a_second_load_does_not_notify(client, caplog):
    """First view only: coming back must stay silent."""
    client.get(f"/api/e/{TEST_TOKEN}/context")

    with caplog.at_level(logging.INFO, logger="app.main"):
        caplog.clear()
        client.get(f"/api/e/{TEST_TOKEN}/context")

    assert OPENED not in caplog.text


def test_your_own_visit_is_flagged_and_silent(client, fake_db, caplog):
    with caplog.at_level(logging.INFO, logger="app.main"):
        client.get(f"/api/e/{TEST_TOKEN}-test/context")

    assert fake_db.views[0]["is_self"] is True
    assert OPENED not in caplog.text


def test_your_own_visit_does_not_use_up_the_notification(client, caplog):
    """Checking the page yourself must not make their real open look like a repeat."""
    client.get(f"/e/{TEST_TOKEN}-test/")
    client.get(f"/api/e/{TEST_TOKEN}-test/context")

    with caplog.at_level(logging.INFO, logger="app.main"):
        caplog.clear()
        client.get(f"/api/e/{TEST_TOKEN}/context")

    assert OPENED in caplog.text


def test_a_wrong_marker_is_not_you(client, fake_db, caplog):
    """Only the exact suffix counts; anything else is just an unknown token."""
    with caplog.at_level(logging.INFO, logger="app.main"):
        response = client.get(f"/api/e/{TEST_TOKEN}-live/context")

    assert response.status_code == 404
    assert fake_db.views == []
    assert OPENED not in caplog.text


def test_the_marker_is_recorded_on_the_page_request_too(client, fake_db):
    client.get(f"/e/{TEST_TOKEN}-test/")
    assert fake_db.views[0]["is_self"] is True


def test_the_marked_page_serves_the_same_bundle(client):
    """The suffix only marks the visit; it must not change what is served."""
    marked = client.get(f"/e/{TEST_TOKEN}-test/")
    plain = client.get(f"/e/{TEST_TOKEN}/")

    assert marked.status_code == 200
    assert marked.text == plain.text


def test_assets_resolve_under_the_marked_url(client):
    """Bundle assets are relative, so they arrive with the suffix still attached."""
    assert client.get(f"/e/{TEST_TOKEN}-test/style.css").status_code == 200


def test_a_submission_from_the_marked_url_still_lands(client, fake_db):
    """The page posts from whatever URL it was opened at."""
    response = client.post(
        f"/api/e/{TEST_TOKEN}-test/submit",
        json={"summary": "Rooftop cocktails", "answers": {"main": "rooftop"}},
    )

    assert response.status_code == 200
    assert len(fake_db.responses) == 1


def test_the_address_is_hashed_not_stored(client, fake_db):
    client.get(f"/api/e/{TEST_TOKEN}/context", headers={"cf-connecting-ip": "203.0.113.9"})

    stored = fake_db.views[0]["ip_hash"]
    assert stored == _hash("203.0.113.9")
    assert "203.0.113.9" not in stored


def test_the_cloudflare_address_wins(client, fake_db):
    """Behind Cloudflare the socket peer is an edge address, not the visitor."""
    client.get(
        f"/api/e/{TEST_TOKEN}/context",
        headers={"cf-connecting-ip": "203.0.113.9", "x-forwarded-for": "198.51.100.4"},
    )
    assert fake_db.views[0]["ip_hash"] == _hash("203.0.113.9")


def test_the_client_is_the_first_forwarded_entry(client, fake_db):
    client.get(
        f"/api/e/{TEST_TOKEN}/context",
        headers={"x-forwarded-for": "198.51.100.4, 172.16.0.1"},
    )
    assert fake_db.views[0]["ip_hash"] == _hash("198.51.100.4")


def test_the_user_agent_is_recorded_and_capped(client, fake_db):
    client.get(f"/api/e/{TEST_TOKEN}/context", headers={"user-agent": "x" * 500})
    assert len(fake_db.views[0]["user_agent"]) == 300


def test_a_failed_write_does_not_break_the_page(client, fake_db):
    """Knowing a page was opened is never worth breaking the page over."""
    fake_db.record_view_fails = True

    assert client.get(f"/e/{TEST_TOKEN}/").status_code == 200
    assert client.get(f"/api/e/{TEST_TOKEN}/context").status_code == 200


def test_an_unknown_token_records_nothing(client, fake_db):
    client.get(f"/e/{UNKNOWN_TOKEN}/")
    client.get(f"/api/e/{UNKNOWN_TOKEN}/context")
    assert fake_db.views == []


def _client_with_telegram(settings, fake_db, monkeypatch, *, succeeds: bool):
    """A client whose Telegram send is faked, returning the messages sent."""
    import dataclasses

    from fastapi.testclient import TestClient

    import app.main
    from app.main import create_app

    sent: list[str] = []

    async def fake_send(bot_token: str, chat_id: str, message: str) -> bool:
        sent.append(message)
        return succeeds

    monkeypatch.setattr(app.main, "send_notification", fake_send)
    configured = dataclasses.replace(settings, telegram_bot_token="t", telegram_chat_id="c")
    return TestClient(create_app(configured, db=fake_db)), sent


def test_a_sent_notification_marks_the_view(settings, fake_db, monkeypatch):
    client, sent = _client_with_telegram(settings, fake_db, monkeypatch, succeeds=True)

    with client:
        client.get(f"/api/e/{TEST_TOKEN}/context")

    assert len(sent) == 1
    assert OPENED in sent[0]
    assert fake_db.notified_views == [1]


def test_a_failed_send_leaves_the_view_unmarked(settings, fake_db, monkeypatch):
    """notified_at stays null, which is how you find a view that never announced."""
    client, sent = _client_with_telegram(settings, fake_db, monkeypatch, succeeds=False)

    with client:
        response = client.get(f"/api/e/{TEST_TOKEN}/context")

    assert response.status_code == 200
    assert len(sent) == 1
    assert fake_db.notified_views == []
