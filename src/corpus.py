"""In-memory search structures built from the vector store.

The vector store holds the chunks; everything here is derived from it and rebuilt when it changes:
  * BM25 over every chunk (independent of the embedding search, so exact names and codes are found
    even when the embedding misses them),
  * an index of named things (identifiers, acronyms, capitalised names) and which chunks mention them,
  * the document structure: which chunk follows which, and which section "see section 7.5" points to.
The last two are what let retrieval follow relationships between passages instead of only matching words.
"""
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache

try:  # Snowball stemmer ships with fastembed; without it matching is simply exact-word
    from py_rust_stemmers import SnowballStemmer

    _stemmer = SnowballStemmer("english")
except ImportError:  # pragma: no cover
    _stemmer = None

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")
_PARTS_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")  # "ClaimPrediction_v2" -> Claim, Prediction, v, 2
_STOPWORDS = set(
    "a an the is are was were be been of to in on at for and or but with by from as it "
    "this that these those what which who whom how when where why do does did can could "
    "i you my your me we our about into than then there their they them its if not no".split()
)


@lru_cache(maxsize=100_000)
def _stem(word: str) -> str:
    return _stemmer.stem_word(word) if _stemmer and word.isalpha() and len(word) > 3 else word


def tokens(text: str) -> list[str]:
    """Lowercase search terms. Compound names ("edi_db_3", "ClaimPredictionPipeline") are kept whole and
    also split into their parts, so a question can match either spelling; plain words are stemmed."""
    out = []
    for word in _WORD_RE.findall(text):
        low = word.lower()
        if low in _STOPWORDS:
            continue
        parts = [p.lower() for p in _PARTS_RE.findall(word)]
        if len(parts) > 1:
            out.append(low)
            out.extend(_stem(p) for p in parts if len(p) > 1 and p not in _STOPWORDS)
        else:
            out.append(_stem(low))
    return out


def compound_names(text: str) -> list[tuple[str, list[str]]]:
    """(whole name, stemmed parts) for each compound identifier in text: ClaimPredictionPipeline, edi_db_3."""
    out = []
    for word in _WORD_RE.findall(text):
        parts = [_stem(p.lower()) for p in _PARTS_RE.findall(word) if len(p) > 1 and p.lower() not in _STOPWORDS]
        if len(_PARTS_RE.findall(word)) > 1 and parts:
            out.append((word.lower(), parts))
    return out


# --- named things -------------------------------------------------------------------------------

_IDENT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[_.][A-Za-z0-9]+)+\b|\b[A-Za-z]+-\d+\b")
_CAMEL_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,5}[0-9]*\b")
_PHRASE_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b")
_LEADING_WORDS = {"the", "a", "an", "in", "on", "at", "if", "it", "he", "she", "we", "you", "i", "and", "but", "or",
                  "this", "that", "these", "those", "there", "then", "when", "what", "how", "why", "who", "his",
                  "her", "our", "your", "their", "my", "as", "for", "from", "with", "by", "to", "of", "is"}
_ACRONYM_SKIP = {"THE", "AND", "FOR", "NOT", "ALL", "ANY", "BUT", "ARE", "YOU", "CAN", "HAS", "NEW", "ONE", "TWO",
                 "PDF", "FAQ", "ETC", "NOTE", "WITH", "THIS", "THAT", "FROM", "WILL", "ALSO", "ONLY", "OUT", "YES"}


def extract_entities(text: str) -> set[str]:
    """Named things in a passage, lowercased: codes (EDI_DB_3, SHA-256), CamelCase names, acronyms, proper names."""
    found = set()
    for m in _IDENT_RE.findall(text):
        found.add(m.lower())
    found.update(m.lower() for m in _CAMEL_RE.findall(text))
    found.update(m.lower() for m in _ACRONYM_RE.findall(text) if m not in _ACRONYM_SKIP)
    for phrase in _PHRASE_RE.findall(text):
        words = phrase.split()
        while words and words[0].lower() in _LEADING_WORDS:
            words.pop(0)
        if len(words) >= 2:
            found.add(" ".join(words).lower())
    return found


# --- cross references ---------------------------------------------------------------------------

_XREF_RE = re.compile(r"\b(?:sections?|clauses?|points?|paragraphs?|para|policy|see|refer to|under)\s+(\d+(?:\.\d+)+)", re.IGNORECASE)
_SECTION_NO_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")


class Corpus:
    """Search structures over every stored chunk. Positions index into `ids`/`texts`/`metas`."""

    def __init__(self, ids, texts, metas):
        self.ids, self.texts, self.metas = list(ids), list(texts), list(metas)
        self.count = len(self.ids)
        self.pos = {cid: i for i, cid in enumerate(self.ids)}
        self._build_bm25()
        self.term_sets = [set(tokens(t)) for t in self.texts]
        self._build_structure()
        self._build_entities()

    # BM25 ------------------------------------------------------------------------------------

    def _build_bm25(self):
        self.postings = defaultdict(list)  # term -> [(position, term frequency)]
        self.lengths = []
        for i, text in enumerate(self.texts):
            toks = tokens(text)
            self.lengths.append(len(toks))
            for term, freq in Counter(toks).items():
                self.postings[term].append((i, freq))
        self.avg_len = sum(self.lengths) / max(self.count, 1)
        self.idf = {t: math.log(1 + (self.count - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def bm25(self, query: str, allowed: set | None = None, limit: int = 40):
        """[(position, score)] best keyword matches across the whole corpus."""
        k1, b = 1.5, 0.75
        scores = defaultdict(float)
        for term in set(tokens(query)):
            idf = self.idf.get(term)
            if not idf:
                continue
            for i, freq in self.postings[term]:
                if allowed is not None and i not in allowed:
                    continue
                norm = k1 * (1 - b + b * self.lengths[i] / max(self.avg_len, 1))
                scores[i] += idf * freq * (k1 + 1) / (freq + norm)
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]

    def names_in(self, i: int, question: str) -> bool:
        """True when chunk i contains a compound identifier the question names (in either spelling)."""
        terms = self.term_sets[i]
        return any(whole in terms or all(p in terms for p in parts) for whole, parts in compound_names(question))

    # structure -------------------------------------------------------------------------------

    def _build_structure(self):
        by_source = defaultdict(list)
        for i, meta in enumerate(self.metas):
            by_source[meta["source"]].append((meta.get("chunk_index", 0), i))
        self.by_source, self.order = {}, {}
        for source, items in by_source.items():
            positions = [i for _, i in sorted(items)]
            self.by_source[source] = positions
            for rank, i in enumerate(positions):
                self.order[i] = rank

        # "7.5" -> chunks whose section path has a heading numbered 7.5, per source
        numbered = defaultdict(set)
        for i, meta in enumerate(self.metas):
            for part in (meta.get("section") or "").split(" > "):
                m = _SECTION_NO_RE.match(part)
                if m:
                    numbered[(meta["source"], m.group(1))].add(i)
        self.xref = {}
        for i, text in enumerate(self.texts):
            targets = set()
            for number in _XREF_RE.findall(text):
                targets |= numbered.get((self.metas[i]["source"], number), set())
            targets.discard(i)
            if targets:
                self.xref[i] = targets

    def neighbours(self, i: int, span: int = 1):
        """Chunks right before/after chunk i in the same document and section (or either side of a section-less doc)."""
        source, section = self.metas[i]["source"], self.metas[i].get("section", "")
        positions, rank = self.by_source[source], self.order[i]
        out = []
        for step in range(1, span + 1):
            for r in (rank - step, rank + step):
                if 0 <= r < len(positions):
                    j = positions[r]
                    if self.metas[j].get("section", "") == section or not section:
                        out.append(j)
        return out

    # entities --------------------------------------------------------------------------------

    def _build_entities(self):
        per_chunk = [extract_entities(t.split("\n", 1)[-1]) for t in self.texts]
        df = Counter(e for ents in per_chunk for e in ents)
        max_df = max(10, int(0.04 * self.count))
        keep = {e for e, n in df.items() if 2 <= n <= max_df}
        self.ent_idf = {e: math.log(self.count / df[e]) for e in keep}
        self.ents = [ents & keep for ents in per_chunk]
        self.ent_index = defaultdict(set)
        for i, ents in enumerate(self.ents):
            for e in ents:
                self.ent_index[e].add(i)

    def query_entities(self, question: str) -> set[str]:
        """Known entities named in a question (matched against the entities found in the documents)."""
        wanted = extract_entities(question)
        lowered = question.lower()
        # also catch names typed in lower case ("edi_db_3", "rita skeeter")
        wanted |= {e for e in self.ent_index if e in lowered and len(e) > 3}
        return {e for e in wanted if e in self.ent_index}

    def related(self, seeds, query_entities, limit: int = 8):
        """Chunks linked to the seed chunks by shared rare entities or explicit cross-references.

        Returns [(position, score)] best first, excluding the seeds. The caller still checks relevance.
        """
        seed_set = set(seeds)
        scores = defaultdict(float)
        weights = {}
        for rank, i in enumerate(seeds):
            for e in self.ents[i]:
                weights[e] = max(weights.get(e, 0.0), 1.0 / (1 + rank))
        for e in query_entities:
            weights[e] = max(weights.get(e, 0.0), 1.5)
        for e, w in weights.items():
            for j in self.ent_index.get(e, ()):
                if j not in seed_set:
                    scores[j] += w * self.ent_idf[e]
        for i in seeds:
            for j in self.xref.get(i, ()):
                if j not in seed_set:
                    scores[j] += 8.0
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
