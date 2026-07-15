import argparse
import os

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
REQUIRED_ENV = {
    "collect": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
    "extract": ["GEMINI_API_KEY"],
    "cluster": ["GEMINI_API_KEY"],
}


def _check_env(stages: list[str], cfg) -> None:
    required = [var for stage in stages for var in REQUIRED_ENV.get(stage, [])]
    if cfg.collector == "public":
        required = [v for v in required if not v.startswith("REDDIT_")]
    missing = [var for var in required if not os.environ.get(var)]
    if missing:
        raise SystemExit(
            "missing environment variables: " + ", ".join(dict.fromkeys(missing))
            + " — copy .env.example to .env and fill it in (see README)")


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="pf", description="Mine Reddit for recurring unsolved problems")
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--config", required=True, help="path to yaml config")
    args = parser.parse_args(argv)

    stages = (["collect", "extract", "cluster", "score", "report"]
              if args.stage == "run" else [args.stage])
    cfg = load_config(args.config)
    _check_env(stages, cfg)
    conn = db.connect(cfg.db_path)

    client = None
    if NEEDS_GEMINI & set(stages):
        from .gemini import GeminiClient
        client = GeminiClient(cfg.extract_model, cfg.embed_model)

    for stage in stages:
        if stage == "collect":
            if cfg.collector == "public":
                from .collect_public import run_collect_public
                run_collect_public(conn, cfg)
            else:
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
