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
