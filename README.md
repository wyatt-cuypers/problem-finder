# Problem Finder

Mines Reddit for recurring, unsolved problems people complain about and ranks
them as potential business opportunities. Output: an xlsx report (top 50 +
all clusters + run info) and a markdown summary of the top 10.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then fill in the three keys below
```

### Reddit access: two modes

`collector: public` in the yaml config uses Reddit's public Atom/RSS feeds —
**no Reddit credentials needed**, just the Gemini key. Tradeoffs: throttled to
one request every ~6.5s (a pilot collect takes an hour or two), comment scores
are unavailable, and each thread yields at most ~100 comments. Use this while
Reddit API app approval is pending (self-serve app creation at
reddit.com/prefs/apps was disabled by Reddit's Responsible Builder Policy, and
unauthenticated .json endpoints were closed in May 2026; new OAuth apps
require manual approval via Reddit's request form).

`collector: praw` (the default) uses the official OAuth API and needs the
credentials below.

### Reddit API credentials (praw mode only)

1. Go to https://www.reddit.com/prefs/apps while logged in.
2. Click "create another app...", choose type **script**, any name,
   redirect uri `http://localhost:8080`.
3. Copy the string under the app name into `REDDIT_CLIENT_ID`, and the
   "secret" into `REDDIT_CLIENT_SECRET`.
4. Set `REDDIT_USER_AGENT` to `problem-finder/0.1 by u/<your-username>`.

### Gemini API key

1. Go to https://aistudio.google.com/apikey and create a key.
2. Put it in `GEMINI_API_KEY`.

## Running

Pilot (5 subreddits, 14 days — sanity-check extraction quality first):

```bash
.venv/bin/pf run --config config/pilot.yaml
```

Stages can run individually and always resume where they left off:

```bash
.venv/bin/pf collect --config config/pilot.yaml
.venv/bin/pf extract --config config/pilot.yaml
.venv/bin/pf cluster --config config/pilot.yaml
.venv/bin/pf score   --config config/pilot.yaml
.venv/bin/pf report  --config config/pilot.yaml
```

Reports land in `output/`. On pilot runs the xlsx includes an
**Extraction QA** sheet — 30 random items with the model's judgment beside
the raw text. Review it before running the full config.

Full run (edit `config/full.yaml` subreddit list first):

```bash
.venv/bin/pf run --config config/full.yaml
```

## Notes

- Reddit listings cap at ~1,000 posts each; the "Run info" sheet shows the
  date coverage actually achieved per subreddit.
- The pipeline stores everything in `data/problem_finder.db`; delete it to
  start fresh, or re-run `collect` anytime to pull new content incrementally.
- Costs: extraction dominates; a pilot run is well under $5 of Gemini usage.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```
