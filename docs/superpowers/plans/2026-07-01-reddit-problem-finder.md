# Reddit Problem Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI pipeline that mines Reddit for recurring, unsolved problems and produces a ranked top-50 xlsx report plus a markdown summary.

**Architecture:** Five idempotent stages (`collect → extract → cluster → score → report`) backed by a SQLite store. Each stage processes only rows not yet handled, so failures resume. API-touching code (PRAW, Gemini) lives in thin wrappers; all filtering/scoring/parsing logic is pure and unit-tested.

**Tech Stack:** Python 3.11+, praw, google-genai, scikit-learn (HDBSCAN), numpy, openpyxl, pyyaml, python-dotenv, pytest.

## Global Constraints

- Package lives in `src/problem_finder/`; installed editable; console script `pf`.
- Models: `gemini-2.5-flash` (extraction/summaries), `gemini-embedding-001` (embeddings) — configurable via yaml.
- Secrets only from `.env`: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `GEMINI_API_KEY`. Never committed (`.env` is gitignored).
- `data/` and `output/` are gitignored (already in `.gitignore`).
- Recurring gate: ≥ 3 distinct threads AND ≥ 3 distinct authors; drop clusters with adequate-solution share > 0.5.
- Composite score: `log1p(mentions) × recency_weight × unsolvedness`.
- Comments shorter than 15 words (config `min_comment_words`) are skipped at collection.
- Examples in reports are the per-item de-contextualized `problem_statement`s (paraphrases), never verbatim Reddit text.
- Failed LLM items are marked `failed` with an attempt count, retried up to 3 passes, and counted in the report — never silently dropped.
- Run all tests with `python -m pytest tests/ -v` from the repo root.

---

### Task 1: Project scaffold and config loading

**Files:**
- Create: `pyproject.toml`
- Create: `src/problem_finder/__init__.py`
- Create: `src/problem_finder/config.py`
- Create: `config/pilot.yaml`
- Create: `config/full.yaml`
- Create: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `config.load_config(path: str | Path) -> Config` and the `Config` dataclass with fields `subreddits: list[str]`, `window_days: int`, `db_path: str`, `output_dir: str`, `min_comment_words: int`, `max_posts_per_sub: int`, `extract_batch_size: int`, `extract_model: str`, `embed_model: str`, `min_cluster_size: int`, `pilot: bool`. All later tasks receive a `Config` named `cfg`.

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "problem-finder"
version = "0.1.0"
description = "Mine Reddit for recurring, unsolved problems"
requires-python = ">=3.11"
dependencies = [
    "praw>=7.7",
    "google-genai>=1.0",
    "scikit-learn>=1.4",
    "numpy>=1.26",
    "openpyxl>=3.1",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
pf = "problem_finder.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create the venv and install**

Run:
```bash
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```
Expected: installs without error. (Create an empty `src/problem_finder/__init__.py` first so the package resolves.) Use `.venv/bin/python -m pytest` for all test runs below.

- [ ] **Step 3: Write the failing test**

`tests/test_config.py`:
```python
from pathlib import Path

from problem_finder.config import Config, load_config


def test_load_config_reads_yaml_and_applies_defaults(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("subreddits: [running, homeowners]\nwindow_days: 14\npilot: true\n")
    cfg = load_config(p)
    assert cfg.subreddits == ["running", "homeowners"]
    assert cfg.window_days == 14
    assert cfg.pilot is True
    assert cfg.min_comment_words == 15
    assert cfg.extract_model == "gemini-2.5-flash"
    assert cfg.db_path == "data/problem_finder.db"


def test_pilot_yaml_parses():
    cfg = load_config("config/pilot.yaml")
    assert len(cfg.subreddits) == 5
    assert cfg.pilot is True
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'problem_finder.config'`

- [ ] **Step 5: Implement config.py and the yaml configs**

`src/problem_finder/config.py`:
```python
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    subreddits: list[str]
    window_days: int
    db_path: str = "data/problem_finder.db"
    output_dir: str = "output"
    min_comment_words: int = 15
    max_posts_per_sub: int = 200
    extract_batch_size: int = 20
    extract_model: str = "gemini-2.5-flash"
    embed_model: str = "gemini-embedding-001"
    min_cluster_size: int = 3
    pilot: bool = False


def load_config(path: str | Path) -> Config:
    data = yaml.safe_load(Path(path).read_text())
    return Config(**data)
```

`config/pilot.yaml`:
```yaml
subreddits: [mildlyinfuriating, homeowners, smallbusiness, running, awardtravel]
window_days: 14
max_posts_per_sub: 150
pilot: true
```

`config/full.yaml` (user approves/edits the list before any full run):
```yaml
subreddits:
  - mildlyinfuriating
  - assholedesign
  - CrappyDesign
  - therewasanattempt
  - personalfinance
  - homeowners
  - Parenting
  - smallbusiness
  - running
  - triathlon
  - cycling
  - fitness
  - travel
  - awardtravel
  - CreditCards
  - churning
  - webdev
  - devops
  - ExperiencedDevs
window_days: 365
max_posts_per_sub: 800
pilot: false
```

`.env.example`:
```
REDDIT_CLIENT_ID=your-client-id
REDDIT_CLIENT_SECRET=your-client-secret
REDDIT_USER_AGENT=problem-finder/0.1 by u/your-reddit-username
GEMINI_API_KEY=your-gemini-key
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src config tests .env.example
git commit -m "feat: project scaffold with config loading"
```

---

### Task 2: SQLite store

**Files:**
- Create: `src/problem_finder/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `db.connect(db_path: str) -> sqlite3.Connection` — creates parent dir, applies schema, `row_factory = sqlite3.Row`. `":memory:"` works for tests.
  - `db.upsert_items(conn, items: list[dict]) -> int` — `INSERT OR IGNORE`, returns number actually inserted. Item dict keys: `id, type, subreddit, thread_id, author_hash, created_utc, score, text, permalink`.
  - Tables: `items`, `coverage(subreddit, run_ts, oldest_utc, newest_utc, post_count, comment_count)`, `extractions(item_id PK, status, is_problem, problem_statement, category, solution_mentioned, solution_notes, wish_expressed, attempts)`, `embeddings(item_id PK, vector BLOB)`, `clusters(id PK, canonical_statement, solution_summary, opportunity_note, coherence_flag)`, `cluster_members(item_id PK, cluster_id)`, `cluster_scores(cluster_id PK, mentions, threads, authors, subreddits, first_seen, last_seen, spike_flag, unsolvedness, composite, passes_gate)`.

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError`

- [ ] **Step 3: Implement db.py**

`src/problem_finder/db.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/db.py tests/test_db.py
git commit -m "feat: sqlite store with schema and item upsert"
```

---

### Task 3: Collection stage

**Files:**
- Create: `src/problem_finder/collect.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `db.upsert_items`, `Config` (fields `subreddits`, `window_days`, `min_comment_words`, `max_posts_per_sub`).
- Produces:
  - Pure: `keep_text(text: str | None, author: str | None, min_words: int) -> bool`, `hash_author(name: str | None) -> str | None`, `window_bounds(window_days: int, now: int | None = None) -> tuple[int, int]`.
  - Stage: `run_collect(conn, cfg, reddit=None) -> None` — builds a `praw.Reddit` from env if `reddit` is None, stores items and a `coverage` row per sub, prints per-sub counts.

- [ ] **Step 1: Write the failing test**

`tests/test_collect.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_collect.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement collect.py**

`src/problem_finder/collect.py`:
```python
import hashlib
import os
import time

from . import db

BOT_AUTHORS = {"automoderator", "remindmebot", "savevideobot", "wikitextbot",
               "sneakpeekbot", "botrickbateman", "repostsleuthbot"}
TOMBSTONES = {"[deleted]", "[removed]", ""}


def hash_author(name: str | None) -> str | None:
    if name is None:
        return None
    return hashlib.sha256(name.lower().encode()).hexdigest()[:16]


def keep_text(text: str | None, author: str | None, min_words: int) -> bool:
    if text is None or text.strip().lower() in TOMBSTONES:
        return False
    if author is None or author.lower() in BOT_AUTHORS:
        return False
    return len(text.split()) >= min_words


def window_bounds(window_days: int, now: int | None = None) -> tuple[int, int]:
    end = int(now if now is not None else time.time())
    return end - window_days * 86400, end


def _make_reddit():
    import praw
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT",
                                  "problem-finder/0.1 (research)"),
    )


def _post_text(post) -> str:
    return f"{post.title}\n\n{post.selftext or ''}".strip()


def _author_name(thing) -> str | None:
    return thing.author.name if thing.author else None


def run_collect(conn, cfg, reddit=None) -> None:
    reddit = reddit or _make_reddit()
    start_utc, end_utc = window_bounds(cfg.window_days)
    for sub_name in cfg.subreddits:
        sub = reddit.subreddit(sub_name)
        posts: dict[str, object] = {}
        listings = [sub.new(limit=None), sub.top(time_filter="year", limit=None),
                    sub.top(time_filter="month", limit=None),
                    sub.controversial(time_filter="year", limit=None)]
        for listing in listings:
            for post in listing:
                if start_utc <= post.created_utc <= end_utc:
                    posts[post.id] = post
                if len(posts) >= cfg.max_posts_per_sub:
                    break
            if len(posts) >= cfg.max_posts_per_sub:
                break

        items: list[dict] = []
        n_comments = 0
        for post in posts.values():
            author = _author_name(post)
            if keep_text(_post_text(post), author, 1):  # keep short titles too
                items.append(dict(
                    id=f"t3_{post.id}", type="post", subreddit=sub_name,
                    thread_id=post.id, author_hash=hash_author(author),
                    created_utc=int(post.created_utc), score=post.score,
                    text=_post_text(post), permalink=post.permalink))
            post.comments.replace_more(limit=None)
            for c in post.comments.list():
                c_author = _author_name(c)
                if not keep_text(c.body, c_author, cfg.min_comment_words):
                    continue
                n_comments += 1
                items.append(dict(
                    id=f"t1_{c.id}", type="comment", subreddit=sub_name,
                    thread_id=post.id, author_hash=hash_author(c_author),
                    created_utc=int(c.created_utc), score=c.score,
                    text=c.body, permalink=c.permalink))

        inserted = db.upsert_items(conn, items)
        dates = [i["created_utc"] for i in items]
        conn.execute(
            "INSERT INTO coverage VALUES (?,?,?,?,?,?)",
            (sub_name, int(time.time()), min(dates, default=None),
             max(dates, default=None), len(posts), n_comments))
        conn.commit()
        print(f"r/{sub_name}: {len(posts)} posts, {n_comments} comments "
              f"({inserted} new items)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_collect.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/collect.py tests/test_collect.py
git commit -m "feat: reddit collection stage with filters and coverage tracking"
```

---

### Task 4: Gemini client wrapper

**Files:**
- Create: `src/problem_finder/gemini.py`
- Test: `tests/test_gemini.py`

**Interfaces:**
- Consumes: env var `GEMINI_API_KEY` (only when actually constructing the real client).
- Produces:
  - `with_retries(fn, attempts=3, base_delay=2.0, sleep=time.sleep)` — calls `fn()`, retries on any exception with exponential backoff, re-raises after the last attempt.
  - `class GeminiClient(extract_model: str, embed_model: str)` with:
    - `.generate_json(prompt: str) -> object` — structured-JSON generation, parsed via `json.loads`, retried.
    - `.embed(texts: list[str]) -> list[list[float]]` — chunked 100 per call, retried.
    - `.usage: dict` with keys `calls`, `input_tokens`, `output_tokens`.

- [ ] **Step 1: Write the failing test**

`tests/test_gemini.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gemini.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement gemini.py**

`src/problem_finder/gemini.py`:
```python
import json
import os
import time


def with_retries(fn, attempts: int = 3, base_delay: float = 2.0,
                 sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception:
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (2 ** attempt))


class GeminiClient:
    def __init__(self, extract_model: str, embed_model: str):
        from google import genai
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.extract_model = extract_model
        self.embed_model = embed_model
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _tally(self, resp) -> None:
        self.usage["calls"] += 1
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            self.usage["input_tokens"] += um.prompt_token_count or 0
            self.usage["output_tokens"] += um.candidates_token_count or 0

    def generate_json(self, prompt: str):
        def call():
            resp = self.client.models.generate_content(
                model=self.extract_model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            self._tally(resp)
            return json.loads(resp.text)
        return with_retries(call)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            chunk = texts[i:i + 100]

            def call():
                resp = self.client.models.embed_content(
                    model=self.embed_model, contents=chunk)
                self.usage["calls"] += 1
                return [e.values for e in resp.embeddings]

            out.extend(with_retries(call))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gemini.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/gemini.py tests/test_gemini.py
git commit -m "feat: gemini client wrapper with retries and usage tally"
```

---

### Task 5: Extraction stage

**Files:**
- Create: `src/problem_finder/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `db.connect` schema (`items`, `extractions`), `GeminiClient.generate_json`, `Config.extract_batch_size`.
- Produces:
  - Pure: `build_extract_prompt(texts: list[str]) -> str`, `parse_extraction_response(data: object, n_items: int) -> list[dict | None]` (index-aligned; `None` = item the model skipped/mangled).
  - Stage: `run_extract(conn, cfg, client) -> None` — processes items with no extraction row, or `status='failed'` and `attempts < 3`; upserts `extractions` rows with `status` `'ok'` or `'failed'`.
  - Extraction row dict keys (from parse): `is_problem: bool`, `problem_statement: str | None`, `category: str`, `solution_mentioned: str` (one of `none|mentioned-adequate|mentioned-inadequate`), `solution_notes: str | None`, `wish_expressed: bool`.

- [ ] **Step 1: Write the failing test**

`tests/test_extract.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement extract.py**

`src/problem_finder/extract.py`:
```python
MAX_ITEM_CHARS = 1500
MAX_ATTEMPTS = 3

EXTRACT_PROMPT = """\
You are analyzing Reddit posts and comments to find problems people complain \
about, for market research. For EACH numbered item below, decide whether it \
expresses a problem, frustration, or unmet need.

Return ONLY a JSON array with one object per item, each with these keys:
- "index": the item's number
- "is_problem": true/false
- "problem_statement": if is_problem, ONE general, de-contextualized sentence \
naming the underlying problem (not "my Peloton screen froze again" but \
"fitness equipment touchscreens are unreliable"); else null
- "category": one of "home", "fitness", "travel", "finance", "dev-tools", "other"
- "solution_mentioned": "none" if no existing product/workaround/fix is \
referenced; "mentioned-adequate" if one is referenced and described as \
working well; "mentioned-inadequate" if one is referenced but called \
expensive, clunky, incomplete, discontinued, or otherwise unsatisfying
- "solution_notes": short note naming the product/workaround and the complaint \
about it, or null
- "wish_expressed": true if the author explicitly wishes a product/service \
existed (e.g. "I wish someone made X", "why is there no app for this")

Items:
{items}
"""

VALID_SOLUTION = {"none", "mentioned-adequate", "mentioned-inadequate"}
VALID_CATEGORY = {"home", "fitness", "travel", "finance", "dev-tools", "other"}


def build_extract_prompt(texts: list[str]) -> str:
    lines = [f"[{i}] {t[:MAX_ITEM_CHARS]}" for i, t in enumerate(texts)]
    return EXTRACT_PROMPT.format(items="\n\n".join(lines))


def parse_extraction_response(data, n_items: int) -> list[dict | None]:
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data).__name__}")
    rows: list[dict | None] = [None] * n_items
    for obj in data:
        if not isinstance(obj, dict):
            continue
        i = obj.get("index")
        if not isinstance(i, int) or not 0 <= i < n_items:
            continue
        sol = obj.get("solution_mentioned")
        cat = obj.get("category")
        rows[i] = {
            "is_problem": bool(obj.get("is_problem")),
            "problem_statement": obj.get("problem_statement"),
            "category": cat if cat in VALID_CATEGORY else "other",
            "solution_mentioned": sol if sol in VALID_SOLUTION else "none",
            "solution_notes": obj.get("solution_notes"),
            "wish_expressed": bool(obj.get("wish_expressed")),
        }
    return rows


PENDING_SQL = """\
SELECT i.id, i.text, COALESCE(e.attempts, 0) AS attempts
FROM items i LEFT JOIN extractions e ON e.item_id = i.id
WHERE e.item_id IS NULL OR (e.status = 'failed' AND e.attempts < ?)
ORDER BY i.id LIMIT ?"""

UPSERT_SQL = """\
INSERT INTO extractions (item_id, status, is_problem, problem_statement,
    category, solution_mentioned, solution_notes, wish_expressed, attempts)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT(item_id) DO UPDATE SET status=excluded.status,
    is_problem=excluded.is_problem,
    problem_statement=excluded.problem_statement,
    category=excluded.category,
    solution_mentioned=excluded.solution_mentioned,
    solution_notes=excluded.solution_notes,
    wish_expressed=excluded.wish_expressed,
    attempts=excluded.attempts"""


def _save(conn, item_id: str, row: dict | None, attempts: int) -> None:
    if row is None:
        conn.execute(UPSERT_SQL, (item_id, "failed", None, None, None,
                                  None, None, None, attempts))
    else:
        conn.execute(UPSERT_SQL, (
            item_id, "ok", int(row["is_problem"]), row["problem_statement"],
            row["category"], row["solution_mentioned"], row["solution_notes"],
            int(row["wish_expressed"]), attempts))


def run_extract(conn, cfg, client) -> None:
    done = 0
    while True:
        batch = conn.execute(
            PENDING_SQL, (MAX_ATTEMPTS, cfg.extract_batch_size)).fetchall()
        if not batch:
            break
        texts = [r["text"] for r in batch]
        try:
            rows = parse_extraction_response(
                client.generate_json(build_extract_prompt(texts)), len(batch))
        except Exception as exc:
            print(f"extract: batch failed ({exc})")
            rows = [None] * len(batch)
        for r, parsed in zip(batch, rows):
            _save(conn, r["id"], parsed, r["attempts"] + 1)
        conn.commit()
        done += len(batch)
        if done % 200 == 0:
            print(f"extract: {done} items processed")
    n_failed = conn.execute(
        "SELECT COUNT(*) AS n FROM extractions WHERE status='failed'"
    ).fetchone()["n"]
    print(f"extract: done ({done} this run, {n_failed} failed total)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_extract.py -v`
Expected: 5 PASS

Note: successfully parsed items get `attempts = previous + 1` too; that is fine because their `status='ok'` excludes them from `PENDING_SQL` forever.

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/extract.py tests/test_extract.py
git commit -m "feat: gemini extraction stage with batching and resume"
```

---

### Task 6: Embedding and clustering stage

**Files:**
- Create: `src/problem_finder/cluster.py`
- Test: `tests/test_cluster.py`

**Interfaces:**
- Consumes: `embeddings`/`extractions`/`clusters`/`cluster_members` tables, `GeminiClient.embed`, `GeminiClient.generate_json`, `Config.min_cluster_size`.
- Produces:
  - Pure: `cluster_labels(vectors: np.ndarray, min_cluster_size: int) -> np.ndarray` (HDBSCAN over unit-normalized vectors; label `-1` = noise), `build_summary_prompt(statements: list[str], notes: list[str]) -> str`, `vec_to_blob(v) -> bytes` / `blob_to_vec(b) -> np.ndarray` (float32).
  - Stage: `run_embed(conn, cfg, client) -> None` (embeds problem statements missing embeddings), `run_cluster(conn, cfg, client) -> None` (rebuilds `clusters` + `cluster_members` from scratch each run, then one `generate_json` summary call per cluster). Summary JSON keys: `canonical_statement`, `solution_summary`, `opportunity_note`, `coherent` (bool).

- [ ] **Step 1: Write the failing test**

`tests/test_cluster.py`:
```python
import numpy as np

from problem_finder import db
from problem_finder.cluster import (blob_to_vec, build_summary_prompt,
                                    cluster_labels, run_cluster, run_embed,
                                    vec_to_blob)
from tests.test_db import make_item


def test_blob_roundtrip():
    v = np.array([0.1, -0.5, 2.0], dtype=np.float32)
    assert np.array_equal(blob_to_vec(vec_to_blob(v)), v)


def test_cluster_labels_groups_nearby_vectors():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=(5, 0, 0), scale=0.05, size=(10, 3))
    b = rng.normal(loc=(0, 5, 0), scale=0.05, size=(10, 3))
    labels = cluster_labels(np.vstack([a, b]).astype(np.float32), 3)
    assert len(set(labels[:10])) == 1 and labels[0] != -1
    assert len(set(labels[10:])) == 1 and labels[10] != -1
    assert labels[0] != labels[10]


def test_summary_prompt_includes_statements_and_notes():
    p = build_summary_prompt(["shoes wear out fast"], ["rotating pairs is pricey"])
    assert "shoes wear out fast" in p
    assert "rotating pairs is pricey" in p
    assert "canonical_statement" in p


class FakeClient:
    def embed(self, texts):
        # deterministic: statement text controls direction
        return [[1.0, 0.0] if "shoe" in t else [0.0, 1.0] for t in texts]

    def generate_json(self, prompt):
        return {"canonical_statement": "canon", "solution_summary": "none mentioned",
                "opportunity_note": "note", "coherent": True}


class Cfg:
    min_cluster_size = 3


def _seed(conn, n_shoe=4, n_wifi=4):
    items, i = [], 0
    for k in range(n_shoe):
        items.append(make_item(f"s{k}", thread_id=f"t{i}")); i += 1
    for k in range(n_wifi):
        items.append(make_item(f"w{k}", thread_id=f"t{i}")); i += 1
    db.upsert_items(conn, items)
    for k in range(n_shoe):
        conn.execute("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"s{k}", "ok", 1, "shoes wear out fast", "fitness",
                      "none", None, 0, 1))
    for k in range(n_wifi):
        conn.execute("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"w{k}", "ok", 1, "hotel wifi is unreliable", "travel",
                      "none", None, 0, 1))
    conn.commit()


def test_run_embed_then_cluster_builds_two_clusters():
    conn = db.connect(":memory:")
    _seed(conn)
    client = FakeClient()
    run_embed(conn, Cfg(), client)
    assert conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"] == 8
    run_embed(conn, Cfg(), client)  # idempotent: no missing rows -> no change
    run_cluster(conn, Cfg(), client)
    n_clusters = conn.execute("SELECT COUNT(*) AS n FROM clusters").fetchone()["n"]
    assert n_clusters == 2
    members = conn.execute(
        "SELECT cluster_id, COUNT(*) AS n FROM cluster_members GROUP BY 1"
    ).fetchall()
    assert sorted(m["n"] for m in members) == [4, 4]
    c = conn.execute("SELECT * FROM clusters").fetchone()
    assert c["canonical_statement"] == "canon"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cluster.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement cluster.py**

`src/problem_finder/cluster.py`:
```python
import numpy as np
from sklearn.cluster import HDBSCAN

MAX_SUMMARY_STATEMENTS = 30
MAX_SUMMARY_NOTES = 15

SUMMARY_PROMPT = """\
The following problem statements were extracted from Reddit and clustered as \
one underlying problem.

Statements:
{statements}

Solution notes from the same threads (may be empty):
{notes}

Return ONLY a JSON object with keys:
- "canonical_statement": ONE general sentence stating the underlying problem
- "solution_summary": 1-2 sentences on existing products/workarounds people \
mention and their shortcomings, or "none mentioned"
- "opportunity_note": one line on why this could be a business opportunity
- "coherent": false if these look like two or more unrelated problems merged \
together, else true
"""


def vec_to_blob(v) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def blob_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def cluster_labels(vectors: np.ndarray, min_cluster_size: int) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.clip(norms, 1e-10, None)
    return HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(unit)


def build_summary_prompt(statements: list[str], notes: list[str]) -> str:
    s = "\n".join(f"- {x}" for x in statements[:MAX_SUMMARY_STATEMENTS])
    n = "\n".join(f"- {x}" for x in notes[:MAX_SUMMARY_NOTES]) or "(none)"
    return SUMMARY_PROMPT.format(statements=s, notes=n)


def run_embed(conn, cfg, client) -> None:
    rows = conn.execute("""\
        SELECT e.item_id, e.problem_statement FROM extractions e
        LEFT JOIN embeddings b ON b.item_id = e.item_id
        WHERE e.status='ok' AND e.is_problem=1 AND b.item_id IS NULL
        ORDER BY e.item_id""").fetchall()
    if not rows:
        print("embed: nothing to do")
        return
    vectors = client.embed([r["problem_statement"] for r in rows])
    conn.executemany("INSERT INTO embeddings VALUES (?,?)",
                     [(r["item_id"], vec_to_blob(v))
                      for r, v in zip(rows, vectors)])
    conn.commit()
    print(f"embed: {len(rows)} statements embedded")


def run_cluster(conn, cfg, client) -> None:
    rows = conn.execute(
        "SELECT item_id, vector FROM embeddings ORDER BY item_id").fetchall()
    if len(rows) < cfg.min_cluster_size:
        print("cluster: not enough embeddings")
        return
    vectors = np.vstack([blob_to_vec(r["vector"]) for r in rows])
    labels = cluster_labels(vectors, cfg.min_cluster_size)

    conn.execute("DELETE FROM cluster_scores")
    conn.execute("DELETE FROM cluster_members")
    conn.execute("DELETE FROM clusters")
    by_label: dict[int, list[str]] = {}
    for r, label in zip(rows, labels):
        if label != -1:
            by_label.setdefault(int(label), []).append(r["item_id"])

    for label, item_ids in sorted(by_label.items()):
        placeholders = ",".join("?" * len(item_ids))
        ex = conn.execute(
            f"""SELECT problem_statement, solution_notes FROM extractions
                WHERE item_id IN ({placeholders})""", item_ids).fetchall()
        statements = [r["problem_statement"] for r in ex]
        notes = [r["solution_notes"] for r in ex if r["solution_notes"]]
        try:
            s = client.generate_json(build_summary_prompt(statements, notes))
            canonical = s.get("canonical_statement") or statements[0]
            solution = s.get("solution_summary") or "none mentioned"
            note = s.get("opportunity_note") or ""
            coherent = bool(s.get("coherent", True))
        except Exception as exc:
            print(f"cluster {label}: summary failed ({exc}); using fallback")
            canonical, solution, note, coherent = (
                statements[0], "none mentioned", "", True)
        cur = conn.execute(
            "INSERT INTO clusters (canonical_statement, solution_summary,"
            " opportunity_note, coherence_flag) VALUES (?,?,?,?)",
            (canonical, solution, note, int(not coherent)))
        conn.executemany(
            "INSERT INTO cluster_members VALUES (?,?)",
            [(i, cur.lastrowid) for i in item_ids])
    conn.commit()
    n_noise = int((labels == -1).sum())
    print(f"cluster: {len(by_label)} clusters, {n_noise} noise items")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cluster.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/cluster.py tests/test_cluster.py
git commit -m "feat: embedding and hdbscan clustering stage with summaries"
```

---

### Task 7: Scoring stage

**Files:**
- Create: `src/problem_finder/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `cluster_members` joined to `items` + `extractions`; writes `cluster_scores`.
- Produces:
  - Pure: `score_cluster(members: list[dict], window_start: int, window_end: int) -> dict`. Each member dict has keys `thread_id, author_hash, subreddit, created_utc, solution_mentioned, wish_expressed`. Returns dict with keys `mentions, threads, authors, subreddits, first_seen, last_seen, spike_flag, unsolvedness, composite, passes_gate`.
  - Stage: `run_score(conn, cfg) -> None` — window from data: `window_end = MAX(items.created_utc)`, `window_start = window_end - cfg.window_days*86400`; upserts one `cluster_scores` row per cluster.

- [ ] **Step 1: Write the failing test**

`tests/test_score.py`:
```python
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
    partial = spread_members(4) + spread_members(2, sol="mentioned-adequate")
    # rebuild with distinct threads/authors across both groups
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_score.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement score.py**

`src/problem_finder/score.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_score.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/score.py tests/test_score.py
git commit -m "feat: cluster scoring with recurrence gate and unsolvedness"
```

---

### Task 8: Report stage

**Files:**
- Create: `src/problem_finder/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: all tables; `Config.output_dir`, `Config.pilot`.
- Produces:
  - Pure: `format_example(statement: str, subreddit: str, created_utc: int) -> str` → `"<statement> (r/<sub>, YYYY-MM)"`; `pick_examples(members: list[dict], n: int = 3) -> list[dict]` — up to `n` members from **distinct threads**, highest Reddit score first.
  - Stage: `run_report(conn, cfg, usage: dict | None = None) -> tuple[Path, Path]` — writes `output/report_<YYYYmmdd_HHMMSS>.xlsx` and `output/summary_<same>.md`, returns both paths. Xlsx sheets: `Top 50`, `All clusters`, `Run info`, plus `Extraction QA` when `cfg.pilot` is true.

- [ ] **Step 1: Write the failing test**

`tests/test_report.py`:
```python
from datetime import datetime, timezone

from openpyxl import load_workbook

from problem_finder import db
from problem_finder.report import format_example, pick_examples, run_report
from tests.test_db import make_item

END = 1_750_000_000


def test_format_example():
    ts = int(datetime(2026, 3, 15, tzinfo=timezone.utc).timestamp())
    assert format_example("hotel wifi is unreliable", "travel", ts) == \
        "hotel wifi is unreliable (r/travel, 2026-03)"


def test_pick_examples_distinct_threads_by_score():
    members = [
        dict(thread_id="t1", score=50, problem_statement="a",
             subreddit="s", created_utc=END),
        dict(thread_id="t1", score=99, problem_statement="b",
             subreddit="s", created_utc=END),
        dict(thread_id="t2", score=10, problem_statement="c",
             subreddit="s", created_utc=END),
    ]
    picked = pick_examples(members, n=3)
    assert [m["problem_statement"] for m in picked] == ["b", "c"]


def _seed(conn):
    items = [make_item(f"i{k}", thread_id=f"t{k}", author_hash=f"a{k}",
                       created_utc=END - k * 86400, score=10 + k,
                       subreddit="running" if k % 2 else "travel")
             for k in range(4)]
    db.upsert_items(conn, items)
    for k in range(4):
        conn.execute("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"i{k}", "ok", 1, f"statement {k}", "other", "none",
                      None, 0, 1))
    conn.execute("""INSERT INTO clusters VALUES
        (1, 'canonical problem', 'no real solutions', 'big market', 0)""")
    conn.executemany("INSERT INTO cluster_members VALUES (?,1)",
                     [(f"i{k}",) for k in range(4)])
    conn.execute("""INSERT INTO cluster_scores VALUES
        (1, 4, 4, 4, 2, ?, ?, 0, 0.9, 1.45, 1)""", (END - 3 * 86400, END))
    conn.commit()


def test_run_report_writes_xlsx_and_md(tmp_path):
    conn = db.connect(":memory:")
    _seed(conn)

    class Cfg:
        output_dir = str(tmp_path)
        pilot = True
        window_days = 14

    xlsx, md = run_report(conn, Cfg(), usage={"calls": 3, "input_tokens": 10,
                                              "output_tokens": 5})
    wb = load_workbook(xlsx)
    assert {"Top 50", "All clusters", "Run info",
            "Extraction QA"} <= set(wb.sheetnames)
    ws = wb["Top 50"]
    header = [c.value for c in ws[1]]
    assert "Problem" in header and "Composite score" in header
    assert ws.cell(row=2, column=header.index("Problem") + 1).value == \
        "canonical problem"
    text = md.read_text()
    assert "canonical problem" in text
    assert "big market" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement report.py**

`src/problem_finder/report.py`:
```python
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook

HEADERS = ["Rank", "Problem", "Composite score", "Mentions", "Threads",
           "Authors", "Subreddits", "First seen", "Last seen", "Spike?",
           "Unsolved-ness", "Solution landscape", "Examples", "Permalinks",
           "Opportunity", "Coherence flag"]

CLUSTER_SQL = """\
SELECT c.id, c.canonical_statement, c.solution_summary, c.opportunity_note,
       c.coherence_flag, s.*
FROM clusters c JOIN cluster_scores s ON s.cluster_id = c.id
WHERE s.passes_gate = 1
ORDER BY s.composite DESC"""

MEMBERS_SQL = """\
SELECT i.thread_id, i.subreddit, i.created_utc, i.score, i.permalink,
       e.problem_statement
FROM cluster_members cm
JOIN items i ON i.id = cm.item_id
JOIN extractions e ON e.item_id = cm.item_id
WHERE cm.cluster_id = ?"""


def _month(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def format_example(statement: str, subreddit: str, created_utc: int) -> str:
    return f"{statement} (r/{subreddit}, {_month(created_utc)})"


def pick_examples(members: list[dict], n: int = 3) -> list[dict]:
    best: dict[str, dict] = {}
    for m in members:
        cur = best.get(m["thread_id"])
        if cur is None or (m["score"] or 0) > (cur["score"] or 0):
            best[m["thread_id"]] = m
    ranked = sorted(best.values(), key=lambda m: m["score"] or 0, reverse=True)
    return ranked[:n]


def _cluster_row(rank: int, c, members: list[dict]) -> list:
    ex = pick_examples(members)
    return [rank, c["canonical_statement"], round(c["composite"], 3),
            c["mentions"], c["threads"], c["authors"], c["subreddits"],
            _month(c["first_seen"]), _month(c["last_seen"]),
            "yes" if c["spike_flag"] else "", round(c["unsolvedness"], 2),
            c["solution_summary"],
            " | ".join(format_example(m["problem_statement"], m["subreddit"],
                                      m["created_utc"]) for m in ex),
            " | ".join(f"https://reddit.com{m['permalink']}" for m in ex),
            c["opportunity_note"],
            "check: may be merged topics" if c["coherence_flag"] else ""]


def _write_sheet(ws, clusters, conn, limit=None):
    ws.append(HEADERS)
    for rank, c in enumerate(clusters[:limit], start=1):
        members = [dict(r) for r in conn.execute(MEMBERS_SQL, (c["id"],))]
        ws.append(_cluster_row(rank, c, members))


def _run_info(ws, conn, usage):
    ws.append(["Subreddit", "Run time", "Oldest", "Newest", "Posts", "Comments"])
    for r in conn.execute("SELECT * FROM coverage ORDER BY subreddit, run_ts"):
        ws.append([r["subreddit"], _month(r["run_ts"]),
                   _month(r["oldest_utc"]) if r["oldest_utc"] else "",
                   _month(r["newest_utc"]) if r["newest_utc"] else "",
                   r["post_count"], r["comment_count"]])
    n_failed = conn.execute(
        "SELECT COUNT(*) AS n FROM extractions WHERE status='failed'"
    ).fetchone()["n"]
    ws.append([])
    ws.append(["Failed extractions", n_failed])
    if usage:
        ws.append(["Gemini calls", usage["calls"]])
        ws.append(["Input tokens", usage["input_tokens"]])
        ws.append(["Output tokens", usage["output_tokens"]])


def _extraction_qa(ws, conn, sample_size=30):
    rows = conn.execute("""\
        SELECT i.text, e.is_problem, e.problem_statement, e.solution_mentioned
        FROM extractions e JOIN items i ON i.id = e.item_id
        WHERE e.status='ok'""").fetchall()
    random.seed(42)
    sample = random.sample(rows, min(sample_size, len(rows)))
    ws.append(["Raw text (truncated)", "Is problem?", "Extracted statement",
               "Solution mentioned"])
    for r in sample:
        ws.append([r["text"][:500], bool(r["is_problem"]),
                   r["problem_statement"], r["solution_mentioned"]])


def _markdown(clusters, conn) -> str:
    lines = ["# Top 10 problem opportunities\n"]
    for rank, c in enumerate(clusters[:10], start=1):
        members = [dict(r) for r in conn.execute(MEMBERS_SQL, (c["id"],))]
        ex = pick_examples(members)
        lines += [
            f"## {rank}. {c['canonical_statement']}\n",
            f"- **Score:** {c['composite']:.2f} | **Mentions:** "
            f"{c['mentions']} across {c['threads']} threads, "
            f"{c['authors']} authors, {c['subreddits']} subreddits",
            f"- **Seen:** {_month(c['first_seen'])} to {_month(c['last_seen'])}"
            + (" (possible news spike)" if c["spike_flag"] else ""),
            f"- **Unsolved-ness:** {c['unsolvedness']:.2f}",
            f"- **Current solutions:** {c['solution_summary']}",
            f"- **Opportunity:** {c['opportunity_note']}",
            "- **Examples:**",
            *[f"  - {format_example(m['problem_statement'], m['subreddit'], m['created_utc'])}"
              for m in ex],
            "",
        ]
    return "\n".join(lines)


def run_report(conn, cfg, usage: dict | None = None) -> tuple[Path, Path]:
    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    clusters = [dict(r) for r in conn.execute(CLUSTER_SQL)]

    wb = Workbook()
    _write_sheet(wb.active, clusters, conn, limit=50)
    wb.active.title = "Top 50"
    _write_sheet(wb.create_sheet("All clusters"), clusters, conn)
    _run_info(wb.create_sheet("Run info"), conn, usage)
    if cfg.pilot:
        _extraction_qa(wb.create_sheet("Extraction QA"), conn)
    xlsx_path = out / f"report_{ts}.xlsx"
    wb.save(xlsx_path)

    md_path = out / f"summary_{ts}.md"
    md_path.write_text(_markdown(clusters, conn))
    print(f"report: {xlsx_path} and {md_path} "
          f"({len(clusters)} clusters pass gates)")
    return xlsx_path, md_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/problem_finder/report.py tests/test_report.py
git commit -m "feat: xlsx and markdown report stage with pilot QA sheet"
```

---

### Task 9: CLI and README

**Files:**
- Create: `src/problem_finder/cli.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above — `load_config`, `db.connect`, `run_collect`, `run_extract`, `run_embed`, `run_cluster`, `run_score`, `run_report`, `GeminiClient`.
- Produces: `main(argv: list[str] | None = None) -> None`; console script `pf <stage> --config <path>` where stage ∈ `collect|extract|cluster|score|report|run`. `cluster` runs `run_embed` then `run_cluster`. `run` chains all five. Loads `.env` via `python-dotenv`. Prints Gemini usage at the end when a client was created.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from problem_finder import cli


def test_score_and_report_run_without_api_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "subreddits: [running]\nwindow_days: 14\n"
        f"db_path: {tmp_path / 'db.sqlite'}\n"
        f"output_dir: {tmp_path / 'out'}\n"
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cli.main(["score", "--config", str(cfg)])   # empty db: prints 'no items'
    cli.main(["report", "--config", str(cfg)])
    assert list((tmp_path / "out").glob("report_*.xlsx"))


def test_unknown_stage_exits():
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["frobnicate", "--config", "config/pilot.yaml"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError` (or `AttributeError: main`)

- [ ] **Step 3: Implement cli.py**

`src/problem_finder/cli.py`:
```python
import argparse

from dotenv import load_dotenv

from . import db
from .cluster import run_cluster, run_embed
from .collect import run_collect
from .config import load_config
from .extract import run_extract
from .report import run_report
from .score import run_score

STAGES = ["collect", "extract", "cluster", "score", "report", "run"]
NEEDS_GEMINI = {"extract", "cluster"}


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="pf", description="Mine Reddit for recurring unsolved problems")
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--config", required=True, help="path to yaml config")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path)
    stages = (["collect", "extract", "cluster", "score", "report"]
              if args.stage == "run" else [args.stage])

    client = None
    if NEEDS_GEMINI & set(stages):
        from .gemini import GeminiClient
        client = GeminiClient(cfg.extract_model, cfg.embed_model)

    for stage in stages:
        if stage == "collect":
            run_collect(conn, cfg)
        elif stage == "extract":
            run_extract(conn, cfg, client)
        elif stage == "cluster":
            run_embed(conn, cfg, client)
            run_cluster(conn, cfg, client)
        elif stage == "score":
            run_score(conn, cfg)
        elif stage == "report":
            run_report(conn, cfg, usage=client.usage if client else None)

    if client:
        u = client.usage
        print(f"gemini usage: {u['calls']} calls, "
              f"{u['input_tokens']} in / {u['output_tokens']} out tokens")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL tests pass (full suite; no API keys or network needed)

- [ ] **Step 5: Write README.md**

````markdown
# Problem Finder

Mines Reddit for recurring, unsolved problems people complain about and ranks
them as potential business opportunities. Output: an xlsx report (top 50 +
all clusters + run info) and a markdown summary of the top 10.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then fill in the three keys below
```

### Reddit API credentials

1. Go to https://www.reddit.com/prefs/apps while logged in.
2. Click "create another app...", choose type **script**, any name,
   redirect uri `http://localhost:8080`.
3. Copy the string under the app name into `REDDIT_CLIENT_ID`, and the
   "secret" into `REDDIT_CLIENT_SECRET`.
4. Set `REDDIT_USER_AGENT` to `problem-finder/0.1 by u/<your-username>`.

### Gemini API key

1. Go to https://aistudio.google.com/apikey and create a key.
2. Put it in `GEMINI_API_KEY`.

## Running

Pilot (5 subreddits, 14 days — sanity-check extraction quality first):

```bash
.venv/bin/pf run --config config/pilot.yaml
```

Stages can run individually and always resume where they left off:

```bash
.venv/bin/pf collect --config config/pilot.yaml
.venv/bin/pf extract --config config/pilot.yaml
.venv/bin/pf cluster --config config/pilot.yaml
.venv/bin/pf score   --config config/pilot.yaml
.venv/bin/pf report  --config config/pilot.yaml
```

Reports land in `output/`. On pilot runs the xlsx includes an
**Extraction QA** sheet — 30 random items with the model's judgment beside
the raw text. Review it before running the full config.

Full run (edit `config/full.yaml` subreddit list first):

```bash
.venv/bin/pf run --config config/full.yaml
```

## Notes

- Reddit listings cap at ~1,000 posts each; the "Run info" sheet shows the
  date coverage actually achieved per subreddit.
- The pipeline stores everything in `data/problem_finder.db`; delete it to
  start fresh, or re-run `collect` anytime to pull new content incrementally.
- Costs: extraction dominates; a pilot run is well under $5 of Gemini usage.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```
````

- [ ] **Step 6: Commit**

```bash
git add src/problem_finder/cli.py tests/test_cli.py README.md
git commit -m "feat: cli entrypoint and setup docs"
```

---

## Post-implementation: pilot run (requires user)

Not a code task — after Task 9, the user must fill `.env` (README has the
walkthrough), then run `.venv/bin/pf run --config config/pilot.yaml`. Review
the Extraction QA sheet together before approving `config/full.yaml`.
