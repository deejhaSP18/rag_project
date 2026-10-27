"""Background indexing ("training") jobs and the document store behind the admin panel.

One worker thread runs jobs in order, so several uploads queue up instead of fighting over
Ollama and the vector store. Job state lives in memory; the vector store is the source of truth.
"""
import hashlib
import logging
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import config, rag
from .ingest import index_source, ingest, remove_source
from .loader import SUPPORTED_EXTENSIONS, file_hash
from .vectorstore import get_collection

log = logging.getLogger("rag.training")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexer")
_jobs: deque = deque(maxlen=30)
_lock = threading.Lock()


class DocumentError(ValueError):
    """A request the admin can fix (bad name, unsupported type, file too large)."""


class DuplicateDocument(DocumentError):
    """The same content is already stored under another name."""

    def __init__(self, existing: str):
        super().__init__(f"This file is identical to '{existing}', which is already in the library.")
        self.existing = existing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name or name.startswith("."):
        raise DocumentError("Invalid file name.")
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DocumentError(f"Unsupported file type. Use: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    return name


def _path(name: str) -> Path:
    path = (config.DATA_DIR / name).resolve()
    if path.parent != config.DATA_DIR.resolve():
        raise DocumentError("Invalid file name.")
    return path


_hashes: dict = {}  # path -> ((mtime_ns, size), sha256), so listing documents does not re-read every file


def _hash_of(path: Path) -> str:
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _hashes.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    digest = file_hash(path)
    _hashes[path] = (stamp, digest)
    return digest


def list_documents() -> list[dict]:
    config.DATA_DIR.mkdir(exist_ok=True)
    chunks: dict[str, int] = {}
    indexed_hash: dict[str, str] = {}
    pages: dict[str, int] = {}
    for meta in get_collection().get(include=["metadatas"])["metadatas"]:
        source = meta["source"]
        chunks[source] = chunks.get(source, 0) + 1
        if meta.get("file_hash"):
            indexed_hash[source] = meta["file_hash"]
        pages[source] = max(pages.get(source, 0), meta.get("page_end", 0))
    pending = {j["target"] for j in _jobs if j["state"] in ("queued", "running")}
    docs = []
    for p in sorted(config.DATA_DIR.iterdir()):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        n = chunks.get(p.name, 0)
        if p.name in pending:
            status = "indexing"
        elif not n:
            status = "not indexed"
        elif p.name in indexed_hash and indexed_hash[p.name] != _hash_of(p):
            status = "outdated"  # the file changed after it was indexed
        else:
            status = "indexed"
        stat = p.stat()
        docs.append({
            "name": p.name, "size": stat.st_size, "chunks": n, "pages": pages.get(p.name, 0), "status": status,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
    return docs


def save_upload(filename: str, data: bytes) -> dict:
    """Store an uploaded file. Returns {"name", "status"}: "new", "replaced" or "unchanged".

    The same bytes under the same name are not written again, and the same bytes under a different
    name are refused: indexed twice, every passage would be found twice and crowd out other answers.
    """
    name = safe_name(filename)
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    config.DATA_DIR.mkdir(exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    for other in sorted(config.DATA_DIR.iterdir()):
        if other.is_file() and other.name != name and other.suffix.lower() in SUPPORTED_EXTENSIONS:
            if other.stat().st_size == len(data) and _hash_of(other) == digest:
                raise DuplicateDocument(other.name)
    path = _path(name)
    existed = path.is_file()
    if existed and path.stat().st_size == len(data) and _hash_of(path) == digest:
        return {"name": name, "status": "unchanged"}
    path.write_bytes(data)
    return {"name": name, "status": "replaced" if existed else "new"}


def is_indexed(name: str) -> bool:
    """True when the stored file is already indexed and no job for it is waiting."""
    pending = any(j["target"] == name and j["state"] in ("queued", "running") for j in _jobs)
    return not pending and any(d["name"] == name and d["status"] == "indexed" for d in list_documents())


def delete_document(filename: str) -> bool:
    name = safe_name(filename)
    path = _path(name)
    existed = path.is_file()
    with _lock:  # not while the indexer is writing chunks
        path.unlink(missing_ok=True)
        remove_source(name)
        rag.invalidate_index()
    return existed


def _submit(kind: str, target: str, work) -> dict:
    job = {
        "id": uuid.uuid4().hex[:10], "kind": kind, "target": target, "state": "queued",
        "message": "Waiting for the indexer", "done": 0, "total": 0, "created_at": _now(),
    }
    _jobs.appendleft(job)

    def run():
        job.update(state="running", message="Reading and splitting the document" if kind == "index" else "Rebuilding the index")

        def progress(done, total):
            job.update(done=done, total=total, message=f"Embedding chunks {done}/{total}")

        try:
            with _lock:
                count = work(progress)
                rag.invalidate_index()
            job.update(state="done", message=f"Indexed {count} chunks", finished_at=_now())
        except Exception as exc:
            log.exception("indexing failed: %s", target)
            job.update(state="error", message=f"Failed: {exc}", finished_at=_now())

    _pool.submit(run)
    return job


def train_document(name: str) -> dict:
    return _submit("index", name, lambda progress: index_source(name, progress))


def train_all() -> dict:
    return _submit("reindex", "all documents", lambda progress: ingest(progress))


def recent_jobs() -> list[dict]:
    return list(_jobs)
