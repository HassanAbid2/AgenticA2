"""Chunk store + vector index (Qdrant) + BM25.

Source of truth is the chunk store (data/processed/chunks_<scheme>.jsonl) plus an embedding cache
keyed by chunk hash. Qdrant is the vector store: a server when QDRANT_URL is set (docker compose),
otherwise an in-process instance rebuilt from the cache in about a second.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from rag.ingest.loaders import Doc

PROCESSED = Path(os.getenv("GIGBID_PROCESSED_DIR", Path(__file__).resolve().parents[2] / "data" / "processed"))
MODELS_DIR = os.getenv("GIGBID_MODELS_DIR", str(Path(__file__).resolve().parents[2] / "var" / "models"))
EMBED_MODEL = os.getenv("GIGBID_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
TOKEN = re.compile(r"[a-z0-9][a-z0-9.+#/-]*")


def tokenize(text: str) -> list[str]:
    return [t.strip(".") for t in TOKEN.findall(text.lower())]


@lru_cache
def embedder(model: str = EMBED_MODEL):
    from fastembed import TextEmbedding

    return TextEmbedding(model, cache_dir=MODELS_DIR)


def embed(texts: list[str], model: str = EMBED_MODEL) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    v = np.array(list(embedder(model).embed(texts, batch_size=64)), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True).clip(1e-9)


@dataclass
class Chunk:
    chunk_id: str
    evidence_id: str
    owner: str
    persona: str
    type: str
    title: str
    text: str  # what the writer sees
    embed_text: str  # what gets embedded / BM25-indexed (may carry a context line)
    project: str | None = None
    skills: list[str] = field(default_factory=list)
    date: str | None = None
    client_industry: str | None = None
    outcome: str | None = None
    source: str = ""
    part: str = "body"
    doc_hash: str = ""

    def meta(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("embed_text",)}


# ----------------------------------------------------------------------------- chunking schemes
def _sections(md: str) -> list[str]:
    parts = re.split(r"\n(?=## )", md)
    return [p.strip() for p in parts if p.strip()]


def chunk_doc(d: Doc, scheme: str) -> list[Chunk]:
    def mk(i, text, part="body", embed_text=None):
        cid = f"{d.evidence_id}#{scheme}#{i}"
        return Chunk(cid, d.evidence_id, d.owner, d.persona, d.type, d.title, text, embed_text or text, d.project,
                     d.skills, d.date, d.client_industry, d.outcome, d.source, part, d.content_hash)

    if scheme == "naive":  # V0: fixed windows, no structure, no metadata
        size, step = 400, 320
        return [mk(i, d.text[s: s + size]) for i, s in enumerate(range(0, max(1, len(d.text)), step)) if d.text[s: s + size].strip()]

    if d.type in ("case_study",):
        pieces = _sections(d.text)
        head = f"{d.title}. "
        chunks = [mk(i, head + p, part="summary" if i == 0 else "section") for i, p in enumerate(pieces)]
    elif d.type == "cv":
        pieces = re.split(r"\n(?=(?:Summary|Core skills|Selected experience|Education)\n)", d.text)
        chunks = [mk(i, p.strip(), part="cv") for i, p in enumerate(pieces) if p.strip()]
    elif d.type == "code":
        chunks = [mk(0, f"{d.title}\n{d.text[:2000]}", part="code")]
    elif d.type == "readme":
        chunks = [mk(0, d.text[:2000], part="readme")]
    else:  # proposals, reviews, blog posts, uploads: whole document
        chunks = [mk(i, d.text[s: s + 1500]) for i, s in enumerate(range(0, max(1, len(d.text)), 1500))]

    if scheme == "contextual":  # V6: context line prepended (metadata-generated; see docs/adr)
        ctx = (f"[{d.type.replace('_', ' ')} | project: {d.project or 'unknown'} | industry: {d.client_industry or '-'}"
               f" | skills: {', '.join(d.skills[:10]) or '-'}" + (f" | outcome: {d.outcome}" if d.outcome else "") + "]\n")
        for c in chunks:
            c.embed_text = ctx + c.text
    return chunks


# ----------------------------------------------------------------------------- index
class PortfolioIndex:
    """All chunks for one scheme, across every owner (tenant); every query filters by owner."""

    def __init__(self, scheme: str = "structured", model: str = EMBED_MODEL):
        self.scheme, self.model = scheme, model
        self.path = PROCESSED / f"chunks_{scheme}.jsonl"
        self.cache_path = PROCESSED / f"emb_{model.replace('/', '_')}_{scheme}.npz"
        self.lock = threading.RLock()
        self._mtime = None
        self.chunks: list[Chunk] = []
        self.vecs = np.zeros((0, 384), dtype=np.float32)
        self.qdrant = None
        self.collection = f"gigbid_{scheme}_{hashlib.sha1(model.encode()).hexdigest()[:6]}"
        self.reload()

    # -- persistence
    def _load_chunks(self):
        if not self.path.exists():
            return []
        return [Chunk(**json.loads(line)) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _save_chunks(self):
        PROCESSED.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for c in self.chunks:
                f.write(json.dumps(c.__dict__) + "\n")
        tmp.replace(self.path)

    def _emb_cache(self) -> dict[str, np.ndarray]:
        if not self.cache_path.exists():
            return {}
        z = np.load(self.cache_path)
        return dict(zip(z["keys"].tolist(), z["vecs"], strict=True))

    @staticmethod
    def _key(c: Chunk) -> str:
        return hashlib.sha1(c.embed_text.encode()).hexdigest()

    def _ensure_vectors(self):
        cache = self._emb_cache()
        missing = [c for c in self.chunks if self._key(c) not in cache]
        if missing:
            for c, v in zip(missing, embed([c.embed_text for c in missing], self.model), strict=True):
                cache[self._key(c)] = v
            keys = list(cache)
            PROCESSED.mkdir(parents=True, exist_ok=True)
            np.savez(self.cache_path, keys=np.array(keys), vecs=np.stack([cache[k] for k in keys]))
        self.vecs = np.stack([cache[self._key(c)] for c in self.chunks]) if self.chunks else np.zeros((0, 384), np.float32)

    def reload(self):
        with self.lock:
            self._mtime = self.path.stat().st_mtime if self.path.exists() else None
            self.chunks = self._load_chunks()
            self._ensure_vectors()
            self.bm25 = BM25Okapi([tokenize(c.embed_text) for c in self.chunks]) if self.chunks else None
            self.full: dict[str, str] = {}
            for c in self.chunks:  # whole document per evidence id (a chunk alone may miss the results section)
                self.full[c.evidence_id] = (self.full[c.evidence_id] + "\n" + c.text) if c.evidence_id in self.full else c.text
            self._sync_qdrant()

    def maybe_reload(self):
        m = self.path.stat().st_mtime if self.path.exists() else None
        if m != self._mtime:
            self.reload()

    def _sync_qdrant(self):
        """Idempotent sync, safe when several processes share one Qdrant server (API, worker, Portfolio
        MCP): upsert points whose chunk id is missing, delete points no longer in the chunk store."""
        from qdrant_client import QdrantClient, models

        url = os.getenv("QDRANT_URL")
        if self.qdrant is None:
            self.qdrant = QdrantClient(url=url, timeout=30) if url else QdrantClient(":memory:")
        self.by_id = {c.chunk_id: c for c in self.chunks}
        dim = self.vecs.shape[1] if len(self.vecs) else 384
        if not self.qdrant.collection_exists(self.collection):
            self.qdrant.create_collection(self.collection, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
            if url:  # payload indexes are a server feature; the in-process instance ignores them
                self.qdrant.create_payload_index(self.collection, "owner", models.PayloadSchemaType.KEYWORD)
        pid = lambda cid: str(uuid.uuid5(uuid.NAMESPACE_URL, cid))  # noqa: E731
        existing, offset = set(), None
        while True:
            pts, offset = self.qdrant.scroll(self.collection, limit=1000, offset=offset, with_payload=False, with_vectors=False)
            existing |= {str(p.id) for p in pts}
            if offset is None:
                break
        wanted = {pid(c.chunk_id): (c, v) for c, v in zip(self.chunks, self.vecs, strict=True)}
        missing = [k for k in wanted if k not in existing]
        if missing:
            self.qdrant.upload_points(self.collection, [
                models.PointStruct(id=k, vector=wanted[k][1].tolist(),
                                   payload={"chunk_id": wanted[k][0].chunk_id, "owner": wanted[k][0].owner, "type": wanted[k][0].type})
                for k in missing], batch_size=256)
        stale = [k for k in existing if k not in wanted]
        if stale:
            self.qdrant.delete(self.collection, points_selector=models.PointIdsList(points=stale))

    # -- writes (ingestion)
    def upsert_docs(self, docs: list[Doc]) -> dict:
        """Incremental re-index: only changed documents are re-chunked and re-embedded."""
        with self.lock:
            by_ev = {}
            for c in self.chunks:
                by_ev.setdefault(c.evidence_id, c.doc_hash)
            changed = [d for d in docs if by_ev.get(d.evidence_id) != d.content_hash]
            ids = {d.evidence_id for d in changed}
            self.chunks = [c for c in self.chunks if c.evidence_id not in ids]
            for d in changed:
                self.chunks.extend(chunk_doc(d, self.scheme))
            if changed:
                self._save_chunks()
                self.reload()
            return {"changed": len(changed), "unchanged": len(docs) - len(changed), "chunks": len(self.chunks)}

    def delete_evidence(self, evidence_id: str, owner: str) -> int:
        with self.lock:
            before = len(self.chunks)
            self.chunks = [c for c in self.chunks if not (c.evidence_id == evidence_id and c.owner == owner)]
            if len(self.chunks) != before:
                self._save_chunks()
                self.reload()
            return before - len(self.chunks)

    # -- reads
    def _allowed(self, c: Chunk, owners, filters) -> bool:
        if c.owner not in owners:
            return False
        for k, v in (filters or {}).items():
            if v is None:
                continue
            val = getattr(c, k, None)
            if isinstance(v, list | tuple | set):
                if k == "skills":
                    if not set(v) & set(val or []):
                        return False
                elif val not in v:
                    return False
            elif val != v:
                return False
        return True

    def dense(self, query: str | np.ndarray, k: int, owners, filters=None) -> list[tuple[Chunk, float]]:
        from qdrant_client import models

        self.maybe_reload()
        if not self.chunks:
            return []
        qv = embed([query], self.model)[0] if isinstance(query, str) else query
        res = self.qdrant.query_points(
            self.collection, query=qv.tolist(), limit=max(k * 4, 50),
            query_filter=models.Filter(must=[models.FieldCondition(key="owner", match=models.MatchAny(any=list(owners)))]),
        ).points
        out = [(self.by_id[p.payload["chunk_id"]], float(p.score)) for p in res if p.payload.get("chunk_id") in self.by_id]
        return [(c, s) for c, s in out if self._allowed(c, owners, filters)][:k]

    def lexical(self, query: str, k: int, owners, filters=None) -> list[tuple[Chunk, float]]:
        self.maybe_reload()
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(-scores)
        out = []
        for i in order:
            if scores[i] <= 0 or len(out) >= k:
                break
            c = self.chunks[i]
            if self._allowed(c, owners, filters):
                out.append((c, float(scores[i])))
        return out

    def full_text(self, evidence_id: str, limit: int = 2000) -> str:
        self.maybe_reload()
        return self.full.get(evidence_id, "")[:limit]

    def docs_for(self, owners) -> list[Chunk]:
        self.maybe_reload()
        return [c for c in self.chunks if c.owner in owners]


_INDEXES: dict[tuple[str, str], PortfolioIndex] = {}


def get_index(scheme: str = "structured", model: str = EMBED_MODEL) -> PortfolioIndex:
    key = (scheme, model)
    if key not in _INDEXES:
        _INDEXES[key] = PortfolioIndex(scheme, model)
    return _INDEXES[key]
