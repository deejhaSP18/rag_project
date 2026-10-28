"""Retrieval: find the passages that answer a question and assemble the context the model reads.

    question -> dense (embedding) candidates + lexical (BM25) candidates over the whole corpus
             -> fused by reciprocal rank -> re-scored by a cross-encoder -> relevance gate
             -> matches, plus the neighbouring passages and passages linked by shared names or
                cross-references ("see section 7.5") -> numbered passages in reading order
"""
import math
from collections import defaultdict

import numpy as np

from . import config, rerank
from .corpus import Corpus
from .vectorstore import embed_query, get_collection

_corpus = None


def invalidate_index():
    """Forget the cached search structures; call after the vector store changes."""
    global _corpus
    _corpus = None


def get_corpus(collection) -> Corpus:
    global _corpus
    if _corpus is None or _corpus.count != collection.count():
        data = collection.get(include=["documents", "metadatas"])
        _corpus = Corpus(data["ids"], data["documents"], data["metadatas"])
    return _corpus


def _hit(corpus: Corpus, i: int, **scores) -> dict:
    meta, text = corpus.metas[i], corpus.texts[i]
    return {
        "id": corpus.ids[i],
        "pos": i,
        "text": text,
        "body": text[meta.get("body_start", 0) :],
        "source": meta["source"],
        "section": meta.get("section", ""),
        "page_start": meta.get("page_start", 0),
        "page_end": meta.get("page_end", 0),
        "chunk_index": meta.get("chunk_index", 0),
        **scores,
    }


def _cosines(collection, corpus: Corpus, positions, query_vec) -> dict:
    """Cosine similarity of the query to stored chunks (for candidates the embedding search did not return)."""
    if not positions:
        return {}
    stored = collection.get(ids=[corpus.ids[i] for i in positions], include=["embeddings"])
    q = np.asarray(query_vec, dtype=float)
    out = {}
    for cid, vec in zip(stored["ids"], stored["embeddings"]):
        v = np.asarray(vec, dtype=float)
        out[corpus.pos[cid]] = float(v @ q / (np.linalg.norm(v) * np.linalg.norm(q) or 1.0))
    return out


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(min(x, 30), -30)))


def _passes(h: dict) -> bool:
    """Clearly relevant to the cross-encoder, or borderline with the embedding agreeing."""
    if h["rerank"] >= config.RERANK_THRESHOLD:
        return True
    if h["rerank"] >= config.RERANK_THRESHOLD - config.RERANK_BORDERLINE and h["cosine"] >= config.RELEVANCE_THRESHOLD:
        return True
    # The question names an identifier this passage contains (ClaimPredictionPipeline / claim_prediction_pipeline.py):
    # a general-purpose cross-encoder under-rates such passages, but the name is strong evidence.
    return h["exact"] and h["rerank"] >= config.RERANK_THRESHOLD - 2 * config.RERANK_BORDERLINE


def search(question: str, top_k: int | None = None, sources: list[str] | None = None) -> list[dict]:
    """Best matching passages for one question, most relevant first; empty when nothing is relevant."""
    top_k = top_k or config.TOP_K
    collection = get_collection()
    total = collection.count()
    if total == 0:
        return []
    corpus = get_corpus(collection)

    allowed = None
    where = {}
    if sources:
        allowed = {i for s in sources for i in corpus.by_source.get(s, [])}
        if not allowed:
            return []
        where = {"where": {"source": sources[0]} if len(sources) == 1 else {"source": {"$in": list(sources)}}}

    query_vec = embed_query(question)
    found = collection.query(
        query_embeddings=[query_vec],
        n_results=min(config.DENSE_CANDIDATES, len(allowed) if allowed else total),
        **where,
    )
    dense = [(corpus.pos[cid], 1 - dist) for cid, dist in zip(found["ids"][0], found["distances"][0]) if cid in corpus.pos]
    lexical = corpus.bm25(question, allowed, config.LEXICAL_CANDIDATES)

    fused = defaultdict(float)
    for rank, (i, _) in enumerate(dense):
        fused[i] += 1 / (60 + rank)
    for rank, (i, _) in enumerate(lexical):
        fused[i] += config.KEYWORD_WEIGHT / (60 + rank)
    ranked = sorted(fused, key=fused.get, reverse=True)[: config.RERANK_CANDIDATES]

    cosine = dict(dense)
    cosine.update(_cosines(collection, corpus, [i for i in ranked if i not in cosine], query_vec))
    reranked = rerank.score(question, [corpus.texts[i] for i in ranked])

    hits = []
    for n, i in enumerate(ranked):
        r = reranked[n] if reranked is not None else None
        hits.append(_hit(
            corpus, i, cosine=cosine.get(i, 0.0), fused=fused[i], rerank=r,
            score=_sigmoid(r) if r is not None else cosine.get(i, 0.0),
            distance=1 - cosine.get(i, 0.0), exact=corpus.names_in(i, question),
        ))

    if reranked is not None:
        hits.sort(key=lambda h: h["rerank"], reverse=True)
        best = hits[0]["rerank"]
        hits = [h for h in hits if _passes(h) and h["rerank"] >= best - config.RERANK_MARGIN]
    else:  # no reranker: the embedding similarity decides, as it did before
        hits.sort(key=lambda h: h["fused"], reverse=True)
        best = max((h["cosine"] for h in hits), default=0)
        hits = [h for h in hits if h["cosine"] >= config.RELEVANCE_THRESHOLD and h["cosine"] >= best - config.RELATIVE_SCORE_MARGIN]
    return hits[:top_k]


def gather_context(queries, top_k: int | None = None, sources: list[str] | None = None) -> list[dict]:
    """Matches for every sub-question, deduplicated, best first within each question."""
    top_k = top_k or config.TOP_K
    per_query = top_k if len(queries) == 1 else config.TOP_K_PER_SUBQUESTION
    hits, seen = [], set()
    for query in queries:
        for h in search(query, per_query, sources):
            if h["id"] not in seen:
                seen.add(h["id"])
                hits.append(h)
    return hits[: config.MAX_CONTEXT_CHUNKS]


def build_passages(hits: list[dict], queries: list[str]) -> list[dict]:
    """Numbered passages in reading order: the matches, their neighbours and linked passages.

    Neighbours keep a match from being cut off mid-thought; linked passages (same rare name, or an
    explicit "see section X") bring in the other end of a relationship. Both only fill what is left
    of the character budget, and linked passages must also look relevant to the question.
    """
    if not hits:
        return []
    corpus = get_corpus(get_collection())
    role = {h["pos"]: "match" for h in hits}
    budget = config.MAX_CONTEXT_CHARS - sum(len(h["body"]) for h in hits)
    scores = {h["pos"]: h["score"] for h in hits}

    def add(i: int, kind: str, score=None) -> None:
        nonlocal budget
        size = len(corpus.texts[i]) - corpus.metas[i].get("body_start", 0)
        if i in role or size > budget:
            return
        role[i], budget = kind, budget - size
        scores[i] = score

    for h in hits:
        for j in corpus.neighbours(h["pos"], config.NEIGHBOR_CHUNKS):
            add(j, "context")

    if config.RELATED_CHUNKS > 0:
        linked = corpus.related([h["pos"] for h in hits], set().union(*(corpus.query_entities(q) for q in queries)))
        linked = [(j, s) for j, s in linked if j not in role]
        if linked:
            texts = [corpus.texts[j] for j, _ in linked]
            per_query = [rerank.score(q, texts) for q in queries]
            if per_query[0] is None:  # without the cross-encoder only explicit cross-references are trusted
                best = [(j, None) for j, s in linked if s >= 8.0]
            else:
                relevance = [max(col) for col in zip(*per_query)]
                best = sorted(
                    ((j, _sigmoid(r)) for (j, _), r in zip(linked, relevance) if r >= config.RERANK_THRESHOLD),
                    key=lambda kv: kv[1], reverse=True,
                )
            for j, score in best[: config.RELATED_CHUNKS]:
                add(j, "related", score)

    # Reading order: documents by their best match, passages by position in the document.
    first_match = {}
    for rank, h in enumerate(hits):
        first_match.setdefault(h["source"], rank)
    ordered = sorted(role, key=lambda i: (first_match.get(corpus.metas[i]["source"], len(hits)), corpus.metas[i]["source"], corpus.order[i]))
    return [
        {**_hit(corpus, i), "n": n, "role": role[i], "score": scores.get(i)}
        for n, i in enumerate(ordered, start=1)
    ]
