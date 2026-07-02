from problem_finder.collect import hash_author, keep_text, window_bounds

LONG = "word " * 20  # 20 words


def test_keep_text_rejects_short_deleted_and_bots():
    assert keep_text(LONG, "someuser", 15) is True
    assert keep_text("too short", "someuser", 15) is False
    assert keep_text(None, "someuser", 15) is False
    assert keep_text("[deleted]", "someuser", 15) is False
    assert keep_text("[removed]", "someuser", 15) is False
    assert keep_text(LONG, "AutoModerator", 15) is False
    assert keep_text(LONG, "RemindMeBot", 15) is False
    assert keep_text(LONG, None, 15) is False  # deleted account


def test_hash_author_is_stable_and_anonymous():
    h = hash_author("SomeUser")
    assert h == hash_author("someuser")  # case-insensitive
    assert h != "someuser" and len(h) == 16
    assert hash_author(None) is None


def test_window_bounds():
    start, end = window_bounds(14, now=1_750_000_000)
    assert end == 1_750_000_000
    assert start == 1_750_000_000 - 14 * 86400
