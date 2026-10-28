# Local RAG: private Q&A over your documents

Ask questions about your own documents (`.md`, `.txt`, `.pdf`) in a chat UI. Answers are written by a
small model running locally through [Ollama](https://ollama.com), so nothing leaves your machine.
No model is trained or fine-tuned: documents are indexed, and the best passages are handed to the
model together with the question.

- **Chat** with streamed answers, saved history, follow-up memory, several questions in one message,
  and a side panel that shows the exact source passage behind an answer.
- **Admin panel** (`/#/admin`): upload or delete documents (indexing starts automatically), re-index,
  and change the model and retrieval settings live.
- **Accounts**: signed-in users keep their own chats; visitors without an account get a private guest session.
- **Guardrails in code**: no answer without supporting text, no SQL execution, a check that numbers
  and names in an answer appear in the sources.

## Run it with Docker (recommended for the team)

You need Docker with at least **8 GB of memory** available to it.

```bash
cp .env.example .env        # set RAG_ADMIN_PASSWORD in .env
docker compose up --build
```

Open <http://localhost:8000>. The first start downloads the models (about 3.5 GB) into a volume,
so it takes a few minutes; later starts are quick. The admin panel is at <http://localhost:8000/#/admin>.

**Faster on a Mac:** Ollama inside Docker cannot use the Mac GPU. Run Ollama natively instead
(`ollama pull phi4-mini:latest && ollama pull nomic-embed-text`) and start only the app:

```bash
docker compose -f docker-compose.host-ollama.yml up --build
```

**Documents.** Upload them in the admin panel, or copy a folder in and click **Rebuild index**:

```bash
docker compose cp ./my-docs/. app:/app/data/
docker compose exec -u root app chown -R rag:rag /app/data   # so the app can replace or delete them later
```

If the library is empty on first start and `/app/data` already holds files, they are indexed automatically.

Useful commands:

```bash
docker compose logs -f app                                   # follow the app log
docker compose exec app python -m src.cli create-admin bob   # add an admin
docker compose exec app python -m scripts.eval               # retrieval quality check
docker compose down                                          # stop (keeps documents, index, accounts, models)
docker compose down -v                                       # stop and delete all of that
```

Data lives in three named volumes: `rag-data` (documents), `rag-storage` (index, accounts, chats) and
`ollama-models`.

## Run it without Docker

Needs Python 3.10+, Node 18+ and Ollama.

```bash
ollama pull phi4-mini:latest
ollama pull nomic-embed-text

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
(cd frontend && npm install && npm run build)

python -m src.cli create-admin <username>     # prompts for a password
python -m src.cli serve                       # http://localhost:8000
```

For frontend development with hot reload, also run `cd frontend && npm run dev` and open
<http://localhost:5173> (it proxies `/api` to port 8000).

Command line: `python -m src.cli ingest | ask "<question>" | chat`.

## Configuration

Defaults live in `src/config.py`. Models can be set with the environment variables `RAG_LLM_MODEL`
and `RAG_EMBED_MODEL`. Most retrieval settings (model, temperature, relevance cut-off, re-ranking,
context size) can be changed while the app runs from **Admin → Model & retrieval**. Chunk size and the
embedding model change the index, so re-index after changing them.

| Environment variable | Purpose |
|---|---|
| `OLLAMA_HOST` | Where Ollama is (default `http://localhost:11434`). |
| `RAG_ADMIN_USER`, `RAG_ADMIN_PASSWORD` | Create the first admin on start, when no account exists. |
| `RAG_LLM_MODEL`, `RAG_EMBED_MODEL` | Chat and embedding model names. |
| `RAG_AUTO_INDEX=1` | Index `data/` on start if nothing is indexed yet (set in the Docker files). |
| `RAG_MODEL_CACHE` | Where the re-ranker model is cached. |
| `DATABASE_URL` | Another SQLAlchemy database instead of `storage/chats.db`. |

## How it works, briefly

1. **Index.** PDFs are turned into structured text (headings, tables, page numbers); documents are cut
   into section-aware chunks that remember their section and page, embedded with `nomic-embed-text`,
   and stored in ChromaDB.
2. **Search.** Each question is matched by meaning (embeddings) and by exact words (BM25) across all
   chunks, then a small local cross-encoder re-ranks the candidates. Neighbouring passages and
   passages linked by a shared name or a "see section X" reference are added.
3. **Answer.** If nothing relevant is found, a fixed "not covered" reply is returned and the model is
   never called. Otherwise the passages go to the model with a strict prompt, the answer streams back,
   and a check flags figures or names that are not in the sources.

See `docs/PROJECT_GUIDE.md` (if present in your copy) for the full explanation, every setting and a demo script.

## Project layout

```
src/            Python backend: api, rag, retriever, corpus, rerank, pdfparse, loader, ingest, ...
frontend/       React + TypeScript app
scripts/eval.py Quality check: retrieval hits, off-topic refusal (add --answers for generation)
Dockerfile, docker-compose*.yml, .env.example
data/           Your documents (not committed)
storage/        Index, accounts and chats (not committed)
```

## Limits

Quality follows the documents: clear headings and complete sentences help most. A small model phrases
things less precisely than a large one. Scanned PDFs without a text layer cannot be read (no OCR).
