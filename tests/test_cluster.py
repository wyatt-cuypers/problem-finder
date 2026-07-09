import numpy as np

from problem_finder import db
from problem_finder.cluster import (blob_to_vec, build_summary_prompt,
                                    cluster_labels, run_cluster, run_embed,
                                    vec_to_blob)
from tests.test_db import make_item


def test_blob_roundtrip():
    v = np.array([0.1, -0.5, 2.0], dtype=np.float32)
    assert np.array_equal(blob_to_vec(vec_to_blob(v)), v)


def test_cluster_labels_groups_nearby_vectors():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=(5, 0, 0), scale=0.05, size=(10, 3))
    b = rng.normal(loc=(0, 5, 0), scale=0.05, size=(10, 3))
    labels = cluster_labels(np.vstack([a, b]).astype(np.float32), 3)
    assert len(set(labels[:10])) == 1 and labels[0] != -1
    assert len(set(labels[10:])) == 1 and labels[10] != -1
    assert labels[0] != labels[10]


def test_summary_prompt_includes_statements_and_notes():
    p = build_summary_prompt(["shoes wear out fast"], ["rotating pairs is pricey"])
    assert "shoes wear out fast" in p
    assert "rotating pairs is pricey" in p
    assert "canonical_statement" in p


class FakeClient:
    def embed(self, texts):
        # deterministic: statement text controls direction
        return [[1.0, 0.0] if "shoe" in t else [0.0, 1.0] for t in texts]

    def generate_json(self, prompt):
        return {"canonical_statement": "canon", "solution_summary": "none mentioned",
                "opportunity_note": "note", "coherent": True}


class Cfg:
    min_cluster_size = 3


def _seed(conn, n_shoe=4, n_wifi=4):
    items, i = [], 0
    for k in range(n_shoe):
        items.append(make_item(f"s{k}", thread_id=f"t{i}")); i += 1
    for k in range(n_wifi):
        items.append(make_item(f"w{k}", thread_id=f"t{i}")); i += 1
    db.upsert_items(conn, items)
    for k in range(n_shoe):
        conn.execute("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"s{k}", "ok", 1, "shoes wear out fast", "fitness",
                      "none", None, 0, 1))
    for k in range(n_wifi):
        conn.execute("INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"w{k}", "ok", 1, "hotel wifi is unreliable", "travel",
                      "none", None, 0, 1))
    conn.commit()


def test_run_embed_then_cluster_builds_two_clusters():
    conn = db.connect(":memory:")
    _seed(conn)
    client = FakeClient()
    run_embed(conn, Cfg(), client)
    assert conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"] == 8
    run_embed(conn, Cfg(), client)  # idempotent: no missing rows -> no change
    run_cluster(conn, Cfg(), client)
    n_clusters = conn.execute("SELECT COUNT(*) AS n FROM clusters").fetchone()["n"]
    assert n_clusters == 2
    members = conn.execute(
        "SELECT cluster_id, COUNT(*) AS n FROM cluster_members GROUP BY 1"
    ).fetchall()
    assert sorted(m["n"] for m in members) == [4, 4]
    c = conn.execute("SELECT * FROM clusters").fetchone()
    assert c["canonical_statement"] == "canon"
