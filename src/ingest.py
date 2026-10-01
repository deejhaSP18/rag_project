from . import config
from .loader import chunk_text, load_documents
from .vectorstore import embed, get_collection


def ingest():
    documents = load_documents(config.DATA_DIR)
    if not documents:
        print(f"No documents found in {config.DATA_DIR}. Add .txt/.md/.pdf files and re-run.")
        return

    collection = get_collection()
    existing_ids = set(collection.get()["ids"])

    ids, texts, metadatas = [], [], []
    for doc in documents:
        chunks = chunk_text(doc["text"], config.CHUNK_SIZE, config.CHUNK_OVERLAP)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc['source']}::{i}"
            if chunk_id in existing_ids:
                continue
            ids.append(chunk_id)
            texts.append(chunk)
            metadatas.append({"source": doc["source"], "chunk_index": i})

    if not ids:
        print("No new chunks to ingest (everything already indexed).")
        return

    print(f"Embedding {len(ids)} new chunks from {len(documents)} document(s)...")
    embeddings = embed(texts)

    collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
    print(f"Ingested {len(ids)} chunks into the vector store at {config.STORAGE_DIR}")


if __name__ == "__main__":
    ingest()
