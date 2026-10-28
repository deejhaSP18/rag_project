import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STORAGE_DIR = ROOT_DIR / "storage"

# The environment variables let a container pick models without editing this file; the admin
# panel can still switch the chat model live.
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.environ.get("RAG_LLM_MODEL", "phi4-mini:latest")
# Where the re-ranker model is cached (a container image bakes it in so first start needs no download).
MODEL_CACHE_DIR = Path(os.environ.get("RAG_MODEL_CACHE", STORAGE_DIR / "models"))

COLLECTION_NAME = "documents"

# In words. Chunks follow markdown section boundaries, so many are shorter than this.
CHUNK_SIZE = 250
CHUNK_OVERLAP = 40

# Chunks for a single question; with several sub-questions each gets TOP_K_PER_SUBQUESTION.
TOP_K = 6
TOP_K_PER_SUBQUESTION = 4
MAX_CONTEXT_CHUNKS = 10
MAX_SUBQUESTIONS = 4

# Context window for the chat model (prompt + answer must fit) and answer cap.
LLM_NUM_CTX = 8192
LLM_MAX_ANSWER_TOKENS = 1024
# Low temperature keeps answers close to the retrieved text instead of improvising.
LLM_TEMPERATURE = 0.2

# Minimum cosine similarity (0-1) for a chunk to count as relevant when the re-ranker is off,
# and the embedding agreement a borderline re-ranker score needs (see RERANK_BORDERLINE).
# If no chunk qualifies the question is treated as unrelated to the documents.
RELEVANCE_THRESHOLD = 0.58

# Drop chunks scoring more than this below the best match for the same question.
RELATIVE_SCORE_MARGIN = 0.06

# Earlier question/answer pairs used to resolve follow-ups like "can you name them?".
CHAT_HISTORY_TURNS = 3

# Hybrid search: the nearest chunks by embedding and the best BM25 keyword matches over the
# whole corpus are fused (reciprocal rank fusion), so exact names and codes are found even when
# the embedding misses them.
DENSE_CANDIDATES = 40
LEXICAL_CANDIDATES = 40
# Exact-word matches count this many times as much as embedding similarity when fusing ranks.
KEYWORD_WEIGHT = 1.0

# Re-scoring of the best fused candidates with a local cross-encoder (see src/rerank.py).
RERANK_ENABLED = True
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RERANK_CANDIDATES = 20
# Cross-encoder scores are not 0-1: below 0 means "does not answer the question". A passage
# needs at least this score, and must be within RERANK_MARGIN of the best one for the question.
RERANK_THRESHOLD = 0.0
# Technical text and tables score low with a general-purpose cross-encoder. A score within this
# distance below the threshold still counts if the embedding similarity also reaches RELEVANCE_THRESHOLD.
RERANK_BORDERLINE = 3.0
RERANK_MARGIN = 6.0

# Context for the model: each match also brings the passages right before/after it, and passages
# linked to the matches by a shared name or "see section 7.5" cross-references.
NEIGHBOR_CHUNKS = 1
RELATED_CHUNKS = 2
# Total passage text sent to the model, in characters (about 4 per token).
MAX_CONTEXT_CHARS = 16000
