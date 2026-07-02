MAX_ITEM_CHARS = 1500
MAX_ATTEMPTS = 3

EXTRACT_PROMPT = """\
You are analyzing Reddit posts and comments to find problems people complain \
about, for market research. For EACH numbered item below, decide whether it \
expresses a problem, frustration, or unmet need.

Return ONLY a JSON array with one object per item, each with these keys:
- "index": the item's number
- "is_problem": true/false
- "problem_statement": if is_problem, ONE general, de-contextualized sentence \
naming the underlying problem (not "my Peloton screen froze again" but \
"fitness equipment touchscreens are unreliable"); else null
- "category": one of "home", "fitness", "travel", "finance", "dev-tools", "other"
- "solution_mentioned": "none" if no existing product/workaround/fix is \
referenced; "mentioned-adequate" if one is referenced and described as \
working well; "mentioned-inadequate" if one is referenced but called \
expensive, clunky, incomplete, discontinued, or otherwise unsatisfying
- "solution_notes": short note naming the product/workaround and the complaint \
about it, or null
- "wish_expressed": true if the author explicitly wishes a product/service \
existed (e.g. "I wish someone made X", "why is there no app for this")

Items:
{items}
"""

VALID_SOLUTION = {"none", "mentioned-adequate", "mentioned-inadequate"}
VALID_CATEGORY = {"home", "fitness", "travel", "finance", "dev-tools", "other"}


def build_extract_prompt(texts: list[str]) -> str:
    lines = [f"[{i}] {t[:MAX_ITEM_CHARS]}" for i, t in enumerate(texts)]
    return EXTRACT_PROMPT.format(items="\n\n".join(lines))


def parse_extraction_response(data, n_items: int) -> list[dict | None]:
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data).__name__}")
    rows: list[dict | None] = [None] * n_items
    for obj in data:
        if not isinstance(obj, dict):
            continue
        i = obj.get("index")
        if not isinstance(i, int) or not 0 <= i < n_items:
            continue
        sol = obj.get("solution_mentioned")
        cat = obj.get("category")
        rows[i] = {
            "is_problem": bool(obj.get("is_problem")),
            "problem_statement": obj.get("problem_statement"),
            "category": cat if cat in VALID_CATEGORY else "other",
            "solution_mentioned": sol if sol in VALID_SOLUTION else "none",
            "solution_notes": obj.get("solution_notes"),
            "wish_expressed": bool(obj.get("wish_expressed")),
        }
    return rows


PENDING_SQL = """\
SELECT i.id, i.text, COALESCE(e.attempts, 0) AS attempts
FROM items i LEFT JOIN extractions e ON e.item_id = i.id
WHERE e.item_id IS NULL OR (e.status = 'failed' AND e.attempts < ?)
ORDER BY i.id LIMIT ?"""

UPSERT_SQL = """\
INSERT INTO extractions (item_id, status, is_problem, problem_statement,
    category, solution_mentioned, solution_notes, wish_expressed, attempts)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT(item_id) DO UPDATE SET status=excluded.status,
    is_problem=excluded.is_problem,
    problem_statement=excluded.problem_statement,
    category=excluded.category,
    solution_mentioned=excluded.solution_mentioned,
    solution_notes=excluded.solution_notes,
    wish_expressed=excluded.wish_expressed,
    attempts=excluded.attempts"""


def _save(conn, item_id: str, row: dict | None, attempts: int) -> None:
    if row is None:
        conn.execute(UPSERT_SQL, (item_id, "failed", None, None, None,
                                  None, None, None, attempts))
    else:
        conn.execute(UPSERT_SQL, (
            item_id, "ok", int(row["is_problem"]), row["problem_statement"],
            row["category"], row["solution_mentioned"], row["solution_notes"],
            int(row["wish_expressed"]), attempts))


def run_extract(conn, cfg, client) -> None:
    done = 0
    while True:
        batch = conn.execute(
            PENDING_SQL, (MAX_ATTEMPTS, cfg.extract_batch_size)).fetchall()
        if not batch:
            break
        texts = [r["text"] for r in batch]
        try:
            rows = parse_extraction_response(
                client.generate_json(build_extract_prompt(texts)), len(batch))
        except Exception as exc:
            print(f"extract: batch failed ({exc})")
            rows = [None] * len(batch)
        for r, parsed in zip(batch, rows):
            _save(conn, r["id"], parsed, r["attempts"] + 1)
        conn.commit()
        done += len(batch)
        if done % 200 == 0:
            print(f"extract: {done} items processed")
    n_failed = conn.execute(
        "SELECT COUNT(*) AS n FROM extractions WHERE status='failed'"
    ).fetchone()["n"]
    print(f"extract: done ({done} this run, {n_failed} failed total)")
