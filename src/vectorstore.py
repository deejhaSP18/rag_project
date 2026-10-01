import chromadb
import ollama

from . import config


def get_collection():
    client = chromadb.PersistentClient(path=str(config.STORAGE_DIR))
    return client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def embed(texts):
    return [
        ollama.embeddings(
            model=config.EMBED_MODEL,
            prompt=text,
            options={"num_ctx": 8192},
        )["embedding"]
        for text in texts
    ]
