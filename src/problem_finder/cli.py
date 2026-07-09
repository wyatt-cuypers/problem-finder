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
