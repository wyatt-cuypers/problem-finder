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


def test_collector_defaults(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("subreddits: [running]\nwindow_days: 14\n")
    cfg = load_config(p)
    assert cfg.collector == "praw"
    assert cfg.request_interval_s == 10.0
