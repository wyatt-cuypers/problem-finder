import math

from problem_finder import db
from problem_finder.score import score_cluster, run_score
from tests.test_db import make_item

DAY = 86400
END = 1_750_000_000
START = END - 365 * DAY


def member(thread="t1", author="a1", sub="running", created=END - DAY,
           sol="none", wish=0):
    return dict(thread_id=thread, author_hash=author, subreddit=sub,
                created_utc=created, solution_mentioned=sol,
                wish_expressed=wish)


def spread_members(n=6, sol="none", wish=0, span_days=300):
    return [member(thread=f"t{i}", author=f"a{i}",
                   created=END - i * span_days * DAY // n, sol=sol, wish=wish)
            for i in range(n)]


def test_gate_requires_3_threads_and_3_authors():
    same_thread = [member(thread="t1", author=f"a{i}") for i in range(5)]
    assert score_cluster(same_thread, START, END)["passes_gate"] == 0
    same_author = [member(thread=f"t{i}", author="a1") for i in range(5)]
    assert score_cluster(same_author, START, END)["passes_gate"] == 0
    assert score_cluster(spread_members(), START, END)["passes_gate"] == 1


def test_adequate_solutions_drop_cluster_and_lower_unsolvedness():
    solved = spread_members(6, sol="mentioned-adequate")
    s = score_cluster(solved, START, END)
    assert s["passes_gate"] == 0  # adequate share 1.0 > 0.5
    assert s["unsolvedness"] == 0.0
    partial = [member(thread=f"t{i}", author=f"a{i}",
                      sol="mentioned-adequate" if i < 2 else "none",
                      created=END - i * DAY) for i in range(6)]
    s = score_cluster(partial, START, END)
    assert s["passes_gate"] == 1
    assert abs(s["unsolvedness"] - 4 / 6) < 1e-9


def test_wishes_boost_unsolvedness_capped_at_1():
    members = [member(thread=f"t{i}", author=f"a{i}", wish=1,
                      created=END - i * DAY) for i in range(6)]
    assert score_cluster(members, START, END)["unsolvedness"] == 1.0


def test_recency_and_spike():
    recent = [member(thread=f"t{i}", author=f"a{i}", created=END - i * DAY)
              for i in range(4)]
    s = score_cluster(recent, START, END)
    assert s["spike_flag"] == 1  # 4 mentions within 3 days of a 365-day window
    expected = math.log1p(4) * 1.0 * 1.0
    assert abs(s["composite"] - expected) < 1e-9
    old = [member(thread=f"t{i}", author=f"a{i}",
                  created=START + i * 30 * DAY) for i in range(4)]
    s = score_cluster(old, START, END)
    assert s["spike_flag"] == 0
    assert abs(s["composite"] - math.log1p(4) * 0.6 * 1.0) < 1e-9


def test_run_score_writes_rows():
    conn = db.connect(":memory:")
    items = [make_item(f"i{k}", thread_id=f"t{k}", author_hash=f"a{k}",
                       created_utc=END - k * DAY) for k in range(4)]
    db.upsert_items(conn, items)
    for k in range(4):
        conn.execute("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"i{k}", "ok", 1, "s", "other", "none", None, 0, 1))
    conn.execute("INSERT INTO clusters (id) VALUES (1)")
    conn.executemany("INSERT INTO cluster_members VALUES (?,1)",
                     [(f"i{k}",) for k in range(4)])
    conn.commit()

    class Cfg:
        window_days = 365

    run_score(conn, Cfg())
    row = conn.execute("SELECT * FROM cluster_scores").fetchone()
    assert row["mentions"] == 4 and row["passes_gate"] == 1
