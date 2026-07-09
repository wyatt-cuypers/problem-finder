import math

DAY = 86400
SPIKE_SPAN = 14 * DAY          # all mentions within 2 weeks...
SPIKE_MIN_WINDOW = 42 * DAY    # ...of a window longer than 6 weeks
WISH_BOOST = 0.05              # per wish, capped
WISH_BOOST_CAP = 0.15
STALE_RECENCY = 0.6            # weight when not active in last quarter
MAX_ADEQUATE_SHARE = 0.5


def score_cluster(members: list[dict], window_start: int,
                  window_end: int) -> dict:
    mentions = len(members)
    threads = len({m["thread_id"] for m in members})
    authors = len({m["author_hash"] for m in members if m["author_hash"]})
    subreddits = len({m["subreddit"] for m in members})
    dates = sorted(m["created_utc"] for m in members)
    first_seen, last_seen = dates[0], dates[-1]

    n_adequate = sum(m["solution_mentioned"] == "mentioned-adequate"
                     for m in members)
    n_wishes = sum(bool(m["wish_expressed"]) for m in members)
    adequate_share = n_adequate / mentions
    unsolvedness = min(1.0, (mentions - n_adequate) / mentions
                       + min(WISH_BOOST_CAP, WISH_BOOST * n_wishes))
    if adequate_share > MAX_ADEQUATE_SHARE:
        unsolvedness = 0.0

    window_len = window_end - window_start
    recency = 1.0 if last_seen >= window_end - window_len // 4 else STALE_RECENCY
    spike = int(window_len > SPIKE_MIN_WINDOW
                and last_seen - first_seen <= SPIKE_SPAN)
    passes = int(threads >= 3 and authors >= 3
                 and adequate_share <= MAX_ADEQUATE_SHARE)
    composite = math.log1p(mentions) * recency * unsolvedness
    return dict(mentions=mentions, threads=threads, authors=authors,
                subreddits=subreddits, first_seen=first_seen,
                last_seen=last_seen, spike_flag=spike,
                unsolvedness=unsolvedness, composite=composite,
                passes_gate=passes)


MEMBERS_SQL = """\
SELECT cm.cluster_id, i.thread_id, i.author_hash, i.subreddit, i.created_utc,
       e.solution_mentioned, e.wish_expressed
FROM cluster_members cm
JOIN items i ON i.id = cm.item_id
JOIN extractions e ON e.item_id = cm.item_id
ORDER BY cm.cluster_id"""


def run_score(conn, cfg) -> None:
    end = conn.execute("SELECT MAX(created_utc) AS m FROM items").fetchone()["m"]
    if end is None:
        print("score: no items")
        return
    start = end - cfg.window_days * DAY
    by_cluster: dict[int, list[dict]] = {}
    for r in conn.execute(MEMBERS_SQL):
        by_cluster.setdefault(r["cluster_id"], []).append(dict(r))
    conn.execute("DELETE FROM cluster_scores")
    for cid, members in by_cluster.items():
        s = score_cluster(members, start, end)
        conn.execute(
            "INSERT INTO cluster_scores VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, s["mentions"], s["threads"], s["authors"], s["subreddits"],
             s["first_seen"], s["last_seen"], s["spike_flag"],
             s["unsolvedness"], s["composite"], s["passes_gate"]))
    conn.commit()
    n_pass = conn.execute(
        "SELECT COUNT(*) AS n FROM cluster_scores WHERE passes_gate=1"
    ).fetchone()["n"]
    print(f"score: {len(by_cluster)} clusters scored, {n_pass} pass gates")
