"""Build / refresh every index scheme from the persona corpora.

    python -m rag.ingest.build            # all personas, all schemes (incremental)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rag.index.store import get_index
from rag.ingest.loaders import load_persona

ROOT = Path(__file__).resolve().parents[2]
SCHEMES = ("naive", "structured", "contextual")


def build(personas=("ai_ml", "fullstack", "data_analyst"), schemes=SCHEMES):
    docs = [d for p in personas for d in load_persona(ROOT / "data" / "personas" / p)]
    report = {}
    for s in schemes:
        t = time.time()
        report[s] = get_index(s).upsert_docs(docs) | {"seconds": round(time.time() - t, 1)}
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", action="append")
    a = ap.parse_args()
    print(build(tuple(a.persona) if a.persona else ("ai_ml", "fullstack", "data_analyst")))
