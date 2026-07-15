"""Collector for Reddit's public Atom/RSS feeds — no OAuth app required.

Reddit closed unauthenticated .json access in May 2026; the Atom feeds on
old.reddit.com remain open. Compared to the OAuth API this path is slower and
lossier: comment scores are unavailable (stored as 0), reply nesting is
flattened, and a thread yields at most ~100 comments per fetch.
"""
import html as html_lib
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

from . import db
from .collect import hash_author, keep_text, window_bounds

BASE = "https://old.reddit.com"
ATOM = "{http://www.w3.org/2005/Atom}"
LISTINGS = [("new", None), ("top", "year"), ("top", "month"),
            ("controversial", "year")]
PAGE_LIMIT = 100
MAX_PAGES = 10  # reddit caps listings at ~1000 items anyway

TAG_RE = re.compile(r"<[^>]+>")
SUBMITTED_RE = re.compile(r"submitted by\s+/u/.*$", re.DOTALL)
THREAD_RE = re.compile(r"/comments/(\w+)/")


def html_to_text(fragment: str) -> str:
    text = html_lib.unescape(TAG_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _norm_author(name: str | None) -> str | None:
    if not name:
        return None
    name = name.removeprefix("/u/")
    return None if name == "[deleted]" else name


def _created_utc(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return 0


def parse_feed(xml_text: str) -> list[dict]:
    """Normalize a listing or comments Atom feed into entry dicts."""
    entries = []
    for e in ET.fromstring(xml_text).findall(ATOM + "entry"):
        full_id = e.findtext(ATOM + "id") or ""
        kind, _, short_id = full_id.partition("_")
        if kind not in ("t1", "t3") or not short_id:
            continue
        link = e.find(ATOM + "link")
        href = link.get("href") if link is not None else ""
        permalink = href.removeprefix(BASE)
        thread = THREAD_RE.search(permalink)
        body = html_to_text(e.findtext(ATOM + "content") or "")
        if kind == "t3":
            body = SUBMITTED_RE.sub("", body).strip()
            title = (e.findtext(ATOM + "title") or "").strip()
            text = f"{title}\n\n{body}".strip()
        else:
            text = body
        entries.append(dict(
            kind=kind, id=short_id,
            author=_norm_author(e.findtext(f"{ATOM}author/{ATOM}name")),
            created_utc=_created_utc(e.findtext(ATOM + "updated") or ""),
            text=text, permalink=permalink,
            thread_id=thread.group(1) if thread else short_id))
    return entries


class PublicFetcher:
    """Rate-limited GET returning feed XML; retries 429/5xx with backoff."""

    def __init__(self, interval_s: float = 6.5):
        self.interval_s = interval_s
        self._next_at = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = os.environ.get(
            "REDDIT_USER_AGENT",
            "macos:problem-finder:v0.1 (personal market research)")

    def __call__(self, path: str, params: dict) -> str:
        for attempt in range(5):
            wait = self._next_at - time.time()
            if wait > 0:
                time.sleep(wait)
            self._next_at = time.time() + self.interval_s
            resp = self.session.get(f"{BASE}{path}", params=params, timeout=30)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if resp.status_code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.text
        raise RuntimeError(f"giving up on {path} after repeated 429/5xx")


def _window_posts(fetch, sub: str, cfg, start_utc: int, end_utc: int) -> dict:
    posts: dict[str, dict] = {}
    for listing, t in LISTINGS:
        after = None
        for _ in range(MAX_PAGES):
            params = {"limit": PAGE_LIMIT}
            if t:
                params["t"] = t
            if after:
                params["after"] = after
            page = [e for e in parse_feed(fetch(f"/r/{sub}/{listing}/.rss",
                                                params))
                    if e["kind"] == "t3"]
            for p in page:
                if len(posts) >= cfg.max_posts_per_sub:
                    break
                if start_utc <= p["created_utc"] <= end_utc:
                    posts[p["id"]] = p
            if len(posts) >= cfg.max_posts_per_sub or len(page) < PAGE_LIMIT:
                break
            if listing == "new" and page[-1]["created_utc"] < start_utc:
                break  # "new" is time-ordered: everything further is older
            after = f"t3_{page[-1]['id']}"
        if len(posts) >= cfg.max_posts_per_sub:
            break
    return posts


def _item(entry: dict, sub: str, item_type: str) -> dict:
    return dict(
        id=f"{entry['kind']}_{entry['id']}", type=item_type, subreddit=sub,
        thread_id=entry["thread_id"], author_hash=hash_author(entry["author"]),
        created_utc=entry["created_utc"], score=0, text=entry["text"],
        permalink=entry["permalink"])


def run_collect_public(conn, cfg, fetch=None, now: int | None = None) -> None:
    fetch = fetch or PublicFetcher(getattr(cfg, "request_interval_s", 6.5))
    start_utc, end_utc = window_bounds(cfg.window_days, now=now)
    for sub in cfg.subreddits:
        posts = _window_posts(fetch, sub, cfg, start_utc, end_utc)
        seen = {r["thread_id"] for r in conn.execute(
            "SELECT DISTINCT thread_id FROM items WHERE subreddit=?", (sub,))}
        items: list[dict] = []
        n_comments = 0
        for p in posts.values():
            if p["id"] in seen:
                continue  # thread already collected on a previous run
            if keep_text(p["text"], p["author"], 1):
                items.append(_item(p, sub, "post"))
            thread_feed = parse_feed(
                fetch(f"/r/{sub}/comments/{p['id']}/.rss",
                      {"limit": PAGE_LIMIT}))
            for c in thread_feed:
                if c["kind"] != "t1":
                    continue  # the post repeats as the feed's first entry
                if not keep_text(c["text"], c["author"], cfg.min_comment_words):
                    continue
                n_comments += 1
                items.append(_item(c, sub, "comment"))
        inserted = db.upsert_items(conn, items)
        dates = [i["created_utc"] for i in items]
        conn.execute(
            "INSERT INTO coverage VALUES (?,?,?,?,?,?)",
            (sub, int(time.time()), min(dates, default=None),
             max(dates, default=None), len(posts), n_comments))
        conn.commit()
        print(f"r/{sub}: {len(posts)} posts, {n_comments} comments "
              f"({inserted} new items)")
