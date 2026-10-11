import ollama

from . import config
from .vectorstore import embed, get_collection

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
    context = "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)
    return f"Context:\n{context}\n\nQuestion: {question}"


def ask(question: str, top_k: int = config.TOP_K, stream: bool = True, on_token=None):
    hits = retrieve(question, top_k)
    messages = [{"role": "user", "content": build_prompt(question, hits)}]

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
