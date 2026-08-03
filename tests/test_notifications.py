from app.notifications import MAX_MESSAGE_CHARS, format_notification, format_view_notification


def test_includes_name_and_summary():
    message = format_notification(
        "Test Person One", "Rooftop cocktails · Friday", {"main": "rooftop"}, is_first=True
    )
    assert "Test Person One" in message
    assert "Rooftop cocktails · Friday" in message


def test_includes_the_raw_answers():
    message = format_notification(
        "Someone", "", {"main": "rooftop", "when": ["fri_pm"]}, is_first=True
    )
    assert "rooftop" in message
    assert "fri_pm" in message


def test_markdown_characters_are_left_alone():
    """Messages are sent without parse_mode, so nothing needs escaping."""
    message = format_notification(
        "Someone", "_underscores_ and *stars*", {"note": "a_b*c"}, is_first=True
    )
    assert "_underscores_ and *stars*" in message


def test_control_characters_are_stripped():
    message = format_notification("Someone\x07", "sum\x00mary", {"a": 1}, is_first=True)
    assert "\x07" not in message
    assert "\x00" not in message


def test_message_is_capped():
    answers = {f"key{index}": "x" * 200 for index in range(100)}
    message = format_notification("Someone", "s" * 400, answers, is_first=True)
    assert len(message) <= MAX_MESSAGE_CHARS


def test_handles_missing_summary():
    message = format_notification("Someone", "", {"a": 1}, is_first=True)
    assert "Someone" in message


def test_first_reply_reads_as_a_new_reply():
    message = format_notification("Someone", "Golf · Sunday", {"main": "golf"}, is_first=True)
    assert message.splitlines()[0] == "💌 Someone replied"


def test_later_reply_reads_as_a_change():
    message = format_notification("Someone", "Golf · Sunday", {"main": "golf"}, is_first=False)
    assert message.splitlines()[0] == "🔄 Someone changed their answer"


def test_a_view_reads_as_an_open():
    assert format_view_notification("Someone").splitlines()[0] == "👀 Someone opened the page"


def test_a_view_says_it_will_not_repeat():
    """The silence afterwards is the design, not a page that stopped working."""
    assert "no second view notification" in format_view_notification("Someone")


def test_a_view_notification_strips_control_characters():
    assert "\x07" not in format_view_notification("Someone\x07")


def test_a_view_notification_carries_no_answers():
    """An open says only that the page was opened; there is nothing to report yet."""
    message = format_view_notification("Someone")
    assert "{" not in message


def test_a_change_still_carries_every_detail():
    """A changed answer stands on its own: same body, different headline."""
    summary = "Hike · Sunday midday"
    answers = {"main": "hike", "sub": "easy", "when": ["sun_midday"]}

    first = format_notification("Someone", summary, answers, is_first=True)
    changed = format_notification("Someone", summary, answers, is_first=False)

    assert first.split("\n", 1)[1] == changed.split("\n", 1)[1]
    for detail in ("Hike · Sunday midday", "hike", "easy", "sun_midday"):
        assert detail in changed
