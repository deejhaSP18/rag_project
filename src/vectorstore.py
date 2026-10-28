import chromadb
import ollama

from . import config


def get_collection():
    client = chromadb.PersistentClient(path=str(config.STORAGE_DIR))
    return client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection():
    client = chromadb.PersistentClient(path=str(config.STORAGE_DIR))
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:
        pass


def _embed(texts, prefix):
    return [
        ollama.embeddings(
            model=config.EMBED_MODEL,
            prompt=f"{prefix}: {text}",
            options={"num_ctx": 8192},
        )["embedding"]
        for text in texts
    ]


# nomic-embed-text expects a task prefix: documents and queries are embedded differently.
def embed(texts):
    return _embed(texts, "search_document")


def embed_query(text):
    return _embed([text], "search_query")[0]
