"""Settings an admin can change while the app runs, stored in the database over config.py defaults.

Everything here is read from `config` at the moment it is used, so applying a change is just
setting the attribute on the config module. Index-shaping values (embedding model, chunk size)
are deliberately not listed: changing them needs a rebuild of the index.
"""
from dataclasses import dataclass

import ollama
from sqlalchemy import select

from . import config
from .db import AppSetting, session_scope


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    help: str
    kind: str  # "float" | "int" | "bool" | "model"
    low: float = 0
    high: float = 0
    step: float = 1


SPEC = [
    Setting("LLM_MODEL", "Chat model", "Ollama model that writes the answers (and splits follow-up questions).", "model"),
    Setting("LLM_TEMPERATURE", "Temperature", "Lower sticks closer to the documents; higher is more varied.", "float", 0, 1.5, 0.05),
    Setting("RERANK_ENABLED", "Re-rank with cross-encoder", "A second model reads question and passage together to judge relevance. Turn off to rank by embedding score only.", "bool"),
    Setting("RERANK_THRESHOLD", "Relevance cut-off (re-ranker)", "A passage must score at least this to count. Below 0 means it does not answer the question. Higher refuses more questions; lower lets weaker matches through.", "float", -10, 10, 0.5),
    Setting("RERANK_MARGIN", "Re-ranker margin", "Drop passages scoring this far below the best match for the same question.", "float", 1, 20, 0.5),
    Setting("RELEVANCE_THRESHOLD", "Embedding relevance threshold", "Minimum embedding similarity: the cut-off when the re-ranker is off, and the agreement a borderline re-ranker score needs.", "float", 0.3, 0.95, 0.01),
    Setting("RELATIVE_SCORE_MARGIN", "Embedding score margin", "Only used when the re-ranker is off: drop passages this far below the best match.", "float", 0, 0.4, 0.01),
    Setting("NEIGHBOR_CHUNKS", "Neighbouring passages", "Passages right before/after each match that are added so it is not cut off mid-thought.", "int", 0, 3),
    Setting("RELATED_CHUNKS", "Linked passages", "Extra passages tied to the matches by a shared name or a 'see section X' reference.", "int", 0, 6),
    Setting("MAX_CONTEXT_CHARS", "Context budget (characters)", "Total passage text sent to the model. About 4 characters per token; must fit the context window.", "int", 4000, 40000, 1000),
    Setting("TOP_K", "Passages per question", "How many passages to consider for a single question.", "int", 1, 20),
    Setting("TOP_K_PER_SUBQUESTION", "Passages per sub-question", "Used when one message holds several questions.", "int", 1, 10),
    Setting("MAX_CONTEXT_CHUNKS", "Max passages in prompt", "Hard cap on passages sent to the model.", "int", 1, 20),
    Setting("KEYWORD_WEIGHT", "Keyword weight", "How much exact-word matches count against meaning-based matches.", "float", 0, 5, 0.1),
    Setting("LLM_MAX_ANSWER_TOKENS", "Max answer length (tokens)", "Longest answer the model may write.", "int", 128, 4096, 64),
    Setting("LLM_NUM_CTX", "Context window (tokens)", "Prompt plus answer must fit. Larger uses more memory.", "int", 2048, 32768, 1024),
    Setting("CHAT_HISTORY_TURNS", "Follow-up memory (turns)", "Earlier question/answer pairs used to resolve follow-ups.", "int", 0, 10),
]
_BY_KEY = {s.key: s for s in SPEC}
DEFAULTS = {s.key: getattr(config, s.key) for s in SPEC}  # captured before any override is applied


class SettingError(ValueError):
    """A value the admin can fix (out of range, unknown model)."""


def installed_models() -> list[str]:
    """Chat-capable models in Ollama (embedding models are left out)."""
    try:
        names = [m.model for m in ollama.list().models]
    except Exception:
        return [config.LLM_MODEL]
    return [n for n in names if "embed" not in n] or [config.LLM_MODEL]


def _coerce(spec: Setting, raw):
    if spec.kind == "model":
        if not isinstance(raw, str) or raw not in installed_models():
            raise SettingError(f"{spec.label}: '{raw}' is not installed in Ollama.")
        return raw
    if spec.kind == "bool":
        if not isinstance(raw, bool):
            raise SettingError(f"{spec.label} must be on or off.")
        return raw
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SettingError(f"{spec.label} must be a number.")
    value = int(raw) if spec.kind == "int" else float(raw)
    if not spec.low <= value <= spec.high:
        raise SettingError(f"{spec.label} must be between {spec.low:g} and {spec.high:g}.")
    return value


def load() -> None:
    """Apply stored overrides to config; call once at startup."""
    with session_scope() as db:
        rows = db.scalars(select(AppSetting)).all()
    for row in rows:
        spec = _BY_KEY.get(row.key)
        if spec:
            try:
                setattr(config, row.key, _coerce(spec, row.value))
            except SettingError:
                pass  # a stale value (e.g. a model since removed) falls back to the default


def current() -> list[dict]:
    models = installed_models()
    out = []
    for s in SPEC:
        value = getattr(config, s.key)
        item = {
            "key": s.key, "label": s.label, "help": s.help, "kind": s.kind, "value": value,
            "default": DEFAULTS[s.key], "changed": value != DEFAULTS[s.key],
        }
        if s.kind == "model":
            item["options"] = models if value in models else [value, *models]
        elif s.kind != "bool":
            item.update(min=s.low, max=s.high, step=s.step)
        out.append(item)
    return out


def update(values: dict) -> None:
    """Validate everything first, then store and apply (all or nothing)."""
    checked = {}
    for key, raw in values.items():
        if key not in _BY_KEY:
            raise SettingError(f"Unknown setting: {key}")
        checked[key] = _coerce(_BY_KEY[key], raw)
    with session_scope() as db:
        for key, value in checked.items():
            if value == DEFAULTS[key]:
                row = db.get(AppSetting, key)
                if row:
                    db.delete(row)
            else:
                db.merge(AppSetting(key=key, value=value))
    for key, value in checked.items():
        setattr(config, key, value)


def reset(keys: list[str] | None = None) -> None:
    update({k: DEFAULTS[k] for k in (keys or DEFAULTS)})
