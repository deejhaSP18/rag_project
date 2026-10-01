# About This Project

This is a local Retrieval-Augmented Generation (RAG) project built with Ollama.

It uses the `qwen3:8b` model for generating answers and `nomic-embed-text` for
turning text into embeddings. Documents are chunked, embedded, and stored in a
local ChromaDB vector store under the `storage/` folder.

To ask a question, the system embeds the question, retrieves the most relevant
chunks from the vector store, and passes them as context to the language model
so it can generate a grounded answer.

You can add your own `.txt`, `.md`, or `.pdf` files to the `data/` folder and
re-run the ingest command to index them.
