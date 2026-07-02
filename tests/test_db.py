from problem_finder import db


def make_item(i: str, **kw) -> dict:
    d = dict(id=i, type="comment", subreddit="running", thread_id="t1",
             author_hash="a1", created_utc=1750000000, score=5,
             text="my shoes wear out fast", permalink="/r/running/x")
    d.update(kw)
    return d


def test_connect_creates_schema_and_upsert_ignores_dupes():
    conn = db.connect(":memory:")
    n = db.upsert_items(conn, [make_item("c1"), make_item("c2")])
    assert n == 2
    n = db.upsert_items(conn, [make_item("c1"), make_item("c3")])
    assert n == 1
    rows = conn.execute("SELECT id FROM items ORDER BY id").fetchall()
    assert [r["id"] for r in rows] == ["c1", "c2", "c3"]


def test_all_tables_exist():
    conn = db.connect(":memory:")
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"items", "coverage", "extractions", "embeddings",
            "clusters", "cluster_members", "cluster_scores"} <= names
