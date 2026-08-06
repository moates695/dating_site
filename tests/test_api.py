import logging

from conftest import TEST_TOKEN

UNKNOWN_TOKEN = "zzzzzzzz9999"
PAYLOAD = {"summary": "Rooftop cocktails · Friday", "answers": {"main": "rooftop", "when": ["fri_pm"]}}


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_robots_disallows_everything(client):
    assert "Disallow: /" in client.get("/robots.txt").text


def test_root_is_not_found(client):
    assert client.get("/").status_code == 404


def test_page_url_redirects_to_trailing_slash(client):
    response = client.get(f"/e/{TEST_TOKEN}", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == f"/e/{TEST_TOKEN}/"


def test_serves_the_index(client):
    response = client.get(f"/e/{TEST_TOKEN}/")
    assert response.status_code == 200
    assert "<h1>hello</h1>" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_serves_an_asset(client):
    response = client.get(f"/e/{TEST_TOKEN}/style.css")
    assert response.status_code == 200
    assert "color: red" in response.text


def test_security_headers_are_set(client):
    headers = client.get(f"/e/{TEST_TOKEN}/").headers
    assert headers["referrer-policy"] == "no-referrer"
    assert "noindex" in headers["x-robots-tag"]
    assert headers["x-content-type-options"] == "nosniff"


def test_unknown_token_is_not_found(client):
    assert client.get(f"/e/{UNKNOWN_TOKEN}/").status_code == 404


def test_malformed_token_is_not_found(client):
    assert client.get("/e/NOT-A-TOKEN/").status_code == 404


def test_traversal_is_rejected(client):
    assert client.get(f"/e/{TEST_TOKEN}/../secret.txt").status_code == 404
    assert client.get(f"/e/{TEST_TOKEN}/%2e%2e/secret.txt").status_code == 404


def test_context_before_any_response(client):
    body = client.get(f"/api/e/{TEST_TOKEN}/context").json()
    assert body == {"display_name": "Test Person One", "submitted": False, "submitted_at": None}


def test_context_for_unknown_token(client):
    assert client.get(f"/api/e/{UNKNOWN_TOKEN}/context").status_code == 404


def test_submit_stores_the_response(client, fake_db):
    response = client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    assert len(fake_db.responses) == 1
    stored = fake_db.responses[0]
    assert stored["answers"] == PAYLOAD["answers"]
    assert stored["summary"] == PAYLOAD["summary"]


def test_submit_accepts_an_arbitrary_answer_shape(client, fake_db):
    """A page can invent any structure it likes without a server change."""
    answers = {"ranked": ["a", "b"], "meta": {"opened": 3, "device": "phone"}, "yes": True}
    client.post(f"/api/e/{TEST_TOKEN}/submit", json={"summary": "x", "answers": answers})
    assert fake_db.responses[0]["answers"] == answers


def test_context_reflects_a_submission(client):
    client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD)
    body = client.get(f"/api/e/{TEST_TOKEN}/context").json()
    assert body["submitted"] is True
    assert body["submitted_at"] is not None


def test_submit_rejects_a_bad_payload(client, fake_db):
    response = client.post(f"/api/e/{TEST_TOKEN}/submit", json={"answers": "nope"})
    assert response.status_code == 400
    assert fake_db.responses == []


def test_submit_for_unknown_token(client, fake_db):
    assert client.post(f"/api/e/{UNKNOWN_TOKEN}/submit", json=PAYLOAD).status_code == 404
    assert fake_db.responses == []


def test_submit_is_rate_limited(client):
    for _ in range(10):
        assert client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD).status_code == 200
    assert client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD).status_code == 429


def test_notification_is_skipped_when_telegram_is_unconfigured(client, fake_db):
    """Storing must succeed regardless; only notified_at is left unset."""
    client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD)
    assert len(fake_db.responses) == 1
    assert fake_db.notified == []


def test_first_submit_notifies_as_a_new_reply(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.main"):
        client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD)
    assert "💌 Test Person One replied" in caplog.text


def test_a_later_submit_notifies_as_a_change(client, caplog):
    """Reopening the form and sending again is a change, not a new reply."""
    client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD)

    with caplog.at_level(logging.INFO, logger="app.main"):
        caplog.clear()
        client.post(f"/api/e/{TEST_TOKEN}/submit", json=PAYLOAD)

    assert "🔄 Test Person One changed their answer" in caplog.text
    assert "replied" not in caplog.text
