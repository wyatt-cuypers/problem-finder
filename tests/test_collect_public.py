from problem_finder import db
from problem_finder.collect_public import (html_to_text, parse_feed,
                                           run_collect_public)

NOW = 1_752_500_000  # 2026-07-14T13:33:20Z
DAY = 86400


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _post_entry(pid, created, author="someuser", title="my wifi keeps dying",
                body="<div class=\"md\"><p>the router drops every hour</p></div>"):
    return f"""<entry>
      <author><name>/u/{author}</name><uri>https://www.reddit.com/user/{author}</uri></author>
      <content type="html">{body.replace('<', '&lt;').replace('>', '&gt;')}
        submitted by /u/{author} [link] [comments]</content>
      <id>t3_{pid}</id>
      <link href="https://www.reddit.com/r/test/comments/{pid}/my_wifi/"/>
      <updated>{_iso(created)}</updated>
      <title>{title}</title>
    </entry>"""


def _comment_entry(cid, tid, body, created=NOW - DAY, author="someuser"):
    return f"""<entry>
      <author><name>/u/{author}</name><uri>https://www.reddit.com/user/{author}</uri></author>
      <content type="html">&lt;div class="md"&gt;&lt;p&gt;{body}&lt;/p&gt;&lt;/div&gt;</content>
      <id>t1_{cid}</id>
      <link href="https://www.reddit.com/r/test/comments/{tid}/my_wifi/{cid}/"/>
      <updated>{_iso(created)}</updated>
      <title>/u/{author} on my wifi keeps dying</title>
    </entry>"""


def _feed(*entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            + "".join(entries) + "</feed>")


def test_html_to_text_strips_tags_and_unescapes():
    fragment = '<div class="md"><p>it&#39;s broken &amp; unusable</p></div>'
    assert html_to_text(fragment) == "it's broken & unusable"


def test_parse_feed_extracts_posts_and_comments():
    xml = _feed(_post_entry("p1", NOW - DAY),
                _comment_entry("c1", "p1", "same issue here with my setup"))
    entries = parse_feed(xml)
    assert [e["kind"] for e in entries] == ["t3", "t1"]
    post, comment = entries
    assert post["id"] == "p1" and post["thread_id"] == "p1"
    assert post["author"] == "someuser"
    assert post["created_utc"] == NOW - DAY
    assert "my wifi keeps dying" in post["text"]
    assert "router drops every hour" in post["text"]
    assert "submitted by" not in post["text"]  # boilerplate stripped
    assert comment["thread_id"] == "p1"
    assert comment["text"] == "same issue here with my setup"
    assert comment["permalink"].startswith("/r/test/comments/p1/")


def test_parse_feed_normalizes_deleted_author():
    xml = _feed(_comment_entry("c9", "p1", "gone", author="[deleted]"))
    assert parse_feed(xml)[0]["author"] is None


class FakeFetch:
    """Stands in for PublicFetcher; returns canned XML per path."""

    def __init__(self, pages):
        self.pages = pages  # {path: [xml, xml, ...]}
        self.paths = []

    def __call__(self, path, params):
        self.paths.append(path)
        queue = self.pages.get(path, [])
        return queue.pop(0) if queue else _feed()


class Cfg:
    subreddits = ["test"]
    window_days = 14
    min_comment_words = 3
    max_posts_per_sub = 50


LONG = "this thing constantly breaks and nothing fixes it properly"


def test_run_collect_public_stores_posts_comments_and_coverage():
    listing = _feed(_post_entry("p1", NOW - DAY),
                    _post_entry("p2", NOW - 40 * DAY))  # outside window
    comments = _feed(_post_entry("p1", NOW - DAY),  # post repeated in thread feed
                     _comment_entry("c1", "p1", LONG),
                     _comment_entry("c2", "p1", "too short"))
    fetch = FakeFetch({"/r/test/new.rss": [listing],
                       "/r/test/comments/p1.rss": [comments]})
    conn = db.connect(":memory:")
    run_collect_public(conn, Cfg(), fetch=fetch, now=NOW)
    ids = [r["id"] for r in conn.execute("SELECT id FROM items ORDER BY id")]
    assert ids == ["t1_c1", "t3_p1"]  # short comment + out-of-window post dropped
    cov = conn.execute("SELECT * FROM coverage").fetchone()
    assert cov["subreddit"] == "test" and cov["post_count"] == 1
    assert cov["comment_count"] == 1


def test_run_collect_public_skips_already_collected_threads():
    listing = _feed(_post_entry("p1", NOW - DAY))
    comments = _feed(_comment_entry("c1", "p1", LONG))
    conn = db.connect(":memory:")
    fetch = FakeFetch({"/r/test/new.rss": [listing],
                       "/r/test/comments/p1.rss": [comments]})
    run_collect_public(conn, Cfg(), fetch=fetch, now=NOW)
    assert sum(p.startswith("/r/test/comments/") for p in fetch.paths) == 1

    fetch2 = FakeFetch({"/r/test/new.rss": [listing]})
    run_collect_public(conn, Cfg(), fetch=fetch2, now=NOW)
    assert sum(p.startswith("/r/test/comments/") for p in fetch2.paths) == 0
    assert conn.execute("SELECT COUNT(*) n FROM items").fetchone()["n"] == 2


def test_max_posts_per_sub_is_enforced_within_a_page():
    listing = _feed(*[_post_entry(f"p{i}", NOW - DAY) for i in range(5)])
    pages = {"/r/test/new.rss": [listing]}
    pages.update({f"/r/test/comments/p{i}.rss": [_feed()] for i in range(5)})
    fetch = FakeFetch(pages)
    conn = db.connect(":memory:")

    class CappedCfg(Cfg):
        max_posts_per_sub = 2

    run_collect_public(conn, CappedCfg(), fetch=fetch, now=NOW)
    assert sum(p.startswith("/r/test/comments/") for p in fetch.paths) == 2
