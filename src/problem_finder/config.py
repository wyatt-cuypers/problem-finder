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
    extract_model: str = "gemini-3.6-flash"
    embed_model: str = "gemini-embedding-001"
    min_cluster_size: int = 3
    pilot: bool = False
    collector: str = "praw"        # "praw" (OAuth app) or "public" (no keys)
    request_interval_s: float = 10.0  # public collector only


def load_config(path: str | Path) -> Config:
    data = yaml.safe_load(Path(path).read_text())
    return Config(**data)
