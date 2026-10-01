from pathlib import Path

from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def load_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def load_documents(data_dir: Path):
    documents = []
    for path in sorted(data_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            text = load_file(path)
            if text.strip():
                documents.append({"source": str(path.relative_to(data_dir)), "text": text})
    return documents


MAX_WORD_LEN = 200
MAX_CHUNK_CHARS = 3000


def _split_long_words(words):
    normalized = []
    for word in words:
        if len(word) > MAX_WORD_LEN:
            normalized.extend(word[i : i + MAX_WORD_LEN] for i in range(0, len(word), MAX_WORD_LEN))
        else:
            normalized.append(word)
    return normalized


def chunk_text(text: str, chunk_size: int, overlap: int):
    words = _split_long_words(text.split())
    if not words:
        return []

    chunks = []
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(words), step):
        chunk_words = words[start : start + chunk_size]
        if not chunk_words:
            break
        chunk = " ".join(chunk_words)
        # Hard safety cap: even if word count is small, dense scripts (e.g. CJK)
        # can pack far more tokens per character than English.
        chunks.extend(chunk[i : i + MAX_CHUNK_CHARS] for i in range(0, len(chunk), MAX_CHUNK_CHARS))
        if start + chunk_size >= len(words):
            break
    return chunks
