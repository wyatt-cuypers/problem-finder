import pytest

from problem_finder.gemini import with_retries


def test_with_retries_succeeds_after_failures():
    calls = {"n": 0}
    delays: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    assert with_retries(flaky, attempts=3, sleep=delays.append) == "ok"
    assert calls["n"] == 3
    assert delays == [2.0, 4.0]  # exponential backoff


def test_with_retries_reraises_after_final_attempt():
    def always_fails():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        with_retries(always_fails, attempts=3, sleep=lambda _: None)
