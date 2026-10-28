import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .pdfparse import PAGE_RE, PdfError, pdf_to_markdown

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


class EmptyDocument(ValueError):
    """The file has no readable text."""


def file_hash(path: Path) -> str:
    """SHA-256 of the file's bytes: the same content has the same hash whatever it is named."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            return pdf_to_markdown(path)
        except PdfError:
            raise
        except Exception:  # an odd PDF the structured parser cannot handle: plain text still beats nothing
            reader = PdfReader(str(path))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def load_document(path: Path, data_dir: Path):
    """One file as {"source", "text", "hash"}, or None if it is unsupported. Raises EmptyDocument if unreadable."""
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None
    try:
        text = load_file(path)
    except PdfError as exc:
        raise EmptyDocument(str(exc)) from exc
    if path.suffix.lower() == ".md":
        text = clean_markdown(text)
    if not text.strip():
        raise EmptyDocument("The file has no readable text.")
    return {"source": str(path.relative_to(data_dir)), "text": text, "hash": file_hash(path)}


def load_documents(data_dir: Path):
    documents = []
    for path in sorted(data_dir.rglob("*")):
        try:
            doc = load_document(path, data_dir)
        except EmptyDocument as exc:
            print(f"Skipping {path.name}: {exc}")
            continue
        if doc:
            documents.append(doc)
    return documents


_META_LINE_RE = re.compile(r"^\*{0,2}(Source|Retrieved|License):.*$\n?", re.MULTILINE)


_MERMAID_RE = re.compile(r"```mermaid\b.*?```", re.DOTALL)
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _clean_table_row(line: str) -> str:
    """'| `EDI_DB_2` | ULF  | **Deprecated** |' -> '| EDI_DB_2 | ULF | Deprecated |' (compact, one row per line)."""
    cells = [re.sub(r"[`*]", "", c).strip() for c in line.strip().strip("|").split("|")]
    return "| " + " | ".join(cells) + " |"


def clean_markdown(text: str) -> str:
    """Prepare markdown for chunking: drop fetch metadata, diagrams and rules; tidy tables."""
    text = _META_LINE_RE.sub("", text)
    text = _MERMAID_RE.sub("", text)  # diagram syntax is noise for retrieval
    lines = []
    for line in text.split("\n"):
        if re.fullmatch(r"\s*[-*_]{3,}\s*", line) or _TABLE_SEPARATOR_RE.match(line) and "-" in line:
            continue
        lines.append(_clean_table_row(line) if line.lstrip().startswith("|") else line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


MAX_WORD_LEN = 200
MAX_CHUNK_CHARS = 3000

_SENTENCE_END_RE = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’)]))\s+(?=[A-Z0-9“\"‘(\[])")


@dataclass
class Chunk:
    text: str  # what gets embedded: "Document — Section" line, then the body
    body: str  # the passage itself, without the heading line
    section: str  # "7. EMPLOYEE LEAVE POLICY > 7.5. Sick / Casual Leave"; empty at the top level
    page_start: int | None = None
    page_end: int | None = None


def _split_sections(text: str):
    """Split on markdown headings, returning (heading path, body) pairs."""
    sections, path, body = [], [], []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if any(b.strip() for b in body):
                sections.append((list(path), "\n".join(body).strip()))
            level = len(m.group(1))
            path = path[: level - 1] + [m.group(2).strip()]
            body = []
        else:
            body.append(line)
    if any(b.strip() for b in body):
        sections.append((list(path), "\n".join(body).strip()))
    return sections


def _split_long_words(words):
    normalized = []
    for word in words:
        if len(word) > MAX_WORD_LEN:
            normalized.extend(word[i : i + MAX_WORD_LEN] for i in range(0, len(word), MAX_WORD_LEN))
        else:
            normalized.append(word)
    return normalized


_NOT_A_SENTENCE_END_RE = re.compile(r"(?:^|\s)(?:\d+(?:\.\d+)*\.|[A-Z][a-z]?\.|Mr\.|Mrs\.|Ms\.|Dr\.|St\.|vs\.|etc\.|e\.g\.|i\.e\.)$")


def _sentences(text: str):
    """Split at sentence ends, but not after list numbering ("17.1.") or abbreviations ("Dr.")."""
    out = []
    for part in _SENTENCE_END_RE.split(text):
        if not part.strip():
            continue
        if out and _NOT_A_SENTENCE_END_RE.search(out[-1]):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _window(words, chunk_size: int, overlap: int):
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(words), step):
        yield " ".join(words[start : start + chunk_size])
        if start + chunk_size >= len(words):
            break


def _split_oversized(para: str, chunk_size: int, overlap: int):
    """Cut one long paragraph into pieces at sentence boundaries (words only as a last resort)."""
    pieces, current, count = [], [], 0
    for sentence in _sentences(para):
        words = _split_long_words(sentence.split())
        if len(words) > chunk_size:  # a single run-on sentence
            if current:
                pieces.append(" ".join(current))
                current, count = [], 0
            pieces.extend(_window(words, chunk_size, overlap))
            continue
        if current and count + len(words) > chunk_size:
            pieces.append(" ".join(current))
            tail = _tail(" ".join(current), overlap)
            current, count = ([tail], len(tail.split())) if tail else ([], 0)
        current.append(" ".join(words))
        count += len(words)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _tail(text: str, overlap: int) -> str:
    """The last whole sentence(s) of text that fit in `overlap` words, so overlap never starts mid-sentence."""
    if not overlap:
        return ""
    tail, count = [], 0
    for sentence in reversed(_sentences(text)):
        n = len(sentence.split())
        if count + n > overlap:
            break
        tail.insert(0, sentence)
        count += n
    return " ".join(tail)


def _tail_units(texts, overlap: int) -> str:
    """Overlap for the next chunk: whole trailing paragraphs/rows that fit, else the last sentence(s)."""
    kept, count = [], 0
    for text in reversed(texts):
        n = len(text.split())
        if count + n > overlap:
            if not kept:
                return _tail(text, overlap)
            break
        kept.insert(0, text)
        count += n
    return "\n".join(kept)


def _pack_paragraphs(units, chunk_size: int, overlap: int):
    """Group whole paragraphs, given as (text, page), into chunks of about chunk_size words.

    Paragraphs are only split when a single one is longer than chunk_size. The last sentence(s)
    of each chunk (up to `overlap` words) are repeated at the start of the next. Yields
    (body, first page, last page).
    """
    pieces = []
    for para, page in units:
        if len(_split_long_words(para.split())) <= chunk_size:
            pieces.append((para, page))
        else:
            pieces.extend((piece, page) for piece in _split_oversized(para, chunk_size, overlap))

    current, count = [], 0  # current holds (text, page); page is None for carried-over overlap
    for piece, page in pieces:
        n = len(piece.split())
        if current and count + n > chunk_size:
            yield _emit(current)
            tail = _tail_units([t for t, _ in current], overlap)
            current, count = ([(tail, None)], len(tail.split())) if tail else ([], 0)
        current.append((piece, page))
        count += n
    if current:
        yield _emit(current)


def _emit(current):
    pages = [p for _, p in current if p is not None]
    return "\n".join(t for t, _ in current), (min(pages) if pages else None), (max(pages) if pages else None)


def _units(body: str, page):
    """Paragraph units (text, page) of a section body, plus the page reached at its end."""
    units = []
    # Lists and table rows are one item per line; prose paragraphs are separated by blank lines.
    for para in re.split(r"\n\s*\n|\n(?=\s*(?:- |\d+\. |\|))", body):
        para = para.strip()
        if not para:
            continue
        marker = PAGE_RE.match(para)
        if marker:
            page = int(marker.group(1))
            continue
        units.append((re.sub(r"\s*\n\s*", " ", para), page))  # undo hard line-wrapping
    return units, page


def _clean_path(path, doc_title):
    return [h for h in path if h != doc_title]


def _group_sections(prepared, doc_title: str, chunk_size: int):
    """Merge small neighbouring subsections of one parent into a single group.

    "7.8.1 Statutory", "7.8.2 Extension" and "7.8.3 Condition" are three short paragraphs about one
    thing. Kept apart, each loses the context of its siblings; together they stay one passage whose
    sub-headings are written inline. Top-level sections are never merged with each other.
    Returns (heading path, units) pairs.
    """
    groups = []  # each: {"parent": [...], "words": n, "members": [(path, units)]}
    for path, units in prepared:
        clean = _clean_path(path, doc_title)
        parent, words = clean[:-1], sum(len(t.split()) for t, _ in units)
        last = groups[-1] if groups else None
        if last and parent and last["parent"] == parent and last["words"] + words <= chunk_size:
            last["members"].append((clean, units))
            last["words"] += words
        else:
            groups.append({"parent": parent, "words": words, "members": [(clean, units)]})

    merged = []
    for g in groups:
        if len(g["members"]) == 1:
            clean, units = g["members"][0]
            merged.append((clean, units))
            continue
        units = []
        for clean, member_units in g["members"]:
            first_page = member_units[0][1] if member_units else None
            units.append((clean[-1], first_page))  # the sub-heading, inline
            units.extend(member_units)
        merged.append((g["parent"], units))
    return merged


def chunk_text(text: str, chunk_size: int, overlap: int, title: str = ""):
    """Split cleaned text into section-aware Chunks.

    Each chunk starts with its document title and section heading so it still makes sense when
    retrieved on its own, and remembers its section and the pages it spans. Small sibling
    subsections are kept together so related paragraphs are not cut apart.
    """
    sections = _split_sections(text)
    doc_title = title
    if sections and sections[0][0]:
        doc_title = sections[0][0][0]

    prepared, page = [], None
    for path, body in sections:
        units, page = _units(body, page)
        if units:
            prepared.append((path, units))

    chunks = []
    for path, units in _group_sections(prepared, doc_title, chunk_size):
        heading = " > ".join(path)
        prefix = doc_title + (f" — {heading}" if heading else "")
        for chunk_body, first, last in _pack_paragraphs(units, chunk_size, overlap):
            full = f"{prefix}\n{chunk_body}" if prefix else chunk_body
            offset = len(full) - len(chunk_body)
            for i in range(0, len(full), MAX_CHUNK_CHARS):
                piece = full[i : i + MAX_CHUNK_CHARS]
                chunks.append(Chunk(piece, piece[max(offset - i, 0) :], heading, first, last))
    return chunks
