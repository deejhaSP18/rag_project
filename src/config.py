from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STORAGE_DIR = ROOT_DIR / "storage"

EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "gemma3:4b"

COLLECTION_NAME = "documents"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

TOP_K = 4

# Minimum cosine similarity (0-1) a retrieved chunk needs to count as "relevant".
# Below this, the question is treated as unrelated to the indexed documents
# (e.g. greetings/small talk) instead of forcing an answer from unrelated context.
RELEVANCE_THRESHOLD = 0.46

# Minimum cosine similarity for a chunk to be used; if none qualify, the LLM is not called.
RELEVANCE_THRESHOLD = 0.55
