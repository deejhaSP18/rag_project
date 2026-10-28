import json
import re

import ollama

from . import config, grounding
from .retriever import build_passages, gather_context, invalidate_index, search
from .vectorstore import get_collection

retrieve = search  # name used by the CLI and the eval script

SYSTEM_PROMPT = (
    "You answer questions using ONLY the reference text provided in the user message. "
    "Rules:\n"
    "- Every fact in your answer must be stated in the reference text. Never use outside "
    "knowledge, never guess, never fill gaps, never assume.\n"
    "- If the reference text does not contain the answer, say exactly: \"I don't have "
    "information about that.\" Do not offer a guess.\n"
    "- If only part of a question is covered, answer that part and say you don't have "
    "information about the rest.\n"
    "- Answer format: start with a direct answer in a full sentence, then add more detail by "
    "stating further relevant facts from the reference text: numbers, names, conditions, "
    "exceptions, steps, reasons and examples. Never reply with only a word, a name or a number: write at least three sentences "
    "whenever the reference text has related facts (status, purpose, who or what it applies to, "
    "where it is used). "
    "Use short paragraphs, and bullet points for lists and steps.\n"
    "- Detail means more facts from the text, not commentary on it. Never interpret, infer or "
    "speculate, and never write phrases like 'this suggests', 'this indicates', 'this means', "
    "'which confirms', 'is indicated by' or 'it can be inferred'. Do not explain how you know "
    "something, and never write 'the reference text', 'the text states' or 'according to'.\n"
    "- Keep numbers, names, codes and dates exactly as written.\n"
    "- The reference text is a set of passages, each starting with a label line (document, page, section). "
    "Passages can be related (a policy and its exceptions, a step and the one before it): combine them "
    "when the question needs it. Never mention passage numbers or labels in your answer.\n"
    "- You cannot run SQL or any code, and you have no database access. Never write out "
    "made-up query results.\n"
    "- Do not mention 'the reference text', 'context' or 'documents' in your answer."
)

MULTI_QUESTION_RULE = (
    "The user asked several questions. Answer each one separately under its own short "
    "bold heading, in the order asked. If you can answer one but not another, answer the "
    "one you can and say \"I don't have information about that.\" for the other."
)

NO_MATCH_PROMPT = (
    "You are a friendly assistant for a document Q&A tool. The user's message didn't match "
    "any indexed document closely. If it's a greeting or small talk, reply warmly and briefly, "
    "then offer help with the topics below. If it's a factual question, don't answer it from "
    "general knowledge: say it isn't covered in the documents and suggest related things you can help with. "
    "You cannot run SQL or code.\n\n"
    "Indexed topics (documents): {topics}"
)

PLANNER_PROMPT = (
    "You turn a user's message into search queries for a document search engine. You never "
    "answer the question yourself.\n"
    "- If the message asks about several different things (lists, several questions, "
    "'X and also Y'), return one complete standalone question per thing, in order.\n"
    "- Carry a shared subject into each query only when the parts are clearly about the "
    "same subject. Unrelated topics stay separate and do not borrow each other's subject.\n"
    "- If the message refers to the earlier conversation (it, they, them, those, that, 'name them', "
    "'what about...'), return ONE complete standalone question with the reference replaced by "
    "what it refers to, using the conversation shown.\n"
    "- If the message is a single self-contained question, return it unchanged as one query.\n"
    "- Keep names, codes, numbers and dates exactly as written. Small talk is returned unchanged.\n"
    'Reply with JSON only: {"queries": ["...", "..."]}, at most 4 queries.'
)

# Cheap check; a match only means "ask the planner", which decides whether to split.
_MULTI_RE = re.compile(
    r"\?\s*\S.*\?"
    r"|\b(?:and|also|plus|as well as)\s+(?:what|how|who|when|where|why|which|can|could|do|does|is|are|tell me)\b"
    r"|,"
    r"|\b(?:and|&)\s+(?:the|its|their)\b",
    re.IGNORECASE | re.DOTALL,
)
_QUESTION_WORD_RE = re.compile(r"\b(?:what|when|who|where|why|which|how)\b", re.IGNORECASE)

# "select * from X", "run this query ...", "drop table X" etc.
SQL_REQUEST_RE = re.compile(
    r"\b(?:select\s+.+?\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|"
    r"drop\s+(?:table|database)|create\s+(?:table|database)|alter\s+table|truncate\s+table)\s+[\w.`\"]+"
    r"|\b(?:run|execute|exec)\s+(?:this|the|a|my)?\s*(?:sql|query|queries|statement)\b",
    re.IGNORECASE | re.DOTALL,
)

SQL_REFUSAL = (
    "I can't run SQL queries or connect to live databases, so I can't execute that. "
    "I can answer questions in plain language about the indexed documents instead."
)


# A message made only of these words is a greeting, thanks or chit-chat, not a question about the documents.
_SMALL_TALK_WORDS = set("""
hi hii hiii hello hey heya hola yo sup howdy greetings namaste good morning afternoon evening night
there team everyone all guys bro buddy friend bot assistant dear sir madam mam again
how are you doing r u going its it today whats what s up hows
thanks thank thx ty much a lot so very
ok okay cool great nice awesome fine alright sure got
bye goodbye see later cya take care
who what can do help please
""".split())
_WORD_RE = re.compile(r"[a-z]+")


def is_small_talk(message: str) -> bool:
    """Greetings, thanks and similar ("hey", "hello there", "hi, how are you?"): answered warmly, never searched.

    Without this a short "hey" counted as a follow-up, was rewritten from the chat history into the
    previous question, and got its answer again; and anything not matched exactly was refused as an
    unanswerable factual question.
    """
    words = _WORD_RE.findall(message.lower())
    return 0 < len(words) <= 8 and all(w in _SMALL_TALK_WORDS for w in words)


NOT_COVERED = (
    "I don't have information about that in the indexed documents. "
    "I can help with these topics: {topics}."
)


def _chat(**kwargs):
    return ollama.chat(model=config.LLM_MODEL, **kwargs)


def _may_have_several_questions(message: str) -> bool:
    return bool(_MULTI_RE.search(message)) or len(_QUESTION_WORD_RE.findall(message)) >= 2


def _split_questions(message: str):
    parts = [p.strip() for p in re.findall(r"[^?]+\?", message) if len(p.split()) >= 2]
    return parts or [message]


_FOLLOWUP_RE = re.compile(
    r"\b(it|its|they|them|their|those|these|that|this|he|she|him|her|one|ones|same|first|second|third|last|"
    r"more|else|also|again|above|previous|name|list)\b|^\s*(and|but|what about|how about|why|so)\b",
    re.IGNORECASE,
)


def _history_text(history) -> str:
    return "\n\n".join(
        f"User: {t['question']}\nAssistant: {' '.join(t['answer'].split())[:400]}" for t in history
    )


def _may_be_followup(message: str, history) -> bool:
    return bool(history) and (len(message.split()) <= 6 or bool(_FOLLOWUP_RE.search(message)))


_LABEL_RE = re.compile(r"^\s*(?:latest user message|user message|message|question|query)\s*[:\-]\s*", re.IGNORECASE)


def plan_queries(message: str, history=None):
    """Return standalone search queries: split multi-part messages, resolve follow-ups."""
    history = (history or [])[-config.CHAT_HISTORY_TURNS :]
    several = _may_have_several_questions(message)
    followup = _may_be_followup(message, history)
    if not several and not followup:
        return [message]
    prompt = f"Latest user message:\n{message}"
    if followup:
        prompt = f"Conversation so far:\n{_history_text(history)}\n\n{prompt}"
    try:
        response = _chat(
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": prompt},
            ],
            format="json",
            options={"temperature": 0, "num_predict": 200, "num_ctx": 4096},
        )
        queries = json.loads(response["message"]["content"]).get("queries", [])
        queries = [_LABEL_RE.sub("", q).strip() for q in queries if isinstance(q, str) and q.strip()]  # small models echo the prompt's label
        queries = [q for q in queries if q]
        if not several:  # a follow-up stays one rewritten question
            queries = queries[:1]
        if queries:
            return queries[: config.MAX_SUBQUESTIONS]
    except (json.JSONDecodeError, KeyError, AttributeError, ollama.ResponseError):
        pass
    return _split_questions(message)[: config.MAX_SUBQUESTIONS]


def list_topics() -> str:
    sources = {m["source"] for m in get_collection().get(include=["metadatas"])["metadatas"]}
    return ", ".join(sorted(s.rsplit(".", 1)[0].replace("_", " ") for s in sources))


def _label(p: dict) -> str:
    """"Employee Handbook · page 38 · 7. EMPLOYEE LEAVE POLICY > 7.8. Maternity Leave" for a passage."""
    parts = [p["source"].rsplit(".", 1)[0].replace("_", " ")]
    if p["page_start"]:
        parts.append(f"page {p['page_start']}" if p["page_end"] in (0, p["page_start"]) else f"pages {p['page_start']}-{p['page_end']}")
    if p["section"]:
        parts.append(p["section"])
    return " · ".join(parts)


def build_prompt(question: str, passages: list, queries: list | None = None) -> str:
    context = "\n\n---\n\n".join(f"Passage {p['n']} ({_label(p)})\n{p['body']}" for p in passages)
    if queries and len(queries) > 1:
        asked = "\n".join(f"{i}. {q}" for i, q in enumerate(queries, start=1))
        task = f"Answer each of these questions in detail:\n{asked}"
    else:
        task = f"Answer this question in detail, in full sentences: {queries[0] if queries else question}"
    return f"Reference text:\n\n{context}\n\n---\n\n{task}"


def answer_stream(question: str, top_k: int | None = None, history=None, documents: list[str] | None = None):
    """Yield ("sources", passages) once, then ("token", text) pieces of the answer, then ("grounding", report)."""
    # SQL is never sent to the model: it can't run it and tends to invent results.
    if SQL_REQUEST_RE.search(question):
        yield "sources", []
        yield "token", SQL_REFUSAL
        return

    # Greetings and thanks never touch the documents. Without this, a short "hey" counted as a
    # follow-up, was rewritten from the chat history into the previous question, and got its answer again.
    small_talk = is_small_talk(question)
    queries = [question] if small_talk else plan_queries(question, history)
    hits = [] if small_talk else gather_context(queries, top_k, documents)
    passages = build_passages(hits, queries)
    if passages:
        system = SYSTEM_PROMPT + (f"\n\n{MULTI_QUESTION_RULE}" if len(queries) > 1 else "")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": build_prompt(question, passages, queries)},
        ]
    elif not small_talk:
        # Never let the model answer a factual question without supporting text.
        yield "sources", []
        yield "token", NOT_COVERED.format(topics=list_topics())
        return
    else:
        messages = [
            {"role": "system", "content": NO_MATCH_PROMPT.format(topics=list_topics())},
            {"role": "user", "content": question},
        ]

    options = {
        "num_ctx": config.LLM_NUM_CTX,
        "num_predict": config.LLM_MAX_ANSWER_TOKENS,
        "temperature": config.LLM_TEMPERATURE,
    }
    yield "sources", passages
    answer = []
    for chunk in _chat(messages=messages, stream=True, options=options):
        piece = chunk["message"]["content"]
        if piece:
            answer.append(piece)
            yield "token", piece
    if passages:
        yield "grounding", grounding.check("".join(answer), passages)


def ask(question: str, top_k: int | None = None, stream: bool = True, on_token=None):
    """Blocking helper used by the CLI and eval script. Returns (answer, hits)."""
    answer, hits = "", []
    for kind, value in answer_stream(question, top_k):
        if kind == "sources":
            hits = value
        elif kind == "token":
            if on_token:
                on_token(value)
            answer += value
    return answer, hits
