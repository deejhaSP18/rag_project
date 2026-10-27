import hashlib
import re
from pathlib import Path

from . import config
from .loader import EmptyDocument, chunk_text, load_document, load_documents
from .vectorstore import embed, get_collection, reset_collection

BATCH = 8  # chunks embedded per progress step
MIN_CHUNK_WORDS = 3  # a heading with nothing under it is not a passage


def _title_of(source: str) -> str:
    return re.sub(r"[_\s]+", " ", Path(source).stem).strip()


def _chunks_of(doc):
    """(id, text, metadata) rows for one document.

    Metadata carries what retrieval and the source viewer need: where the passage sits (section, page
    range, position in the document) and which file version it came from. Chunks come out in reading
    order, so `chunk_index` +/- 1 is the neighbouring passage. Page 0 means the format has no pages.
    """
    chunks = chunk_text(doc["text"], config.CHUNK_SIZE, config.CHUNK_OVERLAP, _title_of(doc["source"]))
    rows, seen = [], set()
    for chunk in chunks:
        if len(chunk.body.split()) < MIN_CHUNK_WORDS and len(chunks) > 1:
            continue
        digest = hashlib.sha1(" ".join(chunk.body.lower().split()).encode()).hexdigest()
        if digest in seen:  # a repeated block inside one document (boilerplate) adds nothing
            continue
        seen.add(digest)
        index = len(rows)
        rows.append((
            f"{doc['source']}::{index}",
            chunk.text,
            {
                "source": doc["source"],
                "chunk_index": index,
                "section": chunk.section,
                "page_start": chunk.page_start or 0,
                "page_end": chunk.page_end or 0,
                "body_start": len(chunk.text) - len(chunk.body),
                "chunk_hash": digest,
                "file_hash": doc["hash"],
            },
        ))
    return rows


def _add_chunks(collection, rows, on_progress=None):
    """Embed and store (id, text, metadata) rows in small batches, reporting progress."""
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        ids, texts, metadatas = zip(*batch)
        collection.add(ids=list(ids), documents=list(texts), metadatas=list(metadatas), embeddings=embed(texts))
        if on_progress:
            on_progress(min(start + BATCH, len(rows)), len(rows))
    return len(rows)


def index_source(source: str, on_progress=None) -> int:
    """(Re)index one file from data/: drop its old chunks, then embed the current text. Returns chunk count.

    Raises EmptyDocument if the file has no readable text; its old chunks are removed first so the
    index never keeps serving a version of the file that no longer exists.
    """
    collection = get_collection()
    try:
        doc = load_document(config.DATA_DIR / source, config.DATA_DIR)
    except EmptyDocument:
        collection.delete(where={"source": source})
        raise
    collection.delete(where={"source": source})
    if doc is None:
        return 0
    return _add_chunks(collection, _chunks_of(doc), on_progress)


def remove_source(source: str) -> None:
    get_collection().delete(where={"source": source})


def ingest(on_progress=None):
    """Rebuild the whole index from data/ (also used by the CLI)."""
    documents = load_documents(config.DATA_DIR)
    if not documents:
        print(f"No documents found in {config.DATA_DIR}. Add .txt/.md/.pdf files and re-run.")
        return 0

    # Rebuild from scratch so chunks from an older chunking scheme never linger.
    reset_collection()
    rows = [row for doc in documents for row in _chunks_of(doc)]
    print(f"Embedding {len(rows)} chunks from {len(documents)} document(s)...")
    count = _add_chunks(get_collection(), rows, on_progress)
    print(f"Ingested {count} chunks into the vector store at {config.STORAGE_DIR}")
    return count


if __name__ == "__main__":
    ingest()
