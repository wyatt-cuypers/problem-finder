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
