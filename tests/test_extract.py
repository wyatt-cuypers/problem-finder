from problem_finder import db
from problem_finder.extract import (build_extract_prompt,
                                    parse_extraction_response, run_extract)
from tests.test_db import make_item


def test_build_prompt_numbers_items_and_truncates():
    prompt = build_extract_prompt(["short text", "x" * 5000])
    assert "[0] short text" in prompt
    assert "[1] " + "x" * 1500 in prompt
    assert "x" * 1501 not in prompt
    assert "de-contextualized" in prompt


def test_parse_response_aligns_by_index_and_fills_defaults():
    data = [
        {"index": 1, "is_problem": True,
         "problem_statement": "running shoes wear out too quickly",
         "category": "fitness", "solution_mentioned": "mentioned-inadequate",
         "solution_notes": "rotating pairs helps but is expensive",
         "wish_expressed": False},
        {"index": 5, "is_problem": False},  # out of range: ignored
    ]
    rows = parse_extraction_response(data, n_items=2)
    assert rows[0] is None  # model skipped item 0
    assert rows[1]["is_problem"] is True
    assert rows[1]["solution_mentioned"] == "mentioned-inadequate"


def test_parse_response_rejects_non_list():
    import pytest
    with pytest.raises(ValueError):
        parse_extraction_response({"not": "a list"}, 1)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Cfg:
    extract_batch_size = 20


def _resp(index, statement):
    return {"index": index, "is_problem": True, "problem_statement": statement,
            "category": "fitness", "solution_mentioned": "none",
            "solution_notes": None, "wish_expressed": False}


def test_run_extract_persists_and_resumes():
    conn = db.connect(":memory:")
    db.upsert_items(conn, [make_item("c1"), make_item("c2")])
    client = FakeClient([[_resp(0, "s1"), _resp(1, "s2")]])
    run_extract(conn, Cfg(), client)
    rows = conn.execute(
        "SELECT * FROM extractions ORDER BY item_id").fetchall()
    assert [r["status"] for r in rows] == ["ok", "ok"]
    assert rows[0]["problem_statement"] == "s1"
    # second run: nothing left to do, no new calls
    run_extract(conn, Cfg(), client)
    assert len(client.prompts) == 1


def test_run_extract_marks_failed_batch_and_gives_up_after_3_attempts():
    conn = db.connect(":memory:")
    db.upsert_items(conn, [make_item("c1")])
    client = FakeClient([RuntimeError(), RuntimeError(), RuntimeError()])
    run_extract(conn, Cfg(), client)
    row = conn.execute("SELECT * FROM extractions").fetchone()
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    run_extract(conn, Cfg(), client)  # no responses left; must not call again
    assert len(client.prompts) == 3
