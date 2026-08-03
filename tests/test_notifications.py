from app.notifications import MAX_MESSAGE_CHARS, format_notification


def test_includes_name_and_summary():
    message = format_notification("Test Person One", "Rooftop cocktails · Friday", {"main": "rooftop"})
    assert "Test Person One" in message
    assert "Rooftop cocktails · Friday" in message


def test_includes_the_raw_answers():
    message = format_notification("Someone", "", {"main": "rooftop", "when": ["fri_pm"]})
    assert "rooftop" in message
    assert "fri_pm" in message


def test_markdown_characters_are_left_alone():
    """Messages are sent without parse_mode, so nothing needs escaping."""
    message = format_notification("Someone", "_underscores_ and *stars*", {"note": "a_b*c"})
    assert "_underscores_ and *stars*" in message


def test_control_characters_are_stripped():
    message = format_notification("Someone\x07", "sum\x00mary", {"a": 1})
    assert "\x07" not in message
    assert "\x00" not in message


def test_message_is_capped():
    answers = {f"key{index}": "x" * 200 for index in range(100)}
    message = format_notification("Someone", "s" * 400, answers)
    assert len(message) <= MAX_MESSAGE_CHARS


def test_handles_missing_summary():
    message = format_notification("Someone", "", {"a": 1})
    assert "Someone" in message
