import json

import pytest

from app.submissions import (
    MAX_ITEMS_PER_ARRAY,
    MAX_KEYS_PER_OBJECT,
    MAX_PAYLOAD_BYTES,
    MAX_STRING_CHARS,
    MAX_SUMMARY_CHARS,
    SubmissionError,
    clean_text,
    parse_submission,
)


def body(payload) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_accepts_a_typical_payload():
    submission = parse_submission(
        body({"summary": "Rooftop cocktails · Friday", "answers": {"main": "rooftop", "when": ["fri_pm"]}})
    )
    assert submission.summary == "Rooftop cocktails · Friday"
    assert submission.answers == {"main": "rooftop", "when": ["fri_pm"]}


def test_summary_is_optional():
    assert parse_submission(body({"answers": {"a": 1}})).summary == ""


def test_arbitrary_answer_shapes_are_preserved():
    """The server must not care what a page chooses to send."""
    answers = {"nested": {"deep": [1, 2, {"ok": True}]}, "flag": False, "score": 4.5, "empty": None}
    assert parse_submission(body({"answers": answers})).answers == answers


@pytest.mark.parametrize(
    "payload",
    [
        [1, 2, 3],
        "a string",
        42,
        {"answers": "not an object"},
        {"answers": []},
        {"answers": {}},
        {"answers": {"a": 1}, "summary": 5},
    ],
)
def test_rejects_malformed_payloads(payload):
    with pytest.raises(SubmissionError):
        parse_submission(body(payload))


def test_rejects_invalid_json():
    with pytest.raises(SubmissionError):
        parse_submission(b"{not json")


def test_rejects_oversized_payload():
    with pytest.raises(SubmissionError, match="too large"):
        parse_submission(b"x" * (MAX_PAYLOAD_BYTES + 1))


def test_rejects_overlong_string_value():
    with pytest.raises(SubmissionError, match="too long"):
        parse_submission(body({"answers": {"note": "x" * (MAX_STRING_CHARS + 1)}}))


def test_rejects_too_many_keys():
    answers = {f"k{index}": index for index in range(MAX_KEYS_PER_OBJECT + 1)}
    with pytest.raises(SubmissionError, match="too many keys"):
        parse_submission(body({"answers": answers}))


def test_rejects_too_many_array_items():
    answers = {"picks": list(range(MAX_ITEMS_PER_ARRAY + 1))}
    with pytest.raises(SubmissionError, match="too many items"):
        parse_submission(body({"answers": answers}))


def test_rejects_deeply_nested_payload():
    nested: dict = {"end": True}
    for _ in range(20):
        nested = {"next": nested}
    with pytest.raises(SubmissionError, match="too deeply"):
        parse_submission(body({"answers": nested}))


def test_summary_is_truncated_and_stripped():
    submission = parse_submission(body({"summary": "  y" * 800, "answers": {"a": 1}}))
    assert len(submission.summary) <= MAX_SUMMARY_CHARS


def test_clean_text_removes_control_characters():
    assert clean_text("a\x00b\x07c", 100) == "abc"


def test_clean_text_keeps_newlines_and_tabs():
    assert clean_text("a\nb\tc", 100) == "a\nb\tc"


def test_clean_text_truncates_with_ellipsis():
    assert clean_text("abcdef", 4).endswith("…")
    assert len(clean_text("abcdef", 4)) == 4
