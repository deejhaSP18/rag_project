import ollama

from . import config
from .vectorstore import embed, get_collection

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions using ONLY the provided context. "
    "If the answer isn't in the context, say you don't know instead of guessing. "
    "Cite the source file name(s) you used at the end of your answer."
)

NO_CONTEXT_SYSTEM_PROMPT = (
    "You are a helpful assistant for a document Q&A tool. The user's message did not "
    "closely match anything in the indexed documents. If it's a greeting or small talk, "
    "respond briefly and naturally. Otherwise, say you don't have relevant indexed "
    "information for that and suggest they ask about the ingested documents. "
    "Do not invent an answer from unrelated context."
)


def retrieve(question: str, top_k: int = config.TOP_K):
    collection = get_collection()
    query_embedding = embed([question])[0]
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)

    hits = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        hits.append({"text": doc, "source": meta["source"], "distance": dist})
    return hits


def build_prompt(question: str, hits: list) -> str:
    context = "\n\n".join(
        f"[{h['source']}]\n{h['text']}" for h in hits
    )
    return (
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer using only the context above."
    )


def ask(question: str, top_k: int = config.TOP_K, stream: bool = True, on_token=None):
    hits = retrieve(question, top_k)
    relevant_hits = [h for h in hits if (1 - h["distance"]) >= config.RELEVANCE_THRESHOLD]

    if not relevant_hits:
        messages = [
            {"role": "system", "content": NO_CONTEXT_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        hits = []
    else:
        prompt = build_prompt(question, relevant_hits)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        hits = relevant_hits

    if stream:
        answer = ""
        for chunk in ollama.chat(model=config.LLM_MODEL, messages=messages, stream=True):
            piece = chunk["message"]["content"]
            if on_token:
                on_token(piece)
            answer += piece
        return answer, hits

    response = ollama.chat(model=config.LLM_MODEL, messages=messages)
    return response["message"]["content"], hits
