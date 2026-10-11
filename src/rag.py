import ollama

from . import config
from .vectorstore import embed, get_collection

NO_MATCH_PROMPT = (
    "You are a friendly assistant for a document Q&A tool. The user's message didn't match "
    "any indexed document closely. If it's a greeting or small talk, reply warmly and briefly, "
    "then offer help with the topics below. If it's a factual question, don't answer it from "
    "general knowledge: say it isn't covered in the documents and suggest related things you can help with.\n\n"
    "Indexed topics (documents): {topics}"
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


def list_topics() -> str:
    sources = {m["source"] for m in get_collection().get(include=["metadatas"])["metadatas"]}
    return ", ".join(sorted(s.rsplit(".", 1)[0].replace("_", " ") for s in sources))


def build_prompt(question: str, hits: list) -> str:
    context = "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)
    return f"Context:\n{context}\n\nQuestion: {question}"


def ask(question: str, top_k: int = config.TOP_K, stream: bool = True, on_token=None):
    hits = [h for h in retrieve(question, top_k) if 1 - h["distance"] >= config.RELEVANCE_THRESHOLD]
    if hits:
        messages = [{"role": "user", "content": build_prompt(question, hits)}]
    else:
        messages = [
            {"role": "system", "content": NO_MATCH_PROMPT.format(topics=list_topics())},
            {"role": "user", "content": question},
        ]

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
