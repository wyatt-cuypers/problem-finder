import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    author_hash TEXT,
    created_utc INTEGER NOT NULL,
    score INTEGER,
    text TEXT NOT NULL,
    permalink TEXT
);
CREATE TABLE IF NOT EXISTS coverage (
    subreddit TEXT NOT NULL,
    run_ts INTEGER NOT NULL,
    oldest_utc INTEGER,
    newest_utc INTEGER,
    post_count INTEGER,
    comment_count INTEGER
);
CREATE TABLE IF NOT EXISTS extractions (
    item_id TEXT PRIMARY KEY REFERENCES items(id),
    status TEXT NOT NULL,
    is_problem INTEGER,
    problem_statement TEXT,
    category TEXT,
    solution_mentioned TEXT,
    solution_notes TEXT,
    wish_expressed INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS embeddings (
    item_id TEXT PRIMARY KEY REFERENCES items(id),
    vector BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    canonical_statement TEXT,
    solution_summary TEXT,
    opportunity_note TEXT,
    coherence_flag INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cluster_members (
    item_id TEXT PRIMARY KEY REFERENCES items(id),
    cluster_id INTEGER NOT NULL REFERENCES clusters(id)
);
CREATE TABLE IF NOT EXISTS cluster_scores (
    cluster_id INTEGER PRIMARY KEY REFERENCES clusters(id),
    mentions INTEGER,
    threads INTEGER,
    authors INTEGER,
    subreddits INTEGER,
    first_seen INTEGER,
    last_seen INTEGER,
    spike_flag INTEGER,
    unsolvedness REAL,
    composite REAL,
    passes_gate INTEGER
);
"""

ITEM_COLS = ["id", "type", "subreddit", "thread_id", "author_hash",
             "created_utc", "score", "text", "permalink"]


def connect(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    cur = conn.executemany(
        f"INSERT OR IGNORE INTO items ({','.join(ITEM_COLS)}) "
        f"VALUES ({','.join(':' + c for c in ITEM_COLS)})",
        items,
    )
    conn.commit()
    return cur.rowcount
