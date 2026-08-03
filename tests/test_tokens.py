from app.tokens import TOKEN_ALPHABET, TOKEN_LENGTH, generate_token, is_valid_token


def test_generated_token_has_expected_length():
    assert len(generate_token()) == TOKEN_LENGTH


def test_generated_tokens_use_only_the_alphabet():
    for _ in range(200):
        assert set(generate_token()) <= set(TOKEN_ALPHABET)


def test_alphabet_excludes_ambiguous_characters():
    for character in "01ilo":
        assert character not in TOKEN_ALPHABET


def test_generated_tokens_are_not_repeated():
    tokens = {generate_token() for _ in range(500)}
    assert len(tokens) == 500


def test_valid_token_accepts_generated_tokens():
    assert is_valid_token(generate_token())


def test_valid_token_rejects_bad_input():
    assert not is_valid_token("")
    assert not is_valid_token("../../etc/passwd")
    assert not is_valid_token("UPPERCASE1234")
    assert not is_valid_token("has spaces!!")
    assert not is_valid_token("o" * 65)
