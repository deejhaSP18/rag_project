# Local RAG with Ollama

A fully local Retrieval-Augmented Generation (RAG) system. Ask questions about
your own documents, answered by a local SLM running through Ollama — no data
ever leaves your machine.

## How it works

1. Documents in `data/` (`.txt`, `.md`, `.pdf`) are split into overlapping chunks.
2. Each chunk is embedded using the `nomic-embed-text` Ollama model and stored
   in a local ChromaDB vector store (`storage/`).
3. At query time, your question is embedded and matched against the stored
   chunks (semantic search) to find the most relevant context.
4. The retrieved chunks are passed to the LLM (`qwen3:8b` or `phi3.5`, configurable)
   as context, so answers are grounded in your data rather than the model's
   general knowledge.

No fine-tuning or weight updates happen — this is retrieval, not training. See
`src/config.py` to change models, chunk size, or how many chunks are retrieved.

## Setup

```powershell
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
ollama pull nomic-embed-text   # embedding model
ollama pull qwen3:8b           # or any other chat model you have
```

## Usage

Add your `.txt` / `.md` / `.pdf` files to `data/`, then:

```powershell
# Index the documents
.\venv\Scripts\python.exe -m src.cli ingest

# Ask a one-off question
.\venv\Scripts\python.exe -m src.cli ask "What is this document about?"

# Or start an interactive chat
.\venv\Scripts\python.exe -m src.cli chat
```

Re-run `ingest` any time you add or change files in `data/` — already-indexed
chunks are skipped, only new ones are embedded.

## Project structure

```
data/           # put your source documents here
storage/        # persistent ChromaDB vector store (auto-created)
src/
  config.py     # models, chunk size, top-k
  loader.py     # file loading + chunking
  vectorstore.py# ChromaDB collection + embedding calls
  ingest.py     # indexing pipeline
  rag.py        # retrieval + prompt building + LLM call
  cli.py        # command-line interface (rich-formatted)
```

## Configuration

Edit `src/config.py`:
- `LLM_MODEL` — which Ollama chat model answers questions
- `EMBED_MODEL` — which Ollama model creates embeddings
- `CHUNK_SIZE` / `CHUNK_OVERLAP` — in words, controls how documents are split
- `TOP_K` — how many chunks are retrieved per question
