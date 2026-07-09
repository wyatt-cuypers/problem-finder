import numpy as np
from sklearn.cluster import HDBSCAN

MAX_SUMMARY_STATEMENTS = 30
MAX_SUMMARY_NOTES = 15

SUMMARY_PROMPT = """\
The following problem statements were extracted from Reddit and clustered as \
one underlying problem.

Statements:
{statements}

Solution notes from the same threads (may be empty):
{notes}

Return ONLY a JSON object with keys:
- "canonical_statement": ONE general sentence stating the underlying problem
- "solution_summary": 1-2 sentences on existing products/workarounds people \
mention and their shortcomings, or "none mentioned"
- "opportunity_note": one line on why this could be a business opportunity
- "coherent": false if these look like two or more unrelated problems merged \
together, else true
"""


def vec_to_blob(v) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def blob_to_vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def cluster_labels(vectors: np.ndarray, min_cluster_size: int) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.clip(norms, 1e-10, None)
    return HDBSCAN(min_cluster_size=min_cluster_size, copy=True).fit_predict(unit)


def build_summary_prompt(statements: list[str], notes: list[str]) -> str:
    s = "\n".join(f"- {x}" for x in statements[:MAX_SUMMARY_STATEMENTS])
    n = "\n".join(f"- {x}" for x in notes[:MAX_SUMMARY_NOTES]) or "(none)"
    return SUMMARY_PROMPT.format(statements=s, notes=n)


def run_embed(conn, cfg, client) -> None:
    rows = conn.execute("""\
        SELECT e.item_id, e.problem_statement FROM extractions e
        LEFT JOIN embeddings b ON b.item_id = e.item_id
        WHERE e.status='ok' AND e.is_problem=1 AND b.item_id IS NULL
        ORDER BY e.item_id""").fetchall()
    if not rows:
        print("embed: nothing to do")
        return
    vectors = client.embed([r["problem_statement"] for r in rows])
    conn.executemany("INSERT INTO embeddings VALUES (?,?)",
                     [(r["item_id"], vec_to_blob(v))
                      for r, v in zip(rows, vectors)])
    conn.commit()
    print(f"embed: {len(rows)} statements embedded")


def run_cluster(conn, cfg, client) -> None:
    rows = conn.execute(
        "SELECT item_id, vector FROM embeddings ORDER BY item_id").fetchall()
    if len(rows) < cfg.min_cluster_size:
        print("cluster: not enough embeddings")
        return
    vectors = np.vstack([blob_to_vec(r["vector"]) for r in rows])
    labels = cluster_labels(vectors, cfg.min_cluster_size)

    conn.execute("DELETE FROM cluster_scores")
    conn.execute("DELETE FROM cluster_members")
    conn.execute("DELETE FROM clusters")
    by_label: dict[int, list[str]] = {}
    for r, label in zip(rows, labels):
        if label != -1:
            by_label.setdefault(int(label), []).append(r["item_id"])

    for label, item_ids in sorted(by_label.items()):
        placeholders = ",".join("?" * len(item_ids))
        ex = conn.execute(
            f"""SELECT problem_statement, solution_notes FROM extractions
                WHERE item_id IN ({placeholders})""", item_ids).fetchall()
        statements = [r["problem_statement"] for r in ex]
        notes = [r["solution_notes"] for r in ex if r["solution_notes"]]
        try:
            s = client.generate_json(build_summary_prompt(statements, notes))
            canonical = s.get("canonical_statement") or statements[0]
            solution = s.get("solution_summary") or "none mentioned"
            note = s.get("opportunity_note") or ""
            coherent = bool(s.get("coherent", True))
        except Exception as exc:
            print(f"cluster {label}: summary failed ({exc}); using fallback")
            canonical, solution, note, coherent = (
                statements[0], "none mentioned", "", True)
        cur = conn.execute(
            "INSERT INTO clusters (canonical_statement, solution_summary,"
            " opportunity_note, coherence_flag) VALUES (?,?,?,?)",
            (canonical, solution, note, int(not coherent)))
        conn.executemany(
            "INSERT INTO cluster_members VALUES (?,?)",
            [(i, cur.lastrowid) for i in item_ids])
    conn.commit()
    n_noise = int((labels == -1).sum())
    print(f"cluster: {len(by_label)} clusters, {n_noise} noise items")
