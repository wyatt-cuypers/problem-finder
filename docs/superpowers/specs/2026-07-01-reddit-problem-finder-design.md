# Reddit Problem Finder — Design Spec

**Date:** 2026-07-01
**Status:** Approved design, pending implementation plan

## Purpose

Identify recurring, unsolved problems people complain about on Reddit and rank them as
potential business opportunities. Output: a ranked top-50 list with supporting evidence,
as an xlsx spreadsheet plus a markdown summary of the top 10.

A **pilot run** (5 subreddits, 14-day window) runs first; the full run (approved
subreddit list, 6–12 month window) only happens after the user reviews pilot extraction
quality.

## Architecture Overview

A Python CLI pipeline of five idempotent, resumable stages backed by a SQLite store:

```
collect → extract → cluster → score → report
```

Each stage reads and writes SQLite, processing only rows not yet handled by that stage,
so any failure (rate limit, API error, interrupt) resumes rather than restarts. Stages
run individually (`pf collect --config config/pilot.yaml`) or chained (`pf run`).

### Project layout

```
problem-finder/
├── config/
│   ├── pilot.yaml          # 5 subs, 14-day window, item caps
│   └── full.yaml           # full sub list, 12-month window (user-approved before running)
├── src/problem_finder/
│   ├── collect.py          # Reddit → SQLite
│   ├── extract.py          # items → Gemini → problem statements + solution signals
│   ├── cluster.py          # embeddings + HDBSCAN → clusters
│   ├── score.py            # recurrence gate, unsolved-ness, composite score
│   ├── report.py           # xlsx + markdown
│   └── cli.py              # `pf collect|extract|cluster|score|report|run`
├── data/problem_finder.db  # SQLite (gitignored)
├── output/                 # timestamped reports (gitignored)
└── .env                    # REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, GEMINI_API_KEY
```

### External services

- **Reddit API** via PRAW (script-type OAuth app; free tier, 100 req/min). No pushshift.
- **Gemini** via `google-genai`: `gemini-2.5-flash` with structured JSON output for
  extraction and per-cluster summarization; `gemini-embedding-001` for embeddings.

## Stage 1: Collection

Config specifies subreddits, date window, and per-sub item caps. For each subreddit:

- Pull post listings from `new`, `top` (year and month), and `controversial`, dedupe by
  post ID, filter to the date window. (Reddit caps each listing at ~1,000 posts;
  combining listings maximizes coverage but cannot guarantee completeness — the run
  report states actual coverage per sub.)
- For each in-window post, fetch the full comment tree (`replace_more`) and store every
  comment as a first-class item. Comments are the primary signal source.
- Stored fields per item: id, type (post/comment), subreddit, thread id, hashed author,
  created date, score, text, permalink.
- Skipped: deleted/removed items, known bots (AutoModerator etc.), comments shorter
  than ~15 words (configurable threshold).
- A `coverage` table records per-sub date ranges and counts actually retrieved.

PRAW handles rate limiting. Re-runs skip already-stored items, enabling incremental
"ongoing new content" pulls with the same command.

## Stage 2: Extraction

Items are sent to `gemini-2.5-flash` in batches of ~20 per call, with structured JSON
output. Per item the model returns:

- `is_problem` (bool) — does this express a problem/frustration/unmet need?
- `problem_statement` — general, de-contextualized sentence (e.g., not "my Peloton
  screen froze again" but "fitness equipment touchscreens are unreliable").
- `category` — coarse: home, fitness, travel, finance, dev-tools, other.
- `solution_mentioned` — none / mentioned-adequate / mentioned-inadequate.
- `solution_notes` — what product/workaround was named and any complaint about it
  (expensive, clunky, incomplete, discontinued).
- `wish_expressed` (bool) — explicit "I wish someone made X" signal.

Results persist to an `extractions` table keyed by item id. Re-runs skip extracted
items; the table supports re-extraction with a revised prompt on a chosen subset.
Non-problems are marked and never reprocessed.

## Stage 3: Clustering

- Embed each problem statement with `gemini-embedding-001`; embeddings persist keyed by
  extraction id.
- Cluster with HDBSCAN over cosine distance. No preset cluster count; true one-offs
  remain noise instead of polluting clusters.
- One `gemini-2.5-flash` call per cluster produces: a canonical one-sentence problem
  statement, a solution-landscape summary (from members' `solution_notes`), a one-line
  "why this looks like an opportunity" note, and a coherence flag if the cluster looks
  like two merged topics (surfaced in the report; no automated splitting).

## Stage 4: Scoring and Filters

Computed per cluster from member items:

- **Recurring gate (hard):** ≥ 3 distinct threads AND ≥ 3 distinct authors. Multiple
  comments in one thread count as one conversation, not a pattern.
- **Tracked stats:** mention count, distinct threads, distinct authors, distinct
  subreddits, first/last seen dates.
- **Spike flag:** clusters whose mentions all fall within one 2-week burst inside a
  longer window are flagged as possibly news-driven.
- **Unsolved-ness (0–1):** share of mentions with no solution or an inadequate solution
  referenced, boosted by explicit wishes. Clusters dominated by `mentioned-adequate`
  are dropped as solved. Surviving clusters are "partially solved" or "unsolved."
- **Composite score:** `log(1 + mentions) × recency_weight × unsolvedness`, where
  recency weight favors clusters still active in the most recent quarter of the window.
  Log damping prevents one viral complaint from dominating.

## Stage 5: Report

- `output/report_<timestamp>.xlsx`:
  - Sheet 1 — top 50 by composite score: rank, canonical problem statement, score,
    mention/thread/author/subreddit counts, date range, unsolved-ness, spike flag,
    solution-landscape summary, 2–3 **paraphrased** examples (subreddit + month),
    permalinks for spot-checking, opportunity note.
  - Sheet 2 — all clusters passing the gates, same columns.
- `output/summary_<timestamp>.md` — top 10 in prose with more detail.
- **Pilot only:** an extraction-quality appendix — 30 random items showing raw text
  beside the model's judgment, for sanity-checking before approving the full run.
- Run report footer: per-sub coverage, API call/token tallies, failed-item counts.

## Error Handling

- Gemini calls retry with exponential backoff; items failing 3× are marked
  `extract_failed` and counted in the run report — never silently dropped.
- Collection failures leave completed items in SQLite; re-run continues.
- All API usage (calls, tokens, estimated cost) tallied per run and printed at the end.

## Costs and Limits (flagged up front)

- Extraction dominates cost; batching ~20 items/call keeps the pilot under ~$5 and a
  full run in the low tens of dollars (Gemini Flash pricing).
- Reddit free tier (100 req/min) is the throughput ceiling: pilot ≈ an hour of wall
  clock; full historical pull ≈ hours, unattended-safe due to resumability.
- Reddit listing caps mean 12 months of "everything" is not literally achievable
  post-pushshift; the coverage table keeps this honest.

## Testing

- Unit tests with fixture data for non-API logic: window/length filters, recurrence
  gate, unsolved-ness and composite scoring, clustering glue, report generation.
- Recorded sample Reddit/Gemini payloads as fixtures.
- API-touching wrappers kept thin; verified live during the pilot run.

## Pilot Configuration

- Subreddits: r/mildlyinfuriating, r/homeowners, r/smallbusiness, r/running,
  r/awardtravel (one per user category; user may swap before running).
- Window: most recent 14 days. Caps sized to keep the pilot under ~$5.

## Out of Scope (YAGNI)

- Scheduling/orchestration (Prefect, cron) — manual CLI runs only.
- Automated cluster splitting — coherence issues are flagged, not fixed.
- Verbatim quotes in output — examples are paraphrased.
- Dashboards/web UI — xlsx + markdown only.
