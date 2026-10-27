"""Cheap, deterministic checks on an answer, done in code because a small model cannot be trusted to do them.

* Unsupported specifics: a plausible-looking number, code or name that is not in the passages it was given
  is the typical slip of a small model. Every figure and identifier in the answer should appear in them.
  This cannot prove an answer right, but a miss is a reliable sign to double-check it.
* Used passages: which passages the answer actually draws on, by shared wording, so the UI can tell the
  passages behind the answer from the ones that were only retrieved.
"""
import re

from .corpus import _CAMEL_RE, _IDENT_RE, tokens

_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SHARED_TERMS = 3


def _numbers(text: str):
    for m in _NUMBER_RE.findall(text):
        value = m.replace(",", "").rstrip(".")
        if len(value.replace(".", "")) >= 2 or "." in value:  # a lone digit is usually a count the model wrote itself
            yield value


def _used(answer: str, passages: list[dict]) -> list[int]:
    """Numbers of the passages that best support at least one sentence of the answer."""
    terms = {p["n"]: set(tokens(p["body"])) for p in passages}
    used = set()
    for sentence in _SENTENCE_RE.split(answer):
        words = {t for t in tokens(sentence) if len(t) >= 4}
        if len(words) < MIN_SHARED_TERMS:
            continue
        best, shared = max(((n, len(words & t)) for n, t in terms.items()), key=lambda kv: kv[1])
        if shared >= MIN_SHARED_TERMS:
            used.add(best)
    return sorted(used)


def check(answer: str, passages: list[dict]) -> dict:
    """{"ok": bool, "unsupported": [...], "used": [passage numbers]} for an answer given its numbered passages."""
    source = " ".join(p["text"] for p in passages).lower()
    source_plain = source.replace(",", "")
    prose = _LIST_MARKER_RE.sub("", answer)
    unsupported = []
    for number in _numbers(prose):
        if number not in source_plain and number not in unsupported:
            unsupported.append(number)
    for code in _IDENT_RE.findall(prose) + _CAMEL_RE.findall(prose):
        if code.lower() not in source and code not in unsupported:
            unsupported.append(code)
    return {"ok": not unsupported, "unsupported": unsupported[:8], "used": _used(answer, passages)}
