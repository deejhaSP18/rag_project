"""Turn a PDF into markdown that keeps its structure, so the chunker can use it.

Plain text extraction throws away what makes a document understandable: headings, paragraph
breaks, page numbers. Here headings are recovered from font size and section numbering
("7.5. Sick Leave"), running headers/footers and table-of-contents pages are dropped, wrapped
lines are rebuilt into paragraphs, and a `<<PAGE:n>>` marker line precedes the first block of
each page so every chunk can say which page it came from.
"""
import re
import statistics
from collections import Counter
from pathlib import Path

import pdfplumber

PAGE_MARK = "<<PAGE:{}>>"
PAGE_RE = re.compile(r"^<<PAGE:(\d+)>>$")

HEADING_SIZE_RATIO = 1.15  # a line this much bigger than body text is a heading
MAX_HEADING_CHARS = 120
EDGE_BAND = 0.10  # top/bottom share of the page where running headers and footers live

_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_LONE_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*\.?$")
_DEEP_NUMBERED_RE = re.compile(r"^\d+(?:\.\d+){2,}\.?\s+[A-Z]")
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s+)?(?:\d{1,4}|[ivxlc]{1,7})(?:\s*(?:/|of)\s*\d{1,4})?$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[•▪●○◦➢►✓✔·]\s*")
_ITEM_START_RE = re.compile(r"^(?:[-–*]\s|\(?\d{1,3}(?:\.\d+)*[.)]\s|\(?[a-z][.)]\s)")
_TERMINAL_RE = re.compile(r"[.!?:;\"”’)\]]$")
_LIST_NUMBER_CELL_RE = re.compile(r"^\(?\d+(?:\.\d+)*[.)]?$|^[a-z][.)]$|^[•▪●○◦➢►·\-–]$")


class PdfError(ValueError):
    """The PDF cannot be read as text (encrypted, corrupt, or scanned images only)."""


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _clean_table(raw):
    """Cell grid of a real data table, or None. Word exports draw numbered clauses and contents pages
    as "tables" too; those have one real column, mostly empty cells, or a list-number first column."""
    rows = [["" if c is None else " ".join(str(c).split()) for c in r] for r in raw]
    width = max((len(r) for r in rows), default=0)
    cols = [j for j in range(width) if any(j < len(r) and r[j] for r in rows)]
    if len(cols) < 2 or len(rows) < 2:
        return None
    rows = [[r[j] if j < len(r) else "" for j in cols] for r in rows]
    cells = [c for r in rows for c in r]
    if sum(1 for c in cells if c) / len(cells) < 0.6:
        return None
    first = [r[0] for r in rows if r[0]]
    if first and sum(1 for c in first if _LIST_NUMBER_CELL_RE.match(c)) / len(first) > 0.5:
        return None
    return rows


def _looks_like_header(row) -> bool:
    return all(c and re.search(r"[A-Za-z]", c) and not re.match(r"\d", c) and not re.search(r"\d{3,}", c) for c in row)


def _render_table(rows, header):
    """One bullet per row, "Column: value; Column: value", so each row still says what its numbers mean."""
    out = []
    for row in rows:
        if header and len(header) == len(row):
            out.append("- " + "; ".join(f"{h}: {c}" for h, c in zip(header, row) if c))
        else:
            out.append("- " + " | ".join(c for c in row if c))
    return "\n".join(out)


def _read_lines(pdf):
    """Per page: lightweight line records (text, position, median font size) and rendered tables."""
    pages, carried = [], None
    for number, page in enumerate(pdf.pages, start=1):
        tables = []
        try:
            for table in page.find_tables():
                rows = _clean_table(table.extract())
                if rows:
                    tables.append((table.bbox, rows))
        except Exception:  # table detection is a bonus; never lose the page's text over it
            tables = []

        def in_table(ln):
            mid = (ln["top"] + ln["bottom"]) / 2
            return any(b[0] - 2 <= ln["x0"] <= b[2] and b[1] - 2 <= mid <= b[3] + 2 for b, _ in tables)

        lines, rendered = [], []
        for ln in page.extract_text_lines(return_chars=True, x_tolerance_ratio=0.15):
            text = " ".join(ln["text"].split())
            if not text or in_table(ln):
                continue
            size = statistics.median(c["size"] for c in ln["chars"])
            lines.append({"text": text, "x0": ln["x0"], "x1": ln["x1"], "top": ln["top"], "bottom": ln["bottom"],
                          "size": round(size * 2) / 2})
        for k, (bbox, rows) in enumerate(sorted(tables, key=lambda t: t[0][1])):
            header = None
            if _looks_like_header(rows[0]):
                header, rows = rows[0], rows[1:]
            elif carried and len(carried) == len(rows[0]) and k == 0 and bbox[1] < page.height * 0.2:
                header = carried  # the table continues from the previous page, which had the header
            if header:
                carried = header
            if rows:
                rendered.append((bbox[1], _render_table(rows, header)))
        pages.append({"number": number, "height": float(page.height), "lines": lines, "tables": rendered})
    return pages


def _body_size(pages) -> float:
    sizes = Counter()
    for page in pages:
        for ln in page["lines"]:
            sizes[ln["size"]] += len(ln["text"])
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _strip_running_text(pages, body: float) -> None:
    """Drop page numbers and headers/footers that repeat across pages (they pollute every chunk)."""
    in_band, anywhere = Counter(), Counter()
    for page in pages:
        in_band.update({_norm(ln["text"]) for ln in page["lines"] if _in_band(ln, page["height"])})
        anywhere.update({_norm(ln["text"]) for ln in page["lines"]})
    repeated_in_band = {t for t, n in in_band.items() if n >= 3}
    # A footer can sit a little above the page edge; a line on nearly every page is furniture wherever it is.
    frequent = {t for t, n in anywhere.items() if len(t) >= 4 and n >= max(5, 0.4 * len(pages))}
    for page in pages:
        keep = []
        for ln in page["lines"]:
            if ln["size"] < body * HEADING_SIZE_RATIO:
                norm = _norm(ln["text"])
                if norm in frequent:
                    continue
                if _in_band(ln, page["height"]) and (_PAGE_NUMBER_RE.match(ln["text"]) or norm in repeated_in_band):
                    continue
            keep.append(ln)
        page["lines"] = keep


def _in_band(ln, height: float) -> bool:
    return ln["top"] < height * EDGE_BAND or ln["bottom"] > height * (1 - EDGE_BAND)


def _is_toc_page(lines) -> bool:
    """A contents page: many short lines that are numbered sections or end in a page number."""
    if len(lines) < 6:
        return False
    short = [ln["text"] for ln in lines if len(ln["text"]) < 90]
    numbered = sum(1 for t in short if _NUMBERED_RE.match(t) and not t.endswith((".", ",")))
    paged = sum(1 for t in short if re.search(r"\s(?:\d{1,4}|[ivxlc]{1,6})$", t))
    avg_words = sum(len(ln["text"].split()) for ln in lines) / len(lines)
    return max(numbered, paged) / len(lines) >= 0.7 and avg_words < 9


def _heading_levels(pages, body: float) -> dict:
    """Map each heading font size to a level (1 = biggest). Sizes seen on fewer than 3 lines are decoration."""
    counts = Counter(
        ln["size"]
        for page in pages
        for ln in page["lines"]
        if ln["size"] >= body * HEADING_SIZE_RATIO and 3 <= len(ln["text"]) <= MAX_HEADING_CHARS
    )
    sizes = sorted((s for s, n in counts.items() if n >= 3), reverse=True)
    return {size: min(rank + 1, 3) for rank, size in enumerate(sizes)}


def _classify(ln, body: float, levels: dict, following=None, right: float = 0.0):
    """Heading level (1-4) for a line, or 0 for body text."""
    text = ln["text"]
    if not 3 <= len(text) <= MAX_HEADING_CHARS or _PAGE_NUMBER_RE.match(text):
        return 0
    numbered = _NUMBERED_RE.match(text)
    if ln["size"] in levels and (numbered or not text.endswith((".", ","))):
        return min(numbered.group(1).count(".") + 1, 4) if numbered else levels[ln["size"]]
    if _DEEP_NUMBERED_RE.match(text) and len(text) <= 70 and not text.rstrip(":").endswith((".", ",")) and (
        text.endswith(":") or len(text.split()) <= 7
    ):
        # "3.2.1. The duration of the probation period would be 3 months and it could be" is a wrapped
        # sentence, not a heading: it runs to the right margin and the next line carries on in lower case.
        if (following and following["text"][:1].islower()) or (right and ln["x1"] >= right * 0.93 and len(text) > 45):
            return 0
        return min(text.split()[0].rstrip(".").count(".") + 1, 4)
    return 0


def _starts_item(text: str) -> bool:
    return bool(_BULLET_RE.match(text) or _ITEM_START_RE.match(text))


def _join(previous: str, line: str) -> str:
    if previous.endswith("-") and line[:1].islower():
        return previous[:-1] + line
    return f"{previous} {line}"


def _page_blocks(page, body: float, levels: dict, pitch: float):
    """(level, text) blocks for one page: level 0 is a paragraph or list item, 1-4 a heading."""
    blocks, prev, drop_cap = [], None, ""
    lines = page["lines"]
    body_right = sorted(ln["x1"] for ln in lines if ln["size"] < body * HEADING_SIZE_RATIO)
    right = body_right[int(len(body_right) * 0.9)] if body_right else 0.0
    tables = list(page.get("tables", []))

    def flush_tables(before: float) -> None:
        nonlocal prev
        while tables and tables[0][0] <= before:
            blocks.append((0, tables.pop(0)[1]))
            prev = None

    for idx, ln in enumerate(lines):
        flush_tables(ln["top"])
        text = ln["text"]
        if len(text) == 1 and text.isalpha() and ln["size"] >= body * 2:
            drop_cap = text  # a decorative first letter; it belongs to the next line ("T" + "he two men")
            prev = ln
            continue
        if drop_cap:
            text, drop_cap = drop_cap + text, ""
        following = lines[idx + 1] if idx + 1 < len(lines) else None
        level = _classify({**ln, "text": text}, body, levels, following, right)
        if level:
            last = blocks[-1] if blocks else None
            # "1." in a large font often sits on its own line just above "INTRODUCTION".
            if last and last[0] == 0 and _LONE_NUMBER_RE.match(last[1]) and prev and ln["top"] - prev["top"] < body * 2.5:
                blocks[-1] = (level, f"{last[1]} {text}")
            elif last and last[0] == level and prev and not _NUMBERED_RE.match(text) and ln["top"] - prev["top"] < ln["size"] * 1.8:
                blocks[-1] = (level, f"{last[1]} {text}")  # a heading wrapped onto a second line
            else:
                blocks.append((level, text))
        elif _LONE_NUMBER_RE.match(text) and ln["size"] >= body * HEADING_SIZE_RATIO:
            blocks.append((0, text))
        else:
            continues = (
                bool(blocks) and blocks[-1][0] == 0 and text[:1].islower() and not _starts_item(text)
                and not _TERMINAL_RE.search(blocks[-1][1]) and "\n" not in blocks[-1][1]
            )
            new_para = not continues and (
                prev is None
                or not blocks
                or blocks[-1][0] != 0
                or blocks[-1][1].startswith("- ") and "\n" in blocks[-1][1]  # right after a table
                or ln["top"] - prev["top"] > pitch * 1.45
                or ln["x0"] - prev["x0"] > body * 0.8  # first-line indent
                or _starts_item(text)
            )
            text = _BULLET_RE.sub("- ", text)
            if new_para:
                blocks.append((0, text))
            else:
                blocks[-1] = (0, _join(blocks[-1][1], text))
        prev = ln
    flush_tables(float("inf"))
    return blocks


def _line_pitch(pages, body: float) -> float:
    gaps = [
        b["top"] - a["top"]
        for page in pages
        for a, b in zip(page["lines"], page["lines"][1:])
        if a["size"] == b["size"] and 0 < b["top"] - a["top"] < body * 3
    ]
    return statistics.median(gaps) if gaps else body * 1.3


def pdf_to_markdown(path: Path) -> str:
    try:
        pdf = pdfplumber.open(str(path))
    except Exception as exc:  # corrupt, encrypted, not a PDF
        raise PdfError(f"Could not open the PDF: {exc}") from exc
    with pdf:
        pages = _read_lines(pdf)

    total_chars = sum(len(ln["text"]) for page in pages for ln in page["lines"])
    if total_chars < 20 * max(len(pages), 1):
        raise PdfError("No readable text found. This looks like a scanned PDF; OCR is not supported.")

    body = _body_size(pages)
    _strip_running_text(pages, body)
    for page in pages:
        if _is_toc_page(page["lines"]):
            page["lines"] = []
    levels = _heading_levels(pages, body)
    pitch = _line_pitch(pages, body)

    blocks = []  # (page number, level, text)
    for page in pages:
        for level, text in _page_blocks(page, body, levels, pitch):
            # A paragraph that runs over the page break continues on the next page.
            if (
                level == 0
                and blocks
                and blocks[-1][1] == 0
                and blocks[-1][0] != page["number"]
                and not _TERMINAL_RE.search(blocks[-1][2])
                and text[:1].islower()
                and not _starts_item(text)
                and not blocks[-1][2].startswith("- ")
            ):
                blocks[-1] = (blocks[-1][0], 0, _join(blocks[-1][2], text))
            else:
                blocks.append((page["number"], level, text))

    title = _title(pages, body) or Path(path).stem
    out = [f"# {title}"]
    headings = [(level, text) for _, level, text in blocks if level]
    outline = _outline_markdown(headings)
    last_page = 0
    if outline:
        out.append(PAGE_MARK.format(blocks[0][0] if blocks else 1))
        out.append(outline)
        last_page = blocks[0][0] if blocks else 1
    for number, level, text in blocks:
        if number != last_page:
            out.append(PAGE_MARK.format(number))
            last_page = number
        out.append(f"{'#' * (level + 1)} {text}" if level else text)
    return "\n\n".join(out)


def _title(pages, body: float) -> str:
    """The biggest line on the first two pages, if it stands out; otherwise the caller uses the file name."""
    candidates = [ln for page in pages[:2] for ln in page["lines"] if len(ln["text"]) <= 100]
    if not candidates:
        return ""
    biggest = max(candidates, key=lambda ln: ln["size"])
    if biggest["size"] < body * 1.4:
        return ""
    # Titles often wrap: join consecutive lines of the same size.
    same = [ln["text"] for ln in candidates if ln["size"] == biggest["size"]][:3]
    return " ".join(same)


def _outline_markdown(headings) -> str:
    """Level-1 headings, each with its level-2 children, as a "Contents" section."""
    top = [(i, text) for i, (level, text) in enumerate(headings) if level == 1]
    if len(top) < 3:
        return ""
    lines = ["## Contents"]
    for n, (i, text) in enumerate(top):
        end = top[n + 1][0] if n + 1 < len(top) else len(headings)
        children = [t for level, t in headings[i + 1 : end] if level == 2 and t[:1].isdigit()]
        lines.append(f"- {text}" + (f": {'; '.join(children[:12])}" if children else ""))
    return "\n".join(lines)
