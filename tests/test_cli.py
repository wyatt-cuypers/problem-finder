import pytest

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
    with pytest.raises(SystemExit):
        cli.main(["frobnicate", "--config", "config/pilot.yaml"])


def _scrub_env(monkeypatch):
    """Remove API keys AND stop load_dotenv re-adding them from a real .env."""
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    for var in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_missing_env_keys_exit_with_clear_message(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("subreddits: [running]\nwindow_days: 14\n")
    _scrub_env(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--config", str(cfg)])
    assert "GEMINI_API_KEY" in str(exc.value)
    assert "REDDIT_CLIENT_ID" in str(exc.value)
    assert ".env" in str(exc.value)


def test_public_collector_needs_no_reddit_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("subreddits: [running]\nwindow_days: 14\ncollector: public\n")
    _scrub_env(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--config", str(cfg)])
    assert "GEMINI_API_KEY" in str(exc.value)
    assert "REDDIT_CLIENT_ID" not in str(exc.value)
