"""Second-stage relevance scoring with a small local cross-encoder.

Embeddings and BM25 score a passage and a question separately, so they are good at finding
candidates but weak at judging them. A cross-encoder reads question and passage together and says
how well the passage answers it. It runs on the CPU, offline, after a one-time model download into
storage/models. If it is disabled or cannot load, retrieval falls back to the embedding score.
"""
import logging
import threading

from . import config

log = logging.getLogger("rag.rerank")

_model = None
_failed = False
_lock = threading.Lock()


def _load():
    global _model, _failed
    with _lock:
        if _model is None and not _failed:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                _model = TextCrossEncoder(config.RERANK_MODEL, cache_dir=str(config.MODEL_CACHE_DIR))
            except Exception as exc:
                _failed = True
                log.warning("Reranker unavailable (%s); using embedding scores only.", exc)
    return _model


def warm_up() -> None:
    """Load the model now (call from a background thread at startup) so the first question is not slow."""
    if config.RERANK_ENABLED:
        _load()


def available() -> bool:
    return bool(config.RERANK_ENABLED and _load())


def score(query: str, texts: list[str]) -> list[float] | None:
    """Relevance of each text to the query (higher is better; roughly >0 means relevant), or None if unavailable."""
    if not texts or not config.RERANK_ENABLED:
        return None
    model = _load()
    if model is None:
        return None
    with _lock:
        return [float(s) for s in model.rerank(query, [t[:2000] for t in texts])]
